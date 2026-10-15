"""Read-only HTTP API.

Kept deliberately small. The value of this project is the pipeline and the
quality gate, not the REST surface. But an API is what makes the advice usable
by an SMS gateway, a PWA, or a Telegram bot later — so it exists from day one.

Endpoints
    GET /health              liveness + row counts
    GET /v1/prices           recent observations for a commodity
    GET /v1/advice           the one-sentence recommendation
    GET /v1/series           the daily price series a forecast was built from
    GET /v1/quality/latest   the most recent data-quality report
    GET /metrics             Prometheus-exposition-format metrics
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse

from kisanmandi import __version__
from kisanmandi.advise import AdvisoryEngine
from kisanmandi.config import Settings, get_settings
from kisanmandi.forecast import build_series
from kisanmandi.storage.db import (
    get_engine,
    init_db,
    load_records,
    make_session_factory,
    session_scope,
    table_counts,
)

log = logging.getLogger(__name__)


class Metrics:
    """A tiny counter registry that emits Prometheus text format.

    Deliberately dependency-free. When you outgrow it (week 9), swap in
    prometheus_client and keep the same endpoint contract.
    """

    def __init__(self) -> None:
        self._counters: dict[str, float] = {}

    def inc(self, name: str, value: float = 1.0) -> None:
        self._counters[name] = self._counters.get(name, 0.0) + value

    def set(self, name: str, value: float) -> None:
        self._counters[name] = float(value)

    def render(self) -> str:
        lines = ["# KisanMandi metrics (Prometheus exposition format)"]
        for name, value in sorted(self._counters.items()):
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")
        return "\n".join(lines) + "\n"


metrics = Metrics()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="KisanMandi API",
        version=__version__,
        description="Mandi price intelligence: prices, quality reports, and sell/hold advice.",
    )

    engine = get_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)

    engine_advisory = AdvisoryEngine(
        horizon_days=settings.forecast_horizon_days,
        hold_threshold_pct=settings.hold_threshold_pct,
        transport_cost_per_quintal=settings.transport_cost_per_quintal,
        min_history_points=settings.min_history_points,
    )

    @app.get("/health")
    def health() -> dict:
        try:
            with session_scope(session_factory) as session:
                counts = table_counts(session)
            healthy = True
        except Exception as exc:  # pragma: no cover
            counts = {"error": str(exc)}
            healthy = False
        metrics.inc("kisanmandi_health_checks_total")
        return {
            "status": "ok" if healthy else "degraded",
            "version": __version__,
            "database": settings.database_url.split("://", 1)[0],
            "counts": counts,
        }

    @app.get("/v1/prices")
    def prices(
        commodity: str = Query(..., min_length=2),
        district: str | None = None,
        market: str | None = None,
        days: int = Query(30, ge=1, le=365),
    ) -> dict:
        since = date.today() - timedelta(days=days)
        with session_scope(session_factory) as session:
            records = load_records(
                session, commodity=commodity, district=district, market=market, since=since
            )
        metrics.inc("kisanmandi_prices_requests_total")
        return {
            "commodity": commodity,
            "district": district,
            "count": len(records),
            "records": [
                {
                    "state": r.state,
                    "district": r.district,
                    "market": r.market,
                    "commodity": r.commodity,
                    "variety": r.variety,
                    "grade": r.grade,
                    "arrival_date": r.arrival_date.isoformat(),
                    "min_price": float(r.min_price) if r.min_price is not None else None,
                    "max_price": float(r.max_price) if r.max_price is not None else None,
                    "modal_price": float(r.modal_price) if r.modal_price is not None else None,
                }
                for r in records
            ],
        }

    @app.get("/v1/series")
    def series(
        commodity: str = Query(..., min_length=2),
        market: str | None = None,
        district: str | None = None,
    ) -> dict:
        with session_scope(session_factory) as session:
            records = load_records(session, commodity=commodity, district=district, market=market)
        points = build_series(records, commodity=commodity, market=market, district=district)
        if not points:
            raise HTTPException(status_code=404, detail=f"no price history for {commodity!r}")
        return {
            "commodity": commodity,
            "market": market,
            "points": len(points),
            "series": [{"date": p.day.isoformat(), "price": round(p.value, 2)} for p in points],
        }

    @app.get("/v1/advice")
    def advice(
        commodity: str = Query(..., min_length=2),
        district: str | None = None,
        market: str | None = None,
    ) -> dict:
        with session_scope(session_factory) as session:
            records = load_records(session, commodity=commodity, district=district, market=market)
        if not records:
            raise HTTPException(status_code=404, detail=f"no records for {commodity!r}")
        result = engine_advisory.advise(
            records, commodity=commodity, district=district, home_market=market
        )
        metrics.inc("kisanmandi_advice_requests_total")
        metrics.inc(f"kisanmandi_advice_action_{result.action.value.lower()}_total")
        return result.as_dict()

    @app.get("/v1/quality/latest")
    def quality_latest() -> dict:
        path = Path(settings.data_dir) / "reports" / "quality-latest.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="no quality report has been generated yet")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/metrics", response_class=PlainTextResponse)
    def prometheus_metrics() -> str:
        try:
            with session_scope(session_factory) as session:
                counts = table_counts(session)
            for key, value in counts.items():
                metrics.set(f"kisanmandi_{key}", value)
        except Exception:  # pragma: no cover
            pass
        return metrics.render()

    return app


app = create_app()
