"""Honest baseline forecasting — pure Python, no heavy dependencies.

Design philosophy for a student project: **beat a baseline or admit you didn't.**

Anyone can plot a fancy model. Very few students can say "our model achieves
an 11% lower MAPE than the naive baseline across 30 walk-forward folds, on
these specific commodities, and here is where it fails." The second sentence is
what gets you hired, and it is impossible to fake.

That's why this module is built around walk-forward **backtesting** with an
explicit **skill score against the naive baseline**, not around a clever model.

Models here:
  * naive            -> tomorrow's price = today's price
  * seasonal_naive   -> tomorrow's price = price 7 days ago (weekly market cycle)
  * moving_average   -> mean of the last `window` observations
  * drift            -> naive + average daily change extrapolated

Once these are exhausted, add Prophet/ARIMA in week 5 and report whether it
actually helps. Often on this data, it barely does — and knowing that is a result.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from kisanmandi.ingest.schema import MandiPriceRecord


@dataclass(frozen=True)
class Point:
    day: date
    value: float

    def __iter__(self):
        yield self.day
        yield self.value


@dataclass
class BacktestResult:
    model_name: str
    horizon_days: int
    folds: int
    mae: float
    rmse: float
    mape: float
    baseline_mape: float

    @property
    def skill(self) -> float:
        """1 - model/baseline. Positive means we beat the naive baseline.

        A negative number is a *result*, not a failure. Report it.
        """
        if self.baseline_mape == 0:
            return 0.0
        return round(1.0 - (self.mape / self.baseline_mape), 4)

    @property
    def skill_pct(self) -> float:
        return round(self.skill * 100, 2)

    def as_dict(self) -> dict:
        return {
            "model": self.model_name,
            "horizon_days": self.horizon_days,
            "folds": self.folds,
            "mae": round(self.mae, 2),
            "rmse": round(self.rmse, 2),
            "mape_pct": round(self.mape, 2),
            "baseline_mape_pct": round(self.baseline_mape, 2),
            "skill_pct": self.skill_pct,
            "beats_baseline": self.skill > 0,
        }


# ---------------------------------------------------------------------- #
# series construction
# ---------------------------------------------------------------------- #
def build_series(
    records: Iterable[MandiPriceRecord],
    *,
    commodity: str,
    market: str | None = None,
    district: str | None = None,
) -> list[Point]:
    """Collapse records into one clean daily price series, sorted by date.

    Multiple rows for the same day (different varieties/grades) are averaged,
    weighted by nothing — simple mean is honest and documented. If two grades
    differ a lot, that is itself worth investigating later.
    """
    buckets: dict[date, list[float]] = {}
    for record in records:
        if record.commodity.lower() != commodity.lower():
            continue
        if market and record.market.lower() != market.lower():
            continue
        if district and record.district.lower() != district.lower():
            continue
        if record.modal_price is None:
            continue
        buckets.setdefault(record.arrival_date, []).append(float(record.modal_price))

    return [Point(day=day, value=statistics.fmean(values)) for day, values in sorted(buckets.items())]


# ---------------------------------------------------------------------- #
# models: each takes history + horizon, returns a flat list of length horizon
# ---------------------------------------------------------------------- #
def naive(history: Sequence[Point], horizon: int) -> list[float]:
    if not history:
        raise ValueError("naive forecast needs at least one observation")
    return [history[-1].value] * horizon


def seasonal_naive(history: Sequence[Point], horizon: int, period: int = 7) -> list[float]:
    if not history:
        raise ValueError("seasonal_naive needs at least one observation")
    forecast: list[float] = []
    for step in range(1, horizon + 1):
        index = len(history) - period + ((step - 1) % period)
        if 0 <= index < len(history):
            forecast.append(history[index].value)
        else:
            forecast.append(history[-1].value)
    return forecast


def moving_average(history: Sequence[Point], horizon: int, window: int = 7) -> list[float]:
    if not history:
        raise ValueError("moving_average needs at least one observation")
    tail = [p.value for p in history[-window:]]
    return [statistics.fmean(tail)] * horizon


def drift(history: Sequence[Point], horizon: int) -> list[float]:
    """Extrapolate the average daily change since the start of the window."""
    if len(history) < 2:
        return naive(history, horizon)
    first, last = history[0].value, history[-1].value
    slope = (last - first) / (len(history) - 1)
    return [last + slope * step for step in range(1, horizon + 1)]


MODELS: dict[str, Callable[..., list[float]]] = {
    "naive": naive,
    "seasonal_naive": seasonal_naive,
    "moving_average": moving_average,
    "drift": drift,
}


# ---------------------------------------------------------------------- #
# evaluation
# ---------------------------------------------------------------------- #
def _mape(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Mean absolute percentage error, skipping zero actuals (div by zero)."""
    # strict=False is deliberate: callers may pass a truncated prediction list.
    pairs = [(a, p) for a, p in zip(actual, predicted, strict=False) if a != 0]
    if not pairs:
        return float("nan")
    return 100.0 * statistics.fmean(abs((a - p) / a) for a, p in pairs)


def backtest(
    history: Sequence[Point],
    model: str | Callable[..., list[float]] = "moving_average",
    *,
    horizon: int = 7,
    min_train: int = 21,
    step: int = 1,
) -> BacktestResult:
    """Walk-forward backtest against the naive baseline.

    At each fold we train only on data available *before* the fold, then predict
    the next `horizon` days. Training on the future is the single most common
    mistake in student forecasting projects — this function makes it impossible.
    """
    model_fn = MODELS[model] if isinstance(model, str) else model
    model_name = model if isinstance(model, str) else getattr(model, "__name__", "custom")

    if len(history) < min_train + horizon:
        raise ValueError(
            f"need at least {min_train + horizon} observations for a backtest, got {len(history)}"
        )

    actuals: list[float] = []
    preds: list[float] = []
    baseline_preds: list[float] = []
    folds = 0

    split = min_train
    while split + horizon <= len(history):
        train = history[:split]
        test = history[split : split + horizon]
        try:
            preds.extend(model_fn(train, horizon))
            baseline_preds.extend(naive(train, horizon))
        except ValueError:
            break
        actuals.extend(p.value for p in test)
        folds += 1
        split += step

    if folds == 0:
        raise ValueError("no complete backtest folds could be evaluated")

    errors = [a - p for a, p in zip(actuals, preds, strict=True)]
    mae = statistics.fmean(abs(e) for e in errors)
    rmse = math.sqrt(statistics.fmean(e * e for e in errors))

    return BacktestResult(
        model_name=model_name,
        horizon_days=horizon,
        folds=folds,
        mae=mae,
        rmse=rmse,
        mape=_mape(actuals, preds),
        baseline_mape=_mape(actuals, baseline_preds),
    )


def compare_models(
    history: Sequence[Point], *, horizon: int = 7, min_train: int = 21
) -> list[BacktestResult]:
    """Backtest every built-in model and rank by skill. Feed this to your README."""
    results: list[BacktestResult] = []
    for name in MODELS:
        try:
            results.append(backtest(history, name, horizon=horizon, min_train=min_train))
        except ValueError:
            continue
    return sorted(results, key=lambda r: r.mape)


def forecast(
    history: Sequence[Point], *, horizon: int = 7, model: str = "moving_average"
) -> list[Point]:
    """Produce future points, continuing the date sequence day by day."""
    if not history:
        raise ValueError("cannot forecast an empty series")
    values = MODELS[model](history, horizon)
    last_day = history[-1].day
    return [
        Point(day=date.fromordinal(last_day.toordinal() + step), value=round(float(value), 2))
        for step, value in enumerate(values, start=1)
    ]
