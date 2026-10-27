"""Command-line interface.

    kisanmandi ingest --state Karnataka --commodity Tomato
    kisanmandi quality-report
    kisanmandi models --commodity Tomato --market "Binny Mill (F&V), Bangalore"
    kisanmandi advise --commodity Tomato --district Bengaluru
    kisanmandi stats
    kisanmandi serve

Everything a scheduled job needs is here, so CI and cron call the same code you
run by hand. If it only works from your laptop, it doesn't work.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from kisanmandi import __version__
from kisanmandi.advise import AdvisoryEngine
from kisanmandi.config import get_settings
from kisanmandi.forecast import build_series, compare_models, forecast
from kisanmandi.ingest.client import daily_filters
from kisanmandi.quality.checks import QualityGate
from kisanmandi.storage.db import (
    get_engine,
    init_db,
    load_records,
    make_session_factory,
    session_scope,
    table_counts,
)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx/httpcore can log request URLs, including the private API-key query
    # parameter. Keep our own ingest progress logs without exposing the key.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _session_factory(settings):
    """Engine + schema + session factory.

    Always creating the schema means a fresh clone asking for advice gets
    "no records, run ingest first" rather than a SQL traceback about a missing
    table. Small thing; the difference between a tool and a toy.
    """
    engine = get_engine(settings.database_url)
    init_db(engine)
    return make_session_factory(engine)


# ---------------------------------------------------------------------- #
# commands
# ---------------------------------------------------------------------- #
def cmd_ingest(args: argparse.Namespace) -> int:
    from kisanmandi.pipeline import run_ingest

    settings = get_settings()
    filters = daily_filters(state=args.state, district=args.district, commodity=args.commodity)
    result = run_ingest(settings, filters=filters or None, dry_run=args.dry_run)
    print(json.dumps(result.as_dict(), indent=2))

    if result.quality.quarantined and not args.dry_run:
        # A non-zero quarantine count is normal. A *spike* is not. Alerting on the
        # ratio rather than the absolute number is what stops alert fatigue.
        ratio = result.quality.quarantined / max(result.quality.total_records, 1)
        if ratio > 0.10:
            print(
                f"\nWARNING: {ratio:.1%} of records were quarantined "
                f"(threshold 10%). Investigate before trusting today's data.",
                file=sys.stderr,
            )
    return 0


def cmd_quality_report(args: argparse.Namespace) -> int:
    settings = get_settings()
    factory = _session_factory(settings)

    with session_scope(factory) as session:
        records = load_records(session, commodity=args.commodity, district=args.district)

    if not records:
        print("No records in the database. Run `kisanmandi ingest` first.", file=sys.stderr)
        return 1

    gate = QualityGate(
        min_plausible_price=settings.min_plausible_price,
        max_plausible_price=settings.max_plausible_price,
        staleness_days=settings.staleness_days,
    )
    _, _, report = gate.evaluate(records, reference_date=date.today())
    text = report.to_markdown()
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    """Backtest every model and print a ranked table. Put this in your README."""
    settings = get_settings()
    factory = _session_factory(settings)
    with session_scope(factory) as session:
        records = load_records(
            session, commodity=args.commodity, market=args.market, district=args.district
        )

    series = build_series(records, commodity=args.commodity, market=args.market, district=args.district)
    if len(series) < args.min_train + args.horizon:
        print(
            f"Need at least {args.min_train + args.horizon} daily observations, have {len(series)}.\n"
            f"Backfill with: kisanmandi backfill --commodity {args.commodity} --days 60",
            file=sys.stderr,
        )
        return 1

    results = compare_models(series, horizon=args.horizon, min_train=args.min_train)
    print(f"\nWalk-forward backtest — {args.commodity} ({len(series)} observations, horizon {args.horizon} days)\n")
    print(f"{'model':<18}{'MAE':>10}{'RMSE':>10}{'MAPE%':>10}{'naive%':>10}{'skill':>10}")
    print("-" * 68)
    for r in results:
        flag = "  <-- best" if r is results[0] else ""
        print(
            f"{r.model_name:<18}{r.mae:>10.2f}{r.rmse:>10.2f}"
            f"{r.mape:>10.2f}{r.baseline_mape:>10.2f}{r.skill_pct:>9.1f}%{flag}"
        )
    best = results[0]
    if best.skill <= 0:
        print(
            "\nHonest result: no model beat the naive baseline on this series.\n"
            "Report that. 'We measured it and it didn't help' is a finding, not a failure."
        )
    return 0


def cmd_advise(args: argparse.Namespace) -> int:
    settings = get_settings()
    factory = _session_factory(settings)
    with session_scope(factory) as session:
        records = load_records(session, commodity=args.commodity, district=args.district)

    if not records:
        print(f"No records for {args.commodity!r}. Run `kisanmandi ingest` first.", file=sys.stderr)
        return 1

    engine_adv = AdvisoryEngine(
        horizon_days=args.horizon or settings.forecast_horizon_days,
        hold_threshold_pct=settings.hold_threshold_pct,
        transport_cost_per_quintal=settings.transport_cost_per_quintal,
        min_history_points=settings.min_history_points,
    )
    advice = engine_adv.advise(
        records, commodity=args.commodity, district=args.district, home_market=args.market
    )

    if args.json:
        # Machine mode: JSON only on stdout, so `kisanmandi advise --json | jq`
        # works. Human commentary would break the pipe.
        print(json.dumps(advice.as_dict(), indent=2))
        return 0

    print("\n" + "=" * 72)
    print(advice.headline())
    print("=" * 72 + "\n")
    print(f"action            : {advice.action.value}")
    print(f"confidence        : {advice.confidence}")
    print(f"model             : {advice.model_used}")
    if advice.backtest:
        print(
            f"backtest          : MAPE {advice.backtest.mape:.1f}% vs naive "
            f"{advice.backtest.baseline_mape:.1f}% over {advice.backtest.folds} folds "
            f"(skill {advice.backtest.skill_pct:+.1f}%)"
        )
    print("\nreasoning:")
    for i, reason in enumerate(advice.reasons, 1):
        print(f"  {i}. {reason}")
    return 0


def cmd_forecast(args: argparse.Namespace) -> int:
    settings = get_settings()
    factory = _session_factory(settings)
    with session_scope(factory) as session:
        records = load_records(
            session, commodity=args.commodity, market=args.market, district=args.district
        )
    series = build_series(records, commodity=args.commodity, market=args.market, district=args.district)
    if len(series) < 3:
        print("Not enough history to forecast.", file=sys.stderr)
        return 1

    model = args.model
    if model == "auto":
        # Pick the backtest winner so `forecast` and `advise` never disagree.
        try:
            ranking = compare_models(series, horizon=args.horizon, min_train=args.min_train)
            model = ranking[0].model_name if ranking else "moving_average"
        except ValueError:
            model = "moving_average"

    points = forecast(series, horizon=args.horizon, model=model)
    print(f"\n{args.commodity} — {args.market or args.district or 'all markets'} "
          f"(last observed {series[-1].day} @ Rs {series[-1].value:.0f})")
    print(f"model: {model}{'  [auto-selected by backtest]' if args.model == 'auto' else ''}\n")
    print(f"{'date':<14}{'forecast Rs/quintal':>22}{'vs today':>12}")
    print("-" * 48)
    for p in points:
        delta = p.value - series[-1].value
        print(f"{p.day.isoformat():<14}{p.value:>22.0f}{delta:>+12.0f}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    settings = get_settings()
    factory = _session_factory(settings)
    with session_scope(factory) as session:
        counts = table_counts(session)
    print(json.dumps(
        {
            "database": settings.database_url,
            "counts": counts,
            "landing_backend": settings.landing_backend,
            "has_personal_api_key": settings.has_personal_api_key,
            "config": {
                "page_size": settings.page_size,
                "max_pages": settings.max_pages,
                "staleness_days": settings.staleness_days,
                "hold_threshold_pct": settings.hold_threshold_pct,
                "transport_cost_per_quintal": settings.transport_cost_per_quintal,
                "min_history_points": settings.min_history_points,
            },
        },
        indent=2,
    ))
    if not settings.has_personal_api_key:
        print(
            "\nNOTE: DATA_GOV_API_KEY is unset, so responses fall back to the demo key\n"
            "and are capped at 10 records per request. Register a free key:\n"
            "  https://data.gov.in/user/register",
            file=sys.stderr,
        )
    return 0


def cmd_verify_landing(args: argparse.Namespace) -> int:
    """Recompute checksums on the raw landing zone. Should always pass."""
    import hashlib

    from kisanmandi.ingest.landing import get_landing_zone

    settings = get_settings()
    zone = get_landing_zone(settings)
    manifests = [k for k in zone.list_keys("manifests/") if k.endswith("manifest.json")]
    if not manifests:
        print("No manifests found — nothing to verify.", file=sys.stderr)
        return 1

    total = ok = 0
    for manifest_key in manifests:
        manifest = json.loads(zone.get(manifest_key))
        for page in manifest.get("pages", []):
            total += 1
            actual = hashlib.sha256(zone.get(page["key"])).hexdigest()
            if actual == page["sha256"]:
                ok += 1
            else:
                print(f"MISMATCH {page['key']}", file=sys.stderr)
    print(f"verified {ok}/{total} landed pages against their recorded checksums")
    return 0 if ok == total else 2


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "kisanmandi.api.main:app",
        host=args.host or settings.api_host,
        port=args.port or settings.api_port,
        reload=args.reload,
    )
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    """Pull one day at a time going backwards — useful for bootstrapping history.

    Slow on purpose. The API is rate limited and a backfill is exactly the kind of
    job that hammers it if you're careless.
    """
    from kisanmandi.pipeline import run_ingest

    settings = get_settings()
    today = date.today()
    inserted_total = 0
    for offset in range(args.days):
        day = today - timedelta(days=offset)
        filters = daily_filters(state=args.state, district=args.district,
                                commodity=args.commodity, arrival_date=day)
        try:
            result = run_ingest(settings, filters=filters or None, ingest_date=day)
        except Exception as exc:
            print(f"{day}: failed ({exc})", file=sys.stderr)
            continue
        inserted_total += result.inserted
        print(f"{day}: fetched={result.stats.records} inserted={result.inserted} "
              f"quarantined={result.quality.quarantined}")
    print(f"\nbackfill complete: {inserted_total} new rows")
    return 0


# ---------------------------------------------------------------------- #
# parser
# ---------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kisanmandi",
        description="Mandi price intelligence for Indian farmers.",
    )
    parser.add_argument("--version", action="version", version=f"kisanmandi {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="fetch today's prices and store them")
    p.add_argument("--state")
    p.add_argument("--district")
    p.add_argument("--commodity")
    p.add_argument("--dry-run", action="store_true", help="fetch and validate, write nothing")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("backfill", help="pull the last N days, one API call per day")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--state")
    p.add_argument("--district")
    p.add_argument("--commodity")
    p.set_defaults(func=cmd_backfill)

    p = sub.add_parser("quality-report", help="regenerate the data-quality report")
    p.add_argument("--commodity")
    p.add_argument("--district")
    p.add_argument("--out", help="write markdown to this path")
    p.set_defaults(func=cmd_quality_report)

    p = sub.add_parser("models", help="backtest models and rank them by skill")
    p.add_argument("--commodity", required=True)
    p.add_argument("--market")
    p.add_argument("--district")
    p.add_argument("--horizon", type=int, default=7)
    p.add_argument("--min-train", type=int, default=21)
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("advise", help="sell / hold / go-to-another-mandi recommendation")
    p.add_argument("--commodity", required=True)
    p.add_argument("--district")
    p.add_argument("--market")
    p.add_argument("--horizon", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_advise)

    p = sub.add_parser("forecast", help="print a simple price forecast")
    p.add_argument("--commodity", required=True)
    p.add_argument("--market")
    p.add_argument("--district")
    p.add_argument("--horizon", type=int, default=7)
    p.add_argument(
        "--model",
        default="auto",
        choices=["auto", "naive", "seasonal_naive", "moving_average", "drift"],
        help="'auto' picks the best model by walk-forward backtest (default)",
    )
    p.add_argument("--min-train", type=int, default=21)
    p.set_defaults(func=cmd_forecast)

    p = sub.add_parser("stats", help="show row counts and effective config")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("verify-landing", help="verify landed raw pages against checksums")
    p.set_defaults(func=cmd_verify_landing)

    p = sub.add_parser("serve", help="run the API")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
