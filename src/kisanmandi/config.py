"""Configuration for KisanMandi, loaded from environment variables.

We deliberately use a plain dataclass instead of pydantic-settings so the
config layer has zero extra dependencies and is trivially testable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv is optional at runtime
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


def _get(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _get_int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)) or default)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(_get(name, str(default)) or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """All tunables in one place.

    Nothing here costs money. See COSTS.md — the whole project runs on free tiers.
    """

    # ---- data.gov.in (Agmarknet daily mandi prices) ----
    # Register a FREE personal key at https://data.gov.in/user/register
    # The shared public demo key caps responses at 10 records per request,
    # which is why pagination + rate limiting is a real engineering task here.
    data_gov_api_key: str = field(default_factory=lambda: _get("DATA_GOV_API_KEY", "") or "")
    data_gov_resource_id: str = field(
        default_factory=lambda: _get(
            "DATA_GOV_RESOURCE_ID", "9ef84268-d588-465a-a308-a864a43d0070"
        )
    )
    data_gov_base_url: str = field(
        default_factory=lambda: _get("DATA_GOV_BASE_URL", "https://api.data.gov.in/resource")
    )
    # data.gov.in allows up to 1000 records/page with a personal key.
    page_size: int = field(default_factory=lambda: _get_int("PAGE_SIZE", 1000))
    # Be a good citizen: minimum seconds between HTTP requests.
    min_request_interval_seconds: float = field(
        default_factory=lambda: _get_float("MIN_REQUEST_INTERVAL_SECONDS", 1.0)
    )
    max_retries: int = field(default_factory=lambda: _get_int("MAX_RETRIES", 5))
    request_timeout_seconds: float = field(
        default_factory=lambda: _get_float("REQUEST_TIMEOUT_SECONDS", 30.0)
    )
    max_pages: int = field(default_factory=lambda: _get_int("MAX_PAGES", 50))

    # ---- storage ----
    database_url: str = field(
        default_factory=lambda: _get("DATABASE_URL", "sqlite:///./data/kisanmandi.db") or ""
    )
    data_dir: Path = field(default_factory=lambda: Path(_get("DATA_DIR", "./data") or "./data"))

    # ---- immutable raw landing zone (local by default; R2/S3 in the cloud) ----
    landing_backend: str = field(default_factory=lambda: _get("LANDING_BACKEND", "local") or "local")
    landing_local_dir: Path = field(
        default_factory=lambda: Path(_get("LANDING_LOCAL_DIR", "./data/landing") or "./data/landing")
    )
    s3_endpoint_url: str | None = field(default_factory=lambda: _get("S3_ENDPOINT_URL"))
    s3_bucket: str | None = field(default_factory=lambda: _get("S3_BUCKET"))
    s3_access_key_id: str | None = field(default_factory=lambda: _get("S3_ACCESS_KEY_ID"))
    s3_secret_access_key: str | None = field(default_factory=lambda: _get("S3_SECRET_ACCESS_KEY"))
    s3_region: str = field(default_factory=lambda: _get("S3_REGION", "auto") or "auto")

    # ---- data quality thresholds ----
    # Agmarknet prices are rupees per quintal.
    min_plausible_price: float = field(default_factory=lambda: _get_float("MIN_PLAUSIBLE_PRICE", 10.0))
    max_plausible_price: float = field(
        default_factory=lambda: _get_float("MAX_PLAUSIBLE_PRICE", 100_000.0)
    )
    staleness_days: int = field(default_factory=lambda: _get_int("STALENESS_DAYS", 7))

    # ---- advisory model assumptions (make these explicit; they are defensible) ----
    forecast_horizon_days: int = field(default_factory=lambda: _get_int("FORECAST_HORIZON_DAYS", 7))
    hold_threshold_pct: float = field(default_factory=lambda: _get_float("HOLD_THRESHOLD_PCT", 3.0))
    transport_cost_per_quintal: float = field(
        default_factory=lambda: _get_float("TRANSPORT_COST_PER_QUINTAL", 150.0)
    )
    min_history_points: int = field(default_factory=lambda: _get_int("MIN_HISTORY_POINTS", 21))

    # ---- api ----
    api_host: str = field(default_factory=lambda: _get("API_HOST", "0.0.0.0") or "0.0.0.0")
    api_port: int = field(default_factory=lambda: _get_int("API_PORT", 8000))

    @property
    def has_personal_api_key(self) -> bool:
        """False means we're on the throttled public demo key."""
        return bool(self.data_gov_api_key)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.landing_local_dir.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    global _settings
    if _settings is None or reload:
        _settings = Settings()
    return _settings
