from app.analyzer import analyze_text


def test_analyze_text_flags_long_sentence_and_passive_voice():
    text = (
        "The motion was granted by the court after the brief was reviewed and the facts were weighed "
        "carefully by the judge in a way that made the sentence much too long for comfortable reading."
    )

    result = analyze_text(text)

    categories = [issue.category for issue in result["issues"]]

    assert result["word_count"] > 20
    assert "Long sentence" in categories
    assert "Passive voice" in categories


def test_analyze_text_flags_repetition_and_jargon():
    text = (
        "The court, pursuant to the record, found the same point again and again. "
        "The court, pursuant to the record, found the same point again and again."
    )

    result = analyze_text(text)

    categories = [issue.category for issue in result["issues"]]

    assert "Repetition" in categories
    assert "Dense legal wording" in categories


def test_analyze_text_extracts_brief_language_passages_with_extra_weight():
    text = (
        "The appellee's brief argued, \"The contract language was plain and unambiguous.\" "
        "The court agreed with that phrasing and repeated it in the opinion."
    )

    result = analyze_text(text)

    categories = [issue.category for issue in result["issues"]]

    assert "Brief language reference" in categories
    assert result["brief_language_references"]
    assert result["brief_language_references"][0].passage == "The contract language was plain and unambiguous."
    assert 0 <= result["summary"].affinity_score <= 100
    assert result["summary"].affinity_explanation


def test_analyze_text_marks_transcript_sourced_brief_references():
    text = (
        "The transcript records that the appellee's brief argued, \"The contract language was plain and unambiguous.\" "
        "The court then adopted that wording."
    )

    result = analyze_text(text, source_type="transcript")

    reference_issues = [issue for issue in result["issues"] if issue.category == "Brief language reference"]

    assert reference_issues
    assert "transcript-linked" in reference_issues[0].suggestion
    assert result["source_type"] == "transcript"
    assert "transcript" in result["summary"].affinity_explanation.lower()


def test_analyze_text_builds_writing_quality_score_with_flagged_examples():
    text = (
        "Arguably, the court was given the ability to make a determination because the appellee's brief argued, "
        '"The contract language was plain and unambiguous," see Brown, 347 U.S. 483 (1954), and the record was reviewed carefully before the court took into consideration all of the arguments presented by the parties in a single sentence that keeps going past forty words while the judge still insisted that the issue was already clear and needed no further explanation. "'
    )

    result = analyze_text(text)

    categories = [flag.category for flag in result["writing_quality"].writing_quality_flags]

    assert 0 <= result["writing_quality"].writing_quality_score <= 100
    assert "Nominalization" in categories
    assert "Passive voice" in categories
    assert "Buried citation" in categories
    assert "Hedging" in categories
    assert "Long sentence" in categories
    assert result["writing_quality"].writing_quality_explanation


def test_analyze_text_without_judge_signals_behaves_as_before():
    text = "The court finds the argument persuasive and grants the motion."

    result = analyze_text(text)

    # Backward compatibility: omitting the new judge-specific params should not
    # change behavior or introduce factors about them.
    assert not any("distinctive terms" in factor for factor in result["summary"].affinity_factors)
    assert not any("verified as prevailing" in factor for factor in result["summary"].affinity_factors)


def test_analyze_text_adds_judge_style_bonus_and_factors():
    text = "The court finds the argument persuasive and grants the motion."

    base_result = analyze_text(text)
    boosted_result = analyze_text(
        text,
        judge_style_raw_bonus=20,
        judge_style_factors=["Shares 10 of Judge Test's 40 most distinctive terms, including court, grant."],
        weight_judge_style=1.0,
    )

    assert boosted_result["summary"].affinity_score >= base_result["summary"].affinity_score
    assert any("distinctive terms" in factor for factor in boosted_result["summary"].affinity_factors)


def test_analyze_text_judge_style_bonus_respects_weight_and_cap():
    text = "The court finds the argument persuasive and grants the motion."

    zero_weight = analyze_text(text, judge_style_raw_bonus=20, weight_judge_style=0.0)
    full_weight = analyze_text(text, judge_style_raw_bonus=20, weight_judge_style=1.0)

    assert zero_weight["summary"].affinity_score <= full_weight["summary"].affinity_score


def test_analyze_text_adds_precedent_bonus_and_factors():
    text = "The court finds the argument persuasive and grants the motion."

    result = analyze_text(
        text,
        precedent_raw_bonus=25,
        precedent_factors=["Shares 8 of 40 distinctive terms from 2 brief(s) verified as prevailing before this judge."],
        weight_precedent_brief=1.0,
    )

    assert any("verified as prevailing" in factor for factor in result["summary"].affinity_factors)
    assert 0 <= result["summary"].affinity_score <= 100


def test_analyze_text_reallocates_full_weight_when_precedent_source_missing():
    # The two weight sliders are a linked pair (sum to 1.0). If the precedent
    # signal has nothing to measure, its unused share should be handed entirely
    # to the judge-style signal instead of being wasted -- even though the user
    # only set judge style to 20% on the slider.
    text = "The court finds the argument persuasive and grants the motion."

    reallocated = analyze_text(
        text,
        judge_style_raw_bonus=20,
        weight_judge_style=0.2,
        judge_style_source_available=True,
        weight_precedent_brief=0.8,
        precedent_source_available=False,
    )
    not_reallocated = analyze_text(
        text,
        judge_style_raw_bonus=20,
        weight_judge_style=0.2,
        judge_style_source_available=True,
        weight_precedent_brief=0.8,
        precedent_source_available=True,
    )

    assert reallocated["summary"].affinity_score > not_reallocated["summary"].affinity_score


def test_analyze_text_reallocates_full_weight_when_judge_style_source_missing():
    # Symmetric case: no synced judge style profile (or no firm-folder text),
    # so the precedent brief signal gets the judge style slider's unused share.
    text = "The court finds the argument persuasive and grants the motion."

    reallocated = analyze_text(
        text,
        precedent_raw_bonus=25,
        weight_precedent_brief=0.3,
        precedent_source_available=True,
        weight_judge_style=0.7,
        judge_style_source_available=False,
    )
    not_reallocated = analyze_text(
        text,
        precedent_raw_bonus=25,
        weight_precedent_brief=0.3,
        precedent_source_available=True,
        weight_judge_style=0.7,
        judge_style_source_available=True,
    )

    assert reallocated["summary"].affinity_score > not_reallocated["summary"].affinity_score


def test_analyze_text_reallocation_ignores_original_slider_split():
    # Once a source is missing, the surviving signal always gets the full 100%
    # budget -- so where the slider originally sat before the source went empty
    # shouldn't change the outcome.
    text = "The court finds the argument persuasive and grants the motion."

    low_slider = analyze_text(
        text,
        judge_style_raw_bonus=20,
        weight_judge_style=0.05,
        judge_style_source_available=True,
        weight_precedent_brief=0.95,
        precedent_source_available=False,
    )
    high_slider = analyze_text(
        text,
        judge_style_raw_bonus=20,
        weight_judge_style=0.95,
        judge_style_source_available=True,
        weight_precedent_brief=0.05,
        precedent_source_available=False,
    )

    assert low_slider["summary"].affinity_score == high_slider["summary"].affinity_score
