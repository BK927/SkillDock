from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class SkillCandidate:
    name: str
    description: str
    relative_path: str
    adapter: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SourceRecord:
    id: str
    source: str
    normalized_source: str
    source_type: str
    install_path: str
    revision: str | None
    installed_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SourceRecord:
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SkillRecord:
    id: str
    name: str
    description: str
    source_id: str
    source: str
    source_type: str
    adapter: str
    relative_path: str
    install_path: str
    revision: str | None
    status: str = "active"
    missing_since: str | None = None
    content_digest: str = ""
    hot: bool = False
    trusted: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_name: str = ""
    installed_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SkillRecord:
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RegistryState:
    schema_version: int = 1
    sources: dict[str, SourceRecord] = field(default_factory=dict)
    skills: dict[str, SkillRecord] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RegistryState:
        return cls(
            schema_version=int(value.get("schemaVersion", 1)),
            sources={
                key: SourceRecord.from_dict(item) for key, item in value.get("sources", {}).items()
            },
            skills={
                key: SkillRecord.from_dict(item) for key, item in value.get("skills", {}).items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "sources": {key: value.to_dict() for key, value in sorted(self.sources.items())},
            "skills": {key: value.to_dict() for key, value in sorted(self.skills.items())},
        }
