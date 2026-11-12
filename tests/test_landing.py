"""Run-scoped raw landing tests: repeated same-day ingests must not overwrite."""

from __future__ import annotations

import json
from datetime import date

import pytest

from kisanmandi.ingest.landing import LandingWriter, LocalLandingZone


def test_same_day_runs_keep_distinct_pages_and_manifests(tmp_path):
    zone = LocalLandingZone(tmp_path)
    day = date(2026, 10, 15)
    first_payload = {"records": [{"market": "A", "modal_price": "100"}]}
    second_payload = {"records": [{"market": "B", "modal_price": "200"}]}

    first_writer = LandingWriter(zone)
    first_page = first_writer.write_page(first_payload, ingest_date=day, page_index=0)
    first_manifest = first_writer.write_manifest([first_page], ingest_date=day)

    second_writer = LandingWriter(zone)
    second_page = second_writer.write_page(second_payload, ingest_date=day, page_index=0)
    second_manifest = second_writer.write_manifest([second_page], ingest_date=day)

    assert first_writer.run_id != second_writer.run_id
    assert first_page.key != second_page.key
    assert first_manifest != second_manifest
    assert (
        zone.get(first_page.key)
        == json.dumps(first_payload, ensure_ascii=False, sort_keys=True).encode()
    )
    assert (
        zone.get(second_page.key)
        == json.dumps(second_payload, ensure_ascii=False, sort_keys=True).encode()
    )
    assert json.loads(zone.get(first_manifest))["run_id"] == first_writer.run_id
    assert json.loads(zone.get(second_manifest))["run_id"] == second_writer.run_id
    assert len(zone.list_keys("raw/")) == 2
    assert len(zone.list_keys("manifests/")) == 2
    assert LandingWriter.verify(zone, first_page.key, first_page.sha256)
    assert LandingWriter.verify(zone, second_page.key, second_page.sha256)


def test_writer_refuses_to_rewrite_page_or_manifest_in_same_run(tmp_path):
    zone = LocalLandingZone(tmp_path)
    writer = LandingWriter(zone)
    day = date(2026, 10, 15)
    page = writer.write_page({"records": [1]}, ingest_date=day, page_index=0)
    original = zone.get(page.key)

    with pytest.raises(FileExistsError):
        writer.write_page({"records": [2]}, ingest_date=day, page_index=0)
    assert zone.get(page.key) == original

    manifest = writer.write_manifest([page], ingest_date=day)
    original_manifest = zone.get(manifest)
    with pytest.raises(FileExistsError):
        writer.write_manifest([page], ingest_date=day, extra={"changed": True})
    assert zone.get(manifest) == original_manifest


def test_local_landing_put_is_create_only(tmp_path):
    zone = LocalLandingZone(tmp_path)
    zone.put("raw/test.json", b"original")
    with pytest.raises(FileExistsError):
        zone.put("raw/test.json", b"replacement")
    assert zone.get("raw/test.json") == b"original"


def test_negative_page_index_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="non-negative"):
        LandingWriter(LocalLandingZone(tmp_path)).write_page(
            {"records": []}, ingest_date=date(2026, 10, 15), page_index=-1
        )
