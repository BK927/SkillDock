from __future__ import annotations

from skill_mcp.evaluation import evaluate_retrieval


def test_evaluation_reports_top_k_by_route_language_and_category(runtime, source_a, tmp_path):
    installed = runtime.install(str(source_a))
    by_name = {skill.name: skill for skill in installed}
    runtime.set_hot(by_name["frontend-design"].id, True)
    dataset = tmp_path / "queries.yaml"
    dataset.write_text(
        f"""\
name: test-set
queries:
  - id: hot-design
    query: accessible HTML interfaces
    expected: {by_name["frontend-design"].id}
    route: hot
    language: en
    category: direct
  - id: discover-debug
    query: methodically debug software with evidence
    expected: {by_name["systematic-debugging"].id}
    route: discovery
    language: en
    category: indirect
""",
        encoding="utf-8",
    )

    result = evaluate_retrieval(runtime, dataset, min_skills=2)

    assert result["provider"] == "lexical"
    assert result["corpus"]["hotCount"] == 1
    assert result["corpus"]["discoveryCount"] == 1
    assert result["corpus"]["revisionMismatches"] == []
    assert result["metrics"]["top1"] == 1.0
    assert result["byRoute"]["hot"]["count"] == 1
    assert result["byLanguage"]["en"]["count"] == 2
    assert result["byCategory"]["indirect"]["top5"] == 1.0
