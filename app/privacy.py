from __future__ import annotations

import json
import re
import uuid
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet


AMOUNT_PATTERN = re.compile(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?")
CASE_NUMBER_PATTERNS = [
    re.compile(r"\b(?:case\s+no\.?|cause\s+no\.?|docket\s+no\.?|no\.?|dkt\.?|file\s+no\.?)\s*[:#-]?\s*[A-Za-z0-9][A-Za-z0-9\-./]*", re.IGNORECASE),
    re.compile(r"\b\d{2,4}[-–][A-Z]{1,4}[-–]\d{1,6}\b"),
    re.compile(r"\b\d{1,6}[:/\-]\d{1,6}[:/\-]\d{1,6}\b"),
]
NAME_SEQUENCE_PATTERN = re.compile(r"\b(?:[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?)(?:\s+(?:[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?))+\b")
HONORIFIC_NAME_PATTERN = re.compile(r"\b(?:Judge|Justice|Mr|Mrs|Ms|Dr)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b")
SINGLE_NAME_PATTERN = re.compile(r"\b[A-Z][a-z]{2,}\b")
UPPER_ACRONYM_PATTERN = re.compile(r"\b[A-Z]{2,}\b")

PROPER_NOUN_KEEPERS = {
    "The",
    "A",
    "An",
    "This",
    "That",
    "These",
    "Those",
    "When",
    "Where",
    "While",
    "Because",
    "If",
    "In",
    "On",
    "At",
    "After",
    "Before",
    "As",
    "By",
    "For",
    "From",
    "To",
    "And",
    "But",
    "Or",
    "Nor",
    "Yet",
    "So",
    "Court",
    "Judge",
    "Justice",
    "Opinion",
    "Record",
    "Brief",
    "Motion",
    "Order",
    "Counsel",
    "Plaintiff",
    "Defendant",
    "Appellant",
    "Appellee",
    "Petitioner",
    "Respondent",
    "United",
    "States",
    "State",
    "Federal",
}


@dataclass(frozen=True)
class FirmDocumentArtifact:
    original_filename: str
    encrypted_path: Path
    anonymized_text: str
    upload_size: int


def ensure_privacy_storage(config: dict[str, Any]) -> None:
    confidential_dir = Path(config["FIRM_CONFIDENTIAL_DIR"])
    confidential_dir.mkdir(parents=True, exist_ok=True)

    audit_log_path = Path(config["AUDIT_LOG_PATH"])
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)

    key_path = Path(config["FIRM_CONFIDENTIAL_KEY_PATH"])
    key_path.parent.mkdir(parents=True, exist_ok=True)


def anonymize_firm_text(text: str) -> str:
    anonymized = text
    anonymized = AMOUNT_PATTERN.sub("[AMOUNT]", anonymized)

    for pattern in CASE_NUMBER_PATTERNS:
        anonymized = pattern.sub("[CASE_NUMBER]", anonymized)

    anonymized = HONORIFIC_NAME_PATTERN.sub("[PROPER_NOUN]", anonymized)
    anonymized = NAME_SEQUENCE_PATTERN.sub("[PROPER_NOUN]", anonymized)
    anonymized = anonymized.replace(" v. ", " [CITATION] ")

    anonymized = replace_remaining_proper_nouns(anonymized)
    anonymized = re.sub(r"\s+", " ", anonymized).strip()

    return anonymized


def replace_remaining_proper_nouns(text: str) -> str:
    tokens = re.findall(r"\s+|\w+|[^\w\s]", text)
    anonymized_tokens: list[str] = []

    for token in tokens:
        if token.isspace() or not token:
            anonymized_tokens.append(token)
            continue

        if UPPER_ACRONYM_PATTERN.fullmatch(token):
            anonymized_tokens.append(token)
            continue

        if SINGLE_NAME_PATTERN.fullmatch(token) and token not in PROPER_NOUN_KEEPERS:
            anonymized_tokens.append("[PROPER_NOUN]")
            continue

        anonymized_tokens.append(token)

    return "".join(anonymized_tokens)


def store_firm_document(config: dict[str, Any], original_filename: str, raw_text: str) -> FirmDocumentArtifact:
    confidential_dir = Path(config["FIRM_CONFIDENTIAL_DIR"])
    confidential_dir.mkdir(parents=True, exist_ok=True)

    encrypted_path = confidential_dir / f"{uuid.uuid4().hex}.enc"
    encrypted_path.write_bytes(get_fernet(config).encrypt(raw_text.encode("utf-8")))

    return FirmDocumentArtifact(
        original_filename=original_filename,
        encrypted_path=encrypted_path,
        anonymized_text=anonymize_firm_text(raw_text),
        upload_size=len(raw_text.encode("utf-8")),
    )


def log_audit_event(config: dict[str, Any], event_type: str, **details: Any) -> None:
    audit_log_path = Path(config["AUDIT_LOG_PATH"])
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        **details,
    }
    with audit_log_path.open("a", encoding="utf-8") as audit_file:
        audit_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_fernet(config: dict[str, Any]) -> Fernet:
    key_path = Path(config["FIRM_CONFIDENTIAL_KEY_PATH"])
    if key_path.exists():
        key = key_path.read_bytes()
    else:
        key = Fernet.generate_key()
        key_path.write_bytes(key)

    if len(key) != 44:
        key = urlsafe_b64encode(key[:32].ljust(32, b"0"))

    return Fernet(key)