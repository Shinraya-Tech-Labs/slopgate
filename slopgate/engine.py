"""
Core SlopGate Audit Engine.
Orchestrates AST tamper checks, phantom symbol detection, diff metrics,
and maintainer verdict generation.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Set
from slopgate.diff_parser import DiffParser, FileDiff
from slopgate.ast_tamper import AstTamperAnalyzer, TamperKind
from slopgate.phantom import PhantomDetector, PhantomKind


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


@dataclass
class AuditReport:
    status: Severity
    violations: List[Violation] = field(default_factory=list)
    metrics: DiffMetrics = field(default_factory=DiffMetrics)
    repro_verified: bool = False
    summary: str = ""

    @property
    def is_clean(self) -> bool:
        return self.status != Severity.BLOCKED


class AuditEngine:
    """Orchestrates all SlopGate security and code integrity checks."""

    def __init__(self, repo_root: Optional[Path] = None):
        self.repo_root = repo_root or Path.cwd()
        self.declared_deps: Set[str] = PhantomDetector.get_declared_dependencies(self.repo_root)

    def audit_diff(self, diff_text: str, pr_title: str = "", pr_body: str = "") -> AuditReport:
        files = DiffParser.parse(diff_text)
        violations: List[Violation] = []
        metrics = self._compute_metrics(files)

        has_code_change = False
        has_test_change = False

        for f in files:
            if f.is_test_file:
                has_test_change = True
                # Run Test Tampering Inspection
                incidents = AstTamperAnalyzer.analyze_file(f)
                for inc in incidents:
                    sev = Severity.BLOCKED if inc.kind in (
                        TamperKind.ASSERT_DELETED,
                        TamperKind.TRY_EXCEPT_BYPASS,
                        TamperKind.TEST_SKIPPED
                    ) else Severity.WARNING

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
            elif f.is_python:
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

        # Repro Test Check
        repro_verified = False
        if has_code_change:
            if has_test_change:
                repro_verified = True
            else:
                # Code changed without any test additions or modifications
                violations.append(
                    Violation(
                        rule_id="SG-MISSING_TEST_REPRO",
                        severity=Severity.WARNING,
                        file_path="tests/",
                        line_number=1,
                        title="Missing Reproduction Test",
                        message="PR modifies production logic without adding or updating a test case.",
                        snippet=None,
                    )
                )

        # Slop Ratio Check (e.g. 50 lines of explanatory comments with 1 line of logic)
        if metrics.slop_ratio > 4.0 and metrics.doc_added > 30 and metrics.code_added < 5:
            violations.append(
                Violation(
                    rule_id="SG-SLOP_BLOAT",
                    severity=Severity.WARNING,
                    file_path="docs/",
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

        summary = self._generate_summary(status, violations, metrics)
        return AuditReport(
            status=status,
            violations=violations,
            metrics=metrics,
            repro_verified=repro_verified,
            summary=summary,
        )

    def _compute_metrics(self, files: List[FileDiff]) -> DiffMetrics:
        metrics = DiffMetrics(files_changed=len(files))
        for f in files:
            added = len(f.added_lines)
            removed = len(f.removed_lines)
            metrics.total_added += added
            metrics.total_removed += removed

            if f.is_test_file:
                metrics.test_added += added
            elif f.is_doc_file:
                metrics.doc_added += added
            elif f.is_python:
                # Separate comments from code in added lines
                for _, line in f.added_lines:
                    stripped = line.strip()
                    if stripped.startswith("#") or stripped.startswith(('"""', "'''")):
                        metrics.doc_added += 1
                    elif stripped:
                        metrics.code_added += 1

        if metrics.code_added > 0:
            metrics.slop_ratio = metrics.doc_added / metrics.code_added
        else:
            metrics.slop_ratio = float(metrics.doc_added)

        return metrics

    def _generate_summary(self, status: Severity, violations: List[Violation], metrics: DiffMetrics) -> str:
        if status == Severity.INFO and not violations:
            return "✅ SlopGate Passed: All test assertions intact, no hallucinated symbols detected."

        blocked_count = sum(1 for v in violations if v.severity == Severity.BLOCKED)
        warning_count = sum(1 for v in violations if v.severity == Severity.WARNING)

        if status == Severity.BLOCKED:
            return f"⛔ SlopGate Blocked: Found {blocked_count} critical integrity violation(s) (test tampering / phantom symbols)."
        return f"⚠️ SlopGate Warning: Found {warning_count} non-blocking notice(s) (missing repro test or bloat ratio)."
