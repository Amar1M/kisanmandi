"""The daily pipeline — this is the thing that runs on a schedule.

Order matters and is deliberate:

    fetch  ->  land raw  ->  validate  ->  gate  ->  store  ->  report

* **Land raw before you validate.** If your validation logic has a bug (it will),
  you can re-run the whole pipeline over stored history without re-hitting a
  rate-limited API. Transformations are cheap; data collection is not.
* **Gate before you store.** Dirty rows never reach the table that forecasts read.
* **Report every run.** The quality report is a product, not a debug artifact.
* **Record the run in a table.** When someone asks "did yesterday's job succeed?",
  the answer should be a SQL query, not a guess.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from kisanmandi.config import Settings, get_settings
from kisanmandi.forecast import Point
from kisanmandi.ingest.client import AgmarknetClient, IngestStats
from kisanmandi.ingest.landing import LandingWriter, get_landing_zone
from kisanmandi.quality import QualityReport
from kisanmandi.quality.checks import QualityGate
from kisanmandi.storage.db import (
    IngestRun,
    get_engine,
    init_db,
    make_session_factory,
    record_quarantine,
    session_scope,
    table_counts,
    upsert_prices,
)

log = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    stats: IngestStats
    quality: QualityReport
    inserted: int = 0
    skipped_duplicates: int = 0
    quarantined: int = 0
    landing_manifest_key: str | None = None
    report_paths: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    dry_run: bool = False

    def as_dict(self) -> dict:
        return {
            "stats": self.stats.as_dict(),
            "quality": {
                "total": self.quality.total_records,
                "passed": self.quality.passed,
                "quarantined": self.quality.quarantined,
                "pass_rate_pct": self.quality.pass_rate,
                "by_check": self.quality.by_check,
            },
            "inserted": self.inserted,
            "skipped_duplicates": self.skipped_duplicates,
            "quarantined": self.quarantined,
            "landing_manifest_key": self.landing_manifest_key,
            "report_paths": self.report_paths,
            "table_counts": self.counts,
            "dry_run": self.dry_run,
        }


def _write_reports(report: QualityReport, out_dir: Path, ingest_date: date) -> list[str]:
    """Persist the quality report as both JSON (machine) and Markdown (human)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = ingest_date.isoformat()
    json_path = out_dir / f"quality-{stamp}.json"
    md_path = out_dir / f"quality-{stamp}.md"
    json_path.write_text(report.to_json(), encoding="utf-8")
    md_path.write_text(report.to_markdown(), encoding="utf-8")
    # Also maintain a rolling "latest" pair so the API and README can always link
    # to the current state without knowing today's date.
    (out_dir / "quality-latest.json").write_text(report.to_json(), encoding="utf-8")
    (out_dir / "quality-latest.md").write_text(report.to_markdown(), encoding="utf-8")
    return [str(json_path), str(md_path)]


def run_ingest(
    settings: Settings | None = None,
    *,
    filters: dict[str, str] | None = None,
    ingest_date: date | None = None,
    dry_run: bool = False,
    client: AgmarknetClient | None = None,
) -> PipelineResult:
    """Run one full ingest → quality → store → report cycle."""
    settings = settings or get_settings()
    settings.ensure_dirs()
    ingest_date = ingest_date or datetime.now(timezone.utc).date()

    engine = get_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)

    gate = QualityGate(
        min_plausible_price=settings.min_plausible_price,
        max_plausible_price=settings.max_plausible_price,
        staleness_days=settings.staleness_days,
    )

    owns_client = client is None
    client = client or AgmarknetClient(
        settings.data_gov_api_key,
        resource_id=settings.data_gov_resource_id,
        base_url=settings.data_gov_base_url,
        page_size=settings.page_size,
        min_request_interval=settings.min_request_interval_seconds,
        max_retries=settings.max_retries,
        timeout=settings.request_timeout_seconds,
    )

    run_id: int | None = None
    try:
        if not dry_run:
            with session_scope(session_factory) as session:
                run = IngestRun(
                    started_at=datetime.now(timezone.utc),
                    status="running",
                    filters=json.dumps(filters or {}),
                )
                session.add(run)
                session.flush()
                run_id = run.id

        log.info("starting ingest (filters=%s, dry_run=%s)", filters, dry_run)
        ingest = client.fetch_all(filters, max_pages=settings.max_pages, keep_pages=True)

        # ---- land raw payloads before any transformation ----
        manifest_key: str | None = None
        if not dry_run and ingest.raw_pages:
            landing = get_landing_zone(settings)
            writer = LandingWriter(landing, source="agmarknet")
            entries = [
                writer.write_page(payload, ingest_date=ingest_date, page_index=i)
                for i, payload in enumerate(ingest.raw_pages)
            ]
            manifest_key = writer.write_manifest(
                entries,
                ingest_date=ingest_date,
                extra={
                    "filters": filters or {},
                    "stats": ingest.stats.as_dict(),
                },
            )
            log.info("landed %s pages, manifest at %s", len(entries), manifest_key)

        # ---- quality gate ----
        loadable, quarantined_records, report = gate.evaluate(
            ingest.records, reference_date=ingest_date
        )
        report_paths = _write_reports(report, settings.data_dir / "reports", ingest_date)

        # ---- store ----
        inserted = skipped = quarantined_count = 0
        if not dry_run:
            with session_scope(session_factory) as session:
                inserted, skipped = upsert_prices(session, loadable)
                quarantined_count = record_quarantine(session, report.issues)
                if run_id is not None:
                    run = session.get(IngestRun, run_id)
                    if run is not None:
                        run.finished_at = datetime.now(timezone.utc)
                        run.status = "success"
                        run.requests = ingest.stats.requests
                        run.pages = ingest.stats.pages
                        run.fetched = ingest.stats.records
                        run.inserted = inserted
                        run.skipped_duplicates = skipped
                        run.quarantined = quarantined_count
                        run.duration_seconds = ingest.stats.duration_seconds

            with session_scope(session_factory) as session:
                counts = table_counts(session)
        else:
            counts = {}

        result = PipelineResult(
            stats=ingest.stats,
            quality=report,
            inserted=inserted,
            skipped_duplicates=skipped,
            quarantined=quarantined_count,
            landing_manifest_key=manifest_key,
            report_paths=report_paths,
            counts=counts,
            dry_run=dry_run,
        )
        log.info("pipeline done: %s", json.dumps(result.as_dict()))
        return result

    except Exception as exc:
        log.exception("pipeline failed")
        if not dry_run and run_id is not None:
            with session_scope(session_factory) as session:
                run = session.get(IngestRun, run_id)
                if run is not None:
                    run.finished_at = datetime.now(timezone.utc)
                    run.status = "failed"
                    run.error = f"{type(exc).__name__}: {exc}"[:2000]
        raise
    finally:
        if owns_client:
            client.close()


def daily_price_series(records, *, commodity: str, market: str | None = None) -> list[Point]:
    """Convenience re-export so the CLI and API share one code path."""
    from kisanmandi.forecast import build_series

    return build_series(records, commodity=commodity, market=market)
