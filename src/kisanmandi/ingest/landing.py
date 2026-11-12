"""Run-scoped raw landing zone.

The rule: **never transform data you haven't first stored raw.** Each writer
gets a unique run ID, so repeated ingests on the same date land in separate
Hive-partitioned paths instead of replacing the previous page and manifest.
SHA-256 checksums detect content changes when verified; they are not, by
themselves, access control or a guarantee against a privileged rewrite.

Backends: `local` (default, ₹0, fine for development) and `s3` (Cloudflare R2,
10 GB free with zero egress fees — see COSTS.md).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

log = logging.getLogger(__name__)


def _partition_key(source: str, ingest_date: date, run_id: str, page_index: int) -> str:
    """Run-scoped Hive key, unique even when a date is ingested more than once."""
    return (
        f"raw/source={source}/ingest_date={ingest_date.isoformat()}/"
        f"run_id={run_id}/page-{page_index:04d}.json"
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
        """Atomically create a new object; never replace an existing raw file."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Stage beside the target, then hard-link atomically. Unlike replace(),
        # link creation fails if the final name already exists.
        tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with tmp.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(tmp, path)
            except FileExistsError:
                raise FileExistsError(f"landing key already exists: {key}") from None
        finally:
            tmp.unlink(missing_ok=True)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def list_keys(self, prefix: str = "") -> list[str]:
        base = self._path(prefix) if prefix else self.root
        if not base.exists():
            return []
        return sorted(
            str(p.relative_to(self.root)).replace("\\", "/") for p in base.rglob("*.json")
        )


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
    """Writes raw pages under a unique run ID plus a checksummed manifest."""

    zone: LandingZone
    source: str = "agmarknet"
    run_id: str = field(default_factory=lambda: uuid4().hex, init=False)
    _written_pages: set[int] = field(default_factory=set, init=False, repr=False)
    _manifest_written: bool = field(default=False, init=False, repr=False)

    def write_page(
        self,
        payload: dict,
        *,
        ingest_date: date | None = None,
        page_index: int = 0,
    ) -> LandingManifestEntry:
        if page_index < 0:
            raise ValueError("page_index must be non-negative")
        if page_index in self._written_pages:
            raise FileExistsError(f"page {page_index} was already written for run {self.run_id}")
        ingest_date = ingest_date or datetime.now(timezone.utc).date()
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        key = _partition_key(self.source, ingest_date, self.run_id, page_index)
        self.zone.put(key, body)
        self._written_pages.add(page_index)
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
        """Write one create-only manifest for this run."""
        if self._manifest_written:
            raise FileExistsError(f"manifest was already written for run {self.run_id}")
        ingest_date = ingest_date or datetime.now(timezone.utc).date()
        key = (
            f"manifests/source={self.source}/ingest_date={ingest_date.isoformat()}/"
            f"run_id={self.run_id}/manifest.json"
        )
        body = json.dumps(
            {
                "source": self.source,
                "ingest_date": ingest_date.isoformat(),
                "run_id": self.run_id,
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
        self._manifest_written = True
        return key

    @staticmethod
    def verify(zone: LandingZone, key: str, expected_sha256: str) -> bool:
        """Recompute a stored page checksum; this detects changes when rechecked.

        A checksum alone is not access control and cannot prevent a privileged
        storage writer from replacing both the object and its manifest.
        """
        actual = hashlib.sha256(zone.get(key)).hexdigest()
        return actual == expected_sha256
