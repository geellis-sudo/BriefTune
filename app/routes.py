from __future__ import annotations

import re
from io import BytesIO

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from werkzeug.datastructures import FileStorage
from docx import Document as DocxDocument
from pypdf import PdfReader

from .ai_verification import (
    BATCH_STORE as VERIFICATION_BATCH_STORE,
    DEFAULT_COST_LIMIT_USD,
    DEFAULT_LOOP_LIMIT,
    JOB_STORE as VERIFICATION_JOB_STORE,
    start_verification,
    start_verification_batch,
)
from .analyzer import analyze_text
from .brief_candidates import (
    VALID_STATUSES,
    get_candidate,
    load_candidates,
    precedent_alignment_score,
    verified_winning_brief_texts,
    verify_candidate,
)
from .courtlistener_sync import add_tracked_judge, get_tracked_judge, load_tracked_judges, remove_tracked_judge, sync_all_judges, sync_judge
from .data_loader import extract_judge_name
from .folder_ingest import JOB_STORE, read_folder_texts
from .privacy import (
    delete_all_firm_documents,
    delete_firm_document,
    list_firm_documents,
    log_audit_event,
    store_firm_document,
)
from .style_profile import build_style_profile, load_style_profile, style_alignment_score
from .writing_coach import run_writing_coach


bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    brief_candidates = load_candidates(current_app.config)
    unverified_count = len([c for c in brief_candidates if c.status == "unverified"])
    return render_template(
        "index.html",
        tracked_judges=load_tracked_judges(current_app.config),
        brief_candidates=brief_candidates,
        unverified_candidate_count=unverified_count,
        auto_research_available=bool(current_app.config.get("ANTHROPIC_API_KEY")),
        ai_coach_available=bool(current_app.config.get("ANTHROPIC_API_KEY")),
        default_loop_limit=DEFAULT_LOOP_LIMIT,
        default_cost_limit_usd=DEFAULT_COST_LIMIT_USD,
    )


@bp.post("/courtlistener/verify/<candidate_id>")
def courtlistener_verify_candidate(candidate_id: str):
    candidate = get_candidate(current_app.config, candidate_id)
    if candidate is None:
        flash("That flagged brief mention no longer exists.")
        return redirect(url_for("main.index"))

    status = request.form.get("verify_status", "").strip()
    brief_text = request.form.get("verify_brief_text", "").strip()
    notes = request.form.get("verify_notes", "").strip()

    if status not in VALID_STATUSES:
        flash("Choose a valid verification status.")
        return redirect(url_for("main.index"))

    updated = verify_candidate(current_app.config, candidate_id, status, brief_text=brief_text, notes=notes)
    log_audit_event(
        current_app.config,
        "brief_candidate_verified",
        candidate_id=candidate_id,
        judge_name=candidate.judge_name,
        case_name=candidate.case_name,
        status=status,
        brief_text_attached=bool(brief_text),
    )
    if updated:
        flash(f"Marked {updated.case_name} as {status.replace('_', ' ')}.")
    return redirect(url_for("main.index"))


@bp.post("/courtlistener/auto-verify/<candidate_id>")
def courtlistener_auto_verify(candidate_id: str):
    candidate = get_candidate(current_app.config, candidate_id)
    if candidate is None:
        flash("That flagged brief mention no longer exists.")
        return redirect(url_for("main.index"))

    if not current_app.config.get("ANTHROPIC_API_KEY"):
        flash("Auto-Research needs an ANTHROPIC_API_KEY set in .env first.")
        return redirect(url_for("main.index"))

    try:
        loop_limit = int(request.form.get("loop_limit", DEFAULT_LOOP_LIMIT))
    except ValueError:
        loop_limit = DEFAULT_LOOP_LIMIT

    try:
        cost_limit_usd = float(request.form.get("cost_limit_usd", DEFAULT_COST_LIMIT_USD))
    except ValueError:
        cost_limit_usd = DEFAULT_COST_LIMIT_USD

    job = start_verification(current_app.config, candidate_id, loop_limit=loop_limit, cost_limit_usd=cost_limit_usd)
    log_audit_event(
        current_app.config,
        "auto_verification_started",
        candidate_id=candidate_id,
        judge_name=candidate.judge_name,
        case_name=candidate.case_name,
        job_id=job.id,
        loop_limit=job.loop_limit,
        cost_limit_usd=job.cost_limit_usd,
    )
    return redirect(url_for("main.auto_verify_status", job_id=job.id))


@bp.get("/auto-verify-status/<job_id>")
def auto_verify_status(job_id: str):
    job = VERIFICATION_JOB_STORE.get(job_id)
    if not job:
        flash("That Auto-Research run is no longer available.")
        return redirect(url_for("main.index"))

    candidate = get_candidate(current_app.config, job.candidate_id) if job.status == "done" else None

    if job.status in {"done", "error"} and not job.audit_logged:
        job.audit_logged = True
        log_audit_event(
            current_app.config,
            "auto_verification_finished",
            candidate_id=job.candidate_id,
            outcome=job.outcome,
            stopped_reason=job.stopped_reason,
            steps_used=job.steps_used,
            cost_spent_usd=job.cost_spent_usd,
            candidate_status_applied=job.candidate_status_applied,
            error=job.error,
        )

    return render_template(
        "auto_verify_status.html",
        job=job,
        candidate=candidate,
        refresh_interval=2 if job.status in {"queued", "running"} else None,
    )


@bp.post("/courtlistener/auto-verify-all")
def courtlistener_auto_verify_all():
    if not current_app.config.get("ANTHROPIC_API_KEY"):
        flash("Auto-Research needs an ANTHROPIC_API_KEY set in .env first.")
        return redirect(url_for("main.index"))

    unverified = [c for c in load_candidates(current_app.config) if c.status == "unverified"]
    if not unverified:
        flash("No unverified flagged brief mentions to research right now.")
        return redirect(url_for("main.index"))

    try:
        loop_limit = int(request.form.get("loop_limit", DEFAULT_LOOP_LIMIT))
    except ValueError:
        loop_limit = DEFAULT_LOOP_LIMIT

    try:
        cost_limit_usd = float(request.form.get("cost_limit_usd", DEFAULT_COST_LIMIT_USD))
    except ValueError:
        cost_limit_usd = DEFAULT_COST_LIMIT_USD

    batch = start_verification_batch(
        current_app.config,
        [c.id for c in unverified],
        loop_limit=loop_limit,
        cost_limit_usd=cost_limit_usd,
    )
    log_audit_event(
        current_app.config,
        "auto_verification_batch_started",
        batch_id=batch.id,
        candidate_count=len(unverified),
        loop_limit=loop_limit,
        cost_limit_usd=cost_limit_usd,
    )
    return redirect(url_for("main.auto_verify_batch_status", batch_id=batch.id))


@bp.get("/auto-verify-status/batch/<batch_id>")
def auto_verify_batch_status(batch_id: str):
    batch = VERIFICATION_BATCH_STORE.get(batch_id)
    if not batch:
        flash("That Auto-Research batch is no longer available.")
        return redirect(url_for("main.index"))

    jobs = [VERIFICATION_JOB_STORE.get(job_id) for job_id in batch.job_ids]
    jobs = [job for job in jobs if job is not None]
    candidates_by_id = {c.id: c for c in load_candidates(current_app.config)}

    still_running = any(job.status in {"queued", "running"} for job in jobs)

    for job in jobs:
        if job.status in {"done", "error"} and not job.audit_logged:
            job.audit_logged = True
            log_audit_event(
                current_app.config,
                "auto_verification_finished",
                candidate_id=job.candidate_id,
                outcome=job.outcome,
                stopped_reason=job.stopped_reason,
                steps_used=job.steps_used,
                cost_spent_usd=job.cost_spent_usd,
                candidate_status_applied=job.candidate_status_applied,
                error=job.error,
            )

    return render_template(
        "auto_verify_batch_status.html",
        batch=batch,
        jobs=jobs,
        candidates_by_id=candidates_by_id,
        refresh_interval=2 if still_running else None,
    )


@bp.post("/courtlistener/track")
def courtlistener_track():
    judge_name = request.form.get("courtlistener_judge_name", "").strip()
    court = request.form.get("courtlistener_court", "").strip()

    if not judge_name:
        flash("Enter a judge name to track.")
        return redirect(url_for("main.index"))

    judge = add_tracked_judge(current_app.config, judge_name, court)
    log_audit_event(
        current_app.config,
        "courtlistener_judge_tracked",
        judge_id=judge.id,
        judge_name=judge.name,
        court=judge.court,
    )
    flash(f"Now tracking {judge.name} for new CourtListener opinions.")
    return redirect(url_for("main.index"))


@bp.post("/courtlistener/untrack/<judge_id>")
def courtlistener_untrack(judge_id: str):
    remove_tracked_judge(current_app.config, judge_id)
    log_audit_event(current_app.config, "courtlistener_judge_untracked", judge_id=judge_id)
    flash("Stopped tracking that judge.")
    return redirect(url_for("main.index"))


@bp.post("/courtlistener/sync/<judge_id>")
def courtlistener_sync_one(judge_id: str):
    judge = get_tracked_judge(current_app.config, judge_id)
    if judge is None:
        flash("That tracked judge no longer exists.")
        return redirect(url_for("main.index"))

    result = sync_judge(current_app.config, judge_id)
    log_audit_event(
        current_app.config,
        "courtlistener_sync",
        judge_id=result.judge_id,
        judge_name=result.judge_name,
        opinions_found=result.opinions_found,
        oral_arguments_found=result.oral_arguments_found,
        files_written=result.files_written,
        skipped_existing=result.skipped_existing,
        errors=result.errors,
    )

    if result.errors:
        flash(
            f"Sync for {result.judge_name} hit {len(result.errors)} error(s) and stopped advancing "
            f"its sync point, so the next \"Sync now\" will pick up right where this one left off "
            f"instead of skipping anything: {'; '.join(result.errors)}"
        )

    if result.job_id:
        return redirect(url_for("main.folder_status", job_id=result.job_id))

    if result.skipped_existing:
        flash(
            f"No new opinions or oral arguments for {result.judge_name} — "
            f"{result.skipped_existing} were already on disk from a previous sync."
        )
    else:
        flash(f"No new opinions or oral arguments found for {result.judge_name}.")
    return redirect(url_for("main.index"))


@bp.post("/courtlistener/sync-all")
def courtlistener_sync_all_route():
    results = sync_all_judges(current_app.config)
    if not results:
        flash("No tracked judges yet. Add one below first.")
        return redirect(url_for("main.index"))

    total_files = sum(result.files_written for result in results)
    total_skipped = sum(result.skipped_existing for result in results)
    total_errors = [error for result in results for error in result.errors]
    log_audit_event(
        current_app.config,
        "courtlistener_sync_all",
        judge_count=len(results),
        total_files_written=total_files,
        total_skipped_existing=total_skipped,
        error_count=len(total_errors),
    )

    message = f"Synced {len(results)} judge(s); {total_files} new file(s) ingested."
    if total_skipped:
        message += f" {total_skipped} already on disk (skipped)."
    if total_errors:
        message += (
            f" {len(total_errors)} error(s) — those judges' sync points weren't advanced, "
            f"so re-running will retry the same items rather than skip them."
        )
    flash(message)
    return redirect(url_for("main.index"))


@bp.get("/folder-status/<job_id>")
def folder_status(job_id: str):
    job = JOB_STORE.get(job_id)
    if not job:
        flash("That folder batch job is no longer available.")
        return redirect(url_for("main.index"))

    return render_template(
        "folder_status.html",
        job=job,
        job_done=job.status == "done",
        refresh_interval=2 if job.status in {"queued", "running"} else None,
    )


@bp.post("/analyze")
def analyze():
    draft_file = request.files.get("draft_file")

    text = ""
    source_label = ""
    judge_name = ""
    source_type = "firm"
    firm_document_used = False

    if draft_file and draft_file.filename:
        draft_text, _ = read_uploaded_text(draft_file)
        if draft_text:
            redact_terms_raw = request.form.get("redact_terms", "")
            manual_terms = [term.strip() for term in re.split(r"[,\n]", redact_terms_raw) if term.strip()]
            firm_artifact = store_firm_document(
                current_app.config, draft_file.filename, draft_text, manual_terms=manual_terms
            )
            text = firm_artifact.anonymized_text
            source_label = f"Draft brief: {draft_file.filename}"
            judge_name = extract_judge_name(draft_text)
            firm_document_used = True
            log_audit_event(
                current_app.config,
                "firm_upload",
                filename=draft_file.filename,
                encrypted_path=str(firm_artifact.encrypted_path),
                upload_size=firm_artifact.upload_size,
                anonymized_characters=len(firm_artifact.anonymized_text),
            )
        else:
            flash("The uploaded draft was empty or could not be read. Try a plain text file or PDF.")
    else:
        flash("Upload a draft brief file to run an analysis.")

    if not text:
        return redirect(url_for("main.index"))

    # These two now come from a linked pair of sliders in the UI that always sum to
    # 100 -- default (e.g. when a field is missing) is an even 50/50 split.
    weight_judge_style = float(request.form.get("weight_judge_style", 50)) / 100
    weight_precedent_brief = float(request.form.get("weight_precedent_brief", 50)) / 100

    compare_judge_id = request.form.get("compare_judge_id", "").strip()
    firm_folder_path = request.form.get("firm_folder_path", "").strip()

    compare_judge_name = ""
    judge_style_raw_bonus = 0
    judge_style_factors: list[str] = []
    judge_style_source_available = False
    precedent_raw_bonus = 0
    precedent_factors: list[str] = []
    precedent_source_available = False
    verified_texts: list[str] = []

    if compare_judge_id:
        tracked_judge = get_tracked_judge(current_app.config, compare_judge_id)
        if tracked_judge:
            compare_judge_name = tracked_judge.name
            profile = load_style_profile(current_app.config, tracked_judge.name)
            judge_style_source_available = profile is not None
            judge_style_raw_bonus, judge_style_factors = style_alignment_score(text, profile)

            verified_texts = verified_winning_brief_texts(current_app.config, tracked_judge.id)
            precedent_source_available = bool(verified_texts)
            precedent_raw_bonus, precedent_factors = precedent_alignment_score(text, verified_texts)

    folder_style_raw_bonus = 0
    folder_style_factors: list[str] = []
    folder_style_source_available = False
    folder_precedent_raw_bonus = 0
    folder_precedent_factors: list[str] = []
    folder_precedent_source_available = False
    folder_used = False
    folder_texts: list[str] = []

    if firm_folder_path:
        folder_used = True
        folder_texts = read_folder_texts(firm_folder_path)

        if not folder_texts:
            no_files_message = (
                f"No .txt/.pdf/.docx files were found at that folder path — check that "
                f"\"{firm_folder_path}\" is correct and accessible."
            )
            folder_style_factors = [no_files_message]
            folder_precedent_factors = [no_files_message]
        else:
            folder_style_source_available = True
            folder_precedent_source_available = True
            folder_profile = build_style_profile("Firm Corpus", folder_texts)
            folder_style_raw_bonus, folder_style_factors = style_alignment_score(
                text,
                folder_profile,
                unit_label="brief",
                no_profile_message="The firm folder didn't yield a usable style profile.",
            )
            folder_precedent_raw_bonus, folder_precedent_factors = precedent_alignment_score(
                text,
                folder_texts,
                source_description="in your firm's winning-briefs folder",
                empty_message="No usable briefs were found in the firm folder.",
            )

    def _run_analysis(
        style_bonus: int,
        style_factors: list[str],
        style_available: bool,
        precedent_bonus: int,
        precedent_factors_: list[str],
        precedent_available: bool,
        verified_texts_: list[str] | None = None,
        folder_texts_: list[str] | None = None,
        brief_language_source_description: str | None = None,
    ) -> dict:
        return analyze_text(
            text,
            source_type=source_type,
            judge_style_raw_bonus=style_bonus,
            judge_style_factors=style_factors,
            weight_judge_style=weight_judge_style,
            judge_style_source_available=style_available,
            precedent_raw_bonus=precedent_bonus,
            precedent_factors=precedent_factors_,
            weight_precedent_brief=weight_precedent_brief,
            precedent_source_available=precedent_available,
            verified_brief_texts=verified_texts_,
            folder_brief_texts=folder_texts_,
            brief_language_source_description=brief_language_source_description,
        )

    both_active = bool(compare_judge_name) and folder_used
    result = _run_analysis(
        judge_style_raw_bonus, judge_style_factors, judge_style_source_available,
        precedent_raw_bonus, precedent_factors, precedent_source_available,
        verified_texts_=verified_texts,
        brief_language_source_description=(
            f"briefs verified as winning before {compare_judge_name}"
            if compare_judge_name
            else None
        ),
    )
    secondary_result = None
    if both_active:
        secondary_result = _run_analysis(
            folder_style_raw_bonus, folder_style_factors, folder_style_source_available,
            folder_precedent_raw_bonus, folder_precedent_factors, folder_precedent_source_available,
            folder_texts_=folder_texts,
            brief_language_source_description="briefs in your firm's winning-briefs folder",
        )
    elif folder_used and not compare_judge_name:
        # Folder was the only comparison source active -- it IS the primary result.
        result = _run_analysis(
            folder_style_raw_bonus, folder_style_factors, folder_style_source_available,
            folder_precedent_raw_bonus, folder_precedent_factors, folder_precedent_source_available,
            folder_texts_=folder_texts,
            brief_language_source_description="briefs in your firm's winning-briefs folder",
        )

    log_audit_event(
        current_app.config,
        "analysis_run",
        source_label=source_label,
        source_type=source_type,
        firm_document_used=firm_document_used,
        word_count=result["word_count"],
        issue_count=len(result["issues"]),
        compare_judge_name=compare_judge_name,
        firm_folder_used=folder_used,
        both_comparisons_active=both_active,
    )

    ai_writing_coach = None
    if request.form.get("run_ai_coach") and current_app.config.get("ANTHROPIC_API_KEY"):
        ai_writing_coach = run_writing_coach(current_app.config, text)
        log_audit_event(
            current_app.config,
            "ai_writing_coach_run",
            source_label=source_label,
            available=ai_writing_coach.available,
            suggestion_count=len(ai_writing_coach.suggestions),
            cost_usd=ai_writing_coach.cost_usd,
            error=ai_writing_coach.error,
        )

    return render_template(
        "results.html",
        source_label=source_label,
        source_text=text,
        judge_name=judge_name,
        source_type=source_type,
        result=result,
        secondary_result=secondary_result,
        primary_label=compare_judge_name if both_active else None,
        secondary_label="Firm folder" if both_active else None,
        firm_document_used=firm_document_used,
        compare_judge_name=compare_judge_name,
        firm_folder_used=folder_used,
        ai_writing_coach=ai_writing_coach,
    )


@bp.get("/documents")
def documents():
    return render_template("documents.html", documents=list_firm_documents(current_app.config))


@bp.post("/documents/delete/<stored_name>")
def documents_delete(stored_name: str):
    if delete_firm_document(current_app.config, stored_name):
        flash("Encrypted document deleted. The deletion was recorded in the audit log.")
    else:
        flash("That document no longer exists or the name was not recognized.")
    return redirect(url_for("main.documents"))


@bp.post("/documents/delete-all")
def documents_delete_all():
    deleted = delete_all_firm_documents(current_app.config)
    log_audit_event(current_app.config, "firm_documents_delete_all", deleted_count=deleted)
    if deleted:
        flash(f"Deleted {deleted} encrypted document{'s' if deleted != 1 else ''}. Recorded in the audit log.")
    else:
        flash("No stored documents to delete.")
    return redirect(url_for("main.documents"))


def read_uploaded_text(uploaded_file: FileStorage) -> tuple[str, str]:
    filename = uploaded_file.filename or "uploaded file"
    file_bytes = uploaded_file.stream.read()

    if filename.lower().endswith(".pdf"):
        extracted_text = extract_text_from_pdf(BytesIO(file_bytes))
        return extracted_text.strip(), filename

    if filename.lower().endswith(".docx"):
        document = DocxDocument(BytesIO(file_bytes))
        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        return "\n\n".join(paragraphs).strip(), filename

    raw_text = file_bytes.decode("utf-8", errors="ignore").strip()
    return raw_text, filename


def extract_text_from_pdf(pdf_stream: BytesIO) -> str:
    reader = PdfReader(pdf_stream)
    pages: list[str] = []

    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            pages.append(page_text.strip())

    return "\n\n".join(pages)
