"""Print the CHANGELOG section for a version, for use as release notes."""

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def section(text: str, version: str) -> str:
    """Body of `## [<version>] ...` up to the next level-2 heading, or ""."""
    pattern = re.compile(
        rf"^## \[?{re.escape(version)}\]?(?=\s|$)[^\n]*\n(.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def main(argv) -> int:
    require = "--require" in argv
    args = [arg for arg in argv if arg != "--require"]
    version = args[1].lstrip("v") if len(args) > 1 else ""
    body = section(CHANGELOG.read_text(encoding="utf-8"), version) if version else ""
    if not body:
        if require:
            print(
                f"CHANGELOG.md has no section for {version or '<missing version>'}",
                file=sys.stderr,
            )
            return 1
        body = "See CHANGELOG.md for details."
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
