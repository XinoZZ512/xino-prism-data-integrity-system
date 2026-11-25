from __future__ import annotations

import csv
import hashlib
import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .detectors import run_detectors
from .loaders import load_input
from .models import AuditError, AuditResult, CoverageEntry, Finding, InputError, LoadedInput, LimitError, Table, utc_now

DETECTOR_IDS = [
    "formula_error_token",
    "formula_drift",
    "formula_hardcoded_constant",
    "volatile_formula",
    "formula_cycle_risk",
    "hidden_structure",
    "merged_cells_in_table",
    "duplicate_row",
    "duplicate_block",
    "derived_relation_break",
    "sequence_deviation",
    "decimal_tail_pattern",
    "terminal_digit_concentration",
    "benford_screen",
]


@dataclass(frozen=True)
class AuditConfig:
    max_bytes: int = 250 * 1024 * 1024
    max_rows: int = 100_000
    max_columns: int = 512
    enable_benford: bool = False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _coverage(
    tables: list[Table],
    findings: list[Finding],
    loaded: LoadedInput,
    *,
    enable_benford: bool,
) -> list[CoverageEntry]:
    entries: list[CoverageEntry] = []
    formula_detectors = {
        "formula_error_token",
        "formula_drift",
        "formula_hardcoded_constant",
        "volatile_formula",
        "formula_cycle_risk",
    }
    workbook_tables = [table for table in tables if table.source_format in {"xlsx", "xlsm"}]
    for detector_id in DETECTOR_IDS:
        detector_findings = [finding for finding in findings if finding.detector_id == detector_id]
        if detector_id == "benford_screen" and not enable_benford:
            status = "disabled"
            reason = "Benford screening is opt-in; enable --benford only for suitable naturally scaled variables."
        elif loaded.partial:
            status = "partial"
            reason = "Safety limits truncated at least one table; absence of a finding is not a clean result."
        elif not tables:
            status = "skipped"
            reason = "No readable tables were found."
        elif detector_id in formula_detectors:
            status = "completed" if any(table.formulas for table in tables) else "skipped"
            reason = (
                "Workbook formulas were inspected without executing formulas or macros."
                if status == "completed"
                else "Input contains no workbook formulas for this detector."
            )
        elif detector_id in {"hidden_structure", "merged_cells_in_table"}:
            status = "completed" if workbook_tables else "skipped"
            reason = (
                "Workbook structure was inspected without executing formulas or macros."
                if status == "completed"
                else "Delimited input has no workbook structure metadata for this detector."
            )
        else:
            status = "completed"
            reason = "Detector ran on all readable tables within configured limits."
        entries.append(CoverageEntry(detector_id, status, reason, [table.name for table in tables], len(detector_findings)))
    return entries


def audit_path(path: str | Path, config: AuditConfig | None = None) -> AuditResult:
    settings = config or AuditConfig()
    loaded = load_input(path, max_bytes=settings.max_bytes, max_rows=settings.max_rows, max_columns=settings.max_columns)
    findings: list[Finding] = []
    for table in loaded.tables:
        findings.extend(run_detectors(table, enable_benford=settings.enable_benford))
    findings.sort(key=lambda finding: (-finding.review_priority_score, finding.detector_id, finding.sheet_name, finding.ranges[:1]))
    input_path = loaded.path
    return AuditResult(
        schema_version="1.0",
        file_name=input_path.name,
        file_path=str(input_path),
        file_hash=sha256_file(input_path),
        created_at=utc_now(),
        finding_count=len(findings),
        findings=findings,
        coverage=_coverage(loaded.tables, findings, loaded, enable_benford=settings.enable_benford),
        warnings=loaded.warnings,
    )


def write_json(result: AuditResult, destination: Path) -> None:
    destination.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(result: AuditResult, destination: Path) -> None:
    fields = [
        "detector_id", "severity", "evidence_strength", "false_positive_risk", "confidence",
        "review_priority_score", "sheet_name", "ranges", "column_names", "phenomenon",
        "statistical_basis", "assumptions", "plausible_benign_causes", "recommended_review", "raw_evidence",
    ]
    with destination.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for finding in result.findings:
            values = finding.to_dict()
            for key in fields:
                if isinstance(values[key], (list, dict)):
                    values[key] = json.dumps(values[key], ensure_ascii=False)
            writer.writerow({field: values[field] for field in fields})


def _severity_class(severity: str) -> str:
    return {"high": "high", "medium": "medium", "low": "low", "info": "info"}.get(severity, "info")


def write_html(result: AuditResult, destination: Path) -> None:
    findings = []
    for finding in result.findings:
        data = finding.to_dict()
        details = "".join([
            f"<p><strong>现象：</strong>{html.escape(finding.phenomenon)}</p>",
            f"<p><strong>依据：</strong>{html.escape(finding.statistical_basis)}</p>",
            f"<p><strong>建议：</strong>{html.escape(finding.recommended_review)}</p>",
            f"<p><strong>范围：</strong>{html.escape(', '.join(finding.ranges))}</p>",
            f"<p><strong>证据：</strong><code>{html.escape(json.dumps(finding.raw_evidence, ensure_ascii=False))}</code></p>",
            f"<p><strong>可能的良性原因：</strong>{html.escape('；'.join(finding.plausible_benign_causes))}</p>",
        ])
        findings.append(f"<details class='finding {_severity_class(finding.severity)}'><summary><span class='badge'>{html.escape(finding.severity.upper())}</span> {html.escape(finding.detector_id)} · {html.escape(finding.sheet_name)} · {html.escape(finding.phenomenon)}</summary>{details}</details>")
    coverage_rows = "".join(
        f"<tr><td>{html.escape(entry.detector_id)}</td><td>{html.escape(entry.status)}</td><td>{html.escape(entry.reason)}</td><td>{entry.finding_count}</td></tr>"
        for entry in result.coverage
    )
    warning_html = "".join(f"<li>{html.escape(warning)}</li>" for warning in result.warnings) or "<li>无</li>"
    content = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LingJing Alt 审计报告 - {html.escape(result.file_name)}</title>
<style>
:root {{ color-scheme: light; font-family: system-ui,-apple-system,Segoe UI,sans-serif; background:#f6f8fa; color:#24292f; }}
body {{ margin:0; }} main {{ max-width:1120px; margin:auto; padding:32px 20px 64px; }}
header, section {{ background:white; border:1px solid #d0d7de; border-radius:8px; padding:20px; margin-bottom:16px; }}
h1 {{ margin:0 0 8px; font-size:26px; }} h2 {{ font-size:18px; margin:0 0 12px; }}
.meta {{ color:#57606a; font-size:13px; overflow-wrap:anywhere; }}
.summary {{ display:flex; flex-wrap:wrap; gap:12px; margin-top:18px; }} .metric {{ background:#f6f8fa; border-radius:6px; padding:12px 16px; min-width:120px; }}
.metric strong {{ display:block; font-size:24px; }} table {{ border-collapse:collapse; width:100%; font-size:13px; }} th,td {{ text-align:left; padding:8px; border-bottom:1px solid #d8dee4; vertical-align:top; }}
.finding {{ border:1px solid #d0d7de; border-left:4px solid #8c959f; border-radius:6px; margin:8px 0; padding:10px 12px; }}
.finding.high {{ border-left-color:#cf222e; }} .finding.medium {{ border-left-color:#bf8700; }} .finding.low {{ border-left-color:#0969da; }}
summary {{ cursor:pointer; font-weight:600; }} .badge {{ display:inline-block; min-width:55px; text-align:center; border-radius:12px; padding:2px 7px; font-size:11px; color:white; background:#57606a; }}
.high .badge {{ background:#cf222e; }} .medium .badge {{ background:#bf8700; }} .low .badge {{ background:#0969da; }} code {{ white-space:pre-wrap; overflow-wrap:anywhere; }}
.note {{ color:#57606a; font-size:13px; }}
</style></head><body><main>
<header><h1>LingJing Alt 本地数据完整性审计</h1>
<div class='meta'>文件：{html.escape(result.file_name)}<br>SHA-256：{html.escape(result.file_hash)}<br>生成时间：{html.escape(result.created_at)}</div>
<div class='summary'><div class='metric'><strong>{result.finding_count}</strong>发现</div><div class='metric'><strong>{sum(entry.status == 'completed' for entry in result.coverage)}</strong>已运行检测</div><div class='metric'><strong>{sum(entry.status in {'partial','skipped'} for entry in result.coverage)}</strong>覆盖限制</div></div></header>
<section><h2>解释边界</h2><p class='note'>本报告是本地、只读的风险筛查，不证明造假、错误意图或 misconduct。请结合原始记录、实验设计和人工复核解释每条 finding。宏未执行，公式未重新计算，缺少覆盖的结果不能视为“通过”。</p></section>
<section><h2>发现</h2>{''.join(findings) if findings else '<p>在已运行的检测中没有发现候选问题。请先阅读覆盖表和警告，再决定是否需要进一步验证。</p>'}</section>
<section><h2>覆盖范围</h2><table><thead><tr><th>检测器</th><th>状态</th><th>说明</th><th>发现数</th></tr></thead><tbody>{coverage_rows}</tbody></table></section>
<section><h2>警告</h2><ul>{warning_html}</ul></section>
<footer class='note'>LingJing Alt 0.1.0 · 输入文件不会被覆盖 · 默认不发起网络请求</footer>
</main></body></html>"""
    destination.write_text(content, encoding="utf-8")


def write_reports(result: AuditResult, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(result.file_name).stem
    destinations = {
        "json": out_dir / f"{stem}.audit.json",
        "csv": out_dir / f"{stem}.findings.csv",
        "html": out_dir / f"{stem}.report.html",
    }
    write_json(result, destinations["json"])
    write_csv(result, destinations["csv"])
    write_html(result, destinations["html"])
    return destinations
