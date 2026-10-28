"""
End-to-End Tests for SlopGate AuditEngine & Reporter.
"""

from pathlib import Path

from slopgate import AuditEngine, Severity, Violation
from slopgate.cli import SAMPLE_CLEAN_DIFF, SAMPLE_PHANTOM_DIFF, SAMPLE_TAMPERED_DIFF
from slopgate.reporter import Reporter

FIXTURES = Path(__file__).parent / "fixtures"


def _audit(fixture_name: str):
    diff_text = (FIXTURES / fixture_name).read_text(encoding="utf-8")
    return AuditEngine(repo_root=FIXTURES).audit_diff(diff_text)


def test_tampered_diff_audit():
    report = AuditEngine().audit_diff(SAMPLE_TAMPERED_DIFF)
    assert report.status == Severity.WARNING  # Assertion weakened
    assert any(v.rule_id == "SG-ASSERT_WEAKENED" for v in report.violations)
    # A tampered test must not count as a reproduction test
    assert not report.repro_verified


def test_phantom_diff_audit():
    report = AuditEngine().audit_diff(SAMPLE_PHANTOM_DIFF)
    assert report.status == Severity.BLOCKED
    assert any(v.rule_id == "SG-HALLUCINATED_IMPORT" for v in report.violations)
    assert not report.is_clean


def test_clean_diff_audit():
    report = AuditEngine().audit_diff(SAMPLE_CLEAN_DIFF)
    assert report.status == Severity.INFO
    assert report.is_clean
    assert report.not_blocked
    assert report.repro_verified
    assert len(report.violations) == 0


def test_warning_is_not_clean():
    report = AuditEngine().audit_diff(SAMPLE_TAMPERED_DIFF)
    assert report.status == Severity.WARNING
    assert not report.is_clean
    assert report.not_blocked


def test_neutered_test_fixture_is_blocked():
    report = _audit("neutered_test.diff")
    assert report.status == Severity.BLOCKED
    assert any(v.rule_id == "SG-ASSERT_DELETED" for v in report.violations)


def test_genuine_bugfix_fixture_is_clean():
    report = _audit("genuine_bugfix.diff")
    assert report.status == Severity.INFO
    assert report.repro_verified


def test_phantom_import_fixture_is_blocked():
    report = _audit("phantom_import.diff")
    assert report.status == Severity.BLOCKED


def test_slop_doc_bloat_fixture_is_flagged():
    report = _audit("slop_doc_bloat.diff")
    assert any(v.rule_id == "SG-SLOP_BLOAT" for v in report.violations)
    assert report.status == Severity.WARNING


def test_tampered_test_does_not_verify_repro():
    diff_text = """diff --git a/src/api.py b/src/api.py
--- a/src/api.py
+++ b/src/api.py
@@ -1,1 +1,2 @@
+def handler():
+    return 1
diff --git a/tests/test_api.py b/tests/test_api.py
--- a/tests/test_api.py
+++ b/tests/test_api.py
@@ -1,2 +1,2 @@
-    assert handler() == 1
+    assert handler() is not None
"""
    report = AuditEngine().audit_diff(diff_text)
    assert not report.repro_verified


def test_reporters():
    report = AuditEngine().audit_diff(SAMPLE_PHANTOM_DIFF)

    terminal_out = Reporter.render_terminal(report)
    assert "SLOPGATE" in terminal_out
    assert "BLOCKED" in terminal_out

    markdown_out = Reporter.render_github_markdown(report)
    assert "# ![" in markdown_out
    assert "SlopGate Status" in markdown_out

    json_out = Reporter.render_json(report)
    assert '"status": "BLOCKED"' in json_out
    assert '"not_blocked": false' in json_out


def test_github_annotations_escape_special_characters():
    report = AuditEngine().audit_diff(SAMPLE_PHANTOM_DIFF)
    report.violations.append(
        Violation(
            rule_id="SG-TEST",
            severity=Severity.BLOCKED,
            file_path="src/a,b.py",
            line_number=4,
            title="Title: with commas, here",
            message="line one\nline two, with 100% coverage",
        )
    )
    annotations = Reporter.render_github_annotations(report)
    assert "file=src/a%2Cb.py" in annotations
    assert "title=Title%3A with commas%2C here" in annotations
    assert "line one%0Aline two, with 100%25 coverage" in annotations
