"""Application ports implemented by infrastructure adapters."""

from course_tutor_practice.ports.outline import OutlineProvider, UnavailableOutlineProvider
from course_tutor_practice.ports.repository import PracticeRepository

__all__ = ["OutlineProvider", "PracticeRepository", "UnavailableOutlineProvider"]
