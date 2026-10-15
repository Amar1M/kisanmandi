"""Forecasting: correct series construction, honest backtesting."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from kisanmandi.forecast.baseline import (
    Point,
    backtest,
    build_series,
    compare_models,
    drift,
    forecast,
    moving_average,
    naive,
    seasonal_naive,
)


def line(days: int = 40, base: float = 1000.0, slope: float = 10.0, start: date = date(2026, 9, 1)) -> list[Point]:
    return [Point(start + timedelta(days=i), base + slope * i) for i in range(days)]


class TestBuildSeries:
    def test_sorts_by_date(self, make_record):
        records = [
            make_record(arrival_date="16/10/2026", modal_price="1800"),
            make_record(arrival_date="14/10/2026", modal_price="1600"),
            make_record(arrival_date="15/10/2026", modal_price="1700"),
        ]
        series = build_series(records, commodity="Tomato")
        assert [p.day for p in series] == [
            date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)
        ]
        assert [p.value for p in series] == [1600.0, 1700.0, 1800.0]

    def test_averages_multiple_varieties_on_the_same_day(self, make_record):
        records = [
            make_record(arrival_date="14/10/2026", variety="Local", modal_price="1500"),
            make_record(arrival_date="14/10/2026", variety="Hybrid", modal_price="2500"),
        ]
        series = build_series(records, commodity="Tomato")
        assert len(series) == 1
        assert series[0].value == 2000.0

    def test_filters_by_commodity(self, make_record):
        records = [
            make_record(commodity="Tomato", modal_price="1500"),
            make_record(commodity="Onion", modal_price="2500"),
        ]
        series = build_series(records, commodity="Tomato")
        assert len(series) == 1 and series[0].value == 1500.0

    def test_filters_by_market(self, make_record):
        records = [
            make_record(market="Kolar", modal_price="1000"),
            make_record(market="Binny Mill (F&V), Bangalore", modal_price="2000"),
        ]
        series = build_series(records, commodity="Tomato", market="Kolar")
        assert len(series) == 1 and series[0].value == 1000.0

    def test_skips_records_without_a_modal_price(self, make_record):
        records = [make_record(modal_price=None)]
        assert build_series(records, commodity="Tomato") == []

    def test_unknown_commodity_returns_empty(self, make_record):
        assert build_series([make_record()], commodity="Nonexistent") == []


class TestModels:
    def test_naive_repeats_the_last_value(self):
        assert naive(line(10), 3) == [line(10)[-1].value] * 3

    def test_naive_requires_history(self):
        with pytest.raises(ValueError):
            naive([], 3)

    def test_moving_average_is_flat(self):
        history = line(10, base=100, slope=10)  # last 7: 130..190
        result = moving_average(history, 4, window=7)
        assert len(set(result)) == 1
        assert 150 < result[0] < 200

    def test_seasonal_naive_reuses_the_period(self):
        history = line(14)
        result = seasonal_naive(history, 7, period=7)
        assert result == [p.value for p in history[-7:]]

    def test_drift_extrapolates_the_trend(self):
        history = line(20, base=1000, slope=10)
        result = drift(history, 3)
        assert result[0] > history[-1].value
        assert result[0] == pytest.approx(history[-1].value + 10)

    def test_drift_falls_back_to_naive_when_too_short(self):
        single = line(1)
        assert drift(single, 3) == naive(single, 3)


class TestBacktest:
    def test_produces_all_metrics(self):
        result = backtest(line(60), "moving_average", horizon=7, min_train=30)
        assert result.folds > 0
        assert result.mae >= 0
        assert result.rmse >= result.mae - 1e-9  # RMSE >= MAE always
        assert result.mape >= 0

    def test_requires_enough_history(self):
        with pytest.raises(ValueError, match="at least"):
            backtest(line(10), "naive", horizon=7, min_train=30)

    def test_drift_beats_naive_on_a_trending_series(self):
        # A perfectly linear series is the one case where extrapolating wins.
        result = backtest(line(80, base=1000, slope=20), "drift", horizon=7, min_train=30)
        assert result.skill > 0.9
        assert result.as_dict()["beats_baseline"] is True

    def test_seasonal_naive_is_the_baseline_when_there_is_no_trend(self):
        # Flat series: naive is already perfect, so nothing should beat it much.
        result = backtest(line(60, base=1500, slope=0), "moving_average", horizon=7, min_train=30)
        assert result.mape == pytest.approx(0.0, abs=1e-6)
        assert result.skill == pytest.approx(0.0, abs=1e-6)

    def test_skill_is_reported_even_when_negative(self):
        # Deliberately bad model: predicting a constant far from the truth.
        def terrible(history, horizon):
            return [1.0] * horizon

        result = backtest(line(60, base=1000, slope=20), terrible, horizon=7, min_train=30)
        assert result.skill < 0
        assert result.as_dict()["beats_baseline"] is False

    def test_folds_increase_with_history(self):
        short = backtest(line(50), "naive", horizon=7, min_train=30)
        long = backtest(line(90), "naive", horizon=7, min_train=30)
        assert long.folds > short.folds


class TestCompareModels:
    def test_returns_sorted_by_mape(self):
        results = compare_models(line(80, slope=15), horizon=7, min_train=30)
        mapes = [r.mape for r in results]
        assert mapes == sorted(mapes)

    def test_includes_every_builtin_model(self):
        results = compare_models(line(80), horizon=7, min_train=30)
        assert {r.model_name for r in results} == {
            "naive", "seasonal_naive", "moving_average", "drift"
        }


class TestForecastOutput:
    def test_produces_the_requested_horizon(self):
        assert len(forecast(line(30), horizon=5)) == 5

    def test_dates_continue_the_sequence(self):
        history = line(10)
        points = forecast(history, horizon=3)
        assert points[0].day == history[-1].day + timedelta(days=1)
        assert points[-1].day == history[-1].day + timedelta(days=3)

    def test_rejects_empty_history(self):
        with pytest.raises(ValueError):
            forecast([], horizon=3)
