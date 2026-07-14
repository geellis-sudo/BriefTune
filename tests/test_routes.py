from pathlib import Path
from io import BytesIO
from unittest.mock import MagicMock, patch

from app import create_app
from app.brief_candidates import flag_brief_mentions, load_candidates, verify_candidate
from app.style_profile import build_style_profile, save_style_profile


def make_analyze_app(tmp_path: Path):
    return create_app(
        {
            "TESTING": True,
            "OPINION_DATA_DIR": tmp_path / "opinions",
            "TRANSCRIPT_DATA_DIR": tmp_path / "transcripts",
            "FIRM_CONFIDENTIAL_DIR": tmp_path / "firm_confidential",
            "FIRM_CONFIDENTIAL_KEY_PATH": tmp_path / "firm_confidential.key",
            "AUDIT_LOG_PATH": tmp_path / "audit.log",
            "TRACKED_JUDGES_PATH": tmp_path / "tracked_judges.json",
            "JUDGE_STYLE_PROFILE_DIR": tmp_path / "judge_style_profiles",
            "BRIEF_MENTION_CANDIDATES_PATH": tmp_path / "brief_mention_candidates.json",
        }
    )


def test_analyze_accepts_uploaded_draft_file(tmp_path: Path):
    app = make_analyze_app(tmp_path)

    with app.test_client() as client:
        response = client.post(
            "/analyze",
            data={
                "draft_file": (
                    BytesIO(b"Opinion by Judge Jane A. Doe\n\nThe motion was granted by the court."),
                    "upload.txt",
                ),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"Jane A. Doe" in response.data


def test_analyze_extracts_text_from_uploaded_pdf(tmp_path: Path):
    app = make_analyze_app(tmp_path)

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
                "draft_file": (BytesIO(b"%PDF-1.4 fake"), "brief.pdf"),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"Robert T. Hill" in response.data


def test_analyze_without_corpus_hides_brief_language_passages(tmp_path: Path):
    app = make_analyze_app(tmp_path)

    with app.test_client() as client:
        response = client.post(
            "/analyze",
            data={
                "draft_file": (
                    BytesIO(
                        b"Opinion by Judge Elena M. Torres\n\nThe appellee's brief argued, \"The contract language was plain and unambiguous.\" The court adopted that wording."
                    ),
                    "opinion.txt",
                ),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"Brief language passages" not in response.data
    assert b"Affinity Score" in response.data
    assert b"Writing Quality" in response.data


def test_analyze_with_verified_winning_brief_highlights_corpus_matched_passage(tmp_path: Path):
    from app.courtlistener_sync import add_tracked_judge

    app = make_analyze_app(tmp_path)
    judge = add_tracked_judge(app.config, "Judge Test", "scotus")

    opinion_text = (
        'The appellee\'s brief argued, "The contract language was plain and unambiguous." '
        "The court agreed with that phrasing."
    )
    flag_brief_mentions(app.config, judge.id, judge.name, 555, "Doe v. Roe", "2025-01-01", opinion_text)
    candidate_id = load_candidates(app.config)[0].id
    verify_candidate(
        app.config,
        candidate_id,
        "verified_winning",
        brief_text="The contract language was plain and unambiguous, and the agreement forecloses the defendant's reading.",
    )

    with app.test_client() as client:
        response = client.post(
            "/analyze",
            data={
                "draft_file": (
                    BytesIO(
                        b"Opinion by Judge Elena M. Torres\n\nThe appellee's brief argued, \"The contract language was plain and unambiguous.\" The court adopted that wording."
                    ),
                    "opinion.txt",
                ),
                "compare_judge_id": judge.id,
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"Brief language passages" in response.data
    assert b"The contract language was plain and unambiguous." in response.data
    assert b"verified as winning" in response.data


def test_analyze_handles_draft_upload_with_anonymization_and_audit_log(tmp_path: Path):
    app = make_analyze_app(tmp_path)

    with app.test_client() as client:
        response = client.post(
            "/analyze",
            data={
                "draft_file": (
                    BytesIO(
                        b"Confidential brief for Acme Corporation in Case No. 24-1234 seeking $2,500,000. "
                        b"Judge Jane Doe should review it. Contact: 555-123-4567, acme@example.com, SSN 123-45-6789."
                    ),
                    "firm_brief.txt",
                ),
                "redact_terms": "Acme Corporation",
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"Draft brief: firm_brief.txt" in response.data

    # Manually-listed client name is redacted...
    assert b"Acme Corporation" not in response.data
    assert b"[REDACTED]" in response.data

    # ...but case numbers and dollar figures are intentionally left visible.
    assert b"24-1234" in response.data
    assert b"2,500,000" in response.data

    # Structured PII is redacted automatically, whether or not it was listed.
    assert b"555-123-4567" not in response.data
    assert b"acme@example.com" not in response.data
    assert b"123-45-6789" not in response.data
    assert b"[PHONE]" in response.data
    assert b"[EMAIL]" in response.data
    assert b"[SSN]" in response.data

    encrypted_files = list((tmp_path / "firm_confidential").glob("*.enc"))
    assert encrypted_files

    audit_log = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert "firm_upload" in audit_log
    assert "analysis_run" in audit_log


AI_COACH_JSON = (
    "```json\n"
    "{\n"
    '  "overall_assessment": "Solid on the facts; the lead paragraph buries the strongest point.",\n'
    '  "suggestions": [\n'
    "    {\n"
    '      "category": "Argument structure",\n'
    '      "quote": "Judge Jane Doe should review it.",\n'
    '      "suggestion": "Lead with the standard-of-review point instead.",\n'
    '      "rationale": "Judges look for the legal hook first."\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "```"
)


def test_analyze_runs_ai_writing_coach_when_requested(tmp_path: Path):
    app = make_analyze_app(tmp_path)
    app.config["ANTHROPIC_API_KEY"] = "test-key"

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = mock_anthropic_cls.return_value
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(type="text", text=AI_COACH_JSON)],
            usage=MagicMock(input_tokens=100, output_tokens=100),
        )

        with app.test_client() as client:
            response = client.post(
                "/analyze",
                data={
                    "draft_file": (
                        BytesIO(b"Confidential brief. Judge Jane Doe should review it."),
                        "firm_brief.txt",
                    ),
                    "run_ai_coach": "1",
                },
                content_type="multipart/form-data",
            )

    assert response.status_code == 200
    assert b"AI Writing Coach" in response.data
    assert b"buries the strongest point" in response.data
    assert b"Argument structure" in response.data

    audit_log = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert "ai_writing_coach_run" in audit_log


def test_analyze_skips_ai_writing_coach_when_not_requested(tmp_path: Path):
    app = make_analyze_app(tmp_path)
    app.config["ANTHROPIC_API_KEY"] = "test-key"

    with app.test_client() as client:
        response = client.post(
            "/analyze",
            data={
                "draft_file": (
                    BytesIO(b"Confidential brief. Judge Jane Doe should review it."),
                    "firm_brief.txt",
                )
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"AI Writing Coach" not in response.data


def test_analyze_without_draft_file_redirects_to_index(tmp_path: Path):
    app = make_analyze_app(tmp_path)

    with app.test_client() as client:
        response = client.post("/analyze", data={}, content_type="multipart/form-data")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_verify_brief_candidate_records_status_and_shows_on_homepage(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "OPINION_DATA_DIR": tmp_path / "opinions",
            "TRANSCRIPT_DATA_DIR": tmp_path / "transcripts",
            "FIRM_CONFIDENTIAL_DIR": tmp_path / "firm_confidential",
            "FIRM_CONFIDENTIAL_KEY_PATH": tmp_path / "firm_confidential.key",
            "AUDIT_LOG_PATH": tmp_path / "audit.log",
            "BRIEF_MENTION_CANDIDATES_PATH": tmp_path / "brief_mention_candidates.json",
        }
    )

    opinion_text = (
        'The appellee\'s brief argued, "The contract language was plain and unambiguous." '
        "The court agreed with that phrasing."
    )
    flag_brief_mentions(app.config, "judge-1", "Judge Test", 555, "Doe v. Roe", "2025-01-01", opinion_text)
    candidate_id = load_candidates(app.config)[0].id

    with app.test_client() as client:
        homepage = client.get("/")
        assert b"Doe v. Roe" in homepage.data
        assert b"unverified" in homepage.data

        response = client.post(
            f"/courtlistener/verify/{candidate_id}",
            data={
                "verify_status": "verified_winning",
                "verify_brief_text": "The contract language was plain and unambiguous.",
                "verify_notes": "Confirmed via opinion text.",
            },
        )
        assert response.status_code == 302

    candidates = load_candidates(app.config)
    assert candidates[0].status == "verified_winning"
    assert candidates[0].brief_text == "The contract language was plain and unambiguous."


def test_auto_verify_all_runs_every_unverified_candidate(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "OPINION_DATA_DIR": tmp_path / "opinions",
            "TRANSCRIPT_DATA_DIR": tmp_path / "transcripts",
            "FIRM_CONFIDENTIAL_DIR": tmp_path / "firm_confidential",
            "FIRM_CONFIDENTIAL_KEY_PATH": tmp_path / "firm_confidential.key",
            "AUDIT_LOG_PATH": tmp_path / "audit.log",
            "BRIEF_MENTION_CANDIDATES_PATH": tmp_path / "brief_mention_candidates.json",
            "COURTLISTENER_SYNC_DIR": tmp_path / "sync",
            "ANTHROPIC_API_KEY": "test-key",
        }
    )

    opinion_text = (
        'The appellee\'s brief argued, "The contract language was plain and unambiguous." '
        "The court agreed with that phrasing."
    )
    flag_brief_mentions(app.config, "judge-1", "Judge Test", 555, "Doe v. Roe", "2025-01-01", opinion_text)
    flag_brief_mentions(app.config, "judge-1", "Judge Test", 556, "Second v. Case", "2025-02-01", opinion_text)

    sync_folder = Path(app.config["COURTLISTENER_SYNC_DIR"]) / "Judge Judge Test"
    sync_folder.mkdir(parents=True, exist_ok=True)
    (sync_folder / "doe-v-roe-555.txt").write_text(opinion_text, encoding="utf-8")
    (sync_folder / "second-v-case-556.txt").write_text(opinion_text, encoding="utf-8")

    winning_json = (
        "```json\n"
        "{\n"
        '  "outcome": "prevailed",\n'
        '  "prevailing_party": "the appellee",\n'
        '  "reasoning": "The opinion adopted the appellee\'s brief language directly.",\n'
        '  "brief_text": "The contract language was plain and unambiguous.",\n'
        '  "brief_source": "https://example.com/brief.pdf",\n'
        '  "confidence": "high"\n'
        "}\n"
        "```"
    )

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = mock_anthropic_cls.return_value
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(type="text", text=winning_json)],
            usage=MagicMock(input_tokens=100, output_tokens=100, server_tool_use=None),
            stop_reason="end_turn",
        )

        with app.test_client() as client:
            homepage = client.get("/")
            assert b"Run Auto-Research on all 2 unverified cases" in homepage.data

            response = client.post("/courtlistener/auto-verify-all", data={})
            assert response.status_code == 302
            batch_url = response.headers["Location"]

            # Jobs run in background threads; the mocked API call is
            # effectively instant, so a short poll is enough for them to finish.
            import time

            for _ in range(50):
                status_page = client.get(batch_url)
                if b"2 of 2 finished" in status_page.data:
                    break
                time.sleep(0.02)

    assert b"2 of 2 finished" in status_page.data
    assert b"Doe v. Roe" in status_page.data
    assert b"Second v. Case" in status_page.data

    candidates = {c.case_name: c for c in load_candidates(app.config)}
    assert candidates["Doe v. Roe"].status == "verified_winning"
    assert candidates["Second v. Case"].status == "verified_winning"


def test_analyze_uses_compare_judge_style_profile_and_precedent_signal(tmp_path: Path):
    app = make_analyze_app(tmp_path)

    from app.courtlistener_sync import add_tracked_judge

    judge = add_tracked_judge(app.config, "Judge Test", "scotus")
    profile = build_style_profile(
        "Judge Test",
        ["We conclude that equitable relief must remain narrowly tailored to the parties before the court."],
    )
    save_style_profile(app.config, profile)

    with app.test_client() as client:
        response = client.post(
            "/analyze",
            data={
                "draft_file": (
                    BytesIO(b"We conclude that equitable relief here must remain narrowly tailored."),
                    "draft.txt",
                ),
                "compare_judge_id": judge.id,
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"Compared against" in response.data
    assert b"Judge Test" in response.data


def test_analyze_with_firm_folder_only_uses_it_as_primary_result(tmp_path: Path):
    folder_dir = tmp_path / "Firm Winning Briefs"
    folder_dir.mkdir()
    (folder_dir / "brief_one.txt").write_text(
        "Equitable relief must remain narrowly tailored to the parties before the court.",
        encoding="utf-8",
    )

    app = make_analyze_app(tmp_path)

    with app.test_client() as client:
        response = client.post(
            "/analyze",
            data={
                "draft_file": (
                    BytesIO(b"We conclude that equitable relief here must remain narrowly tailored."),
                    "draft.txt",
                ),
                "firm_folder_path": str(folder_dir),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"Affinity Score" in response.data
    # No judge selected and only one comparison source active -- no toggle.
    assert b"comparison-toggle" not in response.data


def test_analyze_with_no_files_in_firm_folder_shows_clear_message(tmp_path: Path):
    empty_folder = tmp_path / "Empty Folder"
    empty_folder.mkdir()

    app = make_analyze_app(tmp_path)

    with app.test_client() as client:
        response = client.post(
            "/analyze",
            data={
                "draft_file": (BytesIO(b"Some brief language here."), "draft.txt"),
                "firm_folder_path": str(empty_folder),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"No .txt/.pdf/.docx files were found" in response.data


def test_analyze_with_both_judge_and_folder_produces_toggleable_secondary_result(tmp_path: Path):
    from app.courtlistener_sync import add_tracked_judge

    app = make_analyze_app(tmp_path)

    judge = add_tracked_judge(app.config, "Judge Test", "scotus")
    profile = build_style_profile(
        "Judge Test",
        ["We conclude that equitable relief must remain narrowly tailored to the parties before the court."],
    )
    save_style_profile(app.config, profile)

    folder_dir = tmp_path / "Firm Winning Briefs"
    folder_dir.mkdir()
    (folder_dir / "brief_one.txt").write_text(
        "Equitable relief must remain narrowly tailored to the parties before the court.",
        encoding="utf-8",
    )

    with app.test_client() as client:
        response = client.post(
            "/analyze",
            data={
                "draft_file": (
                    BytesIO(b"We conclude that equitable relief here must remain narrowly tailored."),
                    "draft.txt",
                ),
                "compare_judge_id": judge.id,
                "firm_folder_path": str(folder_dir),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"comparison-toggle" in response.data
    assert b"Judge Test" in response.data
    assert b"Firm folder" in response.data


def test_analyze_reallocates_weight_when_judge_has_style_profile_but_no_verified_briefs(tmp_path: Path):
    # Judge style profile exists but this judge has zero verified winning briefs
    # recorded. The precedent-brief source is unavailable, so its share of the
    # linked sliders should be handed to the judge-style signal automatically,
    # and the results page should still explain why via the empty-source message.
    from app.courtlistener_sync import add_tracked_judge

    app = make_analyze_app(tmp_path)

    judge = add_tracked_judge(app.config, "Judge Test", "scotus")
    profile = build_style_profile(
        "Judge Test",
        ["We conclude that equitable relief must remain narrowly tailored to the parties before the court."],
    )
    save_style_profile(app.config, profile)
    # Deliberately no verified winning briefs recorded for this judge.

    with app.test_client() as client:
        response = client.post(
            "/analyze",
            data={
                "draft_file": (
                    BytesIO(b"We conclude that equitable relief here must remain narrowly tailored."),
                    "draft.txt",
                ),
                "compare_judge_id": judge.id,
                "weight_judge_style": "20",
                "weight_precedent_brief": "80",
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"No verified winning briefs recorded for this judge yet" in response.data


def test_analyze_with_neither_judge_nor_folder_has_no_toggle(tmp_path: Path):
    app = make_analyze_app(tmp_path)

    with app.test_client() as client:
        response = client.post(
            "/analyze",
            data={
                "draft_file": (
                    BytesIO(b"The court finds the argument persuasive and grants the motion."),
                    "draft.txt",
                ),
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert b"comparison-toggle" not in response.data
