"""HTTP client for the data.gov.in / Agmarknet daily mandi price API.

Why this file is more than "call an API in 5 lines":

* **Pagination** — the feed has ~16,000 rows/day. The shared public demo key caps
  every response at 10 records, so a full daily pull is ~1,700 requests. You must
  page correctly and know when to stop.
* **Rate limiting** — hammering the endpoint gets you throttled. We self-impose a
  minimum interval between requests.
* **Retries with exponential backoff + jitter** — 429/5xx happen. Transient
  failures must not lose a day of data.
* **Idempotency** — records carry a natural key, so re-running an ingest is safe.

Docs: https://data.gov.in/catalog/current-daily-price-various-commodities-various-markets-mandi
"""

from __future__ import annotations

import contextlib
import json
import logging
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import httpx

from kisanmandi.ingest.schema import MandiPriceRecord, parse_records

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class AgmarknetError(RuntimeError):
    """Raised when the upstream API cannot be read after all retries."""


@dataclass
class IngestStats:
    """Everything you want in a log line and on a Grafana panel."""

    requests: int = 0
    pages: int = 0
    records: int = 0
    rejected: int = 0
    retries: int = 0
    total_reported: int | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None

    @property
    def duration_seconds(self) -> float:
        end = self.finished_at or datetime.now(timezone.utc)
        return round((end - self.started_at).total_seconds(), 3)

    def as_dict(self) -> dict:
        return {
            "requests": self.requests,
            "pages": self.pages,
            "records": self.records,
            "rejected": self.rejected,
            "retries": self.retries,
            "total_reported": self.total_reported,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class IngestResult:
    records: list[MandiPriceRecord]
    rejected: list[dict]
    stats: IngestStats
    raw_pages: list[dict] = field(default_factory=list)


class AgmarknetClient:
    """Thin, well-behaved wrapper around the Agmarknet resource endpoint."""

    def __init__(
        self,
        api_key: str = "",
        *,
        resource_id: str = "9ef84268-d588-465a-a308-a864a43d0070",
        base_url: str = "https://api.data.gov.in/resource",
        page_size: int = 1000,
        min_request_interval: float = 1.0,
        max_retries: int = 5,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], float] = time.monotonic,
        backoff_base: float = 1.5,
        backoff_cap: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.resource_id = resource_id
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self.min_request_interval = min_request_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self._sleep = sleep_fn
        self._clock = clock_fn
        self._last_request_at: float | None = None
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=timeout, headers={"User-Agent": "kisanmandi/0.1 (+student project)"}
        )
        if not self.api_key:
            log.warning(
                "DATA_GOV_API_KEY is empty - falling back to the public demo key. "
                "Responses will be capped at 10 records/request. "
                "Register a free key at https://data.gov.in/user/register"
            )

    # ------------------------------------------------------------------ #
    # context manager
    # ------------------------------------------------------------------ #
    def __enter__(self) -> AgmarknetClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/{self.resource_id}"

    def _throttle(self) -> None:
        """Never issue two requests closer together than min_request_interval."""
        if self.min_request_interval <= 0:
            return
        if self._last_request_at is None:
            return
        elapsed = self._clock() - self._last_request_at
        remaining = self.min_request_interval - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def _backoff_seconds(self, attempt: int, retry_after: str | None = None) -> float:
        """Exponential backoff with full jitter, honouring Retry-After."""
        if retry_after:
            try:
                return min(float(retry_after), self.backoff_cap)
            except ValueError:
                pass
        raw = min(self.backoff_base * (2**attempt), self.backoff_cap)
        # Full jitter: spreads retries so we don't sync up with other clients.
        return random.uniform(0, raw)

    def _request(self, params: dict, stats: IngestStats) -> dict:
        """One GET with throttling and bounded retries."""
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                stats.requests += 1
                self._last_request_at = self._clock()
                response = self._client.get(self.endpoint, params=params, timeout=self.timeout)

                if response.status_code in RETRYABLE_STATUS:
                    retry_after = response.headers.get("Retry-After")
                    wait = self._backoff_seconds(attempt, retry_after)
                    if attempt == self.max_retries:
                        raise AgmarknetError(
                            f"HTTP {response.status_code} after {self.max_retries} retries: "
                            f"{response.text[:200]}"
                        )
                    stats.retries += 1
                    log.warning(
                        "retryable HTTP %s (attempt %s/%s), sleeping %.1fs",
                        response.status_code,
                        attempt + 1,
                        self.max_retries,
                        wait,
                    )
                    self._sleep(wait)
                    continue

                response.raise_for_status()
                payload = response.json()

                if isinstance(payload, dict) and payload.get("status") not in (None, "ok"):
                    raise AgmarknetError(f"API returned status={payload.get('status')!r}")

                return payload

            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                wait = self._backoff_seconds(attempt)
                stats.retries += 1
                log.warning(
                    "transport error %s (attempt %s/%s), sleeping %.1fs",
                    type(exc).__name__,
                    attempt + 1,
                    self.max_retries,
                    wait,
                )
                self._sleep(wait)
            except (AgmarknetError, httpx.HTTPStatusError):
                # Configuration errors (401 bad key, 403, 404 wrong resource id) are
                # not transient. Fail loudly and immediately instead of burning
                # retries and rate limit on a request that will never succeed.
                raise
            except Exception as exc:  # pragma: no cover - defensive
                last_error = exc
                break

        raise AgmarknetError(f"Failed to read Agmarknet after retries: {last_error!r}")

    @staticmethod
    def _build_params(
        offset: int, limit: int, api_key: str, filters: dict[str, str] | None = None
    ) -> dict:
        params: dict[str, str | int] = {
            "api-key": api_key,
            "format": "json",
            "limit": limit,
            "offset": offset,
        }
        for key, value in (filters or {}).items():
            if value:
                params[f"filters[{key}]"] = value
        return params

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    def fetch_page(
        self, offset: int = 0, limit: int | None = None, filters: dict[str, str] | None = None
    ) -> tuple[list[dict], int | None]:
        """Fetch one page. Returns (records, total_reported)."""
        limit = limit or self.page_size
        stats = IngestStats()
        payload = self._request(
            self._build_params(offset, limit, self.api_key, filters), stats
        )
        records = payload.get("records") or []
        total_raw = payload.get("total")
        try:
            total = int(total_raw) if total_raw is not None else None
        except (TypeError, ValueError):
            total = None
        return records, total

    def iter_pages(
        self,
        filters: dict[str, str] | None = None,
        *,
        max_pages: int = 50,
        stats: IngestStats | None = None,
    ) -> Iterator[dict]:
        """Yield whole API payloads, one per page, until the feed is exhausted.

        Yielding *pages* rather than individual records lets the caller land the
        untouched response in object storage before doing anything else.
        """
        stats = stats if stats is not None else IngestStats()
        offset = 0
        for page_index in range(max_pages):
            params = self._build_params(offset, self.page_size, self.api_key, filters)
            payload = self._request(params, stats)
            page = payload.get("records") or []

            total_raw = payload.get("total")
            with contextlib.suppress(TypeError, ValueError):
                stats.total_reported = (
                    int(total_raw) if total_raw is not None else stats.total_reported
                )

            stats.pages += 1
            log.info(
                "page %s: %s records (offset=%s, total_reported=%s)",
                page_index,
                len(page),
                offset,
                stats.total_reported,
            )

            if not page:
                break
            yield payload

            offset += len(page)
            if len(page) < self.page_size:
                break  # a short page means we reached the end
            if stats.total_reported is not None and offset >= stats.total_reported:
                break
        else:
            log.warning("stopped after max_pages=%s - data may be truncated", max_pages)

    def iter_raw(
        self,
        filters: dict[str, str] | None = None,
        *,
        max_pages: int = 50,
        stats: IngestStats | None = None,
    ) -> Iterator[dict]:
        """Yield individual raw record dicts across all pages."""
        for payload in self.iter_pages(filters=filters, max_pages=max_pages, stats=stats):
            yield from (payload.get("records") or [])

    def fetch_all(
        self,
        filters: dict[str, str] | None = None,
        *,
        max_pages: int = 50,
        keep_pages: bool = True,
    ) -> IngestResult:
        """Full ingest: page through everything, validate, and report."""
        stats = IngestStats()
        raw_records: list[dict] = []
        raw_pages: list[dict] = []

        for payload in self.iter_pages(filters=filters, max_pages=max_pages, stats=stats):
            raw_records.extend(payload.get("records") or [])
            if keep_pages:
                raw_pages.append(payload)

        valid, rejected = parse_records(raw_records)
        stats.records = len(valid)
        stats.rejected = len(rejected)
        stats.finished_at = datetime.now(timezone.utc)

        result = IngestResult(records=valid, rejected=rejected, stats=stats, raw_pages=raw_pages)
        log.info("ingest complete: %s", json.dumps(stats.as_dict()))
        return result


def daily_filters(state: str | None = None, district: str | None = None,
                  commodity: str | None = None, arrival_date: date | None = None) -> dict[str, str]:
    """Build the `filters[...]` dict the API expects. Empty values are dropped."""
    return {
        k: v
        for k, v in {
            "state": state,
            "district": district,
            "commodity": commodity,
            "arrival_date": arrival_date.strftime("%d/%m/%Y") if arrival_date else None,
        }.items()
        if v
    }
