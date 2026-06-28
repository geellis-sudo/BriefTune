from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document

from .data_loader import OpinionSample, extract_judge_name
from .privacy import anonymize_firm_text, log_audit_event, store_firm_document


SUPPORTED_FOLDER_SUFFIXES = {".txt", ".pdf", ".docx"}


@dataclass
class FolderJob:
    id: str
    status: str = "queued"
    progress: int = 0
    total: int = 0
    message: str = "Queued"
    source_label: str = ""
    source_type: str = ""
    judge_name: str = ""
    processed_files: int = 0
    skipped_files: int = 0
    created_samples: list[OpinionSample] = field(default_factory=list)
    anonymized_texts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class FolderJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, FolderJob] = {}
        self._lock = threading.Lock()

    def create(self) -> FolderJob:
        job = FolderJob(id=uuid.uuid4().hex)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> FolderJob | None:
        with self._lock:
            return self._jobs.get(job_id)


JOB_STORE = FolderJobStore()


def start_folder_processing(
    app_config: dict[str, Any],
    folder_path: str,
    context_choice: str,
    judge_name: str,
    known_judges: list[str],
) -> FolderJob:
    job = JOB_STORE.create()
    thread = threading.Thread(
        target=_process_folder_job,
        args=(app_config, job.id, folder_path, context_choice, judge_name, known_judges),
        daemon=True,
    )
    thread.start()
    return job


def _process_folder_job(
    app_config: dict[str, Any],
    job_id: str,
    folder_path: str,
    context_choice: str,
    judge_name: str,
    known_judges: list[str],
) -> None:
    job = JOB_STORE.get(job_id)
    if not job:
        return

    folder = Path(folder_path).expanduser()
    if not folder.exists() or not folder.is_dir():
        job.status = "error"
        job.message = "Folder path was not found or is not a directory."
        return

    files = [path for path in sorted(folder.rglob("*")) if path.is_file() and path.suffix.lower() in SUPPORTED_FOLDER_SUFFIXES]
    job.total = len(files)
    job.status = "running"
    job.message = f"Processing {job.total} file(s)."

    detected_judge = judge_name.strip() or infer_judge_from_folder(folder.name, known_judges)
    if detected_judge:
        job.judge_name = detected_judge

    resolved_context = context_choice
    if not resolved_context:
        if detected_judge:
            resolved_context = "specific_judge"
        elif looks_like_firm_folder(folder.name):
            resolved_context = "firm"
        else:
            resolved_context = "mixed"

    seen_hashes = load_processed_hashes(app_config)

    for index, path in enumerate(files, start=1):
        file_bytes = path.read_bytes()
        content_hash = hashlib.sha256(file_bytes).hexdigest()
        if content_hash in seen_hashes:
            job.skipped_files += 1
            job.progress = int((index / max(job.total, 1)) * 100)
            job.message = f"Skipped duplicate: {path.name}"
            continue

        text = read_folder_document_text(path)
        if not text.strip():
            job.skipped_files += 1
            job.progress = int((index / max(job.total, 1)) * 100)
            job.message = f"Skipped empty file: {path.name}"
            continue

        source_type = "folder"
        source_label = f"{folder.name}/{path.name}"
        judge_for_file = detected_judge or extract_judge_name(text)

        if resolved_context == "firm":
            anonymized_text = anonymize_firm_text(text)
            artifact = store_firm_document(app_config, path.name, text)
            anonymized_text = artifact.anonymized_text
            text_for_index = anonymized_text
            source_type = "firm"
            source_label = f"Firm folder: {folder.name} / {path.name}"
        elif resolved_context == "specific_judge":
            text_for_index = text
            source_type = "opinion"
            source_label = f"Judge folder: {detected_judge or folder.name} / {path.name}"
        else:
            text_for_index = text
            source_type = "mixed"

        sample = OpinionSample(
            id=f"{folder.name}-{path.stem}",
            title=path.stem.replace("_", " ").replace("-", " ").title(),
            text=text_for_index,
            source=str(path),
            source_type=source_type,
            judge_name=judge_for_file,
            court=folder.name,
            year="",
            focus=resolved_context.replace("_", " ").title(),
        )
        job.created_samples.append(sample)
        if resolved_context == "firm":
            job.anonymized_texts.append(text_for_index)

        seen_hashes.add(content_hash)
        save_processed_hashes(app_config, seen_hashes)
        job.processed_files += 1
        job.progress = int((index / max(job.total, 1)) * 100)
        job.message = f"Processed {path.name}"
        log_audit_event(
            app_config,
            "folder_file_processed",
            folder_path=str(folder),
            filename=path.name,
            source_type=source_type,
            judge_name=judge_for_file,
            content_hash=content_hash,
            context=resolved_context,
        )

    job.status = "done"
    job.message = f"Completed {job.processed_files} file(s); skipped {job.skipped_files}."
    log_audit_event(
        app_config,
        "folder_batch_complete",
        folder_path=str(folder),
        processed_files=job.processed_files,
        skipped_files=job.skipped_files,
        context=resolved_context,
        judge_name=job.judge_name,
    )


def infer_judge_from_folder(folder_name: str, known_judges: list[str]) -> str:
    normalized = folder_name.replace("_", " ").replace("-", " ").strip()
    if not normalized:
        return ""

    lowered = normalized.lower()
    for known_judge in known_judges:
        if known_judge.lower() in lowered:
            return known_judge

    if "judge" in lowered or "justice" in lowered:
        return normalized.title()

    return ""


def looks_like_firm_folder(folder_name: str) -> bool:
    lowered = folder_name.lower()
    return any(term in lowered for term in ["firm", "brief", "client", "winning", "confidential"])


def read_folder_document_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        with path.open("rb") as pdf_file:
            reader = PdfReader(pdf_file)
            pages: list[str] = []
            for page in reader.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages.append(page_text.strip())
            return "\n\n".join(pages).strip()

    if suffix == ".docx":
        document = Document(str(path))
        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        return "\n\n".join(paragraphs).strip()

    return path.read_text(encoding="utf-8", errors="ignore").strip()


def load_processed_hashes(app_config: dict[str, Any]) -> set[str]:
    state_path = Path(app_config["PROCESSED_FILES_PATH"])
    if not state_path.exists():
        return set()

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()

    return set(data.get("content_hashes", []))


def save_processed_hashes(app_config: dict[str, Any], hashes: set[str]) -> None:
    state_path = Path(app_config["PROCESSED_FILES_PATH"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"content_hashes": sorted(hashes)}, indent=2), encoding="utf-8")