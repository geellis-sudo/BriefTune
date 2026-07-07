from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from app import create_app
from app.courtlistener_sync import (
    add_tracked_judge,
    load_tracked_judges,
    sync_all_judges,
    sync_judge,
)
from app.folder_ingest import JOB_STORE


def make_app(tmp_path: Path):
    return create_app(
        {
            "TESTING": True,
            "OPINION_DATA_DIR": tmp_path / "opinions",
            "TRANSCRIPT_DATA_DIR": tmp_path / "transcripts",
            "FIRM_CONFIDENTIAL_DIR": tmp_path / "firm_confidential",
            "FIRM_CONFIDENTIAL_KEY_PATH": tmp_path / "firm_confidential.key",
            "AUDIT_LOG_PATH": tmp_path / "audit.log",
            "PROCESSED_FILES_PATH": tmp_path / "processed_files.json",
            "COURTLISTENER_API_TOKEN": "test-token",
            "COURTLISTENER_SYNC_DIR": tmp_path / "courtlistener_sync",
            "TRACKED_JUDGES_PATH": tmp_path / "tracked_judges.json",
        }
    )


def fake_response(payload, status_code=200, headers=None):
    response = MagicMock()
    response.json.return_value = payload
    response.status_code = status_code
    response.headers = headers or {}
    if status_code == 429:
        response.raise_for_status.side_effect = requests.HTTPError("429 rate limited")
    else:
        response.raise_for_status.return_value = None
    return response


def fake_get_for(*, opinion_hits, oa_hits, cluster_payload=None, opinion_payload=None):
    def _fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/search/"):
            if params.get("type") == "o":
                return fake_response({"results": opinion_hits})
            return fake_response({"results": oa_hits})
        if "/clusters/" in url:
            return fake_response(cluster_payload or {"sub_opinions": []})
        if "/opinions/" in url:
            return fake_response(opinion_payload or {"plain_text": ""})
        raise AssertionError(f"Unexpected URL in test: {url}")

    return _fake_get


def wait_for_job(job_id: str, timeout: float = 5.0):
    deadline = time.time() + timeout
    job = JOB_STORE.get(job_id)
    while job and job.status != "done" and time.time() < deadline:
        time.sleep(0.05)
        job = JOB_STORE.get(job_id)
    return job


def test_add_and_load_tracked_judge(tmp_path: Path):
    app = make_app(tmp_path)

    with app.app_context():
        judge = add_tracked_judge(app.config, "Jane A. Doe", "ca9")
        loaded = load_tracked_judges(app.config)

    assert judge.name == "Jane A. Doe"
    assert judge.court == "ca9"
    assert judge.last_synced is None
    assert len(loaded) == 1
    assert loaded[0].id == judge.id

    with app.app_context():
        same_judge = add_tracked_judge(app.config, "Jane A. Doe", "ca9")
    assert same_judge.id == judge.id
    with app.app_context():
        assert len(load_tracked_judges(app.config)) == 1


def test_sync_judge_writes_new_opinion_and_ingests_it(tmp_path: Path):
    app = make_app(tmp_path)

    with app.app_context():
        judge = add_tracked_judge(app.config, "Jane A. Doe", "ca9")

    opinion_hits = [
        {
            "cluster_id": 12345,
            "caseName": "Doe v. Roe",
            "dateFiled": "2026-05-01",
            "absolute_url": "/opinion/12345/doe-v-roe/",
        }
    ]
    cluster_payload = {"sub_opinions": ["/api/rest/v4/opinions/999/"]}
    opinion_payload = {"plain_text": "The court finds the argument persuasive and grants the motion."}

    fake_get = fake_get_for(
        opinion_hits=opinion_hits,
        oa_hits=[],
        cluster_payload=cluster_payload,
        opinion_payload=opinion_payload,
    )

    with app.app_context(), patch("app.courtlistener_sync.requests.get", side_effect=fake_get):
        result = sync_judge(app.config, judge.id)

    assert result.opinions_found == 1
    assert result.files_written == 1
    assert result.job_id is not None
    assert not result.errors

    written_files = list(result.folder.glob("*.txt"))
    assert len(written_files) == 1
    assert "Doe v. Roe" in written_files[0].read_text(encoding="utf-8")

    job = wait_for_job(result.job_id)
    assert job is not None
    assert job.status == "done"
    assert job.judge_name == "Jane A. Doe"
    assert job.processed_files == 1

    with app.app_context():
        refreshed = load_tracked_judges(app.config)[0]
    assert refreshed.last_synced is not None


def test_sync_judge_with_no_new_results_writes_nothing(tmp_path: Path):
    app = make_app(tmp_path)

    with app.app_context():
        judge = add_tracked_judge(app.config, "Robert T. Hill")

    fake_get = fake_get_for(opinion_hits=[], oa_hits=[])

    with app.app_context(), patch("app.courtlistener_sync.requests.get", side_effect=fake_get):
        result = sync_judge(app.config, judge.id)

    assert result.opinions_found == 0
    assert result.oral_arguments_found == 0
    assert result.files_written == 0
    assert result.job_id is None


def test_sync_all_judges_iterates_every_tracked_judge(tmp_path: Path):
    app = make_app(tmp_path)

    with app.app_context():
        add_tracked_judge(app.config, "Judge One")
        add_tracked_judge(app.config, "Judge Two")

    fake_get = fake_get_for(opinion_hits=[], oa_hits=[])

    with app.app_context(), patch("app.courtlistener_sync.requests.get", side_effect=fake_get):
        results = sync_all_judges(app.config)

    assert len(results) == 2
    assert {result.judge_name for result in results} == {"Judge One", "Judge Two"}


def test_sync_judge_retries_on_429_then_succeeds(tmp_path: Path):
    app = make_app(tmp_path)

    with app.app_context():
        judge = add_tracked_judge(app.config, "Jane A. Doe", "ca9")

    opinion_hits = [
        {
            "cluster_id": 12345,
            "caseName": "Doe v. Roe",
            "dateFiled": "2026-05-01",
            "absolute_url": "/opinion/12345/doe-v-roe/",
        }
    ]
    cluster_payload = {"sub_opinions": ["/api/rest/v4/opinions/999/"]}
    opinion_payload = {"plain_text": "The court finds the argument persuasive and grants the motion."}

    rate_limited_once = {"cluster_calls": 0}

    def _fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/search/"):
            if params.get("type") == "o":
                return fake_response({"results": opinion_hits})
            return fake_response({"results": []})
        if "/clusters/" in url:
            rate_limited_once["cluster_calls"] += 1
            if rate_limited_once["cluster_calls"] == 1:
                return fake_response({}, status_code=429, headers={"Retry-After": "0"})
            return fake_response(cluster_payload)
        if "/opinions/" in url:
            return fake_response(opinion_payload)
        raise AssertionError(f"Unexpected URL in test: {url}")

    with app.app_context(), patch("app.courtlistener_sync.requests.get", side_effect=_fake_get), patch(
        "app.courtlistener_sync.time.sleep"
    ):
        result = sync_judge(app.config, judge.id)

    assert rate_limited_once["cluster_calls"] == 2
    assert result.files_written == 1
    assert not result.errors

    with app.app_context():
        refreshed = load_tracked_judges(app.config)[0]
    assert refreshed.last_synced is not None


def test_sync_judge_skips_opinion_already_saved_on_resync(tmp_path: Path):
    app = make_app(tmp_path)

    with app.app_context():
        judge = add_tracked_judge(app.config, "Jane A. Doe", "ca9")

    opinion_hits = [
        {
            "cluster_id": 12345,
            "caseName": "Doe v. Roe",
            "dateFiled": "2026-05-01",
            "absolute_url": "/opinion/12345/doe-v-roe/",
        }
    ]
    cluster_payload = {"sub_opinions": ["/api/rest/v4/opinions/999/"]}
    opinion_payload = {"plain_text": "The court finds the argument persuasive and grants the motion."}

    call_count = {"clusters": 0, "opinions": 0}

    def _fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/search/"):
            if params.get("type") == "o":
                return fake_response({"results": opinion_hits})
            return fake_response({"results": []})
        if "/clusters/" in url:
            call_count["clusters"] += 1
            return fake_response(cluster_payload)
        if "/opinions/" in url:
            call_count["opinions"] += 1
            return fake_response(opinion_payload)
        raise AssertionError(f"Unexpected URL in test: {url}")

    with app.app_context(), patch("app.courtlistener_sync.requests.get", side_effect=_fake_get), patch(
        "app.courtlistener_sync.time.sleep"
    ):
        first = sync_judge(app.config, judge.id)

    assert first.files_written == 1
    assert first.skipped_existing == 0
    assert call_count == {"clusters": 1, "opinions": 1}

    # Second sync sees the same opinion again (e.g. search window overlap) --
    # it should be skipped without any new network calls to clusters/opinions.
    with app.app_context(), patch("app.courtlistener_sync.requests.get", side_effect=_fake_get), patch(
        "app.courtlistener_sync.time.sleep"
    ):
        second = sync_judge(app.config, judge.id)

    assert second.files_written == 0
    assert second.skipped_existing == 1
    assert call_count == {"clusters": 1, "opinions": 1}


def test_sync_judge_does_not_advance_last_synced_on_fetch_error(tmp_path: Path):
    app = make_app(tmp_path)

    with app.app_context():
        judge = add_tracked_judge(app.config, "Jane A. Doe", "ca9")

    opinion_hits = [
        {
            "cluster_id": 12345,
            "caseName": "Doe v. Roe",
            "dateFiled": "2026-05-01",
            "absolute_url": "/opinion/12345/doe-v-roe/",
        }
    ]

    def _fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/search/"):
            if params.get("type") == "o":
                return fake_response({"results": opinion_hits})
            return fake_response({"results": []})
        if "/clusters/" in url:
            # Every attempt (including retries) stays rate-limited -- simulates
            # a sustained outage that exhausts MAX_FETCH_RETRIES.
            return fake_response({}, status_code=429, headers={"Retry-After": "0"})
        raise AssertionError(f"Unexpected URL in test: {url}")

    with app.app_context(), patch("app.courtlistener_sync.requests.get", side_effect=_fake_get), patch(
        "app.courtlistener_sync.time.sleep"
    ):
        result = sync_judge(app.config, judge.id)

    assert result.files_written == 0
    assert result.errors
    assert "12345" in result.errors[0]

    with app.app_context():
        refreshed = load_tracked_judges(app.config)[0]
    assert refreshed.last_synced is None
