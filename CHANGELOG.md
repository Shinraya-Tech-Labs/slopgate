# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
  release pipeline (build → PyPI → GitHub Release) with SHA-pinned actions.

[Unreleased]: https://github.com/Shinraya-Tech-Labs/slopgate/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Shinraya-Tech-Labs/slopgate/releases/tag/v0.1.0
