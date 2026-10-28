"""
Tests for AST Tamper Analyzer: Assertion deletions, weakening, try-except bypasses.
"""

from slopgate.ast_tamper import AstTamperAnalyzer, TamperKind
from slopgate.diff_parser import DiffParser


def _incidents(diff_text):
    return AstTamperAnalyzer.analyze_file(DiffParser.parse(diff_text)[0])


def test_detect_assert_deletion():
    diff_text = """diff --git a/tests/test_math.py b/tests/test_math.py
--- a/tests/test_math.py
+++ b/tests/test_math.py
@@ -10,3 +10,1 @@
-    assert add(2, 2) == 4
-    assert add(3, 3) == 6
+    pass
"""
    assert any(inc.kind == TamperKind.ASSERT_DELETED for inc in _incidents(diff_text))


def test_assert_deletion_not_masked_by_other_hunk():
    diff_text = """diff --git a/tests/test_math.py b/tests/test_math.py
--- a/tests/test_math.py
+++ b/tests/test_math.py
@@ -10,2 +10,1 @@ def test_one():
-    assert add(2, 2) == 4
+    pass
@@ -40,1 +39,2 @@ def test_two():
+    assert add(1, 1) == 2
     pass
"""
    incidents = _incidents(diff_text)
    assert any(inc.kind == TamperKind.ASSERT_DELETED for inc in incidents)


def test_assert_rewrite_in_same_hunk_is_not_a_deletion():
    diff_text = """diff --git a/tests/test_math.py b/tests/test_math.py
--- a/tests/test_math.py
+++ b/tests/test_math.py
@@ -10,2 +10,2 @@
-    assert add(2, 2) == 4
+    assert add(2, 2) == 4.0
"""
    assert not any(
        inc.kind == TamperKind.ASSERT_DELETED for inc in _incidents(diff_text)
    )


def test_detect_weakened_assertion():
    diff_text = """diff --git a/tests/test_api.py b/tests/test_api.py
--- a/tests/test_api.py
+++ b/tests/test_api.py
@@ -5,2 +5,2 @@
-    assert response.status_code == 200
+    assert response.status_code is not None
"""
    assert any(inc.kind == TamperKind.ASSERT_WEAKENED for inc in _incidents(diff_text))


def test_detect_tautology_assert_true():
    diff_text = """diff --git a/tests/test_db.py b/tests/test_db.py
--- a/tests/test_db.py
+++ b/tests/test_db.py
@@ -20,1 +20,1 @@
+    assert True
"""
    assert any(inc.kind == TamperKind.ASSERT_WEAKENED for inc in _incidents(diff_text))


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
    assert any(
        inc.kind == TamperKind.TRY_EXCEPT_BYPASS for inc in _incidents(diff_text)
    )


def test_detect_skipped_test():
    diff_text = """diff --git a/tests/test_heavy.py b/tests/test_heavy.py
--- a/tests/test_heavy.py
+++ b/tests/test_heavy.py
@@ -1,2 +1,3 @@
+@pytest.mark.skip(reason="temp")
 def test_heavy():
     assert 1 + 1 == 2
"""
    assert any(inc.kind == TamperKind.TEST_SKIPPED for inc in _incidents(diff_text))


def test_conditional_skipif_is_allowed():
    diff_text = """diff --git a/tests/test_posix.py b/tests/test_posix.py
--- a/tests/test_posix.py
+++ b/tests/test_posix.py
@@ -1,2 +1,3 @@
+@pytest.mark.skipif(sys.platform == "win32", reason="posix only")
 def test_posix():
     assert 1 + 1 == 2
"""
    assert _incidents(diff_text) == []


def test_skip_mentioned_in_comment_is_allowed():
    diff_text = """diff --git a/tests/test_x.py b/tests/test_x.py
--- a/tests/test_x.py
+++ b/tests/test_x.py
@@ -1,2 +1,3 @@
+# TODO: remember that pytest.skip() exists
 def test_x():
     assert 1 + 1 == 2
"""
    assert _incidents(diff_text) == []


def test_docstring_text_removal_does_not_hide_assert_deletion():
    diff_text = '''diff --git a/tests/test_api.py b/tests/test_api.py
--- a/tests/test_api.py
+++ b/tests/test_api.py
@@ -6,3 +6,1 @@
-    """trailing doc text.
-    """
-    assert res.status == "ok"
+    pass
'''
    incidents = _incidents(diff_text)
    assert [inc.kind for inc in incidents] == [TamperKind.ASSERT_DELETED]


def test_assert_text_inside_a_docstring_is_ignored():
    diff_text = '''diff --git a/tests/test_dsl.py b/tests/test_dsl.py
--- a/tests/test_dsl.py
+++ b/tests/test_dsl.py
@@ -1,1 +1,4 @@
+EXAMPLE = """assert response is not None
+    assert True
+@pytest.mark.skip
+"""
'''
    assert _incidents(diff_text) == []


def test_incident_line_numbers_are_absolute():
    diff_text = """diff --git a/tests/test_late.py b/tests/test_late.py
--- a/tests/test_late.py
+++ b/tests/test_late.py
@@ -100,2 +100,4 @@
+    try:
+        run()
+    except Exception:
+        pass
"""
    incidents = _incidents(diff_text)
    assert [inc.line_number for inc in incidents] == [102]
