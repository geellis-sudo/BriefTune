from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.ai_verification import (
    JOB_STORE,
    _extract_json_block,
    _run_verification,
    clamp_cost_limit,
    clamp_loop_limit,
    start_verification_batch,
)
from app.brief_candidates import flag_brief_mentions, get_candidate, load_candidates

OPINION_TEXT = (
    'The appellee\'s brief argued, "The contract language was plain and unambiguous." '
    "The court agreed with that phrasing and adopted it in full, resolving the dispute in the appellee's favor."
)

JUDGE_NAME = "Judge Test"
CLUSTER_ID = 555
CANDIDATE_ID = f"judge-1-{CLUSTER_ID}"


def make_config(tmp_path: Path) -> dict:
    config = {
        "BRIEF_MENTION_CANDIDATES_PATH": tmp_path / "candidates.json",
        "COURTLISTENER_SYNC_DIR": tmp_path / "sync",
        "ANTHROPIC_API_KEY": "test-key",
    }
    flag_brief_mentions(config, "judge-1", JUDGE_NAME, CLUSTER_ID, "Doe v. Roe", "2025-01-01", OPINION_TEXT)

    folder = Path(config["COURTLISTENER_SYNC_DIR"]) / f"Judge {JUDGE_NAME}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"doe-v-roe-{CLUSTER_ID}.txt").write_text(OPINION_TEXT, encoding="utf-8")

    return config


def make_response(text: str, input_tokens: int = 100, output_tokens: int = 100, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, server_tool_use=None),
        stop_reason=stop_reason,
    )


WINNING_JSON = (
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

LOSING_JSON = (
    "```json\n"
    "{\n"
    '  "outcome": "did_not_prevail",\n'
    '  "prevailing_party": "the appellant",\n'
    '  "reasoning": "The court rejected the appellee\'s argument.",\n'
    '  "brief_text": null,\n'
    '  "brief_source": null,\n'
    '  "confidence": "medium"\n'
    "}\n"
    "```"
)


def test_clamp_loop_limit_respects_bounds():
    assert clamp_loop_limit(1) == 3
    assert clamp_loop_limit(50) == 20
    assert clamp_loop_limit(8) == 8


def test_clamp_cost_limit_respects_bounds():
    assert clamp_cost_limit(0.01) == 0.25
    assert clamp_cost_limit(10.0) == 2.00
    assert clamp_cost_limit(0.75) == 0.75


def test_extract_json_block_parses_fenced_json():
    parsed = _extract_json_block(WINNING_JSON)
    assert parsed is not None
    assert parsed["outcome"] == "prevailed"


def test_extract_json_block_returns_none_for_unparseable_text():
    assert _extract_json_block("Still researching, no answer yet.") is None


def test_run_verification_missing_api_key(tmp_path: Path):
    config = make_config(tmp_path)
    config["ANTHROPIC_API_KEY"] = ""

    job = JOB_STORE.create(CANDIDATE_ID, 5, 0.5)
    _run_verification(config, job.id)

    assert job.status == "error"
    assert "ANTHROPIC_API_KEY" in job.error


def test_run_verification_missing_candidate(tmp_path: Path):
    config = make_config(tmp_path)

    job = JOB_STORE.create("nonexistent-id", 5, 0.5)
    _run_verification(config, job.id)

    assert job.status == "error"
    assert "no longer exists" in job.error


def test_run_verification_records_verified_winning_and_attaches_brief_text(tmp_path: Path):
    config = make_config(tmp_path)
    job = JOB_STORE.create(CANDIDATE_ID, 5, 0.5)

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = mock_anthropic_cls.return_value
        mock_client.messages.create.return_value = make_response(WINNING_JSON)

        _run_verification(config, job.id)

    assert job.status == "done"
    assert job.stopped_reason == "completed"
    assert job.outcome == "prevailed"
    assert job.brief_text_found == "The contract language was plain and unambiguous."
    assert job.candidate_status_applied == "verified_winning"

    candidate = get_candidate(config, CANDIDATE_ID)
    assert candidate.status == "verified_winning"
    assert candidate.brief_text == "The contract language was plain and unambiguous."


def test_run_verification_records_verified_not_winning(tmp_path: Path):
    config = make_config(tmp_path)
    job = JOB_STORE.create(CANDIDATE_ID, 5, 0.5)

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = mock_anthropic_cls.return_value
        mock_client.messages.create.return_value = make_response(LOSING_JSON)

        _run_verification(config, job.id)

    assert job.status == "done"
    assert job.outcome == "did_not_prevail"
    assert job.candidate_status_applied == "verified_not_winning"

    candidate = get_candidate(config, CANDIDATE_ID)
    assert candidate.status == "verified_not_winning"


def test_run_verification_stops_at_cost_limit(tmp_path: Path):
    config = make_config(tmp_path)
    # Cheap enough that one call already exceeds a very low limit.
    job = JOB_STORE.create(CANDIDATE_ID, 10, 0.01)

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = mock_anthropic_cls.return_value
        # Never produces a parseable answer, and costs more than the $0.01 limit
        # in a single call (100k output tokens * $15/mtok = $1.50).
        mock_client.messages.create.return_value = make_response(
            "Still researching, no answer yet.", input_tokens=1000, output_tokens=100_000
        )

        _run_verification(config, job.id)

    assert job.status == "done"
    assert job.stopped_reason == "cost_limit"
    assert job.outcome == "unclear"
    assert job.steps_used == 1
    assert mock_client.messages.create.call_count == 1

    candidate = get_candidate(config, CANDIDATE_ID)
    assert candidate.status == "unverified"


def test_start_verification_batch_runs_all_candidates_concurrently(tmp_path: Path):
    config = make_config(tmp_path)
    # Flag a second candidate so there are two to batch-verify.
    flag_brief_mentions(config, "judge-1", JUDGE_NAME, 556, "Second v. Case", "2025-02-01", OPINION_TEXT)
    sync_folder = Path(config["COURTLISTENER_SYNC_DIR"]) / f"Judge {JUDGE_NAME}"
    (sync_folder / "second-v-case-556.txt").write_text(OPINION_TEXT, encoding="utf-8")

    candidate_ids = [c.id for c in load_candidates(config) if c.status == "unverified"]
    assert len(candidate_ids) == 2

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = mock_anthropic_cls.return_value
        mock_client.messages.create.return_value = make_response(WINNING_JSON)

        batch = start_verification_batch(config, candidate_ids, loop_limit=5, cost_limit_usd=0.5)

        import time

        jobs = []
        for _ in range(50):
            jobs = [JOB_STORE.get(job_id) for job_id in batch.job_ids]
            if all(job.status == "done" for job in jobs):
                break
            time.sleep(0.02)

    assert len(batch.job_ids) == 2
    assert all(job.status == "done" for job in jobs)
    assert all(job.outcome == "prevailed" for job in jobs)


def test_run_verification_stops_at_loop_limit(tmp_path: Path):
    config = make_config(tmp_path)
    job = JOB_STORE.create(CANDIDATE_ID, 3, 2.00)

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = mock_anthropic_cls.return_value
        # Cheap responses that never produce a parseable answer -- should
        # exhaust the loop limit rather than the cost limit.
        mock_client.messages.create.return_value = make_response("Still researching, no answer yet.")

        _run_verification(config, job.id)

    assert job.status == "done"
    assert job.stopped_reason == "loop_limit"
    assert job.outcome == "unclear"
    assert job.steps_used == 3
    assert mock_client.messages.create.call_count == 3

    candidate = get_candidate(config, CANDIDATE_ID)
    assert candidate.status == "unverified"
