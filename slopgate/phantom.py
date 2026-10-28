"""
Phantom Symbol & Hallucinated Import Detector.
Catches packages, modules, and API calls invented by LLMs that do not exist
in Python standard library, project manifests, or local repository files.
"""

import ast
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
import sys
import textwrap
from typing import List, Set, Optional
from slopgate.diff_parser import FileDiff


class PhantomKind(str, Enum):
    HALLUCINATED_IMPORT = "HALLUCINATED_IMPORT"
    HALLUCINATED_STDLIB_METHOD = "HALLUCINATED_STDLIB_METHOD"
    UNINSTALLED_DEPENDENCY = "UNINSTALLED_DEPENDENCY"


@dataclass
class PhantomIncident:
    kind: PhantomKind
    file_path: str
    line_number: int
    symbol: str
    message: str


class PhantomDetector:
    """Detects phantom imports and hallucinated APIs added in diffs."""

    # Python stdlib modules set (built-in in Python 3.10+)
    STDLIB_MODULES: Set[str] = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else {
        "os", "sys", "re", "json", "ast", "math", "time", "datetime", "typing", "pathlib",
        "collections", "itertools", "functools", "unittest", "logging", "urllib", "http",
        "hashlib", "subprocess", "shutil", "tempfile", "io", "string", "copy", "socket",
    }

    # Common hallucinated methods on standard library objects
    KNOWN_STDLIB_HALLUCINATIONS = {
        ("json", "loads_async"): "json has no async loads method.",
        ("json", "parse"): "json uses .loads(), not .parse().",
        ("os", "mkdir_p"): "os uses os.makedirs(..., exist_ok=True).",
        ("re", "match_all"): "re uses .findall() or .finditer(), not .match_all().",
        ("time", "sleep_async"): "time has no sleep_async; use asyncio.sleep().",
        ("sys", "print"): "sys has no print method; use builtin print() or sys.stdout.write().",
    }

    @classmethod
    def get_declared_dependencies(cls, repo_root: Optional[Path] = None) -> Set[str]:
        """Scans pyproject.toml, requirements.txt, setup.py to extract valid declared packages."""
        deps: Set[str] = set()
        if not repo_root:
            repo_root = Path.cwd()

        # 1. requirements.txt / requirements/*.txt
        for req_file in repo_root.glob("*requirement*.txt"):
            try:
                for line in req_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip().split("#")[0]
                    if line and not line.startswith(("-", "http", "git+")):
                        pkg = re.split(r"[><=~!;]", line)[0].strip().replace("-", "_").lower()
                        if pkg:
                            deps.add(pkg)
            except Exception:
                pass

        # 2. pyproject.toml
        pyproject = repo_root / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8", errors="ignore")
                # Look for dependencies = [...]
                for match in re.finditer(r'["\']([a-zA-Z0-9_\-]+)(?:[><=~^!;].*?)?["\']', content):
                    pkg = match.group(1).replace("-", "_").lower()
                    deps.add(pkg)
            except Exception:
                pass

        # 3. Local repo top-level packages & modules
        for p in repo_root.glob("*.py"):
            deps.add(p.stem.lower())
        for p in repo_root.glob("*/__init__.py"):
            deps.add(p.parent.name.lower())
        for p in repo_root.glob("src/*/__init__.py"):
            deps.add(p.parent.name.lower())

        return deps

    @classmethod
    def analyze_file(cls, file_diff: FileDiff, declared_deps: Set[str]) -> List[PhantomIncident]:
        incidents: List[PhantomIncident] = []
        if not file_diff.is_python or file_diff.is_deleted:
            return incidents

        added_code = "\n".join(line for _, line in file_diff.added_lines)
        if not added_code.strip():
            return incidents

        # Try AST parsing of added snippets with dedent & stub wrapper for bare returns
        dedented = textwrap.dedent(added_code)
        tree = None
        try:
            tree = ast.parse(dedented)
        except SyntaxError:
            try:
                stub_code = "def _fragment():\n" + textwrap.indent(dedented, "    ")
                tree = ast.parse(stub_code)
            except SyntaxError:
                tree = None

        if tree is None:
            # Fallback to regex-based line inspection if fragment is not a complete module
            return cls._fallback_regex_scan(file_diff, declared_deps)

        for node in ast.walk(tree):
            # Check `import x`
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_pkg = alias.name.split(".")[0].replace("-", "_").lower()
                    if not cls._is_known_package(top_pkg, declared_deps):
                        incidents.append(
                            PhantomIncident(
                                kind=PhantomKind.HALLUCINATED_IMPORT,
                                file_path=file_diff.target_path,
                                line_number=getattr(node, "lineno", 1),
                                symbol=alias.name,
                                message=f"Package '{alias.name}' is not in stdlib, project dependencies, or local modules.",
                            )
                        )

            # Check `from x import y`
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top_pkg = node.module.split(".")[0].replace("-", "_").lower()
                    if not cls._is_known_package(top_pkg, declared_deps):
                        incidents.append(
                            PhantomIncident(
                                kind=PhantomKind.HALLUCINATED_IMPORT,
                                file_path=file_diff.target_path,
                                line_number=getattr(node, "lineno", 1),
                                symbol=node.module,
                                message=f"Module '{node.module}' is not in stdlib, project dependencies, or local modules.",
                            )
                        )

            # Check hallucinated stdlib method calls (e.g. json.loads_async)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    mod_name = node.func.value.id
                    attr_name = node.func.attr
                    key = (mod_name, attr_name)
                    if key in cls.KNOWN_STDLIB_HALLUCINATIONS:
                        incidents.append(
                            PhantomIncident(
                                kind=PhantomKind.HALLUCINATED_STDLIB_METHOD,
                                file_path=file_diff.target_path,
                                line_number=getattr(node, "lineno", 1),
                                symbol=f"{mod_name}.{attr_name}",
                                message=cls.KNOWN_STDLIB_HALLUCINATIONS[key],
                            )
                        )

        return incidents

    @classmethod
    def _is_known_package(cls, pkg_name: str, declared_deps: Set[str]) -> bool:
        pkg_clean = pkg_name.replace("-", "_").lower()
        if pkg_clean in cls.STDLIB_MODULES:
            return True
        if pkg_clean in declared_deps:
            return True
        # Common build / test tooling usually injected by CI
        if pkg_clean in {"pytest", "unittest", "setuptools", "wheel", "typing_extensions"}:
            return True
        return False

    @classmethod
    def _fallback_regex_scan(cls, file_diff: FileDiff, declared_deps: Set[str]) -> List[PhantomIncident]:
        incidents: List[PhantomIncident] = []
        for ln, line in file_diff.added_lines:
            stripped = line.strip()
            # Check hallucinated method calls
            for (mod, method), msg in cls.KNOWN_STDLIB_HALLUCINATIONS.items():
                if f"{mod}.{method}" in stripped:
                    incidents.append(
                        PhantomIncident(
                            kind=PhantomKind.HALLUCINATED_STDLIB_METHOD,
                            file_path=file_diff.target_path,
                            line_number=ln,
                            symbol=f"{mod}.{method}",
                            message=msg,
                        )
                    )
            # import foo
            m = re.match(r"^import\s+([a-zA-Z0-9_\.]+)", stripped)
            if m:
                top_pkg = m.group(1).split(".")[0].lower()
                if not cls._is_known_package(top_pkg, declared_deps):
                    incidents.append(
                        PhantomIncident(
                            kind=PhantomKind.HALLUCINATED_IMPORT,
                            file_path=file_diff.target_path,
                            line_number=ln,
                            symbol=m.group(1),
                            message=f"Package '{m.group(1)}' is not in stdlib, project dependencies, or local modules.",
                        )
                    )
            # from foo import bar
            m2 = re.match(r"^from\s+([a-zA-Z0-9_\.]+)\s+import", stripped)
            if m2:
                top_pkg = m2.group(1).split(".")[0].lower()
                if not cls._is_known_package(top_pkg, declared_deps):
                    incidents.append(
                        PhantomIncident(
                            kind=PhantomKind.HALLUCINATED_IMPORT,
                            file_path=file_diff.target_path,
                            line_number=ln,
                            symbol=m2.group(1),
                            message=f"Module '{m2.group(1)}' is not in stdlib, project dependencies, or local modules.",
                        )
                    )
        return incidents
