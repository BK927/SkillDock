from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from conftest import make_skill

from skill_mcp.errors import AmbiguousSkillError, SecurityError, SkillNotFoundError
from skill_mcp.mcp_server import ToolFactory
from skill_mcp.runtime import SkillRuntime


def test_installs_multiple_standard_skills_from_one_local_repository(runtime, source_a):
    installed = runtime.install(str(source_a))

    assert {skill.name for skill in installed} == {"frontend-design", "systematic-debugging"}
    assert all(skill.adapter == "local-agent-skill" for skill in installed)
    assert len(runtime.list_sources()) == 1
    registry = json.loads((runtime.home / "registry.json").read_text(encoding="utf-8"))
    assert registry["schemaVersion"] == 1
    assert len(registry["skills"]) == 2


def test_two_sources_coexist_and_name_collision_requires_canonical_id(runtime, source_a, source_b):
    first = runtime.install(str(source_a))
    second = runtime.install(str(source_b))

    assert len(runtime.list_skills()) == 4
    frontend_ids = [skill.id for skill in [*first, *second] if skill.name == "frontend-design"]
    assert len(frontend_ids) == 2
    assert frontend_ids[0] != frontend_ids[1]
    with pytest.raises(AmbiguousSkillError, match="canonical IDs"):
        runtime.load_skill("frontend-design")
    assert runtime.load_skill(frontend_ids[0])["name"] == "frontend-design"


def test_only_hot_skills_become_individual_mcp_tools(runtime, source_a):
    installed = runtime.install(str(source_a), selectors=["frontend-design"], hot=True)
    runtime.install(str(source_a), selectors=["systematic-debugging"])

    tools = ToolFactory(runtime).build()
    assert installed[0].tool_name in tools
    assert runtime.get_skill("systematic-debugging").tool_name not in tools
    assert {
        "find_skills",
        "load_skill",
        "read_skill_asset",
        "list_installed_skills",
    } <= tools.keys()
    assert (
        "Instructions for frontend-design"
        in tools[installed[0].tool_name].handler({})["instructions"]
    )


def test_non_hot_skill_is_searchable_and_loadable(runtime, source_a):
    runtime.install(str(source_a), selectors=["frontend-design"], hot=True)
    runtime.install(str(source_a), selectors=["systematic-debugging"])

    result = runtime.find_skills("methodically debug software with evidence")
    assert result["matches"][0]["name"] == "systematic-debugging"
    assert all(not match["hot"] for match in result["matches"])
    assert (
        "Instructions for systematic-debugging"
        in runtime.load_skill("systematic-debugging")["instructions"]
    )


def test_hot_add_remove_is_persistent_across_runtime_restart(runtime, source_a):
    runtime.install(str(source_a), selectors=["systematic-debugging"])
    runtime.set_hot("systematic-debugging", True)

    restarted = SkillRuntime(runtime.home)
    assert restarted.get_skill("systematic-debugging").hot is True
    restarted.set_hot("systematic-debugging", False)
    assert SkillRuntime(runtime.home).get_skill("systematic-debugging").hot is False


def test_uninstall_removes_only_selected_skill(runtime, source_a):
    runtime.install(str(source_a), hot=True)
    removed = runtime.uninstall("frontend-design")

    assert removed.hot is True
    assert [skill.name for skill in runtime.list_skills()] == ["systematic-debugging"]


@pytest.mark.parametrize(
    "path",
    ["../../secret", "references/../../secret", "/etc/passwd", "C:\\Windows\\win.ini", "SKILL.md"],
)
def test_asset_path_traversal_and_unapproved_roots_are_blocked(runtime, source_a, path):
    runtime.install(str(source_a))
    with pytest.raises(SecurityError):
        runtime.read_skill_asset("systematic-debugging", path)


def test_reads_text_and_binary_assets_with_explicit_encoding(runtime, source_a):
    runtime.install(str(source_a))

    text = runtime.read_skill_asset("systematic-debugging", "references/checklist.md")
    binary = runtime.read_skill_asset("systematic-debugging", "assets/tiny.bin")
    assert text["encoding"] == "utf-8"
    assert text["content"] == "# Debug checklist\n"
    assert binary["encoding"] == "base64"
    assert binary["content"] == "AAEC"


def test_script_execution_requires_explicit_install_trust(runtime, source_a):
    runtime.install(str(source_a), selectors=["systematic-debugging"])
    with pytest.raises(SecurityError, match="not trusted"):
        runtime.exec_skill_script("systematic-debugging", "scripts/echo.py", ["a", "b"])

    trusted_home = runtime.home.parent / "trusted-home"
    trusted = SkillRuntime(trusted_home)
    trusted.install(str(source_a), selectors=["systematic-debugging"], allow_scripts=True)
    result = trusted.exec_skill_script("systematic-debugging", "scripts/echo.py", ["a", "b"])
    assert result["exitCode"] == 0
    assert result["stdout"].strip() == "a|b"


def test_removing_source_does_not_affect_other_source(runtime, source_a, source_b):
    first = runtime.install(str(source_a))
    second = runtime.install(str(source_b))

    removed_source, removed_skills = runtime.remove_source(first[0].source_id)
    assert removed_source.id == first[0].source_id
    assert {skill.id for skill in removed_skills} == {skill.id for skill in first}
    assert {skill.id for skill in runtime.list_skills()} == {skill.id for skill in second}
    assert Path(runtime.list_sources()[0].install_path).exists()


def test_local_source_update_refreshes_metadata_but_preserves_hot(runtime, tmp_path):
    source = tmp_path / "updatable"
    make_skill(source, "weather", "weather", "Find today's local weather.", "# Before")
    runtime.install(str(source), hot=True)
    make_skill(source, "weather", "weather", "Find forecasts and severe weather.", "# After")

    runtime.update()
    skill = runtime.get_skill("weather")
    assert skill.hot is True
    assert skill.description == "Find forecasts and severe weather."
    assert "# After" in runtime.load_skill("weather")["instructions"]


def test_installing_specific_skill_does_not_install_every_discovered_skill(runtime, source_a):
    installed = runtime.install(str(source_a), selectors=["nested/systematic-debugging"])
    assert [skill.name for skill in installed] == ["systematic-debugging"]
    assert [skill.name for skill in runtime.list_skills()] == ["systematic-debugging"]


def test_install_all_can_select_only_a_hot_subset(runtime, source_a):
    installed = runtime.install(str(source_a), hot_selectors=["frontend-design"])

    assert len(installed) == 2
    assert {skill.name for skill in installed if skill.hot} == {"frontend-design"}


def test_reconcile_previews_then_applies_new_updated_and_missing_without_choice_mutation(
    runtime, source_a
):
    runtime.install(str(source_a), hot_selectors=["frontend-design"])
    make_skill(
        source_a,
        "nested/systematic-debugging",
        "systematic-debugging",
        "Diagnose failures with a revised evidence workflow.",
        "# Revised debugging",
    )
    make_skill(source_a, "new-capability", "new-capability", "A newly published capability.")
    shutil.rmtree(source_a / "frontend-design")

    preview = runtime.reconcile()
    assert preview["applied"] is False
    assert preview["totals"] == {"new": 1, "updated": 1, "missing": 1, "unchanged": 0}
    assert runtime.get_skill("frontend-design").status == "active"
    assert len(runtime.list_skills()) == 2

    applied = runtime.reconcile(apply=True)
    assert applied["applied"] is True
    assert len(runtime.list_skills()) == 2
    missing = runtime.get_skill("frontend-design")
    assert missing.status == "missing"
    assert missing.hot is True
    assert missing.missing_since
    assert missing.tool_name not in ToolFactory(runtime).build()
    with pytest.raises(SkillNotFoundError, match="marked missing"):
        runtime.load_skill(missing.id)
    assert runtime.get_skill("systematic-debugging").status == "active"
    assert "# Revised debugging" in runtime.load_skill("systematic-debugging")["instructions"]
    with pytest.raises(SkillNotFoundError, match="not installed"):
        runtime.get_skill("new-capability")
