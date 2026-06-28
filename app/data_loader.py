from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass(frozen=True)
class OpinionSample:
    id: str
    title: str
    text: str
    source: str
    source_type: str = "opinion"
    judge_name: str = ""
    court: str = ""
    year: str = ""
    focus: str = ""

    @property
    def preview(self) -> str:
        snippet = self.text.strip().replace("\n", " ")
        return snippet[:180] + ("..." if len(snippet) > 180 else "")


DEFAULT_SAMPLES = [
    OpinionSample(
        id="sample-1",
        title="Majority Opinion",
        text=(
            "The court finds that the defendant was not given adequate notice. "
            "The record was reviewed by the court and the argument was considered. "
            "In light of the foregoing, the request is denied because the language is repetitive and overly formal."
        ),
        source="bundled",
        source_type="opinion",
        judge_name="",
        court="Appellate",
        year="2024",
        focus="Notice, tone",
    ),
    OpinionSample(
        id="sample-2",
        title="Dissent Opinion",
        text=(
            "The opinion uses several long sentences that make the point harder to follow, "
            "and the phrasing is dense, cautious, and indirect. The court was presented with a cleaner alternative, "
            "but the draft still relied on unnecessary jargon and repeated ideas."
        ),
        source="bundled",
        source_type="opinion",
        judge_name="",
        court="Trial",
        year="2025",
        focus="Clarity, density",
    ),
]


JUDGE_NAME_PATTERNS = [
    re.compile(
        r"^\s*(?:majority\s+)?opinion\s+by\s+(?:the\s+)?(?:hon\.?\s+)?(?:judge|justice|chief judge|circuit judge|district judge|magistrate judge)\s+([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+)*)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:opinion|majority opinion)\s+by\s+([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+)*)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+)*),\s*(?:chief\s+)?(?:circuit|district|magistrate)?\s*judge\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+)*),\s*J\.\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:judge|justice)\s+([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+)*)\b", re.IGNORECASE),
]


def load_opinions(data_dir: str | Path | None) -> list[OpinionSample]:
    return load_documents(data_dir, source_type="opinion", default_samples=DEFAULT_SAMPLES, allowed_suffixes={".txt"})


def load_transcripts(data_dir: str | Path | None) -> list[OpinionSample]:
    return load_documents(data_dir, source_type="transcript", default_samples=[], allowed_suffixes={".txt", ".pdf"})


def load_documents(
    data_dir: str | Path | None,
    *,
    source_type: str,
    default_samples: list[OpinionSample],
    allowed_suffixes: set[str],
) -> list[OpinionSample]:
    if not data_dir:
        return list(default_samples)

    opinions_path = Path(data_dir)
    if not opinions_path.exists() or not opinions_path.is_dir():
        return list(default_samples)

    samples: list[OpinionSample] = []
    for path in sorted(opinions_path.iterdir()):
        if path.suffix.lower() not in allowed_suffixes:
            continue

        text = read_document_text(path)
        if not text:
            continue
        samples.append(
            OpinionSample(
                id=path.stem,
                title=path.stem.replace("_", " ").replace("-", " ").title(),
                text=text,
                source=str(path),
                source_type=source_type,
                judge_name=extract_judge_name(text),
                court="Uploaded file",
                year="",
                focus="Source opinion",
            )
        )

    return samples or list(default_samples)


def read_document_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        with path.open("rb") as pdf_file:
            reader = PdfReader(pdf_file)
            pages: list[str] = []

            for page in reader.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages.append(page_text.strip())

            return "\n\n".join(pages).strip()

    return path.read_text(encoding="utf-8").strip()


def get_opinion_by_id(samples: list[OpinionSample], sample_id: str) -> OpinionSample | None:
    for sample in samples:
        if sample.id == sample_id:
            return sample
    return None


def extract_judge_name(text: str) -> str:
    if not text.strip():
        return ""

    for line in text.splitlines():
        stripped_line = line.strip()
        if not stripped_line:
            continue

        for pattern in JUDGE_NAME_PATTERNS:
            match = pattern.search(stripped_line)
            if match:
                return normalize_judge_name(match.group(1))

    return ""


def normalize_judge_name(name: str) -> str:
    cleaned_name = re.sub(r"\s+", " ", name).strip()
    return cleaned_name
