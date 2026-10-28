"""
SlopGate: AST-based Code Integrity & PR Integrity Shield for Open Source Maintainers.
Zero-dependency, deterministic detection of test tampering, phantom symbols, and slop bloat.
"""

__version__ = "0.1.0"
__author__ = "Shinraya Tech Labs"

from slopgate.engine import AuditEngine, AuditReport, Severity, Violation

__all__ = [
    "__version__",
    "AuditEngine",
    "AuditReport",
    "Violation",
    "Severity",
]
