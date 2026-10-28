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


def test_assert_move_between_hunks_is_not_a_deletion():
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
    # Splitting a test moves assertions between hunks; only a net loss counts
    assert not any(
        inc.kind == TamperKind.ASSERT_DELETED for inc in _incidents(diff_text)
    )


def test_assert_net_loss_across_hunks_is_a_deletion():
    diff_text = """diff --git a/tests/test_math.py b/tests/test_math.py
--- a/tests/test_math.py
+++ b/tests/test_math.py
@@ -10,3 +10,1 @@ def test_one():
-    assert add(2, 2) == 4
-    assert add(3, 3) == 6
+    pass
@@ -40,1 +38,2 @@ def test_two():
+    assert add(1, 1) == 2
     pass
"""
    assert any(inc.kind == TamperKind.ASSERT_DELETED for inc in _incidents(diff_text))


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


def test_django_style_tests_module_is_detected():
    diff_text = """diff --git a/blog/tests.py b/blog/tests.py
--- a/blog/tests.py
+++ b/blog/tests.py
@@ -10,2 +10,1 @@
-    assert Post.objects.count() == 1
+    pass
"""
    assert any(inc.kind == TamperKind.ASSERT_DELETED for inc in _incidents(diff_text))


def test_xfail_and_expected_failure_are_skips():
    for marker in ('@pytest.mark.xfail(reason="flaky")', "@unittest.expectedFailure"):
        diff_text = (
            "diff --git a/tests/test_x.py b/tests/test_x.py\n"
            "--- a/tests/test_x.py\n"
            "+++ b/tests/test_x.py\n"
            "@@ -1,1 +1,2 @@\n"
            f"+{marker}\n"
            " def test_x():\n"
        )
        assert any(inc.kind == TamperKind.TEST_SKIPPED for inc in _incidents(diff_text))


def test_truthiness_replacement_after_removed_comparison_is_weakened():
    diff_text = """diff --git a/tests/test_cart.py b/tests/test_cart.py
--- a/tests/test_cart.py
+++ b/tests/test_cart.py
@@ -10,2 +10,2 @@ def test_total():
-    assert cart.total() == 30
+    assert cart
"""
    kinds = [inc.kind for inc in _incidents(diff_text)]
    assert TamperKind.ASSERT_WEAKENED in kinds


def test_truthiness_assert_without_removed_comparison_is_clean():
    diff_text = """diff --git a/tests/test_cart.py b/tests/test_cart.py
--- a/tests/test_cart.py
+++ b/tests/test_cart.py
@@ -10,1 +10,2 @@ def test_total():
     assert cart.total() == 30
+    assert cart.items
"""
    assert _incidents(diff_text) == []


def test_assert_helper_is_not_weakened():
    diff_text = """diff --git a/tests/test_cart.py b/tests/test_cart.py
--- a/tests/test_cart.py
+++ b/tests/test_cart.py
@@ -10,2 +10,2 @@ def test_total():
-    assert cart.total() == 30
+    self.assertIn("apple", cart.items)
"""
    assert _incidents(diff_text) == []


def test_added_comparison_keeps_the_diff_clean():
    diff_text = """diff --git a/tests/test_cart.py b/tests/test_cart.py
--- a/tests/test_cart.py
+++ b/tests/test_cart.py
@@ -10,2 +10,2 @@ def test_total():
-    assert cart.total() == 30
+    assert cart.total() != 0
"""
    assert _incidents(diff_text) == []


def test_skipif_with_constant_true_is_a_skip():
    diff_text = """diff --git a/tests/test_x.py b/tests/test_x.py
--- a/tests/test_x.py
+++ b/tests/test_x.py
@@ -1,1 +1,2 @@
+@pytest.mark.skipif(True, reason="flaky")
 def test_x():
"""
    assert any(inc.kind == TamperKind.TEST_SKIPPED for inc in _incidents(diff_text))


def test_conditional_skipif_is_not_a_skip():
    diff_text = """diff --git a/tests/test_x.py b/tests/test_x.py
--- a/tests/test_x.py
+++ b/tests/test_x.py
@@ -1,1 +1,2 @@
+@pytest.mark.skipif(sys.platform == "win32", reason="posix only")
 def test_x():
"""
    assert _incidents(diff_text) == []


def test_raise_skiptest_is_a_skip():
    diff_text = """diff --git a/tests/test_x.py b/tests/test_x.py
--- a/tests/test_x.py
+++ b/tests/test_x.py
@@ -1,1 +1,3 @@
 def test_x():
+    raise unittest.SkipTest("flaky")
     assert 1 == 1
"""
    assert any(inc.kind == TamperKind.TEST_SKIPPED for inc in _incidents(diff_text))


def test_or_true_tautology_is_weakened():
    diff_text = """diff --git a/tests/test_cart.py b/tests/test_cart.py
--- a/tests/test_cart.py
+++ b/tests/test_cart.py
@@ -10,1 +10,1 @@
-    assert total == 10
+    assert total == 10 or True
"""
    assert any(inc.kind == TamperKind.ASSERT_WEAKENED for inc in _incidents(diff_text))


def test_new_test_file_may_assert_existence():
    diff_text = """diff --git a/tests/test_new.py b/tests/test_new.py
--- /dev/null
+++ b/tests/test_new.py
@@ -0,0 +1,3 @@
+def test_profile():
+    assert profile is not None
+    assert profile.name == "x"
"""
    assert _incidents(diff_text) == []


def test_existence_check_on_the_same_subject_is_weakened():
    diff_text = """diff --git a/tests/test_api.py b/tests/test_api.py
--- a/tests/test_api.py
+++ b/tests/test_api.py
@@ -10,1 +10,1 @@
-    assert resp.json()["id"] == 3
+    assert resp.json() is not None
"""
    assert any(inc.kind == TamperKind.ASSERT_WEAKENED for inc in _incidents(diff_text))


def test_reindented_assertions_are_not_weakened():
    diff_text = """diff --git a/tests/test_ctx.py b/tests/test_ctx.py
--- a/tests/test_ctx.py
+++ b/tests/test_ctx.py
@@ -10,6 +10,6 @@
-        assert len(items) == 2
-        assert isinstance(items[0], ExceptionGroup)
+    assert len(items) == 2
+    assert isinstance(items[0], ExceptionGroup)
"""
    assert _incidents(diff_text) == []


def test_truthiness_on_the_same_object_is_weakened_despite_other_comparisons():
    diff_text = """diff --git a/tests/test_api.py b/tests/test_api.py
--- a/tests/test_api.py
+++ b/tests/test_api.py
@@ -10,1 +10,1 @@
-    assert resp.status_code == 200
+    assert resp.ok
@@ -30,1 +30,2 @@
+    assert other == 3
"""
    kinds = [inc.kind for inc in _incidents(diff_text)]
    assert TamperKind.ASSERT_WEAKENED in kinds
