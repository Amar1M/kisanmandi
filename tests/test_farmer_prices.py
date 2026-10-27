"""Farmer price browsing uses real stored rows, not fabricated price estimates."""

from __future__ import annotations

from datetime import date, timedelta

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
def farmer_api(test_settings, make_record):
    engine = get_engine(test_settings.database_url)
    init_db(engine)
    factory = make_session_factory(engine)
    today = date.today()
    rows = [
        make_record(market="Market A", arrival_date=today - timedelta(days=2), modal_price="1800"),
        make_record(market="Market A", arrival_date=today, modal_price="2100"),
        make_record(market="Market A", variety="Hybrid", arrival_date=today, modal_price="2200"),
        make_record(market="Market B", arrival_date=today - timedelta(days=9), modal_price="1600"),
        make_record(market="Other District", district="Kolar", arrival_date=today),
        make_record(market="Other State", state="Tamil Nadu", arrival_date=today),
        make_record(market="Other Crop", commodity="Onion", arrival_date=today),
    ]
    with session_scope(factory) as session:
        upsert_prices(session, rows)
    return TestClient(create_app(test_settings))


def test_farmer_page_is_linked_from_existing_dashboard(farmer_api):
    home = farmer_api.get("/")
    page = farmer_api.get("/farmers")
    assert home.status_code == 200
    assert 'href="/farmers"' in home.text
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "Reported mandi prices" in page.text
    assert "not guaranteed offers" in page.text
    assert "/v1/farmer/options" in page.text


def test_filter_options_match_existing_locations_and_crops(farmer_api):
    all_options = farmer_api.get("/v1/farmer/options").json()
    assert all_options == {"states": ["Karnataka", "Tamil Nadu"], "districts": [], "commodities": []}
    state_options = farmer_api.get("/v1/farmer/options", params={"state": "Karnataka"}).json()
    assert state_options["districts"] == ["Bengaluru", "Kolar"]
    assert state_options["commodities"] == []
    crops = farmer_api.get(
        "/v1/farmer/options", params={"state": "Karnataka", "district": "Bengaluru"}
    ).json()
    assert crops["commodities"] == ["Onion", "Tomato"]


def test_latest_price_per_market_variety_and_grade_without_mixing(farmer_api):
    response = farmer_api.get(
        "/v1/farmer/prices",
        params={"state": "Karnataka", "district": "Bengaluru", "commodity": "Tomato"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    assert body["truncated"] is False
    by_market_variety = {(r["market"], r["variety"]): r for r in body["records"]}
    local = by_market_variety[("Market A", "Local")]
    assert local["reported_date"] == date.today().isoformat()
    assert float(local["modal_price"]) == 2100
    assert local["grade"] == "FAQ"
    assert local["is_stale"] is False
    assert float(by_market_variety[("Market A", "Hybrid")]["modal_price"]) == 2200
    assert by_market_variety[("Market B", "Local")]["is_stale"] is True
    assert all("transport_cost" not in row and "recommendation" not in row for row in body["records"])


def test_empty_and_missing_parameters_are_safe(farmer_api):
    assert farmer_api.get("/v1/farmer/prices").status_code == 422
    empty = farmer_api.get(
        "/v1/farmer/prices",
        params={"state": "Karnataka", "district": "Bengaluru", "commodity": "No such crop"},
    )
    assert empty.status_code == 200
    assert empty.json()["records"] == []
    # Input is treated as a bound value, never interpolated into SQL.
    injection = farmer_api.get(
        "/v1/farmer/prices",
        params={"state": "Karnataka", "district": "Bengaluru", "commodity": "' OR 1=1 --"},
    )
    assert injection.json()["count"] == 0


def test_empty_database_options(test_settings):
    client = TestClient(create_app(test_settings))
    assert client.get("/v1/farmer/options").json() == {
        "states": [], "districts": [], "commodities": [],
    }


def test_page_caps_results_and_discloses_truncation(test_settings, make_record):
    engine = get_engine(test_settings.database_url)
    init_db(engine)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        upsert_prices(session, [make_record(market=f"Market {n}", arrival_date=date.today()) for n in range(101)])
    client = TestClient(create_app(test_settings))
    data = client.get(
        "/v1/farmer/prices",
        params={"state": "Karnataka", "district": "Bengaluru", "commodity": "Tomato"},
    ).json()
    assert data["count"] == 100
    assert data["truncated"] is True
