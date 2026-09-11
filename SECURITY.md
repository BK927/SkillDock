# Security policy and threat model

Agent Skill repositories are untrusted supply-chain inputs. A `SKILL.md` can contain hostile
instructions even when it has no executable code. SkillDock preserves provenance and limits
runtime mechanics, but the MCP host and user must still review third-party instructions.

## Enforced controls

- Installing a skill does not grant script execution permission.
- Script execution requires the per-skill `trusted` flag set by explicit `--allow-scripts`.
- MCP exposes no install, uninstall, source update, HOT mutation, or script execution tools.
- Asset reads are limited to `references/`, `assets/`, and recognized text files in `scripts/`.
- Absolute paths, drive paths, dot segments, and `..` traversal are rejected.
- Real paths must remain descendants of the installed skill root, blocking symlink escape.
- Asset size is capped at 5 MiB. Binary assets are returned as base64 with their MIME type.
- Script types map to fixed interpreter argument arrays. `shell=False` is always used.
- Script execution has a bounded timeout and runs only the exact installed file.
- Git uses argument-vector subprocesses and disables terminal credential prompts.
- Managed-source deletion verifies the resolved target is below the runtime sources directory.
- Registry writes use same-directory temporary files and atomic replacement.

## Trust limitations

Once a user opts a skill into script execution, its script runs with that user's permissions and
can access resources outside the skill directory. Process sandboxing is platform-specific and is
not claimed by this release. Run SkillDock under a restricted OS account or container for
untrusted code.

HOT changes expose instruction loaders, not automatic execution. Tool descriptions are limited to
name and description; full instructions and resources remain progressively disclosed.

## Reporting

Please report vulnerabilities privately to the repository owner before public disclosure. Include
the affected version, reproduction, impact, and any suggested mitigation.
