# kiro-cli agent hooks and the `introspect` tool

Research date: 2026-07-31. Findings apply to the stable (non-v3) kiro-cli harness, which is what backs `~/.local/bin/kiro-cli` per local evidence (the five hook-trigger Set literal in `tui.js` matches the documented trigger list exactly). A separate, early-access "V3" harness (`kiro-cli --v3`) exists with a different, incompatible hooks model — flagged throughout below wherever it diverges.

## Brief

Zikaron needs two things confirmed from docs, not inferred from the binary:

1. Which kiro-cli hook (if any) can inject retrieved text into the model's context on every turn, for push-style auto-surfacing of memory gists.
2. Whether any compaction/summarization hook exists, since Zikaron's consolidation trigger is designed to fire on compaction.

Plus: how to correctly enable the built-in `introspect` tool in an agent config, the full hooks schema, the built-in tool table, and whether a published JSON Schema URL exists for `$schema`.

---

## 1. Answer to the two load-bearing questions

**(a) Which hook injects text into the model's context each turn?**
`userPromptSubmit`. Its documented exit-code behavior is explicit: *"0: Hook succeeded, STDOUT is added to agent's context."* [Hooks docs](https://kiro.dev/docs/cli/hooks/#userpromptsubmit) It fires once per user message, receives the prompt text via stdin JSON, and its stdout becomes part of the context the model sees for that turn. This is exactly the mechanism needed for push-retrieval of memory gists — a hook command that greps/queries a local memory store and echoes the top-5 gists to stdout will have that text placed into context automatically. `agentSpawn` has the identical semantic ("STDOUT is added to agent's context") but only fires once at session start, so it is the right hook for one-time orientation context (e.g., "here is the project's memory summary") rather than per-turn retrieval.

**(b) Does a compaction/summarization hook exist?**
No. Confirmed by exhaustive cross-reference: the documented hook trigger enum is exactly `agentSpawn`, `userPromptSubmit`, `preToolUse`, `postToolUse`, `stop` — matching the local binary's validation Set precisely. [Hooks docs](https://kiro.dev/docs/cli/hooks/#hook-types), [Configuration reference](https://kiro.dev/docs/cli/custom-agents/configuration-reference/#hooks-field) Compaction is real and documented as a harness behavior (`chat.disableAutoCompaction`, `compaction.excludeMessages`, `compaction.excludeContextWindowPercent` settings; changelog entries describe compaction bugs and fixes), but nothing in the hooks system, the settings reference, or the changelog exposes a lifecycle event fired at compaction time. The `stop` hook is the closest adjacent mechanism (it can inject a synthetic user message via a block decision) but it fires at end-of-turn, not at compaction, and has no visibility into whether compaction is about to happen or just happened. **This confirms Zikaron's fallback to a manually-invoked consolidation skill is currently the only sound design** — there is no event to hook.

No CLI release notes or docs mention a planned compaction hook. A "scheduler"-like feature exists but is unrelated and lives in a different product surface: **Kiro Web's "Automations"** run scheduled tasks (hourly/daily/cron) in cloud sandboxes that clone repos and open PRs — [Automations changelog](https://kiro.dev/changelog/web/introducing-automations/) — this is not a kiro-cli feature and not a hook. No public evidence of a kiro-cli-side scheduler feature was found in docs or changelog; if the user has non-public roadmap information about a CLI scheduler, that cannot be confirmed or refuted from these sources.

---

## 2. Hook trigger table (stable/non-v3 harness)

| JSON key | Fires when | Can block? | Tool context provided? |
|---|---|---|---|
| `agentSpawn` | Agent is initialized/activated (session start) | No | No |
| `userPromptSubmit` | User submits a message, before the model processes it | No (cannot block the turn; can only add context or surface a warning) | No |
| `preToolUse` | Before a tool executes | **Yes** — exit code 2 blocks the tool, stderr is returned to the LLM as the reason | Yes: `tool_name`, `tool_input` |
| `postToolUse` | After a tool executes | No (tool already ran; hook can only warn) | Yes: `tool_name`, `tool_input`, `tool_response` |
| `stop` | Assistant finishes responding, at end of turn | **Yes, indirectly** — can prevent the agent from stopping by returning `{"decision":"block","reason":"..."}` on stdout, which is sent back as a new user message | No (gets `assistant_response` instead) |

Source: [Hooks documentation](https://kiro.dev/docs/cli/hooks/), [Agent configuration reference — hooks field](https://kiro.dev/docs/cli/custom-agents/configuration-reference/#hooks-field). Both pages list the identical five triggers with identical descriptions, confirming internal consistency.

This is a **flat, non-nested enum** — five keys only. There is no `conversationStart`, `perPrompt`, `sessionStart`, `compaction`, `summarize`, or similar key in the current schema.

### Historical/adjacent naming — the Q Developer CLI comparison
The AWS Q Developer CLI agent-format documentation (kiro-cli's direct ancestor) — [Amazon Q CLI Technical Documentation, Agent Format](https://aws.github.io/amazon-q-developer-cli/agent-format.html) — documents the **exact same five triggers with the exact same names**: `agentSpawn`, `userPromptSubmit`, `preToolUse`, `postToolUse`, `stop`. No `conversationStart` or `perPrompt` key appears anywhere in that page. The brief's concern about stale Q-CLI naming (e.g. `conversationStart`/`perPrompt`) did not materialize in the documentation actually available — those names were not found in any current AWS or Kiro doc page checked. It's possible such names existed in a still-older, now-unindexed Q CLI doc revision, but no such page was located; treat that specific risk as unconfirmed-but-not-found rather than refuted-with-certainty. The practical implication is the same either way: use the five names above, not any alternate spelling.

### V3 divergence (do not use for the installed stable binary)
kiro-cli's early-access V3 mode (`kiro-cli --v3`) uses a structurally different hooks system: hooks become **standalone files** under `.kiro/hooks/` (and, as of CLI 2.13.0, global hooks under `~/.kiro/hooks/`) with a versioned schema, two action types (shell command vs. agent-prompt), and additional lifecycle triggers for spec events, file deletion, and manual invocation. [V3 Hooks docs](https://kiro.dev/docs/cli/v3/hooks/), [CLI 2.13.0 changelog](https://kiro.dev/changelog/cli/2-13/). This is not the same schema as the one in this document and is not what the installed binary's Set literal reflects (V3 is opt-in via a flag and is described as "early access"). Do not port V3 hook syntax into a stable-mode agent config.

---

## 3. Payload and output semantics per hook (the single most important item)

All hooks receive a **JSON payload via stdin**. There are no documented argv or env-var payload channels for the hook *invocation* itself (env vars are used elsewhere, e.g. `$AGENT_CONTEXT_OUT`/`$AGENT_DISPLAY_OUT` for the unrelated shell-tool wrapper-script side channel, not for hooks). Source: [Hooks documentation — Hook event](https://kiro.dev/docs/cli/hooks/#hook-event).

Common envelope fields present on every hook event:
```json
{
  "hook_event_name": "agentSpawn",
  "cwd": "/current/working/directory",
  "session_id": "abc123-def456-789"
}
```

Per-trigger additions:

- **`agentSpawn`**: no additional fields beyond the common envelope.
- **`userPromptSubmit`**: adds `"prompt": "user's input prompt"`.
- **`preToolUse`**: adds `"tool_name"` and `"tool_input"` (tool-specific parameter object).
- **`postToolUse`**: adds `"tool_name"`, `"tool_input"`, and `"tool_response"` (e.g. `{"success": true, "result": [...]}`).
- **`stop`**: adds `"assistant_response"` (the full text of the assistant's last response) instead of tool fields.

**Output/stdout semantics — this is the crux of the brief:**

| Trigger | Exit 0 | Exit 2 | Other exit |
|---|---|---|---|
| `agentSpawn` | stdout **added to agent's context** | n/a | stderr shown as warning to user |
| `userPromptSubmit` | stdout **added to agent's context** | n/a | stderr shown as warning to user |
| `preToolUse` | tool execution allowed | tool execution **blocked**, stderr returned to the LLM | stderr shown as warning to user, tool still runs |
| `postToolUse` | hook succeeded (no context injection documented) | n/a | stderr shown as warning to user; tool already ran |
| `stop` | hook succeeded; if stdout is JSON with `{"decision":"block","reason":"..."}`, the reason is sent as a **new user message** to the LLM and the agent continues instead of stopping | n/a | stderr shown as warning to user |

Source for the exit-code table: [Hooks documentation — Hook output](https://kiro.dev/docs/cli/hooks/#hook-output) and the per-trigger "Exit Code Behavior" sections on the same page; corroborated by the dedicated [Exit codes reference — Hook exit codes](https://kiro.dev/docs/cli/reference/exit-codes/#hook-exit-codes), which independently states the same 0/2/other semantics.

Important nuance found only in the general "Hook output" summary paragraph, which slightly undersells `agentSpawn`/`userPromptSubmit`: it says *"Exit code 0: Hook succeeded. STDOUT is captured but not shown to user."* — phrased generically as if stdout is merely captured-but-hidden. The **per-trigger sections directly below it are more specific and authoritative**: for `agentSpawn` and `userPromptSubmit` specifically, they state stdout is "**added to agent's context**," not merely captured. For `preToolUse` and `postToolUse`, no such context-injection language appears — their stdout is not documented as reaching the model at all (only their stderr, and only on the blocking/warning paths). Treat the per-trigger sections as authoritative over the general summary paragraph where they conflict.

`postToolUse` deserves a specific caution: nothing in the docs says its stdout is added to context. Its only documented effect is that a non-zero exit surfaces stderr as a user-facing warning — the tool has already run by the time this hook fires, so it cannot block, and there's no documented channel for its stdout to reach the model. Don't rely on `postToolUse` for context injection.

---

## 4. `userPromptSubmit` in detail

- **Does its stdout reach the model?** Yes — confirmed directly: "0: Hook succeeded, STDOUT is added to agent's context." [Source](https://kiro.dev/docs/cli/hooks/#userpromptsubmit)
- **Where does it land in assembled context?** Not documented at the level of "system prompt vs. separate block vs. appended-to-user-message." The docs describe the effect ("added to agent's context") but not the exact placement/formatting in the assembled prompt. This is an **unconfirmed** point — do not assume a specific placement (e.g., do not assume it's prepended to the user's literal message text) without empirical verification against the actual binary.
- **Size/token limit or truncation behavior for hook stdout?** Not documented anywhere found — no mention of a hook-output character or token cap, and no truncation behavior described for hook stdout specifically. The general hook **timeout** is documented (see §7) but that is a wall-clock cutoff for the command's execution, not a size cap on its output. Treat any hook-output length limit as **unconfirmed**; if Zikaron's retrieval hook could plausibly emit a large payload, empirically test rather than assume no limit exists.
- **Blocking:** `userPromptSubmit` is not documented as being able to block or deny the user's turn — only `preToolUse` (and `stop`, indirectly) have blocking semantics.

---

## 5. Full `hooks` config schema and worked example

### Where it may be declared
The `hooks` field lives inside an **agent configuration JSON file** (not a separate global settings file, in the stable/non-v3 harness). Agent config files live at:
- **Local (project-specific)**: `.kiro/agents/<name>.json` — takes precedence.
- **Global (user-wide)**: `~/.kiro/agents/<name>.json` — fallback.

Source: [Agent configuration reference — File locations](https://kiro.dev/docs/cli/custom-agents/configuration-reference/#file-locations). (V3 changes this: hooks move to standalone files under `.kiro/hooks/` or `~/.kiro/hooks/`, applying across all agents in a workspace — [V3 Hooks](https://kiro.dev/docs/cli/v3/hooks/), [Global Hooks changelog](https://kiro.dev/changelog/cli/2-13/). Not applicable to stable mode.)

### Nesting and per-entry fields
```
hooks: {
  <triggerName>: [
    {
      command: string,       // required — the shell command to run
      matcher?: string,      // optional — preToolUse/postToolUse only; tool-name pattern
      timeout_ms?: number,   // optional — default 30000 (30s)
      cache_ttl_seconds?: number  // optional — default 0 (no caching)
    },
    ...
  ],
  ...
}
```
- `command` (required): the shell command executed for that hook invocation.
- `matcher` (optional, `preToolUse`/`postToolUse` only): a tool-name pattern. Accepts canonical names (`fs_read`, `fs_write`, `execute_bash`, `use_aws`) or their current aliases (`read`, `write`, `shell`, `aws`); MCP tool syntax (`@server`, `@server/tool`); wildcards `*` and `@builtin`; and "no matcher" to apply to all tools. [Hooks — Tool matching](https://kiro.dev/docs/cli/hooks/#tool-matching)
- `timeout_ms`: not spelled out with an explicit JSON example in the fetched pages, but the **Timeout** section states "Default timeout is 30 seconds (30,000ms). Configure with `timeout_ms` field." [Source](https://kiro.dev/docs/cli/hooks/#timeout)
- `cache_ttl_seconds`: "Successful hook results are cached based on `cache_ttl_seconds`: 0 = no caching (default); >0 = cache successful results for specified seconds. AgentSpawn hooks are never cached." [Source](https://kiro.dev/docs/cli/hooks/#caching) — the exact JSON key spelling (`cache_ttl_seconds`, snake_case) is as documented but no worked JSON example including it was found on the page; treat the *existence and semantics* as confirmed, the exact call site formatting as reasonably inferred from context.
- No **run-once** semantics are documented anywhere in the hooks pages. Caching (`cache_ttl_seconds`) is the closest related concept but is time-based, not a one-shot flag. Treat "run-once" as **not present** in the schema.
- `stop` hooks do not use `matcher` at all ("Stop hooks do not use matchers since they don't relate to specific tools" — [source](https://kiro.dev/docs/cli/hooks/#stop)).

### Complete worked example (agent JSON with hooks)
Synthesized from the two consistent worked examples in the docs (configuration-reference "Complete example" and the hooks page's per-trigger snippets), combined into one illustrative file:

```json
{
  "name": "memory-aware-agent",
  "description": "Agent with a push-retrieval userPromptSubmit hook and an audit preToolUse hook",
  "prompt": "You are an assistant with access to a local tribal-knowledge memory store.",
  "tools": [
    "read",
    "write",
    "shell",
    "@git"
  ],
  "allowedTools": [
    "read",
    "@git/git_status"
  ],
  "hooks": {
    "agentSpawn": [
      { "command": "git status" }
    ],
    "userPromptSubmit": [
      { "command": "zikaron-retrieve --top-k 5", "timeout_ms": 5000 }
    ],
    "preToolUse": [
      {
        "matcher": "execute_bash",
        "command": "{ echo \"$(date) - Bash command:\"; cat; echo; } >> /tmp/bash_audit_log"
      }
    ],
    "postToolUse": [
      {
        "matcher": "fs_write",
        "command": "cargo fmt --all"
      }
    ],
    "stop": [
      { "command": "npm test" }
    ]
  },
  "model": "claude-sonnet-4"
}
```
Notes on this synthesis: `agentSpawn`, `userPromptSubmit`, and the `preToolUse`/`postToolUse` matcher examples are copied in spirit (not verbatim beyond ~30 words) from [Configuration reference — Hooks field](https://kiro.dev/docs/cli/custom-agents/configuration-reference/#hooks-field). The `stop` example and its shape are from [Configuration reference — hooks (second listing)](https://kiro.dev/docs/cli/custom-agents/configuration-reference/#hooks). The `zikaron-retrieve` command and `timeout_ms` value are Zikaron-specific illustrative additions, not from the docs. For the load-bearing `userPromptSubmit` retrieval hook, the hook's stdout — whatever `zikaron-retrieve` prints — is what gets added to the agent's context per §1(a)/§3.

---

## 6. Enabling `introspect`

- **Exact tool name**: `introspect`. Confirmed present in the built-in tools reference under the heading "Introspect Kiro CLI capabilities." [Source](https://kiro.dev/docs/cli/reference/built-in-tools/#introspect-kiro-cli-capabilities)
- **What it does**: "Provides self-awareness for Kiro CLI by answering questions about its features, commands, and functionality using official documentation." It activates automatically when the user asks kiro-cli about itself; it semantically searches indexed documentation and returns matched docs (or, in `progressiveMode`, an index for the LLM to page through) rather than answering from the model's training data. It is explicitly the intended replacement for "reverse-engineering the binary" that motivated this brief.
- **Arguments/parameters**: not documented as a directly-invoked tool with a user-specified parameter schema (unlike, say, `tool_search`, which has `tool_id`/`query`/`max_results`). The docs describe it as auto-triggering on self-referential questions ("How do I save conversations?") rather than being called with explicit arguments by the agent. No parameter table was found for it, unlike several other tools on the same page (`read`, `glob`, `grep`, `tool_search`) which do have explicit parameter/config tables — treat "no user-facing parameters" as the best available inference from the absence of a parameter table, not a directly confirmed statement.
- **Must it appear in both `tools` and `allowedTools`?** The general tool-permission rule applies, and it is documented generically (not introspect-specifically): "If a tool is not in the `allowedTools` list, the user will be prompted for permission when the tool is used" — [Built-in tools — Tool permissions](https://kiro.dev/docs/cli/reference/built-in-tools/#tool-permissions). `introspect` is not one of the tools with a stated default-trusted behavior (that short list is explicitly `report`, and `read`/`grep`/`glob` in the cwd). So: putting `introspect` in `tools` alone makes it *available* but the agent will be prompted for permission each time it's used; adding it to `allowedTools` as well makes it usable without a permission prompt. This mirrors the documented pattern for `subagent`, which the docs explicitly instruct adding to `tools` (and note `@builtin` also covers it) — [Subagents docs](https://kiro.dev/docs/cli/chat/subagents/). No introspect-specific "must be in both arrays" statement was found; the "both arrays" recommendation here is inferred from the general permission-model documentation, not a sentence written specifically about introspect.
- **Gated behind a setting or experiment flag?** No. It is documented on the stable **built-in tools** reference page (not the `/docs/cli/experimental/` page), unlike explicitly-labeled experimental tools such as `knowledge`, `thinking`, and `todo` (each carries an "(experimental)" heading suffix on that same page — `introspect` does not). The only settings found that touch introspect are behavioral, not availability gates:
  - `introspect.progressiveMode` (CLI command form: `kiro-cli settings set introspect.progressiveMode true`) — switches from semantic-search mode (downloads an embedding model) to an index-fetch mode for enterprise environments where model downloads are blocked. [Source](https://kiro.dev/docs/cli/reference/built-in-tools/#how-it-works)
  - `introspect.tangentMode` (boolean, "classic only" per the settings reference table) — auto-enters tangent mode for introspect conversations to keep them separate from the main thread. [Source](https://kiro.dev/docs/cli/reference/settings/#feature-toggles)
  Neither setting turns the tool on/off; both only change its behavior once it's already available via `tools`/`allowedTools`.
- **Critical disambiguation — do not confuse with the "Introspect Subagent":** CLI changelog 2.13.0 (2026-07-17) announced an "**Introspect Subagent**" as a V3-early-access-only feature ("Available in V3 (`kiro-cli --v3`)") that walks users through writing agents/hooks/steering interactively. [Changelog 2.13.0](https://kiro.dev/changelog/cli/2-13/) This is a **different feature** from the stable `introspect` **tool** documented on the built-in-tools page. The brief's evidence (`introspect` appearing ~31 times in `tui.js` but absent from the Rust binary's plain strings) is consistent with the stable `introspect` tool being implemented/wired in the TUI layer, not the V3 subagent — the installed binary is not running V3 by default (no `--v3` flag mentioned in local evidence), so the tool the user wants enabled is almost certainly the stable built-in tool, not the V3 subagent feature.

---

## 7. Full built-in tool name reference table

From [Built-in tools reference](https://kiro.dev/docs/cli/reference/built-in-tools/), which is the authoritative current list for the stable harness:

| Canonical name | Aliases | Category | Experimental? |
|---|---|---|---|
| `read` | `fs_read`, `fsRead` | File read | No |
| `glob` | — | File discovery | No |
| `grep` | — | Content search | No |
| `write` | `fs_write`, `fsWrite` | File write | No |
| `shell` | `execute_bash`, `execute_cmd` | Shell execution | No |
| `aws` | `use_aws` | AWS CLI | No |
| `web_search` | — | Web search | No |
| `web_fetch` | — | Web content fetch | No |
| `introspect` | — | Self-documentation / capability Q&A | No |
| `code` | — | Code intelligence (symbol search, LSP, pattern rewrite) | No |
| `tool_search` | — | On-demand MCP tool discovery | No (but requires `toolSearch.enabled`, default false) |
| `delegate` | — | Background/async task delegation | No (listed under `/docs/cli/experimental/delegate/` yet appears on the main built-in-tools page without an "(experimental)" tag — treat as **ambiguous**; the experimental-features doc groups it there, but the tools-reference page doesn't tag it. Flag this inconsistency rather than resolving it silently.) |
| `report` | — | Open a pre-filled GitHub issue | No; trusted by default |
| `knowledge` | — | Cross-session semantic knowledge store | **Yes** (explicitly tagged "(experimental)") |
| `thinking` | — | Internal reasoning/task decomposition | **Yes** (explicitly tagged "(experimental)") |
| `todo` | — | Multi-step task list tracking | **Yes** (explicitly tagged "(experimental)") |
| `goal` | — | Goal-driven iterative loop with verification (used internally by `/goal`) | No |
| `session` | — | Temporary in-session settings override | No |
| `subagent` | `use_subagent` | Parallel subagent delegation | No, but not in the default agent's implicit set — must be explicitly added to `tools` (or via `@builtin`) for **custom** agents |

Additional tool-reference syntax (not tool names themselves, but valid entries in `tools`/`allowedTools` arrays):
- `*` — all available tools (built-in + MCP). Valid in `tools` only; **not** valid in `allowedTools` (must use specific patterns/server-level permissions there).
- `@builtin` — all built-in tools.
- `@server_name` — all tools from one MCP server.
- `@server_name/tool_name` — one specific MCP tool.

Source for all of the above: [Built-in tools reference](https://kiro.dev/docs/cli/reference/built-in-tools/) (tool-by-tool sections) cross-checked against [Configuration reference — Tools field](https://kiro.dev/docs/cli/custom-agents/configuration-reference/#tools-field) for the wildcard/sigil syntax.

Cross-check against the local evidence: the memory-researcher config's current `tools`/`allowedTools` list — `read, write, grep, glob, code, shell, subagent, task, knowledge` — is consistent with this table with one exception: **`task` is not a name that appears anywhere in the built-in tools reference page fetched for this research.** It may be an alias, a project-local MCP-provided tool, a name from a different doc revision, or a naming mismatch worth double-checking independently — flagging this rather than guessing.

---

## 8. Published JSON Schema for agent config

**No `$schema` URL was found** for the kiro-cli agent configuration format in any official doc page, GitHub repo, or the AWS Q CLI docs checked. None of the worked examples in the official docs (Kiro or AWS Q CLI) include a `$schema` key. A GitHub search surfaced an unrelated, differently-named project ("Kilo"/kilocode) that does define a `$schema` overlay for its own, unrelated config format at `https://app.kilo.ai/config.json` — this is a different tool entirely (note the name similarity is coincidental) and must not be mistaken for a Kiro schema. **Recommendation: do not add a `$schema` key to the memory-researcher agent config** — there is nothing to point it at, and inventing a URL would be actively wrong. If Kiro publishes one in the future, add it then.

---

## Confirmed vs. unconfirmed

### Confirmed (direct doc citation, current stable/non-v3 harness)
- Exactly five hook triggers exist: `agentSpawn`, `userPromptSubmit`, `preToolUse`, `postToolUse`, `stop`. No compaction/summarization/scheduler hook exists.
- `userPromptSubmit` and `agentSpawn` stdout (on exit 0) is added to the agent's context — this is the mechanism for push-retrieval auto-surfacing.
- `preToolUse` can block a tool (exit code 2, stderr → LLM); `postToolUse` cannot block (tool already ran) and has no documented stdout-to-context path.
- `stop` can prevent the agent from stopping via a JSON `{"decision":"block","reason":...}` on stdout, injected as a new user message.
- Hooks are configured in agent JSON files under `.kiro/agents/` (local) or `~/.kiro/agents/` (global); no separate global-settings-file location in stable mode.
- Default hook timeout is 30000ms, configurable via `timeout_ms`; hook result caching via `cache_ttl_seconds` (0 = off, default).
- `introspect` is a real, currently-documented, non-experimental built-in tool name, distinct from the V3-only "Introspect Subagent." No setting gates its availability; `introspect.progressiveMode` and `introspect.tangentMode` only change its behavior.
- No `$schema` URL exists for kiro-cli agent configs in any source checked.
- The AWS Q Developer CLI ancestor documents the identical five hook trigger names — no `conversationStart`/`perPrompt` naming was found in currently-available docs.
- Kiro Web's "Automations" (scheduled cron tasks) is a distinct product surface from kiro-cli and is not a hook or CLI feature.

### Unconfirmed (documented behavior exists but exact detail was not found, or found ambiguous)
- The precise placement of injected `userPromptSubmit`/`agentSpawn` stdout within the assembled context (system prompt vs. a distinct block vs. appended to the user turn) — not specified in any doc found.
- Any size/character/token limit or truncation behavior on hook stdout before it's added to context — not found; only the unrelated command-execution timeout is documented.
- Whether `introspect` specifically needs to be in *both* `tools` and `allowedTools` — inferred correctly from the general tool-permission rule and the `subagent` precedent, but no sentence says this about `introspect` by name.
- Exact JSON call-site formatting for `matcher`/`timeout_ms`/`cache_ttl_seconds` together in one hook entry — the fields' existence and individual semantics are confirmed from prose, but no single worked JSON example combining all of them was found.
- Whether `delegate` is "experimental" — it's covered under `/docs/cli/experimental/delegate/` but not tagged "(experimental)" on the main built-in-tools reference page, an internal inconsistency in the docs rather than something resolvable from outside.
- Whether `task` (present in the local agent config's `tools` array) is a valid built-in tool name — not found on the built-in tools reference page; flagged, not resolved.
- Whether stale Q Developer CLI hook names (`conversationStart`, `perPrompt`) ever existed in some now-unindexed older doc revision — not found in any page checked, but absence-of-evidence is not strong proof of absence for a doc page that may simply not be surfaced by search.

---

## Sources

1. Kiro CLI Hooks documentation — https://kiro.dev/docs/cli/hooks/ (primary source for hook event/output semantics, per-trigger tables, timeout, caching)
2. Kiro CLI Agent configuration reference — https://kiro.dev/docs/cli/custom-agents/configuration-reference/ (hooks field schema, tools/allowedTools/toolsSettings fields, complete worked examples, file locations, tool-permission defaults)
3. Kiro CLI Built-in tools reference — https://kiro.dev/docs/cli/reference/built-in-tools/ (full tool table including `introspect`, `code`, `tool_search`, `delegate`, `knowledge`, `thinking`, `todo`, `goal`, `session`, `subagent`; tool-permission defaults)
4. Kiro CLI Exit codes reference — https://kiro.dev/docs/cli/reference/exit-codes/ (independent corroboration of hook exit-code semantics 0/2/other)
5. Kiro CLI Settings reference — https://kiro.dev/docs/cli/reference/settings/ (compaction settings, `introspect.progressiveMode`/`introspect.tangentMode`, no availability-gating setting found for introspect)
6. Amazon Q Developer CLI Technical Documentation — Agent Format — https://aws.github.io/amazon-q-developer-cli/agent-format.html (ancestor doc confirming identical five hook trigger names; no `conversationStart`/`perPrompt` found)
7. Kiro CLI changelog, 2.13.0 "Introspect Subagent and Global Hooks" — https://kiro.dev/changelog/cli/2-13/ (disambiguates the V3-only Introspect Subagent from the stable `introspect` tool; V3 global hooks under `~/.kiro/hooks/`)
8. Kiro CLI changelog index — https://kiro.dev/changelog/cli/ (2.16.0 through 2.7.0 entries reviewed; no compaction-hook or CLI-scheduler feature found)
9. Kiro CLI V3 Hooks documentation — https://kiro.dev/docs/cli/v3/hooks/ (V3's incompatible standalone-file hooks schema, for contrast/non-use)
10. Kiro Web "Introducing Automations" changelog — https://kiro.dev/changelog/web/introducing-automations/ (confirms the only "scheduler"-like feature found is Kiro Web-specific, not CLI)
11. GitHub — Kilo-Org/kilocode config-schema doc — https://github.com/Kilo-Org/kilocode/blob/main/packages/kilo-docs/pages/contributing/architecture/config-schema.md (checked and ruled out as an unrelated project with superficial name similarity; not a Kiro schema)
