"""Advisory engine: does it refuse to guess, and does it pick the right action?"""

from __future__ import annotations

import pytest

from kisanmandi.advise.engine import Action, AdvisoryEngine


@pytest.fixture
def engine() -> AdvisoryEngine:
    return AdvisoryEngine(
        horizon_days=7,
        hold_threshold_pct=3.0,
        transport_cost_per_quintal=150.0,
        min_history_points=10,
    )


class TestRefusal:
    def test_unknown_commodity_returns_insufficient_data(self, engine, make_series):
        records = make_series(commodity="Tomato", days=40)
        advice = engine.advise(records, commodity="Dragonfruit")
        assert advice.action is Action.INSUFFICIENT_DATA
        assert advice.current_price is None

    def test_short_history_is_refused_rather_than_guessed(self, engine, make_series):
        records = make_series(days=4)  # below min_history_points
        advice = engine.advise(records, commodity="Tomato")
        assert advice.action is Action.INSUFFICIENT_DATA
        assert "Refusing to guess" in " ".join(advice.reasons)
        # The current price is still reported - refusing to advise is not refusing to inform.
        assert advice.current_price is not None


class TestSellNow:
    def test_flat_prices_lead_to_sell_now(self, engine, make_series):
        records = make_series(days=40, base=1500.0, slope=0.0)
        advice = engine.advise(records, commodity="Tomato")
        assert advice.action is Action.SELL_NOW
        assert advice.expected_gain_per_quintal == 0.0
        assert any("Sell" in r for r in advice.reasons)


class TestHold:
    def test_strong_uptrend_leads_to_hold(self, engine, make_series):
        # +20/day on a ~1700 base is well above the 3% hold threshold.
        records = make_series(days=40, base=1000.0, slope=20.0)
        advice = engine.advise(records, commodity="Tomato")
        assert advice.action is Action.HOLD
        assert advice.expected_gain_per_quintal > 0
        assert advice.expected_price > advice.current_price

    def test_hold_picks_a_model_based_on_backtest(self, engine, make_series):
        records = make_series(days=40, base=1000.0, slope=20.0)
        advice = engine.advise(records, commodity="Tomato")
        # On a clean trend, drift extrapolation should win the backtest.
        assert advice.model_used == "drift"
        assert advice.backtest is not None
        assert advice.backtest.folds > 0


class TestTransport:
    def test_much_higher_neighbour_mandi_wins(self, engine, make_series):
        home = make_series(
            market="Kolar", district="Kolar", days=40, base=1000.0, slope=0.0
        )
        neighbour = make_series(
            market="Binny Mill (F&V), Bangalore",
            district="Kolar",
            days=40,
            base=1600.0,
            slope=0.0,
        )
        advice = engine.advise(
            home + neighbour, commodity="Tomato", home_market="Kolar"
        )
        assert advice.action is Action.TRANSPORT_TO_OTHER_MANDI
        assert advice.best_market == "Binny Mill (F&V), Bangalore"
        # 1600 - 1000 - 150 transport = 450 net
        assert advice.expected_gain_per_quintal == pytest.approx(450.0)

    def test_small_price_difference_does_not_justify_transport(self, engine, make_series):
        # +100 price difference, but transport costs 150 -> not worth the trip.
        home = make_series(market="Kolar", district="Kolar", days=40, base=1000.0, slope=0.0)
        neighbour = make_series(
            market="Binny Mill (F&V), Bangalore", district="Kolar",
            days=40, base=1100.0, slope=0.0,
        )
        advice = engine.advise(home + neighbour, commodity="Tomato", home_market="Kolar")
        assert advice.action is Action.SELL_NOW


class TestOutputShape:
    def test_headline_fits_in_an_sms(self, engine, make_series):
        for kwargs in (
            {"slope": 0.0},   # SELL_NOW
            {"slope": 25.0},  # HOLD
        ):
            records = make_series(days=40, base=1000.0, **kwargs)
            advice = engine.advise(records, commodity="Tomato")
            assert len(advice.headline()) <= 160, advice.headline()

    def test_as_dict_has_the_contract_fields(self, engine, make_series):
        records = make_series(days=40, base=1000.0, slope=20.0)
        payload = engine.advise(records, commodity="Tomato").as_dict()
        for key in (
            "action", "commodity", "current_price", "expected_price",
            "expected_gain_per_quintal", "confidence", "model_used",
            "backtest", "headline", "reasons", "generated_at",
        ):
            assert key in payload

    def test_confidence_is_high_with_plenty_of_data_and_real_skill(self, engine, make_series):
        records = make_series(days=60, base=1000.0, slope=20.0)
        advice = engine.advise(records, commodity="Tomato")
        assert advice.confidence == "high"

    def test_reasons_are_populated_with_numbers(self, engine, make_series):
        records = make_series(days=40, base=1000.0, slope=20.0)
        advice = engine.advise(records, commodity="Tomato")
        joined = " ".join(advice.reasons)
        assert "observations" in joined
        assert "Backtest" in joined
        assert "DECISION" in joined

    def test_home_market_defaults_to_the_longest_history(self, engine, make_series):
        long_market = make_series(market="Kolar", district="Kolar", days=40, base=1000.0)
        short_market = make_series(
            market="Other", district="Kolar", days=12, base=2000.0
        )
        advice = engine.advise(long_market + short_market, commodity="Tomato")
        assert advice.home_market == "Kolar"
