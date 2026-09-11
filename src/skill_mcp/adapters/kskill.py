from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from ..models import SkillCandidate, SkillRecord, SourceRecord
from .base import SkillAdapter, is_ignored_path
from .standard import _json_safe, validate_metadata

_MODE_MARKER = re.compile(r"^<!-- mode:(always|dolshoi|generic) -->$")


class KSkillAdapter(SkillAdapter):
    """Optional compatibility adapter for NomaDamas/k-skill style repositories."""

    id = "k-skill"
    priority = 100

    def discover(self, source_root: Path) -> list[SkillCandidate]:
        candidates: list[SkillCandidate] = []
        for manifest_path in sorted(source_root.rglob("skill.json")):
            directory = manifest_path.parent
            if is_ignored_path(manifest_path, source_root):
                continue
            relative = directory.relative_to(source_root)
            relative_posix = relative.as_posix()
            if relative_posix.startswith("packages/k-skill-cli/skills/"):
                continue
            instruction_path = directory / "instruction.md"
            if not instruction_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                frontmatter = _frontmatter_from_manifest(manifest)
                merged: dict[str, Any] = {**frontmatter, **manifest}
                merged.pop("frontmatter", None)
                name, description = validate_metadata(merged, directory)
            except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
                continue
            candidates.append(
                SkillCandidate(
                    name=name,
                    description=description,
                    relative_path=relative_posix or ".",
                    adapter=self.id,
                    metadata=_json_safe(merged),
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
        if runtime_mode not in {"generic", "dolshoi"}:
            raise ValueError('runtime_mode must be "generic" or "dolshoi"')
        skill_root = Path(skill.install_path)
        manifest = json.loads((skill_root / "skill.json").read_text(encoding="utf-8-sig"))
        instruction = (skill_root / "instruction.md").read_text(encoding="utf-8-sig")
        profiles = ["core", *[p for p in manifest.get("profiles", []) if p != "core"]]
        template_root = Path(source.install_path) / "packages" / "k-skill-cli" / "templates"
        blocks: list[str] = []
        for profile in profiles:
            template = template_root / f"{str(profile).replace(':', '-')}.md"
            if template.is_file():
                rendered = render_mode(template.read_text(encoding="utf-8-sig"), runtime_mode)
                if rendered:
                    blocks.append(rendered)

        header = [
            f"# {skill.name} — assembled instructions",
            "",
            f"Runtime mode: {runtime_mode}",
        ]
        if blocks:
            header.extend(["", "## Runtime rules", "", "\n".join(blocks)])

        resource_note = _resource_note(skill_root)
        rendered_instruction = render_mode(instruction, runtime_mode)
        return "\n".join(header + ["", resource_note, rendered_instruction]).strip() + "\n"


def _frontmatter_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    frontmatter = manifest.get("frontmatter", {})
    if isinstance(frontmatter, dict):
        return frontmatter
    if isinstance(frontmatter, str):
        loaded = yaml.safe_load(frontmatter) or {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def render_mode(raw: str, mode: str) -> str:
    output: list[str] = []
    current = "always"
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        marker = _MODE_MARKER.fullmatch(line)
        if marker:
            current = marker.group(1)
            continue
        if current in {"always", mode}:
            output.append(line)
    return "\n".join(output).strip()


def _resource_note(skill_root: Path) -> str:
    roots = [name for name in ("references", "assets", "scripts") if (skill_root / name).is_dir()]
    if not roots:
        return ""
    return (
        "## Bundled resource access\n\n"
        "Use the MCP `read_skill_asset` tool for files under "
        + ", ".join(f"`{name}/`" for name in roots)
        + ". Scripts are not implicitly trusted or executed by loading this skill.\n"
    )
