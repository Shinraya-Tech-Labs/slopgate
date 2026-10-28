"""
Git Unified Diff Parser.
Extracts modified files, line mappings, added/removed AST fragments, and hunk context.
"""

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import List, Optional, Tuple


@dataclass
class DiffLine:
    line_type: str  # '+', '-', ' '
    content: str
    old_line_no: Optional[int] = None
    new_line_no: Optional[int] = None


@dataclass
class FileDiff:
    old_path: Optional[str]
    new_path: Optional[str]
    is_deleted: bool = False
    is_new: bool = False
    added_lines: List[Tuple[int, str]] = field(default_factory=list)
    removed_lines: List[Tuple[int, str]] = field(default_factory=list)
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


class DiffParser:
    """Parses standard unified git diffs into structured FileDiff objects."""

    HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    @classmethod
    def parse(cls, diff_text: str) -> List[FileDiff]:
        files: List[FileDiff] = []
        current_file: Optional[FileDiff] = None
        old_line = 0
        new_line = 0

        lines = diff_text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]

            if line.startswith("diff --git "):
                if current_file:
                    files.append(current_file)
                # diff --git a/path b/path
                parts = line.split(" ")
                old_p = parts[2][2:] if len(parts) > 2 and parts[2].startswith("a/") else None
                new_p = parts[3][2:] if len(parts) > 3 and parts[3].startswith("b/") else None
                current_file = FileDiff(old_path=old_p, new_path=new_p, raw_diff=line + "\n")
                i += 1
                continue

            if current_file is None:
                # Diff text without 'diff --git' header, try parsing '---' and '+++'
                if line.startswith("--- "):
                    p = line[4:].strip()
                    old_p = p[2:] if p.startswith("a/") else p
                    i += 1
                    new_p = None
                    if i < len(lines) and lines[i].startswith("+++ "):
                        p2 = lines[i][4:].strip()
                        new_p = p2[2:] if p2.startswith("b/") else p2
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
                p = line[4:].strip()
                if p != "/dev/null":
                    current_file.old_path = p[2:] if p.startswith("a/") else p
            elif line.startswith("+++ "):
                p = line[4:].strip()
                if p != "/dev/null":
                    current_file.new_path = p[2:] if p.startswith("b/") else p
            elif line.startswith("@@"):
                m = cls.HUNK_RE.match(line)
                if m:
                    old_line = int(m.group(1))
                    new_line = int(m.group(3))
            elif line.startswith("+") and not line.startswith("+++"):
                current_file.added_lines.append((new_line, line[1:]))
                new_line += 1
            elif line.startswith("-") and not line.startswith("---"):
                current_file.removed_lines.append((old_line, line[1:]))
                old_line += 1
            elif line.startswith(" "):
                old_line += 1
                new_line += 1

            i += 1

        if current_file:
            files.append(current_file)

        return files
