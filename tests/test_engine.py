"""
End-to-End Tests for SlopGate AuditEngine & Reporter.
"""

from slopgate.engine import AuditEngine, Severity
from slopgate.reporter import Reporter
from slopgate.cli import SAMPLE_TAMPERED_DIFF, SAMPLE_PHANTOM_DIFF, SAMPLE_CLEAN_DIFF


def test_tampered_diff_audit():
    engine = AuditEngine()
    report = engine.audit_diff(SAMPLE_TAMPERED_DIFF)
    assert report.status == Severity.WARNING  # Assertion weakened
    assert any(v.rule_id == "SG-ASSERT_WEAKENED" for v in report.violations)


def test_phantom_diff_audit():
    engine = AuditEngine()
    report = engine.audit_diff(SAMPLE_PHANTOM_DIFF)
    assert report.status == Severity.BLOCKED
    assert any(v.rule_id == "SG-HALLUCINATED_IMPORT" for v in report.violations)
    assert not report.is_clean


def test_clean_diff_audit():
    engine = AuditEngine()
    report = engine.audit_diff(SAMPLE_CLEAN_DIFF)
    assert report.status == Severity.INFO
    assert report.is_clean
    assert report.repro_verified
    assert len(report.violations) == 0


def test_reporters():
    engine = AuditEngine()
    report = engine.audit_diff(SAMPLE_PHANTOM_DIFF)

    terminal_out = Reporter.render_terminal(report)
    assert "SLOPGATE" in terminal_out
    assert "BLOCKED" in terminal_out

    markdown_out = Reporter.render_github_markdown(report)
    assert "# ![" in markdown_out
    assert "SlopGate Status" in markdown_out

    json_out = Reporter.render_json(report)
    assert '"status": "BLOCKED"' in json_out


if __name__ == "__main__":
    test_tampered_diff_audit()
    test_phantom_diff_audit()
    test_clean_diff_audit()
    test_reporters()
    print("[OK] All test_engine assertions passed!")
