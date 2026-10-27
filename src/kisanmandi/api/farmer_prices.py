"""Farmer-facing price browsing, backed only by stored observations.

These endpoints deliberately do not forecast or recommend a market. Different
varieties, grades and reporting dates are kept separate and made visible.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select

from kisanmandi.api.farmer_page import FARMER_PAGE_HTML
from kisanmandi.storage.db import MandiPrice, session_scope

MAX_COMPARISONS = 100


def create_farmer_router(session_factory, *, staleness_days: int) -> APIRouter:
    router = APIRouter(tags=["Farmer prices"])
    stale_after = max(staleness_days, 0)

    @router.get("/farmers", response_class=HTMLResponse)
    def farmer_page() -> str:
        return FARMER_PAGE_HTML

    @router.get("/v1/farmer/options")
    def farmer_options(
        state: str | None = Query(default=None, min_length=1, max_length=64),
        district: str | None = Query(default=None, min_length=1, max_length=64),
    ) -> dict:
        """Return only locations and crops that exist in the local database."""
        with session_scope(session_factory) as session:
            states = list(session.scalars(
                select(MandiPrice.state)
                .where(MandiPrice.state != "")
                .distinct()
                .order_by(MandiPrice.state)
            ))
            districts: list[str] = []
            commodities: list[str] = []
            if state:
                districts = list(session.scalars(
                    select(MandiPrice.district)
                    .where(MandiPrice.state == state, MandiPrice.district != "")
                    .distinct()
                    .order_by(MandiPrice.district)
                ))
            if state and district:
                commodities = list(session.scalars(
                    select(MandiPrice.commodity)
                    .where(
                        MandiPrice.state == state,
                        MandiPrice.district == district,
                        MandiPrice.commodity != "",
                    )
                    .distinct()
                    .order_by(MandiPrice.commodity)
                ))
        return {"states": states, "districts": districts, "commodities": commodities}

    @router.get("/v1/farmer/prices")
    def farmer_prices(
        state: str = Query(..., min_length=1, max_length=64),
        district: str = Query(..., min_length=1, max_length=64),
        commodity: str = Query(..., min_length=1, max_length=96),
    ) -> dict:
        """Latest stored row per market/variety/grade, never a blended price."""
        ranked = (
            select(
                MandiPrice.market,
                MandiPrice.variety,
                MandiPrice.grade,
                MandiPrice.arrival_date,
                MandiPrice.modal_price,
                func.row_number()
                .over(
                    partition_by=(MandiPrice.market, MandiPrice.variety, MandiPrice.grade),
                    order_by=(MandiPrice.arrival_date.desc(), MandiPrice.id.desc()),
                )
                .label("row_number"),
            )
            .where(
                MandiPrice.state == state,
                MandiPrice.district == district,
                MandiPrice.commodity == commodity,
            )
            .subquery()
        )
        statement = (
            select(
                ranked.c.market,
                ranked.c.variety,
                ranked.c.grade,
                ranked.c.arrival_date,
                ranked.c.modal_price,
            )
            .where(ranked.c.row_number == 1)
            .order_by(ranked.c.arrival_date.desc(), ranked.c.market, ranked.c.variety, ranked.c.grade)
            .limit(MAX_COMPARISONS + 1)
        )
        with session_scope(session_factory) as session:
            rows = list(session.execute(statement))

        today = date.today()
        records = []
        for row in rows[:MAX_COMPARISONS]:
            age_days = (today - row.arrival_date).days
            records.append({
                "market": row.market,
                "variety": row.variety,
                "grade": row.grade,
                "reported_date": row.arrival_date.isoformat(),
                "age_days": age_days,
                "is_stale": age_days > stale_after,
                "is_future": age_days < 0,
                # Keep decimal precision in JSON; the page formats it as rupees.
                "modal_price": str(row.modal_price) if row.modal_price is not None else None,
            })
        return {
            "state": state,
            "district": district,
            "commodity": commodity,
            "source": "Agmarknet via data.gov.in",
            "stale_after_days": stale_after,
            "count": len(records),
            "truncated": len(rows) > MAX_COMPARISONS,
            "records": records,
        }

    return router
