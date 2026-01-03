# src/robotframework_chat/models.py

from dataclasses import dataclass

@dataclass
class GradeResult:
    score: int
    reason: str