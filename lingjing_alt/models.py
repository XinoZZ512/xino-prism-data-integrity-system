from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class Finding:
    detector_id: str
    severity: str
    evidence_strength: str
    false_positive_risk: str
    confidence: float
    review_priority_score: float
    sheet_name: str
    ranges: list[str]
    column_names: list[str]
    phenomenon: str
    statistical_basis: str
    assumptions: list[str]
    plausible_benign_causes: list[str]
    recommended_review: str
    raw_evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = round(max(0.0, min(1.0, float(self.confidence))), 3)
        self.review_priority_score = round(max(0.0, min(100.0, float(self.review_priority_score))), 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector_id": self.detector_id,
            "severity": self.severity,
            "evidence_strength": self.evidence_strength,
            "false_positive_risk": self.false_positive_risk,
            "confidence": self.confidence,
            "review_priority_score": self.review_priority_score,
            "sheet_name": self.sheet_name,
            "ranges": self.ranges,
            "column_names": self.column_names,
            "phenomenon": self.phenomenon,
            "statistical_basis": self.statistical_basis,
            "assumptions": self.assumptions,
            "plausible_benign_causes": self.plausible_benign_causes,
            "recommended_review": self.recommended_review,
            "raw_evidence": self.raw_evidence,
        }


@dataclass
class CoverageEntry:
    detector_id: str
    status: str
    reason: str
    tables: list[str] = field(default_factory=list)
    finding_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector_id": self.detector_id,
            "status": self.status,
            "reason": self.reason,
            "tables": self.tables,
            "finding_count": self.finding_count,
        }


@dataclass
class Table:
    name: str
    source_format: str
    headers: list[str]
    rows: list[list[Any]]
    row_numbers: list[int]
    formulas: dict[str, str] = field(default_factory=dict)
    formula_values: dict[str, Any] = field(default_factory=dict)
    hidden_rows: list[int] = field(default_factory=list)
    hidden_columns: list[str] = field(default_factory=list)
    merged_ranges: list[str] = field(default_factory=list)
    sheet_state: str = "visible"
    macro_present: bool = False
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def column_count(self) -> int:
        return len(self.headers)

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass
class LoadedInput:
    path: Path
    tables: list[Table]
    warnings: list[str] = field(default_factory=list)
    partial: bool = False


@dataclass
class AuditResult:
    schema_version: str
    file_name: str
    file_path: str
    file_hash: str
    created_at: str
    finding_count: int
    findings: list[Finding]
    coverage: list[CoverageEntry]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "file_hash": self.file_hash,
            "created_at": self.created_at,
            "finding_count": self.finding_count,
            "findings": [finding.to_dict() for finding in self.findings],
            "coverage": [entry.to_dict() for entry in self.coverage],
            "warnings": self.warnings,
        }


class AuditError(Exception):
    """Expected, user-actionable audit error."""


class InputError(AuditError):
    """The input is unsupported, malformed, or unsafe."""


class LimitError(AuditError):
    """The input exceeded a configured safety limit."""
