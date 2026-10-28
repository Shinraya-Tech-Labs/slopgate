# Security Policy

## Supported versions

The latest release receives security fixes. Pre-1.0, that means the most recent
`v0.x` tag.

## Reporting a vulnerability

Email **labs@shinraya.com** with the details, or open a
[private security advisory](https://github.com/Shinraya-Tech-Labs/slopgate/security/advisories/new).
Please do not open a public issue for an exploitable problem.

You can expect an acknowledgement within 72 hours and a fix or mitigation plan
within 14 days.

## Scope

- The `slopgate` package and `slopgate` CLI.
- The composite GitHub Action in `action.yml` (supply-chain handling of the
  checked-out PR, token exposure, command injection through diff content).

Reports about SlopGate failing to *detect* a specific slop pattern are welcome as
regular issues — they are not security vulnerabilities.

## Hardening notes

- The action runs with `PYTHONSAFEPATH=1` and an explicit `PYTHONPATH`, so a PR
  that adds its own `slopgate/` package cannot execute code inside the workflow.
- All third-party actions are pinned to commit SHAs and kept current by Dependabot.
- The package has no runtime dependencies, so there is no transitive dependency
  surface to audit.
