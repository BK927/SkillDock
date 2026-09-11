from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .config import default_home
from .errors import SkillMCPError
from .mcp_server import StdioMCPServer
from .runtime import SkillRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill-mcp",
        description="Install and expose Agent Skills through one universal MCP runtime.",
    )
    parser.add_argument(
        "--home", type=Path, default=default_home(), help="Runtime state directory."
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    install = subcommands.add_parser(
        "install", help="Install skills from Git or a local directory."
    )
    install.add_argument("source")
    install.add_argument(
        "--skill", action="append", dest="skills", help="Name or relative path; repeatable."
    )
    install.add_argument(
        "--all", action="store_true", help="Install all discovered skills (the default)."
    )
    install.add_argument("--hot", action="store_true", help="Mark every selected skill HOT.")
    install.add_argument(
        "--hot-skill",
        action="append",
        dest="hot_skills",
        help="Mark only this installed name or relative path HOT; repeatable.",
    )
    install.add_argument(
        "--allow-scripts",
        action="store_true",
        help="Trust selected skills for CLI script execution.",
    )
    install.add_argument("--ref", help="Git branch or tag to clone.")

    subcommands.add_parser("list", help="List installed and HOT skills.")

    hot = subcommands.add_parser("hot", help="Manage the independent HOT tool tier.")
    hot_commands = hot.add_subparsers(dest="hot_command", required=True)
    for action in ("add", "remove"):
        command = hot_commands.add_parser(action)
        command.add_argument("skill", help="Canonical ID or unambiguous name.")
    hot_commands.add_parser("list")

    uninstall = subcommands.add_parser(
        "uninstall", help="Uninstall one skill without affecting peers."
    )
    uninstall.add_argument("skill")

    source = subcommands.add_parser("source", help="Manage installed sources.")
    source_commands = source.add_subparsers(dest="source_command", required=True)
    source_commands.add_parser("list")
    source_remove = source_commands.add_parser("remove")
    source_remove.add_argument("source")

    update = subcommands.add_parser("update", help="Refresh one source or all installed sources.")
    update.add_argument("source", nargs="?")

    load = subcommands.add_parser("load", help="Load complete instructions outside MCP.")
    load.add_argument("skill")
    load.add_argument("--runtime-mode", choices=("generic", "dolshoi"), default="generic")

    read = subcommands.add_parser("read", help="Read a policy-approved bundled skill resource.")
    read.add_argument("skill")
    read.add_argument("path")

    execute = subcommands.add_parser("exec", help="Execute an explicitly trusted bundled script.")
    execute.add_argument("skill")
    execute.add_argument("script")
    execute.add_argument("args", nargs=argparse.REMAINDER)
    execute.add_argument("--timeout", type=float, default=60)

    serve = subcommands.add_parser("serve", help="Start the MCP stdio server.")
    serve.add_argument(
        "--no-watch", action="store_true", help="Disable live registry notifications."
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    runtime = SkillRuntime(args.home)
    try:
        result = dispatch(runtime, args)
        if args.command != "serve" and result is not None:
            _print_result(result, as_json=args.json)
    except (SkillMCPError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")


def dispatch(runtime: SkillRuntime, args: argparse.Namespace) -> Any:
    if args.command == "install":
        installed = runtime.install(
            args.source,
            selectors=args.skills,
            hot=args.hot,
            hot_selectors=args.hot_skills,
            allow_scripts=args.allow_scripts,
            ref=args.ref,
        )
        return {
            "installed": [_skill_summary(skill) for skill in installed],
            "installedCount": len(installed),
            "hotCount": sum(skill.hot for skill in installed),
        }
    if args.command == "list":
        skills = runtime.list_skills()
        return {
            "installedCount": len(skills),
            "hotCount": sum(skill.hot for skill in skills),
            "hot": [_skill_summary(skill) for skill in skills if skill.hot],
            "searchable": [_skill_summary(skill) for skill in skills if not skill.hot],
        }
    if args.command == "hot":
        if args.hot_command == "list":
            return {"hot": [_skill_summary(skill) for skill in runtime.list_skills() if skill.hot]}
        skill = runtime.set_hot(args.skill, args.hot_command == "add")
        return {"skill": _skill_summary(skill)}
    if args.command == "uninstall":
        return {"uninstalled": _skill_summary(runtime.uninstall(args.skill))}
    if args.command == "source":
        if args.source_command == "list":
            return {"sources": [source.to_dict() for source in runtime.list_sources()]}
        source, skills = runtime.remove_source(args.source)
        return {
            "removedSource": source.to_dict(),
            "removedSkills": [_skill_summary(skill) for skill in skills],
        }
    if args.command == "update":
        return {"updatedSources": [source.to_dict() for source in runtime.update(args.source)]}
    if args.command == "load":
        return runtime.load_skill(args.skill, runtime_mode=args.runtime_mode)
    if args.command == "read":
        return runtime.read_skill_asset(args.skill, args.path)
    if args.command == "exec":
        script_args = args.args[1:] if args.args[:1] == ["--"] else args.args
        return runtime.exec_skill_script(args.skill, args.script, script_args, timeout=args.timeout)
    if args.command == "serve":
        StdioMCPServer(runtime, watch_registry=not args.no_watch).run()
        return None
    raise ValueError(f"Unknown command: {args.command}")


def _skill_summary(skill: Any) -> dict[str, Any]:
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "source": skill.source,
        "adapter": skill.adapter,
        "hot": skill.hot,
        "trusted": skill.trusted,
        "toolName": skill.tool_name if skill.hot else None,
    }


def _print_result(result: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if isinstance(result, dict) and "installedCount" in result:
        print(f"Installed Skills: {result['installedCount']}")
        print(f"HOT Skills: {result['hotCount']}")
        for item in result.get("installed", []):
            marker = "HOT" if item["hot"] else "searchable"
            print(f"  [{marker}] {item['name']}  ({item['id']})")
        return
    if isinstance(result, dict) and {"hot", "searchable"} <= result.keys():
        print(f"Installed Skills: {result['installedCount']}")
        print(f"HOT Skills: {result['hotCount']}")
        print("\nHOT")
        for item in result["hot"]:
            print(f"  {item['name']}  ({item['id']})")
        print("\nSEARCHABLE")
        for item in result["searchable"]:
            print(f"  {item['name']}  ({item['id']})")
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
