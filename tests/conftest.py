from __future__ import annotations

from pathlib import Path

import pytest

from skill_mcp.runtime import SkillRuntime


def make_skill(
    source: Path,
    relative: str,
    name: str,
    description: str,
    body: str | None = None,
) -> Path:
    root = source / relative
    root.mkdir(parents=True, exist_ok=True)
    instructions = body or f"# {name}\n\nInstructions for {name}."
    (root / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "metadata:\n"
        "  category: test\n"
        "  tags: ui debug\n"
        "---\n\n"
        f"{instructions}\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def runtime(tmp_path: Path) -> SkillRuntime:
    return SkillRuntime(tmp_path / "home")


@pytest.fixture
def source_a(tmp_path: Path) -> Path:
    source = tmp_path / "source-a"
    make_skill(
        source,
        "frontend-design",
        "frontend-design",
        "Create polished React user interfaces and visual systems.",
    )
    debug = make_skill(
        source,
        "nested/systematic-debugging",
        "systematic-debugging",
        "Debug software methodically using evidence and hypothesis testing.",
    )
    (debug / "references").mkdir()
    (debug / "references" / "checklist.md").write_text("# Debug checklist\n", encoding="utf-8")
    (debug / "assets").mkdir()
    (debug / "assets" / "tiny.bin").write_bytes(b"\x00\x01\x02")
    (debug / "scripts").mkdir()
    (debug / "scripts" / "echo.py").write_text(
        "import sys\nprint('|'.join(sys.argv[1:]))\n", encoding="utf-8"
    )
    return source


@pytest.fixture
def source_b(tmp_path: Path) -> Path:
    source = tmp_path / "source-b"
    make_skill(
        source,
        "frontend-design",
        "frontend-design",
        "Create accessible HTML interfaces with a second design workflow.",
    )
    make_skill(
        source,
        "postgres-optimization",
        "postgres-optimization",
        "Optimize PostgreSQL queries, indexes, and database performance.",
    )
    return source
