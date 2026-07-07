from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.writing_coach import run_writing_coach

DRAFT_TEXT = "The contract language was plain and unambiguous. Appellant respectfully requests reversal."


def make_response(text: str, input_tokens: int = 100, output_tokens: int = 100):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


SUGGESTIONS_JSON = (
    "```json\n"
    "{\n"
    '  "overall_assessment": "Clear on the facts but the lead argument buries the strongest point.",\n'
    '  "suggestions": [\n'
    "    {\n"
    '      "category": "Argument structure",\n'
    '      "quote": "Appellant respectfully requests reversal.",\n'
    '      "suggestion": "Lead with the standard-of-review point before the request for relief.",\n'
    '      "rationale": "Judges look for the legal hook before the ask."\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "```"
)


def test_run_writing_coach_missing_api_key():
    result = run_writing_coach({}, DRAFT_TEXT)

    assert result.available is False
    assert "ANTHROPIC_API_KEY" in result.error


def test_run_writing_coach_returns_parsed_suggestions():
    config = {"ANTHROPIC_API_KEY": "test-key"}

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = mock_anthropic_cls.return_value
        mock_client.messages.create.return_value = make_response(SUGGESTIONS_JSON)

        result = run_writing_coach(config, DRAFT_TEXT)

    assert result.available is True
    assert "buries the strongest point" in result.overall_assessment
    assert len(result.suggestions) == 1
    assert result.suggestions[0].category == "Argument structure"
    assert result.cost_usd > 0


def test_run_writing_coach_handles_unparseable_response():
    config = {"ANTHROPIC_API_KEY": "test-key"}

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = mock_anthropic_cls.return_value
        mock_client.messages.create.return_value = make_response("Not JSON at all.")

        result = run_writing_coach(config, DRAFT_TEXT)

    assert result.available is False
    assert "couldn't parse" in result.error.lower() or "parse" in result.error.lower()


def test_run_writing_coach_handles_api_error():
    config = {"ANTHROPIC_API_KEY": "test-key"}

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = mock_anthropic_cls.return_value
        mock_client.messages.create.side_effect = RuntimeError("network down")

        result = run_writing_coach(config, DRAFT_TEXT)

    assert result.available is False
    assert "network down" in result.error
