from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Any

from .models import InputError, LimitError, LoadedInput, Table
from .utils import cell_address, parse_scalar

SUPPORTED = {".csv", ".tsv", ".xlsx", ".xlsm"}


def _validate_file(path: Path, max_bytes: int) -> None:
    if not path.exists() or not path.is_file():
        raise InputError(f"Input file does not exist: {path}")
    if path.suffix.lower() not in SUPPORTED:
        raise InputError(f"Unsupported input format {path.suffix!r}; use CSV, TSV, XLSX, or XLSM")
    size = path.stat().st_size
    if size > max_bytes:
        raise LimitError(f"Input exceeds the {max_bytes:,}-byte safety limit")


def _trim_rows(rows: list[list[Any]], max_rows: int, max_columns: int) -> tuple[list[list[Any]], bool, list[str]]:
    warnings: list[str] = []
    row_truncated = len(rows) > max_rows + 1  # the first row is the table header
    column_truncated = False
    if row_truncated:
        rows = rows[:max_rows + 1]
        warnings.append(f"row limit reached; only the first {max_rows:,} data rows were audited")
    normalized: list[list[Any]] = []
    for row in rows:
        if len(row) > max_columns:
            row = row[:max_columns]
            column_truncated = True
        normalized.append(row)
    if column_truncated:
        warnings.append(f"column limit reached; only the first {max_columns:,} columns were audited")
    return normalized, row_truncated or column_truncated, warnings


def _table_from_matrix(name: str, matrix: list[list[Any]], source_format: str, max_rows: int, max_columns: int) -> Table:
    if not matrix:
        return Table(name=name, source_format=source_format, headers=[], rows=[], row_numbers=[])
    rows, truncated, warnings = _trim_rows(matrix, max_rows, max_columns)
    header_values = rows[0]
    headers: list[str] = []
    used: dict[str, int] = {}
    for index, value in enumerate(header_values, start=1):
        base = str(value).strip() if value not in (None, "") else f"Column {index}"
        used[base] = used.get(base, 0) + 1
        headers.append(base if used[base] == 1 else f"{base} ({used[base]})")
    width = len(headers)
    data = [(row + [None] * width)[:width] for row in rows[1:]]
    return Table(
        name=name,
        source_format=source_format,
        headers=headers,
        rows=data,
        row_numbers=list(range(2, len(data) + 2)),
        truncated=truncated,
        warnings=warnings,
    )


def _load_delimited(path: Path, max_rows: int, max_columns: int) -> LoadedInput:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    raw = path.read_bytes()
    if len(raw) > 50 * 1024 * 1024:
        raise LimitError("Delimited input exceeds the 50 MiB in-memory safety limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    matrix = [[parse_scalar(value) for value in row] for row in reader]
    table = _table_from_matrix(path.stem, matrix, path.suffix.lower().lstrip("."), max_rows, max_columns)
    return LoadedInput(path=path, tables=[table], warnings=table.warnings, partial=table.truncated)


def _formula_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.startswith("=") else None


def _load_workbook(path: Path, max_rows: int, max_columns: int) -> LoadedInput:
    try:
        import openpyxl
    except ImportError as exc:
        raise InputError("XLSX support requires openpyxl; install the project dependencies") from exc
    if path.suffix.lower() == ".xlsm":
        keep_vba = True
    else:
        keep_vba = False
    try:
        workbook = openpyxl.load_workbook(path, read_only=False, data_only=False, keep_vba=keep_vba)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise InputError(f"Unable to read workbook safely: {exc}") from exc
    tables: list[Table] = []
    warnings: list[str] = []
    partial = False
    macro_present = bool(getattr(workbook, "vba_archive", None))
    if macro_present:
        warnings.append("VBA project detected; macros were inventoried but never executed or analyzed")
    for worksheet in workbook.worksheets:
        max_row = min(worksheet.max_row or 0, max_rows + 1)
        max_column = min(worksheet.max_column or 0, max_columns)
        matrix: list[list[Any]] = []
        formulas: dict[str, str] = {}
        formula_values: dict[str, Any] = {}
        for row in worksheet.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_column):
            values: list[Any] = []
            for cell in row:
                value = cell.value
                values.append(value)
                formula = _formula_text(value)
                if formula:
                    formulas[cell.coordinate] = formula
            matrix.append(values)
        table = _table_from_matrix(worksheet.title, matrix, path.suffix.lower().lstrip("."), max_rows, max_columns)
        table.formulas = formulas
        table.formula_values = formula_values
        table.hidden_rows = [index for index, dimension in worksheet.row_dimensions.items() if dimension.hidden]
        table.hidden_columns = [key for key, dimension in worksheet.column_dimensions.items() if dimension.hidden]
        table.merged_ranges = [str(item) for item in worksheet.merged_cells.ranges]
        table.sheet_state = worksheet.sheet_state
        table.macro_present = macro_present
        table.warnings.extend(warnings)
        if worksheet.max_row > max_rows + 1 or worksheet.max_column > max_columns:
            table.truncated = True
            table.warnings.append(f"sheet exceeded configured limit of {max_rows:,} rows or {max_columns:,} columns")
            partial = True
        if table.warnings:
            warnings.extend(warning for warning in table.warnings if warning not in warnings)
        tables.append(table)
    if not tables:
        warnings.append("workbook contains no worksheets")
    return LoadedInput(path=path, tables=tables, warnings=warnings, partial=partial)


def load_input(path: str | Path, *, max_bytes: int = 250 * 1024 * 1024, max_rows: int = 100_000, max_columns: int = 512) -> LoadedInput:
    input_path = Path(path).expanduser().resolve()
    _validate_file(input_path, max_bytes)
    if input_path.suffix.lower() in {".csv", ".tsv"}:
        return _load_delimited(input_path, max_rows, max_columns)
    return _load_workbook(input_path, max_rows, max_columns)
