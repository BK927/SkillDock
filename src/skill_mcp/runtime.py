from __future__ import annotations

import hashlib
import re
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .adapters import AdapterRegistry
from .config import ensure_home
from .errors import DiscoveryError, RegistryError, SkillNotFoundError
from .models import RegistryState, SkillCandidate, SkillRecord, SourceRecord
from .registry import RegistryStore, resolve_skill, resolve_source
from .search import LexicalSearchIndex
from .security import execute_script, read_asset
from .sources import MaterializedSource, SourceManager, source_identity_from_record


class SkillRuntime:
    def __init__(
        self,
        home: Path,
        *,
        adapters: AdapterRegistry | None = None,
        search_index: LexicalSearchIndex | None = None,
    ):
        self.home = ensure_home(home)
        self.registry = RegistryStore(self.home)
        self.adapters = adapters or AdapterRegistry()
        self.search_index = search_index or LexicalSearchIndex()
        self.sources = SourceManager(self.home)

    def discover_source(self, source: str, *, ref: str | None = None) -> list[SkillCandidate]:
        """Acquire a new source and discover it, leaving it managed for install()."""
        identity = self.sources.identify(source)
        state = self.registry.load()
        existing = state.sources.get(identity.id)
        if existing:
            return self.adapters.discover(Path(existing.install_path), existing.source_type)
        materialized = self.sources.acquire(source, ref=ref)
        try:
            candidates = self.adapters.discover(materialized.path, identity.source_type)
            if not candidates:
                raise DiscoveryError(f'No compatible Agent Skills found in source "{source}"')
            return candidates
        except Exception:
            self.sources.remove_materialized(materialized.path)
            raise

    def install(
        self,
        source: str,
        *,
        selectors: list[str] | None = None,
        hot: bool = False,
        hot_selectors: list[str] | None = None,
        allow_scripts: bool = False,
        ref: str | None = None,
    ) -> list[SkillRecord]:
        identity = self.sources.identify(source)
        state = self.registry.load()
        existing_source = state.sources.get(identity.id)
        newly_materialized = existing_source is None
        if existing_source:
            materialized = MaterializedSource(
                identity=identity,
                path=Path(existing_source.install_path),
                revision=existing_source.revision,
            )
        else:
            materialized = self.sources.acquire(source, ref=ref)

        try:
            candidates = self.adapters.discover(materialized.path, identity.source_type)
            if not candidates:
                raise DiscoveryError(f'No compatible Agent Skills found in source "{source}"')
            selected = _select_candidates(candidates, selectors)
            selected_hot_paths = (
                {
                    candidate.relative_path
                    for candidate in _select_candidates(selected, hot_selectors)
                }
                if hot_selectors
                else set()
            )
            now = _now()
            source_record = SourceRecord(
                id=identity.id,
                source=identity.original,
                normalized_source=identity.normalized,
                source_type=identity.source_type,
                install_path=str(materialized.path),
                revision=materialized.revision,
                installed_at=existing_source.installed_at if existing_source else now,
                updated_at=now,
            )

            installed: list[SkillRecord] = []
            with self.registry.transaction() as current:
                current.sources[identity.id] = source_record
                for candidate in selected:
                    canonical_id = _canonical_id(identity.id, candidate)
                    old = current.skills.get(canonical_id)
                    record = SkillRecord(
                        id=canonical_id,
                        name=candidate.name,
                        description=candidate.description,
                        source_id=identity.id,
                        source=identity.original,
                        source_type=identity.source_type,
                        adapter=candidate.adapter,
                        relative_path=candidate.relative_path,
                        install_path=str(materialized.path / candidate.relative_path),
                        revision=materialized.revision,
                        hot=(
                            hot
                            or candidate.relative_path in selected_hot_paths
                            or (old.hot if old else False)
                        ),
                        trusted=allow_scripts or (old.trusted if old else False),
                        metadata=candidate.metadata,
                        tool_name=old.tool_name
                        if old
                        else _allocate_tool_name(candidate.name, current),
                        installed_at=old.installed_at if old else now,
                        updated_at=now,
                    )
                    current.skills[canonical_id] = record
                    installed.append(record)
            return installed
        except Exception:
            if newly_materialized and materialized.path.exists():
                with suppress(OSError):
                    self.sources.remove_materialized(materialized.path)
            raise

    def list_skills(self) -> list[SkillRecord]:
        return sorted(
            self.registry.load().skills.values(),
            key=lambda item: (not item.hot, item.name, item.id),
        )

    def list_sources(self) -> list[SourceRecord]:
        return sorted(self.registry.load().sources.values(), key=lambda item: item.id)

    def get_skill(self, selector: str) -> SkillRecord:
        return resolve_skill(self.registry.load(), selector)

    def load_skill(self, selector: str, *, runtime_mode: str = "generic") -> dict[str, Any]:
        state = self.registry.load()
        skill = resolve_skill(state, selector)
        source = state.sources.get(skill.source_id)
        if source is None:
            raise RegistryError(f'Source record "{skill.source_id}" is missing')
        instructions = self.adapters.load_instructions(skill, source, runtime_mode=runtime_mode)
        return {
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "source": skill.source,
            "adapter": skill.adapter,
            "hot": skill.hot,
            "instructions": instructions,
        }

    def find_skills(
        self,
        task: str,
        *,
        limit: int = 5,
        include_hot: bool = False,
    ) -> dict[str, Any]:
        skills = list(self.registry.load().skills.values())
        return {
            "task": task,
            "matches": self.search_index.search(task, skills, limit=limit, include_hot=include_hot),
        }

    def set_hot(self, selector: str, hot: bool) -> SkillRecord:
        def mutation(state: RegistryState) -> SkillRecord:
            skill = resolve_skill(state, selector)
            skill.hot = hot
            skill.updated_at = _now()
            return skill

        return self.registry.update(mutation)

    def read_skill_asset(self, selector: str, path: str) -> dict[str, Any]:
        return read_asset(self.get_skill(selector), path)

    def exec_skill_script(
        self,
        selector: str,
        script: str,
        args: list[str],
        *,
        timeout: float = 60,
    ) -> dict[str, Any]:
        return execute_script(self.get_skill(selector), script, args, timeout=timeout)

    def uninstall(self, selector: str) -> SkillRecord:
        def mutation(state: RegistryState) -> SkillRecord:
            skill = resolve_skill(state, selector)
            del state.skills[skill.id]
            return skill

        return self.registry.update(mutation)

    def remove_source(self, selector: str) -> tuple[SourceRecord, list[SkillRecord]]:
        state = self.registry.load()
        source = resolve_source(state, selector)
        removed = [skill for skill in state.skills.values() if skill.source_id == source.id]
        self.sources.remove_materialized(Path(source.install_path))

        def mutation(current: RegistryState) -> None:
            current.sources.pop(source.id, None)
            for skill in removed:
                current.skills.pop(skill.id, None)

        self.registry.update(mutation)
        return source, removed

    def update(self, selector: str | None = None) -> list[SourceRecord]:
        initial = self.registry.load()
        targets = (
            [resolve_source(initial, selector)] if selector else list(initial.sources.values())
        )
        updated: list[SourceRecord] = []
        for old_source in targets:
            identity = source_identity_from_record(
                old_source.id,
                old_source.source,
                old_source.normalized_source,
                old_source.source_type,
            )
            materialized = self.sources.refresh(identity)
            candidates = self.adapters.discover(materialized.path, old_source.source_type)
            by_path = {candidate.relative_path: candidate for candidate in candidates}
            now = _now()

            with self.registry.transaction() as state:
                current_source = state.sources[old_source.id]
                current_source.install_path = str(materialized.path)
                current_source.revision = materialized.revision
                current_source.updated_at = now
                for skill in [
                    item for item in state.skills.values() if item.source_id == old_source.id
                ]:
                    candidate = by_path.get(skill.relative_path)
                    if not candidate:
                        continue
                    skill.name = candidate.name
                    skill.description = candidate.description
                    skill.adapter = candidate.adapter
                    skill.metadata = candidate.metadata
                    skill.install_path = str(materialized.path / candidate.relative_path)
                    skill.revision = materialized.revision
                    skill.updated_at = now
                updated.append(current_source)
        return updated


def _select_candidates(
    candidates: list[SkillCandidate], selectors: list[str] | None
) -> list[SkillCandidate]:
    if not selectors:
        return candidates
    selected: list[SkillCandidate] = []
    for selector in selectors:
        matches = [
            item
            for item in candidates
            if selector in {item.name, item.relative_path, f"{item.adapter}:{item.relative_path}"}
        ]
        if not matches:
            available = ", ".join(item.name for item in candidates[:20])
            raise SkillNotFoundError(
                f'Skill "{selector}" was not found in the source. Available: {available}'
            )
        if len(matches) > 1:
            choices = ", ".join(item.relative_path for item in matches)
            raise SkillNotFoundError(
                f'Skill selector "{selector}" matches multiple paths; use one of: {choices}'
            )
        if matches[0] not in selected:
            selected.append(matches[0])
    return selected


def _canonical_id(source_id: str, candidate: SkillCandidate) -> str:
    suffix = candidate.relative_path.strip("./") or candidate.name
    return f"{source_id}/{suffix}"


def _allocate_tool_name(name: str, state: RegistryState) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.replace("-", "_")).strip("_")
    normalized = normalized or "skill"
    base = f"skill__{normalized}"[:128]
    used = {skill.tool_name for skill in state.skills.values()}
    if base not in used:
        return base
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    candidate = f"{base[:119]}__{digest}"
    counter = 2
    while candidate in used:
        candidate = f"{base[:115]}__{digest}_{counter}"
        counter += 1
    return candidate


def _now() -> str:
    return datetime.now(UTC).isoformat()
