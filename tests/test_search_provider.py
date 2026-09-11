from __future__ import annotations

from skill_mcp.runtime import SkillRuntime
from skill_mcp.search import SearchProvider


class RecordingSearchProvider(SearchProvider):
    id = "recording"

    def __init__(self):
        self.tasks: list[str] = []

    def search(self, task, skills, *, limit=5, include_hot=False):
        self.tasks.append(task)
        return [
            {
                "id": skills[0].id,
                "name": skills[0].name,
                "description": skills[0].description,
                "source": skills[0].source,
                "hot": skills[0].hot,
                "status": skills[0].status,
                "score": 1.0,
            }
        ]


def test_runtime_uses_injected_search_provider(tmp_path, source_a):
    provider = RecordingSearchProvider()
    runtime = SkillRuntime(tmp_path / "custom-search", search_provider=provider)
    runtime.install(str(source_a), selectors=["systematic-debugging"])

    result = runtime.find_skills("find the right workflow")

    assert result["provider"] == "recording"
    assert result["matches"][0]["name"] == "systematic-debugging"
    assert provider.tasks == ["find the right workflow"]


def test_legacy_search_index_parameter_remains_supported(tmp_path, source_a):
    provider = RecordingSearchProvider()
    runtime = SkillRuntime(tmp_path / "legacy-search", search_index=provider)
    runtime.install(str(source_a), selectors=["systematic-debugging"])

    assert runtime.find_skills("debug")["provider"] == "recording"
