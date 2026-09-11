from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import SkillCandidate, SkillRecord, SourceRecord


class SkillAdapter(ABC):
    """Extensible boundary between repository layouts and runtime behavior."""

    id: str
    priority: int = 0

    @abstractmethod
    def discover(self, source_root: Path) -> list[SkillCandidate]:
        """Find compatible skills below a materialized source root."""

    @abstractmethod
    def load_instructions(
        self,
        skill: SkillRecord,
        source: SourceRecord,
        *,
        runtime_mode: str = "generic",
    ) -> str:
        """Load or assemble the complete instructions for one installed skill."""


def is_ignored_path(path: Path, source_root: Path) -> bool:
    relative = path.relative_to(source_root)
    ignored = {".git", ".venv", "node_modules", "__pycache__", ".tox"}
    return any(part in ignored for part in relative.parts)
