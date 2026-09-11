from __future__ import annotations

from pathlib import Path

from ..models import SkillCandidate, SkillRecord, SourceRecord
from .base import SkillAdapter
from .kskill import KSkillAdapter
from .local import LocalSkillAdapter
from .standard import StandardAgentSkillAdapter


class AdapterRegistry:
    def __init__(self, adapters: list[SkillAdapter] | None = None):
        configured = adapters or [KSkillAdapter(), StandardAgentSkillAdapter(), LocalSkillAdapter()]
        self._adapters = {adapter.id: adapter for adapter in configured}

    def discover(self, source_root: Path, source_type: str) -> list[SkillCandidate]:
        adapters = sorted(self._adapters.values(), key=lambda item: item.priority, reverse=True)
        candidates: list[SkillCandidate] = []
        occupied_paths: set[str] = set()
        for adapter in adapters:
            if isinstance(adapter, LocalSkillAdapter) and source_type != "local":
                continue
            if type(adapter) is StandardAgentSkillAdapter and source_type == "local":
                continue
            for candidate in adapter.discover(source_root):
                if candidate.relative_path in occupied_paths:
                    continue
                candidates.append(candidate)
                occupied_paths.add(candidate.relative_path)
        return sorted(candidates, key=lambda item: (item.name, item.relative_path))

    def get(self, adapter_id: str) -> SkillAdapter:
        try:
            return self._adapters[adapter_id]
        except KeyError as exc:
            raise ValueError(f'Unknown skill adapter "{adapter_id}"') from exc

    def load_instructions(
        self,
        skill: SkillRecord,
        source: SourceRecord,
        *,
        runtime_mode: str = "generic",
    ) -> str:
        return self.get(skill.adapter).load_instructions(skill, source, runtime_mode=runtime_mode)


__all__ = [
    "AdapterRegistry",
    "KSkillAdapter",
    "LocalSkillAdapter",
    "SkillAdapter",
    "StandardAgentSkillAdapter",
]
