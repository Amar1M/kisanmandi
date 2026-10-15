"""Immutable raw landing zone.

The rule: **never transform data you haven't first stored raw.**

Every ingest writes the untouched API response to a dated, Hive-partitioned path
and records a SHA-256 checksum in a manifest. That gives you three things:

1. **Replay** — if your transform has a bug, re-run it over history without
   re-hitting the upstream API (which is rate limited and occasionally down).
2. **Tamper evidence** — the checksum proves the raw bytes haven't changed.
3. **Cheap migration** — the `source=/ingest_date=` layout is exactly what
   Athena/Glue expects, so pointing a query engine at it later is a config
   change, not a rewrite.

Backends: `local` (default, ₹0, fine for development) and `s3` (Cloudflare R2,
10 GB free with zero egress fees — see COSTS.md).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


def _partition_key(source: str, ingest_date: date, page_index: int) -> str:
    """Hive-style key: raw/source=agmarknet/ingest_date=2026-10-15/page-0000.json"""
    return (
        f"raw/source={source}/ingest_date={ingest_date.isoformat()}/"
        f"page-{page_index:04d}.json"
    )


@dataclass
class LandingManifestEntry:
    key: str
    sha256: str
    bytes: int
    records: int
    written_at: str

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "records": self.records,
            "written_at": self.written_at,
        }


class LandingZone(Protocol):
    def put(self, key: str, payload: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...


class LocalLandingZone:
    """Filesystem landing zone. Zero cost, adequate for dev and for a demo."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Guard against path traversal from a malformed key.
        safe = Path(key.replace("\\", "/"))
        if safe.is_absolute() or ".." in safe.parts:
            raise ValueError(f"unsafe landing key: {key!r}")
        return self.root / safe

    def put(self, key: str, payload: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a crash never leaves a half-written "immutable" file.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(payload)
        tmp.replace(path)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def list_keys(self, prefix: str = "") -> list[str]:
        base = self._path(prefix) if prefix else self.root
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)).replace("\\", "/") for p in base.rglob("*.json"))


class S3LandingZone:
    """S3-compatible landing zone — works with Cloudflare R2, Backblaze B2 or AWS S3."""

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        region: str = "auto",
    ) -> None:
        import boto3  # imported lazily so local-only users don't need it

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
        )

    def put(self, key: str, payload: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=payload)

    def get(self, key: str) -> bytes:
        obj = self.client.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read()

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def list_keys(self, prefix: str = "") -> list[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return sorted(keys)


def get_landing_zone(settings) -> LocalLandingZone | S3LandingZone:
    """Pick a backend from config. Defaults to local so nothing is required to start."""
    if settings.landing_backend == "s3":
        if not settings.s3_bucket:
            raise ValueError("LANDING_BACKEND=s3 requires S3_BUCKET")
        return S3LandingZone(
            settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            region=settings.s3_region,
        )
    return LocalLandingZone(settings.landing_local_dir)


@dataclass
class LandingWriter:
    """Writes raw payloads plus a checksummed manifest for the run."""

    zone: LandingZone
    source: str = "agmarknet"

    def write_page(
        self,
        payload: dict,
        *,
        ingest_date: date | None = None,
        page_index: int = 0,
    ) -> LandingManifestEntry:
        ingest_date = ingest_date or datetime.now(timezone.utc).date()
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        key = _partition_key(self.source, ingest_date, page_index)
        self.zone.put(key, body)
        entry = LandingManifestEntry(
            key=key,
            sha256=hashlib.sha256(body).hexdigest(),
            bytes=len(body),
            records=len(payload.get("records") or []),
            written_at=datetime.now(timezone.utc).isoformat(),
        )
        log.debug("landed %s (%s bytes, sha256=%s...)", key, entry.bytes, entry.sha256[:12])
        return entry

    def write_manifest(
        self,
        entries: list[LandingManifestEntry],
        *,
        ingest_date: date | None = None,
        extra: dict | None = None,
    ) -> str:
        """The manifest is what makes the landing zone auditable."""
        ingest_date = ingest_date or datetime.now(timezone.utc).date()
        key = f"manifests/source={self.source}/ingest_date={ingest_date.isoformat()}/manifest.json"
        body = json.dumps(
            {
                "source": self.source,
                "ingest_date": ingest_date.isoformat(),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "page_count": len(entries),
                "total_bytes": sum(e.bytes for e in entries),
                "total_records": sum(e.records for e in entries),
                "pages": [e.as_dict() for e in entries],
                **(extra or {}),
            },
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        self.zone.put(key, body)
        return key

    @staticmethod
    def verify(zone: LandingZone, key: str, expected_sha256: str) -> bool:
        """Recompute the checksum of a stored page.

        Call this in your weekly integrity job. If it ever returns False, someone
        mutated your raw data — which is exactly the thing an immutable landing
        zone exists to detect.
        """
        actual = hashlib.sha256(zone.get(key)).hexdigest()
        return actual == expected_sha256
