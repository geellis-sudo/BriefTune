from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .analyzer import FRAMING_PATTERNS, split_sentences, words_in


# Small self-contained stopword list -- deliberately not a dependency (no nltk),
# consistent with the rest of this codebase's plain-regex approach.
STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "that", "is", "was", "for", "on", "as", "with", "by",
    "at", "from", "or", "and", "be", "this", "which", "it", "its", "but", "not", "are", "have",
    "has", "had", "will", "would", "shall", "should", "may", "might", "can", "could", "i", "we",
    "he", "she", "they", "them", "his", "her", "their", "our", "your", "you", "if", "than",
    "then", "so", "such", "these", "those", "there", "here", "who", "whom", "what", "when",
    "where", "why", "how", "all", "any", "each", "no", "nor", "only", "own", "same", "too",
    "very", "just", "also", "under", "over", "into", "about", "between", "because", "while",
    "during", "after", "before", "above", "below", "up", "down", "out", "off", "again",
    "further", "once", "been", "being", "do", "does", "did", "doing", "having", "must",
    "against", "other", "some", "more", "most", "were", "am", "not",
}

MIN_WORD_LENGTH = 3
TOP_TERMS_COUNT = 40
MAX_STYLE_BONUS = 20


@dataclass
class StyleProfile:
    judge_name: str
    opinion_count: int
    top_terms: list[tuple[str, int]]
    avg_sentence_length: float
    framing_hit_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "judge_name": self.judge_name,
            "opinion_count": self.opinion_count,
            "top_terms": [list(item) for item in self.top_terms],
            "avg_sentence_length": self.avg_sentence_length,
            "framing_hit_rate": self.framing_hit_rate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StyleProfile":
        return cls(
            judge_name=data["judge_name"],
            opinion_count=data["opinion_count"],
            top_terms=[tuple(item) for item in data.get("top_terms", [])],
            avg_sentence_length=data.get("avg_sentence_length", 0.0),
            framing_hit_rate=data.get("framing_hit_rate", 0.0),
        )


def build_style_profile(judge_name: str, opinion_texts: list[str]) -> StyleProfile | None:
    """Aggregate a judge-specific vocabulary/style fingerprint from their own opinion texts.

    Deliberately low-tech: word-frequency counting and simple pattern matching,
    no embeddings or external models -- mirrors the rest of analyzer.py.
    """
    cleaned_texts = [text for text in opinion_texts if text and text.strip()]
    if not cleaned_texts:
        return None

    word_counts: Counter[str] = Counter()
    sentence_lengths: list[int] = []
    framing_hits = 0

    for text in cleaned_texts:
        words = [
            word.lower()
            for word in words_in(text)
            if len(word) >= MIN_WORD_LENGTH and word.lower() not in STOPWORDS
        ]
        word_counts.update(words)

        for sentence in split_sentences(text):
            word_count = len(words_in(sentence))
            if word_count:
                sentence_lengths.append(word_count)

        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in FRAMING_PATTERNS):
            framing_hits += 1

    avg_sentence_length = (
        sum(sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0.0
    )

    return StyleProfile(
        judge_name=judge_name,
        opinion_count=len(cleaned_texts),
        top_terms=word_counts.most_common(TOP_TERMS_COUNT),
        avg_sentence_length=avg_sentence_length,
        framing_hit_rate=framing_hits / len(cleaned_texts),
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def style_profile_path(app_config: dict[str, Any], judge_name: str) -> Path:
    from .courtlistener_sync import slugify

    base = Path(app_config["JUDGE_STYLE_PROFILE_DIR"])
    return base / f"{slugify(judge_name)}.json"


def save_style_profile(app_config: dict[str, Any], profile: StyleProfile) -> None:
    path = style_profile_path(app_config, profile.judge_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")


def load_style_profile(app_config: dict[str, Any], judge_name: str) -> StyleProfile | None:
    path = style_profile_path(app_config, judge_name)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    return StyleProfile.from_dict(data)


def rebuild_style_profile_from_folder(
    app_config: dict[str, Any], judge_name: str, folder: Path
) -> StyleProfile | None:
    """Recompute a judge's style profile from every .txt file in their corpus folder."""
    texts: list[str] = []
    if folder.exists():
        for path in sorted(folder.rglob("*.txt")):
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                texts.append(text)

    profile = build_style_profile(judge_name, texts)
    if profile:
        save_style_profile(app_config, profile)
    return profile


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def style_alignment_score(
    text: str,
    profile: StyleProfile | None,
    unit_label: str = "opinion",
    no_profile_message: str = "No judge style profile available yet -- track and sync this judge first.",
) -> tuple[int, list[str]]:
    """How much does `text` align with a specific corpus's actual vocabulary and cadence?

    Returns (bonus capped at MAX_STYLE_BONUS, human-readable factor strings).
    Unlike the generic vocabulary/framing signals in analyzer.py, this compares
    against a real corpus rather than a fixed word list. Originally built for
    judge opinions, but the underlying math doesn't care what the corpus is --
    `unit_label` and `no_profile_message` let callers (e.g. the firm-folder
    comparison) get accurate wording ("brief" instead of "opinion", etc.)
    without changing behavior for the judge path, which keeps its defaults.
    """
    if not profile or not profile.top_terms:
        return 0, [no_profile_message]

    factors: list[str] = []
    words_lower = {word.lower() for word in words_in(text)}
    matched_terms = [term for term, _count in profile.top_terms if term in words_lower]
    match_ratio = len(matched_terms) / len(profile.top_terms)

    bonus = min(MAX_STYLE_BONUS, int(match_ratio * 40))
    if matched_terms:
        examples = ", ".join(matched_terms[:5])
        factors.append(
            f"Shares {len(matched_terms)} of {profile.judge_name}'s {len(profile.top_terms)} "
            f"most distinctive terms (from {profile.opinion_count} ingested {unit_label}(s)), "
            f"including {examples}."
        )
    else:
        factors.append(
            f"Shares none of {profile.judge_name}'s distinctive vocabulary terms from "
            f"{profile.opinion_count} ingested {unit_label}(s)."
        )

    sentences = split_sentences(text)
    if sentences and profile.avg_sentence_length:
        avg_len = sum(len(words_in(sentence)) for sentence in sentences) / len(sentences)
        if abs(avg_len - profile.avg_sentence_length) <= 5:
            bonus = min(MAX_STYLE_BONUS, bonus + 4)
            factors.append(
                f"Sentence length ({avg_len:.0f} words avg) is close to {profile.judge_name}'s "
                f"typical {profile.avg_sentence_length:.0f}-word sentences."
            )

    return bonus, factors
