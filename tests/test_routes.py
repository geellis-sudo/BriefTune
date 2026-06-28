from pathlib import Path
from io import BytesIO
from unittest.mock import MagicMock, patch

from app import create_app


def test_analyze_accepts_uploaded_txt_file(tmp_path: Path):
    app = create_app({"TESTING": True, "OPINION_DATA_DIR": tmp_path / "missing"})

    with app.test_client() as client:
        response = client.post(
            "/analyze",
            data={
                "opinion_file": (
                    BytesIO(b"Opinion by Judge Jane A. Doe\n\nThe motion was granted by the court."),
                    "upload.txt",
                ),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"Jane A. Doe" in response.data


def test_analyze_extracts_text_from_uploaded_pdf(tmp_path: Path):
    app = create_app({"TESTING": True, "OPINION_DATA_DIR": tmp_path / "missing"})

    pdf_file = MagicMock()
    pdf_file.filename = "brief.pdf"
    pdf_file.stream.read.return_value = b"%PDF-1.4 fake"

    fake_page = MagicMock()
    fake_page.extract_text.return_value = (
        "Opinion by Judge Robert T. Hill\n\nThe motion was denied because the argument was unclear."
    )

    fake_reader = MagicMock()
    fake_reader.pages = [fake_page]

    with app.test_client() as client, patch("app.routes.PdfReader", return_value=fake_reader):
        response = client.post(
            "/analyze",
            data={
                "opinion_file": (BytesIO(b"%PDF-1.4 fake"), "brief.pdf"),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"Robert T. Hill" in response.data


def test_analyze_highlights_brief_language_passages(tmp_path: Path):
    app = create_app({"TESTING": True, "OPINION_DATA_DIR": tmp_path / "missing"})

    with app.test_client() as client:
        response = client.post(
            "/analyze",
            data={
                "opinion_file": (
                    BytesIO(
                        b"Opinion by Judge Elena M. Torres\n\nThe appellee's brief argued, \"The contract language was plain and unambiguous.\" The court adopted that wording."
                    ),
                    "opinion.txt",
                ),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"Brief language passages" in response.data
    assert b"The contract language was plain and unambiguous." in response.data
    assert b"Affinity Score" in response.data
    assert b"Writing Quality" in response.data


def test_analyze_uses_transcript_source_type(tmp_path: Path):
    opinions_dir = tmp_path / "opinions"
    transcripts_dir = tmp_path / "transcripts"
    opinions_dir.mkdir()
    transcripts_dir.mkdir()
    (transcripts_dir / "hearing_one.txt").write_text(
        "Opinion by Judge Elena M. Torres\n\nThe appellee's brief argued, \"The contract language was plain and unambiguous.\"",
        encoding="utf-8",
    )

    app = create_app(
        {
            "TESTING": True,
            "OPINION_DATA_DIR": opinions_dir,
            "TRANSCRIPT_DATA_DIR": transcripts_dir,
        }
    )

    with app.test_client() as client:
        response = client.post(
            "/analyze",
            data={"selected_transcript": "hearing_one"},
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"Transcript: Hearing One" in response.data
    assert b"transcript" in response.data
    assert b"Affinity Score" in response.data
    assert b"Writing Quality" in response.data
