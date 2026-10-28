"""
Tests for Phantom Symbol & Hallucinated Import Detector.
"""

from pathlib import Path

from slopgate.diff_parser import DiffParser
from slopgate.phantom import PhantomDetector, PhantomKind


def _incidents(diff_text, declared_deps):
    files = DiffParser.parse(diff_text)
    return PhantomDetector.analyze_file(files[0], declared_deps)


def test_detect_hallucinated_import():
    diff_text = """diff --git a/src/service.py b/src/service.py
--- a/src/service.py
+++ b/src/service.py
@@ -1,2 +1,3 @@
 import os
+import magic_ai_teleport_driver
"""
    incidents = _incidents(diff_text, {"requests", "fastapi"})
    assert any(inc.kind == PhantomKind.HALLUCINATED_IMPORT for inc in incidents)
    assert any("magic_ai_teleport_driver" in inc.symbol for inc in incidents)


def test_allow_stdlib_import():
    diff_text = """diff --git a/src/worker.py b/src/worker.py
--- a/src/worker.py
+++ b/src/worker.py
@@ -1,2 +1,4 @@
 import json
+import asyncio
+from pathlib import Path
"""
    assert _incidents(diff_text, set()) == []


def test_allow_declared_dependency():
    diff_text = """diff --git a/src/client.py b/src/client.py
--- a/src/client.py
+++ b/src/client.py
@@ -1,1 +1,2 @@
+import httpx
"""
    assert _incidents(diff_text, {"httpx"}) == []


def test_allow_relative_imports():
    diff_text = """diff --git a/mypkg/core.py b/mypkg/core.py
--- a/mypkg/core.py
+++ b/mypkg/core.py
@@ -1,2 +1,3 @@
+from .models import User
+from . import helpers
 import os
"""
    assert _incidents(diff_text, set()) == []


def test_allow_import_alias():
    diff_text = """diff --git a/src/config.py b/src/config.py
--- a/src/config.py
+++ b/src/config.py
@@ -1,1 +1,2 @@
+import yaml
"""
    assert _incidents(diff_text, {"pyyaml"}) == []


def test_detect_hallucinated_stdlib_method():
    diff_text = """diff --git a/src/utils.py b/src/utils.py
--- a/src/utils.py
+++ b/src/utils.py
@@ -5,2 +5,3 @@
 def parse_payload(raw):
+    return json.loads_async(raw)
"""
    incidents = _incidents(diff_text, set())
    assert any(inc.kind == PhantomKind.HALLUCINATED_STDLIB_METHOD for inc in incidents)


def test_line_numbers_map_to_real_file():
    diff_text = """diff --git a/src/x.py b/src/x.py
--- a/src/x.py
+++ b/src/x.py
@@ -100,2 +100,4 @@
+import fake_pkg
+from fake_two import thing
 def existing():
     pass
"""
    incidents = _incidents(diff_text, set())
    assert sorted(inc.line_number for inc in incidents) == [100, 101]


def test_declared_dependencies_only_reads_dependency_sections(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "foobar"\n'
        'description = "a thing"\n'
        "dependencies = [\n"
        '  "httpx>=0.27",\n'
        "]\n"
        "\n"
        "[tool.other]\n"
        'keywords = ["magic_sdk"]\n',
        encoding="utf-8",
    )
    deps = PhantomDetector.get_declared_dependencies(tmp_path)
    assert "httpx" in deps
    assert "foobar" not in deps
    assert "magic_sdk" not in deps


def test_declared_dependencies_reads_nested_requirements(tmp_path):
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements" / "dev.txt").write_text(
        "-r base.txt\npyyaml==6.0\n# comment\n", encoding="utf-8"
    )
    deps = PhantomDetector.get_declared_dependencies(tmp_path)
    assert "pyyaml" in deps
    assert "-r" not in deps


def test_declared_dependencies_reads_poetry(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.poetry]\n"
        'name = "demo"\n'
        "\n"
        "[tool.poetry.dependencies]\n"
        'python = "^3.10"\n'
        'requests = "^2.31"\n',
        encoding="utf-8",
    )
    deps = PhantomDetector.get_declared_dependencies(tmp_path)
    assert "requests" in deps
    assert "python" not in deps


def test_repo_root_local_package_is_known(tmp_path):
    (tmp_path / "mypkg").mkdir()
    (tmp_path / "mypkg" / "__init__.py").write_text("", encoding="utf-8")
    deps = PhantomDetector.get_declared_dependencies(tmp_path)
    assert "mypkg" in deps
    assert Path(tmp_path / "mypkg").is_dir()
