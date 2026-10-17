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

import html
import json
import logging
import os
import platform
import socket
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

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


def _render_dashboard(info: dict) -> str:
    app_meta = info["app"]
    pipe = info["pipeline"]
    sys_meta = info["system"]
    counts = pipe["counts"]
    key_mode = "Personal API Key" if pipe["has_personal_api_key"] else "Public Demo Key (10/req)"
    commit_short = html.escape(str(app_meta["commit"])[:12])
    env_label = html.escape(str(app_meta["environment"]))
    build_label = html.escape(str(app_meta["build"]))
    db_label = html.escape(str(pipe["database"]))
    landing_label = html.escape(str(pipe["landing_backend"]))
    host_label = html.escape(str(sys_meta["hostname"]))
    plat_label = html.escape(str(sys_meta["platform"])[:44])
    py_label = html.escape(str(sys_meta["python_version"]))
    ts_label = html.escape(str(sys_meta["timestamp"])[:19])
    prices_n = counts.get("mandi_prices", 0)
    quar_n = counts.get("quarantined_rows", 0)
    runs_n = counts.get("ingest_runs", 0)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>KisanMandi — Mandi Price Intelligence &amp; Cloud DevOps Pipeline</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
      background: #0f172a; color: #e2e8f0; line-height: 1.6;
    }}
    .container {{ max-width: 1120px; margin: 0 auto; padding: 20px; }}
    header {{
      background: linear-gradient(135deg, #059669 0%, #1d4ed8 100%);
      padding: 30px; border-radius: 12px; margin-bottom: 24px; text-align: center;
    }}
    header h1 {{ font-size: 2.1em; margin-bottom: 8px; }}
    header p {{ opacity: 0.92; font-size: 1.05em; }}
    .badge {{
      display: inline-block; background: #10b981; color: #fff;
      padding: 5px 12px; border-radius: 20px; font-size: 0.84em;
      margin: 5px; font-weight: 700;
    }}
    .badge.live {{ background: #ef4444; animation: pulse 2s infinite; }}
    @keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.7; }} }}
    .pipeline, .endpoints, .card {{
      background: #1e293b; border-radius: 12px; padding: 20px;
      border: 1px solid #334155; margin-bottom: 24px;
    }}
    h3 {{
      color: #60a5fa; margin-bottom: 14px; font-size: 1.18em;
      border-bottom: 2px solid #334155; padding-bottom: 8px;
    }}
    .flow {{
      display: flex; align-items: center; justify-content: center;
      flex-wrap: wrap; gap: 10px; margin: 16px 0;
    }}
    .flow-item {{
      background: #064e3b; padding: 12px 16px; border-radius: 8px;
      border: 2px solid #10b981; text-align: center; min-width: 125px;
    }}
    .flow-arrow {{ font-size: 1.4em; color: #60a5fa; }}
    .highlight {{
      background: rgba(16, 185, 129, 0.12); border-left: 4px solid #10b981;
      padding: 14px; border-radius: 8px; margin-top: 12px; font-size: 0.95em;
    }}
    .grid {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(310px, 1fr));
      gap: 20px; margin-bottom: 24px;
    }}
    .grid .card {{ margin-bottom: 0; }}
    ul {{ list-style: none; }}
    li {{
      padding: 8px 0; border-bottom: 1px solid #0f172a;
      display: flex; justify-content: space-between; gap: 12px;
    }}
    li:last-child {{ border-bottom: none; }}
    .label {{ color: #94a3b8; }}
    .value {{ color: #f8fafc; font-weight: 600; font-family: monospace; }}
    .endpoint {{
      display: flex; justify-content: space-between; align-items: center;
      padding: 12px; background: #0f172a; border-radius: 8px; margin: 8px 0;
    }}
    .endpoint a {{ color: #60a5fa; text-decoration: none; font-family: monospace; }}
    .endpoint a:hover {{ text-decoration: underline; }}
    .method {{
      background: #10b981; color: #fff; padding: 3px 8px;
      border-radius: 4px; font-size: 0.75em; font-weight: 700; margin-right: 8px;
    }}
    footer {{ text-align: center; margin-top: 20px; padding: 16px; color: #64748b; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>🌾 KisanMandi — Mandi Price Intelligence</h1>
      <p>Agmarknet API &rarr; SHA-256 Raw Landing &rarr; Quality Gate &rarr; Walk-Forward Forecast &rarr; Farmer Advisory</p>
      <div style="margin-top: 14px;">
        <span class="badge live">● LIVE PIPELINE</span>
        <span class="badge">v{html.escape(__version__)}</span>
        <span class="badge">DB: {db_label}</span>
        <span class="badge">Commit: {commit_short}</span>
      </div>
    </header>

    <div class="pipeline">
      <h3>🔄 End-to-End Data &amp; DevOps Architecture</h3>
      <div class="flow">
        <div class="flow-item">🌐<br><strong>Agmarknet</strong><br><small>data.gov.in</small></div>
        <div class="flow-arrow">&rarr;</div>
        <div class="flow-item">🔒<br><strong>Raw Zone</strong><br><small>SHA-256 Manifest</small></div>
        <div class="flow-arrow">&rarr;</div>
        <div class="flow-item">🛡️<br><strong>Quality Gate</strong><br><small>Blocker / Warn</small></div>
        <div class="flow-arrow">&rarr;</div>
        <div class="flow-item">📈<br><strong>Backtest</strong><br><small>4 Baseline Models</small></div>
        <div class="flow-arrow">&rarr;</div>
        <div class="flow-item">🚜<br><strong>Advisory</strong><br><small>Sell / Hold / Move</small></div>
        <div class="flow-arrow">&rarr;</div>
        <div class="flow-item">⚙️<br><strong>CI/CD &amp; Metrics</strong><br><small>Actions + Prom</small></div>
      </div>
      <div class="highlight">
        <strong>Design principle:</strong> The deliverable is a reproducible decision
        (<code>SELL_NOW</code> / <code>HOLD</code> / <code>TRANSPORT_TO_OTHER_MANDI</code>),
        not just a chart. Every raw page is checksummed before validation; bad rows are
        quarantined rather than silently dropped.
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <h3>📊 Live Pipeline &amp; Storage Telemetry</h3>
        <ul>
          <li><span class="label">Mandi Prices Stored</span><span class="value">{prices_n}</span></li>
          <li><span class="label">Quarantined Rows</span><span class="value">{quar_n}</span></li>
          <li><span class="label">Ingest Runs</span><span class="value">{runs_n}</span></li>
          <li><span class="label">Database Engine</span><span class="value">{db_label}</span></li>
          <li><span class="label">Landing Zone</span><span class="value">{landing_label}</span></li>
          <li><span class="label">API Key Mode</span><span class="value">{key_mode}</span></li>
        </ul>
      </div>
      <div class="card">
        <h3>🖥️ Deployment &amp; System Info</h3>
        <ul>
          <li><span class="label">Environment</span><span class="value">{env_label}</span></li>
          <li><span class="label">Build / Commit</span><span class="value">#{build_label} ({commit_short})</span></li>
          <li><span class="label">Hostname</span><span class="value">{host_label}</span></li>
          <li><span class="label">Platform</span><span class="value">{plat_label}</span></li>
          <li><span class="label">Python / CPUs</span><span class="value">{py_label} ({sys_meta["cpu_count"]} cores)</span></li>
          <li><span class="label">UTC Timestamp</span><span class="value">{ts_label}</span></li>
        </ul>
      </div>
    </div>

    <div class="endpoints">
      <h3>🔌 Interactive API Endpoints (Click to inspect)</h3>
      <div class="endpoint">
        <div><span class="method">GET</span><a href="/docs" target="_blank">/docs</a> — Interactive OpenAPI / Swagger UI</div>
        <span>📘</span>
      </div>
      <div class="endpoint">
        <div><span class="method">GET</span><a href="/health" target="_blank">/health</a> — Liveness probe + table row counts</div>
        <span>✅</span>
      </div>
      <div class="endpoint">
        <div><span class="method">GET</span><a href="/api/info" target="_blank">/api/info</a> — Full pipeline, build &amp; system JSON</div>
        <span>📊</span>
      </div>
      <div class="endpoint">
        <div><span class="method">GET</span><a href="/v1/prices?commodity=Tomato&amp;days=30" target="_blank">/v1/prices?commodity=Tomato&amp;days=30</a> — Recent mandi price observations</div>
        <span>🍅</span>
      </div>
      <div class="endpoint">
        <div><span class="method">GET</span><a href="/v1/advice?commodity=Tomato&amp;market=Kolar" target="_blank">/v1/advice?commodity=Tomato&amp;market=Kolar</a> — Sell / Hold / Transport decision + audit trail</div>
        <span>🚜</span>
      </div>
      <div class="endpoint">
        <div><span class="method">GET</span><a href="/v1/series?commodity=Tomato&amp;market=Kolar" target="_blank">/v1/series?commodity=Tomato&amp;market=Kolar</a> — Daily modal price time series</div>
        <span>📈</span>
      </div>
      <div class="endpoint">
        <div><span class="method">GET</span><a href="/v1/quality/latest" target="_blank">/v1/quality/latest</a> — Latest data-quality &amp; anomaly report</div>
        <span>🛡️</span>
      </div>
      <div class="endpoint">
        <div><span class="method">GET</span><a href="/metrics" target="_blank">/metrics</a> — Prometheus exposition format metrics</div>
        <span>📡</span>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <h3>🛠️ Cloud &amp; DevOps Stack</h3>
        <ul>
          <li><span class="label">Application</span><span class="value">FastAPI + SQLAlchemy 2 + Pydantic v2</span></li>
          <li><span class="label">Quality &amp; Tests</span><span class="value">126 Pytest (91% cov) + Ruff + Gitleaks</span></li>
          <li><span class="label">Containers</span><span class="value">Multi-stage Docker + Compose</span></li>
          <li><span class="label">CI/CD</span><span class="value">GitHub Actions (py3.10–3.14 + Cron)</span></li>
          <li><span class="label">IaC &amp; K8s</span><span class="value">Terraform + Helm Chart + systemd</span></li>
          <li><span class="label">Observability</span><span class="value">Prometheus /metrics + Audit Trail</span></li>
        </ul>
      </div>
      <div class="card">
        <h3>👨‍💻 Built By</h3>
        <ul>
          <li><span class="label">Name</span><span class="value">Amar M S (Amarnath Reddy)</span></li>
          <li><span class="label">Course</span><span class="value">MCA Cloud &amp; DevOps 2027</span></li>
          <li><span class="label">University</span><span class="value">S-VYASA Bengaluru</span></li>
          <li><span class="label">GitHub</span><span class="value"><a href="https://github.com/Amar1M/kisanmandi" style="color:#60a5fa;">github.com/Amar1M/kisanmandi</a></span></li>
          <li><span class="label">Previous Live Demo</span><span class="value"><a href="http://16.4.47.0" style="color:#10b981;">http://16.4.47.0 (AWS EC2)</a></span></li>
          <li><span class="label">Role Focus</span><span class="value" style="color:#10b981;">Cloud / DevOps / Data Engineering</span></li>
        </ul>
      </div>
    </div>

    <footer>
      <p>KisanMandi v{html.escape(__version__)} &middot; Open-source Mandi Price Intelligence for Indian Farmers &middot; MIT License</p>
    </footer>
  </div>
</body>
</html>"""


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

    def _collect_info() -> dict:
        try:
            with session_scope(session_factory) as session:
                counts = table_counts(session)
        except Exception as exc:  # pragma: no cover
            counts = {"error": str(exc)}
        commit = os.getenv("GIT_COMMIT") or os.getenv("APP_VERSION") or "local"
        return {
            "app": {
                "name": "kisanmandi",
                "version": __version__,
                "build": os.getenv("BUILD_NUMBER", "local"),
                "commit": commit,
                "environment": os.getenv("ENVIRONMENT", "development"),
            },
            "pipeline": {
                "database": settings.database_url.split("://", 1)[0],
                "landing_backend": settings.landing_backend,
                "has_personal_api_key": settings.has_personal_api_key,
                "counts": counts,
            },
            "system": {
                "hostname": socket.gethostname(),
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "cpu_count": os.cpu_count() or 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "endpoints": [
                {"method": "GET", "path": "/", "description": "Live pipeline dashboard"},
                {"method": "GET", "path": "/docs", "description": "Interactive Swagger UI"},
                {"method": "GET", "path": "/health", "description": "Liveness + row counts"},
                {"method": "GET", "path": "/api/info", "description": "System & pipeline info"},
                {"method": "GET", "path": "/v1/prices", "description": "Recent mandi prices"},
                {"method": "GET", "path": "/v1/series", "description": "Daily modal price series"},
                {"method": "GET", "path": "/v1/advice", "description": "Sell/Hold/Transport advice"},
                {"method": "GET", "path": "/v1/quality/latest", "description": "Quality report"},
                {"method": "GET", "path": "/metrics", "description": "Prometheus metrics"},
            ],
        }

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        metrics.inc("kisanmandi_dashboard_views_total")
        return _render_dashboard(_collect_info())

    @app.get("/api/info")
    def api_info() -> dict:
        metrics.inc("kisanmandi_info_requests_total")
        return _collect_info()

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
