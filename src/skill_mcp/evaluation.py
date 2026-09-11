from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .runtime import SkillRuntime


def evaluate_retrieval(
    runtime: SkillRuntime,
    dataset_path: Path,
    *,
    min_skills: int = 0,
) -> dict[str, Any]:
    """Evaluate top-k discovery against a versioned natural-language query set."""
    raw = dataset_path.read_bytes()
    loaded = yaml.safe_load(raw.decode("utf-8-sig")) or {}
    queries = loaded.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("Evaluation dataset must contain a non-empty queries list")

    skills = [skill for skill in runtime.list_skills() if skill.status == "active"]
    if len(skills) < min_skills:
        raise ValueError(
            f"Evaluation requires at least {min_skills} active skills; found {len(skills)}"
        )
    skill_by_id = {skill.id: skill for skill in skills}
    results: list[dict[str, Any]] = []
    for index, item in enumerate(queries, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Query #{index} must be a mapping")
        query_id = str(item.get("id") or f"query-{index}")
        task = item.get("query")
        expected = item.get("expected")
        if not isinstance(task, str) or not task.strip():
            raise ValueError(f"{query_id}: query must be a non-empty string")
        if isinstance(expected, str):
            expected_ids = [expected]
        elif isinstance(expected, list) and all(isinstance(value, str) for value in expected):
            expected_ids = expected
        else:
            raise ValueError(f"{query_id}: expected must be a skill ID or list of skill IDs")
        unknown = [skill_id for skill_id in expected_ids if skill_id not in skill_by_id]
        if unknown:
            raise ValueError(f"{query_id}: expected skills are not active: {', '.join(unknown)}")

        route = str(item.get("route", "discovery"))
        if route not in {"discovery", "hot"}:
            raise ValueError(f'{query_id}: route must be "discovery" or "hot"')
        if route == "hot":
            wrong_tier = [skill_id for skill_id in expected_ids if not skill_by_id[skill_id].hot]
            if wrong_tier:
                raise ValueError(
                    f"{query_id}: HOT expectations are not marked HOT: {', '.join(wrong_tier)}"
                )
            candidates = [skill for skill in skills if skill.hot]
            include_hot = True
        else:
            wrong_tier = [skill_id for skill_id in expected_ids if skill_by_id[skill_id].hot]
            if wrong_tier:
                raise ValueError(
                    f"{query_id}: discovery expectations are HOT: {', '.join(wrong_tier)}"
                )
            candidates = skills
            include_hot = False

        ranked = runtime.search_provider.search(task, candidates, limit=5, include_hot=include_hot)
        ranked_ids = [str(match["id"]) for match in ranked]
        ranks = [
            ranked_ids.index(skill_id) + 1 for skill_id in expected_ids if skill_id in ranked_ids
        ]
        best_rank = min(ranks) if ranks else None
        results.append(
            {
                "id": query_id,
                "query": task,
                "expected": expected_ids,
                "route": route,
                "language": str(item.get("language", "unspecified")),
                "category": str(item.get("category", "unspecified")),
                "rank": best_rank,
                "hits": {f"top{k}": best_rank is not None and best_rank <= k for k in (1, 3, 5)},
                "top5": [
                    {
                        "id": match["id"],
                        "name": match["name"],
                        "score": match["score"],
                    }
                    for match in ranked
                ],
            }
        )

    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_language: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_route: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        by_category[result["category"]].append(result)
        by_language[result["language"]].append(result)
        by_route[result["route"]].append(result)

    sources = runtime.list_sources()
    declared_revisions = loaded.get("sourceRevisions") or {}
    if not isinstance(declared_revisions, dict):
        raise ValueError("sourceRevisions must be a mapping when provided")
    revision_mismatches = [
        {
            "id": source.id,
            "expected": str(declared_revisions[source.id]),
            "actual": source.revision,
        }
        for source in sources
        if source.id in declared_revisions and str(declared_revisions[source.id]) != source.revision
    ]
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "dataset": {
            "name": str(loaded.get("name", dataset_path.stem)),
            "path": dataset_path.as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "queryCount": len(results),
        },
        "provider": runtime.search_provider.id,
        "corpus": {
            "activeSkillCount": len(skills),
            "hotCount": sum(skill.hot for skill in skills),
            "discoveryCount": sum(not skill.hot for skill in skills),
            "sources": [
                {"id": source.id, "source": source.source, "revision": source.revision}
                for source in sources
            ],
            "revisionMismatches": revision_mismatches,
        },
        "metrics": _metrics(results),
        "byRoute": {key: _metrics(value) for key, value in sorted(by_route.items())},
        "byLanguage": {key: _metrics(value) for key, value in sorted(by_language.items())},
        "byCategory": {key: _metrics(value) for key, value in sorted(by_category.items())},
        "results": results,
    }


def write_evaluation(result: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(results)
    if not count:
        return {"count": 0, "top1": 0.0, "top3": 0.0, "top5": 0.0, "mrrAt5": 0.0}
    return {
        "count": count,
        **{
            f"top{k}": round(sum(bool(result["hits"][f"top{k}"]) for result in results) / count, 4)
            for k in (1, 3, 5)
        },
        "mrrAt5": round(
            sum(1 / result["rank"] for result in results if result["rank"] is not None) / count,
            4,
        ),
    }
