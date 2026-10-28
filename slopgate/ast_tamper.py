"""
AST-Level Test Assertion & Mock Tamper Detection.
Detects when PRs dishonestly neuter tests to pass CI (removing asserts, tautologies,
try-except suppressions, and skipped tests).
"""

import ast
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from slopgate.diff_parser import FileDiff, Hunk
from slopgate.fragment import Fragment


class TamperKind(str, Enum):
    ASSERT_DELETED = "ASSERT_DELETED"
    ASSERT_WEAKENED = "ASSERT_WEAKENED"
    TRY_EXCEPT_BYPASS = "TRY_EXCEPT_BYPASS"
    TEST_SKIPPED = "TEST_SKIPPED"


@dataclass
class TamperIncident:
    kind: TamperKind
    file_path: str
    line_number: int
    message: str
    snippet: str


# Exact attribute chains that neuter a test. Substring matching is not enough:
# '@pytest.mark.skipif' starts with '@pytest.mark.skip' but is legitimate.
SKIP_SYMBOLS = {"pytest.skip", "pytest.mark.skip", "unittest.skip"}
SKIP_FALLBACK_RE = re.compile(
    r"^\s*@?(?:pytest\.mark\.skip|unittest\.skip|pytest\.skip)\b"
)


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


class AstTamperAnalyzer:
    """Analyzes test file diffs to catch assertion weakening and test neutering."""

    @classmethod
    def analyze_file(cls, file_diff: FileDiff) -> List[TamperIncident]:
        incidents: List[TamperIncident] = []
        if not file_diff.is_test_file or not file_diff.is_python:
            return incidents

        cls._check_assert_deletions(file_diff, incidents)

        # 2. Check for Weakened Assertions / Tautologies in newly added lines using AST
        for ln, line in file_diff.added_lines:
            stripped = line.strip()
            if cls._is_assert_line(stripped):
                weakened_msg = cls._check_weakened_assert(stripped)
                if weakened_msg:
                    incidents.append(
                        TamperIncident(
                            kind=TamperKind.ASSERT_WEAKENED,
                            file_path=file_diff.target_path,
                            line_number=ln,
                            message=weakened_msg,
                            snippet=stripped,
                        )
                    )

        # 3. Check for Try-Except Suppressions (try: ... except: pass) in added lines
        cls._check_try_except_suppression(file_diff, incidents)

        # 4. Check for newly introduced skips
        cls._check_skips(file_diff, incidents)

        return incidents

    @classmethod
    def _check_assert_deletions(
        cls, file_diff: FileDiff, incidents: List[TamperIncident]
    ):
        """A hunk that drops assertions without replacing them is a tamper signal.

        Comparing per hunk (not per file) stops an unrelated new assertion in a
        different test from masking a deletion.
        """
        if file_diff.is_deleted:
            return
        for hunk in file_diff.hunks:
            cls._check_hunk_assertions(file_diff, hunk, incidents)

    @classmethod
    def _check_hunk_assertions(
        cls, file_diff: FileDiff, hunk: Hunk, incidents: List[TamperIncident]
    ):
        removed_asserts = [
            (ln, line) for ln, line in hunk.removed if cls._is_assert_line(line)
        ]
        added_asserts = [
            (ln, line) for ln, line in hunk.added if cls._is_assert_line(line)
        ]

        net_loss = len(removed_asserts) - len(added_asserts)
        if net_loss <= 0:
            return
        for ln, line in removed_asserts[:net_loss]:
            incidents.append(
                TamperIncident(
                    kind=TamperKind.ASSERT_DELETED,
                    file_path=file_diff.target_path,
                    line_number=ln,
                    message=f"Removed {net_loss} assertion(s) in this hunk without equivalent replacement.",
                    snippet=line.strip(),
                )
            )

    @classmethod
    def _check_weakened_assert(cls, assert_line: str) -> Optional[str]:
        """Uses AST to determine if an assertion is a tautology or weakened existence check."""
        try:
            tree = ast.parse(assert_line)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assert):
                    test = node.test
                    # assert True or assert 1
                    if isinstance(test, ast.Constant) and test.value in (True, 1):
                        return "Tautological assertion: 'assert True' / 'assert 1' validates nothing."

                    # assert ... is not None
                    if isinstance(test, ast.Compare):
                        for op, comparator in zip(test.ops, test.comparators):
                            if (
                                isinstance(op, ast.IsNot)
                                and isinstance(comparator, ast.Constant)
                                and comparator.value is None
                            ):
                                return "Weakened assertion: 'is not None' checks existence instead of value equivalence."
                            if (
                                isinstance(op, ast.GtE)
                                and isinstance(comparator, ast.Constant)
                                and comparator.value == 0
                            ):
                                if (
                                    isinstance(test.left, ast.Call)
                                    and isinstance(test.left.func, ast.Name)
                                    and test.left.func.id == "len"
                                ):
                                    return "Tautological assertion: 'len(...) >= 0' is unconditionally True."
        except SyntaxError:
            # Fallback regex
            if re.search(r"assert\s+True\b|assert\s+1\b", assert_line):
                return "Tautological assertion: 'assert True' / 'assert 1' validates nothing."
            if re.search(r"\bis\s+not\s+None\b", assert_line):
                return "Weakened assertion: 'is not None' checks existence instead of value equivalence."
        return None

    @staticmethod
    def _is_assert_line(line: str) -> bool:
        stripped = line.strip()
        return (
            stripped.startswith("assert ")
            or stripped.startswith("assert(")
            or stripped.startswith("self.assert")
        )

    @classmethod
    def _check_try_except_suppression(
        cls, file_diff: FileDiff, incidents: List[TamperIncident]
    ):
        """Detects if added lines contain an except block that silently passes."""
        fragment = Fragment(file_diff)
        if "except" not in fragment.text or "pass" not in fragment.text:
            return

        tree, offset = fragment.parse()
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                        incidents.append(
                            TamperIncident(
                                kind=TamperKind.TRY_EXCEPT_BYPASS,
                                file_path=file_diff.target_path,
                                line_number=fragment.real_line(
                                    getattr(node, "lineno", 1), offset
                                ),
                                message="Test failure silently suppressed with 'except ...: pass'.",
                                snippet="except: pass",
                            )
                        )
            return

        # Fallback regex if the snippet isn't parseable even with the stub wrapper
        if re.search(r"except\s*.*:\s*(?:\n\s*)?pass\b", fragment.text):
            incidents.append(
                TamperIncident(
                    kind=TamperKind.TRY_EXCEPT_BYPASS,
                    file_path=file_diff.target_path,
                    line_number=fragment.line_map[0] if fragment.line_map else 1,
                    message="Test failure silently suppressed with 'except ...: pass'.",
                    snippet="except: pass",
                )
            )

    @classmethod
    def _check_skips(cls, file_diff: FileDiff, incidents: List[TamperIncident]):
        fragment = Fragment(file_diff)
        found_lines = set()

        tree, offset = fragment.parse()
        if tree is not None:
            for node in ast.walk(tree):
                if _dotted(node) in SKIP_SYMBOLS:
                    found_lines.add(
                        fragment.real_line(getattr(node, "lineno", 1), offset)
                    )

        if found_lines:
            for ln in sorted(found_lines):
                incidents.append(
                    TamperIncident(
                        kind=TamperKind.TEST_SKIPPED,
                        file_path=file_diff.target_path,
                        line_number=ln,
                        message="Test explicitly skipped with pytest.skip / @mark.skip in PR.",
                        snippet="skip",
                    )
                )
            return

        # Fallback for fragments the parser cannot handle (e.g. mixed indentation)
        for ln, line in file_diff.added_lines:
            if SKIP_FALLBACK_RE.match(line):
                incidents.append(
                    TamperIncident(
                        kind=TamperKind.TEST_SKIPPED,
                        file_path=file_diff.target_path,
                        line_number=ln,
                        message="Test explicitly skipped with pytest.skip / @mark.skip in PR.",
                        snippet=line.strip(),
                    )
                )
