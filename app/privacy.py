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


SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
PHONE_PATTERN = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


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


def anonymize_firm_text(text: str, manual_terms: list[str] | None = None) -> str:
    """Redact client-supplied terms plus structured PII (SSN/phone/email).

    This is a targeted redaction, not a blanket proper-noun stripper: only
    terms explicitly listed by the caller (e.g. the client's name and any
    aliases, typed into the "Names or info to redact" field) get redacted
    as names. Case numbers and dollar figures are intentionally left
    visible -- they're useful context for the analysis and aren't treated
    as privileged on their own. Social Security numbers, phone numbers, and
    email addresses are always redacted automatically, regardless of
    whether they were listed, since those formats are reliably detectable
    and essentially never appropriate to leave in.
    """
    anonymized = text

    for term in _prepare_manual_terms(manual_terms or []):
        pattern = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
        anonymized = pattern.sub("[REDACTED]", anonymized)

    anonymized = SSN_PATTERN.sub("[SSN]", anonymized)
    anonymized = PHONE_PATTERN.sub("[PHONE]", anonymized)
    anonymized = EMAIL_PATTERN.sub("[EMAIL]", anonymized)

    anonymized = re.sub(r"\s+", " ", anonymized).strip()
    return anonymized


def _prepare_manual_terms(terms: list[str]) -> list[str]:
    cleaned = [term.strip() for term in terms if term and term.strip()]
    # Longest first so e.g. "John Smith" gets redacted whole before a
    # separately-listed "Smith" would otherwise partially match inside it.
    cleaned.sort(key=len, reverse=True)
    return cleaned


def store_firm_document(
    config: dict[str, Any],
    original_filename: str,
    raw_text: str,
    manual_terms: list[str] | None = None,
) -> FirmDocumentArtifact:
    confidential_dir = Path(config["FIRM_CONFIDENTIAL_DIR"])
    confidential_dir.mkdir(parents=True, exist_ok=True)

    encrypted_path = confidential_dir / f"{uuid.uuid4().hex}.enc"
    encrypted_path.write_bytes(get_fernet(config).encrypt(raw_text.encode("utf-8")))

    return FirmDocumentArtifact(
        original_filename=original_filename,
        encrypted_path=encrypted_path,
        anonymized_text=anonymize_firm_text(raw_text, manual_terms),
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