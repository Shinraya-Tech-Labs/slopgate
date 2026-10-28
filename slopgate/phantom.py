"""
Phantom Symbol & Hallucinated Import Detector.
Catches packages, modules, and API calls invented by LLMs that do not exist
in Python standard library, project manifests, or local repository files.
"""

import ast
import os
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


def _dotted(node: ast.AST) -> str:
    """Dotted name of a Name/Attribute chain ('typing.TYPE_CHECKING')."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


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
        "rest_framework": "djangorestframework",
        "django_filters": "django_filter",
        "github": "pygithub",
        "mysql": "mysqlclient",
        "mysqldb": "mysqlclient",
        "jose": "python_jose",
        "slugify": "python_slugify",
        "magic": "python_magic",
        "docx": "python_docx",
        "pptx": "python_pptx",
        "fitz": "pymupdf",
        "grpc": "grpcio",
        "googleapiclient": "google_api_python_client",
    }

    # Vendored, virtualenv, and build-output trees are not project code.
    IGNORED_DIRS = {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "build",
        "dist",
        "__pycache__",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        "site-packages",
        "htmlcov",
        ".eggs",
    }
    LOCAL_SCAN_DEPTH = 3

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
        """Scans dependency manifests and local modules to extract valid import names.

        Manifests are read from every directory up to LOCAL_SCAN_DEPTH so
        monorepos and `src/` layouts resolve too. The manifest is the PR head's
        copy: shortcut: a PR that adds its own dependency declaration can
        whitelist a package in the same diff, move to base-SHA manifests if
        that is ever abused.
        """
        repo_root = (repo_root or Path.cwd()).resolve()
        deps: Set[str] = set()

        for directory in cls._walk_dirs(repo_root):
            cls._scan_manifests(directory, deps)
            if directory != repo_root:
                # Local package directory (works without __init__.py, PEP 420)
                deps.add(directory.name.lower())
            for entry in directory.iterdir():
                if entry.is_file() and entry.suffix == ".py":
                    deps.add(entry.stem.lower())

        deps.discard("")
        return deps

    @classmethod
    def _walk_dirs(cls, repo_root: Path) -> List[Path]:
        """Repo directories up to LOCAL_SCAN_DEPTH, skipping vendored/venv trees."""
        dirs: List[Path] = []
        base_depth = len(repo_root.parts)
        for dirpath, dirnames, _ in os.walk(repo_root):
            current = Path(dirpath)
            if len(current.parts) - base_depth >= cls.LOCAL_SCAN_DEPTH:
                dirnames[:] = []
            dirnames[:] = [
                d
                for d in dirnames
                if d.lower() not in cls.IGNORED_DIRS and not d.startswith(".")
            ]
            dirs.append(current)
        return dirs

    @classmethod
    def _scan_manifests(cls, repo_root: Path, deps: Set[str]) -> None:
        """Reads every dependency manifest directly inside one directory."""
        # 1. requirements.txt, requirements/*.txt, requirements-*.txt
        req_files = list(repo_root.glob("*requirement*.txt")) + list(
            repo_root.glob("requirements/*.txt")
        )
        for req_file in sorted(set(req_files)):
            cls._read_requirements_file(req_file, deps)

        # 2. setup.py install_requires / extras_require (all quoted dist names)
        setup_py = repo_root / "setup.py"
        if setup_py.exists():
            try:
                content = setup_py.read_text(encoding="utf-8", errors="ignore")
                if "install_requires" in content or "extras_require" in content:
                    for match in re.finditer(
                        r'["\']([A-Za-z0-9][A-Za-z0-9_.\-]*)(?:\[[^\]]*\])?'
                        r'(?:[<>=!~][^"\']*)?["\']',
                        content,
                    ):
                        deps.add(_normalize(match.group(1)))
            except Exception:
                pass

        # 3. setup.cfg [options] install_requires
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

        # 4. environment.yml (conda)
        for env_file in (repo_root / "environment.yml", repo_root / "environment.yaml"):
            if not env_file.exists():
                continue
            try:
                content = env_file.read_text(encoding="utf-8", errors="ignore")
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- ") and "::" not in stripped:
                        deps.add(_normalize(stripped[2:]))
            except Exception:
                pass

        # 5. Pipfile [packages] / [dev-packages]
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

        # 6. pyproject.toml: only dependency sections, not every quoted string
        pyproject = repo_root / "pyproject.toml"
        if pyproject.exists():
            try:
                cls._read_pyproject(
                    pyproject.read_text(encoding="utf-8", errors="ignore"), deps
                )
            except Exception:
                pass

    @classmethod
    def _read_requirements_file(cls, path: Path, deps: Set[str], depth: int = 0):
        """Reads a requirements file, following `-r` includes one level deep."""
        if depth > 5:
            return
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return
        for line in text.splitlines():
            stripped = line.strip().split("#")[0].strip()
            if not stripped:
                continue
            if stripped.startswith(("-r ", "--requirement ")):
                included = stripped.split(None, 1)[1].strip().strip("'\"")
                cls._read_requirements_file(path.parent / included, deps, depth + 1)
                continue
            if stripped.startswith("-") or "://" in stripped:
                continue
            deps.add(_normalize(stripped))

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
        if tree is not None:
            return cls._scan_tree(
                tree,
                file_diff,
                lambda lineno: fragment.real_line(lineno, offset),
                declared_deps,
            )

        # Unparseable fragment (a hunk can start mid-expression): scan each added
        # line on its own. Single-line strings parse as expressions, not calls.
        # shortcut: statement-shaped prose inside a docstring of an unparseable
        # hunk can still be flagged; upgrade to tokenize-based skipping if reported.
        covered = fragment.string_lines()
        for idx, (ln, line) in enumerate(file_diff.added_lines, start=1):
            if idx in covered:
                continue
            try:
                line_tree = ast.parse(line.strip())
            except SyntaxError:
                continue
            incidents.extend(
                cls._scan_tree(
                    line_tree, file_diff, lambda _lineno, ln=ln: ln, declared_deps
                )
            )
        return incidents

    @classmethod
    def _scan_tree(cls, tree, file_diff, line_of, declared_deps: Set[str]):
        incidents: List[PhantomIncident] = []
        # Imports under `if TYPE_CHECKING:` never load at runtime.
        type_only_lines: Set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and _dotted(node.test) in (
                "TYPE_CHECKING",
                "typing.TYPE_CHECKING",
            ):
                end = getattr(node, "end_lineno", None) or node.lineno
                type_only_lines.update(range(node.lineno, end + 1))

        for node in ast.walk(tree):
            # Check `import x`
            if isinstance(node, ast.Import):
                if getattr(node, "lineno", 0) in type_only_lines:
                    continue
                for alias in node.names:
                    top_pkg = alias.name.split(".")[0]
                    if not cls._is_known_package(top_pkg, declared_deps):
                        incidents.append(
                            PhantomIncident(
                                kind=PhantomKind.HALLUCINATED_IMPORT,
                                file_path=file_diff.target_path,
                                line_number=line_of(getattr(node, "lineno", 1)),
                                symbol=alias.name,
                                message=f"Package '{alias.name}' is not in stdlib, project dependencies, or local modules.",
                            )
                        )

            # Check `from x import y`
            elif isinstance(node, ast.ImportFrom):
                if getattr(node, "lineno", 0) in type_only_lines:
                    continue
                # Relative imports (from . import x) always resolve inside the package
                if node.module and not node.level:
                    top_pkg = node.module.split(".")[0]
                    if not cls._is_known_package(top_pkg, declared_deps):
                        incidents.append(
                            PhantomIncident(
                                kind=PhantomKind.HALLUCINATED_IMPORT,
                                file_path=file_diff.target_path,
                                line_number=line_of(getattr(node, "lineno", 1)),
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
                                line_number=line_of(getattr(node, "lineno", 1)),
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
        # Namespaced distributions: import `google.cloud.x` is served by
        # `google-cloud-storage` (normalized prefix match).
        if any(dep.startswith(pkg_clean + "_") for dep in declared_deps):
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
