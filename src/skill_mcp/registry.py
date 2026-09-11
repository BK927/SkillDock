from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

from .errors import AmbiguousSkillError, RegistryError, SkillNotFoundError
from .models import RegistryState, SkillRecord, SourceRecord

T = TypeVar("T")


class RegistryStore:
    """Atomic JSON persistence for installed sources, skills, trust, and HOT state."""

    def __init__(self, home: Path):
        self.home = home
        self.path = home / "registry.json"
        self._thread_lock = threading.RLock()

    def load(self) -> RegistryState:
        with self._thread_lock:
            if not self.path.exists():
                return RegistryState()
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                return RegistryState.from_dict(raw)
            except (OSError, ValueError, TypeError) as exc:
                raise RegistryError(f"Cannot read registry {self.path}: {exc}") from exc

    def save(self, state: RegistryState) -> None:
        with self._thread_lock:
            self.home.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
            payload = json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n"
            try:
                temporary.write_text(payload, encoding="utf-8")
                os.replace(temporary, self.path)
            except OSError as exc:
                temporary.unlink(missing_ok=True)
                raise RegistryError(f"Cannot save registry {self.path}: {exc}") from exc

    def update(self, mutation: Callable[[RegistryState], T]) -> T:
        with self._thread_lock:
            state = self.load()
            result = mutation(state)
            self.save(state)
            return result

    @contextmanager
    def transaction(self) -> Iterator[RegistryState]:
        with self._thread_lock:
            state = self.load()
            yield state
            self.save(state)

    def fingerprint(self) -> tuple[int, int]:
        try:
            stat = self.path.stat()
            return stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            return 0, 0


def resolve_skill(state: RegistryState, selector: str) -> SkillRecord:
    if selector in state.skills:
        return state.skills[selector]

    by_tool = [skill for skill in state.skills.values() if skill.tool_name == selector]
    if len(by_tool) == 1:
        return by_tool[0]

    by_name = [skill for skill in state.skills.values() if skill.name == selector]
    if not by_name:
        folded = selector.casefold()
        by_name = [skill for skill in state.skills.values() if skill.name.casefold() == folded]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        choices = ", ".join(sorted(skill.id for skill in by_name))
        raise AmbiguousSkillError(
            f'Skill name "{selector}" is ambiguous; use one of these canonical IDs: {choices}'
        )
    raise SkillNotFoundError(f'Skill "{selector}" is not installed')


def resolve_source(state: RegistryState, selector: str) -> SourceRecord:
    if selector in state.sources:
        return state.sources[selector]
    folded = selector.rstrip("/\\").removesuffix(".git").casefold()
    matches = [
        source
        for source in state.sources.values()
        if source.source.rstrip("/\\").removesuffix(".git").casefold() == folded
        or source.normalized_source.rstrip("/\\").removesuffix(".git").casefold() == folded
        or source.id.casefold().endswith(folded)
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        choices = ", ".join(sorted(source.id for source in matches))
        raise RegistryError(f'Source "{selector}" is ambiguous; use one of: {choices}')
    raise RegistryError(f'Source "{selector}" is not installed')
