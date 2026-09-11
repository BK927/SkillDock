from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from ..models import SkillCandidate, SkillRecord, SourceRecord
from .base import SkillAdapter, is_ignored_path

_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def parse_skill_markdown(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_text(encoding="utf-8-sig")
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    end = normalized.find("\n---\n", 4)
    if end < 0:
        raise ValueError("SKILL.md YAML frontmatter is not closed")
    metadata = yaml.safe_load(normalized[4:end]) or {}
    if not isinstance(metadata, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping")
    return metadata, normalized[end + 5 :].lstrip("\n")


def validate_metadata(metadata: dict[str, Any], directory: Path) -> tuple[str, str]:
    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not _NAME_PATTERN.fullmatch(name) or len(name) > 64:
        raise ValueError(f"invalid Agent Skill name in {directory / 'SKILL.md'}")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise ValueError(f"invalid Agent Skill description in {directory / 'SKILL.md'}")
    return name, description.strip()


class StandardAgentSkillAdapter(SkillAdapter):
    id = "standard-agent-skill"
    priority = 10

    def discover(self, source_root: Path) -> list[SkillCandidate]:
        candidates: list[SkillCandidate] = []
        for manifest in sorted(source_root.rglob("SKILL.md")):
            if not manifest.is_file() or is_ignored_path(manifest, source_root):
                continue
            directory = manifest.parent
            # k-skill roots are intentionally handled by the compatibility adapter.
            if (directory / "skill.json").is_file() and (directory / "instruction.md").is_file():
                continue
            try:
                metadata, _ = parse_skill_markdown(manifest)
                name, description = validate_metadata(metadata, directory)
            except (OSError, UnicodeError, ValueError, yaml.YAMLError):
                continue
            relative = directory.relative_to(source_root).as_posix() or "."
            candidates.append(
                SkillCandidate(
                    name=name,
                    description=description,
                    relative_path=relative,
                    adapter=self.id,
                    metadata=_json_safe(metadata),
                )
            )
        return candidates

    def load_instructions(
        self,
        skill: SkillRecord,
        source: SourceRecord,
        *,
        runtime_mode: str = "generic",
    ) -> str:
        del source, runtime_mode
        metadata, body = parse_skill_markdown(Path(skill.install_path) / "SKILL.md")
        validate_metadata(metadata, Path(skill.install_path))
        return body


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(item) for item in value]
    return str(value)
