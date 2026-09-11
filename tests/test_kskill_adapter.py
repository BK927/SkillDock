from __future__ import annotations

import json
from pathlib import Path


def test_kskill_adapter_assembles_profiles_and_mode_specific_instructions(runtime, tmp_path: Path):
    source = tmp_path / "k-skill"
    skill = source / "korea-weather"
    skill.mkdir(parents=True)
    (skill / "skill.json").write_text(
        json.dumps(
            {
                "name": "korea-weather",
                "description": "Look up weather in Korea.",
                "profiles": ["lookup"],
                "frontmatter": "name: korea-weather\ndescription: Look up weather in Korea.\n",
            }
        ),
        encoding="utf-8",
    )
    (skill / "instruction.md").write_text(
        "Always here\n<!-- mode:generic -->\nGeneric workflow\n"
        "<!-- mode:dolshoi -->\nDolshoi workflow\n",
        encoding="utf-8",
    )
    templates = source / "packages" / "k-skill-cli" / "templates"
    templates.mkdir(parents=True)
    (templates / "core.md").write_text("Core rules", encoding="utf-8")
    (templates / "lookup.md").write_text(
        "Lookup always\n<!-- mode:generic -->\nGeneric lookup\n"
        "<!-- mode:dolshoi -->\nDolshoi lookup\n",
        encoding="utf-8",
    )
    # Generated adapter stubs must not win over the specialized adapter.
    (skill / "SKILL.md").write_text(
        "---\nname: korea-weather\ndescription: Stub.\n---\nRun npx k-skill.",
        encoding="utf-8",
    )

    installed = runtime.install(str(source))
    assert installed[0].adapter == "k-skill"
    generic = runtime.load_skill("korea-weather")["instructions"]
    dolshoi = runtime.load_skill("korea-weather", runtime_mode="dolshoi")["instructions"]
    assert "Core rules" in generic
    assert "Generic lookup" in generic
    assert "Generic workflow" in generic
    assert "Dolshoi workflow" not in generic
    assert "Dolshoi lookup" in dolshoi
    assert "Generic workflow" not in dolshoi


def test_k_adapter_is_optional_and_standard_runtime_still_works(runtime, source_a):
    installed = runtime.install(str(source_a))
    assert installed
    assert all(skill.adapter != "k-skill" for skill in installed)
