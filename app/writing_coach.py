from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# AI Writing Coach (optional, billed per run)
#
# This is a separate, additive pass on top of the free/instant regex-based
# Writing Quality section in analyzer.py. It calls the Anthropic API directly
# -- with the caller's own API key, billed per token -- for a close editorial
# read that pattern-matching can't do: argument structure, persuasiveness,
# and tone, not just mechanical issues like passive voice or long sentences.
# It never replaces the free analysis; it's an opt-in extra step, same shape
# as Auto-Research in ai_verification.py, but a single bounded call rather
# than a multi-step tool-using loop, so no loop limiter is needed here.
# ---------------------------------------------------------------------------

# Model string current as of this build (July 2026). If Anthropic renames or
# retires this model, confirm the current string at
# https://docs.claude.com/en/docs/about-claude/models before relying on it.
DEFAULT_MODEL = "claude-sonnet-5"
MAX_TOKENS = 2000

# Rough per-token pricing estimates for the configured model. These are
# ESTIMATES for budgeting purposes only -- confirm against Anthropic's
# current pricing page before relying on them for real client billing.
INPUT_COST_PER_MTOK = 3.00
OUTPUT_COST_PER_MTOK = 15.00


@dataclass(frozen=True)
class CoachSuggestion:
    category: str
    quote: str
    suggestion: str
    rationale: str


@dataclass(frozen=True)
class WritingCoachResult:
    available: bool
    overall_assessment: str = ""
    suggestions: list[CoachSuggestion] = field(default_factory=list)
    cost_usd: float = 0.0
    error: str = ""


def _build_prompt(text: str) -> str:
    return (
        "You are an experienced appellate brief editor reviewing a draft brief for "
        "clarity, persuasiveness, and professional tone. The text below has already "
        "been anonymized -- redacted names or identifying details appear as bracketed "
        "tags like [REDACTED], [SSN], [PHONE], [EMAIL]; treat those as normal "
        "placeholders, not errors to flag.\n\n"
        "Draft brief text:\n-----\n"
        f"{text[:16000]}\n-----\n\n"
        "Give a close editorial read beyond simple pattern-matching: argument "
        "structure, persuasiveness, tone, and clarity -- not mechanical issues like "
        "passive voice, long sentences, or hedging words (a separate automated pass "
        "already checks those, so don't repeat them unless the point is substantively "
        "different).\n\n"
        "Respond with ONLY a fenced json block in exactly this shape, nothing else:\n"
        "```json\n"
        "{\n"
        '  "overall_assessment": "2-3 sentence summary of the draft\'s strongest and weakest points",\n'
        '  "suggestions": [\n'
        "    {\n"
        '      "category": "short label, e.g. Argument structure",\n'
        '      "quote": "the exact passage being discussed, verbatim from the draft",\n'
        '      "suggestion": "the specific rewrite or fix recommended",\n'
        '      "rationale": "1-2 sentences on why this improves the brief"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "```"
    )


def _extract_json_block(text: str) -> dict[str, Any] | None:
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate_text = match.group(1) if match else None

    if candidate_text is None:
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        candidate_text = match.group(1) if match else None

    if not candidate_text:
        return None

    try:
        return json.loads(candidate_text)
    except json.JSONDecodeError:
        return None


def _estimate_cost(usage: Any) -> float:
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    return (input_tokens / 1_000_000) * INPUT_COST_PER_MTOK + (output_tokens / 1_000_000) * OUTPUT_COST_PER_MTOK


def run_writing_coach(app_config: dict[str, Any], text: str) -> WritingCoachResult:
    """One-shot, whole-draft AI editorial pass. Optional and billed separately
    from the free regex-based Writing Quality section -- gated behind the
    caller's own ANTHROPIC_API_KEY, same precondition as Auto-Research.
    """
    api_key = app_config.get("ANTHROPIC_API_KEY")
    if not api_key:
        return WritingCoachResult(available=False, error="ANTHROPIC_API_KEY is not configured. Add it to .env to use the AI Writing Coach.")

    try:
        from anthropic import Anthropic
    except ImportError:
        return WritingCoachResult(available=False, error="The 'anthropic' package is not installed. Run: pip install -r requirements.txt")

    client = Anthropic(api_key=api_key)
    model = app_config.get("AI_VERIFICATION_MODEL", DEFAULT_MODEL)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": _build_prompt(text)}],
        )
    except Exception as exc:  # network/auth/model errors -- surface, don't crash the request
        return WritingCoachResult(available=False, error=f"Anthropic API call failed: {exc}")

    cost = round(_estimate_cost(response.usage), 4)
    text_blocks = [block.text for block in response.content if getattr(block, "type", "") == "text"]
    parsed = _extract_json_block("\n".join(text_blocks))

    if parsed is None:
        return WritingCoachResult(
            available=False,
            cost_usd=cost,
            error="The AI Writing Coach ran but didn't return a response BriefTune could parse. Try again.",
        )

    suggestions = [
        CoachSuggestion(
            category=item.get("category") or "Suggestion",
            quote=item.get("quote") or "",
            suggestion=item.get("suggestion") or "",
            rationale=item.get("rationale") or "",
        )
        for item in parsed.get("suggestions", [])
        if isinstance(item, dict)
    ]

    return WritingCoachResult(
        available=True,
        overall_assessment=parsed.get("overall_assessment") or "",
        suggestions=suggestions,
        cost_usd=cost,
    )
