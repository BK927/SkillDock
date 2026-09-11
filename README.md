# SkillDock

SkillDock is a universal Agent Skill runtime for MCP. It installs compatible skills from
Git repositories or local directories, keeps them in a persistent registry, exposes a small
set of selected **HOT** skills as individual MCP tools, and keeps every other installed skill
available through search and progressive loading.

It is not tied to one skill repository. Standard `SKILL.md` repositories work through the
default adapter; repository-specific behavior, such as NomaDamas/k-skill's runtime-aware
instruction assembly, lives behind optional adapters.

## What works

- GitHub, generic Git, GitHub `owner/repo` shorthand, and local directory installation
- Recursive discovery of multiple `SKILL.md` folders in any repository layout
- Persistent source, revision, install path, trust, adapter, and HOT metadata
- Canonical IDs that safely distinguish same-named skills from different sources
- A `SearchProvider` boundary with a dependency-free/offline `LexicalSearchProvider` default
- Dynamic HOT tools plus `find_skills`, `load_skill`, `read_skill_asset`, and
  `list_installed_skills`
- Live `notifications/tools/list_changed` when another CLI process changes HOT state
- k-skill `skill.json`/`instruction.md` profile and runtime-mode assembly
- Traversal-safe text/binary asset reads
- Explicit opt-in trust before CLI execution of allow-listed script types; no shell command
  construction and no script-execution MCP tool
- Non-mutating upstream reconciliation previews with explicit safe apply
- Persistent `active`/`missing` state for skills removed upstream
- Reproducible Top-1/3/5 retrieval evaluation over versioned natural-language query sets
- Dependency-light MCP stdio transport

## Install

Python 3.11 or newer and Git are required.

```console
pip install .
```

For development with uv:

```console
uv sync --all-groups
uv run pytest
```

State defaults to `~/.config/skilldock`. Set `SKILLDOCK_HOME` or pass `--home` to use a
different registry and managed-source directory. The old `SKILL_MCP_HOME` variable and
`skill-mcp` executable remain backward-compatible aliases. If only an existing legacy
`~/.config/skill-mcp` directory is present, SkillDock continues using it without moving data.

## CLI

Install every compatible skill in a repository:

```console
skilldock install https://github.com/NomaDamas/k-skill
skilldock install mattpocock/skills --all
```

Install selected skills without exposing them as HOT tools:

```console
skilldock install https://github.com/example/skills \
  --skill frontend-design --skill debugging
```

Review the installed inventory, then explicitly expose only skills the user selected:

```console
skilldock list
skilldock hot add github:example/skills/frontend-design
skilldock hot add github:example/skills/debugging
```

### HOT consent policy

Installation never changes HOT state. The same is true for `update` and `reconcile`: they preserve
an existing user choice but cannot create a new one. Only `skilldock hot add` and
`skilldock hot remove` may change the HOT tier.

The person operating SkillDock must choose every HOT skill by exact name or canonical ID after
reviewing `skilldock list`. Agents, deployment scripts, installers, and repository metadata must
not infer a HOT set, choose a convenient default, or promote all installed skills. The deprecated
install-time `--hot` and `--hot-skill` options now fail with guidance instead of changing state.

Local directories use the same flow and are copied into managed storage:

```console
skilldock install ./my-local-skills
```

Manage installed and HOT state independently:

```console
skilldock list
skilldock hot add frontend-design
skilldock hot remove frontend-design
skilldock hot list
skilldock uninstall frontend-design
skilldock source list
skilldock source remove mattpocock/skills
skilldock reconcile
skilldock reconcile mattpocock/skills --apply
```

`reconcile` is preview-only unless `--apply` is given. Applying refreshes installed metadata,
instructions, and missing state, but does not install NEW skills or delete MISSING ones.
It also preserves, but never creates, HOT choices. `skilldock update` remains a
backward-compatible shorthand for the safe apply behavior.

Short names work only when unambiguous. If two sources contain `frontend-design`, use the
canonical ID shown by `skilldock list`, for example
`github:example/skills/frontend-design`.

Start the MCP server:

```console
skilldock serve
```

Example host configuration:

```json
{
  "mcpServers": {
    "skills": {
      "command": "skilldock",
      "args": ["serve"]
    }
  }
}
```

The server writes only MCP JSON-RPC messages to stdout. HOT changes from another CLI process
trigger `notifications/tools/list_changed`; hosts without refresh support see the new inventory
after reconnecting.

## MCP tool model

Always visible:

- `find_skills(task, limit=5, include_hot=false)` searches installed non-HOT skills.
- `load_skill(skill, runtime_mode="generic")` returns complete instructions for any skill.
- `read_skill_asset(skill, path)` reads approved bundled resources on demand.
- `list_installed_skills()` reports IDs, source, adapter, and HOT state.

For every HOT skill, SkillDock adds a read-only activation tool such as
`skill__frontend_design`. Its description contains only discovery metadata. Calling it loads
the complete instructions. If normalized names collide, the later tool receives a stable
suffix and both remain addressable.

## Supported layouts

Standard Agent Skill layout:

```text
repo/
  any/nesting/skill-name/
    SKILL.md
    scripts/       # optional
    references/    # optional
    assets/        # optional
```

`SKILL.md` must have YAML frontmatter containing a valid `name` and non-empty `description`.
All additional frontmatter is preserved in the discovery index and registry.

k-skill compatibility layout:

```text
repo/
  skill-name/
    skill.json
    instruction.md
    SKILL.md        # generated stub, not used for activation
  packages/k-skill-cli/templates/
```

The `KSkillAdapter` assembles `core` and declared profile templates, filters `generic` or
`dolshoi` mode markers, then adds the skill instruction. Removing that adapter does not affect
the standard runtime.

## Script trust boundary

Installing instructions is not permission to execute their code. Script execution is CLI-only
and disabled unless that skill was installed with `--allow-scripts`:

```console
skilldock install ./trusted-skills --skill formatter --allow-scripts
skilldock exec formatter scripts/format.py -- input.txt
```

Execution resolves a real file below that installed skill's `scripts/` directory, accepts only
known interpreter suffixes, passes arguments as an array with `shell=False`, applies a timeout,
and never turns input into a shell command. Opt-in trust still means the script can act with the
user's operating-system permissions; inspect third-party code before enabling it.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
[docs/evaluation-baseline.md](docs/evaluation-baseline.md),
[docs/compatibility.md](docs/compatibility.md), and [SECURITY.md](SECURITY.md).

## Tests

```console
uv run pytest
uv run ruff check .
uv run python scripts/smoke_stdio.py --home ~/.config/skilldock
skilldock eval evals/retrieval_queries.yaml --min-skills 150
```

The suite covers multi-source discovery, collisions, HOT inventory, persistence, restart,
search/load behavior, uninstall and source isolation, path traversal, trust-gated execution,
k-skill assembly, reconciliation and missing state, pluggable search, retrieval metrics, updates,
and raw MCP stdio initialize/list/call notifications.
