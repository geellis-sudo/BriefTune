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


@dataclass(frozen=True)
class StoredDocument:
    stored_name: str  # e.g. "3fa4….enc" — basename only, never a path
    original_filename: str | None
    size_bytes: int
    stored_at: datetime


def _original_filename_map(config: dict[str, Any]) -> dict[str, str]:
    """Map encrypted-file basenames to original filenames by replaying the
    audit log. The log — not a separate manifest — is the source of truth
    for what each opaque .enc file was, so a missing/rotated log simply
    yields 'unknown' rather than an error."""
    mapping: dict[str, str] = {}
    audit_log_path = Path(config["AUDIT_LOG_PATH"])
    if not audit_log_path.exists():
        return mapping
    with audit_log_path.open("r", encoding="utf-8") as audit_file:
        for line in audit_file:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            encrypted_path = entry.get("encrypted_path")
            filename = entry.get("filename")
            if encrypted_path and filename:
                mapping[Path(encrypted_path).name] = filename
    return mapping


def list_firm_documents(config: dict[str, Any]) -> list[StoredDocument]:
    confidential_dir = Path(config["FIRM_CONFIDENTIAL_DIR"])
    if not confidential_dir.exists():
        return []
    names = _original_filename_map(config)
    documents = []
    for path in sorted(confidential_dir.glob("*.enc"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        documents.append(
            StoredDocument(
                stored_name=path.name,
                original_filename=names.get(path.name),
                size_bytes=stat.st_size,
                stored_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )
        )
    return documents


def delete_firm_document(config: dict[str, Any], stored_name: str) -> bool:
    """Delete one encrypted upload by basename. Returns True if deleted.

    The basename is validated against a strict pattern and re-anchored under
    the confidential dir, so a crafted value like "../firm_confidential.key"
    cannot escape."""
    if not re.fullmatch(r"[0-9a-f]{32}\.enc", stored_name):
        return False
    target = Path(config["FIRM_CONFIDENTIAL_DIR"]) / stored_name
    if not target.is_file():
        return False
    target.unlink()
    log_audit_event(config, "firm_document_deleted", stored_name=stored_name)
    return True


def delete_all_firm_documents(config: dict[str, Any]) -> int:
    deleted = 0
    for document in list_firm_documents(config):
        if delete_firm_document(config, document.stored_name):
            deleted += 1
    return deleted


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