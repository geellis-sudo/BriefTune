from __future__ import annotations

import threading
from pathlib import Path

from app.brief_candidates import (
    candidates_for_judge,
    flag_brief_mentions,
    load_candidates,
    precedent_alignment_score,
    verified_winning_brief_texts,
    verify_candidate,
)


def make_config(tmp_path: Path) -> dict:
    return {"BRIEF_MENTION_CANDIDATES_PATH": tmp_path / "brief_mention_candidates.json"}


OPINION_WITH_BRIEF_MENTION = (
    'The appellee\'s brief argued, "The contract language was plain and unambiguous." '
    "The court agreed with that phrasing and adopted it in full."
)

OPINION_WITHOUT_BRIEF_MENTION = (
    "The court reviewed the record and found the evidence sufficient to support the verdict."
)


def test_flag_brief_mentions_creates_candidate_when_reference_found(tmp_path: Path):
    app_config = make_config(tmp_path)

    flagged = flag_brief_mentions(
        app_config, "judge-1", "Judge Test", 12345, "Doe v. Roe", "2025-01-01", OPINION_WITH_BRIEF_MENTION
    )

    assert flagged is True
    candidates = load_candidates(app_config)
    assert len(candidates) == 1
    assert candidates[0].case_name == "Doe v. Roe"
    assert candidates[0].status == "unverified"
    assert candidates[0].excerpts


def test_flag_brief_mentions_skips_opinions_without_a_brief_reference(tmp_path: Path):
    app_config = make_config(tmp_path)

    flagged = flag_brief_mentions(
        app_config, "judge-1", "Judge Test", 999, "Smith v. Jones", "2025-01-01", OPINION_WITHOUT_BRIEF_MENTION
    )

    assert flagged is False
    assert load_candidates(app_config) == []


def test_flag_brief_mentions_is_idempotent_for_the_same_opinion(tmp_path: Path):
    app_config = make_config(tmp_path)

    flag_brief_mentions(app_config, "judge-1", "Judge Test", 12345, "Doe v. Roe", "2025-01-01", OPINION_WITH_BRIEF_MENTION)
    flagged_again = flag_brief_mentions(
        app_config, "judge-1", "Judge Test", 12345, "Doe v. Roe", "2025-01-01", OPINION_WITH_BRIEF_MENTION
    )

    assert flagged_again is False
    assert len(load_candidates(app_config)) == 1


def test_verify_candidate_records_status_and_brief_text(tmp_path: Path):
    app_config = make_config(tmp_path)
    flag_brief_mentions(app_config, "judge-1", "Judge Test", 12345, "Doe v. Roe", "2025-01-01", OPINION_WITH_BRIEF_MENTION)
    candidate_id = load_candidates(app_config)[0].id

    updated = verify_candidate(
        app_config, candidate_id, "verified_winning", brief_text="The contract language was plain and unambiguous."
    )

    assert updated is not None
    assert updated.status == "verified_winning"
    assert updated.brief_text == "The contract language was plain and unambiguous."
    assert updated.verified_at is not None

    winning_texts = verified_winning_brief_texts(app_config, "judge-1")
    assert winning_texts == ["The contract language was plain and unambiguous."]


def test_candidates_for_judge_filters_by_status(tmp_path: Path):
    app_config = make_config(tmp_path)
    flag_brief_mentions(app_config, "judge-1", "Judge Test", 1, "Case One", "2025-01-01", OPINION_WITH_BRIEF_MENTION)
    flag_brief_mentions(app_config, "judge-1", "Judge Test", 2, "Case Two", "2025-01-02", OPINION_WITH_BRIEF_MENTION)
    candidates = load_candidates(app_config)
    verify_candidate(app_config, candidates[0].id, "verified_winning", brief_text="won text")

    unverified = candidates_for_judge(app_config, "judge-1", status="unverified")
    winning = candidates_for_judge(app_config, "judge-1", status="verified_winning")

    assert len(unverified) == 1
    assert len(winning) == 1


def test_precedent_alignment_score_rewards_shared_vocabulary():
    verified_texts = [
        "Universal injunctions exceed the equitable authority granted by the Judiciary Act.",
        "Equitable authority under the Judiciary Act does not extend to universal injunctions.",
    ]

    aligned_text = "This brief argues that the Judiciary Act limits equitable authority to traditional remedies."
    bonus, factors = precedent_alignment_score(aligned_text, verified_texts)

    assert bonus > 0
    assert any("verified as prevailing" in factor for factor in factors)


def test_precedent_alignment_score_handles_no_verified_briefs():
    bonus, factors = precedent_alignment_score("Some brief text.", [])

    assert bonus == 0
    assert "No verified winning briefs" in factors[0]


def test_concurrent_verify_candidate_does_not_lose_updates(tmp_path: Path):
    """Regression test for the race condition that surfaced once Auto-Research
    could run on multiple candidates in parallel: verify_candidate() used to
    do a plain read-modify-write on candidates.json, so two threads finishing
    around the same time could silently overwrite one another's update. Now
    guarded by a lock plus an atomic write; this test fails loudly if either
    protection regresses.
    """
    app_config = make_config(tmp_path)

    candidate_count = 20
    for i in range(candidate_count):
        flag_brief_mentions(app_config, "judge-1", "Judge Test", i, f"Case {i} v. Roe", "2025-01-01", OPINION_WITH_BRIEF_MENTION)

    candidate_ids = [c.id for c in load_candidates(app_config)]
    assert len(candidate_ids) == candidate_count

    errors: list[Exception] = []

    def verify(cid: str) -> None:
        try:
            verify_candidate(app_config, cid, "verified_winning", brief_text="Some brief text", notes="auto")
        except Exception as exc:  # pragma: no cover - surfaced via `errors`
            errors.append(exc)

    threads = [threading.Thread(target=verify, args=(cid,)) for cid in candidate_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors

    final_candidates = load_candidates(app_config)
    assert len(final_candidates) == candidate_count
    still_unverified = [c.case_name for c in final_candidates if c.status != "verified_winning"]
    assert still_unverified == [], f"Lost update(s) for: {still_unverified}"
