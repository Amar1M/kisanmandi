"""Data-quality gates.

This module is the whole reason KisanMandi is a DevOps project and not a
"download a CSV" exercise.

Public government data arrives dirty: prices of 0, modal prices below the minimum,
dates in the future, the same mandi publishing the same row three times, and
commodities reported in inconsistent units. If you load that straight into a
dashboard you will confidently advise a farmer to sell at a price that never
existed. Bad advice is worse than no advice.

So every ingest runs through a gate that:
  * **BLOCKS** (quarantines) records that are structurally wrong,
  * **WARNS** on records that are suspicious but usable,
  * and emits a machine-readable *and* human-readable report.

The aggregated report becomes a public artifact: "Mandi Price Data Quality
Report" — see docs/03-data-quality-report.md. Almost nobody publishes this for
Indian agricultural data, which is exactly why it is a genuine contribution.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum

from kisanmandi.ingest.schema import MandiPriceRecord


class Severity(str, Enum):
    BLOCKER = "blocker"  # quarantine: never reaches the database
    WARNING = "warning"  # load, but flag it


class Check(str, Enum):
    MISSING_PRICE = "missing_price"
    NON_POSITIVE_PRICE = "non_positive_price"
    INVALID_PRICE_RANGE = "invalid_price_range"
    IMPLAUSIBLE_PRICE = "implausible_price"
    FUTURE_ARRIVAL_DATE = "future_arrival_date"
    STALE_ARRIVAL_DATE = "stale_arrival_date"
    DUPLICATE_NATURAL_KEY = "duplicate_natural_key"
    OUTLIER_PRICE = "outlier_price"


@dataclass
class QualityIssue:
    natural_key: str
    check: str
    severity: Severity
    detail: str
    commodity: str = ""
    market: str = ""
    arrival_date: str = ""

    def as_dict(self) -> dict:
        return {
            "natural_key": self.natural_key,
            "check": self.check,
            "severity": self.severity.value,
            "detail": self.detail,
            "commodity": self.commodity,
            "market": self.market,
            "arrival_date": self.arrival_date,
        }

    @classmethod
    def from_record(cls, record: MandiPriceRecord, check: Check, severity: Severity, detail: str) -> QualityIssue:
        return cls(
            natural_key=record.natural_key,
            check=check.value,
            severity=severity,
            detail=detail,
            commodity=record.commodity,
            market=record.market,
            arrival_date=record.arrival_date.isoformat(),
        )


@dataclass
class QualityReport:
    total_records: int
    passed: int
    quarantined: int
    issues: list[QualityIssue] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "agmarknet"

    @property
    def by_check(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for issue in self.issues:
            out[issue.check] = out.get(issue.check, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    @property
    def by_severity(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for issue in self.issues:
            out[issue.severity.value] = out.get(issue.severity.value, 0) + 1
        return out

    @property
    def pass_rate(self) -> float:
        if self.total_records == 0:
            return 0.0
        return round(100.0 * self.passed / self.total_records, 2)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "generated_at": self.generated_at.isoformat(),
            "total_records": self.total_records,
            "passed": self.passed,
            "quarantined": self.quarantined,
            "pass_rate_pct": self.pass_rate,
            "by_check": self.by_check,
            "by_severity": self.by_severity,
            "issues": [i.as_dict() for i in self.issues],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        """Publishable summary. Drop this straight into your repo's docs/."""
        lines = [
            "# Mandi Price Data Quality Report",
            "",
            f"- **Source:** `{self.source}` (data.gov.in / Agmarknet)",
            f"- **Generated:** {self.generated_at.isoformat()}",
            f"- **Records evaluated:** {self.total_records:,}",
            f"- **Passed:** {self.passed:,}",
            f"- **Quarantined:** {self.quarantined:,}",
            f"- **Pass rate:** {self.pass_rate}%",
            "",
            "## Issues by check",
            "",
        ]
        if not self.issues:
            lines.append("_No issues detected in this batch._")
        else:
            lines += ["| Check | Severity mix | Count |", "|---|---|---:|"]
            for check, count in self.by_check.items():
                severities = {}
                for issue in self.issues:
                    if issue.check == check:
                        severities[issue.severity.value] = severities.get(issue.severity.value, 0) + 1
                mix = ", ".join(f"{k} {v}" for k, v in sorted(severities.items()))
                lines.append(f"| `{check}` | {mix} | {count:,} |")

        if self.issues:
            lines += ["", "## Sample issues (first 10)", "", "| Check | Detail | Commodity | Market | Date |", "|---|---|---|---|---|"]
            for issue in self.issues[:10]:
                detail = issue.detail.replace("|", "/")[:80]
                lines.append(
                    f"| `{issue.check}` | {detail} | {issue.commodity} | {issue.market} | {issue.arrival_date} |"
                )

        lines += [
            "",
            "---",
            "",
            "_Generated by `kisanmandi quality-report`. Reproduce with the exact same input_",
            "_to verify these numbers — that is the point of publishing them._",
        ]
        return "\n".join(lines)


class QualityGate:
    """Runs every check over a batch and splits records into clean vs quarantined."""

    def __init__(
        self,
        *,
        min_plausible_price: float = 10.0,
        max_plausible_price: float = 100_000.0,
        staleness_days: int = 7,
        outlier_z: float = 4.0,
    ) -> None:
        self.min_plausible_price = min_plausible_price
        self.max_plausible_price = max_plausible_price
        self.staleness_days = staleness_days
        self.outlier_z = outlier_z

    # ---------------------------------------------------------------- #
    # individual checks
    # ---------------------------------------------------------------- #
    def _check_record(self, record: MandiPriceRecord, reference_date: date, issues: list[QualityIssue]) -> bool:
        """Return True if the record is loadable (no BLOCKERs)."""
        blocked = False

        prices = [p for p in (record.min_price, record.modal_price, record.max_price) if p is not None]
        if not prices:
            issues.append(QualityIssue.from_record(record, Check.MISSING_PRICE, Severity.BLOCKER,
                                                   "no min/modal/max price present"))
            return False

        for label, value in (("min", record.min_price), ("modal", record.modal_price), ("max", record.max_price)):
            if value is not None and value <= 0:
                issues.append(QualityIssue.from_record(record, Check.NON_POSITIVE_PRICE, Severity.BLOCKER,
                                                       f"{label}_price={value} is not positive"))
                blocked = True

        if not blocked and not record.price_ordering_ok:
            issues.append(QualityIssue.from_record(
                record, Check.INVALID_PRICE_RANGE, Severity.BLOCKER,
                f"ordering violated: min={record.min_price} modal={record.modal_price} max={record.max_price}",
            ))
            blocked = True

        for label, value in (("min", record.min_price), ("modal", record.modal_price), ("max", record.max_price)):
            if value is None:
                continue
            if float(value) > self.max_plausible_price or float(value) < self.min_plausible_price:
                issues.append(QualityIssue.from_record(
                    record, Check.IMPLAUSIBLE_PRICE, Severity.BLOCKER,
                    f"{label}_price={value} outside [{self.min_plausible_price}, {self.max_plausible_price}]",
                ))
                blocked = True

        if record.arrival_date > reference_date:
            issues.append(QualityIssue.from_record(
                record, Check.FUTURE_ARRIVAL_DATE, Severity.BLOCKER,
                f"arrival_date={record.arrival_date} is after reference_date={reference_date}",
            ))
            blocked = True
        else:
            age = (reference_date - record.arrival_date).days
            if age > self.staleness_days:
                issues.append(QualityIssue.from_record(
                    record, Check.STALE_ARRIVAL_DATE, Severity.WARNING,
                    f"arrival_date is {age} days old (threshold {self.staleness_days})",
                ))

        return not blocked

    def _flag_outliers(self, records: list[MandiPriceRecord], issues: list[QualityIssue]) -> None:
        """Robust per-commodity outlier flag using median + MAD.

        Median and MAD instead of mean and standard deviation, because a handful
        of nonsense prices would inflate a standard deviation and hide the very
        outliers we are hunting. This is a WARNING, not a blocker: an extreme
        price is sometimes real (a shortage spike), and silently dropping real
        spikes is how you make a forecasting model useless.
        """
        by_commodity: dict[str, list[tuple[MandiPriceRecord, float]]] = {}
        for record in records:
            if record.modal_price is None:
                continue
            by_commodity.setdefault(record.commodity, []).append((record, float(record.modal_price)))

        for commodity, pairs in by_commodity.items():
            if len(pairs) < 8:  # not enough data for a meaningful distribution
                continue
            values = [v for _, v in pairs]
            median = statistics.median(values)
            deviations = [abs(v - median) for v in values]
            mad = statistics.median(deviations)
            if mad == 0:
                continue
            # 0.6745 makes MAD comparable to a standard deviation for normal data.
            for record, value in pairs:
                robust_z = 0.6745 * (value - median) / mad
                if abs(robust_z) > self.outlier_z:
                    issues.append(QualityIssue.from_record(
                        record, Check.OUTLIER_PRICE, Severity.WARNING,
                        f"{commodity} modal={value} robust_z={robust_z:.1f} vs batch median={median}",
                    ))

    # ---------------------------------------------------------------- #
    # entry point
    # ---------------------------------------------------------------- #
    def evaluate(
        self, records: list[MandiPriceRecord], *, reference_date: date | None = None
    ) -> tuple[list[MandiPriceRecord], list[MandiPriceRecord], QualityReport]:
        """Split into (loadable, quarantined) and build the report."""
        reference_date = reference_date or datetime.now(timezone.utc).date()
        issues: list[QualityIssue] = []
        loadable: list[MandiPriceRecord] = []
        quarantined: list[MandiPriceRecord] = []
        seen: set[str] = set()

        for record in records:
            key = record.natural_key
            if key in seen:
                issues.append(QualityIssue.from_record(
                    record, Check.DUPLICATE_NATURAL_KEY, Severity.WARNING,
                    "duplicate of an earlier record in this batch - keeping the first",
                ))
                continue
            seen.add(key)

            if self._check_record(record, reference_date, issues):
                loadable.append(record)
            else:
                quarantined.append(record)

        self._flag_outliers(loadable, issues)

        report = QualityReport(
            total_records=len(records),
            passed=len(loadable),
            quarantined=len(quarantined),
            issues=issues,
        )
        return loadable, quarantined, report
