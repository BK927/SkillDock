from __future__ import annotations

import pytest

from skill_mcp.cli import build_parser, dispatch


@pytest.mark.parametrize(
    "legacy_args",
    [
        ["--hot"],
        ["--hot-skill", "frontend-design"],
    ],
)
def test_install_time_hot_options_fail_with_user_selection_guidance(runtime, source_a, legacy_args):
    args = build_parser().parse_args(["install", str(source_a), *legacy_args])

    with pytest.raises(ValueError, match="explicitly selected by the user"):
        dispatch(runtime, args)
    assert runtime.list_skills() == []
