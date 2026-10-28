"""
Tests for the unified diff parser: hunks, quoted paths, renames.
"""

from slopgate.diff_parser import DiffParser


def test_hunks_are_tracked_separately():
    diff_text = """diff --git a/tests/test_a.py b/tests/test_a.py
--- a/tests/test_a.py
+++ b/tests/test_a.py
@@ -10,2 +10,2 @@ def test_one():
-    assert value == 1
+    assert value is not None
@@ -40,2 +40,3 @@ def test_two():
+    assert other == 2
+    assert third == 3
     pass
"""
    files = DiffParser.parse(diff_text)
    assert len(files) == 1
    assert len(files[0].hunks) == 2
    assert len(files[0].hunks[0].removed) == 1
    assert len(files[0].hunks[1].added) == 2
    assert len(files[0].added_lines) == 3
    assert len(files[0].removed_lines) == 1


def test_quoted_paths_with_spaces():
    diff_text = """diff --git "a/src/my file.py" "b/src/my file.py"
--- "a/src/my file.py"
+++ "b/src/my file.py"
@@ -1,1 +1,2 @@
 x = 1
+y = 2
"""
    files = DiffParser.parse(diff_text)
    assert files[0].target_path == "src/my file.py"
    assert files[0].added_lines == [(2, "y = 2")]


def test_rename_without_hunks_keeps_paths():
    diff_text = """diff --git a/old_name.py b/new_name.py
similarity index 100%
rename from old_name.py
rename to new_name.py
"""
    files = DiffParser.parse(diff_text)
    assert files[0].old_path == "old_name.py"
    assert files[0].new_path == "new_name.py"
    assert files[0].added_lines == []


def test_c_quoted_paths_are_decoded():
    diff_text = (
        'diff --git "a/t\\303\\251st.py" "b/t\\303\\251st.py"\n'
        '--- "a/t\\303\\251st.py"\n'
        '+++ "b/t\\303\\251st.py"\n'
        "@@ -1,1 +1,1 @@\n"
        "-x = 1\n"
        "+x = 2\n"
    )
    files = DiffParser.parse(diff_text)
    assert files[0].target_path == "tést.py"


def test_combined_merge_diff_is_skipped_not_misnumbered():
    diff_text = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@@ -1,2 -1,2 +1,3 @@@
+  x = 1
+  y = 2
"""
    files = DiffParser.parse(diff_text)
    assert files[0].added_lines == []
    assert files[0].removed_lines == []


if __name__ == "__main__":
    test_hunks_are_tracked_separately()
    test_quoted_paths_with_spaces()
    test_rename_without_hunks_keeps_paths()
    print("[OK] All test_diff_parser assertions passed!")
