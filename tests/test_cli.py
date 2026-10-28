"""
Tests for the CLI entry point: exit codes, formats, install, and hardening.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from slopgate import cli

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def _main(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["slopgate", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return exc.value.code


def test_check_exit_codes(monkeypatch, capsys):
    blocked = str(FIXTURES / "neutered_test.diff")
    clean = str(FIXTURES / "genuine_bugfix.diff")

    assert _main(monkeypatch, ["check", "--diff", blocked, "--fail-on", "blocked"]) == 1
    assert _main(monkeypatch, ["check", "--diff", blocked, "--fail-on", "warning"]) == 1
    assert _main(monkeypatch, ["check", "--diff", blocked, "--fail-on", "never"]) == 0
    assert _main(monkeypatch, ["check", "--diff", clean, "--fail-on", "warning"]) == 0
    capsys.readouterr()


def test_check_json_format(monkeypatch, capsys):
    _main(
        monkeypatch,
        ["check", "--diff", str(FIXTURES / "neutered_test.diff"), "--format", "json"],
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "BLOCKED"
    assert payload["is_clean"] is False
    assert payload["not_blocked"] is False


def test_check_github_format(monkeypatch, capsys):
    _main(
        monkeypatch,
        ["check", "--diff", str(FIXTURES / "neutered_test.diff"), "--format", "github"],
    )
    out = capsys.readouterr().out
    assert "SlopGate Status" in out
    assert "::error file=" in out


def test_summary_file(monkeypatch, capsys, tmp_path):
    summary = tmp_path / "summary.md"
    _main(
        monkeypatch,
        [
            "check",
            "--diff",
            str(FIXTURES / "neutered_test.diff"),
            "--summary-file",
            str(summary),
        ],
    )
    assert "SlopGate Status" in summary.read_text(encoding="utf-8")
    capsys.readouterr()


def test_missing_diff_fails_only_in_ci(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_git_diff", lambda: "")
    args = SimpleNamespace(
        diff_file=None, format="terminal", fail_on="blocked", summary_file=None
    )

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert cli.cmd_check(args) == 1

    monkeypatch.delenv("GITHUB_ACTIONS")
    assert cli.cmd_check(args) == 0
    capsys.readouterr()


def test_install_writes_workflow(monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert _main(monkeypatch, ["install"]) == 0
    assert (tmp_path / ".github" / "workflows" / "slopgate.yml").is_file()
    capsys.readouterr()


def test_version_flag(monkeypatch, capsys):
    assert _main(monkeypatch, ["--version"]) == 0
    capsys.readouterr()


@pytest.mark.skipif(
    sys.version_info < (3, 11), reason="PYTHONSAFEPATH needs Python 3.11+"
)
def test_checked_out_pr_cannot_shadow_package(tmp_path):
    """A PR adding its own slopgate/ package must not run code in the workflow."""
    pkg = tmp_path / "slopgate"
    pkg.mkdir()
    marker = tmp_path / "pwned.txt"
    (pkg / "__init__.py").write_text(
        f"open({str(marker)!r}, 'w').write('x')\n", encoding="utf-8"
    )

    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONSAFEPATH": "1"}
    env.pop("GITHUB_ACTIONS", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "slopgate.cli",
            "check",
            "--diff",
            str(FIXTURES / "neutered_test.diff"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert not marker.exists()
    assert result.returncode == 1
