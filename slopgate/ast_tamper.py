"""
AST-Level Test Assertion & Mock Tamper Detection.
Detects when PRs dishonestly neuter tests to pass CI (removing asserts, tautologies,
try-except suppressions, and skipped tests).
"""

import ast
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

from slopgate.diff_parser import FileDiff
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
SKIP_SYMBOLS = {
    "pytest.skip",
    "pytest.mark.skip",
    "pytest.mark.xfail",
    "pytest.importorskip",
    "unittest.skip",
    "unittest.expectedFailure",
}
SKIP_FALLBACK_RE = re.compile(
    r"^\s*@?(?:pytest\.mark\.(?:skip|xfail)|unittest\.(?:skip|expectedFailure)"
    r"|pytest\.(?:skip|importorskip))\b"
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
        covered = Fragment(file_diff).string_lines()
        for idx, (ln, line) in enumerate(file_diff.added_lines, start=1):
            stripped = line.strip()
            if idx in covered or not cls._is_assert_line(stripped):
                continue
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
        """Net assertion loss across the file is a tamper signal.

        Counted per file (not per hunk) so splitting a test or converting it to
        parametrize does not look like a deletion; a net drop still counts.
        """
        if file_diff.is_deleted:
            return
        removed_asserts: List[Tuple[int, str]] = []
        added_count = 0
        for hunk in file_diff.hunks:
            removed_asserts.extend(cls._assert_lines(hunk.removed))
            added_count += len(cls._assert_lines(hunk.added))

        net_loss = len(removed_asserts) - added_count
        if net_loss <= 0:
            return
        for ln, line in removed_asserts[-net_loss:]:
            incidents.append(
                TamperIncident(
                    kind=TamperKind.ASSERT_DELETED,
                    file_path=file_diff.target_path,
                    line_number=ln,
                    message=f"Removed {net_loss} assertion(s) without equivalent replacement.",
                    snippet=line.strip(),
                )
            )

    @classmethod
    def _assert_lines(cls, lines: List[Tuple[int, str]]) -> List[Tuple[int, str]]:
        """Assertions in these lines, ignoring text inside block strings."""
        covered = Fragment.from_lines(lines).string_lines()
        return [
            (ln, line)
            for idx, (ln, line) in enumerate(lines, start=1)
            if idx not in covered and cls._is_assert_line(line)
        ]

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
        covered = fragment.string_lines()
        code_text = "\n".join(
            line
            for idx, (_, line) in enumerate(file_diff.added_lines, start=1)
            if idx not in covered
        )
        if re.search(r"except\s*.*:\s*(?:\n\s*)?pass\b", code_text):
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
        covered = fragment.string_lines()
        found_lines = set()

        tree, offset = fragment.parse()
        if tree is not None:
            for node in ast.walk(tree):
                if _dotted(node) in SKIP_SYMBOLS:
                    found_lines.add(
                        fragment.real_line(getattr(node, "lineno", 1), offset)
                    )

        # Always scan lines too: the AST path sees one node per decorator chain,
        # the regex catches what a partially parseable fragment hides.
        for idx, (ln, line) in enumerate(file_diff.added_lines, start=1):
            if idx in covered or ln in found_lines:
                continue
            stripped = line.strip()
            if SKIP_FALLBACK_RE.match(stripped):
                found_lines.add(ln)

        for ln in sorted(found_lines):
            incidents.append(
                TamperIncident(
                    kind=TamperKind.TEST_SKIPPED,
                    file_path=file_diff.target_path,
                    line_number=ln,
                    message="Test explicitly skipped with skip/xfail/expectedFailure in PR.",
                    snippet="skip",
                )
            )
