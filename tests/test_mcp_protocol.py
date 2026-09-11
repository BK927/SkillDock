from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from skill_mcp.runtime import SkillRuntime


class MCPProcess:
    def __init__(self, home: Path):
        environment = os.environ.copy()
        source_root = str(Path(__file__).parents[1] / "src")
        environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "skill_mcp", "--home", str(home), "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=environment,
        )

    def send(self, message: dict) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def receive(self) -> dict:
        assert self.process.stdout is not None
        line = self.process.stdout.readline()
        assert line, self.process.stderr.read() if self.process.stderr else "server stopped"
        return json.loads(line)

    def request(self, request_id: int, method: str, params: dict | None = None) -> dict:
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        while True:
            message = self.receive()
            if message.get("id") == request_id:
                return message

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)


def test_stdio_initialize_list_and_call_round_trip(tmp_path, source_a):
    home = tmp_path / "mcp-home"
    runtime = SkillRuntime(home)
    installed = runtime.install(str(source_a), selectors=["frontend-design"], hot=True)
    process = MCPProcess(home)
    try:
        initialized = process.request(
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "integration-test", "version": "1"},
            },
        )
        assert initialized["result"]["protocolVersion"] == "2025-06-18"
        assert initialized["result"]["capabilities"]["tools"]["listChanged"] is True
        process.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        listed = process.request(2, "tools/list")
        names = {tool["name"] for tool in listed["result"]["tools"]}
        assert installed[0].tool_name in names
        assert "find_skills" in names

        called = process.request(
            3,
            "tools/call",
            {"name": installed[0].tool_name, "arguments": {}},
        )
        assert called["result"]["isError"] is False
        assert "Instructions for frontend-design" in called["result"]["content"][0]["text"]
        assert called["result"]["structuredContent"]["id"] == installed[0].id
    finally:
        process.close()


def test_running_server_notifies_and_refreshes_when_hot_registry_changes(tmp_path, source_a):
    home = tmp_path / "watch-home"
    runtime = SkillRuntime(home)
    runtime.install(str(source_a), selectors=["systematic-debugging"])
    process = MCPProcess(home)
    try:
        process.request(1, "initialize", {"protocolVersion": "2025-06-18"})
        process.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        runtime.set_hot("systematic-debugging", True)

        deadline = time.monotonic() + 5
        notification = None
        while time.monotonic() < deadline:
            candidate = process.receive()
            if candidate.get("method") == "notifications/tools/list_changed":
                notification = candidate
                break
        assert notification is not None
        listed = process.request(2, "tools/list")
        names = {tool["name"] for tool in listed["result"]["tools"]}
        assert runtime.get_skill("systematic-debugging").tool_name in names
    finally:
        process.close()
