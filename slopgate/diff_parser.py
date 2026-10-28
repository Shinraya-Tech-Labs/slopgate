"""
Git Unified Diff Parser.
Extracts modified files, hunks, line mappings, and added/removed fragments.
"""

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class Hunk:
    added: List[Tuple[int, str]] = field(default_factory=list)
    removed: List[Tuple[int, str]] = field(default_factory=list)


@dataclass
class FileDiff:
    old_path: Optional[str]
    new_path: Optional[str]
    is_deleted: bool = False
    is_new: bool = False
    added_lines: List[Tuple[int, str]] = field(default_factory=list)
    removed_lines: List[Tuple[int, str]] = field(default_factory=list)
    hunks: List[Hunk] = field(default_factory=list)
    raw_diff: str = ""

    @property
    def target_path(self) -> str:
        return self.new_path or self.old_path or "unknown"

    @property
    def is_python(self) -> bool:
        return self.target_path.endswith(".py")

    @property
    def is_test_file(self) -> bool:
        path = self.target_path.lower()
        parts = Path(path).parts
        return (
            any(p in ("tests", "test", "__tests__") for p in parts)
            or Path(path).name.startswith("test_")
            or Path(path).name.endswith("_test.py")
        )

    @property
    def is_doc_file(self) -> bool:
        path = self.target_path.lower()
        return path.endswith((".md", ".rst", ".txt", ".adoc", ".markdown"))


def _unquote(path: str) -> str:
    """Git wraps paths with spaces or special characters in double quotes."""
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        try:
            parts = shlex.split(path)
            if parts:
                return parts[0]
        except ValueError:
            return path.strip('"')
    return path


def _clean_path(path: str) -> Optional[str]:
    path = _unquote(path.strip())
    if path == "/dev/null":
        return None
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


class DiffParser:
    """Parses standard unified git diffs into structured FileDiff objects."""

    HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    @classmethod
    def _header_paths(cls, line: str) -> Tuple[Optional[str], Optional[str]]:
        rest = line[len("diff --git ") :]
        parts = shlex.split(rest) if '"' in rest else rest.split(" ")
        if len(parts) < 2:
            return None, None
        return _clean_path(parts[0]), _clean_path(parts[1])

    @classmethod
    def parse(cls, diff_text: str) -> List[FileDiff]:
        files: List[FileDiff] = []
        current_file: Optional[FileDiff] = None
        current_hunk: Optional[Hunk] = None
        old_line = 0
        new_line = 0

        lines = diff_text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]

            if line.startswith("diff --git "):
                if current_file:
                    files.append(current_file)
                old_p, new_p = cls._header_paths(line)
                current_file = FileDiff(
                    old_path=old_p, new_path=new_p, raw_diff=line + "\n"
                )
                current_hunk = None
                i += 1
                continue

            if current_file is None:
                # Diff text without 'diff --git' header, try parsing '---' and '+++'
                if line.startswith("--- "):
                    old_p = _clean_path(line[4:])
                    i += 1
                    new_p = None
                    if i < len(lines) and lines[i].startswith("+++ "):
                        new_p = _clean_path(lines[i][4:])
                        i += 1
                    current_file = FileDiff(old_path=old_p, new_path=new_p)
                    continue
                i += 1
                continue

            current_file.raw_diff += line + "\n"

            if line.startswith("new file mode"):
                current_file.is_new = True
            elif line.startswith("deleted file mode"):
                current_file.is_deleted = True
            elif line.startswith("--- "):
                path = _clean_path(line[4:])
                if path:
                    current_file.old_path = path
            elif line.startswith("+++ "):
                path = _clean_path(line[4:])
                if path:
                    current_file.new_path = path
            elif line.startswith("@@"):
                m = cls.HUNK_RE.match(line)
                if m:
                    old_line = int(m.group(1))
                    new_line = int(m.group(3))
                current_hunk = Hunk()
                current_file.hunks.append(current_hunk)
            elif line.startswith("+") and not line.startswith("+++"):
                if current_hunk is None:
                    # Fragments without hunk headers still need a bucket
                    current_hunk = Hunk()
                    current_file.hunks.append(current_hunk)
                current_file.added_lines.append((new_line, line[1:]))
                current_hunk.added.append((new_line, line[1:]))
                new_line += 1
            elif line.startswith("-") and not line.startswith("---"):
                if current_hunk is None:
                    current_hunk = Hunk()
                    current_file.hunks.append(current_hunk)
                current_file.removed_lines.append((old_line, line[1:]))
                current_hunk.removed.append((old_line, line[1:]))
                old_line += 1
            elif line.startswith(" "):
                old_line += 1
                new_line += 1

            i += 1

        if current_file:
            files.append(current_file)

        return files
