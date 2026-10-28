"""
AST-Level Test Assertion & Mock Tamper Detection.
Detects when PRs dishonestly neuter tests to pass CI (removing asserts, tautologies,
try-except suppressions, and skipped tests).
"""

import ast
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Set, Tuple

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
# `skipif(<constant>)` and `raise SkipTest` neuter a test exactly like @skip does.
SKIPIF_SYMBOLS = {"pytest.mark.skipif", "unittest.skipIf", "skipif", "skipIf"}
SKIP_EXCEPTIONS = {"unittest.SkipTest", "SkipTest"}
# Calls that check a value rather than its truthiness.
STRONG_ASSERT_CALLS = {"isinstance", "issubclass", "hasattr", "callable", "all", "any"}


def _is_constant_true(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


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
        cls._check_weak_replacements(file_diff, incidents)
        cls._check_existence_replacement(file_diff, incidents)

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
    def _check_weak_replacements(
        cls, file_diff: FileDiff, incidents: List[TamperIncident]
    ):
        """Catches masking: delete a value comparison, add a truthiness check.

        Net assert counts can stay flat while the check itself is gutted, e.g.
        ``-assert price == 10`` in one test and ``+assert cart`` in another.
        Only fires when *every* assertion the diff adds is weaker than the value
        comparisons it removed, so a PR that also adds a real comparison is clean.
        """
        removed = [
            line
            for hunk in file_diff.hunks
            for _, line in cls._assert_lines(hunk.removed)
        ]
        if not any(cls._assert_compares(line) for line in removed):
            return
        # A re-indented assertion (moved into/out of a block) is not a rewrite.
        removed_text = {line.strip() for line in removed}
        added = cls._assert_lines(file_diff.added_lines)
        if not added:
            return
        weak = [
            (ln, line)
            for ln, line in added
            if cls._is_weak_assert(line) and line.strip() not in removed_text
        ]
        if not weak:
            return
        # When every added assertion is weak the whole file was gutted; when the
        # PR also adds real comparisons, only flag weak checks on the same subject
        # (e.g. `resp.status_code == 200` -> `assert resp.ok`).
        if all(cls._is_weak_assert(line) for _, line in added):
            flagged = weak
        else:
            removed_roots = {
                root for line in removed for root in cls._assert_roots(line)
            }
            flagged = [
                (ln, line)
                for ln, line in weak
                if cls._assert_roots(line) & removed_roots
            ]
        for ln, line in flagged:
            incidents.append(
                TamperIncident(
                    kind=TamperKind.ASSERT_WEAKENED,
                    file_path=file_diff.target_path,
                    line_number=ln,
                    message="Assertion weakened to a truthiness check while a value comparison was removed.",
                    snippet=line.strip(),
                )
            )

    @staticmethod
    def _assert_node(line: str) -> Optional[ast.Assert]:
        try:
            node = ast.parse(line.strip()).body[0]
        except (SyntaxError, IndexError):
            return None
        return node if isinstance(node, ast.Assert) else None

    @classmethod
    def _assert_compares(cls, line: str) -> bool:
        node = cls._assert_node(line)
        return node is not None and any(
            isinstance(child, ast.Compare) for child in ast.walk(node.test)
        )

    @classmethod
    def _is_weak_assert(cls, line: str) -> bool:
        """`assert x`, `assert x.y`, `assert not x`, `assert f()` â€” no value check.

        `self.assertIn(...)` / `assert_equal(...)` are real helpers, not weak.
        """
        node = cls._assert_node(line)
        if node is None:
            return False
        test = node.test
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            test = test.operand
        if isinstance(test, ast.Call):
            func = test.func
            name = _dotted(func).split(".")[-1]
            if name.startswith("assert") or name in STRONG_ASSERT_CALLS:
                return False
        return isinstance(test, (ast.Name, ast.Attribute, ast.Call))

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
    def _check_existence_replacement(
        cls, file_diff: FileDiff, incidents: List[TamperIncident]
    ):
        """`assert x is not None` only counts when it replaced a check on x.

        A brand-new test legitimately asserts that a value exists; masking shows up
        when the same subject stops being compared and starts being existence-checked.
        """
        removed: Set[str] = set()
        for hunk in file_diff.hunks:
            for _, line in cls._assert_lines(hunk.removed):
                removed |= cls._assert_roots(line)
        if not removed:
            return
        for ln, line in cls._assert_lines(file_diff.added_lines):
            if cls._is_existence_check(line) and cls._assert_roots(line) & removed:
                incidents.append(
                    TamperIncident(
                        kind=TamperKind.ASSERT_WEAKENED,
                        file_path=file_diff.target_path,
                        line_number=ln,
                        message="Weakened assertion: 'is not None' checks existence instead of value equivalence.",
                        snippet=line.strip(),
                    )
                )

    @classmethod
    def _assert_roots(cls, line: str) -> Set[str]:
        """Base object behind the assertion's subject (`resp.json() == x` -> resp)."""
        node = cls._assert_node(line)
        if node is None:
            return set()
        exprs = node.test.values if isinstance(node.test, ast.BoolOp) else [node.test]
        roots: Set[str] = set()
        for expr in exprs:
            if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
                expr = expr.operand
            if isinstance(expr, ast.Compare):
                expr = expr.left
            while isinstance(expr, (ast.Attribute, ast.Subscript)):
                expr = expr.value
            if isinstance(expr, ast.Call):
                expr = expr.func
                while isinstance(expr, (ast.Attribute, ast.Subscript)):
                    expr = expr.value
            if isinstance(expr, ast.Name):
                roots.add(expr.id)
        return roots

    @classmethod
    def _is_existence_check(cls, line: str) -> bool:
        node = cls._assert_node(line)
        if node is None:
            return bool(re.search(r"\bis\s+not\s+None\b", line))
        return isinstance(node.test, ast.Compare) and any(
            isinstance(op, ast.IsNot)
            and isinstance(comparator, ast.Constant)
            and comparator.value is None
            for op, comparator in zip(node.test.ops, node.test.comparators)
        )

    @classmethod
    def _check_weakened_assert(cls, assert_line: str) -> Optional[str]:
        """Uses AST to determine if an assertion is a tautology."""
        try:
            tree = ast.parse(assert_line)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assert):
                    test = node.test
                    # assert True or assert 1
                    if isinstance(test, ast.Constant) and test.value in (True, 1):
                        return "Tautological assertion: 'assert True' / 'assert 1' validates nothing."

                    # assert x or True — short-circuits to always-true
                    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
                        if any(
                            isinstance(value, ast.Constant) and value.value
                            for value in test.values
                        ):
                            return (
                                "Tautological assertion: '... or True' can never fail."
                            )

                    # assert len(...) >= 0
                    if isinstance(test, ast.Compare):
                        for op, comparator in zip(test.ops, test.comparators):
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
                elif (
                    isinstance(node, ast.Call)
                    and _dotted(node.func) in SKIPIF_SYMBOLS
                    and _is_constant_true(node.args[0] if node.args else None)
                ):
                    found_lines.add(
                        fragment.real_line(getattr(node, "lineno", 1), offset)
                    )
                elif (
                    isinstance(node, ast.Raise)
                    and isinstance(node.exc, ast.Call)
                    and _dotted(node.exc.func) in SKIP_EXCEPTIONS
                ):
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
            elif re.match(
                r"^@?(?:[\w.]*\.)?(?:skipif|skipIf)\(\s*True\b", stripped
            ) or re.match(r"raise\s+(?:unittest\.)?SkipTest\b", stripped):
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
