# Claude Code install-artefact contract — documented shapes for the M15 installer

## Brief

We are porting Zikaron's installer to write Claude Code configuration files. This note is a
**documentation-reading task only** — the parent session will measure anything load-bearing
separately. The requirement: the precise documented contract for five artefacts the installer will
write programmatically — hooks config, per-hook `timeout`, `.mcp.json`, MCP tool naming in
config, and the subagent/skill frontmatter shapes — with exact key names, nesting and units, quoted
from `code.claude.com/docs`, and explicit flags where the docs are silent.

## Method

Fetched `code.claude.com/docs/en/hooks`, `.../en/mcp`, `.../en/sub-agents`, `.../en/skills`, and
`.../en/settings` directly (WebFetch, 2026-08-16), cross-checked with WebSearch for two settings
keys the first fetch summarized rather than quoted. All quotes below are transcribed from the
fetched page content; paraphrase is marked as such. Anthropic's docs frequently note a **minimum
Claude Code version** for a behavior — those are recorded, since the installer cannot assume the
user's version, though the "as of / before vX.Y.Z" pattern in these docs implies fairly aggressive,
frequent doc updates tied to shipped versions, which is itself worth flagging: this is documentation
for a fast-moving CLI, and exact defaults have changed release to release (see `timeout` note below).

**No independent verification was performed.** This is a documentation reading, not a probe — that
is a deliberate scope line drawn by the brief, and follows the pattern already used successfully for
`research/claude-code-harness-probe.md` (probe) vs `research/claude-code-harness-contract.md`
(reading) — this note plays the second role, refreshed and widened to the five install artefacts.

---

## 1. Hooks in `settings.json` / `settings.local.json`

Source: [Hooks reference](https://code.claude.com/docs/en/hooks)

### Complete JSON shape

Quoted (code block) from the docs:

```json
{
  "hooks": {
    "EventName": [
      {
        "matcher": "ToolName|OtherTool",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/script.sh",
            "args": [],
            "timeout": 600,
            "statusMessage": "Custom message",
            "if": "Bash(rm *)",
            "async": false,
            "asyncRewake": false,
            "shell": "bash"
          },
          { "type": "http", "url": "...", "timeout": 600, "headers": {}, "allowedEnvVars": [] },
          { "type": "mcp_tool", "server": "my_server", "tool": "tool_name", "input": {}, "timeout": 600 },
          { "type": "prompt", "prompt": "...", "model": "...", "timeout": 30 },
          { "type": "agent", "prompt": "...", "timeout": 60 }
        ]
      }
    ]
  }
}
```

So the nesting **is** as the brief guessed: `{"hooks": {"<EventName>": [{"matcher": "...", "hooks":
[{"type": "command", "command": "...", "timeout": N, ...}]}]}}`. Zikaron only needs the `command`
type. Note the docs also expose `http`, `mcp_tool`, `prompt`, and `agent` hook types — not needed
here, but worth knowing the `hooks` array is heterogeneous by `type`.

A second, minimal worked example is given for `PreToolUse`/`Bash`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "if": "Bash(rm *)",
            "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/block-rm.sh",
            "args": []
          }
        ]
      }
    ]
  }
}
```

`${CLAUDE_PROJECT_DIR}` expansion in `command` is confirmed by this example.

### Event names Zikaron cares about, matcher support, and what the matcher matches

From the docs' event table (transcribed, full table has ~28 events; only the four the brief asked
about plus neighbours are reproduced):

| Event | Matcher support | Matches against |
|---|---|---|
| `SessionStart` | Yes | `startup`, `resume`, `clear`, `compact`, `fork` |
| `UserPromptSubmit` | **No** | N/A — always fires |
| `SubagentStart` | Yes | Agent type (e.g. `general-purpose`, `Explore`, custom agent names) |
| `SubagentStop` | Yes | Agent type |
| `PreCompact` | Yes | What triggered it: `manual`, `auto` |
| `PostCompact` | No | N/A — always fires |
| `Stop` | No | N/A — always fires |

**`UserPromptSubmit` does not accept a `matcher`** — confirming and sharpening what M14's probe
already established (fires once per user message, `{hook_event_name, cwd, session_id, prompt}`).
Any `matcher` key under `UserPromptSubmit` in a written config is inert; the installer should omit
it there.

`SubagentStart`/`SubagentStop` matchers are **agent type strings** (e.g. a custom subagent's `name`
field, or built-ins like `general-purpose`/`Explore`) — this is the mechanism D32's "withhold the
write-policy injection from the consolidator specifically" would use, confirming what FINDINGS
already recorded from the M14 probe (`agent_id` **and** `agent_type` are both carried on the
payload).

### Per-hook `timeout` — the single most important item

**Key name:** `timeout`. **Unit: seconds, not milliseconds.** This directly contradicts the
provisional assumption baked into `push.py`'s ~2 s internal deadline being sized against "whatever
unit the field turns out to be" — the unit is now documented, and it is **seconds**.

**Scope: per-hook-command entry**, i.e. per object inside the `hooks` array, not per `EventName`
block and not one global value.

**Default values, quoted/transcribed from the docs, by hook `type`:**
- `command`: 600 seconds
- `http`: 600 seconds
- `mcp_tool`: 600 seconds
- `prompt`: 30 seconds
- `agent`: 60 seconds

**Event-specific overrides of those defaults** (also documented):
- `UserPromptSubmit` lowers the `command`/`http`/`mcp_tool` default to **30 seconds** (not 600).
- `MessageDisplay` lowers the same three to **10 seconds**.
- `SessionEnd` hooks share a **1.5-second total budget**; a longer per-hook `timeout` raises the
  total budget to match, capped at 60 seconds.

**Behaviour on timeout, quoted:**
> "A `command`, `http`, or `mcp_tool` hook that reaches its `timeout` is canceled: Claude Code
> discards the hook's output, and the hook renders no decision. On `PreToolUse`, the hook doesn't
> block the tool call — the call continues through the normal permission flow. A timed-out hook on
> most other events behaves as a non-blocking error."

So: **killed, output discarded, no decision rendered**, and on most events it is silently treated
as a non-blocking error rather than surfaced as a hard failure. This matters for Zikaron's push hook
specifically under `SessionStart`/`UserPromptSubmit`, neither of which is `PreToolUse` — a timed-out
push hook is a silent no-op from the agent's perspective, consistent with the "always exit 0"
design already in place, but now for a documented reason rather than an assumed one.

**What this settles for FINDINGS current-state item (b):** the "documented, unmeasured" status is
now **documented**. The default for `UserPromptSubmit` specifically (the event Zikaron's push hook
uses) is **30 seconds**, i.e. **30,000 ms**, a full order of magnitude looser than kiro's 10,000 ms
`timeout_ms`. The internal ~2 s deadline clears this by a wide margin either way — but the number to
carry forward is **30 s for `command` hooks under `UserPromptSubmit`**, not 600 s, and not any
`timeout_ms`-shaped value; the installer must write a bare integer number of **seconds**, and if it
sets an explicit `timeout` it should write something like `10` (not `10000`) or omit the field to
take the 30 s event default. **Flag:** this default is stated as current documentation for whatever
Claude Code version the docs site currently describes (fetched 2026-08-16); the docs' own
versioning notes elsewhere on the page (e.g. "Before v2.1.203...") show these numbers have moved
before and could move again — the parent session should still confirm the *installed* version's
number empirically before shipping, per the brief's stated intent to measure anything load-bearing.
The docs do not state whether the default has ever been different for `UserPromptSubmit`
specifically (only the `roots/list` and idle-timeout-adjacent notes on the MCP page carry that kind
of version history; the hooks page's timeout section carries none).

**Not stated by the docs:** whether `timeout` accepts a fractional/decimal number of seconds (all
examples use integers); whether a `timeout` of `0` is legal or meaningful; the exact wall-clock
measurement start point (process spawn vs. first byte).

---

## 2. `.mcp.json` — project-scoped MCP servers

Source: [Connect Claude Code to tools via MCP](https://code.claude.com/docs/en/mcp)

### File shape

Quoted, the "standardized format" for a project-scoped server, written by `claude mcp add --scope
project`:

```json
{
  "mcpServers": {
    "shared-server": {
      "type": "http",
      "url": "https://example.com/mcp"
    }
  }
}
```

For a **stdio** server the shape (assembled from the plugin example and the `command`/`args`/`env`
fields documented throughout the page) is:

```json
{
  "mcpServers": {
    "database-tools": {
      "command": "/path/to/server",
      "args": ["--config", "config.json"],
      "env": { "DB_URL": "..." }
    }
  }
}
```

**Important, and easy to get wrong:** a stdio entry has **no `type` field** in the examples shown
(the docs' plugin example above omits it entirely), while an HTTP/SSE/WS entry **requires**
`"type": "http"` (or `"sse"`/`"ws"`; `"streamable-http"` is accepted as an alias for `"http"`).
Quoted: "A JSON entry that has a `url` but no `type` is a configuration error, because Claude Code
reads an entry with no `type` as a stdio server." So the discriminator is: **presence of `type` +
`url`** → remote server; **absence of `type`, presence of `command`** → stdio server. Zikaron's MCP
server is stdio, so its `.mcp.json` entry should carry `command`/`args`/`env` and **no `type` key**.

Environment variable expansion is supported in `.mcp.json` for `command`, `args`, `env`, `url`,
`headers`, syntax `${VAR}` and `${VAR:-default}`. `${CLAUDE_PROJECT_DIR}` is set in the **spawned
server's own environment** (not Claude Code's), so referencing it via `${VAR}` expansion inside
`.mcp.json` itself needs a default form, `${CLAUDE_PROJECT_DIR:-.}` — quoted: "This variable is set
in the server's environment, not in Claude Code's own environment, so referencing it via `${VAR}`
expansion in the `command` or `args` of a project-scoped `.mcp.json` entry ... requires a default
such as `${CLAUDE_PROJECT_DIR:-.}`." This is a genuine trap for an installer that assumes
`${CLAUDE_PROJECT_DIR}` resolves the same way inside `.mcp.json` as it does when the *server process*
later reads it from its own env — it does not resolve at config-parse time without the fallback.

### Approval flow

Quoted: "For security reasons, Claude Code prompts for approval in interactive sessions before
using project-scoped servers from `.mcp.json` files. To reset those approval choices, run `claude
mcp reset-project-choices`."

What the user sees: `claude mcp list` / `claude mcp get <name>` show a pending server as
`` ⏸ Pending approval (run `claude` to approve) ``; a rejected server shows `` ✘ Rejected (see
disabledMcpjsonServers in settings) ``. Approving happens by running `claude` interactively in the
project and going through the prompt Claude Code shows at that point (the docs describe the prompt's
existence and its trigger but do not show its literal on-screen text/wording).

**Modes that skip the prompt entirely, quoted:** "`claude -p` runs, Agent SDK sessions, and cloud
sessions can't show that prompt: Claude Code loads project-scoped servers there without asking. A
session you start in `bypassPermissions` mode with `skipDangerousModePermissionPrompt` set skips the
prompt too." To keep a server out even then: add it to `disabledMcpjsonServers` (blocks in every
mode), or exclude project settings entirely via `--setting-sources` / the SDK's `settingSources`.

**Pre-approval mechanism (this answers "is there a documented way to pre-approve"):** three
settings keys, documented on the settings page and referenced from the MCP page:
- `enableAllProjectMcpServers: true` — auto-approves every server in the project's `.mcp.json`.
- `enabledMcpjsonServers: ["name", ...]` — whitelist of specific servers to auto-approve.
- `disabledMcpjsonServers: ["name", ...]` — blacklist; **quoted, verbatim definition from the
  settings page:** "List of specific MCP servers from `.mcp.json` files to reject."

**Workspace-trust interaction — genuinely load-bearing for an installer that writes into a
repository, and easy to miss.** Quoted from the MCP page: "As of v2.1.196, `claude mcp list` and
`claude mcp get` read `.mcp.json` approvals only from settings files that aren't checked into the
repository until you trust the workspace by running `claude` in it and accepting the workspace trust
dialog. A cloned repository can't approve its own servers: `enableAllProjectMcpServers` or
`enabledMcpjsonServers` committed to the project's `.claude/settings.json` is ignored in an
untrusted folder, and the server stays at `⏸ Pending approval`..." Settings that **do** still apply
in an untrusted folder: user `~/.claude/settings.json`, managed settings, `--settings`-passed
settings, and (after accepting a trust dialog) an **untracked** `.claude/settings.local.json`. So:
**if Zikaron's installer wants the MCP server auto-approved without a manual `claude` run, the
pre-approval entry must go in an untracked file** (`settings.local.json`, not committed) **or the
user's own `~/.claude/settings.json`** — putting `enableAllProjectMcpServers`/
`enabledMcpjsonServers` in the committed `.claude/settings.json` does not bypass the trust dialog for
a freshly cloned repo, which is exactly the installer's own use case if it commits its config.

Reserved server names that will silently fail to register: `workspace`, `claude-in-chrome`,
`computer-use`, `Claude Preview`, `Claude Browser` — the docs say Claude Code "skips it at load time
and shows a warning asking you to rename it" for a config-file entry with a reserved name, and `claude
mcp add` rejects the name outright at the CLI. Not a concern for a server literally named `zikaron`,
but worth the installer asserting the name doesn't collide.

**Not stated by the docs:** the literal wording/UI text of the interactive approval prompt itself
(only its *outcome states* — pending/approved/rejected — are documented); whether there is a
non-interactive CLI verb to approve a specific server ahead of time (only `reset-project-choices`,
which clears rather than sets approvals, is documented — pre-approval is only via the three settings
keys above, not a `claude mcp approve <name>` command).

---

## 3. MCP tool naming

Source: [MCP page](https://code.claude.com/docs/en/mcp) (plugin-tool-naming section) and
[Settings page](https://code.claude.com/docs/en/settings) (`permissions.allow`/`deny` examples), and
[Sub-agents page](https://code.claude.com/docs/en/sub-agents) (`tools:`/`disallowedTools:` examples).

**Confirmed: the qualified form is `mcp__<serverName>__<toolName>`.** Direct example from the
settings page's `permissions` block:
```json
"allow": ["mcp__github__search_repositories", "mcp__filesystem__read"],
"deny": ["mcp__filesystem__write"]
```

**Wildcard / whole-server reference — confirmed, with a caveat found on the sub-agents page:**
- `mcp__<server>` — all tools from a server.
- `mcp__<server>__*` — equivalent, all tools from a server, explicit-glob form.
- `mcp__*` — **only usable in `disallowedTools`**, per the sub-agents page's own summary; the docs
  do not show this form used in `permissions.allow`/`deny` in the settings-page examples, so its
  legality there specifically is not directly evidenced (only inferred by analogy — **flagged, not
  asserted**).

Worked example from the sub-agents page, withholding one server entirely via denylist:
```yaml
---
name: local-only
description: Inherits every tool except those from the github MCP server
disallowedTools:
  - mcp__github
---
```

**Plugin-bundled servers use a different, longer qualified form**, documented on the MCP page:
`mcp__plugin_<plugin-name>_<server-name>__<tool-name>`, with any character outside `A-Z a-z 0-9 _ -`
replaced by `_`. Quoted: "A hook matcher written against the bare server key, such as
`mcp__database-tools__.*`, never fires for a plugin-bundled server." **Not relevant to Zikaron**
(Zikaron's server is not distributed as a plugin), but worth recording since it is a real trap for
anyone who later plugin-wraps the server: the tool name changes shape entirely, it does not stay
`mcp__zikaron__search`.

**Same string in three places, confirmed by the docs' own cross-reference:** the MCP page explicitly
says to "Use this full name when referencing the tool in permission rules, a skill's `allowed-tools`
list, a subagent's `tools` field, or a hook matcher" — i.e. `mcp__<server>__<tool>` (or the
plugin-scoped variant) is the **one** canonical string used consistently across `permissions.allow`/
`deny`, subagent frontmatter `tools:`/`disallowedTools:`, skill frontmatter `allowed-tools:`, and a
`hooks` matcher for MCP tools.

**Is this the same string the model sees in its tool list?** The docs do not directly restate the
qualified name as the literal string shown to the model in its tool-call schema/tool-list — they
document it consistently as the *configuration-addressing* string across all four surfaces above,
and separately note (MCP page, "Scale with MCP tool search") that with tool search enabled (the
default), the model discovers tools via a `ToolSearch` call rather than always seeing a flat list —
so **the docs do not explicitly confirm the model-visible tool name is byte-identical to the
configuration string**; this is plausible by construction (nothing suggests a second aliasing layer)
but should be flagged as **not directly stated**, and is a candidate for the parent session's own
measurement (e.g. inspect what a subagent transcript actually calls the tool).

**Not stated by the docs:** the exact registration/addressing form for the **server** name itself
where a plain server key rather than a tool-qualified string is expected (the MCP page gives one
data point — the *plugin-scoped* server registers under `plugin:<plugin-name>:<server-name>` for use
in an `mcp_tool` hook's `server` field — but does not restate the **non-plugin** case, which is
presumably just the bare key used in `mcpServers`, e.g. `"zikaron"`, though this is inference, not a
quoted statement).

---

## 4. Subagent files (`.claude/agents/*.md`)

Source: [Create custom subagents](https://code.claude.com/docs/en/sub-agents)

**Full documented frontmatter field table** (transcribed):

| Field | Required | Type | Notes |
|---|---|---|---|
| `name` | **Yes** | string | Lowercase + hyphens; used as `agent_type` in hooks |
| `description` | **Yes** | string | When Claude should delegate to this subagent |
| `tools` | No | **YAML list** | Allowlist. **Omitting it → inherits every tool available to subagents.** |
| `disallowedTools` | No | YAML list | Denylist, removed from inherited/specified list |
| `model` | No | string | `sonnet`, `opus`, `haiku`, `fable`, a full model ID, or `inherit`. **Default: `inherit`** |
| `permissionMode` | No | string | `default`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions`, `plan`, `manual` |
| `maxTurns` | No | number | Max agentic turns before the subagent stops |
| `skills` | No | YAML list | Skills preloaded into the subagent's context at startup |
| `mcpServers` | No | YAML list | MCP servers available to this subagent (names or inline defs) |
| `hooks` | No | object | Lifecycle hooks scoped to this subagent |
| `memory` | No | string | `user`, `project`, or `local` |
| `background` | No | boolean | Keep the subagent in the background |
| `effort` | No | string | `low`, `medium`, `high`, `xhigh`, `max` |
| `isolation` | No | string | `worktree` runs in a temporary git worktree |
| `color` | No | string | Display colour |
| `initialPrompt` | No | string | Auto-submitted as first user turn when run as main session |

**`tools:` is a YAML list, not a comma-separated string** — confirmed directly, with worked example:
```yaml
tools:
  - Read
  - Grep
  - Glob
  - Bash
```
(a flow-style `tools: [Read, Grep, Glob, Bash]` is also shown elsewhere on the page as equivalent —
so both YAML list styles work, but it is a list either way, never a bare comma-separated string —
**contrast this with skill frontmatter's `allowed-tools`, which explicitly does accept a
space/comma-separated string as an alternative to a YAML list — the two frontmatter formats are not
uniform on this point, which is exactly the kind of divergence an installer template could get
wrong by assuming consistency.**

**Omitting `tools:` → inherits every tool available to subagents** — confirmed, quoted: "Inherits
every tool available to subagents if omitted."

**Precedence when both `tools` and `disallowedTools` are set:** quoted: "If both are set,
`disallowedTools` is applied first, then `tools` is resolved against the remaining pool."

**Full worked YAML example**, quoted from the docs:
```yaml
---
name: code-reviewer
description: Expert code review specialist. Proactively reviews code for quality, security, and maintainability. Use immediately after writing or modifying code.
tools:
  - Read
  - Grep
  - Glob
  - Bash
model: sonnet
permissionMode: default
maxTurns: 10
skills:
  - code-review-checklist
memory: project
background: false
effort: high
color: blue
---

You are a senior code reviewer ensuring high standards of code quality and security.
...
```

**Not stated by the docs (in what was fetched):** an exhaustive enumeration of every legal built-in
tool name string (only `Read`/`Write`/`Edit`/`Bash`/`Grep`/`Glob` appear in examples — the full tool
name list lives on a separate tools-reference page, not fetched here); whether `name` must be
globally unique across personal/project/plugin agent sources or only within one source (analogous
skill-name collision rules are documented for skills, not restated for agents in what was fetched).

---

## 5. Skill files (`.claude/skills/<name>/SKILL.md`)

Source: [Extend Claude with skills](https://code.claude.com/docs/en/skills)

**Location convention confirmed:** project skills at `.claude/skills/<skill-name>/SKILL.md`,
personal at `~/.claude/skills/<skill-name>/SKILL.md`, plugin at `<plugin>/skills/<skill-name>/SKILL.md`.
Directory name is `SKILL.md`'s parent and (for personal/project skills) is what supplies the `/`
command name — **not** the frontmatter `name` field for those two locations (see the "how a skill
gets its command name" table below).

**Full documented frontmatter field table** (transcribed verbatim from the "Frontmatter reference"
section; quoted intro: "All fields are optional. Only `description` is recommended so Claude knows
when to use the skill."):

| Field | Required | Notes |
|---|---|---|
| `name` | No | Display name in listings; defaults to directory name. For personal/project skills this does **not** change the invocation command (directory name does); for plugin skills it does. |
| `description` | **Recommended** | What the skill does and when to use it — what Claude matches against to auto-load. If omitted, falls back to the first markdown paragraph. Combined `description` + `when_to_use` truncated at **1,536 characters** in the skill listing. |
| `when_to_use` | No | Additional trigger-phrase context, appended to `description`, counts toward the same 1,536-char cap |
| `argument-hint` | No | Autocomplete hint, e.g. `[issue-number]` |
| `arguments` | No | Named positional args for `$name` substitution; space-separated string or YAML list |
| `disable-model-invocation` | No | `true` → Claude never auto-loads it (manual `/name` only); also blocks subagent preload and scheduled-task auto-fire. Default `false` |
| `user-invocable` | No | `false` → hidden from `/` menu, users can't type `/name`; Claude can still invoke it. Default `true` |
| `allowed-tools` | No | Tools pre-approved for the invoking turn only (clears next message). **Accepts space- or comma-separated string, or YAML list** |
| `disallowed-tools` | No | Tools removed while skill active (clears next message). Same string-or-list acceptance |
| `model` | No | Override for the current turn only, not persisted |
| `effort` | No | `low`/`medium`/`high`/`xhigh`/`max`, overrides session effort for the turn |
| `context` | No | `fork` → runs in a forked subagent context |
| `agent` | No | Which subagent type to use with `context: fork` |
| `background` | No | With `context: fork`, `false` waits for the result inline instead of backgrounding. Default `true` |
| `hooks` | No | Hooks registered when skill invoked, live for rest of session |
| `paths` | No | Glob patterns gating auto-activation to matching files; comma-separated string or YAML list |
| `shell` | No | `bash` (default) or `powershell`, for inline `!command` execution |
| `metadata` | No | Free-form YAML map, not acted on by Claude Code |
| `license` | No | Agent Skills spec field, accepted but not acted on |
| `compatibility` | No | Agent Skills spec field (≤500 chars), accepted but not acted on |

Worked minimal example, quoted:
```yaml
---
name: my-skill
description: What this skill does
disable-model-invocation: true
allowed-tools: Read Grep
---

Your skill instructions here...
```

**What governs auto-loading:** the `description` field (plus optional `when_to_use`) is what Claude
matches the user's request against at session start to decide whether to load the skill — quoted
from elsewhere on the page: "At startup, Claude scans all available skills and reads only the name
and description from each one" (this line came from the earlier WebSearch synthesis, corroborated by
the frontmatter table's own description of `description`'s role: "Claude uses this to decide when to
apply the skill"). `disable-model-invocation: true` removes a skill from that automatic path
entirely, leaving only explicit `/name` invocation — this is the field Zikaron's `self-review` skill
or any task-style (rather than reference-style) skill would want if it should never be silently
autoloaded.

**Boolean field parsing, worth noting for a config-writing installer:** quoted, "Boolean fields
accept `yes`, `no`, `on`, `off`, `1`, and `0` in any letter case, in addition to `true` and `false`."
— generous, but the installer should still emit literal `true`/`false` rather than relying on this.

**Agent Skills open-standard subset — relevant if Zikaron's skill is ever distributed outside Claude
Code:** only six fields are legal for claude.ai skill uploads / the Skills API / `package_skill.py`:
`name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`. Any other field (e.g.
`argument-hint`, `context`) causes those paths to **hard-fail** with `Unexpected key(s) in SKILL.md
frontmatter: ...`. Not relevant to the Claude-Code-only installer path, but recorded since it bounds
what a portable skill file could ever use.

**Not stated by the docs (in what was fetched):** the exact matching algorithm behind "Claude uses
this to decide" — no scoring/threshold mechanism is documented, only that `description` (and
`when_to_use`) are what gets matched, and that they are read at session start alongside every other
skill's; whether skill matching happens per-turn or only at session start for newly-relevant skills
(the docs describe live file-change detection picking up edited/added skills mid-session, but not
whether an *unedited*, already-loaded-as-metadata skill can newly match on turn 50 based on
conversation drift rather than session start).

---

## Summary of what the docs leave silent (all flags collected in one place)

1. The literal on-screen wording of the project-scoped MCP-server approval prompt.
2. Whether there is a non-interactive command to **grant** approval for one named server ahead of
   time (only `reset-project-choices`, which clears rather than grants, and the three settings-file
   keys, are documented — no `claude mcp approve <name>` verb).
3. Whether `mcp__*` (bare wildcard, all servers) is legal in `permissions.allow`/`deny`, versus only
   in a subagent's `disallowedTools` — only the latter usage is directly evidenced in what was
   fetched.
4. Whether the qualified tool name a subagent frontmatter/permission rule uses
   (`mcp__<server>__<tool>`) is byte-identical to what the model sees in its own tool-call schema —
   documented consistently as the *configuration* string, never directly restated as the
   *model-facing* string.
5. Whether `timeout` (hooks) accepts a fractional number of seconds, or `0`, and the precise
   wall-clock start point.
6. The non-plugin `mcpServers` key's role as an addressable "server name" outside `.mcp.json` itself
   (the plugin-scoped form `plugin:<name>:<server>` for hook `server` fields is documented; the
   ordinary case is inferred, not quoted).
7. Full enumeration of built-in tool name strings for subagent `tools:`/`disallowedTools:` (only a
   handful appear in examples on this page; the canonical list is presumably on a separate
   tools-reference page not fetched for this note).
8. Whether skill-description matching can trigger mid-session on conversation drift, or is
   effectively re-evaluated only per-turn against a static description set loaded at session start.

---

## Sources

1. [Hooks reference](https://code.claude.com/docs/en/hooks) — Claude Code Docs, fetched 2026-08-16
2. [Connect Claude Code to tools via MCP](https://code.claude.com/docs/en/mcp) — Claude Code Docs,
   fetched 2026-08-16
3. [Create custom subagents](https://code.claude.com/docs/en/sub-agents) — Claude Code Docs, fetched
   2026-08-16
4. [Extend Claude with skills](https://code.claude.com/docs/en/skills) — Claude Code Docs, fetched
   2026-08-16
5. [Settings](https://code.claude.com/docs/en/settings) — Claude Code Docs, fetched 2026-08-16
   (`settings.json` vs `settings.local.json`, precedence order, `permissions.allow`/`deny` MCP
   examples, `disabledMcpjsonServers` definition)
