from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from itertools import combinations
from statistics import mean, median, pstdev
from typing import Any

from .models import Finding, Table
from .utils import (
    as_float,
    cell_address,
    cell_range,
    chi_square_sf_df8,
    column_letter,
    decimal_tail,
    is_number,
    shannon_entropy,
    stable_value,
    terminal_digit,
)

_ERROR_TOKENS = ("#REF!", "#DIV/0!", "#VALUE!", "#N/A", "#NAME?", "#NUM!", "#NULL!")
_CELL_REF_RE = re.compile(r"(?:(?:'([^']+)'|([A-Za-z_][\w ]*))!)?\$?([A-Z]{1,3})\$?(\d+)")
_FUNC_RE = re.compile(r"\b(?:OFFSET|INDIRECT|RAND|RANDBETWEEN|NOW|TODAY|INFO|CELL)\s*\(", re.I)
_NUMERIC_LITERAL_RE = re.compile(r"(?<![A-Z_])(?:\d+(?:\.\d+)?|\.\d+)(?![A-Z_])")


def _finding(
    detector_id: str,
    severity: str,
    strength: str,
    risk: str,
    confidence: float,
    score: float,
    table: Table,
    ranges: list[str],
    columns: list[str],
    phenomenon: str,
    basis: str,
    assumptions: list[str],
    causes: list[str],
    review: str,
    evidence: dict[str, Any],
) -> Finding:
    return Finding(
        detector_id=detector_id,
        severity=severity,
        evidence_strength=strength,
        false_positive_risk=risk,
        confidence=confidence,
        review_priority_score=score,
        sheet_name=table.name,
        ranges=ranges,
        column_names=columns,
        phenomenon=phenomenon,
        statistical_basis=basis,
        assumptions=assumptions,
        plausible_benign_causes=causes,
        recommended_review=review,
        raw_evidence=evidence,
    )


def _numeric_columns(table: Table, min_values: int = 5) -> dict[int, list[tuple[int, float]]]:
    result: dict[int, list[tuple[int, float]]] = {}
    for index, _header in enumerate(table.headers):
        values: list[tuple[int, float]] = []
        for row_index, row in enumerate(table.rows):
            if index >= len(row):
                continue
            number = as_float(row[index])
            if number is not None:
                values.append((table.row_numbers[row_index], number))
        if len(values) >= min_values:
            result[index] = values
    return result


def detect_duplicate_rows(table: Table) -> list[Finding]:
    groups: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for row_number, row in zip(table.row_numbers, table.rows):
        if not any(value not in (None, "") for value in row):
            continue
        groups[tuple(stable_value(value) for value in row)].append(row_number)
    findings: list[Finding] = []
    for values, rows in groups.items():
        if len(rows) < 2:
            continue
        ranges = [cell_range(row, 1, len(table.headers)) for row in rows]
        findings.append(_finding(
            "duplicate_row",
            "medium" if len(rows) < 4 else "high",
            "strong",
            "medium",
            0.96,
            min(90.0, 45.0 + len(rows) * 8),
            table,
            ranges,
            table.headers,
            f"Identical non-empty row repeated {len(rows)} times",
            "Exact equality after stable scalar normalization; this is a deterministic structural signal, not proof of fabrication.",
            ["Rows are compared across all imported columns.", "Blank-only rows are ignored."],
            ["Legitimate replicates, repeated controls, duplicated exports, or intentional reference rows."],
            "Inspect the repeated rows against the study design and source provenance; confirm whether they are independent observations.",
            {"rows": rows, "values": values, "repeat_count": len(rows)},
        ))
    return findings


def detect_duplicate_blocks(table: Table) -> list[Finding]:
    if len(table.rows) < 6 or not table.headers:
        return []
    fingerprints = [tuple(stable_value(value) for value in row) for row in table.rows]
    findings: list[Finding] = []
    for block_size in range(2, min(10, len(fingerprints) // 2 + 1)):
        seen: dict[tuple[tuple[str, ...], ...], int] = {}
        for start in range(0, len(fingerprints) - block_size + 1):
            block = tuple(fingerprints[start:start + block_size])
            if block in seen and start - seen[block] >= block_size:
                first_row = table.row_numbers[seen[block]]
                second_row = table.row_numbers[start]
                findings.append(_finding(
                    "duplicate_block",
                    "medium",
                    "strong",
                    "medium",
                    0.92,
                    62.0,
                    table,
                    [f"{cell_range(first_row, 1, len(table.headers))} ({block_size} rows)", f"{cell_range(second_row, 1, len(table.headers))} ({block_size} rows)"],
                    table.headers,
                    f"Repeated contiguous block of {block_size} rows",
                    "Exact contiguous row-block equality after scalar normalization.",
                    ["The same columns and row order are meaningful."],
                    ["Repeated measurement panels, controls, or intentionally duplicated sections."],
                    "Check whether the second block is a legitimate replicate or an accidental copy/paste.",
                    {"block_size": block_size, "first_start_row": first_row, "second_start_row": second_row},
                ))
                break
            seen[block] = start
        if findings:
            break
    return findings


def detect_numeric_relations(table: Table) -> list[Finding]:
    numeric = _numeric_columns(table, min_values=8)
    if len(numeric) < 2:
        return []
    findings: list[Finding] = []
    for left_index, right_index in combinations(sorted(numeric), 2):
        left = {row: value for row, value in numeric[left_index]}
        right = {row: value for row, value in numeric[right_index]}
        pairs = [(row, left[row], right[row]) for row in sorted(left.keys() & right.keys())]
        if len(pairs) < 8:
            continue
        candidates = [("sum", lambda a, b: a + b), ("difference", lambda a, b: a - b), ("ratio", lambda a, b: a / b if b else math.nan)]
        best_name = ""
        best_residual = math.inf
        best_values: list[tuple[int, float, float]] = []
        for name, operation in candidates:
            values = [(row, operation(a, b), b) for row, a, b in pairs]
            finite = [value for value in values if math.isfinite(value[1])]
            if len(finite) < 8:
                continue
            center = median(value[1] for value in finite)
            residual = median(abs(value[1] - center) for value in finite)
            scale = max(abs(center), 1.0)
            normalized = residual / scale
            if normalized < best_residual:
                best_name, best_residual, best_values = name, normalized, finite
        if not best_name or best_residual > 0.0005:
            continue
        deviations = [abs(value - median(item[1] for item in best_values)) for _, value, _ in best_values]
        center = median(item[1] for item in best_values)
        outlier_rows = [row for (row, value, _), deviation in zip(best_values, deviations) if deviation > max(abs(center) * 0.1, 1e-9)]
        if not outlier_rows:
            continue
        left_name = table.headers[left_index]
        right_name = table.headers[right_index]
        ranges = [cell_range(row, left_index + 1, right_index + 1) for row in outlier_rows[:25]]
        findings.append(_finding(
            "derived_relation_break",
            "medium",
            "moderate",
            "medium",
            0.84,
            58.0,
            table,
            ranges,
            [left_name, right_name],
            f"Columns show a stable {best_name} relation with {len(outlier_rows)} deviation row(s)",
            f"Across {len(best_values)} paired rows, the median residual for {best_name} is {best_residual:.4g}; flagged rows deviate by more than 10% of the relation center.",
            ["Rows are aligned by position and the relation is expected to be approximately constant."],
            ["Legitimate subgroup effects, rounding, missing covariates, or a relation that is only coincidental."],
            "Review the flagged rows with source calculations and subgroup labels; verify whether the relation is part of the measurement model.",
            {"operation": best_name, "paired_rows": len(best_values), "median_relation": center, "normalized_median_residual": best_residual, "outlier_rows": outlier_rows[:25]},
        ))
    return findings


def detect_sequence_anomalies(table: Table) -> list[Finding]:
    findings: list[Finding] = []
    numeric = _numeric_columns(table, min_values=8)
    for index, values in numeric.items():
        ordered = sorted(values)
        differences = [b - a for (_, a), (_, b) in zip(ordered, ordered[1:])]
        if len(differences) < 7:
            continue
        rounded = [round(value, 10) for value in differences]
        counts = Counter(rounded)
        common_difference, frequency = counts.most_common(1)[0]
        if frequency / len(rounded) < 0.8 or abs(common_difference) < 1e-12:
            continue
        mismatches = [ordered[i + 1][0] for i, difference in enumerate(rounded) if difference != common_difference]
        if not mismatches:
            continue
        findings.append(_finding(
            "sequence_deviation",
            "low",
            "moderate",
            "high",
            0.73,
            40.0,
            table,
            [cell_address(row, index + 1) for row in mismatches[:25]],
            [table.headers[index]],
            f"Mostly regular numeric sequence has {len(mismatches)} deviation(s)",
            f"{frequency}/{len(rounded)} adjacent differences equal {common_difference:g}; deviations are reported as review candidates.",
            ["Rows are in meaningful sequence order and values should progress regularly."],
            ["Sorting artifacts, missing records, resets at subgroup boundaries, or legitimate irregular sampling."],
            "Check row ordering and subgroup boundaries before treating the deviations as suspicious.",
            {"common_difference": common_difference, "common_frequency": frequency, "deviation_rows": mismatches[:25]},
        ))
    return findings


def detect_digit_patterns(table: Table, *, enable_benford: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    numeric = _numeric_columns(table, min_values=20)
    for index, values in numeric.items():
        tails = [decimal_tail(number) for _, number in values]
        tails = [tail for tail in tails if tail is not None]
        if len(tails) >= 20:
            counts = Counter(tails)
            entropy = shannon_entropy(counts.values())
            if len(counts) <= 2 or entropy < 1.0:
                findings.append(_finding(
                    "decimal_tail_pattern",
                    "medium",
                    "moderate",
                    "high",
                    0.79,
                    55.0,
                    table,
                    [cell_range(values[0][0], index + 1, index + 1), cell_range(values[-1][0], index + 1, index + 1)],
                    [table.headers[index]],
                    f"Decimal tails have unusually low diversity (entropy {entropy:.2f})",
                    "Shannon entropy over non-zero decimal tails; low entropy is a screening signal and depends strongly on rounding conventions.",
                    ["Values are measured quantities rather than prices, scores, or deliberately rounded outputs."],
                    ["Instrument resolution, reporting rules, fixed decimal formatting, or a legitimate discrete scale."],
                    "Compare with the instrument precision and the original unrounded measurements; rerun after stratifying by variable and batch.",
                    {"sample_size": len(tails), "distinct_tails": len(counts), "entropy": entropy, "counts": dict(counts)},
                ))
        terminal = [terminal_digit(number) for _, number in values]
        terminal = [digit for digit in terminal if digit is not None]
        if len(terminal) >= 20:
            counts = Counter(terminal)
            dominant_digit, dominant_count = counts.most_common(1)[0]
            if dominant_count / len(terminal) >= 0.65:
                findings.append(_finding(
                    "terminal_digit_concentration",
                    "low",
                    "moderate",
                    "high",
                    0.71,
                    42.0,
                    table,
                    [cell_range(values[0][0], index + 1, index + 1), cell_range(values[-1][0], index + 1, index + 1)],
                    [table.headers[index]],
                    f"Terminal digit {dominant_digit} occurs in {dominant_count}/{len(terminal)} values",
                    "Observed terminal digit concentration exceeds the broad 65% screening threshold; this is not a formal fraud test.",
                    ["Values have a known quantization or rounding step."],
                    ["Measurement resolution, manually entered scores, or prices ending in a fixed digit."],
                    "Inspect the data-generation and rounding process; compare against raw instrument output.",
                    {"sample_size": len(terminal), "counts": dict(counts), "dominant_digit": dominant_digit, "dominant_fraction": dominant_count / len(terminal)},
                ))
        if enable_benford and len(values) >= 50:
            leading = [str(abs(int(number))).lstrip("0")[:1] for _, number in values if number != 0]
            leading = [digit for digit in leading if digit in "123456789"]
            if len(leading) < 50:
                continue
            counts = Counter(leading)
            expected = {str(digit): math.log10(1 + 1 / digit) for digit in range(1, 10)}
            statistic = sum((counts.get(digit, 0) - len(leading) * expected[digit]) ** 2 / (len(leading) * expected[digit]) for digit in expected)
            p_value = chi_square_sf_df8(statistic)
            if p_value < 0.01:
                findings.append(_finding(
                    "benford_screen",
                    "low",
                    "weak",
                    "high",
                    0.62,
                    35.0,
                    table,
                    [cell_range(values[0][0], index + 1, index + 1), cell_range(values[-1][0], index + 1, index + 1)],
                    [table.headers[index]],
                    f"Leading digits depart from Benford expectation (p={p_value:.3g})",
                    "Pearson chi-square goodness-of-fit against Benford's first-digit distribution; use only for suitable naturally scaled quantities.",
                    ["The column contains positive, naturally scaled measurements spanning multiple magnitudes.", "Rows are independent enough for a screening comparison."],
                    ["Bounded scores, prices, assigned IDs, small samples, truncation, or selection effects."],
                    "Do not infer misconduct. First document why Benford is appropriate, then inspect the exact digit counts and sampling frame.",
                    {"sample_size": len(leading), "counts": dict(counts), "expected_proportions": expected, "chi_square": statistic, "p_value": p_value},
                ))
    return findings


def _normalize_formula(formula: str) -> str:
    normalized = formula.upper().replace("$", "")
    return re.sub(r"\d+", "#", normalized)


def _formula_refs(formula: str) -> list[tuple[str | None, str, int]]:
    refs: list[tuple[str | None, str, int]] = []
    for match in _CELL_REF_RE.finditer(formula):
        sheet = match.group(1) or match.group(2)
        refs.append((sheet, match.group(3), int(match.group(4))))
    return refs


def detect_formula_structure(table: Table) -> list[Finding]:
    if not table.formulas:
        return []
    findings: list[Finding] = []
    error_cells = [address for address, formula in table.formulas.items() if any(token in formula.upper() for token in _ERROR_TOKENS)]
    if error_cells:
        findings.append(_finding(
            "formula_error_token",
            "high",
            "strong",
            "low",
            0.99,
            88.0,
            table,
            error_cells[:100],
            table.headers,
            f"Formula text contains error token(s) in {len(error_cells)} cell(s)",
            "The formula string contains a literal Excel error token such as #REF! or #DIV/0!.",
            ["Formula text is available and was read without recalculation."],
            ["Intentionally documented error formulas or cached workbook state not represented in formula text."],
            "Open the cited cells in a trusted spreadsheet engine and trace precedents/dependents before editing the source.",
            {"cells": error_cells[:100], "tokens": _ERROR_TOKENS},
        ))
    formula_groups: dict[str, list[str]] = defaultdict(list)
    for address, formula in table.formulas.items():
        formula_groups[_normalize_formula(formula)].append(address)
    for normalized, addresses in formula_groups.items():
        if len(addresses) < 3:
            continue
        rows = sorted(int(re.search(r"\d+", address).group()) for address in addresses)
        if max(rows) - min(rows) + 1 != len(rows):
            continue
        formulas = [table.formulas[address] for address in addresses]
        if len(set(formulas)) == 1:
            continue
        findings.append(_finding(
            "formula_drift",
            "medium",
            "strong",
            "medium",
            0.9,
            65.0,
            table,
            addresses,
            table.headers,
            f"Formula pattern changes within a contiguous copied block ({len(addresses)} cells)",
            "Formulas share the same normalized shape but contain a non-uniform relative reference pattern.",
            ["Cells are intended to be a copied formula block."],
            ["Subtotal boundaries, intentional exceptions, inserted rows, or mixed formula regimes."],
            "Compare each formula with neighboring rows and inspect whether the reference shift matches the intended model.",
            {"normalized_formula": normalized, "cells": addresses, "formulas": formulas},
        ))
    for address, formula in table.formulas.items():
        if _FUNC_RE.search(formula):
            findings.append(_finding(
                "volatile_formula",
                "low",
                "moderate",
                "medium",
                0.86,
                38.0,
                table,
                [address],
                table.headers,
                "Formula uses a volatile or indirect function",
                "Functions such as INDIRECT, OFFSET, RAND, NOW, and TODAY can make recalculation and audit reproduction context-dependent.",
                ["The formula is intentionally dynamic."],
                ["Legacy workbook patterns or convenience formulas."],
                "Document the dependency and recalculate in a controlled environment before comparing outputs.",
                {"cell": address, "formula": formula},
            ))
        numeric_literals = [literal for literal in _NUMERIC_LITERAL_RE.findall(formula) if literal not in {"0", "1"}]
        if numeric_literals:
            findings.append(_finding(
                "formula_hardcoded_constant",
                "low",
                "moderate",
                "medium",
                0.78,
                35.0,
                table,
                [address],
                table.headers,
                "Formula contains embedded numeric constant(s)",
                "Numeric literals inside formulas may be hidden assumptions; the detector does not decide whether they are wrong.",
                ["Constant is an intentional threshold, rate, or domain parameter."],
                ["A manually patched value, stale assumption, or missing input reference."],
                "Check whether each literal is documented and should instead be an explicit input cell.",
                {"cell": address, "formula": formula, "numeric_literals": numeric_literals},
            ))
    if table.hidden_rows or table.hidden_columns or table.sheet_state != "visible":
        findings.append(_finding(
            "hidden_structure",
            "low",
            "moderate",
            "medium",
            0.93,
            45.0,
            table,
            table.hidden_rows[:100] + table.hidden_columns[:100],
            table.headers,
            "Workbook contains hidden rows, columns, or sheets",
            "Hidden workbook structure can conceal inputs, intermediate calculations, or exclusions from manual review.",
            ["Hidden structure is intentionally used for presentation or helper calculations."],
            ["Legacy artifacts, accidental hiding, or omitted audit context."],
            "Unhide and document the affected rows, columns, or sheet state; trace whether they influence reported results.",
            {"hidden_rows": table.hidden_rows[:100], "hidden_columns": table.hidden_columns[:100], "sheet_state": table.sheet_state},
        ))
    if table.merged_ranges:
        findings.append(_finding(
            "merged_cells_in_table",
            "info",
            "moderate",
            "high",
            0.8,
            22.0,
            table,
            table.merged_ranges[:100],
            table.headers,
            "Merged cells may reduce machine-readable table coverage",
            "Merged cells can obscure row/column boundaries and complicate downstream formula and data validation.",
            ["Merged cells are presentation-only and outside the data region."],
            ["Report layout, title blocks, or manually formatted tables."],
            "Confirm that merged ranges do not overlap the actual data and calculation region.",
            {"merged_ranges": table.merged_ranges[:100]},
        ))
    return findings


def detect_formula_cycles(table: Table) -> list[Finding]:
    if not table.formulas:
        return []
    graph: dict[str, set[str]] = defaultdict(set)
    for address, formula in table.formulas.items():
        for sheet, column, row in _formula_refs(formula):
            if sheet is not None and sheet.casefold() != table.name.casefold():
                continue
            reference = f"{column}{row}"
            if reference in table.formulas:
                graph[address].add(reference)
    cycles: list[list[str]] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, path: list[str]) -> None:
        if node in visiting:
            start = path.index(node) if node in path else 0
            cycles.append(path[start:])
            return
        if node in visited:
            return
        visiting.add(node)
        for child in graph.get(node, set()):
            visit(child, path + [child])
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node, [node])
    if not cycles:
        return []
    unique = []
    seen: set[tuple[str, ...]] = set()
    for cycle in cycles:
        normalized = tuple(sorted(set(cycle)))
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return [_finding(
        "formula_cycle_risk",
        "high",
        "strong",
        "low",
        0.98,
        92.0,
        table,
        list(cycle),
        table.headers,
        "Formula dependency graph contains a cycle",
        "A directed cycle was found among same-sheet formula references; Excel may report or suppress circular calculation depending on settings.",
        ["Formula references are parseable A1-style same-sheet references."],
        ["Intentional iterative calculation or references hidden inside unsupported formula constructs."],
        "Open the workbook with iterative calculation disabled and inspect the cited dependency cycle.",
        {"cycle": list(cycle)},
    ) for cycle in unique]


def run_detectors(table: Table, *, enable_benford: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(detect_formula_structure(table))
    findings.extend(detect_formula_cycles(table))
    findings.extend(detect_duplicate_rows(table))
    findings.extend(detect_duplicate_blocks(table))
    findings.extend(detect_numeric_relations(table))
    findings.extend(detect_sequence_anomalies(table))
    findings.extend(detect_digit_patterns(table, enable_benford=enable_benford))
    return findings
