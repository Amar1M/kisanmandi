"""Pydantic models for one Agmarknet mandi price row.

The upstream feed from data.gov.in is *messy*: prices arrive as strings, dates as
dd/mm/yyyy, and some fields are blank or whitespace. Everything is normalised
here, at the boundary, so the rest of the codebase only ever sees clean objects.

That single decision — validate at the edge, trust internally — is worth
mentioning in your report.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

# Formats data.gov.in actually returns for `arrival_date`
_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y")

_NUMERIC_CLEAN = re.compile(r"[^\d.\-]")


def _clean_numeric(value: object) -> object:
    """Turn '1,200' / ' 1200.50 ' / '' into a Decimal or None."""
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return value
    text = str(value).strip()
    if text == "" or text.upper() in {"NA", "N/A", "NULL", "NONE", "-"}:
        return None
    text = _NUMERIC_CLEAN.sub("", text)
    if text in {"", "-", "."}:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if text == "":
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class MandiPriceRecord(BaseModel):
    """A single clean observation: one commodity, one mandi, one day."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    state: str
    district: str
    market: str
    commodity: str
    variety: str = ""
    grade: str = ""
    arrival_date: date
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    modal_price: Decimal | None = None

    @field_validator("arrival_date", mode="before")
    @classmethod
    def _v_date(cls, v: object) -> object:
        return _parse_date(v)

    @field_validator("min_price", "max_price", "modal_price", mode="before")
    @classmethod
    def _v_price(cls, v: object) -> object:
        return _clean_numeric(v)

    @field_validator("variety", "grade", mode="before")
    @classmethod
    def _v_optional_text(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @model_validator(mode="after")
    def _normalise_uppercase_keys(self) -> MandiPriceRecord:
        # Keep place names consistent so 'Bengaluru' and 'BENGALURU' don't
        # fragment the time series. Display casing is a UI concern.
        object.__setattr__(self, "state", self.state.title())
        object.__setattr__(self, "district", self.district.title())
        object.__setattr__(self, "commodity", self.commodity.title())
        return self

    # ------------------------------------------------------------------ #
    # Identity
    # ------------------------------------------------------------------ #
    @property
    def natural_key(self) -> str:
        """Stable idempotency key for this observation.

        The same mandi publishing the same price for the same day twice must
        produce the same key, so re-running an ingest never double-counts.
        """
        parts = [
            self.state,
            self.district,
            self.market,
            self.commodity,
            self.variety,
            self.grade,
            self.arrival_date.isoformat(),
        ]
        raw = "|".join(p.strip().lower() for p in parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @property
    def price_ordering_ok(self) -> bool:
        """min <= modal <= max, for whichever of the three are present."""
        present = [p for p in (self.min_price, self.modal_price, self.max_price) if p is not None]
        return present == sorted(present)

    def to_row(self) -> dict:
        """Flatten to a DB row dict."""
        return {
            "natural_key": self.natural_key,
            "state": self.state,
            "district": self.district,
            "market": self.market,
            "commodity": self.commodity,
            "variety": self.variety,
            "grade": self.grade,
            "arrival_date": self.arrival_date,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "modal_price": self.modal_price,
        }


def parse_records(raw_records: list[dict]) -> tuple[list[MandiPriceRecord], list[dict]]:
    """Split raw API rows into (valid_models, rejected_rows_with_reason)."""
    valid: list[MandiPriceRecord] = []
    rejected: list[dict] = []
    for raw in raw_records:
        try:
            valid.append(MandiPriceRecord(**raw))
        except Exception as exc:  # validation error -> quarantine, never crash the run
            rejected.append({"raw": raw, "reason": str(exc).splitlines()[0][:200]})
    return valid, rejected
