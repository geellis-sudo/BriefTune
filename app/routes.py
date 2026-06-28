from __future__ import annotations

from io import BytesIO

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from werkzeug.datastructures import FileStorage
from pypdf import PdfReader

from .analyzer import analyze_text
from .data_loader import extract_judge_name, get_opinion_by_id
from .folder_ingest import JOB_STORE, start_folder_processing
from .privacy import anonymize_firm_text, log_audit_event, store_firm_document


bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    samples = current_app.config["OPINION_SAMPLES"]
    transcripts = current_app.config.get("TRANSCRIPT_SAMPLES", [])
    known_judges = collect_known_judge_names(samples, transcripts)
    return render_template(
        "index.html",
        samples=samples,
        transcripts=transcripts,
        known_judges=known_judges,
        selected_sample_id=samples[0].id if samples else "",
        selected_transcript_id=transcripts[0].id if transcripts else "",
        default_text=samples[0].text if samples else "",
        selected_sample=samples[0] if samples else None,
    )


@bp.post("/load-folder")
def load_folder():
    folder_path = request.form.get("folder_path", "").strip()
    folder_context = request.form.get("folder_context", "").strip()
    folder_judge_name = request.form.get("folder_judge_name", "").strip()

    if not folder_path:
        flash("Enter a local folder path to load sources from.")
        return redirect(url_for("main.index"))

    job = start_folder_processing(
        current_app.config,
        folder_path,
        folder_context,
        folder_judge_name,
        collect_known_judge_names(current_app.config["OPINION_SAMPLES"], current_app.config.get("TRANSCRIPT_SAMPLES", [])),
    )
    log_audit_event(
        current_app.config,
        "folder_batch_started",
        folder_path=folder_path,
        folder_context=folder_context or "auto",
        folder_judge_name=folder_judge_name,
        job_id=job.id,
    )
    return redirect(url_for("main.folder_status", job_id=job.id))


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
    samples = current_app.config["OPINION_SAMPLES"]
    transcripts = current_app.config.get("TRANSCRIPT_SAMPLES", [])
    selected_sample_id = request.form.get("selected_sample", "")
    selected_transcript_id = request.form.get("selected_transcript", "")
    custom_text = request.form.get("custom_text", "").strip()
    uploaded_file = request.files.get("opinion_file")
    firm_file = request.files.get("firm_file")

    sample = get_opinion_by_id(samples, selected_sample_id) if selected_sample_id else None
    transcript = get_opinion_by_id(transcripts, selected_transcript_id) if selected_transcript_id else None
    judge_name = ""
    source_type = "uploaded"
    firm_document_used = False
    if custom_text:
        source_label = "Pasted text"
        text = custom_text
        judge_name = extract_judge_name(text)
        source_type = "pasted"
    elif transcript:
        source_label = f"Transcript: {transcript.title}"
        text = transcript.text
        judge_name = transcript.judge_name or extract_judge_name(text)
        source_type = transcript.source_type
    elif uploaded_file and uploaded_file.filename:
        text, source_label = read_uploaded_text(uploaded_file)
        judge_name = extract_judge_name(text)
        if not text:
            flash("The uploaded file was empty or could not be read. Try a plain text file.")
            sample = samples[0] if samples else None
            source_label = sample.title if sample else "No sample available"
            text = sample.text if sample else ""
            judge_name = sample.judge_name if sample else ""
            source_type = sample.source_type if sample else "opinion"
    elif sample:
        source_label = sample.title
        text = sample.text
        judge_name = sample.judge_name or extract_judge_name(text)
        source_type = sample.source_type
    elif samples:
        sample = samples[0]
        source_label = sample.title
        text = sample.text
        judge_name = sample.judge_name or extract_judge_name(text)
        source_type = sample.source_type
    else:
        source_label = "No sample available"
        text = ""
        judge_name = ""
        source_type = "opinion"

    firm_document_label = ""
    if firm_file and firm_file.filename:
        firm_text, firm_document_label = read_uploaded_text(firm_file)
        if firm_text:
            firm_artifact = store_firm_document(current_app.config, firm_file.filename, firm_text)
            text = firm_artifact.anonymized_text
            source_label = f"Firm document: {firm_file.filename}"
            source_type = "firm"
            judge_name = extract_judge_name(firm_text)
            firm_document_used = True
            log_audit_event(
                current_app.config,
                "firm_upload",
                filename=firm_file.filename,
                encrypted_path=str(firm_artifact.encrypted_path),
                upload_size=firm_artifact.upload_size,
                anonymized_characters=len(firm_artifact.anonymized_text),
            )
        else:
            flash("The firm document was empty or could not be read. Try a plain text file or PDF.")

    weight_vocabulary = float(request.form.get("weight_vocabulary", 100)) / 100
    weight_framing = float(request.form.get("weight_framing", 100)) / 100
    weight_brief_refs = float(request.form.get("weight_brief_refs", 100)) / 100

    result = analyze_text(
        text,
        source_type=source_type,
        weight_vocabulary=weight_vocabulary,
        weight_framing=weight_framing,
        weight_brief_refs=weight_brief_refs,
    )
    log_audit_event(
        current_app.config,
        "analysis_run",
        source_label=source_label,
        source_type=source_type,
        firm_document_used=firm_document_used,
        selected_sample_id=selected_sample_id,
        selected_transcript_id=selected_transcript_id,
        word_count=result["word_count"],
        issue_count=len(result["issues"]),
    )
    return render_template(
        "results.html",
        samples=samples,
        transcripts=transcripts,
        selected_sample_id=sample.id if sample else selected_sample_id,
        selected_transcript_id=transcript.id if transcript else selected_transcript_id,
        source_label=source_label,
        source_text=text,
        judge_name=judge_name,
        source_type=source_type,
        result=result,
        firm_document_used=firm_document_used,
    )


def read_uploaded_text(uploaded_file: FileStorage) -> tuple[str, str]:
    filename = uploaded_file.filename or "uploaded file"
    file_bytes = uploaded_file.stream.read()

    if filename.lower().endswith(".pdf"):
        extracted_text = extract_text_from_pdf(BytesIO(file_bytes))
        return extracted_text.strip(), filename

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


def collect_known_judge_names(samples, transcripts) -> list[str]:
    known: set[str] = set()
    for sample in list(samples) + list(transcripts):
        judge_name = getattr(sample, "judge_name", "")
        if judge_name:
            known.add(judge_name)

    return sorted(known)
