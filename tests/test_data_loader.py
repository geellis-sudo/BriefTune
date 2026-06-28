from pathlib import Path
from unittest.mock import MagicMock, patch

from app.data_loader import DEFAULT_SAMPLES, get_opinion_by_id, load_opinions, load_transcripts


def test_load_opinions_falls_back_to_defaults_when_directory_missing(tmp_path: Path):
    samples = load_opinions(tmp_path / "missing")

    assert len(samples) == len(DEFAULT_SAMPLES)
    assert samples[0].source == "bundled"


def test_load_opinions_reads_text_files(tmp_path: Path):
    opinions_dir = tmp_path / "opinions"
    opinions_dir.mkdir()
    (opinions_dir / "sample_one.txt").write_text(
        "Opinion by Judge Jane A. Doe\n\nHello opinion text.",
        encoding="utf-8",
    )

    samples = load_opinions(opinions_dir)

    assert len(samples) == 1
    assert samples[0].id == "sample_one"
    assert samples[0].title == "Sample One"
    assert samples[0].text.startswith("Opinion by Judge Jane A. Doe")
    assert samples[0].judge_name == "Jane A. Doe"


def test_get_opinion_by_id_returns_match():
    samples = load_opinions(None)

    match = get_opinion_by_id(samples, samples[0].id)

    assert match is not None
    assert match.id == samples[0].id


def test_extract_judge_name_detects_author():
    from app.data_loader import extract_judge_name

    text = """Opinion by Judge Maria L. Garcia\n\nThe court concludes ..."""

    assert extract_judge_name(text) == "Maria L. Garcia"


def test_load_transcripts_reads_text_files(tmp_path: Path):
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    (transcripts_dir / "hearing_one.txt").write_text("Transcript text one.", encoding="utf-8")

    transcripts = load_transcripts(transcripts_dir)

    assert len(transcripts) == 1
    assert transcripts[0].source_type == "transcript"
    assert transcripts[0].text == "Transcript text one."


def test_load_transcripts_reads_pdf_files(tmp_path: Path):
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    pdf_path = transcripts_dir / "hearing_two.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    fake_page = MagicMock()
    fake_page.extract_text.return_value = "Transcript text from pdf."

    fake_reader = MagicMock()
    fake_reader.pages = [fake_page]

    with patch("app.data_loader.PdfReader", return_value=fake_reader):
        transcripts = load_transcripts(transcripts_dir)

    assert len(transcripts) == 1
    assert transcripts[0].source_type == "transcript"
    assert transcripts[0].text == "Transcript text from pdf."
