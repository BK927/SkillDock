# MCP host compatibility and live evaluation

Status snapshot: 2026-09-11

SkillDock's runtime and MCP protocol remain separate. The current transport is a local stdio
server; this document distinguishes automated protocol coverage from live model behavior.

## Compatibility matrix

| Host | Connection path | Current status | Evidence still required |
| --- | --- | --- | --- |
| ChatGPT Web / ChatGPT MCP | Remote Streamable HTTP | Not directly supported by the current stdio-only transport | Add an optional remote transport, auth policy, then run the live matrix below |
| Codex local MCP client | Local stdio command | Configuration path documented; raw protocol is automated | Repeat prompt-routing cases in representative fresh conversations |
| Claude Desktop | Local MCP server / desktop extension | Expected to work over stdio; raw protocol is automated | Install in the current desktop release and record all live cases |
| Generic MCP 2024-11-05 through 2025-11-25 client | Local stdio | Automated initialize/list/call/change-notification/reconnect surface | Add named-client rows as clients are tested |

OpenAI's current skill metadata examples declare MCP dependencies with
`transport: streamable_http`, so ChatGPT Web compatibility is intentionally not claimed for this
stdio build. Anthropic documents local MCP servers/Desktop Extensions for Claude Desktop and
remote connectors separately. The MCP specification makes tool use model-controlled and defines
`listChanged` as the signal that the available tool list changed.

References: [OpenAI skill metadata](https://learn.chatgpt.com/ko-KR/docs/build-skills),
[Anthropic local MCP servers](https://support.anthropic.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop),
and [MCP tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).

SkillDock intentionally negotiates at most MCP `2025-11-25`. MCP `2026-07-28` moves list-change
delivery onto a client-opened `subscriptions/listen` stream and adds other message requirements;
claiming that revision without implementing them would be false compatibility. This is a small
version boundary, not a transport rewrite.

## Host configuration

Local stdio clients should start:

```json
{
  "mcpServers": {
    "skilldock": {
      "command": "skilldock",
      "args": ["serve"]
    }
  }
}
```

Use an absolute executable path when a desktop host does not inherit the shell's `PATH`.
`skill-mcp serve` remains a backward-compatible command alias.

## Live test matrix

Run each case in a fresh conversation with a fixed model/version and record the tool-call trace,
not just the final prose answer.

| ID | Setup | Prompt intent | Pass condition |
| --- | --- | --- | --- |
| H01 | Expected skill is HOT | Use the capability without naming it | Host calls the correct `skill__*` tool before answering |
| H02 | Expected skill is non-HOT | Use the capability without naming SkillDock | Host spontaneously calls `find_skills`, then `load_skill` with the expected canonical ID |
| H03 | Connected; add/remove HOT externally | Ask for the changed capability | Host receives `notifications/tools/list_changed`, refreshes `tools/list`, and uses the new inventory |
| H04 | Host deliberately ignores H03 notification | Disconnect and reconnect | Reconnected `tools/list` reflects the registry exactly |
| H05 | Repeat H01 at 5, 10, 20, and 40 HOT skills | Balanced direct-selection prompt set | Record correct-call rate, wrong-tool rate, no-tool rate, and prompt tokens |
| H06 | Similar HOT skills coexist | Ask with the distinguishing action and object | Host selects the exact skill rather than a same-family neighbor |
| H07 | Korean request, English description | Ask without English product words | Record direct/discovery route and expected-skill Top-k outcome |

For every run, capture:

- host, app version, model, date, and OS;
- source revisions and exact HOT canonical IDs;
- prompt and expected canonical ID;
- first tool chosen, complete call sequence, and final route;
- notification receipt and whether a fresh `tools/list` followed;
- pass/fail reason and any host-side approval interruption.

## Automated coverage in this repository

`tests/test_mcp_protocol.py` starts a real stdio subprocess and verifies initialization,
`tools/list`, HOT tool invocation, live `notifications/tools/list_changed`, refreshed inventory,
and the explicit 2026-version fallback. `scripts/smoke_stdio.py` provides the same basic round trip
for an installed registry. These tests validate the server surface, but they do not substitute for
H01/H02 model-choice measurements.

## Interpretation rule

Do not combine provider Top-k and host success into one metric. Use three stages:

1. HOT tool description choice by the host model.
2. The host's decision to invoke `find_skills` for non-HOT tasks.
3. SearchProvider Top-k retrieval after discovery begins.

This separation tells us whether to change HOT count, system-tool descriptions, or search ranking
without attributing one layer's failure to another.
