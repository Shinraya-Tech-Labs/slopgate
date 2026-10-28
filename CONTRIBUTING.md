# Contributing to SlopGate

Thank you for your interest in contributing to SlopGate! We are building the open-source defense against AI PR slop and test tampering.

## Code of Conduct & Integrity

SlopGate dogfoods itself! Every Pull Request submitted to SlopGate is audited by SlopGate.
- All bugfixes must include a test reproduction.
- No assertion weakening or mock bypasses.
- Keep the core engine zero-dependency (stdlib only).

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/Shinraya-Tech-Labs/slopgate.git
   cd slopgate
   ```

2. Run the test suite:
   ```bash
   python tests/test_tamper.py
   python tests/test_phantom.py
   python tests/test_engine.py
   ```

3. Run the interactive demo:
   ```bash
   python -m slopgate.cli demo
   ```

## PR Guidelines

- Use descriptive commit messages.
- Add test fixtures in `tests/fixtures/` for any new tamper or hallucination patterns.
- Ensure the code adheres to PEP 8 standards.

Thank you for helping keep open source clean and sustainable!
