"""
Tests for AST Tamper Analyzer: Assertion deletions, weakening, try-except bypasses.
"""

from slopgate.diff_parser import DiffParser
from slopgate.ast_tamper import AstTamperAnalyzer, TamperKind


def test_detect_assert_deletion():
    diff_text = """diff --git a/tests/test_math.py b/tests/test_math.py
--- a/tests/test_math.py
+++ b/tests/test_math.py
@@ -10,3 +10,1 @@
-    assert add(2, 2) == 4
-    assert add(3, 3) == 6
+    pass
"""
    files = DiffParser.parse(diff_text)
    assert len(files) == 1
    incidents = AstTamperAnalyzer.analyze_file(files[0])
    assert any(inc.kind == TamperKind.ASSERT_DELETED for inc in incidents)


def test_detect_weakened_assertion():
    diff_text = """diff --git a/tests/test_api.py b/tests/test_api.py
--- a/tests/test_api.py
+++ b/tests/test_api.py
@@ -5,2 +5,2 @@
-    assert response.status_code == 200
+    assert response.status_code is not None
"""
    files = DiffParser.parse(diff_text)
    incidents = AstTamperAnalyzer.analyze_file(files[0])
    assert any(inc.kind == TamperKind.ASSERT_WEAKENED for inc in incidents)


def test_detect_tautology_assert_true():
    diff_text = """diff --git a/tests/test_db.py b/tests/test_db.py
--- a/tests/test_db.py
+++ b/tests/test_db.py
@@ -20,1 +20,1 @@
+    assert True
"""
    files = DiffParser.parse(diff_text)
    incidents = AstTamperAnalyzer.analyze_file(files[0])
    assert any(inc.kind == TamperKind.ASSERT_WEAKENED for inc in incidents)


def test_detect_try_except_suppression():
    diff_text = """diff --git a/tests/test_flaky.py b/tests/test_flaky.py
--- a/tests/test_flaky.py
+++ b/tests/test_flaky.py
@@ -10,1 +10,4 @@
+    try:
+        flaky_operation()
+    except Exception:
+        pass
"""
    files = DiffParser.parse(diff_text)
    incidents = AstTamperAnalyzer.analyze_file(files[0])
    assert any(inc.kind == TamperKind.TRY_EXCEPT_BYPASS for inc in incidents)


def test_detect_skipped_test():
    diff_text = """diff --git a/tests/test_heavy.py b/tests/test_heavy.py
--- a/tests/test_heavy.py
+++ b/tests/test_heavy.py
@@ -1,2 +1,3 @@
+@pytest.mark.skip(reason="temp")
 def test_heavy():
     assert 1 + 1 == 2
"""
    files = DiffParser.parse(diff_text)
    incidents = AstTamperAnalyzer.analyze_file(files[0])
    assert any(inc.kind == TamperKind.TEST_SKIPPED for inc in incidents)


if __name__ == "__main__":
    test_detect_assert_deletion()
    test_detect_weakened_assertion()
    test_detect_tautology_assert_true()
    test_detect_try_except_suppression()
    test_detect_skipped_test()
    print("[OK] All test_tamper assertions passed!")
