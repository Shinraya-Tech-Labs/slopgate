"""
Tests for Phantom Symbol & Hallucinated Import Detector.
"""

from pathlib import Path

from slopgate.diff_parser import DiffParser
from slopgate.engine import AuditEngine
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


def test_hallucinated_api_inside_a_docstring_is_ignored():
    diff_text = '''diff --git a/slopgate/cli.py b/slopgate/cli.py
--- a/slopgate/cli.py
+++ b/slopgate/cli.py
@@ -1,1 +1,5 @@
+SAMPLE = """diff --git a/x.py b/x.py
+    return json.loads_async(data)
+import fake_pkg
+"""
+    )
'''
    assert _incidents(diff_text, set()) == []


def test_unparseable_fragment_still_flags_real_calls():
    diff_text = """diff --git a/src/svc.py b/src/svc.py
--- a/src/svc.py
+++ b/src/svc.py
@@ -1,1 +1,3 @@
+    x = json.loads_async(data)
+    )
"""
    incidents = _incidents(diff_text, set())
    assert [inc.kind for inc in incidents] == [PhantomKind.HALLUCINATED_STDLIB_METHOD]


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


def test_allow_namespaced_distribution():
    diff_text = """diff --git a/src/storage.py b/src/storage.py
--- a/src/storage.py
+++ b/src/storage.py
@@ -1,1 +1,2 @@
+from google.cloud import storage
"""
    assert _incidents(diff_text, {"google_cloud_storage"}) == []


def test_declared_dependencies_reads_nested_requirements(tmp_path):
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements" / "dev.txt").write_text(
        "-r base.txt\npyyaml==6.0\n# comment\n", encoding="utf-8"
    )
    deps = PhantomDetector.get_declared_dependencies(tmp_path)
    assert "pyyaml" in deps
    assert "-r" not in deps


def test_declared_dependencies_reads_setup_py(tmp_path):
    (tmp_path / "setup.py").write_text(
        "from setuptools import setup\n"
        "setup(name='demo', install_requires=['numpy>=1.0', 'requests'])\n",
        encoding="utf-8",
    )
    deps = PhantomDetector.get_declared_dependencies(tmp_path)
    assert {"numpy", "requests"} <= deps


def test_declared_dependencies_reads_environment_yml(tmp_path):
    (tmp_path / "environment.yml").write_text(
        "name: demo\n"
        "dependencies:\n"
        "  - numpy=1.26\n"
        "  - conda-forge::scipy=1.11\n"
        "  - pip:\n"
        "      - requests\n",
        encoding="utf-8",
    )
    deps = PhantomDetector.get_declared_dependencies(tmp_path)
    assert "numpy" in deps
    assert "requests" in deps


def test_declared_dependencies_follows_requirement_includes(tmp_path):
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements" / "base.txt").write_text("httpx\n", encoding="utf-8")
    (tmp_path / "requirements" / "dev.txt").write_text(
        "-r base.txt\npytest\n", encoding="utf-8"
    )
    deps = PhantomDetector.get_declared_dependencies(tmp_path)
    assert {"httpx", "pytest"} <= deps


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


def _audit_in(repo_root, diff_text):
    return AuditEngine(repo_root=repo_root).audit_diff(diff_text)


def _hallucinated(report):
    return [v for v in report.violations if "HALLUCINATED" in v.rule_id]


def test_namespace_package_without_init_is_local(tmp_path):
    (tmp_path / "ns" / "sub").mkdir(parents=True)
    (tmp_path / "ns" / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "ns" / "sub" / "util.py").write_text("def helper():\n    return 1\n")
    diff = """diff --git a/app/main.py b/app/main.py
--- a/app/main.py
+++ b/app/main.py
@@ -1,1 +1,2 @@
+from ns.sub.util import helper
"""
    assert _hallucinated(_audit_in(tmp_path, diff)) == []


def test_subproject_manifest_is_read(tmp_path):
    (tmp_path / "services" / "api").mkdir(parents=True)
    (tmp_path / "services" / "api" / "pyproject.toml").write_text(
        '[project]\nname = "api"\ndependencies = ["fastapi>=0.100"]\n',
        encoding="utf-8",
    )
    diff = """diff --git a/services/api/main.py b/services/api/main.py
--- a/services/api/main.py
+++ b/services/api/main.py
@@ -1,1 +1,2 @@
+from fastapi import FastAPI
"""
    assert _hallucinated(_audit_in(tmp_path, diff)) == []


def test_setup_py_extras_are_dependencies(tmp_path):
    (tmp_path / "setup.py").write_text(
        "from setuptools import setup\n"
        "setup(\n"
        "    name='demo',\n"
        "    install_requires=['requests'],\n"
        "    extras_require={'aws': ['boto3>=1.0']},\n"
        ")\n",
        encoding="utf-8",
    )
    deps = PhantomDetector.get_declared_dependencies(tmp_path)
    assert {"requests", "boto3"} <= deps


def test_import_alias_for_declared_distribution():
    diff = """diff --git a/api/views.py b/api/views.py
--- a/api/views.py
+++ b/api/views.py
@@ -1,1 +1,2 @@
+from rest_framework.decorators import api_view
"""
    assert _incidents(diff, {"djangorestframework"}) == []


def test_type_checking_imports_are_not_runtime_deps():
    diff = """diff --git a/src/models.py b/src/models.py
--- a/src/models.py
+++ b/src/models.py
@@ -1,1 +1,4 @@
+from typing import TYPE_CHECKING
+if TYPE_CHECKING:
+    import pandas
"""
    assert _incidents(diff, set()) == []


def test_bom_does_not_hide_the_first_line():
    diff = (
        "diff --git a/src/x.py b/src/x.py\n"
        "--- a/src/x.py\n"
        "+++ b/src/x.py\n"
        "@@ -1,0 +1,1 @@\n"
        "+\ufeffimport hallucinated_pkg\n"
    )
    incidents = _incidents(diff, set())
    assert any(inc.symbol == "hallucinated_pkg" for inc in incidents)


def test_self_declared_dependency_is_reported():
    diff_text = """diff --git a/src/agent.py b/src/agent.py
--- a/src/agent.py
+++ b/src/agent.py
@@ -1,1 +1,2 @@
+from hallucinated_sdk import Agent
"""
    files = DiffParser.parse(diff_text)
    incidents = PhantomDetector.analyze_file(
        files[0], {"hallucinated_sdk"}, {"hallucinated_sdk"}
    )
    assert [inc.kind for inc in incidents] == [PhantomKind.SELF_DECLARED_DEPENDENCY]


def test_added_dependencies_reads_manifest_hunks():
    diff_text = """diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -5,2 +5,2 @@
-dependencies = ["requests>=2.0"]
+dependencies = ["requests>=2.0", "hallucinated-sdk>=1.0"]
"""
    files = DiffParser.parse(diff_text)
    added = PhantomDetector.added_dependencies(files, {"requests", "hallucinated_sdk"})
    assert added == {"hallucinated_sdk"}


def test_companion_package_of_declared_dependency_is_allowed():
    diff_text = """diff --git a/src/service.py b/src/service.py
--- a/src/service.py
+++ b/src/service.py
@@ -1,2 +1,3 @@
 import os
+from pydantic_core import CoreSchema
"""
    assert _incidents(diff_text, {"pydantic"}) == []
