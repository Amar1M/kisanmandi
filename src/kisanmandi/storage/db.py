"""Storage layer.

Defaults to SQLite so `make ingest` works on your laptop with zero setup.
Point DATABASE_URL at Postgres on your Oracle Always Free VM when you deploy.

The unique constraint on `natural_key` is what makes the pipeline idempotent:
re-running today's ingest five times inserts zero duplicate rows. That single
constraint is the difference between a cron job you trust and one you babysit.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import (
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    create_engine,
    func,
    insert,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from kisanmandi.ingest.schema import MandiPriceRecord

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class MandiPrice(Base):
    """One clean observation. The source of truth for every forecast."""

    __tablename__ = "mandi_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    natural_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    district: Mapped[str] = mapped_column(String(64), nullable=False)
    market: Mapped[str] = mapped_column(String(160), nullable=False)
    commodity: Mapped[str] = mapped_column(String(96), nullable=False)
    variety: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    grade: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    arrival_date: Mapped[date] = mapped_column(Date, nullable=False)
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    max_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    modal_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("ix_mandi_commodity_date", "commodity", "arrival_date"),
        Index("ix_mandi_market_date", "market", "arrival_date"),
        Index("ix_mandi_district", "district"),
    )

    def to_record(self) -> MandiPriceRecord:
        return MandiPriceRecord(
            state=self.state,
            district=self.district,
            market=self.market,
            commodity=self.commodity,
            variety=self.variety,
            grade=self.grade,
            arrival_date=self.arrival_date,
            min_price=self.min_price,
            max_price=self.max_price,
            modal_price=self.modal_price,
        )


class QuarantinedRow(Base):
    """Records that failed a BLOCKER check. Kept, never deleted.

    Deleting bad data hides the problem. Keeping it lets you write the
    "Data Quality Report" that is a core part of this project's contribution.
    """

    __tablename__ = "quarantined_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    natural_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    check_name: Mapped[str] = mapped_column(String(48), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    commodity: Mapped[str] = mapped_column(String(96), default="")
    market: Mapped[str] = mapped_column(String(160), default="")
    arrival_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    quarantined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class IngestRun(Base):
    """One row per pipeline execution — your operational history."""

    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="running")
    source: Mapped[str] = mapped_column(String(48), default="agmarknet")
    filters: Mapped[str] = mapped_column(Text, default="")
    requests: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    skipped_duplicates: Mapped[int] = mapped_column(Integer, default=0)
    quarantined: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Numeric(10, 3), default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------- #
# engine / session
# ---------------------------------------------------------------------- #
def _ensure_sqlite_parent_dir(database_url: str) -> None:
    """Create the parent directory for a file-backed SQLite database.

    Guard clauses rather than nested conditionals — flat is easier to read and
    the intent ("do nothing unless this is a real file") is obvious at a glance.
    """
    if not database_url.startswith("sqlite") or ":///" not in database_url:
        return
    raw_path = database_url.split(":///", 1)[1]
    if not raw_path or raw_path == ":memory:":
        return
    Path(raw_path).parent.mkdir(parents=True, exist_ok=True)


def get_engine(database_url: str, *, echo: bool = False) -> Engine:
    _ensure_sqlite_parent_dir(database_url)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, echo=echo, future=True, pool_pre_ping=True, connect_args=connect_args)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------- #
# writes
# ---------------------------------------------------------------------- #
def _insert_for_dialect(session: Session, table, rows: list[dict]):
    """Build an INSERT ... ON CONFLICT DO NOTHING for the active dialect.

    `on_conflict_do_nothing` lives on the dialect-specific Insert construct, not
    the generic one, so we import it per dialect. This is the piece that makes
    re-running an ingest safe rather than a duplicate-row factory.
    """
    dialect = session.bind.dialect.name if session.bind is not None else "sqlite"

    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return (
            pg_insert(table)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["natural_key"])
        )
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        return (
            sqlite_insert(table)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["natural_key"])
        )
    return insert(table).values(rows)  # generic fallback; unique violation surfaces to caller


def upsert_prices(
    session: Session, records: Sequence[MandiPriceRecord], *, chunk_size: int = 500
) -> tuple[int, int]:
    """Insert new observations, silently skip ones already stored.

    Returns (inserted, skipped). Idempotent by construction.
    """
    inserted = skipped = 0
    rows = [r.to_row() for r in records]

    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        if not chunk:
            continue
        before = session.scalar(select(func.count()).select_from(MandiPrice)) or 0
        session.execute(_insert_for_dialect(session, MandiPrice.__table__, chunk))
        session.flush()
        after = session.scalar(select(func.count()).select_from(MandiPrice)) or 0
        changed = after - before
        inserted += changed
        skipped += len(chunk) - changed

    return inserted, skipped


def record_quarantine(session: Session, issues: Sequence) -> int:
    rows = [
        {
            "natural_key": issue.natural_key,
            "check_name": issue.check,
            "detail": issue.detail,
            "commodity": issue.commodity,
            "market": issue.market,
            "arrival_date": date.fromisoformat(issue.arrival_date) if issue.arrival_date else None,
        }
        for issue in issues
        if getattr(issue, "severity", None) is not None and issue.severity.value == "blocker"
    ]
    if rows:
        session.execute(insert(QuarantinedRow.__table__).values(rows))
        session.flush()
    return len(rows)


# ---------------------------------------------------------------------- #
# reads
# ---------------------------------------------------------------------- #
def load_records(
    session: Session,
    *,
    commodity: str | None = None,
    district: str | None = None,
    market: str | None = None,
    since: date | None = None,
    limit: int = 100_000,
) -> list[MandiPriceRecord]:
    stmt = select(MandiPrice)
    if commodity:
        stmt = stmt.where(func.lower(MandiPrice.commodity) == commodity.lower())
    if district:
        stmt = stmt.where(func.lower(MandiPrice.district) == district.lower())
    if market:
        stmt = stmt.where(func.lower(MandiPrice.market) == market.lower())
    if since:
        stmt = stmt.where(MandiPrice.arrival_date >= since)
    stmt = stmt.order_by(MandiPrice.arrival_date).limit(limit)
    return [row.to_record() for row in session.scalars(stmt)]


def table_counts(session: Session) -> dict[str, int]:
    return {
        "mandi_prices": session.scalar(select(func.count()).select_from(MandiPrice)) or 0,
        "quarantined_prices": session.scalar(select(func.count()).select_from(QuarantinedRow)) or 0,
        "ingest_runs": session.scalar(select(func.count()).select_from(IngestRun)) or 0,
    }
