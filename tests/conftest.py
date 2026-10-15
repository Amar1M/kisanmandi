"""Shared test fixtures.

Nothing here touches the network or the real data.gov.in API. Tests must pass on
a plane with no wifi — and must never consume your rate limit.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

# Point the *default* settings at a throwaway directory before any module can
# import them. Without this, importing kisanmandi.api.main creates ./data/ in the
# repo root during the test run -- which is exactly the kind of side effect that
# makes a test suite untrustworthy.
_TMP_ROOT = tempfile.mkdtemp(prefix="kisanmandi-tests-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP_ROOT}/default.db")
os.environ.setdefault("DATA_DIR", f"{_TMP_ROOT}/data")
os.environ.setdefault("LANDING_LOCAL_DIR", f"{_TMP_ROOT}/landing")
os.environ.setdefault("DATA_GOV_API_KEY", "test-key")

from kisanmandi.config import Settings  # noqa: E402
from kisanmandi.ingest.schema import MandiPriceRecord  # noqa: E402

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def page_payload() -> dict:
    """A realistic single-page API response."""
    return json.loads((FIXTURES_DIR / "agmarknet_page.json").read_text(encoding="utf-8"))


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Settings pointed at throwaway paths so tests never touch real data."""
    return Settings(
        data_gov_api_key="test-key",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        data_dir=tmp_path / "data",
        landing_local_dir=tmp_path / "landing",
        landing_backend="local",
        page_size=100,
        max_pages=3,
        min_request_interval_seconds=0.0,
        max_retries=2,
        min_history_points=14,
    )


@pytest.fixture
def make_record():
    """Factory for building a valid record, with any field overridden."""

    def _make(**overrides) -> MandiPriceRecord:
        base = {
            "state": "Karnataka",
            "district": "Bengaluru",
            "market": "Binny Mill (F&V), Bangalore",
            "commodity": "Tomato",
            "variety": "Local",
            "grade": "FAQ",
            "arrival_date": date(2026, 10, 14),
            "min_price": "1200",
            "max_price": "2400",
            "modal_price": "1800",
        }
        base.update(overrides)
        return MandiPriceRecord(**base)

    return _make


@pytest.fixture
def make_series():
    """Build a synthetic price series — a ladder of daily observations."""

    def _make(
        *,
        commodity: str = "Tomato",
        market: str = "Binny Mill (F&V), Bangalore",
        district: str = "Bengaluru",
        start: date = date(2026, 9, 1),
        days: int = 30,
        base: float = 1500.0,
        slope: float = 0.0,
        wobble: float = 0.0,
    ) -> list[MandiPriceRecord]:
        records = []
        for i in range(days):
            price = base + slope * i + (wobble * ((i % 3) - 1))
            records.append(
                MandiPriceRecord(
                    state="Karnataka",
                    district=district,
                    market=market,
                    commodity=commodity,
                    variety="Local",
                    grade="FAQ",
                    arrival_date=start + timedelta(days=i),
                    min_price=str(round(price * 0.8)),
                    max_price=str(round(price * 1.2)),
                    modal_price=str(round(price)),
                )
            )
        return records

    return _make
