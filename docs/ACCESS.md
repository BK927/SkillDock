# Home-server access through a secure stdio tunnel

SkillDock exposes a stdio MCP server. It does not ship an HTTP login page,
administrator password, OAuth issuer or passkey enrollment service.

For the recorded personal home-server deployment, an authenticated OpenAI secure
MCP tunnel launches `skilldock --home <private-registry-directory> serve`. Keep
that existing transport and its account/access controls. A shared passkey front
door for HTTP MCPs does not need to replace the tunnel or add another password.
Do not turn the stdio server into a public unauthenticated HTTP service.

Tunnel profiles can contain credentials. Store them privately, outside Git and
outside the installed-skill registry; never print or publish their contents.
Restarting or redeploying the SkillDock executable should preserve the existing
registry, installed sources and the user's explicit HOT choices. It must not
install another source or infer new HOT selections.

The private Cloud Browser control console is a separate service and is not a
SkillDock endpoint. Its optional shared passkey login is documented in
[Cloud Browser](https://github.com/BK927/cloud-browser-mcp/blob/main/docs/PASSKEY_LOGIN.md).

The personal deployment was inspected on 2026-10-03: the tunnel launched the
existing stdio command and its service was active. No SkillDock transport code,
installed skills or HOT selections changed during the passkey rollout.
