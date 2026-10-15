"""Data-quality gates — the checks that stop bad data becoming bad advice."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from kisanmandi.quality.checks import Check, QualityGate, Severity

REFERENCE = date(2026, 10, 15)


@pytest.fixture
def gate() -> QualityGate:
    return QualityGate(
        min_plausible_price=10.0, max_plausible_price=100_000.0, staleness_days=7
    )


class TestBlockerChecks:
    def test_missing_all_prices_is_quarantined(self, gate, make_record):
        record = make_record(min_price=None, modal_price=None, max_price=None)
        loadable, quarantined, report = gate.evaluate([record], reference_date=REFERENCE)
        assert loadable == []
        assert len(quarantined) == 1
        assert Check.MISSING_PRICE.value in report.by_check

    def test_zero_price_is_quarantined(self, gate, make_record):
        record = make_record(modal_price="0")
        loadable, quarantined, report = gate.evaluate([record], reference_date=REFERENCE)
        assert quarantined and not loadable
        assert Check.NON_POSITIVE_PRICE.value in report.by_check

    def test_inverted_price_range_is_quarantined(self, gate, make_record):
        # modal below min: structurally impossible
        record = make_record(min_price="2000", modal_price="1500", max_price="2400")
        loadable, quarantined, report = gate.evaluate([record], reference_date=REFERENCE)
        assert quarantined and not loadable
        assert Check.INVALID_PRICE_RANGE.value in report.by_check

    def test_absurd_price_is_quarantined(self, gate, make_record):
        record = make_record(min_price="90000", modal_price="999999", max_price="999999")
        loadable, quarantined, report = gate.evaluate([record], reference_date=REFERENCE)
        assert quarantined
        assert Check.IMPLAUSIBLE_PRICE.value in report.by_check

    def test_future_arrival_date_is_quarantined(self, gate, make_record):
        tomorrow = REFERENCE + timedelta(days=1)
        record = make_record(arrival_date=tomorrow)
        loadable, quarantined, report = gate.evaluate([record], reference_date=REFERENCE)
        assert quarantined
        assert Check.FUTURE_ARRIVAL_DATE.value in report.by_check


class TestWarningChecks:
    def test_stale_record_warns_but_is_loaded(self, gate, make_record):
        old = REFERENCE - timedelta(days=30)
        record = make_record(arrival_date=old)
        loadable, quarantined, report = gate.evaluate([record], reference_date=REFERENCE)
        assert len(loadable) == 1  # still usable
        assert not quarantined
        assert Check.STALE_ARRIVAL_DATE.value in report.by_check

    def test_recent_record_does_not_warn(self, gate, make_record):
        record = make_record(arrival_date=REFERENCE - timedelta(days=1))
        loadable, _, report = gate.evaluate([record], reference_date=REFERENCE)
        assert len(loadable) == 1
        assert report.issues == []

    def test_duplicate_is_deduplicated_not_quarantined(self, gate, make_record):
        first = make_record()
        duplicate = make_record()  # identical -> identical natural key
        loadable, quarantined, report = gate.evaluate([first, duplicate], reference_date=REFERENCE)
        assert len(loadable) == 1
        assert not quarantined
        assert Check.DUPLICATE_NATURAL_KEY.value in report.by_check

    def test_outlier_is_flagged_but_kept(self, gate, make_record):
        # Nine normal prices plus one wild spike. Markets differ so the natural
        # keys are distinct - otherwise these would be deduplicated as repeats.
        normal = [90, 95, 98, 100, 102, 105, 108, 110]
        records = [
            make_record(market=f"Market {i}", arrival_date=REFERENCE, modal_price=str(p),
                        min_price=str(p - 10), max_price=str(p + 10))
            for i, p in enumerate(normal)
        ]
        records.append(
            make_record(market="Spike Market", arrival_date=REFERENCE, modal_price="500",
                        min_price="480", max_price="520")
        )
        loadable, quarantined, report = gate.evaluate(records, reference_date=REFERENCE)
        assert len(loadable) == 9  # everything loads
        assert not quarantined
        assert Check.OUTLIER_PRICE.value in report.by_check

    def test_outlier_check_needs_enough_points(self, gate, make_record):
        # With fewer than 8 observations we deliberately skip outlier detection.
        records = [
            make_record(market=f"Market {i}", arrival_date=REFERENCE, modal_price=str(p),
                        min_price=str(p - 5), max_price=str(p + 5))
            for i, p in enumerate([100, 100, 100, 500])
        ]
        _, _, report = gate.evaluate(records, reference_date=REFERENCE)
        assert Check.OUTLIER_PRICE.value not in report.by_check


class TestBatchBehaviour:
    def test_mixed_batch_splits_correctly(self, gate, make_record):
        good = make_record()
        bad = make_record(market="Kolar", modal_price="0")
        loadable, quarantined, report = gate.evaluate([good, bad], reference_date=REFERENCE)
        assert len(loadable) == 1
        assert len(quarantined) == 1
        assert report.total_records == 2
        assert report.passed == 1
        assert report.quarantined == 1

    def test_pass_rate_is_computed(self, gate, make_record):
        records = [make_record(market=f"M{i}") for i in range(9)]
        records.append(make_record(market="Bad", modal_price="0"))
        loadable, _, report = gate.evaluate(records, reference_date=REFERENCE)
        assert report.pass_rate == 90.0

    def test_empty_batch_does_not_crash(self, gate):
        loadable, quarantined, report = gate.evaluate([], reference_date=REFERENCE)
        assert loadable == [] and quarantined == []
        assert report.pass_rate == 0.0

    def test_clean_batch_passes_entirely(self, gate, make_record):
        records = [make_record(market=f"M{i}") for i in range(20)]
        loadable, quarantined, report = gate.evaluate(records, reference_date=REFERENCE)
        assert len(loadable) == 20
        assert report.pass_rate == 100.0
        assert report.issues == []


class TestReportRendering:
    def test_json_report_is_valid_and_complete(self, gate, make_record):
        _, _, report = gate.evaluate(
            [make_record(modal_price="0")], reference_date=REFERENCE
        )
        payload = json.loads(report.to_json())
        assert payload["total_records"] == 1
        assert payload["quarantined"] == 1
        assert "by_check" in payload and "issues" in payload

    def test_markdown_report_contains_the_numbers(self, gate, make_record):
        records = [make_record(market=f"M{i}") for i in range(9)]
        records.append(make_record(market="Bad", modal_price="0"))
        _, _, report = gate.evaluate(records, reference_date=REFERENCE)
        markdown = report.to_markdown()
        assert "Mandi Price Data Quality Report" in markdown
        assert "Records evaluated:** 10" in markdown
        assert "90.0%" in markdown

    def test_markdown_handles_a_clean_batch(self, gate, make_record):
        _, _, report = gate.evaluate([make_record()], reference_date=REFERENCE)
        assert "No issues detected" in report.to_markdown()

    def test_severity_mix_is_reported(self, gate, make_record):
        records = [
            make_record(market="A", modal_price="0"),                       # blocker
            make_record(market="B", arrival_date=REFERENCE - timedelta(days=40)),  # warning
        ]
        _, _, report = gate.evaluate(records, reference_date=REFERENCE)
        severities = report.by_severity
        assert severities.get(Severity.BLOCKER.value, 0) >= 1
        assert severities.get(Severity.WARNING.value, 0) >= 1
