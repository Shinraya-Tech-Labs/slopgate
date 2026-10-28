"""
Partial AST for the added lines of a diff.

Diff fragments are rarely valid modules (a hunk can start mid-function), so the
parser retries the fragment wrapped in a stub function and reports the line
offset so callers can map AST line numbers back to real file lines.
"""

import ast
import textwrap
from typing import List, Optional, Set, Tuple

from slopgate.diff_parser import FileDiff

QUOTE_DELIMS = ('"""', "'''")


def _lexical_string_lines(text: str) -> Set[int]:
    """Line ranges of complete triple-quoted strings in unparseable text.

    Only spans with a matching close count, so a hunk starting on a docstring
    *closing* line cannot swallow the rest of the hunk.
    """
    covered: Set[int] = set()
    opened: Optional[str] = None
    opened_at = 0
    for lineno, line in enumerate(text.splitlines(), start=1):
        for delim in QUOTE_DELIMS:
            start = 0
            while True:
                pos = line.find(delim, start)
                if pos < 0:
                    break
                start = pos + 3
                if pos > 0 and line[pos - 1] == "\\":
                    continue
                if opened is None:
                    opened, opened_at = delim, lineno
                elif opened == delim:
                    covered.update(range(opened_at, lineno + 1))
                    opened = None
    return covered


class Fragment:
    def __init__(self, file_diff: FileDiff):
        self.text = "\n".join(line for _, line in file_diff.added_lines)
        self.line_map: List[int] = [ln for ln, _ in file_diff.added_lines]

    @classmethod
    def from_lines(cls, lines: List[Tuple[int, str]]) -> "Fragment":
        fragment = cls.__new__(cls)
        fragment.text = "\n".join(line for _, line in lines)
        fragment.line_map = [ln for ln, _ in lines]
        return fragment

    def real_line(self, lineno: int, offset: int = 0) -> int:
        """Maps an AST line number inside the fragment to the real file line."""
        idx = lineno - 1 - offset
        if 0 <= idx < len(self.line_map):
            return self.line_map[idx]
        return self.line_map[0] if self.line_map else 1

    def parse(self) -> Tuple[Optional[ast.Module], int]:
        """Returns (tree, offset). offset is 1 when the stub wrapper was added."""
        dedented = textwrap.dedent(self.text)
        try:
            return ast.parse(dedented), 0
        except SyntaxError:
            pass
        try:
            return ast.parse(
                "def _fragment():\n" + textwrap.indent(dedented, "    ")
            ), 1
        except SyntaxError:
            return None, 0

    def string_lines(
        self, tree: Optional[ast.Module] = None, offset: Optional[int] = None
    ) -> Set[int]:
        """Fragment line numbers (1-based) sitting inside a multi-line string.

        Raw-line fallbacks use this so docstrings and fixtures are not scanned
        for API calls or assertions. Empty when the fragment does not parse.
        """
        if tree is None:
            tree, parsed_offset = self.parse()
            offset = parsed_offset
        offset = offset or 0
        if tree is None:
            return _lexical_string_lines(self.text)

        covered: Set[int] = set()
        for node in ast.walk(tree):
            is_str = (
                isinstance(node, ast.Constant) and isinstance(node.value, str)
            ) or isinstance(node, ast.JoinedStr)
            begin = getattr(node, "lineno", 0) - offset
            end = getattr(node, "end_lineno", begin) - offset
            if is_str and end > begin:
                covered.update(range(begin, end + 1))
        return covered
