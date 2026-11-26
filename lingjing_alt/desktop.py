from __future__ import annotations

import os
import queue
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .auditor import AuditConfig, audit_path, write_reports
from .models import AuditError, AuditResult


@dataclass(frozen=True)
class AuditJob:
    input_path: Path
    output_dir: Path
    config: AuditConfig
    strict: bool = False


class DesktopApp:
    """Small Tk desktop shell around the local audit engine."""

    def __init__(self, tk: Any, ttk: Any, filedialog: Any, messagebox: Any) -> None:
        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.root = tk.Tk()
        self.root.title("思诺棱镜-数据诚信检测系统 | Xino Prism")
        self.root.geometry("980x700")
        self.root.minsize(820, 580)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.max_rows_var = tk.StringVar(value="100000")
        self.max_columns_var = tk.StringVar(value="512")
        self.benford_var = tk.BooleanVar(value=False)
        self.strict_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="准备就绪：选择一个 CSV、TSV、XLSX 或 XLSM 文件。")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.report_paths: dict[str, Path] = {}
        self.result: AuditResult | None = None
        self.messages: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.running = False
        self.controls: list[Any] = []
        self._build()

    def _build(self) -> None:
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        header = self.ttk.Frame(root, padding=(24, 22, 24, 12))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.ttk.Label(
            header,
            text="思诺棱镜-数据诚信检测系统",
            font=("Segoe UI", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.ttk.Label(
            header,
            text="Xino Prism · 本地优先 · 只读审计 · 默认不联网",
        ).grid(row=1, column=0, pady=(5, 0), sticky="w")

        files = self.ttk.LabelFrame(root, text="输入与报告位置", padding=14)
        files.grid(row=1, column=0, padx=24, pady=(0, 12), sticky="ew")
        files.columnconfigure(1, weight=1)
        self.ttk.Label(files, text="输入文件").grid(row=0, column=0, padx=(0, 10), pady=5, sticky="w")
        input_entry = self.ttk.Entry(files, textvariable=self.input_var)
        input_entry.grid(row=0, column=1, pady=5, sticky="ew")
        input_button = self.ttk.Button(files, text="选择文件…", command=self._choose_input)
        input_button.grid(row=0, column=2, padx=(10, 0), pady=5)
        self.ttk.Label(files, text="报告目录").grid(row=1, column=0, padx=(0, 10), pady=5, sticky="w")
        output_entry = self.ttk.Entry(files, textvariable=self.output_var)
        output_entry.grid(row=1, column=1, pady=5, sticky="ew")
        output_button = self.ttk.Button(files, text="选择目录…", command=self._choose_output)
        output_button.grid(row=1, column=2, padx=(10, 0), pady=5)
        self.controls.extend([input_entry, input_button, output_entry, output_button])

        options = self.ttk.LabelFrame(root, text="审计选项", padding=14)
        options.grid(row=2, column=0, padx=24, pady=(0, 12), sticky="ew")
        options.columnconfigure(5, weight=1)
        self.ttk.Label(options, text="最大数据行").grid(row=0, column=0, padx=(0, 8), sticky="w")
        rows_entry = self.ttk.Entry(options, width=11, textvariable=self.max_rows_var)
        rows_entry.grid(row=0, column=1, padx=(0, 18), sticky="w")
        self.ttk.Label(options, text="最大列数").grid(row=0, column=2, padx=(0, 8), sticky="w")
        columns_entry = self.ttk.Entry(options, width=8, textvariable=self.max_columns_var)
        columns_entry.grid(row=0, column=3, padx=(0, 18), sticky="w")
        benford_check = self.ttk.Checkbutton(options, text="启用 Benford 筛查", variable=self.benford_var)
        benford_check.grid(row=0, column=4, padx=(0, 18), sticky="w")
        strict_check = self.ttk.Checkbutton(options, text="覆盖不完整时提示严格状态", variable=self.strict_var)
        strict_check.grid(row=0, column=5, sticky="w")
        self.controls.extend([rows_entry, columns_entry, benford_check, strict_check])

        main = self.ttk.Frame(root, padding=(24, 0, 24, 24))
        main.grid(row=3, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        actions = self.ttk.Frame(main)
        actions.grid(row=0, column=0, pady=(0, 10), sticky="ew")
        self.run_button = self.ttk.Button(actions, text="开始审计", command=self._start)
        self.run_button.pack(side="left")
        self.progress = self.ttk.Progressbar(actions, variable=self.progress_var, mode="indeterminate", length=220)
        self.progress.pack(side="left", padx=(14, 0))
        self.ttk.Label(actions, textvariable=self.status_var).pack(side="left", padx=(14, 0), fill="x", expand=True)

        report_frame = self.ttk.LabelFrame(main, text="审计摘要", padding=10)
        report_frame.grid(row=1, column=0, sticky="nsew")
        report_frame.columnconfigure(0, weight=1)
        report_frame.rowconfigure(0, weight=1)
        self.summary = tk.Text(report_frame, height=18, wrap="word", state="disabled", background="#ffffff")
        self.summary.grid(row=0, column=0, sticky="nsew")
        scrollbar = self.ttk.Scrollbar(report_frame, orient="vertical", command=self.summary.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.summary.configure(yscrollcommand=scrollbar.set)

        report_actions = self.ttk.Frame(report_frame)
        report_actions.grid(row=1, column=0, columnspan=2, pady=(10, 0), sticky="w")
        self.open_html_button = self.ttk.Button(report_actions, text="打开 HTML 报告", command=lambda: self._open_report("html"), state="disabled")
        self.open_html_button.pack(side="left")
        self.open_json_button = self.ttk.Button(report_actions, text="打开 JSON 文件夹", command=lambda: self._open_report("json"), state="disabled")
        self.open_json_button.pack(side="left", padx=(8, 0))

    def _choose_input(self) -> None:
        path = self.filedialog.askopenfilename(
            title="选择待审计文件",
            filetypes=[
                ("支持的表格", "*.csv *.tsv *.xlsx *.xlsm"),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        selected = Path(path)
        self.input_var.set(str(selected))
        if not self.output_var.get().strip():
            self.output_var.set(str(selected.parent / "xino-prism-reports"))

    def _choose_output(self) -> None:
        path = self.filedialog.askdirectory(title="选择报告目录")
        if path:
            self.output_var.set(path)

    def _start(self) -> None:
        if self.running:
            return
        input_path = Path(self.input_var.get().strip()).expanduser()
        output_dir = Path(self.output_var.get().strip()).expanduser()
        if not input_path.is_file():
            self.messagebox.showerror("无法开始审计", "请选择一个存在的输入文件。")
            return
        try:
            max_rows = int(self.max_rows_var.get())
            max_columns = int(self.max_columns_var.get())
            if max_rows <= 0 or max_columns <= 0:
                raise ValueError
        except ValueError:
            self.messagebox.showerror("参数错误", "最大数据行和最大列数必须是正整数。")
            return

        if not self.output_var.get().strip():
            self.messagebox.showerror("无法开始审计", "请选择报告输出目录。")
            return
        job = AuditJob(
            input_path=input_path,
            output_dir=output_dir,
            config=AuditConfig(
                max_rows=max_rows,
                max_columns=max_columns,
                enable_benford=self.benford_var.get(),
            ),
            strict=self.strict_var.get(),
        )
        self.running = True
        self.result = None
        self.report_paths = {}
        self._set_running(True)
        self._set_summary("正在读取输入文件并运行本地检测器…\n\n原始文件不会被覆盖，也不会上传。")
        self.status_var.set("审计进行中…")
        self.progress.start(12)
        threading.Thread(target=self._run_job, args=(job,), daemon=True).start()
        self.root.after(100, self._poll)

    def _run_job(self, job: AuditJob) -> None:
        try:
            result = audit_path(job.input_path, job.config)
            paths = write_reports(result, job.output_dir)
            self.messages.put(("done", (result, paths, job.strict)))
        except (AuditError, OSError, ValueError) as exc:
            self.messages.put(("error", str(exc)))
        except Exception as exc:  # unexpected worker boundary; surface the type and message
            self.messages.put(("internal", f"{type(exc).__name__}: {exc}"))

    def _poll(self) -> None:
        try:
            kind, payload = self.messages.get_nowait()
        except queue.Empty:
            if self.running:
                self.root.after(100, self._poll)
            return
        if kind == "done":
            result, paths, strict = payload
            self._finish(result, paths, strict)
        else:
            self._fail(kind, str(payload))

    def _finish(self, result: AuditResult, paths: dict[str, Path], strict: bool) -> None:
        self.running = False
        self.result = result
        self.report_paths = paths
        self.progress.stop()
        self.progress_var.set(0)
        self._set_running(False)
        completed = sum(entry.status == "completed" for entry in result.coverage)
        limited = sum(entry.status in {"partial", "skipped", "disabled"} for entry in result.coverage)
        incomplete = any(entry.status in {"partial", "skipped"} for entry in result.coverage)
        lines = [
            f"文件：{result.file_name}",
            f"SHA-256：{result.file_hash}",
            f"候选发现：{result.finding_count}",
            f"已运行检测：{completed}    覆盖限制/禁用：{limited}",
            f"报告目录：{paths['html'].parent}",
            "",
        ]
        if result.warnings:
            lines.append("警告：")
            lines.extend(f"- {warning}" for warning in result.warnings)
            lines.append("")
        if result.findings:
            lines.append("优先复核：")
            for finding in result.findings[:20]:
                lines.append(f"[{finding.severity.upper()}] {finding.detector_id} · {finding.sheet_name} · {finding.phenomenon}")
        else:
            lines.append("在已运行的检测中没有发现候选问题；请先查看 coverage 和警告。")
        self._set_summary("\n".join(lines))
        self.open_html_button.configure(state="normal")
        self.open_json_button.configure(state="normal")
        if strict and incomplete:
            self.status_var.set("审计完成，但覆盖不完整；严格模式提示人工复核。")
        else:
            self.status_var.set("审计完成。结果仅用于风险筛查，不是造假裁决。")

    def _fail(self, kind: str, message: str) -> None:
        self.running = False
        self.progress.stop()
        self.progress_var.set(0)
        self._set_running(False)
        self.status_var.set("审计失败。")
        title = "内部错误" if kind == "internal" else "无法完成审计"
        self.messagebox.showerror(title, message)
        self._set_summary(f"审计失败：\n{message}")

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.run_button.configure(state=state)
        for control in self.controls:
            control.configure(state=state)

    def _set_summary(self, text: str) -> None:
        self.summary.configure(state="normal")
        self.summary.delete("1.0", "end")
        self.summary.insert("1.0", text)
        self.summary.configure(state="disabled")

    def _open_report(self, kind: str) -> None:
        path = self.report_paths.get(kind)
        if path is None:
            return
        if kind == "html":
            webbrowser.open(path.resolve().as_uri())
            return
        if os.name == "nt":
            os.startfile(path.parent)  # type: ignore[attr-defined]
        else:
            webbrowser.open(path.parent.resolve().as_uri())

    def _close(self) -> None:
        if self.running and not self.messagebox.askyesno("正在审计", "审计仍在运行，确定退出吗？"):
            return
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError as exc:
        raise SystemExit("当前 Python 未安装 Tk 图形库；请使用 Windows 官方 Python 安装包后重试。") from exc
    DesktopApp(tk, ttk, filedialog, messagebox).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
