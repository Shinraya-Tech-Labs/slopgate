# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.4] - 2026-10-28

### Added

- `SG-TEST_SKIPPED` now also catches `@pytest.mark.skipif(True, ...)` and
  `raise unittest.SkipTest(...)` — two ways to disable a test without adding
  a skip marker.
- `SG-ASSERT_WEAKENED` now catches the `assert x == 1 or True` tautology and
  truthiness masking that hides among other comparisons in the same file.

### Fixed

- `assert x is not None` in a brand-new or reworked test no longer blocks: it
  is only reported when the same object lost a value comparison, which is the
  actual masking pattern.
- `assert isinstance(...)`, `hasattr`, `all` and `any` are real checks, not
  truthiness, and re-indented assertions are no longer treated as rewrites.
  (Found by running the gate over merged PRs in Flask.)
- Companion packages of a declared dependency (`pydantic_core` with
  `pydantic`) no longer report `SG-HALLUCINATED_IMPORT`. (Found by running the
  gate over merged PRs in FastAPI.)

## [0.1.3] - 2026-10-28

### Added

- **`SG-VACUOUS_TEST` (blocked):** a new test file that defines tests but
  contains no assertion (`assert`, `pytest.raises`, `self.assert*`, or a
  `mock.assert_*` call) is a placeholder, not a reproduction.
- **`SG-SELF_DECLARED_DEPENDENCY` (warning):** the import is served only by a
  dependency this same PR adds to a manifest. A diff can no longer silently
  whitelist a package it invents.

### Fixed

- **Assertion masking:** withdrawing a value comparison (`assert total == 30`)
  and adding a bare truthiness check (`assert cart`) is reported as
  `SG-ASSERT_WEAKENED`, even when the file's net assert count stays flat.
- **Release notes** now come from `CHANGELOG.md`; the build job refuses to
  publish a tag with no changelog section, and the GitHub Release is no longer
  created with an empty auto-generated body.
- README demo output regenerated from the current engine.

## [0.1.2] - 2026-10-28

### Fixed

- A test file that adds no assertion (only scaffolding — imports, a function
  body, no `assert` / `pytest.raises` / `self.assert*`) no longer counts as a
  reproduction test. Such a PR now reports `SG-MISSING_TEST_REPRO` instead of
  being reported as verified.

## [0.1.1] - 2026-10-28

Correctness release: two tamper classes that v0.1.0 reported as warnings now block.

### Fixed

- **Deleting a whole test file now blocks** (`SG-TEST_FILE_DELETED`) instead of
  only emitting the missing-repro warning.
- **`assert True` / `x is not None` weakening now blocks.** `ASSERT_WEAKENED` is
  part of the blocked set, so the default `fail-on: blocked` catches it.
- Local package detection walks the repo to depth 3 and no longer needs
  `__init__.py`, so PEP 420 namespace packages, `src/` and `python/` layouts stop
  reading as hallucinated imports. Virtualenv, `node_modules`, and build
  directories are skipped.
- Dependency manifests are read from subproject directories too (monorepos).
- `setup.py` `extras_require` entries count as dependencies, not just
  `install_requires`.
- Import/distribution aliases for `rest_framework`, `django_filters`, `github`,
  `MySQLdb`, `python-jose`, `grpcio`, and friends.
- Django-style test files (`myapp/tests.py`, `conftest.py`, `*_spec.py`, `spec/`)
  are treated as tests, so tampering there is detected.
- `from conftest import ...` and sibling helper modules resolve as local modules.
- A saved diff in UTF-16 (PowerShell `git diff > pr.diff`) is decoded instead of
  parsing to zero files and reporting a pass.
- An unparseable or unreadable diff exits 2 instead of being reported as clean.
- Missing `--diff` file prints one line and exits 2 instead of a traceback.
- Imports under `if TYPE_CHECKING:` are not treated as runtime dependencies.
- A UTF-8 BOM no longer hides findings on line 1.
- `@pytest.mark.xfail`, `unittest.expectedFailure`, and `pytest.importorskip` are
  detected as skips; the line fallback now always runs alongside the AST pass.
- Shallow checkouts suggest `fetch-depth: 0` instead of only "no diff detected".

### Changed

- Assert deletions are counted per file rather than per hunk, so splitting a test
  or moving assertions between hunks is not a false block; a net loss still is.
- `slopgate install` pins `@v0` (patch/minor updates) instead of the exact tag.
- The dogfood workflow no longer requests unused `pull-requests: write`.
- The Release job waits for the PyPI publish job, so a failed upload no longer
  produces a GitHub Release.
- Added the Python 3.14 classifier.

## [0.1.0] - 2026-10-28

First public release. Python 3.10+, zero runtime dependencies.

### Added

- `slopgate check` — audits a unified git diff from a file, stdin, or the current
  PR (`GITHUB_BASE_REF`), with `terminal`, `json`, and `github` output formats and
  `--fail-on blocked|warning|never`.
- Test tamper detection: deleted assertions (per hunk), tautology/weakening swaps,
  `try: ... except: pass` suppression, and newly added `pytest` skips — parsed
  with `ast`, so `skipif` and comments do not trip it.
- Phantom symbol detection: imports missing from the stdlib, declared dependencies
  (`pyproject.toml`, `requirements*.txt` incl. `-r` includes, `setup.py`,
  `setup.cfg`, `Pipfile`, `environment.yml`, Poetry) and local modules; plus a
  table of hallucinated stdlib methods.
- Reproduction gate: flags production changes that ship without a test change,
  and only counts the reproduction as verified when the test change is untampered.
- Slop ratio: docstring/comment bloat versus executable statements added.
- `slopgate demo` — offline interactive simulation of three real PR scenarios.
- `slopgate install` — writes a pinned `.github/workflows/slopgate.yml` into a repo.
- `slopgate badge` — Markdown and HTML README badges.
- Composite GitHub Action with Step Summary output and `::error` annotations.
- GitHub Actions workflows: CI matrix (Python 3.10–3.13 on Linux/macOS/Windows),
  package-integrity job (build + `twine check` + wheel smoke test), and a release
  pipeline (build → PyPI via Trusted Publishing or `PYPI_API_TOKEN` → GitHub
  Release) with SHA-pinned actions.

[Unreleased]: https://github.com/Shinraya-Tech-Labs/slopgate/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Shinraya-Tech-Labs/slopgate/releases/tag/v0.1.0
