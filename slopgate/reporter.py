"""
Multi-Channel Output Formatter.
Outputs human-friendly ANSI terminal displays, GitHub Step Summaries,
PR review comments, and structured JSON.
"""

import json
from typing import Optional
from slopgate.engine import AuditReport, Severity


class AnsiColor:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"


class Reporter:
    """Formats AuditReport for CLI, GitHub Actions, and JSON pipelines."""

    @classmethod
    def render_terminal(cls, report: AuditReport) -> str:
        lines = []
        # Header Box
        lines.append(f"{AnsiColor.CYAN}======================================================={AnsiColor.RESET}")
        lines.append(f"{AnsiColor.BOLD}{AnsiColor.CYAN} 🛡️  SLOPGATE — Code & PR Integrity Shield {AnsiColor.RESET}")
        lines.append(f"{AnsiColor.CYAN}======================================================={AnsiColor.RESET}")

        # Metrics
        m = report.metrics
        lines.append(f" {AnsiColor.GRAY}Diff:{AnsiColor.RESET} {m.files_changed} files | "
                     f"{AnsiColor.GREEN}+{m.total_added}{AnsiColor.RESET} / "
                     f"{AnsiColor.RED}-{m.total_removed}{AnsiColor.RESET} | "
                     f"Code: +{m.code_added} | Tests: +{m.test_added} | Docs: +{m.doc_added}")

        # Status
        if report.status == Severity.BLOCKED:
            status_badge = f"{AnsiColor.BOLD}{AnsiColor.RED}[BLOCKED]{AnsiColor.RESET}"
        elif report.status == Severity.WARNING:
            status_badge = f"{AnsiColor.BOLD}{AnsiColor.YELLOW}[WARNING]{AnsiColor.RESET}"
        else:
            status_badge = f"{AnsiColor.BOLD}{AnsiColor.GREEN}[PASSED]{AnsiColor.RESET}"

        lines.append(f" Status: {status_badge} {report.summary}")
        lines.append("")

        # Violations Table
        if report.violations:
            lines.append(f"{AnsiColor.BOLD}Violations Detected:{AnsiColor.RESET}")
            for v in report.violations:
                color = AnsiColor.RED if v.severity == Severity.BLOCKED else AnsiColor.YELLOW
                lines.append(f"  • {color}[{v.rule_id}]{AnsiColor.RESET} {AnsiColor.BOLD}{v.title}{AnsiColor.RESET}")
                lines.append(f"    Location: {v.file_path}:{v.line_number}")
                lines.append(f"    Details:  {v.message}")
                if v.snippet:
                    lines.append(f"    Snippet:  {AnsiColor.GRAY}{v.snippet}{AnsiColor.RESET}")
                lines.append("")
        else:
            lines.append(f"  {AnsiColor.GREEN}✨ Zero integrity violations found. Clean PR!{AnsiColor.RESET}\n")

        lines.append(f"{AnsiColor.CYAN}-------------------------------------------------------{AnsiColor.RESET}")
        return "\n".join(lines)

    @classmethod
    def render_github_markdown(cls, report: AuditReport) -> str:
        """Formats markdown for GitHub Step Summary and PR comments."""
        if report.status == Severity.BLOCKED:
            badge = "![SlopGate Status](https://img.shields.io/badge/SlopGate-BLOCKED-red?style=for-the-badge)"
            callout = "> [!CAUTION]\n> **PR Blocked by SlopGate**: Critical code/test integrity violations detected."
        elif report.status == Severity.WARNING:
            badge = "![SlopGate Status](https://img.shields.io/badge/SlopGate-WARNING-yellow?style=for-the-badge)"
            callout = "> [!WARNING]\n> **SlopGate Warning**: Non-critical suggestions detected."
        else:
            badge = "![SlopGate Status](https://img.shields.io/badge/SlopGate-PASSED-brightgreen?style=for-the-badge)"
            callout = "> [!NOTE]\n> **SlopGate Audit Passed**: All test assertions intact and symbols verified."

        lines = [
            f"# {badge}",
            "",
            callout,
            "",
            "### 📊 Diff Metrics",
            f"| Metric | Value |",
            f"| --- | --- |",
            f"| **Files Changed** | `{report.metrics.files_changed}` |",
            f"| **Logic Added** | `+{report.metrics.code_added}` lines |",
            f"| **Tests Added** | `+{report.metrics.test_added}` lines |",
            f"| **Docs / Comments** | `+{report.metrics.doc_added}` lines |",
            f"| **Repro Test Verified** | `{'✅ Yes' if report.repro_verified else '⚠️ No'}` |",
            "",
        ]

        if report.violations:
            lines.extend([
                "### 🔍 Integrity Findings",
                "| Severity | Rule | File & Line | Message |",
                "| :---: | :---: | :--- | :--- |",
            ])
            for v in report.violations:
                sev_icon = "⛔ `BLOCKED`" if v.severity == Severity.BLOCKED else "⚠️ `WARNING`"
                lines.append(f"| {sev_icon} | `{v.rule_id}` | `{v.file_path}:{v.line_number}` | {v.message} |")

            lines.append("")
            lines.append("---")
            lines.append("*Protected by [SlopGate](https://github.com/Shinraya-Tech-Labs/slopgate) — The AST Code Integrity Shield for Open Source.*")

        return "\n".join(lines)

    @classmethod
    def render_github_annotations(cls, report: AuditReport) -> str:
        """Formats GitHub Actions workflow command annotations (::error:: and ::warning::)."""
        lines = []
        for v in report.violations:
            cmd = "error" if v.severity == Severity.BLOCKED else "warning"
            lines.append(f"::{cmd} file={v.file_path},line={v.line_number},title={v.title}::{v.message}")
        return "\n".join(lines)

    @classmethod
    def render_json(cls, report: AuditReport) -> str:
        data = {
            "status": report.status.value,
            "is_clean": report.is_clean,
            "summary": report.summary,
            "repro_verified": report.repro_verified,
            "metrics": {
                "files_changed": report.metrics.files_changed,
                "total_added": report.metrics.total_added,
                "total_removed": report.metrics.total_removed,
                "code_added": report.metrics.code_added,
                "test_added": report.metrics.test_added,
                "doc_added": report.metrics.doc_added,
                "slop_ratio": round(report.metrics.slop_ratio, 2),
            },
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "severity": v.severity.value,
                    "file_path": v.file_path,
                    "line_number": v.line_number,
                    "title": v.title,
                    "message": v.message,
                    "snippet": v.snippet,
                }
                for v in report.violations
            ],
        }
        return json.dumps(data, indent=2)
