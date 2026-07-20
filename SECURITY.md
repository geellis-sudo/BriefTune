# Security & Confidentiality

This document describes how BriefTune handles confidential material and what the deploying attorney or firm still needs to verify themselves. It is engineering/workflow guidance, not legal advice, and it is not a substitute for review by the firm's ethics/compliance counsel or IT security before the tool touches a real matter.

BriefTune processes draft briefs — privileged attorney work product. Everything below is written on that assumption.

## What stays local vs. what leaves the machine

**Stays local (never transmitted):**

- The raw uploaded draft. It is encrypted (Fernet, symmetric) and stored under `data/firm_confidential/` with a random filename. The plaintext is never written to disk.
- The firm winning-briefs folder, if configured. It is read fresh from disk at analysis time.
- The audit log (`data/audit.log`), style profiles, and all analysis results.
- The core analysis itself (style signals, affinity scoring, writing-quality checks) runs entirely in local Python — no network calls.

**Leaves the machine, only when the corresponding feature is used:**

- **Anthropic API** — two optional features call it, and only if `ANTHROPIC_API_KEY` is set in `.env`:
  - *AI Writing Coach* sends the **anonymized** draft text (see redaction below), never the raw upload.
  - *Auto-Research* sends text of public court opinions and brief-mention candidates pulled from CourtListener — public-record material, not client documents.
- **CourtListener API** — judge names, search queries, and opinion downloads. Public-records service; no client document content is sent.

## Redaction (anonymization) before any AI call

`app/privacy.py` redacts before the draft is indexed or sent anywhere:

- Every term the user lists in "Names or info to redact" (client names, companies, addresses), matched case-insensitively, longest-first.
- Social Security numbers, phone numbers, and email addresses — always, automatically.
- Case numbers and dollar figures are deliberately left visible (useful context, not privileged on their own).

**Known limitation:** redaction of names depends on the user listing them. An unlisted name sails through. Before using the AI Writing Coach on a sensitive draft, list every identifying term, or don't enable the feature for that draft.

## Vendor data agreement (the question this tool cannot answer)

Anonymized draft text goes to a third-party AI vendor (Anthropic) when AI features are used. Whether that is acceptable for privileged material depends on the agreement covering the API account whose key is in `.env` — ideally one with a zero-data-retention (ZDR) commitment and/or an appropriate data processing agreement (DPA), and a BAA if source material could contain protected health information.

This is not something the software can verify. Confirm it with the firm's IT/compliance function before running AI features on real matter documents. Until confirmed, the safe default is to leave `ANTHROPIC_API_KEY` unset — the app runs fully locally without it.

## Encryption at rest

- Uploads are encrypted with a Fernet key auto-generated at `data/firm_confidential.key`.
- **Limitation to understand:** the key sits on the same disk, adjacent to the encrypted files. This protects against casual reads and accidental cloud-sync/backup exposure of document contents, but not against an attacker with access to the whole `data/` directory. Full-disk encryption (FileVault) on the host machine is the real perimeter; keep it on.
- Do not commit `data/` to version control.

## Audit trail

Every upload, analysis run, judge sync, verification, AI call, and document deletion appends a JSON line to `data/audit.log` with a UTC timestamp. The log records filenames, sizes, event types, and costs — not document text and not API keys. Treat the log itself as confidential (filenames can be revealing).

## Retention and deletion

Encrypted uploads persist until deleted. The **Stored documents** page in the app lists every encrypted upload and provides per-document and delete-all controls; deletions are recorded in the audit log. There is no automatic expiry — deleting after a matter concludes is a manual step, and firms should fold it into their existing matter-closing/retention procedures. Confirm deletion practices are consistent with any litigation-hold or preservation obligations on the matter before purging.

## Regulatory/ethics context worth flagging for firm review

Not something this tool can certify — surface these to whoever signs off:

- **ABA Model Rules** 1.1 (technology competence), 1.6 (confidentiality — sending client information to a third-party AI vendor), and 5.3 (supervision of nonlawyer/technology assistance), plus the state-bar analogues and ethics opinions on generative AI, which vary by jurisdiction.
- **HIPAA**, if drafts quote protected health information — including whether a BAA with the AI vendor is needed.
- **Heightened handling for minors' identifying information** — list such names in the redaction field without exception.
- **Litigation hold / preservation** — BriefTune never modifies source documents, which is consistent with preservation duties, but confirm sufficiency against the specific hold order.

## Operational hygiene

- `SECRET_KEY` is `"dev"` in `app/__init__.py` — acceptable only for local single-user use. Set a real secret before any network-accessible deployment.
- The app binds to localhost by default; do not expose it to a network without adding authentication.
- Keep `.env` (API keys) out of version control and rotate keys that may have been exposed.
- Dependencies are pinned in `requirements.txt`; review before upgrading.

## What BriefTune deliberately does not do

It does not decide what is privileged, does not certify vendor compliance, and does not replace attorney judgment on any suggestion it makes. AI-generated output (Writing Coach suggestions, Auto-Research verdicts) is a first-pass read for attorney verification, not a finished product.
