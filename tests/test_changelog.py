from scripts.changelog_section import main, section

CHANGELOG = """# Changelog

## [Unreleased]

## [1.2.0] - 2026-01-01

### Added

- Something new.

## [1.1.0] - 2025-01-01

### Fixed

- Something else.
"""


def test_section_returns_only_the_matching_version():
    body = section(CHANGELOG, "1.2.0")
    assert "Something new." in body
    assert "Something else." not in body
    assert not body.startswith("## ")


def test_section_ignores_a_prefix_of_another_version():
    assert section(CHANGELOG, "1.2") == ""


def test_missing_section_falls_back_without_require():
    assert main(["prog", "9.9.9"]) == 0


def test_missing_section_fails_with_require(capsys):
    assert main(["prog", "--require", "9.9.9"]) == 1
    assert "9.9.9" in capsys.readouterr().err
