"""
Core SlopGate Audit Engine.
Orchestrates AST tamper checks, phantom symbol detection, diff metrics,
and maintainer verdict generation.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from slopgate.ast_tamper import AstTamperAnalyzer, TamperKind
from slopgate.diff_parser import DiffParser, FileDiff
from slopgate.phantom import PhantomDetector


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"


@dataclass
class Violation:
    rule_id: str
    severity: Severity
    file_path: str
    line_number: int
    title: str
    message: str
    snippet: Optional[str] = None


@dataclass
class DiffMetrics:
    total_added: int = 0
    total_removed: int = 0
    code_added: int = 0
    test_added: int = 0
    doc_added: int = 0
    files_changed: int = 0
    slop_ratio: float = 0.0  # ratio of doc/comment lines to real logic lines
    doc_heaviest_path: str = ""


@dataclass
class AuditReport:
    status: Severity
    violations: List[Violation] = field(default_factory=list)
    metrics: DiffMetrics = field(default_factory=DiffMetrics)
    repro_verified: bool = False
    summary: str = ""

    @property
    def is_clean(self) -> bool:
        return self.status == Severity.INFO

    @property
    def not_blocked(self) -> bool:
        return self.status != Severity.BLOCKED


QUOTE_DELIMS = ('"""', "'''")


def classify_added_python_lines(lines: List[Tuple[int, str]]) -> Tuple[int, int]:
    """Splits added Python lines into (doc/comment, executable) counts.

    Tracks multi-line block strings so docstring bodies count as docs, not code.
    """
    doc = 0
    code = 0
    block: Optional[str] = None
    for _, line in lines:
        stripped = line.strip()
        if block:
            doc += 1
            if block in stripped:
                block = None
            continue
        if not stripped:
            continue
        if stripped.startswith("#"):
            doc += 1
            continue
        # Drop a string prefix (r""" / f""" / rb""") before delimiter detection
        literal = re.sub(r"^[rRbBuUfF]{0,2}(?=['\"])", "", stripped)
        for delim in QUOTE_DELIMS:
            if literal.startswith(delim):
                doc += 1
                if literal.count(delim) == 1:
                    block = delim
                break
        else:
            code += 1
    return doc, code


class AuditEngine:
    """Orchestrates all SlopGate security and code integrity checks."""

    def __init__(self, repo_root: Optional[Path] = None):
        self.repo_root = repo_root or Path.cwd()
        self.declared_deps: Set[str] = PhantomDetector.get_declared_dependencies(
            self.repo_root
        )

    def audit_diff(self, diff_text: str) -> AuditReport:
        files = DiffParser.parse(diff_text)
        violations: List[Violation] = []
        metrics = self._compute_metrics(files)

        has_code_change = False
        has_test_change = False
        tampered_test = False

        for f in files:
            if f.is_test_file and f.is_deleted:
                # Deleting the test is the cheapest way to "make it pass"
                tampered_test = True
                violations.append(
                    Violation(
                        rule_id="SG-TEST_FILE_DELETED",
                        severity=Severity.BLOCKED,
                        file_path=f.old_path or f.target_path,
                        line_number=1,
                        title="Test File Deleted",
                        message="PR deletes a test file instead of fixing the code under test.",
                        snippet=None,
                    )
                )
            elif f.is_test_file:
                has_test_change = True
                # Run Test Tampering Inspection
                incidents = AstTamperAnalyzer.analyze_file(f)
                for inc in incidents:
                    tampered_test = True
                    sev = (
                        Severity.BLOCKED
                        if inc.kind
                        in (
                            TamperKind.ASSERT_DELETED,
                            TamperKind.ASSERT_WEAKENED,
                            TamperKind.TRY_EXCEPT_BYPASS,
                            TamperKind.TEST_SKIPPED,
                        )
                        else Severity.WARNING
                    )

                    violations.append(
                        Violation(
                            rule_id=f"SG-{inc.kind.value}",
                            severity=sev,
                            file_path=inc.file_path,
                            line_number=inc.line_number,
                            title=inc.kind.value.replace("_", " ").title(),
                            message=inc.message,
                            snippet=inc.snippet,
                        )
                    )
            elif f.is_python and f.added_lines:
                has_code_change = True

            # Run Phantom Symbol Inspection on all Python files
            if f.is_python:
                phantoms = PhantomDetector.analyze_file(f, self.declared_deps)
                for ph in phantoms:
                    violations.append(
                        Violation(
                            rule_id=f"SG-{ph.kind.value}",
                            severity=Severity.BLOCKED,
                            file_path=ph.file_path,
                            line_number=ph.line_number,
                            title=ph.kind.value.replace("_", " ").title(),
                            message=ph.message,
                            snippet=f"symbol: {ph.symbol}",
                        )
                    )

        # Repro Test Check: a test file must have been touched and not tampered with
        repro_verified = has_code_change and has_test_change and not tampered_test
        if has_code_change and not repro_verified:
            changed_prod = next(
                (
                    f
                    for f in files
                    if f.is_python
                    and not f.is_test_file
                    and not f.is_deleted
                    and f.added_lines
                ),
                None,
            )
            violations.append(
                Violation(
                    rule_id="SG-MISSING_TEST_REPRO",
                    severity=Severity.WARNING,
                    file_path=changed_prod.target_path if changed_prod else "diff",
                    line_number=1,
                    title="Missing Reproduction Test",
                    message="PR modifies production logic without adding a trustworthy test case.",
                    snippet=None,
                )
            )

        # Slop Ratio Check (e.g. 50 lines of explanatory comments with 1 line of logic)
        if (
            metrics.slop_ratio > 4.0
            and metrics.doc_added >= 30
            and 0 < metrics.code_added < 5
        ):
            violations.append(
                Violation(
                    rule_id="SG-SLOP_BLOAT",
                    severity=Severity.WARNING,
                    file_path=metrics.doc_heaviest_path or "diff",
                    line_number=1,
                    title="Disproportionate Comment/Doc Bloat",
                    message=f"PR contains high slop-to-logic ratio ({metrics.slop_ratio:.1f}x doc additions vs executable code).",
                    snippet=f"+{metrics.doc_added} doc lines vs +{metrics.code_added} code lines",
                )
            )

        # Determine overall status
        status = Severity.INFO
        if any(v.severity == Severity.BLOCKED for v in violations):
            status = Severity.BLOCKED
        elif any(v.severity == Severity.WARNING for v in violations):
            status = Severity.WARNING

        summary = self._generate_summary(status, violations)
        return AuditReport(
            status=status,
            violations=violations,
            metrics=metrics,
            repro_verified=repro_verified,
            summary=summary,
        )

    def _compute_metrics(self, files: List[FileDiff]) -> DiffMetrics:
        metrics = DiffMetrics(files_changed=len(files))
        doc_by_file: Dict[str, int] = {}
        for f in files:
            added = len(f.added_lines)
            removed = len(f.removed_lines)
            metrics.total_added += added
            metrics.total_removed += removed

            if f.is_test_file:
                metrics.test_added += added
            elif f.is_doc_file:
                metrics.doc_added += added
                doc_by_file[f.target_path] = added
            elif f.is_python:
                doc, code = classify_added_python_lines(f.added_lines)
                metrics.doc_added += doc
                metrics.code_added += code
                doc_by_file[f.target_path] = doc

        if doc_by_file:
            metrics.doc_heaviest_path = max(doc_by_file, key=lambda p: doc_by_file[p])

        if metrics.code_added > 0:
            metrics.slop_ratio = metrics.doc_added / metrics.code_added
        else:
            metrics.slop_ratio = float(metrics.doc_added)

        return metrics

    def _generate_summary(self, status: Severity, violations: List[Violation]) -> str:
        if status == Severity.INFO and not violations:
            return "✅ SlopGate Passed: All test assertions intact, no hallucinated symbols detected."

        blocked_count = sum(1 for v in violations if v.severity == Severity.BLOCKED)
        warning_count = sum(1 for v in violations if v.severity == Severity.WARNING)

        if status == Severity.BLOCKED:
            return f"⛔ SlopGate Blocked: Found {blocked_count} critical integrity violation(s) (test tampering / phantom symbols)."
        return f"⚠️ SlopGate Warning: Found {warning_count} non-blocking notice(s)."
