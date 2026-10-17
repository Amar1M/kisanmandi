"""HTTP client behaviour: pagination, retries, throttling, error handling.

These tests use respx to mock the API. They never touch the network, so they are
fast, deterministic, and safe to run in CI on every push.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from kisanmandi.ingest.client import PUBLIC_DEMO_API_KEY, AgmarknetClient, AgmarknetError


def make_client(**kwargs) -> AgmarknetClient:
    """A client with sleeping disabled so tests don't actually wait."""
    defaults = {
        "api_key": "test-key",
        "page_size": 2,
        "min_request_interval": 0.0,
        "max_retries": 2,
        "sleep_fn": lambda _seconds: None,
    }
    defaults.update(kwargs)
    return AgmarknetClient(**defaults)


def page(records: list[dict], total: int) -> dict:
    return {"status": "ok", "total": str(total), "count": str(len(records)),
            "limit": "2", "offset": "0", "records": records}


def rec(market: str, day: str, price: str = "1800") -> dict:
    return {
        "state": "Karnataka", "district": "Bengaluru", "market": market,
        "commodity": "Tomato", "variety": "Local", "grade": "FAQ",
        "arrival_date": day, "min_price": "1200", "max_price": "2400",
        "modal_price": price,
    }


class TestSinglePage:
    @respx.mock
    def test_short_page_ends_pagination(self, page_payload):
        route = respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(200, json=page_payload)
        )
        with make_client(page_size=100) as client:
            result = client.fetch_all()

        assert route.call_count == 1
        assert result.stats.records == 3
        assert result.stats.pages == 1

    @respx.mock
    def test_empty_response_is_handled(self):
        respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(200, json={"status": "ok", "total": "0", "records": []})
        )
        with make_client() as client:
            result = client.fetch_all()
        assert result.records == []
        assert result.stats.records == 0


class TestPagination:
    @respx.mock
    def test_walks_pages_until_total_is_reached(self):
        first = page([rec("A", "14/10/2026"), rec("B", "14/10/2026")], total=3)
        second = page([rec("C", "14/10/2026")], total=3)
        respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            side_effect=[
                httpx.Response(200, json=first),
                httpx.Response(200, json=second),
            ]
        )
        with make_client(page_size=2) as client:
            result = client.fetch_all()

        assert result.stats.pages == 2
        assert result.stats.records == 3
        assert {r.market for r in result.records} == {"A", "B", "C"}

    @respx.mock
    def test_respects_max_pages_ceiling(self):
        full = page([rec("A", "14/10/2026"), rec("B", "14/10/2026")], total=999)
        respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(200, json=full)
        )
        with make_client(page_size=2) as client:
            result = client.fetch_all(max_pages=2)
        assert result.stats.pages == 2

    @respx.mock
    def test_offset_advances_between_requests(self):
        route = respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            side_effect=[
                httpx.Response(200, json=page([rec("A", "14/10/2026"), rec("B", "14/10/2026")], 4)),
                httpx.Response(200, json=page([rec("C", "14/10/2026")], 4)),
            ]
        )
        with make_client(page_size=2) as client:
            client.fetch_all()
        offsets = [call.request.url.params["offset"] for call in route.calls]
        assert offsets == ["0", "2"]


class TestRetries:
    @respx.mock
    def test_retries_on_429_then_succeeds(self, page_payload):
        route = respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "0"}),
                httpx.Response(200, json=page_payload),
            ]
        )
        with make_client(page_size=100) as client:
            result = client.fetch_all()

        assert route.call_count == 2
        assert result.stats.retries == 1
        assert result.stats.records == 3

    @respx.mock
    def test_retries_on_500_then_succeeds(self, page_payload):
        route = respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            side_effect=[httpx.Response(503), httpx.Response(200, json=page_payload)]
        )
        with make_client(page_size=100) as client:
            result = client.fetch_all()
        assert route.call_count == 2
        assert result.stats.records == 3

    @respx.mock
    def test_gives_up_after_max_retries(self):
        route = respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(503)
        )
        with make_client(max_retries=2) as client, pytest.raises(AgmarknetError):
            client.fetch_all()
        # initial attempt + 2 retries
        assert route.call_count == 3

    @respx.mock
    def test_does_not_retry_client_errors(self):
        route = respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(401)
        )
        with make_client(max_retries=3) as client, pytest.raises(httpx.HTTPStatusError):
            client.fetch_all()
        # 401 is not in RETRYABLE_STATUS: fail fast rather than burn the budget.
        assert route.call_count == 1

    @respx.mock
    def test_raises_when_api_reports_non_ok_status(self):
        respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(200, json={"status": "error", "records": []})
        )
        with make_client() as client, pytest.raises(AgmarknetError):
            client.fetch_all()


class TestThrottling:
    @respx.mock
    def test_sleeps_between_requests(self):
        calls: list[float] = []
        first = page([rec("A", "14/10/2026"), rec("B", "14/10/2026")], total=4)
        second = page([rec("C", "14/10/2026")], total=4)
        respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            side_effect=[httpx.Response(200, json=first), httpx.Response(200, json=second)]
        )

        clock_value = {"t": 0.0}

        def fake_clock() -> float:
            return clock_value["t"]

        def fake_sleep(seconds: float) -> None:
            calls.append(seconds)
            clock_value["t"] += seconds

        with make_client(
            page_size=2,
            min_request_interval=1.0,
            sleep_fn=fake_sleep,
            clock_fn=fake_clock,
        ) as client:
            client.fetch_all()

        # The second request must have waited out the minimum interval.
        assert any(seconds > 0 for seconds in calls)


class TestRequestBuilding:
    @respx.mock
    def test_filters_are_encoded_in_the_expected_format(self, page_payload):
        route = respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(200, json=page_payload)
        )
        with make_client(page_size=100) as client:
            client.fetch_all({"state": "Karnataka", "commodity": "Tomato"})

        params = route.calls[0].request.url.params
        assert params["filters[state]"] == "Karnataka"
        assert params["filters[commodity]"] == "Tomato"
        assert params["api-key"] == "test-key"
        assert params["format"] == "json"

    @respx.mock
    def test_blank_filter_values_are_dropped(self, page_payload):
        route = respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(200, json=page_payload)
        )
        with make_client(page_size=100) as client:
            client.fetch_all({"state": "Karnataka", "district": ""})
        keys = {k for k, _ in route.calls[0].request.url.params.multi_items()}
        assert "filters[district]" not in keys

    @respx.mock
    def test_empty_api_key_falls_back_to_public_demo_key(self, page_payload):
        route = respx.get(url__startswith="https://api.data.gov.in/resource/").mock(
            return_value=httpx.Response(200, json=page_payload)
        )
        with make_client(api_key="", page_size=100) as client:
            client.fetch_all()
        assert route.calls[0].request.url.params["api-key"] == PUBLIC_DEMO_API_KEY
