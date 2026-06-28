from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Issue:
    category: str
    sentence: str
    suggestion: str
    detail: str = ""
    weight: int = 1


@dataclass(frozen=True)
class AnalysisSummary:
    affinity_score: int
    affinity_explanation: str
    affinity_factors: list[str]


@dataclass(frozen=True)
class WritingQualityFlag:
    category: str
    example: str
    suggestion: str
    weight: int = 1


@dataclass(frozen=True)
class WritingQualitySummary:
    writing_quality_score: int
    writing_quality_explanation: str
    writing_quality_flags: list[WritingQualityFlag]
    writing_quality_factors: list[str]


@dataclass(frozen=True)
class BriefLanguageReference:
    passage: str
    signal: str
    source_sentence: str
    source_type: str = "opinion"
    weight: int = 3


JARGON_PATTERNS = [
    (r"\bhereinafter\b", "Replace hereinafter with a plain reference."),
    (r"\baforementioned\b", "Replace aforementioned with the specific noun."),
    (r"\bpursuant to\b", "Consider a shorter alternative to pursuant to."),
    (r"\bnotwithstanding\b", "Consider a simpler alternative to notwithstanding."),
    (r"\butilize\b", "Use use instead of utilize."),
]

WEAKENERS = [
    (r"\bvery\b", "very"),
    (r"\breally\b", "really"),
    (r"\bquite\b", "quite"),
    (r"\bas a result of\b", "as a result of"),
    (r"\bin order to\b", "in order to"),
]

NOMINALIZATIONS = [
    (r"\bimplementation\b", "implement"),
    (r"\butilization\b", "use"),
    (r"\bconsideration\b", "consider"),
    (r"\bprovision\b", "provide"),
    (r"\bdetermination\b", "determine"),
]

BRIEF_REFERENCE_TERMS = [
    r"brief",
    r"appellant'?s brief",
    r"appellee'?s brief",
    r"respondent'?s brief",
    r"prevailing party'?s brief",
    r"prevailing party",
]

BRIEF_REFERENCE_VERBS = [
    r"quote",
    r"quoted",
    r"cites?",
    r"cite[s/d]?",
    r"reference",
    r"references",
    r"referenced",
    r"argue",
    r"argued",
    r"contend",
    r"contended",
    r"assert",
    r"asserted",
    r"maintain",
    r"maintained",
    r"state",
    r"stated",
    r"claim",
    r"claimed",
    r"note",
    r"noted",
    r"explain",
    r"explained",
    r"say",
    r"said",
]

OPINION_STYLE_TERMS = [
    "court",
    "record",
    "foregoing",
    "conclude",
    "concludes",
    "hold",
    "holds",
    "grant",
    "grants",
    "deny",
    "denies",
    "because",
    "therefore",
    "reasoning",
    "majority",
    "opinion",
    "argument",
]

FRAMING_PATTERNS = [
    r"\bthe court\b",
    r"\bwe conclude\b",
    r"\bwe hold\b",
    r"\bin light of\b",
    r"\bthe issue\b",
    r"\bthe record\b",
    r"\bthe argument\b",
    r"\bas the court noted\b",
]

TRANSCRIPT_MARKERS = [
    "counsel",
    "judge",
    "justice",
    "your honor",
    "let me",
    "what about",
    "questions",
    "question",
    "answer",
]

WRITING_QUALITY_NOMINALIZATION_PATTERNS = [
    (r"\bmake a determination\b", "determine"),
    (r"\breach a conclusion\b", "conclude"),
    (r"\bprovide an explanation\b", "explain"),
    (r"\btake into consideration\b", "consider"),
    (r"\bconduct an analysis\b", "analyze"),
    (r"\bmake an argument\b", "argue"),
    (r"\bgive consideration to\b", "consider"),
    (r"\bhave a discussion\b", "discuss"),
    (r"\bperform a review\b", "review"),
]

WRITING_QUALITY_HEDGES = [
    (r"\bit would seem\b", "Replace 'it would seem' with a direct statement if the point is already clear."),
    (r"\barguably\b", "Remove 'arguably' unless you need to qualify a contested point."),
    (r"\bapparently\b", "Delete 'apparently' if the sentence can stand without hedging."),
    (r"\bperhaps\b", "Remove 'perhaps' if the sentence can be stated directly."),
    (r"\bmay(?:be)?\b", "Consider whether 'may' or 'maybe' is weakening the point."),
    (r"\bpossibly\b", "Remove 'possibly' if the claim can be stated with confidence."),
    (r"\bto some extent\b", "Trim 'to some extent' to sharpen the point."),
    (r"\bseems?\b", "Replace 'seems' with a direct assertion when the record supports it."),
    (r"\bappears?\b", "Replace 'appears' with a firmer statement if appropriate."),
]

BURIED_CITATION_PATTERNS = [
    re.compile(r"\bsee\b.*\([^)]*(?:\d{4}|F\.|U\.S\.|S\.Ct\.).*\)", re.IGNORECASE),
    re.compile(r"\b(?:[A-Z][A-Za-z.&']+\s+v\.\s+[A-Z][A-Za-z.&']+)[^\n]*\([^)]*\d{4}[^)]*\)", re.IGNORECASE),
    re.compile(r"\b(?:[A-Z][A-Za-z.&']+\s+v\.\s+[A-Z][A-Za-z.&']+)[^\n]*,\s*\d+\s+[A-Z][A-Za-z.]+\s+\d+", re.IGNORECASE),
]

QUOTE_PATTERN = re.compile(r"[\"“](.+?)[\"”]")


def analyze_text(text: str, source_type: str = "opinion") -> dict:
    cleaned_text = text.strip()
    sentences = split_sentences(cleaned_text)
    issues: list[Issue] = []
    brief_language_references = extract_brief_language_references(cleaned_text, source_type=source_type)
    writing_quality_flags = collect_writing_quality_flags(cleaned_text, sentences)
    word_count = len(words_in(cleaned_text))

    for sentence in sentences:
        word_total = len(words_in(sentence))
        if word_total > 25:
            issues.append(
                Issue(
                    category="Long sentence",
                    sentence=sentence,
                    suggestion="Split this sentence into two shorter sentences.",
                    detail=f"{word_total} words in a single sentence",
                )
            )

        if looks_passive(sentence):
            issues.append(
                Issue(
                    category="Passive voice",
                    sentence=sentence,
                    suggestion="Try naming the actor directly and using an active verb.",
                    detail="Look for a subject that can take ownership of the action.",
                )
            )

        for pattern, suggestion in JARGON_PATTERNS:
            if re.search(pattern, sentence, flags=re.IGNORECASE):
                issues.append(
                    Issue(
                        category="Dense legal wording",
                        sentence=sentence,
                        suggestion=suggestion,
                        detail="A simpler phrase will usually read more directly.",
                    )
                )
                break

        for pattern, replacement in WEAKENERS:
            if re.search(pattern, sentence, flags=re.IGNORECASE):
                issues.append(
                    Issue(
                        category="Hedging",
                        sentence=sentence,
                        suggestion=f"Cut '{replacement}' if the sentence is still accurate without it.",
                        detail="Tightening filler words makes the argument sound more confident.",
                    )
                )
                break

        for pattern, replacement in NOMINALIZATIONS:
            if re.search(pattern, sentence, flags=re.IGNORECASE):
                issues.append(
                    Issue(
                        category="Nominalization",
                        sentence=sentence,
                        suggestion=f"Try rewriting around '{replacement}' as the main verb.",
                        detail="Verb-based phrasing tends to be clearer and shorter.",
                    )
                )
                break

    for reference in brief_language_references:
        issues.append(
            Issue(
                category="Brief language reference",
                sentence=reference.passage,
                suggestion=f"Treat this {source_type_label(reference.source_type)} language as especially important when revising your brief.",
                detail=reference.signal,
                weight=reference.weight,
            )
        )

    repeated_phrase = find_repeated_phrase(cleaned_text)
    if repeated_phrase:
        issues.append(
            Issue(
                category="Repetition",
                sentence=repeated_phrase,
                suggestion="Reduce repeated phrasing so the point lands once, clearly.",
                detail="Repeated three-word phrases often signal a drafting loop.",
            )
        )

    weighted_issue_total = sum(issue.weight for issue in issues)
    summary = build_summary(
        cleaned_text,
        word_count,
        len(sentences),
        weighted_issue_total,
        len(brief_language_references),
        source_type,
    )
    writing_quality = build_writing_quality_summary(cleaned_text, writing_quality_flags)

    return {
        "word_count": word_count,
        "sentence_count": len(sentences),
        "issues": issues,
        "brief_language_references": brief_language_references,
        "source_type": source_type,
        "summary": summary,
        "writing_quality": writing_quality,
    }


def split_sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [part.strip() for part in parts if part.strip()]


def words_in(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text)


def looks_passive(sentence: str) -> bool:
    passive_patterns = [
        r"\b(?:was|were|is|are|been|be|being)\s+[A-Za-z]+ed\b",
        r"\b(?:was|were|is|are|been|be|being)\s+made\b",
        r"\b(?:was|were|is|are|been|be|being)\s+given\b",
    ]
    return any(re.search(pattern, sentence, flags=re.IGNORECASE) for pattern in passive_patterns)


def find_repeated_phrase(text: str) -> str | None:
    words = [word.lower() for word in words_in(text)]
    if len(words) < 6:
        return None

    phrase_counts = Counter()
    phrase_lookup: dict[str, str] = {}
    for index in range(len(words) - 2):
        phrase = " ".join(words[index:index + 3])
        phrase_counts[phrase] += 1
        phrase_lookup.setdefault(phrase, " ".join(words[index:index + 3]))

    repeated = [phrase for phrase, count in phrase_counts.items() if count > 1]
    if not repeated:
        return None

    return phrase_lookup[repeated[0]]


def extract_brief_language_references(text: str, source_type: str = "opinion") -> list[BriefLanguageReference]:
    references: list[BriefLanguageReference] = []
    seen_passages: set[str] = set()

    for sentence in split_sentences(text):
        normalized_sentence = sentence.strip()
        if not normalized_sentence:
            continue

        has_brief_terms = any(re.search(term, normalized_sentence, flags=re.IGNORECASE) for term in BRIEF_REFERENCE_TERMS)
        has_reference_verbs = any(re.search(verb, normalized_sentence, flags=re.IGNORECASE) for verb in BRIEF_REFERENCE_VERBS)
        quote_matches = [match.strip() for match in QUOTE_PATTERN.findall(normalized_sentence)]

        if quote_matches and (has_brief_terms or has_reference_verbs):
            for quote in quote_matches:
                normalized_quote = normalize_excerpt(quote)
                if normalized_quote and normalized_quote not in seen_passages:
                    references.append(
                        BriefLanguageReference(
                            passage=normalized_quote,
                            signal=f"Quoted language tied to a {source_type_label(source_type)} reference.",
                            source_sentence=normalized_sentence,
                            source_type=source_type,
                        )
                    )
                    seen_passages.add(normalized_quote)
            continue

        if has_brief_terms and has_reference_verbs:
            normalized_excerpt = normalize_excerpt(normalized_sentence)
            if normalized_excerpt and normalized_excerpt not in seen_passages:
                references.append(
                    BriefLanguageReference(
                        passage=normalized_excerpt,
                        signal=f"Sentence references or paraphrases language from a {source_type_label(source_type)}.",
                        source_sentence=normalized_sentence,
                        source_type=source_type,
                    )
                )
                seen_passages.add(normalized_excerpt)

    return references


def normalize_excerpt(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def collect_writing_quality_flags(text: str, sentences: list[str]) -> list[WritingQualityFlag]:
    flags: list[WritingQualityFlag] = []
    seen: set[tuple[str, str]] = set()

    for sentence in sentences:
        normalized_sentence = sentence.strip()
        if not normalized_sentence:
            continue

        for pattern, replacement in WRITING_QUALITY_NOMINALIZATION_PATTERNS:
            match = re.search(pattern, normalized_sentence, flags=re.IGNORECASE)
            if match:
                example = match.group(0)
                key = ("nominalization", example.lower())
                if key not in seen:
                    flags.append(
                        WritingQualityFlag(
                            category="Nominalization",
                            example=example,
                            suggestion=f"Replace '{example}' with '{replacement}'.",
                            weight=10,
                        )
                    )
                    seen.add(key)

        if looks_passive(normalized_sentence):
            key = ("passive", normalized_sentence.lower())
            if key not in seen:
                flags.append(
                    WritingQualityFlag(
                        category="Passive voice",
                        example=normalized_sentence,
                        suggestion="Rewrite this sentence so the actor comes first and the verb is active.",
                        weight=12,
                    )
                )
                seen.add(key)

        for pattern, suggestion in WRITING_QUALITY_HEDGES:
            match = re.search(pattern, normalized_sentence, flags=re.IGNORECASE)
            if match:
                example = match.group(0)
                key = ("hedging", example.lower())
                if key not in seen:
                    flags.append(
                        WritingQualityFlag(
                            category="Hedging",
                            example=example,
                            suggestion=suggestion,
                            weight=8,
                        )
                    )
                    seen.add(key)

        buried_citation = find_buried_citation(normalized_sentence)
        if buried_citation:
            key = ("citation", normalized_sentence.lower())
            if key not in seen:
                flags.append(
                    WritingQualityFlag(
                        category="Buried citation",
                        example=normalized_sentence,
                        suggestion="Move the citation to the end of the sentence or into a parenthetical so the core argument stays front and center.",
                        weight=14,
                    )
                )
                seen.add(key)

        word_total = len(words_in(normalized_sentence))
        if word_total > 40:
            key = ("long", normalized_sentence.lower())
            if key not in seen:
                flags.append(
                    WritingQualityFlag(
                        category="Long sentence",
                        example=normalized_sentence,
                        suggestion="Split this sentence; a 40+ word sentence is hard to scan and usually hides the main point.",
                        weight=7,
                    )
                )
                seen.add(key)

    for buried_citation in find_buried_citation_examples(text):
        key = ("citation-full", buried_citation.lower())
        if key in seen:
            continue
        flags.append(
            WritingQualityFlag(
                category="Buried citation",
                example=buried_citation,
                suggestion="Move the citation to the end of the sentence or into a parenthetical so the core argument stays front and center.",
                weight=14,
            )
        )
        seen.add(key)

    return flags


def find_buried_citation(sentence: str) -> str | None:
    for pattern in BURIED_CITATION_PATTERNS:
        match = pattern.search(sentence)
        if not match:
            continue

        suffix = sentence[match.end():].strip(" ,.;:)")
        prefix = sentence[:match.start()].strip(" ,.;:(")
        if suffix and len(words_in(prefix)) >= 5:
            return match.group(0)

    return None


def find_buried_citation_examples(text: str) -> list[str]:
    matches: list[str] = []

    for pattern in BURIED_CITATION_PATTERNS:
        for match in pattern.finditer(text):
            suffix = text[match.end():].strip(" ,.;:)")
            prefix = text[:match.start()].strip(" ,.;:(")
            if suffix and len(words_in(prefix)) >= 5:
                matches.append(match.group(0))

    return matches


def source_type_label(source_type: str) -> str:
    if source_type == "transcript":
        return "transcript-linked"
    return "opinion-linked"


def build_writing_quality_summary(text: str, flags: list[WritingQualityFlag]) -> WritingQualitySummary:
    score = 100
    factors: list[str] = []

    if not flags:
        return WritingQualitySummary(
            writing_quality_score=score,
            writing_quality_explanation="No major legal-writing problems were detected, so the draft stays close to the principles that usually make a brief easier to read.",
            writing_quality_flags=[],
            writing_quality_factors=["No nominalizations, passive constructions, buried citations, or 40+ word sentences were detected."],
        )

    category_counts: dict[str, int] = {}
    category_examples: dict[str, list[str]] = {}

    for flag in flags:
        score -= flag.weight
        category_counts[flag.category] = category_counts.get(flag.category, 0) + 1
        category_examples.setdefault(flag.category, [])
        if flag.example not in category_examples[flag.category]:
            category_examples[flag.category].append(flag.example)

    score = max(0, score)

    if category_counts.get("Nominalization"):
        examples = format_examples(category_examples["Nominalization"][:3])
        factors.append(
            f"Nominalizations like {examples} make the prose more abstract than it needs to be."
        )
    if category_counts.get("Passive voice"):
        examples = format_examples(category_examples["Passive voice"][:2])
        factors.append(
            f"Passive voice appears in sentences such as {examples}, which can blur who is doing what."
        )
    if category_counts.get("Buried citation"):
        examples = format_examples(category_examples["Buried citation"][:2])
        factors.append(
            f"Citations buried mid-sentence, like {examples}, make the argument harder to follow."
        )
    if category_counts.get("Hedging"):
        examples = format_examples(category_examples["Hedging"][:3])
        factors.append(
            f"Hedging words such as {examples} weaken the force of the statement."
        )
    if category_counts.get("Long sentence"):
        examples = format_examples(category_examples["Long sentence"][:2])
        factors.append(
            f"Sentences like {examples} run past 40 words, which makes the core point harder to scan quickly."
        )

    strongest = max(category_counts.items(), key=lambda item: item[1])
    explanation = (
        f"The score is down mainly because of {strongest[1]} {strongest[0].lower()} issue(s), plus a total of {len(flags)} writing-quality flags across the draft."
    )

    return WritingQualitySummary(
        writing_quality_score=score,
        writing_quality_explanation=explanation,
        writing_quality_flags=flags,
        writing_quality_factors=factors,
    )


def build_summary(
    text: str,
    word_count: int,
    sentence_count: int,
    weighted_issue_total: int,
    brief_reference_count: int,
    source_type: str,
) -> AnalysisSummary:
    affinity_score = 50
    factors: list[str] = []

    average_sentence_length = word_count / sentence_count if sentence_count else 0

    vocabulary_hits, vocabulary_examples = count_matches(text, OPINION_STYLE_TERMS)
    vocabulary_bonus = min(18, vocabulary_hits * 3)
    if vocabulary_bonus:
        affinity_score += vocabulary_bonus
        factors.append(
            f"Uses opinion-style vocabulary such as {format_examples(vocabulary_examples)}."
        )
    else:
        affinity_score -= 6
        factors.append("Uses few opinion-style terms, so the style signal is lighter.")

    framing_hits, framing_examples = count_regex_matches(text, FRAMING_PATTERNS)
    framing_bonus = min(18, framing_hits * 4)
    if framing_bonus:
        affinity_score += framing_bonus
        factors.append(
            f"Frames the issues in a way that resembles majority-opinion reasoning, especially around {format_examples(framing_examples)}."
        )
    else:
        affinity_score -= 4
        factors.append("Shows little majority-opinion framing, so the alignment signal is thinner.")

    if brief_reference_count:
        brief_bonus = min(28, brief_reference_count * 18)
        affinity_score += brief_bonus
        factors.append(
            f"Quotes or references {brief_reference_count} brief-linked passage(s), which strongly boosts affinity when the judge echoes that language."
        )
    else:
        affinity_score -= 8
        factors.append("No brief-linked quotations or references were detected, so that signal is missing.")

    transcript_bonus = 0
    if source_type == "transcript":
        transcript_hits, _ = count_matches(text, TRANSCRIPT_MARKERS)
        transcript_bonus = min(16, transcript_hits * 4)
        if transcript_bonus:
            affinity_score += transcript_bonus
            factors.append(
                "Oral-argument transcript cues surface how the judge questions and responds, which adds preference signal."
            )
        else:
            affinity_score += 6
            factors.append(
                "This comes from an oral-argument transcript, so it still supplies useful preference signal even without many conversational markers."
            )

    if 14 <= average_sentence_length <= 28:
        affinity_score += 10
        factors.append("Sentence cadence is balanced enough to sound close to a polished judicial voice.")
    elif average_sentence_length < 12:
        affinity_score -= 4
        factors.append("Very short sentences reduce the judge-style signal.")
    elif average_sentence_length > 35:
        affinity_score -= 8
        factors.append("Very long sentences make the style signal harder to use.")

    if weighted_issue_total >= 10:
        affinity_score -= 12
        factors.append("The draft has enough drafting issues that the style signal is diluted.")
    elif weighted_issue_total >= 5:
        affinity_score -= 6
        factors.append("A few drafting issues still pull the style signal down.")

    affinity_score = max(0, min(100, affinity_score))

    if brief_reference_count:
        explanation = (
            f"Strongest signal: the {source_type_label(source_type)} text quotes or references brief language, so those passages carry extra weight."
        )
        if transcript_bonus:
            explanation += " Transcript cues also contribute to the score because they reveal oral-argument style preferences."
    elif source_type == "transcript":
        explanation = (
            "The score is driven mainly by oral-argument transcript cues, opinion-style vocabulary, and framing choices that hint at how the judge prefers issues to be presented."
        )
    else:
        explanation = (
            "The score is driven mainly by opinion-style vocabulary, issue framing, and sentence cadence, with no brief-linked quotations found to push it higher."
        )

    return AnalysisSummary(
        affinity_score=affinity_score,
        affinity_explanation=explanation,
        affinity_factors=factors,
    )


def count_matches(text: str, terms: list[str]) -> tuple[int, list[str]]:
    lowered_text = text.lower()
    hits = 0
    examples: list[str] = []

    for term in terms:
        if term in lowered_text:
            hits += 1
            examples.append(term)

    return hits, examples


def count_regex_matches(text: str, patterns: list[str]) -> tuple[int, list[str]]:
    hits = 0
    examples: list[str] = []

    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits += 1
            examples.append(pattern.replace(r"\\b", "").replace("\\", "").strip("^$") or pattern)

    return hits, examples


def format_examples(examples: list[str]) -> str:
    cleaned = [example.replace("\\", "").strip() for example in examples if example]
    if not cleaned:
        return "that wording"
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{cleaned[0]}, {cleaned[1]}, and {len(cleaned) - 2} others"
