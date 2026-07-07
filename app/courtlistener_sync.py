from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .brief_candidates import flag_brief_mentions
from .folder_ingest import start_folder_processing
from .style_profile import rebuild_style_profile_from_folder


COURTLISTENER_BASE_URL = "https://www.courtlistener.com/api/rest/v4"
REQUEST_TIMEOUT = 30

# --- Reliability: two-stage sync (glance, then pull only what's missing) ---
#
# A judge's first-ever sync can turn up dozens of opinions in one search
# call. Fetching full text for every single one back-to-back is what used to
# trip CourtListener's rate limit partway through, leaving a partial corpus
# with no way to safely resume. Three changes fix that:
#   1. Before "pulling" (fetching full text) for an opinion, "glance" at the
#      sync folder first -- if a file for that cluster_id already exists on
#      disk, skip the fetch entirely. This makes a re-run after a partial
#      failure resume for free instead of re-costing every already-saved
#      opinion.
#   2. Every GET goes through `_get_with_retry`, which backs off and retries
#      on HTTP 429 (honoring `Retry-After` if CourtListener sends one)
#      instead of failing immediately.
#   3. A small proactive delay between opinion fetches reduces how often a
#      429 happens in the first place.
# On top of that, `last_synced` is only advanced when a run completes with
# zero errors -- if anything failed, the watermark stays put so the next
# sync re-asks for the same window rather than silently skipping whatever
# didn't make it in.
MAX_FETCH_RETRIES = 4
INITIAL_BACKOFF_SECONDS = 2.0
FETCH_THROTTLE_SECONDS = 0.4


def _get_with_retry(url: str, *, headers: dict[str, str], params: dict[str, Any] | None = None) -> requests.Response:
    attempt = 0
    while True:
        response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code != 429 or attempt >= MAX_FETCH_RETRIES:
            response.raise_for_status()
            return response

        retry_after = response.headers.get("Retry-After")
        try:
            wait_seconds = float(retry_after) if retry_after else INITIAL_BACKOFF_SECONDS * (2**attempt)
        except (TypeError, ValueError):
            wait_seconds = INITIAL_BACKOFF_SECONDS * (2**attempt)

        time.sleep(wait_seconds)
        attempt += 1


@dataclass
class TrackedJudge:
    id: str
    name: str
    court: str = ""
    last_synced: str | None = None  # ISO 8601 timestamp of the last successful sync

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "court": self.court, "last_synced": self.last_synced}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrackedJudge":
        return cls(
            id=data["id"],
            name=data["name"],
            court=data.get("court", ""),
            last_synced=data.get("last_synced"),
        )


@dataclass
class SyncResult:
    judge_id: str
    judge_name: str
    opinions_found: int = 0
    oral_arguments_found: int = 0
    files_written: int = 0
    skipped_existing: int = 0
    folder: Path | None = None
    job_id: str | None = None
    brief_mentions_flagged: int = 0
    errors: list[str] = field(default_factory=list)


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug or uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Tracked judge storage (data/tracked_judges.json)
# ---------------------------------------------------------------------------

def load_tracked_judges(app_config: dict[str, Any]) -> list[TrackedJudge]:
    path = Path(app_config["TRACKED_JUDGES_PATH"])
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    return [TrackedJudge.from_dict(item) for item in data.get("judges", [])]


def save_tracked_judges(app_config: dict[str, Any], judges: list[TrackedJudge]) -> None:
    path = Path(app_config["TRACKED_JUDGES_PATH"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"judges": [judge.to_dict() for judge in judges]}, indent=2),
        encoding="utf-8",
    )


def add_tracked_judge(app_config: dict[str, Any], name: str, court: str = "") -> TrackedJudge:
    name = name.strip()
    court = court.strip()
    judges = load_tracked_judges(app_config)
    judge_id = slugify(f"{name}-{court}" if court else name)

    for judge in judges:
        if judge.id == judge_id:
            return judge

    judge = TrackedJudge(id=judge_id, name=name, court=court, last_synced=None)
    judges.append(judge)
    save_tracked_judges(app_config, judges)
    return judge


def get_tracked_judge(app_config: dict[str, Any], judge_id: str) -> TrackedJudge | None:
    for judge in load_tracked_judges(app_config):
        if judge.id == judge_id:
            return judge
    return None


def remove_tracked_judge(app_config: dict[str, Any], judge_id: str) -> None:
    judges = [judge for judge in load_tracked_judges(app_config) if judge.id != judge_id]
    save_tracked_judges(app_config, judges)


def _update_last_synced(app_config: dict[str, Any], judge_id: str, when: str) -> None:
    judges = load_tracked_judges(app_config)
    for judge in judges:
        if judge.id == judge_id:
            judge.last_synced = when
    save_tracked_judges(app_config, judges)


# ---------------------------------------------------------------------------
# CourtListener REST calls
# ---------------------------------------------------------------------------

def _auth_headers(app_config: dict[str, Any]) -> dict[str, str]:
    token = app_config.get("COURTLISTENER_API_TOKEN") or ""
    headers = {"User-Agent": "BriefTune/1.0 (living corpus sync)"}
    if token:
        headers["Authorization"] = f"Token {token}"
    return headers


def _date_only(iso_timestamp: str | None) -> str | None:
    if not iso_timestamp:
        return None
    return iso_timestamp[:10]


def _id_from_url(url: str) -> int | None:
    match = re.search(r"/(\d+)/?$", url or "")
    return int(match.group(1)) if match else None


def _strip_html(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _search(
    app_config: dict[str, Any],
    *,
    type_: str,
    judge: str,
    court: str,
    since: str | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "type": type_,
        "judge": judge,
        "order_by": "dateFiled asc" if type_ == "o" else "dateArgued asc",
    }
    if court:
        params["court"] = court

    after = _date_only(since)
    if after:
        params["filed_after" if type_ == "o" else "argued_after"] = after

    response = _get_with_retry(
        f"{COURTLISTENER_BASE_URL}/search/",
        params=params,
        headers=_auth_headers(app_config),
    )
    return response.json().get("results", [])


def _opinion_already_saved(folder: Path, cluster_id: int) -> bool:
    """The "glance" step: check the sync folder before "pulling" full text.
    A file already existing here means a prior sync already fetched and
    saved this opinion, so there's no need to spend two more API calls (and
    rate-limit risk) re-fetching it.
    """
    return any(folder.glob(f"*-{cluster_id}.txt"))


def _fetch_opinion_text(app_config: dict[str, Any], cluster_id: int) -> str:
    headers = _auth_headers(app_config)

    cluster_resp = _get_with_retry(f"{COURTLISTENER_BASE_URL}/clusters/{cluster_id}/", headers=headers)
    cluster = cluster_resp.json()

    for sub_opinion_url in cluster.get("sub_opinions") or []:
        opinion_id = _id_from_url(sub_opinion_url)
        if opinion_id is None:
            continue

        opinion_resp = _get_with_retry(f"{COURTLISTENER_BASE_URL}/opinions/{opinion_id}/", headers=headers)
        opinion = opinion_resp.json()

        text = (
            opinion.get("plain_text")
            or _strip_html(opinion.get("html_with_citations", ""))
            or _strip_html(opinion.get("html", ""))
        )
        if text and text.strip():
            return text.strip()

    return ""


def _fetch_oral_argument_text(audio: dict[str, Any]) -> str:
    # CourtListener's oral-argument transcript coverage (speech-to-text) is newer
    # than its opinion text pipeline, and the field name has not been verified
    # against a live authenticated response as part of this build. Try the
    # likely candidates and skip gracefully rather than guessing. Confirm the
    # real field name against a live `/audio/<id>/` response before relying on
    # this in production.
    for key in ("stt_transcript", "transcript", "stt_google_response"):
        value = audio.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


# ---------------------------------------------------------------------------
# Sync orchestration
# ---------------------------------------------------------------------------

def sync_judge(app_config: dict[str, Any], judge_id: str) -> SyncResult:
    judge = get_tracked_judge(app_config, judge_id)
    if judge is None:
        raise ValueError(f"No tracked judge with id {judge_id!r}")

    result = SyncResult(judge_id=judge.id, judge_name=judge.name)

    sync_root = Path(app_config["COURTLISTENER_SYNC_DIR"])
    folder = sync_root / f"Judge {judge.name}"
    folder.mkdir(parents=True, exist_ok=True)
    result.folder = folder

    try:
        opinions = _search(app_config, type_="o", judge=judge.name, court=judge.court, since=judge.last_synced)
    except requests.RequestException as exc:
        result.errors.append(f"Opinion search failed: {exc}")
        opinions = []

    result.opinions_found = len(opinions)

    for hit in opinions:
        cluster_id = hit.get("cluster_id") or _id_from_url(hit.get("absolute_url", ""))
        if cluster_id is None:
            continue

        if _opinion_already_saved(folder, cluster_id):
            result.skipped_existing += 1
            continue

        try:
            text = _fetch_opinion_text(app_config, cluster_id)
        except requests.RequestException as exc:
            result.errors.append(f"Failed to fetch opinion {cluster_id}: {exc}")
            continue
        finally:
            time.sleep(FETCH_THROTTLE_SECONDS)

        if not text:
            continue

        case_name = hit.get("caseName") or f"opinion-{cluster_id}"
        date_filed = hit.get("dateFiled", "")
        filename = f"{slugify(case_name)}-{cluster_id}.txt"
        header = f"Opinion by Judge {judge.name}\n{case_name} ({date_filed})\n\n"
        (folder / filename).write_text(header + text, encoding="utf-8")
        result.files_written += 1

        if flag_brief_mentions(app_config, judge.id, judge.name, cluster_id, case_name, date_filed, text):
            result.brief_mentions_flagged += 1

    try:
        oral_arguments = _search(app_config, type_="oa", judge=judge.name, court=judge.court, since=judge.last_synced)
    except requests.RequestException as exc:
        result.errors.append(f"Oral argument search failed: {exc}")
        oral_arguments = []

    result.oral_arguments_found = len(oral_arguments)

    for hit in oral_arguments:
        text = _fetch_oral_argument_text(hit)
        if not text:
            continue

        case_name = hit.get("caseName") or "oral-argument"
        date_argued = hit.get("dateArgued", "")
        filename = f"oa-{slugify(case_name)}.txt"
        header = f"Opinion by Judge {judge.name}\nOral argument: {case_name} ({date_argued})\n\n"
        (folder / filename).write_text(header + text, encoding="utf-8")
        result.files_written += 1

    if result.errors:
        # Leave the watermark where it was: if anything failed to fetch, the
        # next sync should re-ask for this same window rather than silently
        # skip it. Already-saved opinions are still cheap to re-check thanks
        # to `_opinion_already_saved`, so nothing extra is re-fetched.
        pass
    else:
        _update_last_synced(app_config, judge.id, datetime.now(timezone.utc).isoformat())

    if result.files_written:
        job = start_folder_processing(
            app_config,
            str(folder),
            "specific_judge",
            judge.name,
            [judge.name],
        )
        result.job_id = job.id

    # Refresh the judge's style profile from everything in their corpus folder so
    # far (including opinions ingested in prior syncs), not just this batch.
    rebuild_style_profile_from_folder(app_config, judge.name, folder)

    return result


def sync_all_judges(app_config: dict[str, Any]) -> list[SyncResult]:
    return [sync_judge(app_config, judge.id) for judge in load_tracked_judges(app_config)]
