from __future__ import annotations

from io import BytesIO

from flask import Blueprint, current_app, flash, render_template, request
from werkzeug.datastructures import FileStorage
from pypdf import PdfReader

from .analyzer import analyze_text
from .data_loader import extract_judge_name, get_opinion_by_id


bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    samples = current_app.config["OPINION_SAMPLES"]
    transcripts = current_app.config.get("TRANSCRIPT_SAMPLES", [])
    return render_template(
        "index.html",
        samples=samples,
        transcripts=transcripts,
        selected_sample_id=samples[0].id if samples else "",
        selected_transcript_id=transcripts[0].id if transcripts else "",
        default_text=samples[0].text if samples else "",
        selected_sample=samples[0] if samples else None,
    )


@bp.post("/analyze")
def analyze():
    samples = current_app.config["OPINION_SAMPLES"]
    transcripts = current_app.config.get("TRANSCRIPT_SAMPLES", [])
    selected_sample_id = request.form.get("selected_sample", "")
    selected_transcript_id = request.form.get("selected_transcript", "")
    custom_text = request.form.get("custom_text", "").strip()
    uploaded_file = request.files.get("opinion_file")

    sample = get_opinion_by_id(samples, selected_sample_id) if selected_sample_id else None
    transcript = get_opinion_by_id(transcripts, selected_transcript_id) if selected_transcript_id else None
    judge_name = ""
    source_type = "uploaded"
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

    result = analyze_text(text, source_type=source_type)
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
