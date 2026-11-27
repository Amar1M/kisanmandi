#!/usr/bin/env python3
"""Run one bounded, quality-gated Karnataka ingest for the public Pages demo.

The script refuses to use the shared demo key: a personal key must be supplied
through the DATA_GOV_API_KEY environment variable (GitHub Actions secret).
"""

from __future__ import annotations

import json
import logging

from kisanmandi.config import Settings
from kisanmandi.ingest.client import daily_filters
from kisanmandi.pipeline import run_ingest


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # httpx INFO request logs include the full URL, including data.gov.in's
    # api-key query parameter. Suppress those loggers before any request.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    settings = Settings()
    if not settings.data_gov_api_key:
        raise SystemExit("DATA_GOV_API_KEY is required; refusing the shared demo key.")

    result = run_ingest(settings, filters=daily_filters(state="Karnataka"))
    stats = result.stats
    received = stats.records + stats.rejected

    if stats.records == 0 or result.quality.passed == 0:
        raise SystemExit(
            "No quality-approved Karnataka records; refusing to publish an empty snapshot."
        )
    if stats.total_reported is not None and received < stats.total_reported:
        raise SystemExit(
            f"Ingest truncated: received {received} of {stats.total_reported} reported records."
        )
    if stats.pages >= settings.max_pages and stats.total_reported is None:
        raise SystemExit(
            "Ingest reached MAX_PAGES without a reported total; refusing a possibly partial snapshot."
        )

    # Intentionally omit all credential/config values from this summary.
    print(
        json.dumps(
            {
                "state": "Karnataka",
                "requests": stats.requests,
                "pages": stats.pages,
                "records_received": received,
                "records_valid": stats.records,
                "records_rejected": stats.rejected,
                "quality_passed": result.quality.passed,
                "quality_quarantined": result.quality.quarantined,
                "duration_seconds": stats.duration_seconds,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
