"""
SlopGate Command Line Interface.
Runs PR audits, simulated interactive demos, and GitHub Actions workflow installations.
"""

import argparse
from pathlib import Path
import subprocess
import sys
from typing import Optional

# Ensure UTF-8 output on Windows consoles
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from slopgate import __version__
from slopgate.engine import AuditEngine, Severity
from slopgate.reporter import Reporter, AnsiColor


GITHUB_WORKFLOW_TEMPLATE = """name: SlopGate PR Integrity Check

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  slopgate-audit:
    name: SlopGate PR Audit
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run SlopGate Integrity Check
        uses: Shinraya-Tech-Labs/slopgate@main
        with:
          fail-on: blocked
"""


SAMPLE_TAMPERED_DIFF = """diff --git a/src/auth.py b/src/auth.py
index 1234567..89abcdef 100644
--- a/src/auth.py
+++ b/src/auth.py
@@ -10,3 +10,4 @@ def verify_token(token: str) -> bool:
     if not token:
         return False
+    # AI: simplified token validation
     return True
diff --git a/tests/test_auth.py b/tests/test_auth.py
index 2345678..9abcdef0 100644
--- a/tests/test_auth.py
+++ b/tests/test_auth.py
@@ -14,3 +14,3 @@ def test_expired_token():
-    assert verify_token("expired_xyz") == False
+    assert verify_token("expired_xyz") is not None
"""

SAMPLE_PHANTOM_DIFF = """diff --git a/src/database.py b/src/database.py
index 3456789..abcdef01 100644
--- a/src/database.py
+++ b/src/database.py
@@ -5,2 +5,4 @@ import json
+import phantom_ai_driver
+from hallucinated_orm import AsyncSession
 
 def load_config():
-    return json.loads(data)
+    return json.loads_async(data)
"""

SAMPLE_CLEAN_DIFF = """diff --git a/src/calculator.py b/src/calculator.py
index 4567890..bcdef012 100644
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -8,2 +8,4 @@ def divide(a: float, b: float) -> float:
+    if b == 0:
+        raise ValueError("Cannot divide by zero")
     return a / b
diff --git a/tests/test_calculator.py b/tests/test_calculator.py
index 5678901..cdef0123 100644
--- a/tests/test_calculator.py
+++ b/tests/test_calculator.py
@@ -20,2 +20,6 @@ def test_divide_valid():
     assert divide(10, 2) == 5.0
+
+def test_divide_zero_repro():
+    import pytest
+    with pytest.raises(ValueError, match="Cannot divide by zero"):
+        divide(10, 0)
"""


def get_git_diff() -> str:
    """Gets git diff against GITHUB_BASE_REF, origin/main, master, or working tree."""
    import os
    base_ref = os.environ.get("GITHUB_BASE_REF")
    cmds = []
    if base_ref:
        cmds.extend([
            ["git", "diff", f"origin/{base_ref}...HEAD"],
            ["git", "diff", f"{base_ref}...HEAD"],
        ])
    cmds.extend([
        ["git", "diff", "origin/main...HEAD"],
        ["git", "diff", "main...HEAD"],
        ["git", "diff", "origin/master...HEAD"],
        ["git", "diff", "master...HEAD"],
        ["git", "diff", "HEAD~1"],
        ["git", "diff", "--cached"],
        ["git", "diff"],
    ])
    for cmd in cmds:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.stdout.strip():
                return res.stdout
        except Exception:
            continue
    return ""


def cmd_check(args: argparse.Namespace) -> int:
    """Audits diff text."""
    if args.diff_file == "-":
        diff_text = sys.stdin.read()
    elif args.diff_file:
        diff_text = Path(args.diff_file).read_text(encoding="utf-8", errors="ignore")
    else:
        diff_text = get_git_diff()
        if not diff_text:
            print("⚠️ No git diff detected. Provide a diff via --diff <file> or piped via stdin.")
            return 0

    engine = AuditEngine()
    report = engine.audit_diff(diff_text)

    # Output formatting
    if args.format == "json":
        print(Reporter.render_json(report))
    elif args.format == "github":
        print(Reporter.render_github_markdown(report))
        annotations = Reporter.render_github_annotations(report)
        if annotations:
            print(annotations)
    else:
        print(Reporter.render_terminal(report))

    # Write summary file if requested (e.g. $GITHUB_STEP_SUMMARY)
    if args.summary_file:
        Path(args.summary_file).write_text(Reporter.render_github_markdown(report), encoding="utf-8")

    # Exit code evaluation
    if args.fail_on == "blocked" and report.status == Severity.BLOCKED:
        return 1
    elif args.fail_on == "warning" and report.status in (Severity.BLOCKED, Severity.WARNING):
        return 1
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Runs interactive demonstration of SlopGate detecting AI slop scenarios in real time."""
    print(f"\n{AnsiColor.CYAN}{AnsiColor.BOLD}======================================================={AnsiColor.RESET}")
    print(f"{AnsiColor.BOLD} 🎮 SLOPGATE INTERACTIVE AUDIT SIMULATOR v{__version__}{AnsiColor.RESET}")
    print(f"{AnsiColor.CYAN}======================================================={AnsiColor.RESET}\n")

    engine = AuditEngine()

    print(f"{AnsiColor.BOLD}Scenario 1: Rogue AI PR weakens test assertion to pass CI{AnsiColor.RESET}")
    print(f"{AnsiColor.GRAY}Simulating: Contributor PR replaces 'assert val == False' with 'assert val is not None'...{AnsiColor.RESET}")
    rep1 = engine.audit_diff(SAMPLE_TAMPERED_DIFF)
    print(Reporter.render_terminal(rep1))

    print(f"{AnsiColor.BOLD}Scenario 2: AI PR with phantom packages and hallucinated stdlib APIs{AnsiColor.RESET}")
    print(f"{AnsiColor.GRAY}Simulating: PR imports 'phantom_ai_driver' and calls 'json.loads_async()'...{AnsiColor.RESET}")
    rep2 = engine.audit_diff(SAMPLE_PHANTOM_DIFF)
    print(Reporter.render_terminal(rep2))

    print(f"{AnsiColor.BOLD}Scenario 3: Genuine human bugfix with reproduction test case{AnsiColor.RESET}")
    print(f"{AnsiColor.GRAY}Simulating: Legitimate PR fixing ZeroDivisionError with reproduction test...{AnsiColor.RESET}")
    rep3 = engine.audit_diff(SAMPLE_CLEAN_DIFF)
    print(Reporter.render_terminal(rep3))

    print(f"{AnsiColor.GREEN}{AnsiColor.BOLD}✓ Simulator completed: 2 rogue AI PRs intercepted, 1 clean bugfix approved.{AnsiColor.RESET}\n")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    """Installs .github/workflows/slopgate.yml into the current repository."""
    wf_dir = Path(".github/workflows")
    wf_dir.mkdir(parents=True, exist_ok=True)
    wf_file = wf_dir / "slopgate.yml"
    wf_file.write_text(GITHUB_WORKFLOW_TEMPLATE, encoding="utf-8")
    print(f"✨ Successfully installed SlopGate workflow to {wf_file}")
    print("Now commit and push to enable automated AI slop PR protection in your repo!")
    return 0


def cmd_badge(args: argparse.Namespace) -> int:
    """Outputs Markdown and HTML README badges."""
    print("\n### 🛡️ SlopGate README Badges\n")
    print("**Markdown:**")
    print("[![Protected by SlopGate](https://img.shields.io/badge/PRs-SlopGate_Protected-brightgreen?style=flat-square&logo=github)](https://github.com/Shinraya-Tech-Labs/slopgate)")
    print("\n**HTML:**")
    print('<a href="https://github.com/Shinraya-Tech-Labs/slopgate"><img src="https://img.shields.io/badge/PRs-SlopGate_Protected-brightgreen?style=flat-square&logo=github" alt="Protected by SlopGate" /></a>\n')
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="slopgate",
        description="🛡️ SlopGate: AST-Based Code Integrity & PR Integrity Shield",
    )
    parser.add_argument("-v", "--version", action="version", version=f"slopgate {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    # check
    check_parser = subparsers.add_parser("check", help="Audit git diff or PR for code integrity violations")
    check_parser.add_argument("--diff", dest="diff_file", help="Path to unified diff file (or '-' for stdin)")
    check_parser.add_argument("--format", choices=["terminal", "github", "json"], default="terminal")
    check_parser.add_argument("--fail-on", choices=["blocked", "warning", "never"], default="blocked")
    check_parser.add_argument("--summary-file", help="Write GitHub Step Summary markdown to file path")

    # demo
    subparsers.add_parser("demo", help="Run interactive terminal simulation of SlopGate in action")

    # install
    subparsers.add_parser("install", help="Install SlopGate GitHub Action into current repository")

    # badge
    subparsers.add_parser("badge", help="Generate README badges for your repository")

    args = parser.parse_args()

    if not args.command:
        # Default behavior: run check
        args.command = "check"
        args.diff_file = None
        args.format = "terminal"
        args.fail_on = "blocked"
        args.summary_file = None

    if args.command == "check":
        sys.exit(cmd_check(args))
    elif args.command == "demo":
        sys.exit(cmd_demo(args))
    elif args.command == "install":
        sys.exit(cmd_install(args))
    elif args.command == "badge":
        sys.exit(cmd_badge(args))


if __name__ == "__main__":
    main()
