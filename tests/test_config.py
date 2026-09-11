from __future__ import annotations

from skill_mcp.config import default_home


def test_default_home_uses_skilldock_name(monkeypatch, tmp_path):
    monkeypatch.delenv("SKILLDOCK_HOME", raising=False)
    monkeypatch.delenv("SKILL_MCP_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert default_home() == (tmp_path / "skilldock").resolve()


def test_new_home_environment_wins_but_legacy_environment_is_supported(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy"
    current = tmp_path / "current"
    monkeypatch.setenv("SKILL_MCP_HOME", str(legacy))
    assert default_home() == legacy.resolve()

    monkeypatch.setenv("SKILLDOCK_HOME", str(current))
    assert default_home() == current.resolve()


def test_existing_legacy_default_is_discovered_without_moving_state(monkeypatch, tmp_path):
    monkeypatch.delenv("SKILLDOCK_HOME", raising=False)
    monkeypatch.delenv("SKILL_MCP_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    legacy = tmp_path / "skill-mcp"
    legacy.mkdir()

    assert default_home() == legacy.resolve()

    (tmp_path / "skilldock").mkdir()
    assert default_home() == (tmp_path / "skilldock").resolve()
