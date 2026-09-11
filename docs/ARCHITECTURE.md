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
       `---- non-HOT --> SearchProvider ------> find_skills -> load_skill
                              | LexicalSearchProvider (default/offline)
                              | HybridSearchProvider (future extension point)
                              ` SemanticSearchProvider (future extension point)
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

`SearchProvider` is the only ranking boundary used by `SkillRuntime`.
`LexicalSearchProvider` searches name, description, metadata, tags, and source with weighted
token, substring, and fuzzy similarity. Hybrid and semantic provider types are extension points,
not installed backends; the default remains offline and dependency-light.

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

`skilldock reconcile` builds a fresh snapshot in staging and compares it without changing the
managed source or registry. It reports NEW, UPDATED, and MISSING paths. `--apply` atomically swaps
the snapshot and refreshes installed records by relative path while preserving HOT and trust
choices. Newly discovered skills remain uninstalled. Removed paths remain registered with
`status=missing`, are excluded from search and MCP tools, and return a clear load error rather than
an incidental filesystem exception. `skilldock update` remains an alias for the safe apply path.
