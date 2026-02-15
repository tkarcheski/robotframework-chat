"""Re-export from canonical location. Use rfc.safety_grader instead."""

from rfc.safety_grader import SafetyGrader
from rfc.models import SafetyResult

__all__ = ["SafetyGrader", "SafetyResult"]
