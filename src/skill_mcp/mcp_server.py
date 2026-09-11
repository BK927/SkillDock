from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import __version__
from .errors import SkillMCPError
from .runtime import SkillRuntime

LATEST_PROTOCOL_VERSION = "2026-07-28"
SUPPORTED_PROTOCOL_VERSIONS = {
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
    LATEST_PROTOCOL_VERSION,
}


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class ToolFactory:
    def __init__(self, runtime: SkillRuntime):
        self.runtime = runtime

    def build(self) -> dict[str, ToolDefinition]:
        definitions = [
            ToolDefinition(
                name="find_skills",
                description=(
                    "Find installed non-HOT Agent Skills relevant to a task. Returns canonical IDs "
                    "that can be passed to load_skill. Set include_hot to search every installed "
                    "skill."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "Task or capability to match."},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 5},
                        "include_hot": {"type": "boolean", "default": False},
                    },
                    "required": ["task"],
                    "additionalProperties": False,
                },
                handler=lambda args: self.runtime.find_skills(
                    _required_string(args, "task"),
                    limit=_bounded_int(args.get("limit", 5), 1, 100, "limit"),
                    include_hot=_boolean(args.get("include_hot", False), "include_hot"),
                ),
            ),
            ToolDefinition(
                name="load_skill",
                description=(
                    "Load the complete instructions for any installed skill by canonical ID or an "
                    "unambiguous short name. k-skill instructions are assembled for the runtime "
                    "mode."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "skill": {"type": "string", "description": "Canonical ID or unique name."},
                        "runtime_mode": {
                            "type": "string",
                            "enum": ["generic", "dolshoi"],
                            "default": "generic",
                        },
                    },
                    "required": ["skill"],
                    "additionalProperties": False,
                },
                handler=lambda args: self.runtime.load_skill(
                    _required_string(args, "skill"),
                    runtime_mode=str(args.get("runtime_mode", "generic")),
                ),
            ),
            ToolDefinition(
                name="read_skill_asset",
                description=(
                    "Read an installed skill resource below references/, assets/, or a recognized "
                    "text file below scripts/. Traversal outside the skill root is blocked."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "skill": {"type": "string", "description": "Canonical ID or unique name."},
                        "path": {
                            "type": "string",
                            "description": "Skill-root-relative resource path.",
                        },
                    },
                    "required": ["skill", "path"],
                    "additionalProperties": False,
                },
                handler=lambda args: self.runtime.read_skill_asset(
                    _required_string(args, "skill"), _required_string(args, "path")
                ),
            ),
            ToolDefinition(
                name="list_installed_skills",
                description=(
                    "List installed skills, canonical IDs, sources, adapters, and HOT status."
                ),
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                handler=lambda _args: {
                    "skills": [
                        {
                            "id": skill.id,
                            "name": skill.name,
                            "description": skill.description,
                            "source": skill.source,
                            "adapter": skill.adapter,
                            "hot": skill.hot,
                            "toolName": skill.tool_name if skill.hot else None,
                        }
                        for skill in self.runtime.list_skills()
                    ]
                },
            ),
        ]
        tools = {item.name: item for item in definitions}
        for skill in self.runtime.list_skills():
            if not skill.hot:
                continue
            tool_name = skill.tool_name
            description = f"Load the {skill.name} Agent Skill. Use when: {skill.description}"

            def load_hot(_args: dict[str, Any], skill_id: str = skill.id) -> dict[str, Any]:
                return self.runtime.load_skill(skill_id)

            tools[tool_name] = ToolDefinition(
                name=tool_name,
                description=description[:1024],
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                handler=load_hot,
            )
        return tools


class StdioMCPServer:
    """Small, dependency-light JSON-RPC stdio implementation of the MCP tool surface."""

    def __init__(self, runtime: SkillRuntime, *, watch_registry: bool = True):
        self.runtime = runtime
        self.factory = ToolFactory(runtime)
        self.watch_registry = watch_registry
        self._write_lock = threading.Lock()
        self._initialized = threading.Event()
        self._stopped = threading.Event()

    def run(self) -> None:
        watcher: threading.Thread | None = None
        if self.watch_registry:
            watcher = threading.Thread(target=self._watch, name="skill-mcp-registry", daemon=True)
            watcher.start()
        try:
            for raw_line in sys.stdin.buffer:
                if not raw_line.strip():
                    continue
                try:
                    message = json.loads(raw_line)
                    response = self.handle(message)
                    if response is not None:
                        self._write(response)
                except json.JSONDecodeError as exc:
                    self._write(_rpc_error(None, -32700, f"Parse error: {exc.msg}"))
                except Exception as exc:  # keep the transport alive for malformed requests
                    self._write(_rpc_error(None, -32603, f"Internal error: {exc}"))
        finally:
            self._stopped.set()
            if watcher:
                watcher.join(timeout=1)

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _rpc_error(
                message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request"
            )
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}

        if request_id is None:
            if method == "notifications/initialized":
                self._initialized.set()
            return None
        if method == "initialize":
            requested = str(params.get("protocolVersion", LATEST_PROTOCOL_VERSION))
            selected = (
                requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
            )
            return _rpc_result(
                request_id,
                {
                    "protocolVersion": selected,
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": "SkillDock", "version": __version__},
                    "instructions": (
                        "Use HOT skill tools directly. Discover other installed skills with "
                        "find_skills, then activate one with load_skill."
                    ),
                },
            )
        if method == "ping":
            return _rpc_result(request_id, {})
        if method == "tools/list":
            tools = self.factory.build()
            return _rpc_result(
                request_id, {"tools": [item.descriptor() for item in tools.values()]}
            )
        if method == "tools/call":
            return self._call_tool(request_id, params)
        return _rpc_error(request_id, -32601, f'Method not found: "{method}"')

    def _call_tool(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _rpc_error(request_id, -32602, "Invalid tool call parameters")
        tool = self.factory.build().get(name)
        if tool is None:
            return _rpc_result(request_id, _tool_error(f'Unknown tool "{name}"'))
        try:
            result = tool.handler(arguments)
            if name.startswith("skill__") or name == "load_skill":
                text = str(result["instructions"])
            elif name == "read_skill_asset" and result.get("encoding") == "utf-8":
                text = str(result["content"])
            else:
                text = json.dumps(result, ensure_ascii=False, indent=2)
            return _rpc_result(
                request_id,
                {
                    "content": [{"type": "text", "text": text}],
                    "structuredContent": result,
                    "isError": False,
                },
            )
        except (SkillMCPError, ValueError, TypeError) as exc:
            return _rpc_result(request_id, _tool_error(str(exc)))

    def _watch(self) -> None:
        fingerprint = self.runtime.registry.fingerprint()
        while not self._stopped.wait(0.4):
            current = self.runtime.registry.fingerprint()
            if current == fingerprint:
                continue
            fingerprint = current
            if self._initialized.is_set():
                self._write({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})

    def _write(self, payload: dict[str, Any]) -> None:
        encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        with self._write_lock:
            sys.stdout.buffer.write(encoded)
            sys.stdout.buffer.flush()


def _required_string(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Argument "{name}" must be a non-empty string')
    return value


def _bounded_int(value: Any, minimum: int, maximum: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f'Argument "{name}" must be an integer from {minimum} to {maximum}')
    return value


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f'Argument "{name}" must be a boolean')
    return value


def _rpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}
