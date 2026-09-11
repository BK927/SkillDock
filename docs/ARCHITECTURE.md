# Architecture

SkillDock keeps repository acquisition, skill interpretation, and MCP exposure as separate
boundaries.

```text
Git / local source
       |
       v
SourceManager ---------> managed immutable-ish source snapshot + revision
       |
       v
AdapterRegistry -------> SkillCandidate[]
  | StandardAgentSkillAdapter
  | LocalSkillAdapter
  ` KSkillAdapter (optional compatibility)
       |
       v
RegistryStore ---------> registry.json (atomic replacement)
       |
       +---- HOT -------> ToolFactory -------> individual skill__* tools
       |
       `---- non-HOT --> LexicalSearchIndex -> find_skills -> load_skill
                              |
                              `--------------> future semantic index
```

## Responsibilities

`SourceManager` classifies, clones, snapshots, refreshes, and removes sources. It knows nothing
about `SKILL.md`, k-skill, or MCP.

`SkillAdapter` implementations discover metadata and load complete instructions. New repository
formats register an adapter instead of changing source, registry, search, or transport code.
The local adapter is a named extension point over the standard content format; acquisition type
and content layout intentionally remain independent concepts.

`RegistryStore` persists sources and skills separately. A skill ID combines a stable source ID
with its relative path, so equal display names never overwrite each other. Short selectors are
accepted only when they resolve uniquely.

`LexicalSearchIndex` searches name, description, metadata, tags, and source with weighted token,
substring, and fuzzy similarity. Its narrow interface allows a semantic implementation later
without changing the runtime or MCP surface.

`ToolFactory` rebuilds the inventory from registry state. Four system tools are always present;
only records with `hot=true` get an individual activation tool. Tool names are persisted so
restarts do not rename them.

`StdioMCPServer` implements the MCP JSON-RPC lifecycle and tool messages. A registry watcher
emits the standard tool-list-changed notification, while hosts that ignore it remain correct
after reconnect.

`security.py` owns real-path containment, allowed resource roots, text-script policy, size limits,
binary encoding, interpreter selection, trust checks, argument-vector execution, and timeouts.

## Canonical identity

GitHub sources use `github:<owner>/<repo>`. Other Git sources use a hash of their normalized URL;
local sources use a readable directory slug plus an absolute-path hash. Skill IDs append the
skill root relative to the source:

```text
github:mattpocock/skills/skills/engineering/to-spec
github:someone/skills/frontend-design
local:team-skills-a13e72f6c1b2/debugging
```

The display name remains the frontmatter `name`. APIs return both.

## Update semantics

Refresh builds a new snapshot in staging and swaps it into the managed source path. Installed
records are refreshed by relative path, preserving HOT and trust choices. Newly discovered skills
remain uninstalled, and removed paths remain visible as stale records rather than silently deleting
user choices; a future release can add an explicit reconciliation policy.
