from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from .models import SkillRecord

_TOKEN = re.compile(r"[\w-]+", re.UNICODE)


class LexicalSearchIndex:
    """Dependency-free search interface that can later be replaced by a semantic index."""

    def search(
        self,
        task: str,
        skills: list[SkillRecord],
        *,
        limit: int = 5,
        include_hot: bool = False,
    ) -> list[dict[str, object]]:
        query = task.strip().casefold()
        if not query:
            return []
        query_tokens = set(_TOKEN.findall(query))
        ranked: list[tuple[float, SkillRecord]] = []
        for skill in skills:
            if skill.hot and not include_hot:
                continue
            fields = " ".join(
                [
                    skill.name,
                    skill.description,
                    skill.source,
                    json.dumps(skill.metadata, ensure_ascii=False, sort_keys=True),
                ]
            ).casefold()
            field_tokens = set(_TOKEN.findall(fields))
            overlap = len(query_tokens & field_tokens) / max(len(query_tokens), 1)
            name_ratio = SequenceMatcher(None, query, skill.name.casefold()).ratio()
            description_ratio = SequenceMatcher(None, query, skill.description.casefold()).ratio()
            substring = 1.0 if query in fields else 0.0
            prefix_hits = sum(
                1 for token in query_tokens if any(item.startswith(token) for item in field_tokens)
            ) / max(len(query_tokens), 1)
            score = 0.50 * overlap + 0.20 * substring + 0.15 * name_ratio
            score += 0.10 * description_ratio + 0.05 * prefix_hits
            if score > 0:
                ranked.append((min(score, 1.0), skill))
        ranked.sort(key=lambda item: (-item[0], item[1].name, item[1].id))
        return [
            {
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "source": skill.source,
                "hot": skill.hot,
                "score": round(score, 4),
            }
            for score, skill in ranked[: max(1, min(limit, 100))]
        ]
