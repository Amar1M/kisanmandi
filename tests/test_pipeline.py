"""End-to-end pipeline tests.

This is the most important test file in the repo. It proves the properties that
actually matter in production:

  * the pipeline runs end to end,
  * **running it twice inserts nothing the second time** (idempotency),
  * raw payloads are landed *before* validation,
  * quarantined rows are recorded, not silently dropped,
  * every run is recorded in `ingest_runs`,
  * a failing run is recorded as failed.
"""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
import respx

from kisanmandi.ingest.client import AgmarknetClient, AgmarknetError
from kisanmandi.pipeline import run_ingest
from kisanmandi.storage.db import (
    IngestRun,
    get_engine,
    load_records,
    make_session_factory,
    session_scope,
)


def build_client(settings) -> AgmarknetClient:
    return AgmarknetClient(
        settings.data_gov_api_key,
        page_size=settings.page_size,
        min_request_interval=0.0,
        max_retries=1,
        sleep_fn=lambda _s: None,
    )


class TestHappyPath:
    @respx.mock
    def test_ingest_inserts_everything_and_lands_raw_pages(self, test_settings, page_payload):
        respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(200, json=page_payload)
        )

        result = run_ingest(test_settings, client=build_client(test_settings))

        assert result.inserted == 3
        assert result.skipped_duplicates == 0
        assert result.quality.quarantined == 0
        assert result.quality.pass_rate == 100.0
        assert result.landing_manifest_key is not None

        # raw payloads were landed under a dated Hive partition
        landed = sorted(test_settings.landing_local_dir.rglob("page-*.json"))
        assert len(landed) == 1
        assert "source=agmarknet" in str(landed[0])

        # a manifest with checksums exists
        manifests = sorted(test_settings.landing_local_dir.rglob("manifest.json"))
        assert len(manifests) == 1
        manifest = json.loads(manifests[0].read_text())
        assert manifest["total_records"] == 3
        assert len(manifest["pages"][0]["sha256"]) == 64

        # reports are written for humans and machines
        assert (test_settings.data_dir / "reports" / "quality-latest.json").exists()
        assert (test_settings.data_dir / "reports" / "quality-latest.md").exists()

    @respx.mock
    def test_running_twice_is_idempotent(self, test_settings, page_payload):
        respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(200, json=page_payload)
        )

        first = run_ingest(test_settings, client=build_client(test_settings))
        second = run_ingest(test_settings, client=build_client(test_settings))

        assert first.inserted == 3
        assert second.inserted == 0, "re-running the pipeline must not duplicate rows"
        assert second.skipped_duplicates == 3

        engine = get_engine(test_settings.database_url)
        factory = make_session_factory(engine)
        with session_scope(factory) as session:
            rows = load_records(session, commodity="Tomato")
        assert len(rows) == 3

    @respx.mock
    def test_each_run_is_recorded(self, test_settings, page_payload):
        respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(200, json=page_payload)
        )
        run_ingest(test_settings, client=build_client(test_settings))

        engine = get_engine(test_settings.database_url)
        factory = make_session_factory(engine)
        with session_scope(factory) as session:
            run = session.query(IngestRun).one()
            assert run.status == "success"
            assert run.inserted == 3
            assert run.finished_at is not None
            assert run.duration_seconds >= 0


class TestDirtyData:
    @respx.mock
    def test_bad_rows_are_quarantined_not_stored(self, test_settings):
        payload = {
            "status": "ok",
            "total": "3",
            "records": [
                {  # good
                    "state": "Karnataka", "district": "Bengaluru", "market": "Binny Mill",
                    "commodity": "Tomato", "variety": "Local", "grade": "FAQ",
                    "arrival_date": "14/10/2026",
                    "min_price": "1200", "max_price": "2400", "modal_price": "1800",
                },
                {  # modal below min: structurally impossible
                    "state": "Karnataka", "district": "Bengaluru", "market": "Kolar",
                    "commodity": "Tomato", "variety": "Local", "grade": "FAQ",
                    "arrival_date": "14/10/2026",
                    "min_price": "2000", "max_price": "2400", "modal_price": "1500",
                },
                {  # no prices at all
                    "state": "Karnataka", "district": "Bengaluru", "market": "Mysuru",
                    "commodity": "Tomato", "variety": "Local", "grade": "FAQ",
                    "arrival_date": "14/10/2026",
                    "min_price": "", "max_price": "", "modal_price": "",
                },
            ],
        }
        respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(200, json=payload)
        )

        result = run_ingest(
            test_settings,
            client=build_client(test_settings),
            ingest_date=date(2026, 10, 15),
        )

        assert result.inserted == 1
        assert result.quality.quarantined == 2
        assert result.quality.pass_rate == pytest.approx(33.33, abs=0.01)

        # the two bad rows are recorded in quarantine, not deleted
        from kisanmandi.storage.db import QuarantinedRow

        engine = get_engine(test_settings.database_url)
        factory = make_session_factory(engine)
        with session_scope(factory) as session:
            quarantined = session.query(QuarantinedRow).all()
        assert len(quarantined) == 2

        # the report is written even when the batch is mostly bad
        report = json.loads(
            (test_settings.data_dir / "reports" / "quality-latest.json").read_text()
        )
        assert report["quarantined"] == 2


class TestFailureHandling:
    @respx.mock
    def test_failed_run_is_recorded_as_failed(self, test_settings):
        respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(503)
        )
        with pytest.raises(AgmarknetError):
            run_ingest(test_settings, client=build_client(test_settings))

        engine = get_engine(test_settings.database_url)
        factory = make_session_factory(engine)
        with session_scope(factory) as session:
            run = session.query(IngestRun).one()
            assert run.status == "failed"
            assert run.error is not None
            assert "503" in run.error or "Agmarknet" in run.error


class TestDryRun:
    @respx.mock
    def test_dry_run_writes_nothing(self, test_settings, page_payload):
        respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(200, json=page_payload)
        )
        result = run_ingest(test_settings, client=build_client(test_settings), dry_run=True)

        assert result.dry_run is True
        assert result.inserted == 0
        assert result.landing_manifest_key is None
        assert result.stats.records == 3  # it still fetched and validated

        engine = get_engine(test_settings.database_url)
        factory = make_session_factory(engine)
        with session_scope(factory) as session:
            assert session.query(IngestRun).count() == 0
