"""Ingest layer: read Agmarknet, validate at the boundary, land raw payloads."""

from kisanmandi.ingest.client import (
    AgmarknetClient,
    AgmarknetError,
    IngestResult,
    IngestStats,
    daily_filters,
)
from kisanmandi.ingest.landing import (
    LandingWriter,
    LandingZone,
    LocalLandingZone,
    get_landing_zone,
)
from kisanmandi.ingest.schema import MandiPriceRecord, parse_records

__all__ = [
    "AgmarknetClient",
    "AgmarknetError",
    "IngestResult",
    "IngestStats",
    "daily_filters",
    "LandingWriter",
    "LocalLandingZone",
    "LandingZone",
    "get_landing_zone",
    "MandiPriceRecord",
    "parse_records",
]
