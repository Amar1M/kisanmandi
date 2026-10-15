"""The advisory engine: turn price history into a decision.

**The deliverable is a decision, not a chart.**

A farmer does not need another dashboard. They need one sentence: *"Sell now at
Binny Mill"* or *"Hold 5 days — the model expects about ₹190/quintal more."*

So this module outputs exactly that, plus the arithmetic behind it, so a human
can disagree with the reasoning. Every number in `reasons` is reproducible from
the inputs — never hand-wave a recommendation.

Explicit assumptions (state these in your report; they are the weakest link):
  * Prices are ₹ per quintal.
  * `transport_cost_per_quintal` is a *configured constant*, not measured. Ask a
    local farmer or transporter for a real number in week 2 and put it in your
    README. A guessed constant presented as a measured one is the fastest way to
    lose credibility.
  * Holding grain carries risk (spoilage, theft, price reversal). The expected
    gain is an expectation, not a promise — the advice text says so.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum

from kisanmandi.forecast.baseline import (
    BacktestResult,
    Point,
    build_series,
    compare_models,
    forecast,
)
from kisanmandi.ingest.schema import MandiPriceRecord


class Action(str, Enum):
    SELL_NOW = "SELL_NOW"
    HOLD = "HOLD"
    TRANSPORT_TO_OTHER_MANDI = "TRANSPORT_TO_OTHER_MANDI"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass
class MarketView:
    market: str
    latest_price: float
    latest_date: date
    history_points: int
    forecast_price: float | None = None

    def as_dict(self) -> dict:
        return {
            "market": self.market,
            "latest_price": round(self.latest_price, 2),
            "latest_date": self.latest_date.isoformat(),
            "history_points": self.history_points,
            "forecast_price": round(self.forecast_price, 2) if self.forecast_price is not None else None,
        }


@dataclass
class Advice:
    action: Action
    commodity: str
    district: str | None
    home_market: str | None
    current_price: float | None
    expected_price: float | None
    expected_gain_per_quintal: float
    horizon_days: int
    best_market: str | None = None
    confidence: str = "low"
    model_used: str | None = None
    backtest: BacktestResult | None = None
    reasons: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def headline(self) -> str:
        """One sentence for an SMS. Keep it under 160 characters."""
        if self.action is Action.INSUFFICIENT_DATA:
            return (
                f"{self.commodity}: not enough price history yet to advise safely. "
                f"Keep recording daily prices."
            )
        if self.action is Action.SELL_NOW:
            return (
                f"{self.commodity} at {self.home_market}: sell now at about "
                f"Rs {self.current_price:.0f}/quintal. No better option expected this week."
            )
        if self.action is Action.HOLD:
            return (
                f"{self.commodity} at {self.home_market}: HOLD {self.horizon_days} days. "
                f"Expected about Rs {self.expected_price:.0f}/quintal "
                f"(+Rs {self.expected_gain_per_quintal:.0f}). Selling is always an option."
            )
        return (
            f"{self.commodity}: take it to {self.best_market} instead of {self.home_market}. "
            f"About +Rs {self.expected_gain_per_quintal:.0f}/quintal after transport."
        )

    def as_dict(self) -> dict:
        return {
            "action": self.action.value,
            "commodity": self.commodity,
            "district": self.district,
            "home_market": self.home_market,
            "best_market": self.best_market,
            "current_price": round(self.current_price, 2) if self.current_price else None,
            "expected_price": round(self.expected_price, 2) if self.expected_price else None,
            "expected_gain_per_quintal": round(self.expected_gain_per_quintal, 2),
            "horizon_days": self.horizon_days,
            "confidence": self.confidence,
            "model_used": self.model_used,
            "backtest": self.backtest.as_dict() if self.backtest else None,
            "headline": self.headline(),
            "reasons": self.reasons,
            "generated_at": self.generated_at,
        }


class AdvisoryEngine:
    def __init__(
        self,
        *,
        horizon_days: int = 7,
        hold_threshold_pct: float = 3.0,
        transport_cost_per_quintal: float = 150.0,
        min_history_points: int = 21,
    ) -> None:
        self.horizon_days = horizon_days
        self.hold_threshold_pct = hold_threshold_pct
        self.transport_cost_per_quintal = transport_cost_per_quintal
        self.min_history_points = min_history_points

    # ---------------------------------------------------------------- #
    def _market_views(
        self, records: list[MandiPriceRecord], commodity: str, district: str | None
    ) -> dict[str, list[Point]]:
        markets: set[str] = {
            r.market
            for r in records
            if r.commodity.lower() == commodity.lower()
            and (district is None or r.district.lower() == district.lower())
        }
        series: dict[str, list[Point]] = {}
        for market in markets:
            points = build_series(records, commodity=commodity, market=market, district=district)
            if points:
                series[market] = points
        return series

    # ---------------------------------------------------------------- #
    def advise(
        self,
        records: list[MandiPriceRecord],
        *,
        commodity: str,
        district: str | None = None,
        home_market: str | None = None,
    ) -> Advice:
        series_by_market = self._market_views(records, commodity, district)

        if not series_by_market:
            return Advice(
                action=Action.INSUFFICIENT_DATA,
                commodity=commodity,
                district=district,
                home_market=None,
                current_price=None,
                expected_price=None,
                expected_gain_per_quintal=0.0,
                horizon_days=self.horizon_days,
                reasons=[f"No price history found for {commodity}" + (f" in {district}" if district else "")],
            )

        # Pick a home mandi: the one with the most history (most reliable),
        # unless the caller told us which market the farmer actually uses.
        if home_market and home_market in series_by_market:
            chosen = home_market
        else:
            chosen = max(series_by_market, key=lambda m: len(series_by_market[m]))

        home_series = series_by_market[chosen]
        reasons: list[str] = [
            f"Home mandi: {chosen} with {len(home_series)} daily observations.",
        ]

        if len(home_series) < self.min_history_points:
            return Advice(
                action=Action.INSUFFICIENT_DATA,
                commodity=commodity,
                district=district,
                home_market=chosen,
                current_price=home_series[-1].value,
                expected_price=None,
                expected_gain_per_quintal=0.0,
                horizon_days=self.horizon_days,
                confidence="low",
                reasons=reasons
                + [
                    f"Only {len(home_series)} observations; need at least "
                    f"{self.min_history_points} before issuing advice. "
                    f"Refusing to guess is a feature."
                ],
            )

        # --- choose a model honestly, using a backtest on the home market ---
        model_used = "moving_average"
        bt: BacktestResult | None = None
        try:
            ranking = compare_models(home_series, horizon=self.horizon_days, min_train=self.min_history_points)
            if ranking:
                best = ranking[0]
                bt = best
                model_used = best.model_name
                reasons.append(
                    f"Backtest over {best.folds} walk-forward folds picked '{best.model_name}' "
                    f"(MAPE {best.mape:.1f}% vs naive {best.baseline_mape:.1f}%, "
                    f"skill {best.skill_pct:+.1f}%)."
                )
                if best.skill <= 0:
                    reasons.append(
                        "NOTE: the best model did not beat the naive baseline on this series. "
                        "Treat the forecast as weak evidence."
                    )
        except ValueError as exc:
            reasons.append(f"Backtest skipped ({exc}); falling back to moving average.")

        future = forecast(home_series, horizon=self.horizon_days, model=model_used)
        expected_price = round(statistics.fmean(p.value for p in future), 2)
        current_price = round(home_series[-1].value, 2)

        hold_gain = expected_price - current_price
        hold_gain_pct = (hold_gain / current_price * 100.0) if current_price else 0.0
        reasons.append(
            f"Forecast for {chosen} in {self.horizon_days} days: Rs {expected_price:.0f} "
            f"(now Rs {current_price:.0f}, change {hold_gain:+.0f} / {hold_gain_pct:+.1f}%)."
        )

        # --- compare with other mandis in the district ---
        best_market: str | None = None
        best_transport_gain = float("-inf")
        for market, points in series_by_market.items():
            if market == chosen:
                continue
            other_price = points[-1].value
            net = other_price - current_price - self.transport_cost_per_quintal
            if net > best_transport_gain:
                best_transport_gain = net
                best_market = market

        if best_market is not None:
            reasons.append(
                f"Best alternative mandi: {best_market} at "
                f"Rs {series_by_market[best_market][-1].value:.0f} — net "
                f"{best_transport_gain:+.0f}/quintal after "
                f"Rs {self.transport_cost_per_quintal:.0f} transport."
            )

        # --- confidence from data volume + backtest skill ---
        if bt and bt.skill > 0 and len(home_series) >= 2 * self.min_history_points:
            confidence = "high"
        elif len(home_series) >= self.min_history_points:
            confidence = "medium"
        else:
            confidence = "low"

        # --- the decision, in priority order ---
        transport_wins = best_market is not None and best_transport_gain > 0 and best_transport_gain >= hold_gain
        holds = hold_gain_pct >= self.hold_threshold_pct

        if transport_wins:
            action = Action.TRANSPORT_TO_OTHER_MANDI
            gain = best_transport_gain
            reasons.append(
                f"DECISION: selling at {best_market} nets {best_transport_gain:+.0f} vs holding "
                f"for {hold_gain:+.0f}. Transport wins."
            )
        elif holds:
            action = Action.HOLD
            gain = hold_gain
            reasons.append(
                f"DECISION: expected gain {hold_gain_pct:+.1f}% clears the "
                f"{self.hold_threshold_pct:.1f}% hold threshold."
            )
        else:
            action = Action.SELL_NOW
            gain = 0.0
            reasons.append(
                f"DECISION: expected gain {hold_gain_pct:+.1f}% is below the "
                f"{self.hold_threshold_pct:.1f}% hold threshold, and no other mandi "
                f"nets more than transport costs. Sell."
            )

        advice = Advice(
            action=action,
            commodity=commodity,
            district=district,
            home_market=chosen,
            current_price=current_price,
            expected_price=expected_price,
            expected_gain_per_quintal=round(gain, 2),
            horizon_days=self.horizon_days,
            best_market=best_market if action is Action.TRANSPORT_TO_OTHER_MANDI else None,
            confidence=confidence,
            model_used=model_used,
            backtest=bt,
            reasons=reasons,
        )
        return advice
