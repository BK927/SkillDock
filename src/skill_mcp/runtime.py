from __future__ import annotations

import hashlib
import json
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
from .search import LexicalSearchProvider, SearchProvider
from .security import execute_script, read_asset
from .sources import MaterializedSource, SourceManager, source_identity_from_record


class SkillRuntime:
    def __init__(
        self,
        home: Path,
        *,
        adapters: AdapterRegistry | None = None,
        search_provider: SearchProvider | None = None,
        search_index: SearchProvider | None = None,
    ):
        if search_provider is not None and search_index is not None:
            raise ValueError("Pass search_provider or the legacy search_index, not both")
        self.home = ensure_home(home)
        self.registry = RegistryStore(self.home)
        self.adapters = adapters or AdapterRegistry()
        self.search_provider = search_provider or search_index or LexicalSearchProvider()
        # Compatibility for code that inspected the old runtime attribute.
        self.search_index = self.search_provider
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
        if hot or hot_selectors:
            raise ValueError(
                "Installation cannot change HOT state. Install first, review `skilldock list`, "
                "then make each user-selected skill HOT with `skilldock hot add <skill>`."
            )
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
                        status="active",
                        missing_since=None,
                        content_digest=self._candidate_digest(
                            candidate, source_record, materialized.path
                        ),
                        hot=old.hot if old else False,
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
            key=lambda item: (item.status != "active", not item.hot, item.name, item.id),
        )

    def list_sources(self) -> list[SourceRecord]:
        return sorted(self.registry.load().sources.values(), key=lambda item: item.id)

    def get_skill(self, selector: str) -> SkillRecord:
        return resolve_skill(self.registry.load(), selector)

    def load_skill(self, selector: str, *, runtime_mode: str = "generic") -> dict[str, Any]:
        state = self.registry.load()
        skill = resolve_skill(state, selector)
        self._ensure_available(skill)
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
            "status": skill.status,
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
            "provider": self.search_provider.id,
            "matches": self.search_provider.search(
                task, skills, limit=limit, include_hot=include_hot
            ),
        }

    def set_hot(self, selector: str, hot: bool) -> SkillRecord:
        def mutation(state: RegistryState) -> SkillRecord:
            skill = resolve_skill(state, selector)
            if hot:
                self._ensure_available(skill)
            skill.hot = hot
            skill.updated_at = _now()
            return skill

        return self.registry.update(mutation)

    def read_skill_asset(self, selector: str, path: str) -> dict[str, Any]:
        skill = self.get_skill(selector)
        self._ensure_available(skill)
        return read_asset(skill, path)

    def exec_skill_script(
        self,
        selector: str,
        script: str,
        args: list[str],
        *,
        timeout: float = 60,
    ) -> dict[str, Any]:
        skill = self.get_skill(selector)
        self._ensure_available(skill)
        return execute_script(skill, script, args, timeout=timeout)

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

    def reconcile(self, selector: str | None = None, *, apply: bool = False) -> dict[str, Any]:
        """Preview upstream changes, optionally applying safe record refreshes.

        Applying never installs newly discovered skills and never deletes missing records.
        """
        report, _ = self._reconcile_sources(selector, apply=apply)
        return report

    def update(self, selector: str | None = None) -> list[SourceRecord]:
        """Backward-compatible safe refresh (equivalent to reconcile --apply)."""
        _, updated = self._reconcile_sources(selector, apply=True)
        return updated

    def _reconcile_sources(
        self, selector: str | None, *, apply: bool
    ) -> tuple[dict[str, Any], list[SourceRecord]]:
        initial = self.registry.load()
        targets = (
            [resolve_source(initial, selector)] if selector else list(initial.sources.values())
        )
        updated: list[SourceRecord] = []
        source_reports: list[dict[str, Any]] = []
        for old_source in targets:
            identity = source_identity_from_record(
                old_source.id,
                old_source.source,
                old_source.normalized_source,
                old_source.source_type,
            )
            installed = [
                item for item in initial.skills.values() if item.source_id == old_source.id
            ]
            with self.sources.preview_refresh(identity) as preview:
                candidates = self.adapters.discover(preview.path, old_source.source_type)
                preview_source = _source_record_for_materialized(old_source, preview)
                report = self._build_reconciliation(
                    old_source, installed, candidates, preview_source, preview.path
                )
                source_reports.append(report)
                if not apply:
                    continue

                by_path = {candidate.relative_path: candidate for candidate in candidates}
                digests = {
                    candidate.relative_path: self._candidate_digest(
                        candidate, preview_source, preview.path
                    )
                    for candidate in candidates
                }
                materialized = self.sources.commit_preview(preview)
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
                            if skill.status != "missing":
                                skill.missing_since = now
                            skill.status = "missing"
                            skill.install_path = str(materialized.path / skill.relative_path)
                            skill.updated_at = now
                            continue
                        skill.name = candidate.name
                        skill.description = candidate.description
                        skill.adapter = candidate.adapter
                        skill.metadata = candidate.metadata
                        skill.install_path = str(materialized.path / candidate.relative_path)
                        skill.revision = materialized.revision
                        skill.status = "active"
                        skill.missing_since = None
                        skill.content_digest = digests[candidate.relative_path]
                        skill.updated_at = now
                    updated.append(current_source)

        totals = {
            key: sum(item["counts"][key] for item in source_reports)
            for key in ("new", "updated", "missing", "unchanged")
        }
        return (
            {
                "applied": apply,
                "sourceCount": len(source_reports),
                "totals": totals,
                "sources": source_reports,
            },
            updated,
        )

    def _build_reconciliation(
        self,
        source: SourceRecord,
        installed: list[SkillRecord],
        candidates: list[SkillCandidate],
        preview_source: SourceRecord,
        preview_root: Path,
    ) -> dict[str, Any]:
        installed_by_path = {skill.relative_path: skill for skill in installed}
        candidates_by_path = {candidate.relative_path: candidate for candidate in candidates}
        new = [
            _candidate_summary(candidate)
            for candidate in candidates
            if candidate.relative_path not in installed_by_path
        ]
        changed: list[dict[str, Any]] = []
        unchanged = 0
        for skill in installed:
            candidate = candidates_by_path.get(skill.relative_path)
            if not candidate:
                continue
            digest = self._candidate_digest(candidate, preview_source, preview_root)
            if (
                skill.status != "active"
                or skill.name != candidate.name
                or skill.description != candidate.description
                or skill.adapter != candidate.adapter
                or skill.metadata != candidate.metadata
                or skill.content_digest != digest
            ):
                changed.append(
                    {
                        "id": skill.id,
                        "name": candidate.name,
                        "path": candidate.relative_path,
                        "hot": skill.hot,
                    }
                )
            else:
                unchanged += 1
        missing = [
            {
                "id": skill.id,
                "name": skill.name,
                "path": skill.relative_path,
                "hot": skill.hot,
                "status": skill.status,
            }
            for skill in installed
            if skill.relative_path not in candidates_by_path
        ]
        return {
            "sourceId": source.id,
            "source": source.source,
            "fromRevision": source.revision,
            "toRevision": preview_source.revision,
            "counts": {
                "new": len(new),
                "updated": len(changed),
                "missing": len(missing),
                "unchanged": unchanged,
            },
            "new": new,
            "updated": changed,
            "missing": missing,
        }

    def _candidate_digest(
        self, candidate: SkillCandidate, source: SourceRecord, source_root: Path
    ) -> str:
        provisional = SkillRecord(
            id="preview",
            name=candidate.name,
            description=candidate.description,
            source_id=source.id,
            source=source.source,
            source_type=source.source_type,
            adapter=candidate.adapter,
            relative_path=candidate.relative_path,
            install_path=str(source_root / candidate.relative_path),
            revision=source.revision,
            metadata=candidate.metadata,
        )
        modes = ("generic", "dolshoi") if candidate.adapter == "k-skill" else ("generic",)
        rendered = [
            self.adapters.load_instructions(provisional, source, runtime_mode=mode)
            for mode in modes
        ]
        payload = json.dumps(
            {
                "name": candidate.name,
                "description": candidate.description,
                "metadata": candidate.metadata,
                "instructions": rendered,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _ensure_available(skill: SkillRecord) -> None:
        if skill.status == "missing":
            raise SkillNotFoundError(
                f'Skill "{skill.id}" is marked missing because it no longer exists upstream. '
                "Reconcile the source or uninstall the stale record."
            )
        if not Path(skill.install_path).is_dir():
            raise SkillNotFoundError(
                f'Installed files for skill "{skill.id}" are unavailable. '
                "Run `skilldock reconcile --apply` to refresh its source state."
            )


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


def _source_record_for_materialized(
    old: SourceRecord, materialized: MaterializedSource
) -> SourceRecord:
    return SourceRecord(
        id=old.id,
        source=old.source,
        normalized_source=old.normalized_source,
        source_type=old.source_type,
        install_path=str(materialized.path),
        revision=materialized.revision,
        installed_at=old.installed_at,
        updated_at=old.updated_at,
    )


def _candidate_summary(candidate: SkillCandidate) -> dict[str, Any]:
    return {
        "name": candidate.name,
        "description": candidate.description,
        "path": candidate.relative_path,
        "adapter": candidate.adapter,
    }


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
