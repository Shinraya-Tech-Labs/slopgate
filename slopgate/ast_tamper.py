"""
AST-Level Test Assertion & Mock Tamper Detection.
Detects when PRs dishonestly neuter tests to pass CI (removing asserts, tautologies,
try-except suppressions, and mock short-circuiting).
"""

import ast
from dataclasses import dataclass
from enum import Enum
import re
from typing import List, Optional, Tuple
from slopgate.diff_parser import FileDiff


class TamperKind(str, Enum):
    ASSERT_DELETED = "ASSERT_DELETED"
    ASSERT_WEAKENED = "ASSERT_WEAKENED"
    TRY_EXCEPT_BYPASS = "TRY_EXCEPT_BYPASS"
    TEST_SKIPPED = "TEST_SKIPPED"
    MOCK_SHORT_CIRCUIT = "MOCK_SHORT_CIRCUIT"


@dataclass
class TamperIncident:
    kind: TamperKind
    file_path: str
    line_number: int
    message: str
    snippet: str


class AstTamperAnalyzer:
    """Analyzes test file diffs to catch assertion weakening and test neutering."""

    @classmethod
    def analyze_file(cls, file_diff: FileDiff) -> List[TamperIncident]:
        incidents: List[TamperIncident] = []
        if not file_diff.is_test_file or not file_diff.is_python:
            return incidents

        # 1. Assertion Count & Deletion Tracking
        removed_asserts = [
            (ln, line) for ln, line in file_diff.removed_lines
            if cls._is_assert_line(line)
        ]
        added_asserts = [
            (ln, line) for ln, line in file_diff.added_lines
            if cls._is_assert_line(line)
        ]

        if len(removed_asserts) > len(added_asserts) and not file_diff.is_deleted:
            net_loss = len(removed_asserts) - len(added_asserts)
            for ln, line in removed_asserts[:net_loss]:
                incidents.append(
                    TamperIncident(
                        kind=TamperKind.ASSERT_DELETED,
                        file_path=file_diff.target_path,
                        line_number=ln,
                        message=f"Removed {net_loss} assertion(s) in test file without equivalent replacement.",
                        snippet=line.strip(),
                    )
                )

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

        # 4. Check for newly introduced @pytest.mark.skip or pytest.skip()
        for ln, line in file_diff.added_lines:
            stripped = line.strip()
            if "pytest.skip" in stripped or "@pytest.mark.skip" in stripped or "@unittest.skip" in stripped:
                incidents.append(
                    TamperIncident(
                        kind=TamperKind.TEST_SKIPPED,
                        file_path=file_diff.target_path,
                        line_number=ln,
                        message="Test explicitly skipped with pytest.skip / @mark.skip in PR.",
                        snippet=stripped,
                    )
                )

        return incidents

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
                            if isinstance(op, ast.IsNot) and isinstance(comparator, ast.Constant) and comparator.value is None:
                                return "Weakened assertion: 'is not None' checks existence instead of value equivalence."
                            if isinstance(op, ast.GtE) and isinstance(comparator, ast.Constant) and comparator.value == 0:
                                if isinstance(test.left, ast.Call) and isinstance(test.left.func, ast.Name) and test.left.func.id == "len":
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
    def _check_try_except_suppression(cls, file_diff: FileDiff, incidents: List[TamperIncident]):
        """Detects if added lines contain an except block that silently passes."""
        added_text = "\n".join(line for _, line in file_diff.added_lines)
        if "except" in added_text and "pass" in added_text:
            # Parse added fragments with ast
            try:
                tree = ast.parse(added_text)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ExceptHandler):
                        # check if body is just pass
                        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                            ln = getattr(node, "lineno", 1)
                            incidents.append(
                                TamperIncident(
                                    kind=TamperKind.TRY_EXCEPT_BYPASS,
                                    file_path=file_diff.target_path,
                                    line_number=ln,
                                    message="Test failure silently suppressed with 'except ...: pass'.",
                                    snippet="except: pass",
                                )
                            )
            except SyntaxError:
                # Fallback regex if snippet isn't a standalone valid module
                if re.search(r"except\s*.*:\s*(?:\n\s*)?pass\b", added_text):
                    incidents.append(
                        TamperIncident(
                            kind=TamperKind.TRY_EXCEPT_BYPASS,
                            file_path=file_diff.target_path,
                            line_number=file_diff.added_lines[0][0] if file_diff.added_lines else 1,
                            message="Test failure silently suppressed with 'except ...: pass'.",
                            snippet="except: pass",
                        )
                    )
