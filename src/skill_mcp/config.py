from __future__ import annotations

import os
from pathlib import Path


def default_home() -> Path:
    """Return the runtime state directory, honoring explicit configuration first."""
    configured = os.environ.get("SKILLDOCK_HOME") or os.environ.get("SKILL_MCP_HOME")
    if configured:
        return Path(configured).expanduser().resolve()

    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config).expanduser() if xdg_config else Path.home() / ".config"
    preferred = (base / "skilldock").resolve()
    legacy = (base / "skill-mcp").resolve()
    if not preferred.exists() and legacy.exists():
        return legacy
    return preferred


def ensure_home(home: Path) -> Path:
    home = home.expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    (home / "sources").mkdir(exist_ok=True)
    (home / "staging").mkdir(exist_ok=True)
    return home
