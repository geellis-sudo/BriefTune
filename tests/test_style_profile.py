from __future__ import annotations

from pathlib import Path

from app.style_profile import (
    build_style_profile,
    load_style_profile,
    rebuild_style_profile_from_folder,
    save_style_profile,
    style_alignment_score,
)


JUDGE_OPINIONS = [
    "The court concludes that equitable relief must be narrowly tailored to the parties before it. "
    "We hold that complete relief does not require a universal remedy.",
    "The court again concludes that equitable authority is limited by historical practice. "
    "We hold that the District Court exceeded its remedial authority.",
]


def test_build_style_profile_extracts_distinctive_terms_and_sentence_length():
    profile = build_style_profile("Judge Test", JUDGE_OPINIONS)

    assert profile is not None
    assert profile.judge_name == "Judge Test"
    assert profile.opinion_count == 2
    terms = [term for term, _count in profile.top_terms]
    assert "equitable" in terms or "concludes" in terms or "relief" in terms
    assert profile.avg_sentence_length > 0
    assert profile.framing_hit_rate == 1.0


def test_build_style_profile_returns_none_for_empty_input():
    assert build_style_profile("Judge Test", []) is None
    assert build_style_profile("Judge Test", ["   ", ""]) is None


def test_save_and_load_style_profile_round_trips(tmp_path: Path):
    app_config = {"JUDGE_STYLE_PROFILE_DIR": tmp_path / "profiles"}
    profile = build_style_profile("Judge Test", JUDGE_OPINIONS)

    save_style_profile(app_config, profile)
    loaded = load_style_profile(app_config, "Judge Test")

    assert loaded is not None
    assert loaded.judge_name == "Judge Test"
    assert loaded.top_terms == profile.top_terms


def test_load_style_profile_returns_none_when_missing(tmp_path: Path):
    app_config = {"JUDGE_STYLE_PROFILE_DIR": tmp_path / "profiles"}
    assert load_style_profile(app_config, "Nobody") is None


def test_rebuild_style_profile_from_folder(tmp_path: Path):
    app_config = {"JUDGE_STYLE_PROFILE_DIR": tmp_path / "profiles"}
    folder = tmp_path / "Judge Test"
    folder.mkdir()
    (folder / "opinion_one.txt").write_text(JUDGE_OPINIONS[0], encoding="utf-8")
    (folder / "opinion_two.txt").write_text(JUDGE_OPINIONS[1], encoding="utf-8")

    profile = rebuild_style_profile_from_folder(app_config, "Judge Test", folder)

    assert profile is not None
    assert profile.opinion_count == 2
    assert load_style_profile(app_config, "Judge Test") is not None


def test_style_alignment_score_rewards_shared_vocabulary():
    profile = build_style_profile("Judge Test", JUDGE_OPINIONS)

    aligned_text = "We conclude that equitable relief here must remain narrowly tailored."
    bonus, factors = style_alignment_score(aligned_text, profile)

    assert bonus > 0
    assert any("distinctive terms" in factor for factor in factors)


def test_style_alignment_score_handles_missing_profile():
    bonus, factors = style_alignment_score("Some brief text.", None)

    assert bonus == 0
    assert "No judge style profile available yet" in factors[0]
