"""Static Pages export tests: only public price observations leave the runner."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kisanmandi.storage.db import (
    get_engine,
    init_db,
    make_session_factory,
    session_scope,
    upsert_prices,
)
from scripts.export_static_site import export_site


def test_export_contains_price_rows_and_no_runtime_diagnostics(
    tmp_path: Path, test_settings, make_record
):
    engine = get_engine(test_settings.database_url)
    init_db(engine)
    with session_scope(make_session_factory(engine)) as session:
        upsert_prices(
            session,
            [make_record(market="Test Market", modal_price="1800")],
        )

    output = tmp_path / "public"
    result = export_site(
        test_settings.database_url,
        output,
        generated_at=datetime(2026, 11, 12, 13, 0, tzinfo=timezone.utc),
    )

    payload = json.loads((output / "prices.json").read_text(encoding="utf-8"))
    page = (output / "index.html").read_text(encoding="utf-8")
    assert result["records"] == 1
    assert payload["records"][0]["market"] == "Test Market"
    assert payload["records"][0]["modal_price"] == "1800.00"
    assert payload["generated_at"] == "2026-11-12T13:00:00+00:00"
    assert "hostname" not in payload
    assert "DATABASE_URL" not in payload
    assert "DATA_GOV_API_KEY" not in payload
    assert "fetch('./prices.json'" in page
    assert "Test Market" not in page


def test_export_refuses_empty_snapshot(tmp_path: Path, test_settings):
    with pytest.raises(RuntimeError, match="empty price snapshot"):
        export_site(test_settings.database_url, tmp_path / "empty")
