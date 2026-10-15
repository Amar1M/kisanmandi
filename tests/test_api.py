"""API contract tests. Fast, no network, no real data."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kisanmandi.api.main import create_app
from kisanmandi.storage.db import (
    get_engine,
    init_db,
    make_session_factory,
    session_scope,
    upsert_prices,
)


@pytest.fixture
def api(test_settings, make_series):
    """An app backed by a seeded temporary database."""
    engine = get_engine(test_settings.database_url)
    init_db(engine)
    factory = make_session_factory(engine)

    records = make_series(
        market="Binny Mill (F&V), Bangalore", district="Bengaluru",
        days=40, base=1000.0, slope=20.0,
    ) + make_series(
        market="Kolar", district="Bengaluru", days=40, base=1400.0, slope=20.0,
    )
    with session_scope(factory) as session:
        upsert_prices(session, records)

    return TestClient(create_app(test_settings))


class TestHealth:
    def test_health_reports_counts(self, api):
        response = api.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["counts"]["mandi_prices"] == 80


class TestPrices:
    def test_returns_seeded_records(self, api):
        response = api.get("/v1/prices", params={"commodity": "Tomato", "days": 365})
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 80
        assert body["records"][0]["commodity"] == "Tomato" or "market" in body["records"][0]

    def test_filters_by_market(self, api):
        response = api.get(
            "/v1/prices", params={"commodity": "Tomato", "market": "Kolar", "days": 365}
        )
        assert response.json()["count"] == 40

    def test_unknown_commodity_returns_zero(self, api):
        response = api.get("/v1/prices", params={"commodity": "Dragonfruit", "days": 365})
        assert response.status_code == 200
        assert response.json()["count"] == 0


class TestSeries:
    def test_returns_a_continuous_series(self, api):
        response = api.get("/v1/series", params={"commodity": "Tomato", "market": "Kolar"})
        assert response.status_code == 200
        body = response.json()
        assert body["points"] == 40
        assert body["series"][0]["price"] < body["series"][-1]["price"]  # upward trend

    def test_404_for_unknown_commodity(self, api):
        response = api.get("/v1/series", params={"commodity": "Dragonfruit"})
        assert response.status_code == 404


class TestAdvice:
    def test_returns_advice_with_reasoning(self, api):
        response = api.get("/v1/advice", params={"commodity": "Tomato", "market": "Kolar"})
        assert response.status_code == 200
        body = response.json()
        assert body["action"] in {"SELL_NOW", "HOLD", "TRANSPORT_TO_OTHER_MANDI", "INSUFFICIENT_DATA"}
        assert body["reasons"]
        assert len(body["headline"]) <= 160

    def test_404_when_no_data(self, api):
        response = api.get("/v1/advice", params={"commodity": "Dragonfruit"})
        assert response.status_code == 404

    def test_requires_a_commodity_parameter(self, api):
        assert api.get("/v1/advice").status_code == 422


class TestQualityEndpoint:
    def test_404_before_any_report_exists(self, api, test_settings):
        if (test_settings.data_dir / "reports" / "quality-latest.json").exists():
            pytest.skip("report already present in this settings fixture")
        assert api.get("/v1/quality/latest").status_code == 404


class TestMetrics:
    def test_metrics_are_prometheus_formatted(self, api):
        api.get("/health")
        response = api.get("/metrics")
        assert response.status_code == 200
        text = response.text
        assert "# TYPE kisanmandi_mandi_prices gauge" in text
        assert "kisanmandi_mandi_prices 80" in text
