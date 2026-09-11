from __future__ import annotations

from .standard import StandardAgentSkillAdapter


class LocalSkillAdapter(StandardAgentSkillAdapter):
    """Named extension point for local SKILL.md sources.

    Acquisition is deliberately separate from content parsing; local skills use the
    standard format unless a higher-priority content adapter recognizes them.
    """

    id = "local-agent-skill"
