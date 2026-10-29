# kiro-cli V3 agent engine vs V2 — differences and migration guidance (for Zikaron's kiro installer, hooks, MCP server and skills)

Research date: **2026-10-28**. Local binary named in the brief: kiro-cli **2.35.1** (V2 default; `--v3`, `--v2`,
`--agent-engine <v1|v2|v3>`). Author: memory-assistant, for memory-researcher. No shell was available to this
session, so **nothing below was measured on a binary** — every statement is from official docs, official
changelog, or a labeled third-party source. Where a statement is "documented", that means a kiro.dev page says
it; where the docs are silent the answer is **NOT DOCUMENTED**, and where pages disagree the disagreement is
recorded in §"Documentation conflicts".

Marking used throughout: **[DOC]** = stated on an official kiro.dev page; **[DOC-CONFLICT]** = official pages
disagree; **[INFERRED]** = my reading, not stated; **[NOT DOCUMENTED]** = official docs silent (a valid and
important answer); **[3P]** = third-party/community; **[LOCAL]** = this repository's own earlier measurement.

## Brief (restated)

Operator proposes dropping kiro V2 support and targeting V3 only. Zikaron's installer writes kiro artifacts
(agent configs at `.kiro/agents/<name>.json` with `hooks`/`mcpServers`/`allowedTools`, skills, an MCP server),
and runs hooks (`agentSpawn`, `userPromptSubmit`) and an MCP server inside kiro sessions. Eleven numbered
questions (agent configs, hooks, tool names, subagents, skills, MCP, session identity, workspace trust, models,
headless, release status), plus an addendum of six more: **12** kiro 3.0's own Memory feature, **13** expanded
hooks, **14** the improved trust model and local sandbox, **15** Workflows, **16** whether V2-style configs
keep working after the 3.0 auto-update, **17** exact release date and the auto-update/pin/opt-out mechanism.
The expected output is per-item answers with URL + quoted sentence, a breaking-changes list for an installer,
and versions/dates on every claim.

## Bottom line

1. **"Kiro CLI 3.0" is the version at which V3 becomes the default engine, scheduled "end of October" 2026
   (no day given in any official page).** As of 2026-10-28 the official changelog's newest entry is 2.34.0
   (2026-10-23); no 3.0 entry or "upgrading to 3.0" page exists. The local 2.35.1 is newer than the changelog
   index, so the index lags. There is **no documented V2 end-of-support date** and no statement that the V2
   engine is removed in 3.0; `--v2` is documented as a per-launch switch. [DOC]
2. **A V2 agent JSON is not silently read as-is.** A 2.x profile that carries `allowedTools` or `toolsSettings`
   and no `permissions` block is **skipped** by V3 ("falls back to another agent") until `/upgrade-agent`
   converts it, and the 3.0 switch "enables automatic agent upgrades" that rewrite `.kiro/agents/*.json` in place
   with `.json.bak` backups. Zikaron's shipped agents carry `allowedTools` (documenter, consolidator), so this is
   the single biggest installer risk. The upgrade yields a **"universal" (V2 + V3) config**, which means a
   V2-compatible and V3-compatible file can be one file — dropping V2 is not forced by the file format. [DOC]
3. **Hooks are the largest semantic change and the least documented.** New location/schema (flat array with
   PascalCase triggers; standalone `.kiro/hooks/*.json`; global `~/.kiro/hooks/`), `timeout` in seconds, and
   **no V3 page documents the stdin payload fields per trigger, a `prompt` field, a stdout size cap, or
   `timeout_ms`/`max_output_size` conversion**. Third-party testing on 2.13.0 found no prompt text in the
   `UserPromptSubmit` payload. Zikaron's push hook reads `prompt` from stdin — **this must be probed on a V3
   binary before any commitment.** [NOT DOCUMENTED + 3P]
4. **PreToolUse can block (exit 2 is the one code all sources agree on); whether PostToolUse stdout reaches the
   model is contradicted between official pages.** [DOC-CONFLICT]
5. **V3 trust model gates project agents, hooks, MCP servers, steering, skills, workflows in interactive V3
   sessions until the user trusts the folder** (CLI ≥ 2.33); headless `--no-interactive` and V1/V2 are not gated.
   Trust is recorded outside the repo, so an installer cannot pre-trust. [DOC]
6. **Kiro's own Memory (2.29+) is local, per user account, off by default in the IDE, with CLI access levels
   read & write / read only / off.** Storage under `~/.kiro/memories/`; recall mechanism (inject vs tool) is not
   documented. Coexistence with Zikaron is not addressed anywhere; it needs a measurement. [DOC + NOT DOCUMENTED]

## 11. Release status, the 3.0 date, deprecation, official migration pages (items 11 and 17)

**Documented facts, with dates**

- Blog "Kiro CLI V3 is rolling out as the default experience", published **2026-10-09**: V3 has been opt-in
  since June; "Starting October 12, we are gradually rolling out a startup prompt" to switch, "ahead of the CLI
  3.0 release by the end of October". [1] The same post says the "Don't ask again" choice "will not keep you on
  V2 and your setup will still be upgraded to V3 when CLI 3.0 is released at end of October." [1]
- Changelog 2.30.0 (**2026-10-12**): the startup prompt is rolling out gradually; "V3 becomes the default with CLI
  3.0 at the end of October". Choosing "Switch to V3 and upgrade my configs" saves V3 as the default harness,
  **enables automatic agent upgrades**, and starts migrating custom agent configs. [43]
- Changelog 2.28.0 (**2026-10-05**): an interactive **Classic** session on a host that can run 3.0 offers to
  switch; accepting sets 3.0 as the default, upgrades agent configs, and reruns the command in 3.0; declining
  re-asks about weekly. [42]
- Retirements stated with 3.0: inline shell autocomplete and the CLI desktop app; the **Classic** (non-TUI)
  experience is retired gradually and not supported in V3 (remove `--classic` from aliases). [1] Classic is a UI
  mode, not the V2 engine; the docs do not say the V2 engine is removed.
- V2 deprecation/removal date: **NOT DOCUMENTED.** The V3 landing page states no V2 retirement or end-of-support
  date; it says V3 "runs alongside your existing 2.x install" and "Use `--v2` when you need to return to a V2
  session". [2] The 2.x reference page "documents CLI 2.x behavior for users who haven't yet migrated to V3"
  (updated 2026-10-10) and states no support timeline. [34] The local `--help` text ("v2 … the pre-3.0 default")
  [brief, LOCAL] is consistent with V2 staying selectable in 2.35.x; whether the 3.0 binary keeps `--v2` is
  **NOT DOCUMENTED**.
- **Exact 3.0 release date: NOT DOCUMENTED.** Only "end of October". The coordinator-supplied launch notice in
  2.35.1 says the same [LOCAL, quoted in the task message]. The docs landing page is "updated October 13, 2026"
  and gives no release date. [2] A third-party tracker (Havoptic) lists a "v3.0.0" dated 2026-10-05 whose body
  is the 2.28.0 changelog text; that is a tracker artifact and is **not evidence of a release** [3P].
- **Official "upgrading to 3.0" page: none found.** The V3 landing page and migration guide are the closest; the
  blog links to `/docs/cli/v3/upgrade-agent/`, `/docs/cli/v3/acp-migration/`, `/docs/cli/v3/permissions/` and
  has no "Upgrading to 3.0" heading. [1][2][3] One search snippet had a V3 page saying a v2-config migration guide
  was "coming soon"; the live migration guide page has no such statement. [3] (the contradiction is in the search
  summary only — treat the live page as current.)
- Changelog index state at fetch time: newest entry **2.34.0 (2026-10-23)**; `https://kiro.dev/changelog/cli/2-35/`
  and `/3-0/` return 404. [38][brief]

**Auto-update mechanism, pinning, opt-out (item 17)**

- The statement "If you have auto-updates on, you'll be upgraded to 3.0 automatically" comes from the in-binary
  notice quoted by the coordinator [LOCAL]. **No kiro.dev page documents the 3.0 binary auto-update**; the blog
  talks about the *setup* being upgraded and mentions no auto-updates or pinning. [1] (Blog: "If you need to
  switch back to V2, run `kiro-cli --v2`. The flag applies to that launch only." [1])
- Opt out of background updates: `kiro-cli settings app.disableAutoupdates true`; on Windows the env var
  `KIRO_NO_AUTO_UPDATE` set to any value also disables background updates. [DOC] [33] The same key appears in
  the Settings reference (boolean, "Turns off background auto-updates"; default not documented). [31]
- Pinning: **not documented for individual users.** The enterprise page describes pinning by not publishing a
  version above the one a fleet runs on a mirror (`update.baseUrl` policy). There is no documented
  "install version X" command. [DOC] [33] `kiro-cli update` checks and installs from the configured mirror; on
  macOS it takes `--non-interactive`, `--relaunch-dashboard`, `--rollout`, not `--check`/`--force`. [33][30]
- Staying on the V2 *engine* after 3.0: only `--v2` per launch is documented, and it "overrides a saved
  `chat.agentEngine` value without changing it". [30] `chat.agentEngine` is mentioned only as what the startup
  offer saves (`v3`); it is **not in the Settings reference**. [2][31] Whether `kiro-cli settings
  chat.agentEngine v2` is honored after 3.0 is **NOT DOCUMENTED** (do not assume).

**Changelog digest, 2.8 to 2.34 (official; dates 2026)**

| Version | Date | Relevant change |
|---|---|---|
| 2.8.0 | Jun 17 | V3 early access via `--v3`; capability-based permissions, standalone hooks file format, tag-based agent config [38p3] |
| 2.13.0 | Jul 17 | Introspect subagent; global hooks in `~/.kiro/hooks/` [38p3] |
| 2.14.0 | Jul 22 | `/upgrade-agent` converts V2 agent configs "to a format that works in both V2 and V3" [38p3] |
| 2.18.0 | Aug 12 | nested `AGENTS.md` loaded as steering; cloud sessions opt-in [38p2] |
| 2.21.0 / 2.21.4 | Sep 1 / Sep 11 | `/config` panel, `/sessions` dashboard; `--v2` flag for one session [38p2] |
| 2.23.0 | Sep 21 | reasoning (thinking + effort) controls move into `/model` [38p2] |
| 2.24.0 | Sep 23 | `/tools trust-all`; **stops auto-loading project `.env` files into chats, MCP servers and tools** [38p2] |
| 2.25.0 | Sep 28 | **`SessionEnd` hook trigger** for V3 session teardown [38p2] |
| 2.26.0 | Sep 30 | opt-in Workflows; tighter approvals for hook/LSP file writes, MCP tools, shell in untrusted workspaces [38p2] |
| 2.27.0 | Oct 1 | "Workflows: sub-agent tool" setting; live file refs in steering; saved prompts as slash commands [41] |
| 2.28.0 | Oct 5 | Classic can switch to 3.0; **hooks match by tool category** in V3 [42] |
| 2.29.0 | Oct 9 | **Memory for local V3 sessions** [44] |
| 2.30.0 | Oct 12 | startup prompt to switch to V3; auto agent upgrade; model fallback notices [43] |
| 2.31.0 | Oct 13 | local command sandbox + autonomous mode for all V3 users; **MCP tools load on demand**; `KIRO_HOME` across V3 config/state [45] |
| 2.31.1 | Oct 14 | saved settings apply to headless V3 runs [38] |
| 2.32.0 | Oct 15 | non-interactive V3 cloud sessions; write approvals can cover a folder [38] |
| 2.33.0 | Oct 20 | **workspace trust screen for interactive V3**; model fallback restored [46] |
| 2.33.1 | Oct 21 | Workflows start only on request; fixes MCP setup and V2-to-V3 session resume [47] |
| 2.34.0 | Oct 23 | MCP elicitation in V3; memory deletion; (per permissions page) `--trust-workspace` [48][19] |
| 2.35.x | — | exists locally (brief); **not in the changelog index at fetch time** |

(Entries 2.17 and 2.16 and earlier: 2.17.0 Aug 11 cloud sessions preview; 2.16.0 Jul 31 tangent; 2.15.0 Jul 27
spec drafting; 2.12.0 and earlier MCP OAuth/hot reload items — none touch the questions here.)

## 1. Agent config files and schema (item 1 and 16)

**Does V3 still read `.kiro/agents/<name>.json`? Yes, with a compatibility gate.** Workspace `.kiro/agents/[name].json`
or `.md`; global `~/.kiro/agents/[name].json|.md`; workspace wins on a name collision; nested directories form
`team/planner`-style names. JSON and Markdown "have identical fields". [DOC] [13]

**New format: yes — Markdown with YAML frontmatter, body = system prompt.** Example in [5] has `name`,
`description`, `model`, `tools`, `excludedTools`, `includeMcpJson`, `includePowers`, `mcpServers`, `resources`,
`permissions`, `welcomeMessage` in frontmatter. [DOC] [5][14]

**Field status** [5][14] (all [DOC]):

| Field | V3 status |
|---|---|
| `name`, `description`, `prompt`, `model`, `mcpServers`, `resources`, `welcomeMessage` | carried over; `mcpServers` called "unchanged" in [14] but "New in profile" in [5] (**[DOC-CONFLICT]**); `upgrade-agent` lists all of them as passed through unchanged [4] |
| `tools` | **changed**: selectors and category tags `read`, `write`, `shell`, `web`, `subagent`; `knowledge` direct ID; `@builtin`, `@mcp`, `*` |
| `allowedTools`, `toolsSettings` | **2.x only / deprecated**; replaced by `permissions.rules` ("`toolsSettings` is removed in V3" [5]; "deprecated in CLI V3" and "still supported for settings `permissions` doesn't cover" [14] — conflict in strength) |
| `permissions` | **new**: `rules[]` of `capability`, `match` (globs), `effect` (allow/ask/deny), optional `exclude` |
| `excludedTools`, `includeMcpJson`, `includePowers` | **new** |
| `hooks` | **changed**: flat array, PascalCase triggers; object form accepted as "compatibility input" |
| `toolAliases`, `keyboardShortcut` | **not applied / not part of the V3 schema** [14] |
| `effort` | **NOT in the profile schema.** Effort is set via `/model`, `/effort <level>`, `--effort`, and persistent per-model defaults `chat.modelDefaults` in `~/.kiro/settings/cli.json` or `.kiro/settings/cli.json`. [29] No per-agent `effort` field is documented on [5], [13], [14] or [29]. (Workflow recipes have their own `effortLevel` [24].) |

**The compatibility gate (item 16).** [14]: a CLI 2.x JSON profile with `allowedTools` but no `permissions` block
"is skipped by V3 until `/upgrade-agent` converts it", and "profiles with unsupported trust fields fall back to
another agent until `/upgrade-agent` converts them". [5][13] say the same ("skipped until you run
`/upgrade-agent`"). **What the user sees when a profile is skipped is NOT DOCUMENTED** (no warning text on any
page read), and the migration guide says nothing about a missing `permissions` block. [3] Fields that are only
`name`/`description`/`model`/`prompt`/`resources`/`mcpServers`/`welcomeMessage` carry over "unchanged". [5]

**What the upgrade does** [4][1] (all [DOC]):
- `/upgrade-agent` (alias `run`) scans `.kiro/agents/` and `~/.kiro/agents/` (falls back to
  `.amazonq/cli-agents/` and `~/.aws/amazonq/cli-agents/`; if `KIRO_AGENT_CONFIG_DIR` is set, only that
  directory); `kiro-cli agent upgrade <dir>` does a directory non-interactively (top-level `*.json` only) with
  `--dry-run` and `--no-backup`; exit 0/1/2.
- Before writing, each original is copied to `<file>.json.bak` (numbered if one exists).
- Converts: old tool names to capability tags (both kept), `toolsSettings` to `permissions.rules`, `allowedTools`
  to capability-level allow rules, regexes to globs where possible, object-form hooks to the array form.
  Result is "universal (V2 + V3)". Dropped fields: **none listed**; hooks V3 cannot represent are dropped with an
  `unconvertible-hook` warning. [4][6]
- **Auto-refresh:** generated V3 fields are refreshed when V2 trust settings change; hand edits stop refreshing and
  the agent shows as "Universal · Out of Sync", and selecting it "rebuilds V3 from the V2 settings and overwrites
  your manual V3 edits". [4]
- **Does 3.0 upgrade agents automatically?** The upgrade page says upgrades are manual (`/upgrade-agent`); the
  startup choice "Switch to V3 and upgrade my configs" **enables automatic agent upgrades** (changelog 2.30.0,
  blog). [4][43][1] So: automatic only for users who took that choice or whom the 3.0 switch migrates
  (blog: setup "will still be upgraded when CLI 3.0 is released"). [1] The exact trigger set is not specified.
- **Installer-written agents:** the upgrade page mentions "externally managed agents" as skipped by the CLI
  command but does not define the term. **NOT DOCUMENTED** whether an installer-written file counts. [4]
- Validation: `kiro-cli agent validate --path <file>` exists. [3][30] [LOCAL] our earlier note that
  `agent validate` accepts an unknown tool name silently was for 2.28.0 (design/harness.md); V3 behavior not
  documented. [14] on unknown names in `tools`: "does not say".

**Implication for the installer [INFERRED, from LOCAL design/harness.md rows that say the shipped documenter and
consolidator configs carry `allowedTools`]:** under 3.0 those two files would be skipped or auto-rewritten unless
they also carry a `permissions` block. A `permissions` block alongside `allowedTools` gives a universal profile
V2 also reads (extra field), which would make V2 and V3 one file.

## 2. Hooks (item 2 and item 13)

### Where hooks live and the schema

- **Three locations** [DOC] [6][10]: (a) inline `hooks` array in an agent profile (scoped to that profile);
  (b) workspace standalone `.kiro/hooks/*.json`; (c) global `~/.kiro/hooks/*.json` ("loaded by Kiro CLI V3 only").
  Global and workspace "run alongside each other". Standalone hooks apply regardless of agent; the config
  reference recommends them for "automation that should work across agents". [14]
- **Standalone file:** top-level `"version": "v1"` and `hooks[]`; each hook `name` (required), `description`,
  `trigger` (required, PascalCase), `matcher`, `action` (`{type:"command", command}` or `{type:"agent", prompt}`),
  `timeout`, `enabled` (default true), `confirm` (Stop command hooks only). Any `.json` filename. [10]
- **Legacy object form** (`{"agentSpawn":[{"command":...}]}`) is "compatibility input"; `/upgrade-agent`
  flattens it and keeps the camelCase trigger as an alias; the migrated example shows `"timeout": 10`. [6][14]
- **Timeout:** `timeout` in **seconds**, default **60**, `0` disables, ignored for agent actions. [10][12]
  (The page [6] says units are not stated; [10] says seconds; [12] gives the default 60 without naming the unit.)
- **`timeout_ms`, `max_output_size` (65536), `cache_ttl_seconds`: not mentioned on any V3 page read.** How they
  convert, or whether they are honored in the array form, is **NOT DOCUMENTED**. [6][14] (migration guide says
  explicitly: not present). Our installer writes `timeout_ms` and `max_output_size` today [LOCAL].
- **Output size budget (hook stdout injected into context): NOT DOCUMENTED** for V3.

### Trigger list in V3 (official)

From [11] (trigger types page) and [6] (hooks migration):

| V3 trigger | 2.x name | CLI status | Can block? |
|---|---|---|---|
| `SessionStart` | `agentSpawn` (V3 accepts `AgentSpawn`/`agentSpawn` as compatibility spellings [11]) | V3 | No |
| `UserPromptSubmit` | `userPromptSubmit` | V3 | **CLI: no** ("CLI Prompt Submit Hooks cannot block" [11]; "the prompt is sent regardless of exit code" [6]) |
| `PreToolUse` | `preToolUse` | V3 | **Yes** |
| `PostToolUse` | `postToolUse` | V3 | No |
| `Stop` | `stop` | V3 | indirect: exit 1 or `{"decision":"block","reason":…}` asks Kiro to continue; "cannot reject an event with exit code 2" [6] |
| `SessionEnd` | — | **V3 only** ("fires when a CLI V3 session is torn down"; added 2.25.0) [11][38p2] | No |
| `PostFileCreate`, `PostFileSave`, `PostFileDelete` | — | V3; "agent-made file changes only" | No |
| `PreTaskExec` / `PostTaskExec` | — | V3; spec task execution | Pre: yes |
| `Manual` | — | listed; "`/hooks` doesn't provide an action to invoke them" [11] | n/a |

**Compaction hook: none exists in any V3 list read** ([6][11][36]); the compaction page mentions no hook. [35]
**Session-end hook: yes, `SessionEnd`, V3 only (2.25.0).** [11]

### Payload on stdin (what we read: `prompt`, `session_id`, `cwd`, `hook_event_name`)

- The docs say command actions receive "session context as JSON on STDIN" but give field lists only as examples:
  `SessionStart`/agentSpawn example = `hook_event_name`, `cwd`, `session_id`; `PreToolUse` example (MCP tool) =
  `hook_event_name: "PreToolUse"` (PascalCase), `cwd`, `session_id`, `tool_name: "mcp_postgres_query"`,
  `tool_input`. [DOC] [11] **Hook event names in V3 are PascalCase in the payload; the spawn example still shows
  the lower-case `agentSpawn`** — a hook that normalizes `hook_event_name` must accept both.
- **`UserPromptSubmit` stdin fields: NOT DOCUMENTED.** [10][11][12][6] The trigger page says "With a shell command
  action, the prompt is available as the `USER_PROMPT` environment variable." [DOC] [11] — an environment
  variable, not a payload field. **Third-party evidence (labeled):** a tester of V3 hooks on Kiro CLI 2.13.0
  (2026-07-20) "could not find the prompt text in the payload" [3P][53]; an empirical Kiro-IDE capture
  (IDE 1.0.242) found `prompt` present but empty and `USER_PROMPT` empty on 1.x [3P][54]; a community post
  (2026-06-22) does not list a prompt field. [3P][55] **Zikaron's `userPromptSubmit` push hook depends on
  `prompt`; this is [NOT DOCUMENTED] and must be probed.**
- `PostToolUse` payload (V3): documented only as having tool results; field names beyond the `tool_response` shape
  in 2.x are **not documented**. IDE empirical capture: `session_id`, `hook_event_name`, `cwd`, `tool_name`,
  `tool_input`, `tool_response`, **no success flag**, and `tool_input` empty (`{}`) for write/shell. [3P][54]
- V3 tool hook input in the Classic/V2 engine adds `tool_tags`; "Classic and V3 engines do not send `tool_tags`."
  [6] (This sentence is ambiguous on the page; it describes the V2 engine's tool hook input.)
- `session_id` is in the documented examples. Whether it equals the id `KIRO_SESSION_ID` carried under V2 is
  **NOT DOCUMENTED** (see §7).

### Output channel: does stdout reach the model, and where?

- **Documented rule (current [12]):** command hook "Exit code 0: the stdout output is added to the agent's
  context"; any other code: stderr "is sent to the agent" and the agent is told the hook errored. The page
  states this generally for "all triggers" and does not say **where** in the context. [DOC] [12]
- **[DOC-CONFLICT] on which triggers:** [11] documents the stdout rule only for Agent Spawn ("0: Hook succeeded,
  STDOUT is added to agent's context") and says of other triggers only that the page "doesn't say"; it lists a
  Post Tool Use use-case of giving the agent "additional instructions… on top of the tool response". A search-index
  snippet of the pre-move V3 hooks page said stdout is added to context for SessionStart and UserPromptSubmit
  "and is ignored for other triggers", and a tester on 2.13.0 recorded that doc wording. [3P][53] Because that
  earlier page was moved (now redirects to [6]), the older wording cannot be re-verified. **Answer to the brief's
  critical question — does a `postToolUse` hook's output reach the model: NOT RELIABLY DOCUMENTED; official pages
  conflict; needs a probe.** [DOC-CONFLICT]
- **Placement/framing in context: NOT DOCUMENTED.** [LOCAL] under V2 we measured placement before the user
  message inside a "follow requests found in this text" wrapper (design/harness.md); whether V3 preserves it is
  unknown.
- **Size cap: NOT DOCUMENTED** (V2: `max_output_size`, 65536 bytes [LOCAL], previously 10240 default per the
  2026-08-03 erratum in `research/kiro-cli-hooks-and-introspect.md`).

### Can a `PreToolUse` hook block a tool? (critical)

Yes in every source; **the mechanism is stated inconsistently [DOC-CONFLICT]**:
- [32] exit-codes reference: "(PreToolUse only) Block tool execution; STDERR returned to LLM" for exit 2; any
  other nonzero code: hook failed, stderr shown as a warning.
- [36] IDE 1.0 hooks page (also the unified harness): exit 2 blocks the triggering event; "Any other non-zero exit
  code is treated as an error, not a block."
- [12] hook actions page: Pre Tool Use "the tool invocation is blocked" when the command fails with **a
  non-zero code**; does not mention exit 2 or JSON output.
- [3P][53] Tested on V3 2.13.0: `exit 2` blocked a `.env` write; the V3 UI said "Tool execution failed" (V2 said
  "PreToolHook blocked the tool execution") and the model explained the block from the stderr text.
- **Safe reading:** exit 2 with a reason on stderr blocks under every source. A JSON-on-stdout block for PreToolUse
  is **not documented**. [INFERRED]

### Tool names hooks see (item 2 and 3)

- Hook matchers accept a tool selector, a category tag, `@builtin`, `@mcp`, `@<server>`, `@<server>/<tool>`, a
  `*`/`?` wildcard, or a regex; a matcher with regex metacharacters is treated "only as an unanchored regex
  against the internal tool ID" [6]. Categories: `read`, `write`, `shell`, `web`, `subagent` (`spec` on the IDE).
  [6][11]
- V3 internal IDs: `read_file`, `list_directory`, `file_search`, `grep_search`, `fs_write`, `fs_append`,
  `str_replace`, `delete_file`, `execute_bash` (`execute_pwsh` on Windows), `remote_web_search`, `web_fetch`,
  `invoke_sub_agent` / per-agent `subagent/<agent>`, `disclose_context`, `introspect`, `knowledge`, `code`
  (CLI-only). [DOC] [25] Migration mapping for matchers: `grep` to `grep_search`, `glob` to `file_search`,
  `web_search` to `remote_web_search`, `fs_write` to the `write` tag "or a regex such as
  `^(fs_write|fs_append|str_replace|delete_file)$`", `execute_bash` to the `shell` tag. [3]
- MCP tools in hook payloads use `mcp_<server>_<tool>` ("not `@server/tool`"). [DOC] [11]
- A third party observed on 2.13.0 that matcher `"write"` fired on `fs_write` because matching is an unanchored
  regex — anchor matchers for exact matches. [3P][53]
- **Under V3 a guard that wants "edit-like" tools must match four IDs (`fs_write`, `fs_append`, `str_replace`,
  `delete_file`)**, or use the `write` tag. The V3 `PreToolUse` `tool_input` for these (e.g., `path`, `text` on
  `fs_write`) is from the IDE capture [3P][54], not CLI docs.

## 3. Built-in tools in V3 (item 3)

[25] (all [DOC]): the full ID table is above. Key answers to the brief:

- `fs_read`/`read` → tag `read` covering `read_file`, `list_directory`, `file_search`, `grep_search`, `code`,
  `introspect` per the migration guide mapping (`read` replaces `fs_read, fsRead, read, grep, glob, code,
  introspect`). [3]
- `write` (2.x) → tag `write` covering `fs_write`, `fs_append`, `str_replace`, `delete_file`. **In-place edit:
  yes, via a separate `str_replace` tool** ("Replace exact text in a file (targeted edits)"); `fs_write` overwrites
  a whole file. [25]
- `shell`/`execute_bash` → `shell` tag; ID `execute_bash`. [25][3]
- `subagent`/`use_subagent` → tag `subagent`; ID `invoke_sub_agent` and per-agent `subagent/<agent>` tools.
  `agent_crew`, `delegate` replaced by sub-agents. [25][3]
- `knowledge`: selected by direct ID; CLI-only, experimental, **enabled by default in V3** (`chat.enableKnowledge`
  default true; disable with `false`). `code` intelligence on by default (`chat.enableCodeIntelligence`). [25][26][31]
- **Removed/not V3 built-ins:** `use_aws`/`aws`, `task`/`todo`/`todo_list` (rewritten to `todo_list`, which "selects
  nothing"), `goal`, `session`, `thinking`, `tool_search` (V2 tool). [25][3] **Note: our own config lists `task`
  in `tools` [LOCAL, research/kiro-cli-hooks-and-introspect.md]; V3 selects nothing for it.**
- **`introspect` as a tool still exists** in V3 (`introspect`, category context) and V3 adds an "Introspect
  subagent". [25][9]
- **Can a subagent spawn subagents in V3? NOT DOCUMENTED.** The subagents page "does not say". [15] The Workflows
  page implies a workflow step's agent may invoke sub-agents ("those sub-agents run outside the workflow's session
  tree") [24] — in the workflow context only. [INFERRED for general subagents: nothing]

## 4. Subagents (item 4)

[15] (all [DOC] unless noted):
- Tool: `subagent` (tag; `@builtin` also covers it); an orchestrator custom agent must list it in `tools`.
- Which configs: "Any custom agent can be a sub-agent." Selection by `description`, or by explicit name; an
  unknown name "fails rather than falling back". Two built-ins (context gathering, general purpose).
- Isolation: own conversation/context; **shared** with the main agent: steering, MCP servers, workspace file
  access, spec state, permissions configuration, **hook triggers**. The page lists hook triggers as shared but
  does not explicitly say hooks fire for subagent sessions. [DOC, implicit] [LOCAL] under V2, hooks were measured
  to fire for subagent sessions (2026-08-01 probe, design/architecture.md via design/harness.md).
- **Own MCP server process per subagent: not offered as a setting**; MCP servers are listed as shared with the
  main agent. A custom subagent only sees tools its own config lists. Process model (one per session vs per
  agent) is **NOT DOCUMENTED** (page [17] says the same). [LOCAL] V2: one MCP process per agent instance
  (research/kiro-mcp-lifecycle-probe.md).
- Parallel: with Workflows disabled, sub-agents run in parallel and the parent waits for all. With Workflows
  enabled, custom-agent delegation is launched "as a background workflow run" and the parent conversation
  continues; Ctrl+G checks long-running sub-agents. **Background subagents therefore exist in V3 only through
  Workflows.** No concurrency cap documented. Task graphs are DAGs planned upfront. [15]
- Permissions: `toolsSettings.subagent` `availableAgents` / `trustedAgents` is still named on this page even
  though `toolsSettings` is removed elsewhere — **[DOC-CONFLICT]**. The permissions page says subagents "inherit
  the parent's rules through deny-wins intersection". [19]

## 5. Skills (item 5)

- `.kiro/skills/<name>/SKILL.md` (workspace) and `~/.kiro/skills/` (global): **same location**; folder with
  required `SKILL.md` plus optional `scripts/`, `references/`, `assets/`. Frontmatter: `name` (must match folder;
  lowercase/digits/hyphens; max 64), `description` (required; max 1024), optional `license`, `compatibility`,
  `metadata`. Workspace beats global on a name clash. Follows the open Agent Skills standard. [DOC] [16]
- Invocation: automatic (matched on `description`) or `/skill-name [args]` slash command; `$ARGUMENTS` and `${N}`
  substitution are CLI-only. V3 built-in `disclose_context` tool "activates skills or steering files". Progressive
  loading: name+description at startup, full `SKILL.md` on activation, scripts/references on demand. [16][25]
- **Custom agents and skills [DOC-CONFLICT]:** [16] says custom agents do not load skills by default and must list
  them in `resources` as `skill://` URIs; [9] says skills "are automatically discovered and available to all
  agents in the workspace". Zikaron's skills are run by the invoking default session [LOCAL], so the conflict
  matters only if a skill is to be loaded inside a custom agent.
- Trust: workspace skills are **not loaded in an untrusted workspace**; writes to `.kiro/skills` ask. [19]
- **Skills format differences V2→V3: NOT DOCUMENTED** (the page links to "What's new in V3" and "2.x reference"
  and describes no differences). [16]

## 6. MCP (item 6)

- **Where config is read:** workspace `.kiro/settings/mcp.json`; user `~/.kiro/settings/mcp.json`; agent
  `mcpServers` field; Powers. Precedence (high to low): agent config, workspace, global; a same-named entry at a
  higher level **replaces** the lower one wholesale; different names all load. [DOC] [17] The agent profile can
  pull the file-based servers with `includeMcpJson: true` (adds servers from both `mcp.json` files). [14][5]
- Schema: stdio (`command`, `args`, `env`, `disabled`, `autoApprove`, `disabledTools`); remote (`url`, `headers`,
  `oauth`, `oauthScopes`). `${VAR}` expansion in `env` (the MCP page says "only … explicitly approved" variables
  expand; the V3 agent-config pages say env values "expand environment variables at runtime"). [17][5][14]
- **Timeouts:** `timeout` = connection handshake, default **60000 ms**; `requestTimeout` = per-call, default
  **120000 ms**. [DOC] [14] **[LOCAL conflict]:** under V2 we measured a 330 s MCP call completing with no
  `timeout` configured (design/harness.md row "MCP tool-call duration"). [14] calls `mcpServers` "unchanged"
  between 2.x and V3, yet a 120 s per-call default would have cut that call. Either the docs describe a new
  default, or V2 did not enforce it. **Unresolved — probe on V3 with a 150 s call before relying on the
  consolidator's 300 s planning wait; set `requestTimeout` explicitly in the config if it is honored.** [INFERRED
  risk]
- **Process model (per agent instance vs per session): NOT DOCUMENTED.** [17]
- **Tool names as the model sees them: NOT DOCUMENTED.** [18] shows approval-list examples of the form
  `mcp_aws_docs_search_documentation` and hook payloads use `mcp_<server>_<tool>`; the model-facing name is not
  stated. [LOCAL] under V2 we observed `zikaron_memory_search` with no server prefix.
- **On-demand loading:** changelog 2.31.0: "MCP tools now load on demand". [45] The MCP pages do not describe it;
  headless docs say V3 "applies saved compaction and Tool Search settings" (2.31.1+). [26] **Risk [INFERRED]:** the
  model may not see `zikaron_*` tools in its initial list (the same class of deferral we measured under Claude
  Code, design/harness.md "Tool availability to the model"). Settings key `toolSearch.enabled` was listed under 2.x
  in our earlier note; V3 behavior **NOT DOCUMENTED**.
- **Over-large tool result: NOT DOCUMENTED** (neither V2 nor V3; [LOCAL] "unmeasured").
- **Hot reload:** a watcher on `.kiro/agents` and `mcp.json`; only affected servers restart; applied "at the next
  idle boundary (between turns)". [17]
- **Elicitation** (2.34.0, local V3): MCP tools may pause and ask the user for a form or link. [18][48]
- **2.24.0: project `.env` files are no longer auto-loaded** into chats, MCP servers and tools. [38p2]
- **Untrusted workspace:** workspace MCP configuration is not loaded; "every MCP tool call asks for approval,
  including tools listed in `autoApprove`". [19][18] Docs caveat: configuration separation "does not isolate
  server access" — a workspace server runs with the user's privileges absent the sandbox. [search summary of
  MCP best-practices page, secondary]

## 7. Session identity and the session store (item 7)

- `KIRO_SESSION_ID` exported to hook/MCP processes: **NOT DOCUMENTED in V2 or V3** (searched; no official or
  community page names it). [LOCAL] we use it today (measured under V2). **It must be re-probed on V3.**
  The hook payload `session_id` field is documented in examples (§2). `/session-id` prints the current id. [27]
- Store: V3 "uses a separate session store"; V2 sessions are neither converted nor deleted; V2 cannot open a V3
  session; V3 can resume V2 sessions (blog: "V2 sessions can be resumed in V3, but V3 sessions cannot be resumed
  in V2"; 2.33.1 fixed a V2-to-V3 resume bug). [DOC] [1][3][47] The session-management page says sessions are in a
  local SQLite database under `~/.kiro/`, keyed by directory, UUID ids, owner-only access; `KIRO_HOME` (V3,
  2.31.0+) relocates "config, sign-ins, sessions, and agent state". [27][31][45] Back up `~/.kiro/sessions`
  before trying V3 (blog). [1]
- `--resume`, `--resume-id <ID>`, `--resume-picker`, `--list-sessions`, `--delete-session`, `--sessions` (V3
  dashboard). In V3, an unmatched `--resume-id` no longer silently starts a replacement. [27] **Whether the id
  survives `--resume` is implied by `--resume-id` semantics but not stated; NOT DOCUMENTED for hook/MCP
  `session_id`.** `--session-source v1|v2` appears in the local `--help` [brief] but **not on any docs page**
  read. [30]
- Compaction in V3 "records the compaction summary as a checkpoint marker within the same session" (V2 forked a
  new session). [34][9] Session id behavior across compaction: **NOT DOCUMENTED**. [35]
- A tangent "is a full session"; whether it gets a new id: **NOT DOCUMENTED**. [37]

## 8. Workspace trust and headless (item 8; addendum 14)

**What is gated (interactive V3, CLI ≥ 2.33.0, 2026-10-20)** [DOC] [19][46]:
- Trust screen on first launch in a folder, before any folder config loads: "Trust, continue" / "Don't trust,
  exit". Declining exits without loading anything.
- Until trusted: the folder's **hooks, agents, MCP servers, steering, workflows and language-server config** are
  not loaded (changelog 2.33.0 [46]). The permissions page's list names "custom agents, Steering files, MCP server
  configuration, or Skills" plus workflow files [19]; hooks appear in [46] and [9] but not in that sentence —
  **[DOC-CONFLICT, minor]**; treat hooks as gated.
- Also while untrusted: asks before every shell command (incl. background), every MCP tool call (even
  `autoApprove`), Power use; the agent cannot add/change/delete memories, knowledge bases or remote learnings
  (reading works); writes to the memory database and session store are refused without a prompt. [19]
- Always asks, trusted or not: writes to `agents`, `hooks`, `workflows`, `powers` directories (by the agent). [19]
  The installer is a separate process, not the agent [INFERRED: not covered by this].
- **Recording:** `workspaceTrusted` in a per-workspace permissions file under `~/.kiro/workspace-roots/` (outside
  the repo, "so a cloned repo can't grant itself trust"); revoke by deleting that line; home directory is never
  saved (asked every launch). `--trust-workspace` (CLI ≥ 2.34.0, V3) trusts one launch without saving. The
  workspace `permissions.yaml` lives at `~/.kiro/workspace-roots/<hash>/permissions.yaml`. [19][7]
  **An installer cannot pre-trust a workspace through any documented path** [INFERRED from "stored outside the
  repository"]; the analogous Claude Code gate is the user's own too (design/harness.md "Approval gates").
- **Not gated:** "`--no-interactive` runs are not gated. They load workspace configuration without asking, as
  before"; V1/V2 sessions are not gated. [19] Headless: "When no interactive client is available, every `ask`
  is treated as a deny" — only explicitly allowed operations run. [19] V3 non-interactive runs load hooks from the
  selected agent and workspace since **2.27.1**, and "A `PreToolUse` Hook can deny a tool call". [26]
- Headless flags: `--no-interactive`, `--trust-all-tools` (also auto-approves hook confirmation requests),
  `--trust-tools=<exact V3 internal IDs>` (honored only with `--no-interactive`; ignored by the interactive V3
  TUI), `--sandbox`, `--require-mcp-startup` (V3 exit code 3), `--agent`, `--model`, `--effort`. Exit code 4: the
  named agent is unavailable (also for a fresh V3 run whose `chat.defaultAgent` is unavailable). [26][32]
- **Headless authentication: "Headless mode requires an API key set as the `KIRO_API_KEY` environment
  variable"; API keys limited to Pro/Pro+/Pro Max/Power.** [DOC] [26] Whether `--no-interactive` with a logged-in
  session still works (as in our live tests today [LOCAL]) is **NOT DOCUMENTED**.

**Local command sandbox (addendum 14)** [DOC] [20][45]:
- Off by default; Kiro CLI ≥ 2.31 (2026-10-13), local V3 sessions only; macOS Seatbelt, Linux **bubblewrap**
  required (+ `socat` for some network modes), Windows needs setup for some modes.
- Wraps the agent's shell commands and their children. "The agent harness stays outside the sandbox"; built-in
  file tools run outside it; remote MCP servers are outside it. Stdio MCP servers are wrapped **only** if
  `mcpSandboxing: true` (default false).
- **Hooks: not mentioned on the sandbox page — NOT DOCUMENTED whether hook processes are sandboxed.** The statement
  that the harness stays outside suggests they are not [INFERRED, weak].
- **Filesystem write limits (workspace-only? temp dirs?): NOT DOCUMENTED**; the page says `fs_read`/`fs_write`
  permission rules "shape which paths sandboxed commands can see and write". **Unix domain sockets: not
  mentioned.** Network modes `DEFAULT_BLOCKED` (default), `COMMON_DEPENDENCIES`, `DEFAULT_ALLOWED`. Config:
  `sandbox.json` global (`$KIRO_HOME/settings/` or `~/.kiro/settings/`) and project `.kiro/settings/`; a project
  file can only tighten an active global policy. "The sandbox reduces what a command can do; it is not a
  guarantee of isolation." So whether a sandboxed shell command (e.g., a typed `zikaron …` command) may reach a
  Unix socket under `$XDG_RUNTIME_DIR` is **not answerable from the docs**; it is only relevant if the user
  enables the sandbox, which is opt-in.

## 9. Models (item 9)

- Models page lists **Claude Haiku 5.5**, Haiku 4.5, Sonnet 5.5/5/4.6/4.5/4.0, Opus 5.5/5/4.8/4.7/4.6/4.5, Claude
  Fable 5.1 (Enterprise, US East), GPT-5.6 variants, Auto. [DOC] [28] (One table, not CLI-specific.) [LOCAL]
  design/harness.md records `--list-models` offered **no Haiku 5.5 on 2026-10-20** — so docs-listed does not mean
  the CLI offers it to this account; the docs page does not cover `--list-models`.
- `kiro-cli chat --list-models` under V3 (and `--format json`): the flag is documented, "Displays available
  models"; **whether V3 output differs is NOT DOCUMENTED.** [30]
- Agent `model` resolution: must match an id from Kiro's model service. "If the specified model is unavailable,
  the first prompt can fail instead of falling back automatically." In the V3 TUI an unavailable agent model "stays
  selected" and the UI reports requests will fail. An explicit `--model` overrides the agent; `chat.defaultModel`
  applies only when the agent has no model. [DOC] [14][5] **Headless V3 skips the TUI availability check; if the
  model cannot be set it writes a warning to stderr and continues.** [26] **[LOCAL] V2: silent fallback to the
  default** (design/harness.md). So V3 is a change from silent fallback to "first prompt may fail" (TUI) or "warn
  and continue" (headless) — exact behavior for an unknown id is **NOT DOCUMENTED** and the install-time
  `--list-models` check is still the safe measure.
- Model fallback: V3 can move a turn to another model when the current one declines/unavailable (2.30.0, 2.33.0;
  `/model fallback <id>`). [28][43][46]
- Effort: `low|medium|high|xhigh|max`; set per session, via `chat.modelDefaults`; no agent-level field. [29]

## 10. Headless runs and stream-json (item 10)

- `--no-interactive`, `--output-format stream-json` ("Emits JSON Lines on stdout. Requires V2 or V3") — both
  documented on [26]. **Event type names and field schemas are NOT DOCUMENTED on any page read**; the docs say
  only: each line is a JSON object; in V3 an interrupted run writes a final interruption record to treat as the
  end; workflow progress is emitted as it happens with final outcomes `completed|failed|aborted|paused`. [26]
- **The brief's "ACP events" for stream-json is not documented.** The ACP migration page [8] covers the
  `kiro-cli acp` server (standard `session/update` notifications routed by `sessionId`; `toolCallId`; permission
  requests via `options[]`; V3 rejects `--agent`, `--model`, `--effort`, `--trust-all-tools`, `--trust-tools` on
  `acp`) and says nothing about stream-json. Treat stream-json's shape as unknown until captured.
- Other V3 headless facts [26]: `KIRO_HEADLESS_WORKFLOW_TIMEOUT_SECS` (default 21600) bounds how long a
  non-interactive run waits for in-flight workflows; saved settings apply to headless V3 runs (2.31.1+);
  `--require-mcp-startup` exits 3 on failure; `--agent` unavailable exits 4.

## 12. Kiro 3.0's own Memory (addendum 12)

[DOC] sources: [21] docs/memory, [22] blog, [44] changelog 2.29.0, [19], [48].

| Question | Answer |
|---|---|
| Availability | Local V3 sessions, CLI ≥ **2.29.0 (2026-10-09)**, IDE ≥ 1.4.0. Cloud sessions: not listed. |
| What is stored | Records `{title, description, content}`, a type (Preference / Fact / Other) and a location (Global or a repository); "not a copy of a past conversation". Example kinds: repository commands/conventions, corrections, debugging insights, approaches ruled out, work preferences. Overlaps Zikaron's tribal-knowledge scope almost exactly. |
| Where | "stored locally per user account, not per workspace"; the permissions page names the database as under `~/.kiro/memories/` (writes to it are refused without a prompt in an untrusted workspace). **File format and schema: NOT DOCUMENTED.** Shared between Kiro IDE and CLI on one machine; each app has its own on/off setting. No cloud storage statement ("stay local to your machine"). |
| Scope | per user account; each memory Global or repo-scoped. No per-project directory like `.zikaron/`. |
| Written how | **Automatically by the harness** ("can identify useful context and create or refine a memory") at access level "read & write" with "Automatic memory updates" on (changes to that toggle apply immediately; also "including after a session ends"); otherwise only when asked. The underlying tool is **not named**; chat shows "Memory created"/"Memory accessed"; a changelog example shows an entry `command=get` with the memory's title. |
| Recalled how | "Kiro can retrieve a matching memory while it works"; **injection vs tool call is NOT DOCUMENTED.** Context Usage view (IDE) has a Memory row; "Using memory can increase context usage." |
| User-editable | `/memories`: `list` to search/preview/open (read-only listing); **delete from `/memories` since 2.34.0 (2026-10-23)**; changing content = ask Kiro in chat (trusted workspace only). Direct file editing: **NOT DOCUMENTED.** |
| Disable | `/memories` then `config`: **read & write / read only / off**; takes effect next session. **Default: Off in the IDE** (docs: "The default is Off"; blog: "off by default for this launch"); **the CLI's default is not stated** on the pages read. User-level setting only; workspace settings have no effect (IDE). No settings key for CLI listed in the Settings reference. |
| Trust | In an untrusted workspace it can read but not write/delete. |

**Coexistence with Zikaron [INFERRED — no source addresses third-party memory servers]:** no conflict mechanism
exists at the config level (Zikaron's store is a separate MCP server and hook; Kiro's is harness-internal under
`~/.kiro/memories/`). Real risks: (a) **overlap/duplication** — both capture "approaches already ruled out",
commands, conventions, and Kiro's agent may autonomously write to its store the same facts the Zikaron write
policy asks it to `remember`; (b) **two injection/retrieval paths into one prompt** (Zikaron's push block plus
Kiro's recalled memories) with unknown relative ordering; (c) **scope mismatch** (Kiro: per user account,
global-or-repo; Zikaron: per project directory, D8). It is opt-in/off by default in the IDE, so a Zikaron
install does not need to disable it, but whether to ask the user to set `/memories` to off or read only, is a
product decision the docs do not make for you. Measure: with both enabled, count duplicate facts and token
overhead of recalled memories on a fixed task.

## 13. "Expanded hooks" (addendum 13) — summary

See §2. Concretely, the answers asked:
- **Full trigger list:** `SessionStart` (with `AgentSpawn`/`agentSpawn` accepted), `UserPromptSubmit`, `PreToolUse`,
  `PostToolUse`, `Stop`, `SessionEnd` (V3, 2.25.0), `PostFileCreate`, `PostFileSave`, `PostFileDelete`,
  `PreTaskExec`, `PostTaskExec`, `Manual` (listed, not invocable). [11][6]
- **Inject text into the model after a tool call:** **unresolved** (official conflict; §2). The only documented
  PostToolUse effects are: "access to tool results", a stated use case of giving "additional instructions…
  on top of the tool response", the general stdout rule in [12], and a block-on-failure message path
  ("stderr is sent to the agent" on non-zero exit, [12]). A non-zero exit on a post hook sending **stderr to the
  agent** is the most-documented route to the model [DOC, [12]] but it is a failure-path channel — a probe must
  establish what stdout does at exit 0.
- **Block a tool call:** yes, `PreToolUse` (exit 2). Also matchers by category since 2.28.0. [42]
- **Fire on session end:** yes, `SessionEnd`. **Fire on compaction:** no trigger documented. [11][35]
- Also new: `agent` action type (a hook that injects a prompt into the conversation and "consumes credits because
  [it starts] a new agent loop"), `confirm`/`confirmCommand` on `Stop` command hooks, `enabled` flag. [10][12]

## 14. Sandbox and trust — see §8.

## 15. Workflows (addendum 15)

[DOC] [23][24][49 settings][15]:
- **What:** declarative multi-agent plans ("recipes") run by the Kiro runtime: nodes `step`, `sequence`,
  `repeat`, `parallel`, `watch`; each step is one agent in its **own fresh session**; handoffs by text
  (`{{previous.output}}`) or file artifacts; loops need a finite `maxIterations`; max 50 step nodes, nesting
  depth 8. Recipes: JSON/YAML in `.kiro/workflows/*.workflow.json|yaml|yml` (workspace), `~/.kiro/workflows/`,
  account-synced, bundled (`investigate`, `feature-pipeline`, `publish-pr`; bundled agents `wf-planner`,
  `wf-coder`, `wf-design`).
- **Enablement:** opt-in. `chat.enableWorkflows` (restart required) and `chat.workflowLaunch` default
  `when-asked` (also `large-tasks`, `delegate-all`) in V3; CLI ≥ 2.34.0 has the three-mode setting; since 2.33.1
  enabling no longer starts one automatically. Interactive V3 shows a plan for approval before steps run;
  `/workflow run <name> --task "…"` opens a form. Not loaded from an untrusted workspace's `.kiro/workflows/`.
  Headless V3 runs wait up to `KIRO_HEADLESS_WORKFLOW_TIMEOUT_SECS` (default 6 h) for in-flight workflows.
- **Replacement for a skill that loops over subagents? Not documented, and by the documented features probably
  not for Zikaron's documenter loop [INFERRED]:** there is **no for-each construct over a list**; the closest
  documented pieces are `repeat` with `stopCondition` (`containsText`, `completionSignal`, `fileCheck`) and
  `watch` with `handler: "command"` (poll interval minimum 10 s for `command`). A step's agent must be
  "workflow-capable" — "A built-in sub-agent is not a valid workflow step agent" — while nested sub-agents inside
  a step "run outside the workflow's session tree" and cannot signal the parent step. It is opt-in per user (an
  installer cannot enable it for the user other than by a setting the user must take), carries plan-approval
  friction, and the docs warn it uses more tokens. The page does not compare Workflows with Skills.
  (Zikaron's current design runs the loop in a session-spawned background orchestrator under Claude Code and in
  the invoking session under kiro [LOCAL, CLAUDE.md D39].)

## 16. Does 3.0 still read V2-style files, or only V3 formats? (addendum 16) — answer by artifact

| Artifact | 3.0 / V3 | Marking |
|---|---|---|
| `.kiro/agents/*.json` | Read; JSON and `.md` both valid. **Skipped / falls back to another agent** if it has `allowedTools` or `toolsSettings` and no `permissions` | [DOC] [14][5][13] |
| agent `mcpServers` | Read; "unchanged" | [DOC] [14] (conflicts with [5]'s "New in profile") |
| agent `hooks` object form | Accepted as compatibility input; flattened by `/upgrade-agent`; `timeout_ms`/`max_output_size`/`cache_ttl_seconds` handling unstated | [DOC] [6][14] + [NOT DOCUMENTED] |
| agent `hooks` array, PascalCase | Native V3 form | [DOC] |
| `.kiro/hooks/*.json` | Native V3, versioned, standalone; global `~/.kiro/hooks/` | [DOC] [10] |
| `.kiro/skills/<name>/SKILL.md` | Same location and format | [DOC] [16] |
| `.kiro/settings/mcp.json` | Read; included in a profile with `includeMcpJson: true` | [DOC] [17][14] |
| `toolAliases` | Not applied | [DOC] [14] |
| `tools: ["read","write","grep","glob","shell","code","knowledge","@zikaron"]` | Legacy names are mapped to tags by the upgrader and "both are kept"; whether a hand-written profile with `grep`/`glob` selectors loads without upgrading is **NOT DOCUMENTED** | [DOC] [4] + [NOT DOCUMENTED] |
| `task` in `tools` | Selects nothing in V3 | [DOC] [3] |

**So: a V2-style config does not "silently stop working" wholesale; the specific failure is any profile with
legacy trust fields and no `permissions`, which V3 skips and (in a session started with it) replaces by another
agent, with no documented warning text.** [DOC for the skip; NOT DOCUMENTED for any message] Also: in
interactive V3 a *project's* agents, hooks and MCP servers do not load at all until the user trusts the folder.

## Breaking changes that affect an installer writing kiro artifacts (ordered by risk)

1. **Agent profiles with `allowedTools` / `toolsSettings` and no `permissions` are skipped in V3** (fall back to
   another agent) and are rewritten in place (with `.json.bak`) by auto-upgrade. Fix direction: emit a universal
   profile that also carries `permissions.rules` (V3 form) alongside `allowedTools` (V2 form), or write
   Markdown profiles for V3 only. [DOC][INFERRED fix]
2. **`UserPromptSubmit` payload's `prompt` field is undocumented in V3**; a `USER_PROMPT` env var is documented
   instead for shell hooks; one 3P tester found no prompt in the payload (2.13.0). The push hook may receive no
   query. Probe first. [NOT DOCUMENTED + 3P]
3. **Hook configuration schema moved**: array with PascalCase triggers; `timeout` seconds (default 60) replaces
   `timeout_ms`; `max_output_size` and `cache_ttl_seconds` unmentioned; object form is compat-only. Standalone
   hooks apply to **all agents** (including subagents and consolidator/documenter) rather than being scoped to
   the agent file. [DOC]
4. **Trust gate**: interactive V3 will not load the project's `.kiro/agents`, hooks or MCP servers until the user
   confirms "Trust this workspace?"; the installer cannot pre-trust (record is in `~/.kiro/workspace-roots/`).
   Headless is not gated. [DOC]
5. **Tool vocabulary**: tags (`read`, `write`, `shell`, `web`, `subagent`) plus IDs; `grep`/`glob` map to
   `grep_search`/`file_search` in hook matchers; `fs_write` edit coverage needs `fs_write|fs_append|str_replace|
   delete_file`; MCP tools in hook payloads are `mcp_<server>_<tool>`; `task`, `delegate`, `tool_search`,
   `use_aws` gone. [DOC]
6. **MCP per-call timeout default 120 s** is documented (`requestTimeout`) against our V2 measurement of a 330 s
   call completing; unresolved. [DOC + LOCAL]
7. **MCP tools "load on demand" (2.31.0)** — may change whether `zikaron_*` tools are in the model's initial tool
   list. [DOC for the changelog line; effect NOT DOCUMENTED]
8. **Unknown model id**: V2 silent fallback; V3 TUI "first prompt can fail", headless warns and continues. [DOC]
9. **Session store separate; `KIRO_SESSION_ID` undocumented; compaction continues the same session** (no fork).
   Zikaron's session label ladder relies on the id. [DOC + NOT DOCUMENTED]
10. **`--classic` / Classic UI retired; inline autocomplete and desktop app retired**; only the TUI. [DOC]
11. **Config path moves with `KIRO_HOME`** (V3, 2.31.0+). [DOC]
12. **`.env` no longer auto-loaded** into MCP servers/tools (2.24.0). [DOC]
13. **Hooks may now fire on more events** (`SessionEnd`, file events) and tool-category matchers broaden
    (`read` covers `grep_search`, `file_search`, `code`, `introspect`, …): a V3 `PostToolUse` matcher meant for
    one tool name can match a group. [DOC]

## Documentation conflicts register

| # | Conflict | Sources |
|---|---|---|
| C1 | Does PostToolUse stdout reach the model; which triggers add stdout to context | [12] general rule vs [11] only Agent Spawn documented vs earlier V3 wording (search snippet, [3P][53]): SessionStart and UserPromptSubmit only |
| C2 | PreToolUse block: any non-zero vs exit 2 only | [12] vs [32], [36] |
| C3 | UserPromptSubmit can block? | [11] "CLI … cannot block", [6] "sent regardless" vs [36] exit 2 blocks (IDE) and [12] "blocked" |
| C4 | `mcpServers`: unchanged vs "New in profile" | [14] vs [5] |
| C5 | `toolsSettings`: removed vs deprecated-but-supported; subagent page still uses `toolsSettings.subagent` | [5] vs [14] vs [15] |
| C6 | Custom agents load skills by default or not | [16] vs [9] |
| C7 | Hooks gated while untrusted? | [46], [9] yes vs [19]'s enumerated sentence omits hooks |
| C8 | Hook `timeout` unit | [10] seconds vs [6] "not stated" |
| C9 | V3 migration guide "coming soon" | a search snippet vs live [3] (no such line) |
| C10 | MCP env `${VAR}` expansion approval | [17] approved-only vs [5][14] "expand at runtime" |
| C11 | `requestTimeout` default 120 s vs our 330 s V2 measurement | [14] vs [LOCAL] |

Old doc paths in earlier research notes now redirect: `/docs/cli/hooks/` → `/docs/hooks/`;
`/docs/cli/v3/hooks/` → `/docs/cli/v3/hooks-migration/`; `/docs/cli/reference/exit-codes/` →
`/docs/reference/exit-codes/`. [fetch results] The earlier note's §2 "V3 divergence" (hooks as standalone files)
is **confirmed** by the V3 pages, and the earlier erratum's doubt ("whether the array format is what the V3 note
was describing") is resolved: yes, the array form is the V3 inline form and the standalone files are the same
documents. [DOC] [6][10]

## Probes to run (the docs cannot answer these)

Run on a binary where V3 is the engine (`kiro-cli --v3`, 2.35.1 or 3.0), once, with a logging hook:
1. `UserPromptSubmit`/`SessionStart`/`PostToolUse`/`PreToolUse` stdin payloads, exact field names, event-name casing
   and whether `prompt` is present; `USER_PROMPT` env.
2. Does exit-0 stdout of `PostToolUse` reach the model (put a canary string, ask the model to repeat it)? Where do
   `SessionStart`/`UserPromptSubmit` outputs land relative to the user message? Is there a size cap, and does a
   hook emitting 100 KB truncate silently?
3. `KIRO_SESSION_ID` presence in hook and MCP server environments; `session_id` stability across `--resume` and
   compaction; whether hooks fire for subagent sessions.
4. MCP: model-facing tool name; whether `zikaron_*` tools are present initially with on-demand loading; a 150 s
   and a 330 s tool call with and without `requestTimeout`; one process per session or per agent.
5. A 2.x-style agent JSON (with `allowedTools`, no `permissions`) launched with `--agent` in `--no-interactive` and
   in the TUI: what is shown, and which agent actually runs. The same file after `kiro-cli agent upgrade --dry-run`
   (diff of the rewrite; whether `timeout_ms`/`max_output_size` survive).
6. Unknown model id in an agent file: TUI and headless behavior.
7. With Kiro Memory on (read & write) and Zikaron installed: dedup rate and tokens.
8. `--output-format stream-json` capture of one run (event names/fields).
9. Sandbox on: can a sandboxed shell command and a hook process connect to a Unix socket under `$XDG_RUNTIME_DIR`?

## Search queries and methodology

Tool: WebSearch (standard mode) and WebFetch. Note on method: WebFetch returns a small model's extraction of the
page, so quoted sentences are as returned by the fetch tool and were not diffed against raw HTML; I re-fetched
twice (`configuration-reference`, `migration-guide`) with narrow prompts to confirm load-bearing claims
(`requestTimeout`, skipped agents). Queries run:
- "kiro-cli 3.0 V3 agent engine default migration guide"
- "Kiro CLI V3 memory feature /memories docs local memory sessions where stored"
- "Kiro workspace trust hooks agents MCP servers untrusted workspace V3 docs"
- "Kiro CLI local sandbox command sandbox V3 workflows docs"
- "Kiro CLI 3.0 released changelog October 2026 auto-update upgrade"
- "kiro-cli update auto-update disable setting … version pin install specific version"
- "Kiro hooks PreToolUse exit code block tool stdin JSON payload UserPromptSubmit prompt field V3 hook output context"
- "KIRO_SESSION_ID environment variable hooks MCP server kiro-cli"
- "kiro-cli --output-format stream-json event types JSON lines example headless V3"
- "github kirodotdev Kiro cli issues V3 hooks …" (no GitHub issues found; kiro-cli's source repository was not
  located, so no source-level confirmation is available)
Fetched in full: items [1]–[48] below. Not fetched: the sidebar pages `/docs/steering/`, `/docs/powers/`,
`/docs/cli/setup/`, `/docs/cli/acp/`, `/docs/configuration/` (cited via search summaries only where noted), the
`/docs/cli/v3/` "Reasoning effort" detail beyond [29], the Crew docs.

## Evidence quality and debate

- All V3 documentation is **new and visibly in motion**: pages moved during the last weeks, several pages
  contradict each other (§"Documentation conflicts"), changelog entries 2.31+ have empty "Improvements/Fixes"
  lists in the fetched text, and the 2.35.x line is absent from the changelog. Treat docs as intent, not
  behavior; the hook payload and output-channel questions are exactly where docs are thinnest.
- Third-party evidence is small: one Japanese write-up testing V3 hooks on 2.13.0 (a July build, with the docs of
  that month), one community summary of the docs (not a test), one empirical IDE-hook capture (IDE, not CLI). All
  are labeled [3P] and none overrides official text.
- No source measures anything about Kiro Memory, only documents it.
- No official statement exists on: V2 removal date, the 3.0 day, the auto-update mechanism for the 3.0 binary,
  pinning for individuals.

## Open questions and leads

- Run the probe list above; the three load-bearing for the decision to drop V2 are the `prompt` payload field,
  `KIRO_SESSION_ID`, and the skipped-agent behavior.
- Capture kiro's own embedded documentation for V3 hooks through the `introspect` tool inside a `--v3` session
  (the 2026-08-03 erratum in `research/kiro-cli-hooks-and-introspect.md` shows the embedded docs were more
  precise than the web docs for 2.16.0). That would also answer C1–C3 from the binary's own doc commit.
- Watch https://kiro.dev/changelog/cli/ for the 3.0 entry and a possible "Upgrading to 3.0" page; re-run the
  release-status section when it lands. Revisit once 2.35.x notes appear.
- Whether a universal profile (V2 fields plus `permissions`) loads cleanly in 2.35.1 V2: the docs say the upgrade
  yields one, so a test with `kiro-cli chat --v2 --agent <x>` would confirm "dropping V2 is optional".
- Which is more robust for Zikaron's hooks under V3: inline array in the agent profile (agent-scoped) or
  standalone `.kiro/hooks/*.json` (all agents; would also fire for the consolidator/documenter and for subagent
  sessions) — a design question the docs make real but do not answer.

## Sources

Official kiro.dev (fetched 2026-10-28):
1. Kiro CLI V3 is rolling out as the default experience — blog, 2026-10-09, Pooja Giri & Jay Raval — https://kiro.dev/blog/cli-3/
2. What's new in V3 (landing; "Page updated: October 13, 2026") — https://kiro.dev/docs/cli/v3/
3. CLI 2.x to V3 Migration Guide — https://kiro.dev/docs/cli/v3/migration-guide/
4. Upgrading agent configs — https://kiro.dev/docs/cli/v3/upgrade-agent/
5. Agent config changes in CLI V3 — https://kiro.dev/docs/cli/v3/agent-config/
6. Hooks migration (V3) — https://kiro.dev/docs/cli/v3/hooks-migration/
7. Permissions migration (V3) — https://kiro.dev/docs/cli/v3/permissions/
8. Migrate an ACP client to CLI V3 — https://kiro.dev/docs/cli/v3/acp-migration/
9. New features in V3 — https://kiro.dev/docs/cli/v3/new-features/
10. Hooks (features) — https://kiro.dev/docs/hooks/
11. Hook triggers — https://kiro.dev/docs/hooks/types/
12. Hook actions — https://kiro.dev/docs/hooks/actions/
13. Custom agents — https://kiro.dev/docs/custom-agents/
14. Agent configuration reference (IDE 1.0 / CLI V3) — https://kiro.dev/docs/custom-agents/configuration-reference/
15. Sub-agents — https://kiro.dev/docs/custom-agents/subagents/
16. Skills — https://kiro.dev/docs/skills/
17. MCP configuration — https://kiro.dev/docs/mcp/configuration/
18. MCP usage (tools) — https://kiro.dev/docs/mcp/usage/
19. Permissions (incl. Workspace trust) — https://kiro.dev/docs/permissions/
20. Local command sandbox — https://kiro.dev/docs/sandbox/
21. Memory — https://kiro.dev/docs/memory/ (CLI/Web tabs missing from the fetched text)
22. Introducing memory in Kiro IDE and CLI — blog — https://kiro.dev/blog/memory-in-ide-cli/
23. Workflows — https://kiro.dev/docs/workflows/
24. Author workflows — https://kiro.dev/docs/workflows/authoring/
25. Built-in tools (V3) — https://kiro.dev/docs/tools/
26. Headless mode — https://kiro.dev/docs/cli/headless/
27. Session management — https://kiro.dev/docs/cli/chat/session-management/
28. Models — https://kiro.dev/docs/models/
29. Reasoning effort — https://kiro.dev/docs/models/effort/
30. CLI commands reference — https://kiro.dev/docs/reference/cli-commands/
31. Settings reference — https://kiro.dev/docs/reference/settings/
32. Exit codes — https://kiro.dev/docs/reference/exit-codes/
33. Managed updates (enterprise) — https://kiro.dev/docs/enterprise/managed-updates/
34. 2.x reference ("last updated October 10, 2026") — https://kiro.dev/docs/cli/2x-reference/
35. Compaction — https://kiro.dev/docs/compaction/
36. IDE 1.0 hooks — https://kiro.dev/docs/ide/whats-new-v1/hooks/
37. Tangent — https://kiro.dev/docs/cli/v3/tangent/
38. CLI changelog index (newest 2.34.0) — https://kiro.dev/changelog/cli/ ; page 2 (2.18–2.26) https://kiro.dev/changelog/cli/page/2/ ("38p2"); page 3 (2.8–2.17) https://kiro.dev/changelog/cli/page/3/ ("38p3")
41. CLI 2.27.0 (2026-10-01) — https://kiro.dev/changelog/cli/2-27/
42. CLI 2.28.0 (2026-10-05) — https://kiro.dev/changelog/cli/2-28/
43. CLI 2.30.0 (2026-10-12) — https://kiro.dev/changelog/cli/2-30/
44. CLI 2.29.0 "Memory Across Chat Sessions" (2026-10-09) — https://kiro.dev/changelog/cli/2-29/
45. CLI 2.31.0 "Local Command Sandbox and Local Autonomous Mode" (2026-10-13) — https://kiro.dev/changelog/cli/2-31/
46. CLI 2.33.0 "Workspace Trust, Workflow Plan Step Trees, and Mermaid Subgraphs" (2026-10-20) — https://kiro.dev/changelog/cli/2-33/
47. CLI 2.33.1 (2026-10-21) — https://kiro.dev/changelog/cli/2-33-1/
48. CLI 2.34.0 "MCP Elicitation, Workflow Controls, and Memory Deletion" (2026-10-23) — https://kiro.dev/changelog/cli/2-34/
49. (settings keys used in §15 come from [31]; no separate source.)

Third-party / community (labeled [3P]):
53. Classmethod, "Kiro CLI 2.13 V3モードの新機能 Introspect Subagent / Global Hooks を試してみた" (tests on 2.13.0, 2026-07-20) — https://dev.classmethod.jp/articles/kiro-cli-213-v3-introspect-global-hooks/
54. AWS Labs aidlc-workflows, "Kiro IDE hook payload — empirical reference" (Kiro IDE 1.x captures; IDE, not CLI) — https://awslabs.github.io/aidlc-workflows/reference/kiro-ide-hook-payload/
55. sarbashis, "hooks in claude code and kiro cli" (2026-06-22; docs summary, not a test) — https://sarbashis.github.io/ai/2026/hooks-in-claude-code-and-kiro-cli/
56. Havoptic tracker "Kiro CLI v3.0.0" (body is 2.28.0 text; unreliable) — https://www.havoptic.com/r/kiro-3.0.0
Search-snippet-only (not fetched): Akto "kiro cli hooks" doc; kiro.dev Crew hooks page https://kiro.dev/docs/crew/capabilities/hooks/ (a different product surface); MCP best-practices https://kiro.dev/docs/mcp/security/.

Local (this repository):
L1. `research/kiro-cli-hooks-and-introspect.md` (2026-07-31, erratum 2026-08-03; against 2.16.0).
L2. `design/harness.md` (kiro column rows: session variable, hook output channel and budget, MCP process scope, unknown-model behavior, tool names, 330 s MCP call, `agent validate`), as read 2026-10-28.
