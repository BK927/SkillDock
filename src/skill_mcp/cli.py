from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import default_home
from .errors import SkillMCPError
from .evaluation import evaluate_retrieval, write_evaluation
from .mcp_server import StdioMCPServer
from .runtime import SkillRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skilldock",
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
    install.add_argument("--hot", action="store_true", help=argparse.SUPPRESS)
    install.add_argument(
        "--hot-skill",
        action="append",
        dest="hot_skills",
        help=argparse.SUPPRESS,
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

    reconcile = subcommands.add_parser(
        "reconcile", help="Preview upstream NEW, UPDATED, and MISSING skills."
    )
    reconcile.add_argument("source", nargs="?")
    reconcile.add_argument(
        "--apply",
        action="store_true",
        help="Refresh installed records and mark missing paths without installing or deleting.",
    )

    evaluate = subcommands.add_parser(
        "eval", help="Evaluate discovery top-k quality from a YAML query set."
    )
    evaluate.add_argument("dataset", type=Path)
    evaluate.add_argument("--output", type=Path, help="Write the complete JSON result.")
    evaluate.add_argument("--min-skills", type=int, default=0)

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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
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
        if args.hot or args.hot_skills:
            raise ValueError(
                "Installation cannot change HOT state. Install first, review `skilldock list`, "
                "then run `skilldock hot add <skill>` for each skill explicitly selected by "
                "the user."
            )
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
            "activeCount": sum(skill.status == "active" for skill in skills),
            "hotCount": sum(skill.hot and skill.status == "active" for skill in skills),
            "hot": [
                _skill_summary(skill) for skill in skills if skill.hot and skill.status == "active"
            ],
            "searchable": [
                _skill_summary(skill)
                for skill in skills
                if not skill.hot and skill.status == "active"
            ],
            "missing": [_skill_summary(skill) for skill in skills if skill.status == "missing"],
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
    if args.command == "reconcile":
        return runtime.reconcile(args.source, apply=args.apply)
    if args.command == "eval":
        result = evaluate_retrieval(runtime, args.dataset, min_skills=args.min_skills)
        if args.output:
            write_evaluation(result, args.output)
            result["output"] = str(args.output.resolve())
        return result
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
        "status": skill.status,
        "missingSince": skill.missing_since,
        "trusted": skill.trusted,
        "toolName": skill.tool_name if skill.hot and skill.status == "active" else None,
    }


def _print_result(result: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if isinstance(result, dict) and "installed" in result and "installedCount" in result:
        print(f"Installed Skills: {result['installedCount']}")
        print(f"HOT Skills: {result['hotCount']}")
        for item in result.get("installed", []):
            marker = "HOT" if item["hot"] else "searchable"
            print(f"  [{marker}] {item['name']}  ({item['id']})")
        return
    if isinstance(result, dict) and {"hot", "searchable"} <= result.keys():
        print(f"Installed Skills: {result['installedCount']}")
        print(f"Active Skills: {result['activeCount']}")
        print(f"HOT Skills: {result['hotCount']}")
        print("\nHOT")
        for item in result["hot"]:
            print(f"  {item['name']}  ({item['id']})")
        print("\nSEARCHABLE")
        for item in result["searchable"]:
            print(f"  {item['name']}  ({item['id']})")
        if result["missing"]:
            print("\nMISSING")
            for item in result["missing"]:
                marker = " [HOT]" if item["hot"] else ""
                print(f"  {item['name']}{marker}  ({item['id']})")
        return
    if isinstance(result, dict) and {"applied", "sources", "totals"} <= result.keys():
        action = "Applied" if result["applied"] else "Preview"
        totals = result["totals"]
        print(f"Source changes ({action.lower()}):")
        print(
            f"  + {totals['new']} newly discovered skills\n"
            f"  ~ {totals['updated']} installed skills updated\n"
            f"  * {totals['missing']} installed skills no longer exist upstream"
        )
        for source in result["sources"]:
            print(f"\n{source['sourceId']}")
            for heading, key in (("NEW", "new"), ("UPDATED", "updated"), ("MISSING", "missing")):
                if not source[key]:
                    continue
                print(f"\n{heading}")
                for item in source[key]:
                    marker = " [HOT]" if item.get("hot") else ""
                    print(f"  {item['name']}{marker}  ({item['path']})")
        if not result["applied"]:
            print("\nNo registry choices changed. Re-run with --apply to refresh safe state.")
        return
    if isinstance(result, dict) and {"provider", "metrics", "corpus"} <= result.keys():
        metrics = result["metrics"]
        corpus = result["corpus"]
        print(
            f"Provider: {result['provider']}\n"
            f"Corpus: {corpus['activeSkillCount']} active "
            f"({corpus['hotCount']} HOT, {corpus['discoveryCount']} discovery)\n"
            f"Queries: {metrics['count']}\n"
            f"Top-1: {metrics['top1']:.1%}\n"
            f"Top-3: {metrics['top3']:.1%}\n"
            f"Top-5: {metrics['top5']:.1%}\n"
            f"MRR@5: {metrics['mrrAt5']:.4f}"
        )
        if result.get("output"):
            print(f"Full result: {result['output']}")
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
