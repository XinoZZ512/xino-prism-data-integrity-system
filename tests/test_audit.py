from __future__ import annotations

import csv
import json
from pathlib import Path

import openpyxl

from lingjing_alt.auditor import AuditConfig, audit_path, write_reports
from lingjing_alt.cli import main


def write_csv_fixture(path: Path) -> None:
    rows = [
        ["id", "value", "total"],
        ["a", 10.10, 20.10],
        ["b", 11.10, 21.10],
        ["c", 12.10, 22.10],
        ["d", 13.10, 23.10],
        ["e", 14.10, 24.10],
        ["f", 15.10, 25.10],
        ["g", 16.10, 26.10],
        ["h", 17.10, 27.10],
        ["i", 18.10, 28.10],
        ["j", 19.10, 29.10],
        ["dup", 99.99, 100.99],
        ["dup", 99.99, 100.99],
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)


def write_workbook_fixture(path: Path) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(["value", "formula", "cycle"])
    for row in range(2, 7):
        sheet.cell(row, 1, row * 2)
        sheet.cell(row, 2, f"=A{row}+10" if row != 4 else "=A4+99")
    sheet["C2"] = "=C3+1"
    sheet["C3"] = "=C2+1"
    sheet.row_dimensions[5].hidden = True
    sheet.column_dimensions["C"].hidden = True
    workbook.save(path)


def test_csv_audit_reports_duplicate_row_and_schema(tmp_path: Path) -> None:
    source = tmp_path / "fixture.csv"
    out_dir = tmp_path / "reports"
    write_csv_fixture(source)
    result = audit_path(source)
    detector_ids = {finding.detector_id for finding in result.findings}
    assert "duplicate_row" in detector_ids
    assert result.file_hash and len(result.file_hash) == 64
    destinations = write_reports(result, out_dir)
    payload = json.loads(destinations["json"].read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == "1.0"
    assert payload["finding_count"] == len(payload["findings"])
    assert destinations["html"].read_text(encoding="utf-8").startswith("<!doctype html>")


def test_row_limit_reports_partial_row_coverage_without_column_warning(tmp_path: Path) -> None:
    source = tmp_path / "fixture.csv"
    write_csv_fixture(source)
    result = audit_path(source, AuditConfig(max_rows=2))
    assert result.warnings == ["row limit reached; only the first 2 data rows were audited"]
    assert any(entry.status == "partial" for entry in result.coverage)


def test_csv_formula_coverage_is_skipped_and_benford_can_be_enabled(tmp_path: Path) -> None:
    source = tmp_path / "fixture.csv"
    write_csv_fixture(source)
    result = audit_path(source, AuditConfig(enable_benford=True))
    coverage = {entry.detector_id: entry.status for entry in result.coverage}
    assert coverage["formula_cycle_risk"] == "skipped"
    assert coverage["hidden_structure"] == "skipped"
    assert coverage["benford_screen"] == "completed"


def test_cross_sheet_references_are_not_reported_as_same_sheet_cycles(tmp_path: Path) -> None:
    source = tmp_path / "cross-sheet.xlsx"
    workbook = openpyxl.Workbook()
    data = workbook.active
    data.title = "Data"
    data.append(["value"])
    data["A2"] = "='Other'!A2+1"
    other = workbook.create_sheet("Other")
    other.append(["value"])
    other["A2"] = "=Data!A2+1"
    workbook.save(source)
    result = audit_path(source)
    assert not any(finding.detector_id == "formula_cycle_risk" for finding in result.findings)


def test_workbook_audit_detects_formula_and_structure_risks(tmp_path: Path) -> None:
    source = tmp_path / "fixture.xlsx"
    write_workbook_fixture(source)
    result = audit_path(source)
    detector_ids = {finding.detector_id for finding in result.findings}
    assert "formula_cycle_risk" in detector_ids
    assert "hidden_structure" in detector_ids
    assert any(entry.detector_id == "formula_cycle_risk" and entry.status == "completed" for entry in result.coverage)


def test_cli_exit_code_and_outputs(tmp_path: Path, capsys) -> None:
    source = tmp_path / "fixture.csv"
    out_dir = tmp_path / "reports"
    write_csv_fixture(source)
    exit_code = main(["audit", str(source), "--out-dir", str(out_dir)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert (out_dir / "fixture.audit.json").exists()
    assert "findings" in captured.out


def test_cli_rejects_unsupported_input(tmp_path: Path, capsys) -> None:
    source = tmp_path / "fixture.xls"
    source.write_bytes(b"not an xls")
    out_dir = tmp_path / "reports"
    exit_code = main(["audit", str(source), "--out-dir", str(out_dir)])
    captured = capsys.readouterr()
    assert exit_code == 4
    assert "Unsupported input format" in captured.err
