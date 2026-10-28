"""
Partial AST for the added lines of a diff.

Diff fragments are rarely valid modules (a hunk can start mid-function), so the
parser retries the fragment wrapped in a stub function and reports the line
offset so callers can map AST line numbers back to real file lines.
"""

import ast
import textwrap
from typing import List, Optional, Tuple

from slopgate.diff_parser import FileDiff


class Fragment:
    def __init__(self, file_diff: FileDiff):
        self.text = "\n".join(line for _, line in file_diff.added_lines)
        self.line_map: List[int] = [ln for ln, _ in file_diff.added_lines]

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
