from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .auditor import AuditConfig, audit_path, write_reports
from .models import AuditError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xino-prism",
        description="Local-first, read-only data integrity and spreadsheet audit toolkit.",
    )
    parser.add_argument("--version", action="version", version=f"xino-prism {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit", help="audit a CSV, TSV, XLSX, or XLSM file")
    audit.add_argument("input", type=Path, help="input file; it is never overwritten")
    audit.add_argument("--out-dir", type=Path, required=True, help="directory for JSON, CSV, and HTML reports")
    audit.add_argument("--strict", action="store_true", help="return exit code 2 when any coverage is partial or skipped")
    audit.add_argument("--benford", action="store_true", help="enable the opt-in Benford first-digit screen")
    audit.add_argument("--max-bytes", type=int, default=250 * 1024 * 1024, help="maximum input size in bytes")
    audit.add_argument("--max-rows", type=int, default=100_000, help="maximum rows per table, excluding the header")
    audit.add_argument("--max-columns", type=int, default=512, help="maximum columns per table")
    return parser


def _validate_limits(args: argparse.Namespace) -> None:
    for name in ("max_bytes", "max_rows", "max_columns"):
        if getattr(args, name) <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be greater than zero")


def run_audit(args: argparse.Namespace) -> int:
    _validate_limits(args)
    result = audit_path(
        args.input,
        AuditConfig(
            max_bytes=args.max_bytes,
            max_rows=args.max_rows,
            max_columns=args.max_columns,
            enable_benford=args.benford,
        ),
    )
    destinations = write_reports(result, args.out_dir)
    summary = {
        "file": result.file_name,
        "findings": result.finding_count,
        "warnings": len(result.warnings),
        "partial_coverage": any(entry.status == "partial" for entry in result.coverage),
        "reports": {key: str(path) for key, path in destinations.items()},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    incomplete = any(entry.status in {"partial", "skipped"} for entry in result.coverage)
    if args.strict and incomplete:
        return 2
    if result.finding_count:
        return 1
    if incomplete:
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            return run_audit(args)
        parser.error("unknown command")
    except (AuditError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"internal error: {exc}", file=sys.stderr)
        return 5
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
