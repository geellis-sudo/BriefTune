from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .brief_candidates import get_candidate, verify_candidate
from .courtlistener_sync import _fetch_opinion_text

# ---------------------------------------------------------------------------
# Auto-Research (billed per verification)
#
# This module lets BriefTune call the Anthropic API directly -- with its own
# API key, billed per token -- to confirm which party's brief a judge actually
# discussed in a flagged opinion, and (only if that party won) to research and
# attach the real brief text. It mirrors exactly what a human doing this by
# hand in a chat would do; the difference is BriefTune's own server is now the
# one paying for and running that research, so every run is bounded by two
# independent guardrails: a "loop limiter" (max API round-trips) and a "price
# limiter" (max estimated dollars). Neither limit is ever silently exceeded --
# a run that would cross either one stops early and reports what it found so
# far as partial/inconclusive rather than continuing.
# ---------------------------------------------------------------------------

# Model string current as of this build (July 2026). If Anthropic renames or
# retires this model, confirm the current string at
# https://docs.claude.com/en/docs/about-claude/models before relying on it.
DEFAULT_MODEL = "claude-sonnet-5"

DEFAULT_LOOP_LIMIT = 10  # max Claude API round-trips per verification run.
MIN_LOOP_LIMIT = 3
MAX_LOOP_LIMIT = 20

DEFAULT_COST_LIMIT_USD = 0.50  # hard ceiling on estimated spend per verification.
MIN_COST_LIMIT_USD = 0.25
MAX_COST_LIMIT_USD = 2.00

# Rough per-token pricing estimates for the configured model, plus a flat
# per-web-search-use fee. These are ESTIMATES for budgeting purposes only --
# confirm against Anthropic's current pricing page before relying on them for
# real client billing, and update these constants if pricing changes.
INPUT_COST_PER_MTOK = 3.00
OUTPUT_COST_PER_MTOK = 15.00
WEB_SEARCH_COST_PER_USE = 0.01

WEB_SEARCH_TOOL_TYPE = "web_search_20260209"

VALID_STOPPED_REASONS = {"completed", "loop_limit", "cost_limit", "error"}


@dataclass
class VerificationJob:
    id: str
    candidate_id: str
    status: str = "queued"  # queued -> running -> done -> error
    steps_used: int = 0
    loop_limit: int = DEFAULT_LOOP_LIMIT
    cost_limit_usd: float = DEFAULT_COST_LIMIT_USD
    cost_spent_usd: float = 0.0
    stopped_reason: str = ""  # "" until finished, then one of VALID_STOPPED_REASONS
    outcome: str = ""  # "prevailed" | "did_not_prevail" | "unclear"
    prevailing_party: str = ""
    reasoning_summary: str = ""
    brief_text_found: str | None = None
    brief_source: str = ""
    candidate_status_applied: str = ""
    error: str = ""
    log: list[str] = field(default_factory=list)
    audit_logged: bool = False


class VerificationJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, VerificationJob] = {}
        self._lock = threading.Lock()

    def create(self, candidate_id: str, loop_limit: int, cost_limit_usd: float) -> VerificationJob:
        job = VerificationJob(
            id=uuid.uuid4().hex,
            candidate_id=candidate_id,
            loop_limit=loop_limit,
            cost_limit_usd=cost_limit_usd,
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> VerificationJob | None:
        with self._lock:
            return self._jobs.get(job_id)


JOB_STORE = VerificationJobStore()


@dataclass
class VerificationBatch:
    id: str
    job_ids: list[str] = field(default_factory=list)


class VerificationBatchStore:
    def __init__(self) -> None:
        self._batches: dict[str, VerificationBatch] = {}
        self._lock = threading.Lock()

    def create(self, job_ids: list[str]) -> VerificationBatch:
        batch = VerificationBatch(id=uuid.uuid4().hex, job_ids=job_ids)
        with self._lock:
            self._batches[batch.id] = batch
        return batch

    def get(self, batch_id: str) -> VerificationBatch | None:
        with self._lock:
            return self._batches.get(batch_id)


BATCH_STORE = VerificationBatchStore()


def clamp_loop_limit(value: int) -> int:
    return max(MIN_LOOP_LIMIT, min(MAX_LOOP_LIMIT, value))


def clamp_cost_limit(value: float) -> float:
    return max(MIN_COST_LIMIT_USD, min(MAX_COST_LIMIT_USD, value))


def start_verification(
    app_config: dict[str, Any],
    candidate_id: str,
    loop_limit: int = DEFAULT_LOOP_LIMIT,
    cost_limit_usd: float = DEFAULT_COST_LIMIT_USD,
) -> VerificationJob:
    job = JOB_STORE.create(candidate_id, clamp_loop_limit(loop_limit), clamp_cost_limit(cost_limit_usd))
    thread = threading.Thread(target=_run_verification, args=(app_config, job.id), daemon=True)
    thread.start()
    return job


def start_verification_batch(
    app_config: dict[str, Any],
    candidate_ids: list[str],
    loop_limit: int = DEFAULT_LOOP_LIMIT,
    cost_limit_usd: float = DEFAULT_COST_LIMIT_USD,
) -> VerificationBatch:
    """Start one independent verification job per candidate. Each job already
    runs in its own background thread (see start_verification), so this is
    genuine concurrency, not a queue -- all candidates are researched at the
    same time, bounded only by however many the caller passes in and the
    Anthropic API's own rate limits.
    """
    jobs = [
        start_verification(app_config, candidate_id, loop_limit=loop_limit, cost_limit_usd=cost_limit_usd)
        for candidate_id in candidate_ids
    ]
    return BATCH_STORE.create([job.id for job in jobs])


def _load_synced_opinion_text(app_config: dict[str, Any], judge_name: str, cluster_id: int) -> str:
    """Prefer the copy already saved locally during sync (free, instant, no
    CourtListener rate-limit risk); fall back to a fresh fetch only if it's
    somehow missing from the corpus folder.
    """
    sync_root = Path(app_config["COURTLISTENER_SYNC_DIR"])
    folder = sync_root / f"Judge {judge_name}"
    if folder.exists():
        for path in folder.glob(f"*-{cluster_id}.txt"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if text.strip():
                return text

    try:
        return _fetch_opinion_text(app_config, cluster_id)
    except Exception:
        return ""


def _estimate_cost(usage: Any) -> float:
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    server_tool_use = getattr(usage, "server_tool_use", None)
    web_searches = getattr(server_tool_use, "web_search_requests", 0) if server_tool_use else 0

    return (
        (input_tokens / 1_000_000) * INPUT_COST_PER_MTOK
        + (output_tokens / 1_000_000) * OUTPUT_COST_PER_MTOK
        + web_searches * WEB_SEARCH_COST_PER_USE
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


def _build_prompt(candidate, opinion_text: str) -> str:
    excerpt_block = "\n".join(f'- "{excerpt}"' for excerpt in candidate.excerpts[:5]) or "(no excerpt captured)"

    return (
        f"You are reviewing a real court opinion by Judge {candidate.judge_name} in the case "
        f'"{candidate.case_name}" (filed {candidate.date_filed or "date unknown"}).\n\n'
        "BriefTune's regex scan flagged the following passage(s) as likely referencing a party's brief:\n"
        f"{excerpt_block}\n\n"
        "Full opinion text:\n"
        "-----\n"
        f"{opinion_text[:12000]}\n"
        "-----\n\n"
        "Step 1: Using ONLY the opinion text above, determine which party's brief is being discussed, "
        "and whether that party's argument on this point actually prevailed in the court's holding. "
        "Do not guess beyond what the opinion text supports; if it's genuinely ambiguous, say so.\n\n"
        "Step 2: If (and only if) that party's argument prevailed, use the web_search tool to locate "
        "the real brief that party filed in this case (court dockets, case archives, or legal databases "
        "are good sources), and pull the substantive argument language relevant to the passage above. "
        "If you cannot find it after a reasonable search, say so rather than fabricating text.\n\n"
        "Respond with ONLY a fenced json block in exactly this shape, nothing else:\n"
        "```json\n"
        "{\n"
        '  "outcome": "prevailed | did_not_prevail | unclear",\n'
        '  "prevailing_party": "string, e.g. the appellee",\n'
        '  "reasoning": "1-3 sentence explanation grounded in the opinion text",\n'
        '  "brief_text": "the real brief argument text if found and outcome is prevailed, else null",\n'
        '  "brief_source": "url or citation for where the brief text came from, else null",\n'
        '  "confidence": "high | medium | low"\n'
        "}\n"
        "```"
    )


def _run_verification(app_config: dict[str, Any], job_id: str) -> None:
    job = JOB_STORE.get(job_id)
    if job is None:
        return

    candidate = get_candidate(app_config, job.candidate_id)
    if candidate is None:
        job.status = "error"
        job.stopped_reason = "error"
        job.error = "That flagged brief mention no longer exists."
        return

    api_key = app_config.get("ANTHROPIC_API_KEY")
    if not api_key:
        job.status = "error"
        job.stopped_reason = "error"
        job.error = "ANTHROPIC_API_KEY is not configured. Add it to .env to use Auto-Research."
        return

    opinion_text = _load_synced_opinion_text(app_config, candidate.judge_name, candidate.cluster_id)
    if not opinion_text:
        job.status = "error"
        job.stopped_reason = "error"
        job.error = "Could not load the synced opinion text for this case."
        return

    try:
        from anthropic import Anthropic
    except ImportError:
        job.status = "error"
        job.stopped_reason = "error"
        job.error = "The 'anthropic' package is not installed. Run: pip install -r requirements.txt"
        return

    client = Anthropic(api_key=api_key)
    model = app_config.get("AI_VERIFICATION_MODEL", DEFAULT_MODEL)

    messages: list[dict[str, Any]] = [{"role": "user", "content": _build_prompt(candidate, opinion_text)}]
    tools = [{"type": WEB_SEARCH_TOOL_TYPE, "name": "web_search", "max_uses": job.loop_limit}]

    job.status = "running"
    parsed: dict[str, Any] | None = None

    for step in range(1, job.loop_limit + 1):
        job.steps_used = step
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1500,
                tools=tools,
                messages=messages,
            )
        except Exception as exc:  # network/auth/model errors -- surface, don't crash the thread
            job.status = "error"
            job.stopped_reason = "error"
            job.error = f"Anthropic API call failed: {exc}"
            return

        job.cost_spent_usd = round(job.cost_spent_usd + _estimate_cost(response.usage), 4)
        text_blocks = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        full_text = "\n".join(text_blocks)
        parsed = _extract_json_block(full_text)
        job.log.append(
            f"Step {step}: stop_reason={response.stop_reason}, running cost ${job.cost_spent_usd:.4f}"
        )

        if parsed is not None:
            job.stopped_reason = "completed"
            break

        if job.cost_spent_usd >= job.cost_limit_usd:
            job.stopped_reason = "cost_limit"
            break

        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {"role": "user", "content": "Continue and provide your final answer as ONLY the fenced json block described above."}
        )
    else:
        job.stopped_reason = "loop_limit"

    if parsed is None:
        job.outcome = "unclear"
        job.reasoning_summary = job.reasoning_summary or "Stopped before producing a parseable answer."
        job.status = "done"
        return

    job.outcome = parsed.get("outcome", "unclear")
    job.prevailing_party = parsed.get("prevailing_party", "") or ""
    job.reasoning_summary = parsed.get("reasoning", "") or ""
    job.brief_text_found = parsed.get("brief_text") or None
    job.brief_source = parsed.get("brief_source", "") or ""

    if job.outcome == "prevailed" and job.brief_text_found:
        verify_candidate(
            app_config,
            candidate.id,
            "verified_winning",
            brief_text=job.brief_text_found,
            notes=f"Auto-researched: {job.reasoning_summary} (source: {job.brief_source or 'unspecified'})".strip(),
        )
        job.candidate_status_applied = "verified_winning"
    elif job.outcome == "did_not_prevail":
        verify_candidate(
            app_config,
            candidate.id,
            "verified_not_winning",
            notes=f"Auto-researched: {job.reasoning_summary}",
        )
        job.candidate_status_applied = "verified_not_winning"
    else:
        job.candidate_status_applied = ""  # left unverified for human review

    job.status = "done"
