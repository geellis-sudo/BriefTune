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
