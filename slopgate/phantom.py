"""
Phantom Symbol & Hallucinated Import Detector.
Catches packages, modules, and API calls invented by LLMs that do not exist
in Python standard library, project manifests, or local repository files.
"""

import ast
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Set

from slopgate.diff_parser import FileDiff
from slopgate.fragment import Fragment


class PhantomKind(str, Enum):
    HALLUCINATED_IMPORT = "HALLUCINATED_IMPORT"
    HALLUCINATED_STDLIB_METHOD = "HALLUCINATED_STDLIB_METHOD"


@dataclass
class PhantomIncident:
    kind: PhantomKind
    file_path: str
    line_number: int
    symbol: str
    message: str


def _normalize(name: str) -> str:
    """Normalizes a distribution or module name for comparison (PEP 503-ish)."""
    name = name.split("[")[0]
    name = re.split(r"[<>=~!;\s]", name)[0]
    return name.strip().replace("-", "_").replace(".", "_").lower()


class PhantomDetector:
    """Detects phantom imports and hallucinated APIs added in diffs."""

    # Python stdlib modules set (built-in in Python 3.10+)
    STDLIB_MODULES: Set[str] = (
        set(sys.stdlib_module_names)
        if hasattr(sys, "stdlib_module_names")
        else {
            "os",
            "sys",
            "re",
            "json",
            "ast",
            "math",
            "time",
            "datetime",
            "typing",
            "pathlib",
            "collections",
            "itertools",
            "functools",
            "unittest",
            "logging",
            "urllib",
            "http",
            "hashlib",
            "subprocess",
            "shutil",
            "tempfile",
            "io",
            "string",
            "copy",
            "socket",
        }
    )

    # Import name != distribution name for these packages.
    # shortcut: fixed alias table covers the common offenders, extend it when a
    # false positive is reported.
    IMPORT_ALIASES = {
        "yaml": "pyyaml",
        "cv2": "opencv_python",
        "pil": "pillow",
        "bs4": "beautifulsoup4",
        "skimage": "scikit_image",
        "sklearn": "scikit_learn",
        "dateutil": "python_dateutil",
        "dotenv": "python_dotenv",
        "jwt": "pyjwt",
        "serial": "pyserial",
        "openssl": "pyopenssl",
        "crypto": "pycryptodome",
        "usb": "pyusb",
        "attr": "attrs",
        "gi": "pygobject",
    }

    # Common hallucinated methods on standard library objects
    KNOWN_STDLIB_HALLUCINATIONS = {
        ("json", "loads_async"): "json has no async loads method.",
        ("json", "parse"): "json uses .loads(), not .parse().",
        ("os", "mkdir_p"): "os uses os.makedirs(..., exist_ok=True).",
        ("re", "match_all"): "re uses .findall() or .finditer(), not .match_all().",
        ("time", "sleep_async"): "time has no sleep_async; use asyncio.sleep().",
        (
            "sys",
            "print",
        ): "sys has no print method; use builtin print() or sys.stdout.write().",
    }

    @classmethod
    def get_declared_dependencies(cls, repo_root: Optional[Path] = None) -> Set[str]:
        """Scans dependency manifests and local modules to extract valid import names."""
        deps: Set[str] = set()
        repo_root = repo_root or Path.cwd()

        # 1. requirements.txt, requirements/*.txt, requirements-*.txt
        req_files = list(repo_root.glob("*requirement*.txt")) + list(
            repo_root.glob("requirements/*.txt")
        )
        for req_file in req_files:
            try:
                cls._read_requirement_lines(
                    req_file.read_text(encoding="utf-8", errors="ignore"), deps
                )
            except Exception:
                pass

        # 2. setup.cfg [options] install_requires
        setup_cfg = repo_root / "setup.cfg"
        if setup_cfg.exists():
            try:
                content = setup_cfg.read_text(encoding="utf-8", errors="ignore")
                block = re.search(
                    r"(?ms)^install_requires\s*=\s*\n(.*?)(?=^\S|\Z)", content
                )
                if block:
                    cls._read_requirement_lines(block.group(1), deps)
            except Exception:
                pass

        # 3. Pipfile [packages] / [dev-packages]
        pipfile = repo_root / "Pipfile"
        if pipfile.exists():
            try:
                content = pipfile.read_text(encoding="utf-8", errors="ignore")
                section = ""
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("["):
                        section = stripped.strip("[]").lower()
                    elif section in ("packages", "dev-packages") and "=" in stripped:
                        deps.add(_normalize(stripped.split("=")[0].strip(' "')))
            except Exception:
                pass

        # 4. pyproject.toml: only dependency sections, not every quoted string
        pyproject = repo_root / "pyproject.toml"
        if pyproject.exists():
            try:
                cls._read_pyproject(
                    pyproject.read_text(encoding="utf-8", errors="ignore"), deps
                )
            except Exception:
                pass

        # 5. Local repo top-level packages & modules
        for p in repo_root.glob("*.py"):
            deps.add(p.stem.lower())
        for pattern in ("*/__init__.py", "src/*.py", "src/*/__init__.py"):
            for p in repo_root.glob(pattern):
                deps.add(
                    p.stem.lower() if p.name != "__init__.py" else p.parent.name.lower()
                )

        return deps

    @classmethod
    def _read_requirement_lines(cls, text: str, deps: Set[str]):
        for line in text.splitlines():
            line = line.strip().split("#")[0]
            if not line or line.startswith(("-", "http", "git+", "--")):
                continue
            pkg = _normalize(line)
            if pkg:
                deps.add(pkg)

    @classmethod
    def _read_pyproject(cls, content: str, deps: Set[str]):
        section = ""
        in_deps = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped.strip("[]").strip()
                in_deps = False
                continue

            poetry_deps = section.startswith(
                (
                    "tool.poetry.dependencies",
                    "tool.poetry.dev-dependencies",
                    "tool.poetry.group",
                )
            )
            dependency_section = (
                section
                in (
                    "project.optional-dependencies",
                    "dependency-groups",
                    "build-system",
                )
                or poetry_deps
            )
            if re.match(r"^dependencies\s*=\s*\[", stripped):
                in_deps = True

            # Poetry declares packages as bare keys: requests = "^2.31"
            if poetry_deps and "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=")[0].strip().strip("\"'")
                if key and key != "python":
                    deps.add(_normalize(key))

            if in_deps or dependency_section:
                for match in re.finditer(r'["\']([A-Za-z0-9_.\-]+)', stripped):
                    deps.add(_normalize(match.group(1)))

            if in_deps and "]" in stripped:
                in_deps = False

    @classmethod
    def analyze_file(
        cls, file_diff: FileDiff, declared_deps: Set[str]
    ) -> List[PhantomIncident]:
        incidents: List[PhantomIncident] = []
        if not file_diff.is_python or file_diff.is_deleted:
            return incidents

        fragment = Fragment(file_diff)
        if not fragment.text.strip():
            return incidents

        tree, offset = fragment.parse()
        if tree is None:
            # Fallback to regex-based line inspection if fragment is not parseable
            return cls._fallback_regex_scan(file_diff, declared_deps)

        for node in ast.walk(tree):
            # Check `import x`
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_pkg = alias.name.split(".")[0]
                    if not cls._is_known_package(top_pkg, declared_deps):
                        incidents.append(
                            PhantomIncident(
                                kind=PhantomKind.HALLUCINATED_IMPORT,
                                file_path=file_diff.target_path,
                                line_number=fragment.real_line(
                                    getattr(node, "lineno", 1), offset
                                ),
                                symbol=alias.name,
                                message=f"Package '{alias.name}' is not in stdlib, project dependencies, or local modules.",
                            )
                        )

            # Check `from x import y`
            elif isinstance(node, ast.ImportFrom):
                # Relative imports (from . import x) always resolve inside the package
                if node.module and not node.level:
                    top_pkg = node.module.split(".")[0]
                    if not cls._is_known_package(top_pkg, declared_deps):
                        incidents.append(
                            PhantomIncident(
                                kind=PhantomKind.HALLUCINATED_IMPORT,
                                file_path=file_diff.target_path,
                                line_number=fragment.real_line(
                                    getattr(node, "lineno", 1), offset
                                ),
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
                                line_number=fragment.real_line(
                                    getattr(node, "lineno", 1), offset
                                ),
                                symbol=f"{mod_name}.{attr_name}",
                                message=cls.KNOWN_STDLIB_HALLUCINATIONS[key],
                            )
                        )

        return incidents

    @classmethod
    def _is_known_package(cls, pkg_name: str, declared_deps: Set[str]) -> bool:
        pkg_clean = _normalize(pkg_name)
        if pkg_clean in cls.STDLIB_MODULES:
            return True
        if pkg_clean in declared_deps:
            return True
        alias = cls.IMPORT_ALIASES.get(pkg_clean)
        if alias and alias in declared_deps:
            return True
        # Common build / test tooling usually injected by CI
        if pkg_clean in {
            "pytest",
            "unittest",
            "setuptools",
            "wheel",
            "typing_extensions",
        }:
            return True
        return False

    @classmethod
    def _fallback_regex_scan(
        cls, file_diff: FileDiff, declared_deps: Set[str]
    ) -> List[PhantomIncident]:
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
                top_pkg = m.group(1).split(".")[0]
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
            # from foo import bar (relative imports are skipped)
            m2 = re.match(r"^from\s+([a-zA-Z0-9_\.]+)\s+import", stripped)
            if m2:
                top_pkg = m2.group(1).split(".")[0]
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
