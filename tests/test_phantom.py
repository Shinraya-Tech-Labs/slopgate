"""
Tests for Phantom Symbol & Hallucinated Import Detector.
"""

from slopgate.diff_parser import DiffParser
from slopgate.phantom import PhantomDetector, PhantomKind


def test_detect_hallucinated_import():
    diff_text = """diff --git a/src/service.py b/src/service.py
--- a/src/service.py
+++ b/src/service.py
@@ -1,2 +1,3 @@
 import os
+import magic_ai_teleport_driver
"""
    files = DiffParser.parse(diff_text)
    declared_deps = {"requests", "fastapi"}
    incidents = PhantomDetector.analyze_file(files[0], declared_deps)
    assert any(inc.kind == PhantomKind.HALLUCINATED_IMPORT for inc in incidents)
    assert any("magic_ai_teleport_driver" in inc.symbol for inc in incidents)


def test_allow_stdlib_import():
    diff_text = """diff --git a/src/worker.py b/src/worker.py
--- a/src/worker.py
+++ b/src/worker.py
@@ -1,2 +1,3 @@
 import json
+import asyncio
+from pathlib import Path
"""
    files = DiffParser.parse(diff_text)
    declared_deps = set()
    incidents = PhantomDetector.analyze_file(files[0], declared_deps)
    assert len(incidents) == 0


def test_allow_declared_dependency():
    diff_text = """diff --git a/src/client.py b/src/client.py
--- a/src/client.py
+++ b/src/client.py
@@ -1,1 +1,2 @@
+import httpx
"""
    files = DiffParser.parse(diff_text)
    declared_deps = {"httpx"}
    incidents = PhantomDetector.analyze_file(files[0], declared_deps)
    assert len(incidents) == 0


def test_detect_hallucinated_stdlib_method():
    diff_text = """diff --git a/src/utils.py b/src/utils.py
--- a/src/utils.py
+++ b/src/utils.py
@@ -5,2 +5,3 @@
 def parse_payload(raw):
+    return json.loads_async(raw)
"""
    files = DiffParser.parse(diff_text)
    declared_deps = set()
    incidents = PhantomDetector.analyze_file(files[0], declared_deps)
    assert any(inc.kind == PhantomKind.HALLUCINATED_STDLIB_METHOD for inc in incidents)


if __name__ == "__main__":
    test_detect_hallucinated_import()
    test_allow_stdlib_import()
    test_allow_declared_dependency()
    test_detect_hallucinated_stdlib_method()
    print("[OK] All test_phantom assertions passed!")
