from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analyzer import distinctive_terms, extract_brief_language_references, words_in

# Precedent-brief signal is capped a bit below the generic brief-reference signal
# (28) since it represents real judge-specific evidence but shouldn't fully
# dominate the score by itself.
MAX_PRECEDENT_BONUS = 25
TOP_TERMS_COUNT = 40

VALID_STATUSES = {"unverified", "verified_winning", "verified_not_winning", "rejected"}

# candidates.json can now be written concurrently -- bulk Auto-Research starts
# one background thread per flagged case, and a CourtListener sync can also be
# flagging new candidates at the same time. Without this lock, two threads
# doing read-modify-write on the same file can lose one another's update (the
# second writer's stale in-memory copy overwrites the first writer's change).
# Guards every read-modify-write cycle in this module; save_candidates itself
# writes atomically (temp file + os.replace) so any reader not holding the
# lock still never sees a torn/partial write.
_CANDIDATES_LOCK = threading.Lock()


@dataclass
class BriefMentionCandidate:
    id: str
    judge_id: str
    judge_name: str
    case_name: str
    cluster_id: int
    date_filed: str
    excerpts: list[str] = field(default_factory=list)
    status: str = "unverified"
    brief_text: str | None = None
    verified_at: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "judge_id": self.judge_id,
            "judge_name": self.judge_name,
            "case_name": self.case_name,
            "cluster_id": self.cluster_id,
            "date_filed": self.date_filed,
            "excerpts": self.excerpts,
            "status": self.status,
            "brief_text": self.brief_text,
            "verified_at": self.verified_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BriefMentionCandidate":
        return cls(
            id=data["id"],
            judge_id=data["judge_id"],
            judge_name=data["judge_name"],
            case_name=data["case_name"],
            cluster_id=data["cluster_id"],
            date_filed=data.get("date_filed", ""),
            excerpts=data.get("excerpts", []),
            status=data.get("status", "unverified"),
            brief_text=data.get("brief_text"),
            verified_at=data.get("verified_at"),
            notes=data.get("notes", ""),
        )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def load_candidates(app_config: dict[str, Any]) -> list[BriefMentionCandidate]:
    path = Path(app_config["BRIEF_MENTION_CANDIDATES_PATH"])
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    return [BriefMentionCandidate.from_dict(item) for item in data.get("candidates", [])]


def save_candidates(app_config: dict[str, Any], candidates: list[BriefMentionCandidate]) -> None:
    path = Path(app_config["BRIEF_MENTION_CANDIDATES_PATH"])
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write to a sibling temp file and rename into place. os.replace is atomic
    # on both POSIX and Windows, so a concurrent reader (e.g. the batch status
    # page polling while other jobs are still writing) always sees either the
    # fully-old or fully-new file, never a half-written one.
    tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(
        json.dumps({"candidates": [c.to_dict() for c in candidates]}, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp_path, path)


def get_candidate(app_config: dict[str, Any], candidate_id: str) -> BriefMentionCandidate | None:
    for candidate in load_candidates(app_config):
        if candidate.id == candidate_id:
            return candidate
    return None


def candidates_for_judge(
    app_config: dict[str, Any], judge_id: str, status: str | None = None
) -> list[BriefMentionCandidate]:
    candidates = [c for c in load_candidates(app_config) if c.judge_id == judge_id]
    if status:
        candidates = [c for c in candidates if c.status == status]
    return candidates


# ---------------------------------------------------------------------------
# Flagging (called automatically during CourtListener sync)
# ---------------------------------------------------------------------------

def flag_brief_mentions(
    app_config: dict[str, Any],
    judge_id: str,
    judge_name: str,
    cluster_id: int,
    case_name: str,
    date_filed: str,
    opinion_text: str,
) -> bool:
    """Check whether an opinion mentions a brief; if so, record it as an
    unverified candidate. Returns True if a new candidate was flagged.

    This is cheap (pure regex against text already fetched during sync) and
    makes no claim about who won -- that requires actual reading, which is
    why verification is a separate, human-or-agent-driven step.
    """
    references = extract_brief_language_references(opinion_text, source_type="opinion")
    if not references:
        return False

    candidate_id = f"{judge_id}-{cluster_id}"

    with _CANDIDATES_LOCK:
        candidates = load_candidates(app_config)

        if any(c.id == candidate_id for c in candidates):
            return False

        candidates.append(
            BriefMentionCandidate(
                id=candidate_id,
                judge_id=judge_id,
                judge_name=judge_name,
                case_name=case_name,
                cluster_id=cluster_id,
                date_filed=date_filed,
                excerpts=[ref.passage for ref in references[:5]],
                status="unverified",
            )
        )
        save_candidates(app_config, candidates)
        return True


# ---------------------------------------------------------------------------
# Verification (human/agent-recorded outcome)
# ---------------------------------------------------------------------------

def verify_candidate(
    app_config: dict[str, Any],
    candidate_id: str,
    status: str,
    brief_text: str | None = None,
    notes: str = "",
) -> BriefMentionCandidate | None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status!r}")

    with _CANDIDATES_LOCK:
        candidates = load_candidates(app_config)
        updated = None
        for candidate in candidates:
            if candidate.id == candidate_id:
                candidate.status = status
                candidate.notes = notes
                if brief_text and brief_text.strip():
                    candidate.brief_text = brief_text.strip()
                candidate.verified_at = datetime.now(timezone.utc).isoformat()
                updated = candidate

        if updated:
            save_candidates(app_config, candidates)
        return updated


def verified_winning_brief_texts(app_config: dict[str, Any], judge_id: str) -> list[str]:
    return [
        c.brief_text
        for c in candidates_for_judge(app_config, judge_id, status="verified_winning")
        if c.brief_text
    ]


def precedent_alignment_score(
    text: str,
    verified_brief_texts: list[str],
    source_description: str = "verified as prevailing before this judge",
    empty_message: str = "No verified winning briefs recorded for this judge yet.",
) -> tuple[int, list[str]]:
    """How much does `text` align with briefs already known to have won? Same
    low-tech vocabulary-overlap approach as style_profile.style_alignment_score,
    applied to a different corpus. Originally built for CourtListener-verified
    briefs tied to a specific judge, but the math doesn't care where the
    "known winning briefs" came from -- `source_description` and
    `empty_message` let callers (e.g. the firm-folder comparison, where the
    whole folder is trusted as wins by construction) get accurate wording
    without changing the judge path's defaults.
    """
    if not verified_brief_texts:
        return 0, [empty_message]

    terms = distinctive_terms(verified_brief_texts, TOP_TERMS_COUNT)
    if not terms:
        return 0, ["Verified briefs did not yield distinctive vocabulary to compare against."]

    words_lower = {word.lower() for word in words_in(text)}
    matched = [term for term, _count in terms if term in words_lower]
    ratio = len(matched) / len(terms)
    bonus = min(MAX_PRECEDENT_BONUS, int(ratio * 45))

    if matched:
        examples = ", ".join(matched[:5])
        factors = [
            f"Shares {len(matched)} of {len(terms)} distinctive terms from "
            f"{len(verified_brief_texts)} brief(s) {source_description}, "
            f"including {examples}."
        ]
    else:
        factors = [
            f"Shares none of the distinctive vocabulary from {len(verified_brief_texts)} "
            f"verified winning brief(s)."
        ]

    return bonus, factors
