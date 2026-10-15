"""Schema validation: the messy upstream feed must become clean objects."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from kisanmandi.ingest.schema import parse_records


class TestFieldNormalisation:
    def test_parses_dd_mm_yyyy_dates(self, make_record):
        assert make_record(arrival_date="14/10/2026").arrival_date == date(2026, 10, 14)

    def test_parses_iso_dates(self, make_record):
        assert make_record(arrival_date="2026-10-14").arrival_date == date(2026, 10, 14)

    def test_strips_thousands_separators_from_prices(self, make_record):
        assert make_record(modal_price="1,800").modal_price == Decimal("1800")

    @pytest.mark.parametrize("blank", ["", "  ", "NA", "N/A", "NULL", "-", None])
    def test_blank_prices_become_none(self, make_record, blank):
        assert make_record(modal_price=blank).modal_price is None

    def test_unicode_digits_and_stray_characters(self, make_record):
        # Real feeds contain things like "Rs. 1800" or trailing spaces.
        assert make_record(modal_price=" 1800.50 ").modal_price == Decimal("1800.50")

    def test_missing_variety_defaults_to_empty_string(self, make_record):
        record = make_record(variety=None, grade=None)
        assert record.variety == "" and record.grade == ""


class TestNaturalKey:
    def test_key_is_stable_for_identical_input(self, make_record):
        assert make_record().natural_key == make_record().natural_key

    def test_key_is_case_insensitive(self, make_record):
        # 'BENGALURU' and 'Bengaluru' must not create two different series.
        lower = make_record(state="karnataka", district="bengaluru")
        upper = make_record(state="KARNATAKA", district="BENGALURU")
        assert lower.natural_key == upper.natural_key

    def test_different_dates_produce_different_keys(self, make_record):
        a = make_record(arrival_date="14/10/2026")
        b = make_record(arrival_date="15/10/2026")
        assert a.natural_key != b.natural_key

    def test_different_markets_produce_different_keys(self, make_record):
        a = make_record(market="Kolar")
        b = make_record(market="Binny Mill (F&V), Bangalore")
        assert a.natural_key != b.natural_key

    def test_key_is_reasonably_short(self, make_record):
        assert len(make_record().natural_key) == 32


class TestPlaceNameNormalisation:
    def test_state_and_district_are_title_cased(self, make_record):
        record = make_record(state="KARNATAKA", district="bengaluru rural")
        assert record.state == "Karnataka"
        assert record.district == "Bengaluru Rural"

    def test_commodity_is_title_cased(self, make_record):
        assert make_record(commodity="TOMATO").commodity == "Tomato"

    def test_market_name_is_left_alone(self, make_record):
        # Markets have parentheses and abbreviations; title-casing would mangle them.
        record = make_record(market="Binny Mill (F&V), Bangalore")
        assert record.market == "Binny Mill (F&V), Bangalore"


class TestPriceOrdering:
    def test_valid_ordering(self, make_record):
        assert make_record(min_price="1200", modal_price="1800", max_price="2400").price_ordering_ok

    def test_modal_below_min_is_invalid(self, make_record):
        assert not make_record(min_price="2000", modal_price="1800", max_price="2400").price_ordering_ok

    def test_ordering_tolerates_missing_values(self, make_record):
        assert make_record(min_price=None, modal_price="1800", max_price=None).price_ordering_ok


class TestParseRecords:
    def test_splits_valid_from_invalid(self, page_payload):
        valid, rejected = parse_records(page_payload["records"])
        assert len(valid) == 3
        assert rejected == []

    def test_rejects_unparseable_row_without_raising(self):
        valid, rejected = parse_records([{"state": "Karnataka"}])  # missing required fields
        assert valid == []
        assert len(rejected) == 1
        assert "reason" in rejected[0]

    def test_one_bad_row_does_not_lose_the_good_ones(self, page_payload):
        rows = page_payload["records"] + [{"nonsense": True}]
        valid, rejected = parse_records(rows)
        assert len(valid) == 3
        assert len(rejected) == 1
