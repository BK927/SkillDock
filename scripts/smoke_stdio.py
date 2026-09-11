"""Run a real JSON-RPC initialize/list/call exchange against SkillDock stdio."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def request(
    process: subprocess.Popen[str], request_id: int, method: str, params: dict[str, Any]
) -> dict[str, Any]:
    assert process.stdin is not None
    assert process.stdout is not None
    message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()
    while line := process.stdout.readline():
        response = json.loads(line)
        if response.get("id") == request_id:
            return response
    detail = process.stderr.read() if process.stderr else ""
    raise RuntimeError(f"MCP server stopped before response {request_id}: {detail}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--expect-hot", help="Expected HOT MCP tool name.")
    args = parser.parse_args()

    process = subprocess.Popen(
        [sys.executable, "-m", "skill_mcp", "--home", str(args.home), "serve", "--no-watch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        initialized = request(
            process,
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "skilldock-smoke", "version": "1"},
            },
        )
        assert initialized["result"]["capabilities"]["tools"]["listChanged"] is True
        assert process.stdin is not None
        process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        process.stdin.flush()

        listed = request(process, 2, "tools/list", {})
        names = [tool["name"] for tool in listed["result"]["tools"]]
        for builtin in ("find_skills", "load_skill", "read_skill_asset"):
            assert builtin in names
        hot_tool = args.expect_hot or next(name for name in names if name.startswith("skill__"))
        assert hot_tool in names
        called = request(process, 3, "tools/call", {"name": hot_tool, "arguments": {}})
        assert called["result"]["isError"] is False
        assert called["result"]["structuredContent"]["instructions"]
        print(
            json.dumps(
                {
                    "protocolVersion": initialized["result"]["protocolVersion"],
                    "toolCount": len(names),
                    "called": hot_tool,
                    "skillId": called["result"]["structuredContent"]["id"],
                },
                indent=2,
            )
        )
    finally:
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
