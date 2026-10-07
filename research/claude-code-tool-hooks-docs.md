# Claude Code PreToolUse / PostToolUse hooks: what they can do to the model (documentation check)

**Date of research:** 2026-10-06. Docs read were at the Claude Code v2.1.292 era (changelog's newest entry is 2026-10-06).
**Scope:** documentation only (hooks reference, hooks guide, and the pages they link), plus release notes and GitHub issues where they bear on whether a documented channel actually works.
**Author:** memory-assistant (for memory-researcher).

## 0. The brief, restated

Zikaron is designing two deterministic Claude Code hooks:

1. A `PreToolUse` hook that **denies Bash calls that edit files** via sed/awk/python/perl/heredoc rewrites, with an escape hatch the agent can use by adding a marker such as `#ZIKARON-FORCE` to the command.
2. A `PostToolUse` hook that, **after a successful Edit/MultiEdit/Write**, nudges the agent to re-read the surrounding lines for consistency.

The existing note `research/claude-code-harness-contract.md` (2026-08-16) marks PreToolUse model-visibility "unknown" and says PostToolUse "cannot inject context on success". The task: verify or refute both, and answer six numbered questions (exit-2 semantics and JSON decisions; PostToolUse channels; permission-mode interaction; matcher syntax, subagent scope and stdin fields; size caps, timeouts and `continue`/`stopReason`/`suppressOutput`; any documented model-side override mechanism) with a URL and a quoted passage for each.

## 1. Bottom line

- **PreToolUse model-visibility is documented, not unknown.** Three channels reach the model: (a) exit-2 stderr, (b) `permissionDecisionReason` on `deny`, and (c) `hookSpecificOutput.additionalContext` (documented since v2.1.9, 2026-01-16). Plain stdout on exit 0 does **not** reach the model.
- **The existing note's PostToolUse claim is half right.** Plain stdout on a successful PostToolUse hook goes only to the debug log (confirmed). But PostToolUse can inject context on success through JSON `hookSpecificOutput.additionalContext` (documented; "next to the tool result"), and exit-2 stderr also reaches Claude (documented). So "cannot inject context on success" is **refuted** as a general statement.
- **Block on PreToolUse:** exit 2 or JSON `permissionDecision: "deny"`. Both feed text to the model. The block holds in every permission mode including `bypassPermissions`, and an allow rule or a hook `"allow"` cannot override it.
- **No documented model-side override exists.** `"ask"` hands the decision to the *human*; `"defer"` is `-p`-only. An in-command marker is entirely hook-implemented (the hook sees the command text and chooses to exit 0), which is the only model-initiated override available.
- **Reliability caveat the docs do not mention:** GitHub issues from 2026 report `additionalContext` (both Pre and Post) not reaching the model on some versions/surfaces. All were closed without a fix confirmation. A one-session probe on the target harness is warranted before relying on it (section 9).

## 2. How reliable is what I read (read this before trusting any quote)

`WebFetch` runs page content through a small model unless the page is short enough to pass through. The tools reference itself says so: "WebFetch is lossy by design" ([4]). Outcomes here:

- **[RAW]** pages came back verbatim: hooks guide [1], Agent SDK hooks page [3], tools reference [4], permissions [5], permission modes [6], headless [7], the GitHub example script [10], and the open-source Python SDK `types.py` [11]. Claims tagged [RAW] were read in the page text itself.
- **[SUMM]** The hooks **reference** [2] is too large to pass through. Every fetch of it came back as a model-written extract, and **extracts disagreed with each other** on several fields (listed in section 8). I therefore tag each claim sourced only from [2] as [SUMM], and say whether two or more independent fetches agreed.
- **Rule I applied:** a claim from [2] is treated as established only if it is (i) corroborated by a [RAW] page, or (ii) returned identically by at least two separately-prompted fetches. Anything else is marked **conflicting** or **unverified**.

## 3. PreToolUse

### 3.1 Exit-code semantics

| Exit | Effect on PreToolUse | Where the text goes | Tag |
|---|---|---|---|
| 0 | No decision; normal permission flow applies. Stdout is **not** shown to the model. | Debug log only | [RAW]+[SUMM] |
| 2 | Blocks the tool call, **regardless of any JSON** | stderr (or the JSON blocking reason) is shown to **Claude**; user sees it in the transcript view | [RAW] |
| other (1, crash, etc.) | **Non-blocking error: the tool call proceeds** | First stderr line shown to the *user*, "but not to Claude" | [RAW] |

Quotes (each under 30 words):

- Guide's example script, comment on the stderr line: "stderr becomes Claude's feedback" and on `exit 2`: "exit 2 = block the action". ([1], hooks-guide "Hook output") [RAW]
- "For a `PreToolUse` hook this doesn't approve the tool call: the normal permission flow still applies." (about exit 0; [1]) [RAW]
- Official example script comments: "Exit code 2 blocks tool call and shows stderr to Claude" and, for exit 1, "shows stderr to the user but not to Claude" ([10], `anthropics/claude-code/examples/hooks/bash_command_validator_example.py`) [RAW]
- "Exit 2 means a blocking error... even a JSON `permissionDecision` of `"allow"` can't override it." ([2], Exit code 2) [SUMM; the same paragraph came back identically in 3 separate fetches]
- "The blocking message is the reason from your JSON's blocking decision when it makes one, and your stderr text otherwise." ([2]) [SUMM, 3 fetches agree]
- Guide, on non-0/2 exits: "Stdout that Claude Code treats as plain text, or empty stdout: the action proceeds as a non-blocking error." ([1]) [RAW]
- Guide, on user visibility: "Blocking error: on most events you see the hook's feedback." (Ctrl+O transcript view; [1]) [RAW]
- "Use exit 2 to block with a stderr message, or exit 0 with JSON for structured control. Choose one approach per hook." ([1]) [RAW]

**Design-relevant:** a hook script that crashes (Python traceback = exit 1) **fails open**. Only exit 2 blocks. Separately, release 2.1.288 (2026-10-02) fixed the case where "PreToolUse and PermissionRequest hooks being skipped when matching them failed or the tool's input could not be serialized to JSON; the call is now blocked" ([15]) [RAW-ish, GitHub release page]. So the harness fails closed when *its own* hook matching breaks, but not when the script breaks.

### 3.2 JSON: `hookSpecificOutput` on PreToolUse

Field names (open-source SDK type, [RAW]): `hookEventName`, `permissionDecision` (`allow | deny | ask | defer`), `permissionDecisionReason`, `updatedInput`, `additionalContext` ([11], `PreToolUseHookSpecificOutput`). Top-level fields `continue`, `stopReason`, `suppressOutput`, `systemMessage`, `decision`, `reason` are on `SyncHookJSONOutput` ([11]).

**Placement:** "Nest `additionalContext` inside `hookSpecificOutput`; if you place it at the top level of the JSON, Claude Code silently ignores it." ([1]) [RAW]. Same for `permissionDecision`: "Claude Code ignores the misplaced fields without reporting an error." ([1]). Include `hookEventName` ([3] "Include `hookEventName` in `hookSpecificOutput`") [RAW]. Stdout must start with `{` and end with `}` to be parsed as JSON; a shell profile that echoes on startup corrupts it ([1]) [RAW].

**`permissionDecision` values** (all [RAW] from [1] unless marked):

- `"allow"`: "skip the interactive permission prompt. Deny and ask rules, including enterprise managed deny lists, still apply"
- `"deny"`: "cancel the tool call and send the reason to Claude"
- `"ask"`: "show the permission prompt to the user as normal"
- `"defer"`: "available in non-interactive mode with the `-p` flag. It exits the process with the tool call preserved so an Agent SDK wrapper can collect input and resume." The SDK page adds: the turn ends with a result whose `stop_reason` is `"tool_deferred"` ([3]) [RAW]. (One extract of [2] described `defer` as an interactive queue with `/approve-deferred`; a second extract said that section was "NOT ON PAGE". I treat the interactive-queue description as **unverified** and likely wrong.)
- Precedence across multiple hooks: "the most restrictive answer applies, in the order `deny`, `defer`, `ask`, `allow`." ([1]); SDK page says the same ([3]) [RAW].

**Where `permissionDecisionReason` is shown, per value:**

| Value | Reaches the model? | Evidence |
|---|---|---|
| `deny` | **Yes** | [1] "feeds `permissionDecisionReason` back to Claude"; [3] "`permissionDecisionReason` tells the model why, so it avoids retrying" [RAW, two pages]. User also sees the blocking feedback in the transcript view ([1] debug section: "the feedback is the reason from that decision"). |
| `ask` | **Not established.** The reason is shown in the *user's* permission prompt (extracts of [2] agree on that). Whether Claude also sees it is **conflicting/undocumented**. | [2] extracts disagree (see section 8). |
| `allow` | **Not established / undocumented.** | Same conflict. An older doc generation, quoted in a 2025-26 GitHub issue, said the reason was "shown to user only, NOT to Claude" ([16], #15345) but that is third-hand and about an older doc. |
| `defer` | Not established | |

One extract of [2] also gave the exact deny framing "Tool call blocked: [your reason]" as the system message Claude receives. Single sample, **unverified**.

**`systemMessage`** is the user-side companion: "The `systemMessage` field shows a message to the user, not the model." ([3]) [RAW]. The SDK page's block example uses both: "`permissionDecisionReason` tells the model why... `systemMessage` shows the user what happened." ([3]) [RAW]. So (a) block + (b) text for the model + a separate note for the user are all expressible in one JSON object.

### 3.3 `additionalContext` on PreToolUse

- **Supported.** Release v2.1.9 (2026-01-16): "Added support for `PreToolUse` hooks to return `additionalContext` to the model" ([12]).
- **Fixed on tool failure.** v2.1.110 (2026-04-15): "Fixed `PreToolUse` hook `additionalContext` being dropped when the tool call fails" ([13]). Issue #30899 reports (v2.1.69/2.1.86) that with `additionalContext` and a failing tool the *turn silently terminated*; fixed as of 2.1.110 ([16]).
- **When it reaches the model.** The "Add context for Claude" section of [2] [SUMM, two fetches identical]: Claude Code "wraps the string in a system reminder and inserts it into the conversation at the point where the hook fired. Claude reads the reminder on the next model request"; for `PreToolUse`, `PostToolUse`, `PostToolUseFailure` and `PostToolBatch` the reminder appears "next to the tool result"; "When several hooks return `additionalContext` for the same event, Claude receives all of the values." The guide independently says: "Text returned via `additionalContext` is injected as a system reminder that Claude reads as plain text." ([1]) [RAW]
- **Combined with `defer`: ignored** (a search-result synthesis of the official doc, not fetched verbatim: "ignored when permissionDecision is 'defer'"). Treat as likely.
- **Combined with `deny`: not stated** in anything I could read. The documented rule is simply "next to the tool result"; on a denied call the "result" is the denial. **Undocumented; probe it.** The documented, widely used channel for model-directed text on the deny path is `permissionDecisionReason` / stderr, so a design need not depend on this.
- **Wording guidance (documented):** "Write the text as factual statements rather than imperative system instructions... Text framed as out-of-band system commands can trigger Claude's prompt-injection defenses, which causes Claude to surface the text to you instead of treating it as context." ([2], "Add context for Claude") [SUMM, two fetches]
- **Escaping:** v2.1.292 (2026-10-06): "`<system-reminder>` tags written in a hook's output are escaped before they reach Claude" ([14]). Do not write that tag in hook output.
- **Replay on resume:** the injected text is saved in the transcript and replayed (not regenerated) when you `--continue`/`--resume` ([2]) [SUMM].

### 3.4 `updatedInput` (can a hook rewrite tool input?)

**Yes.** [3] [RAW]: "Pair `updatedInput` with `permissionDecision: 'allow'` to auto-approve the modified input, or `permissionDecision: 'ask'` to show it to the user. If you omit `permissionDecision`, the modified input still applies and flows through the normal permission evaluation. With `'defer'`, `updatedInput` is ignored." (the sentence is long; the three clauses are quoted in short form). SDK example: a Write hook rewrites `file_path`, spreading the original `tool_input` and overriding one key ([3]).

- Merge vs replace is **ambiguous**: one extract of [2] said "only fields you include are replaced; other fields stay the same"; the SDK page says "Always return a new object rather than mutating the original `tool_input`" and its example spreads the full input. Safe practice: return the complete input object.
- Parallel hooks: "the last one to finish takes effect... Avoid having more than one hook modify the same tool's input." ([1]) [RAW]
- `deny` plus `updatedInput`: one extract said it applies only for allow/ask/defer, not deny. Unverified, and irrelevant to a block.
- Safety: v2.1.110 fixed `PermissionRequest` hooks returning `updatedInput` not being re-checked against `permissions.deny` ([13]); whether the same re-check applies to `PreToolUse` `updatedInput` is **not stated**.

## 4. PostToolUse

PostToolUse fires only after a **successful** tool call ([1] event table: "After a tool call succeeds") [RAW]. A failure fires `PostToolUseFailure` instead. **Caveat:** issue #72996 (tested on v2.1.198) reported that built-in file tools returning `<tool_use_error>` validation errors (for example Edit's "String to replace not found") fire PreToolUse but *neither* post event; closed 2026-07-13 as fixed/completed, but whether the fix was behaviour or docs is not stated in what I could read ([16]). For a success-only nudge this is harmless.

| Mechanism | Reaches the model on a successful call? | Evidence |
|---|---|---|
| Plain stdout, exit 0 | **No.** "For most events, Claude Code writes stdout to the debug log and doesn't show it in the transcript. The exceptions are `UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, and `PostModelSwitch`." | [2] [SUMM; consistent in 3 fetches] and [1] [RAW]: only those four events add plain stdout to context |
| Exit-0 stderr | **No** ("debug log only... Claude never sees it") | [2] [SUMM, 1 fetch] |
| Exit 2 stderr | **Yes**: "Shows stderr to Claude; the tool already ran" (cannot undo or block) | [2] exit-2 table, consistent across fetches [SUMM]; PostToolUse intro: "The tool has already run, so exit code 2 doesn't block it, but you can still provide feedback that Claude sees." |
| `hookSpecificOutput.additionalContext` | **Yes**, "next to the tool result" | [3] [RAW]: "you can set `additionalContext` to append information to the tool result"; [1] [RAW]; [2] [SUMM] |
| `decision: "block"` + `reason` | Per [2]: "prevent Claude from continuing past this tool result, similar to a `Stop` hook. The reason appears as a system message." **Whether the turn continues is ambiguous** (extracts conflict). For prompt/agent-type hooks, [1] [RAW] says a PostToolUse block "by default the turn ends and the `reason` appears in the chat as a warning line" unless `continueOnBlock: true`. | Do not rely on `block` for a soft nudge. |
| `updatedToolOutput` | Replaces what Claude sees. **Works for any tool** (v2.1.121, 2026-04-28 per secondary sources). `updatedMCPToolOutput` is the "older" MCP-only field and "is deprecated". For built-ins the value must match the tool's output schema; "a mismatched shape is rejected and the original output is kept." | [3] [RAW], [11] [RAW] docstring. Issue #67442 (v2.1.173) reports it silently ignored for Bash/WebFetch, closed as duplicate ([16]). |
| `continue: false` + `stopReason` | Stops Claude entirely; "`stopReason`... stays in the conversation, so Claude sees it if the conversation continues." | [2] [SUMM] |
| `systemMessage` | User only | [3] [RAW] |

**PostToolUse stdin fields.** `session_id`, `cwd`, `transcript_path`, `permission_mode`, `hook_event_name`, `tool_name`, `tool_input`, `tool_use_id`, and a result field. **The result field name is conflicting:** the open-source SDK type `PostToolUseHookInput` has `tool_response` ([11], [RAW]); extracts of [2] said `tool_output` (plus `tool_output_truncated`). Use `tool_response` and tolerate both; a success nudge needs only `tool_input.file_path`.

## 5. Interaction with permission modes and rules (question 3)

All [RAW] unless noted.

- **A hook deny blocks in every mode, including `bypassPermissions` and `--dangerously-skip-permissions`.** "`PreToolUse` hooks fire before any permission-mode check, in every permission mode, including `dontAsk`." and "A hook that returns `permissionDecision: "deny"` blocks the tool even in `bypassPermissions` mode or with `--dangerously-skip-permissions`." ([1], "Hooks and permission modes")
- **Auto mode:** auto is a permission mode, so the "every permission mode" sentence covers it. The auto-mode decision-order list in [6] starts with allow/ask/deny rules and does not mention hooks; the doc does not give an auto-mode-specific hook statement. Note that auto is now the built-in default in interactive terminal and VS Code sessions from v2.1.283 ([6]), so hooks will mostly run under auto.
- **An exit-2 block beats allow rules:** "A hook that exits with code 2 stops the tool call before permission rules are evaluated, so the block applies even when an allow rule would otherwise let the call proceed." ([5], "Extend permissions with hooks")
- **A hook `"allow"` does not bypass deny/ask rules:** "PreToolUse hook decisions don't bypass permission rules. Claude Code evaluates deny and ask rules regardless of what a PreToolUse hook returns" ([5]); also "a hook returning "allow" doesn't bypass deny rules from settings" ([1]). Hooks "can tighten restrictions but not loosen them past what permission rules allow" ([1]).
- **Exception that matters for a policy hook: mods.** "A block from a `PreToolUse` hook: the mod can approve the call, unless the hook is in managed settings." ([5]) A plugin "mod" handling `tool.check` can approve a call that a settings-file hook blocked. Only a managed-settings hook is protected.
- **Ways the hook never runs:** `"disableAllHooks": true` ([1]); `claude --bare` skips hook auto-discovery ([7]); `allowManagedHooksOnly` hides user/project hooks ([1]); a project `.claude/settings.json` hook is loaded from the launch directory's `.claude/` "with no parent-directory fallback" ([5]). Without `--bare`, `-p` runs do run project hooks "even in a folder you've never trusted" ([7]).
- **`acceptEdits` auto-approves `sed`:** "`acceptEdits` mode auto-approves common filesystem Bash commands: `mkdir`, `touch`, `rm`, `rmdir`, `mv`, `cp`, and `sed`." ([6]) So a hook (or a deny rule) is the only thing that stops `sed -i` there.
- **Native deny rules already cover some of the same ground:** "Read and Edit deny rules apply to Claude's built-in file tools, to file commands Claude Code recognizes in Bash, such as `cat`, `head`, `tail`, `sed`, and `tee`, and to the targets of Bash redirections" but not to "a Python or Node script that opens files itself" ([5], paraphrase with short quotes). These are path-based and have no marker escape; for OS-level enforcement the doc points to the sandbox.
- **Rule order** (not hooks): "Rules are evaluated in order: deny, then ask, then allow." ([5])

## 6. Matcher syntax, subagents, stdin fields (question 4)

**Matchers** (tool events match on tool name only).
- Guide [RAW]: `"Edit|Write"` fires only for those tools; "A comma separates alternatives the same way, so `"Edit, Write"` is equivalent." "Matchers are case-sensitive." "Hook `matcher` fields use bare tool names, not the parenthesized rule format." ([1], [4])
- Reference [SUMM, one fetch]: `"*"`, `""` or omitted matches all; a value of only letters, digits, `_`, `-`, spaces, `,`, `|` is an exact string or list; anything else is an unanchored JavaScript regex.
- "Matchers only match tool names, not file paths or other arguments. To filter by file path, check `tool_input.file_path` inside your hook." ([3]) [RAW]
- The `if` field (permission-rule syntax, e.g. `"Bash(git *)"`, `"Edit(*.ts)"`) filters by tool and arguments on tool events, but "the filter is best-effort, use the permission system rather than a hook to enforce a hard allow or deny", and "When Claude Code can't determine which commands the Bash input runs, it runs your hook regardless of the pattern." ([1]) [RAW]. Do the real decision inside the script.
- **Tool names:** `Bash`, `Edit`, `Write`, `NotebookEdit` are in the tools table ([4]). **`MultiEdit` is not in the tools table**; the permissions page calls it "the legacy `MultiEdit` tool" ([5]) [RAW]. Whether a `MultiEdit` matcher ever fires on current builds is **undocumented**; including it is harmless. `PowerShell` is a separate tool (default on Windows, opt-in on Linux/macOS): the guide says to "match `Bash|PowerShell`" for shell-command hooks and that "Claude can also create or modify files by running shell commands" ([1], [4]).

**Subagents: yes, settings hooks apply.**
- "Hooks from settings files, managed policy settings, and plugins also run inside subagents. When a subagent calls a tool, tool events such as `PreToolUse` and `PostToolUse` fire the same configured hooks as in the main conversation, and the input carries the `agent_id` and `agent_type`" ([2], Hook locations) [SUMM, same text in two separate fetches]; the sub-agents page says "a `PreToolUse` hook in `settings.json` also runs before every tool a subagent uses" ([8]) [SUMM].
- [RAW] corroboration: "`agent_id` and `agent_type` are populated when the hook fires inside a subagent." ([3])
- Subagent *frontmatter* hooks are additional and run only while that subagent is active ([8]); project-subagent frontmatter hooks need workspace trust ([8]).

**stdin JSON (tool events):**
- Common: `session_id`, `prompt_id`, `transcript_path`, `cwd`, `scratchpad_dir`, `permission_mode`, `effort`, `hook_event_name`, `agent_id`/`agent_type` (subagent only) ([2]) [SUMM, consistent].
- PreToolUse adds `tool_name`, `tool_input`, `tool_use_id`, and `attempt_number` ([2]) [SUMM, one fetch]. Example Bash input: `{"command": "npm test", "description": "Run test suite", "timeout": 120000, "run_in_background": false}` ([2], [1] gives `command` only) [SUMM/RAW].
- **Bash:** `tool_input.command` ("For Bash, its `command` field holds the shell command", [1]) [RAW]; also `description`, `timeout`, `run_in_background` ([2]).
- **Edit:** `file_path`, `old_string`, `new_string`, `replace_all`. [RAW] [4]: "It takes an `old_string` and a `new_string` and replaces the first with the second"; `replace_all: true` for all occurrences. **Conflict:** one extract of [2] wrote `old_str`/`new_str`; the tools reference says `old_string`/`new_string`, and a search synthesis of the SDK type reference lists `FileEditInput` as `file_path, old_string, new_string, replace_all?`. I take `old_string`/`new_string` as correct and treat `old_str` as an extractor error.
- **Write:** `file_path` ([5], "`file_path` for Read, Edit, and Write") [RAW]; `content` is from the SDK type summary (`FileWriteInput {file_path, content}`), not independently fetched.
- **NotebookEdit:** `notebook_path` ([5]) [RAW]; edit modes `replace | insert | delete`, `cell_id`, `cell_type` ([4]) [RAW]; the exact JSON names for the source text and mode are **not in the pages I could read**.
- Permission-rule doc confirms the primary content fields: "`command` for Bash and PowerShell, `file_path` for Read, Edit, and Write... `notebook_path` for NotebookEdit" ([5]) [RAW].

## 7. Size caps, timeouts, `continue`/`stopReason`/`suppressOutput` (question 5)

- **Cap:** "A hook's `additionalContext`, `systemMessage`, and `initialUserMessage` strings, and its plain stdout, are capped at **10,000 characters**." Over the limit: saved to a file in the session directory, replaced by the path plus "a preview of up to the first 2,000 characters"; "Claude Code doesn't ask Claude to read the file"; "this cap has no setting or environment variable to raise it." ([2], JSON output) [SUMM; the 10,000 figure also appears in the 2026-08 note and the "Add context" section]. **No documented cap for `permissionDecisionReason` or exit-2 stderr** on command hooks (plugin/mod deny reasons have a 4,096-character limit per the 2.1.292 notes, [14]; that is a different hook family).
- **Timeouts** ([1] [RAW]): "Override per hook with the `timeout` field in seconds." `command`, `http`, `mcp_tool`: 10 minutes; `prompt`: 30 s; `agent`: 60 s; `UserPromptSubmit`, `PreModelSwitch`, `PostModelSwitch`: 30 s; `MessageDisplay`: 10 s; `SessionEnd`: 1.5 s budget. (The 2026-08 note guessed milliseconds; the field is **seconds**.)
- **What a timeout does on PreToolUse:** command/http/mcp_tool hooks: "A timed-out `command`, `http`, or `mcp_tool` hook doesn't block the tool call. The call continues through the normal permission flow, so don't count on a stalled hook to act as a gate." ([2]) [SUMM, one fetch]. SDK *callback* hooks differ and fail closed: "Claude Code doesn't run the tool call, Claude receives a tool result stating the hook didn't respond before its timeout" ([3]) [RAW]. So a **command hook is fail-open on both crash and timeout**.
- **`continue`**: "If `false`, Claude stops processing entirely after the hook runs. Takes precedence over any event-specific decision fields." **`stopReason`**: shown to the user when `continue` is false and "stays in the conversation, so Claude sees it if the conversation continues." **`suppressOutput`**: "Has no effect: Claude Code accepts the field but doesn't act on it." **`systemMessage`**: user-side warning. ([2], universal fields table) [SUMM, one fetch]; `continue` and `systemMessage` also in [3] [RAW]. For PreToolUse/PostToolUse "the stop applies even when the tool call fails or completes while Claude is still streaming" ([2]) [SUMM]. None of these is what you want for a nudge or a soft block.
- **Parallelism:** matching hooks run in parallel; "One hook returning `deny` doesn't stop sibling hooks from executing." ([1]) [RAW]. `async: true` hooks "can't block, modify, or inject context" ([3]) [RAW].

## 8. Where my sources disagreed (so the researcher knows what not to trust)

Same page [2], different prompts, different output:

| Item | Extract A | Extract B | Settled by |
|---|---|---|---|
| `permissionDecisionReason` visibility | "Message shown to Claude or the user... When 'deny' is chosen, the message appears to Claude. When 'ask' is chosen, the message appears in the permission prompt." | "Shown to the user when `deny` blocks the call, and to Claude on `allow`, `ask`, and `defer`" (contradicts [1] and [3] for deny) | **Deny settled** by [1] and [3] (model sees it). **allow/ask unsettled.** |
| `defer` | Interactive queue, `/approve-deferred` | "Defer a tool call for later: NOT ON PAGE" | [1], [3] RAW: `-p`-only, `stop_reason: "tool_deferred"` |
| `updatedInput` + `deny` | "applies when allow, ask or defer, not deny" | Not stated | [3]: with `defer` it is ignored, with omitted decision it still applies. Unsettled for `deny`. |
| Edit field names | `old_str` / `new_str` | no per-tool shapes on page | [4] RAW: `old_string` / `new_string` |
| PostToolUse result field | `tool_output` | | [11] RAW: `tool_response` |
| PostToolUse `decision: "block"` | "No: Claude does not continue with blocking" (self-contradictory with the same extract's "reason ... appears as a system message") | "prevent Claude from continuing... similar to a Stop hook" | Unsettled. |

Treat sentences quoted from [2] as strong only where tagged "consistent". If a decision turns on any row above, probe it.

## 9. Does the documented channel actually work? (reported bugs, third-party evidence)

These are user reports on GitHub, not vendor statements, and several closed as stale/duplicate rather than fixed, so they are evidence of risk, not of current behaviour.

- **#19432** (v2.1.12, macOS): PreToolUse `additionalContext` "received but not injected"; same report says `permissionDecision: "deny"` and its reason work. Closed "not planned". ([16])
- **#55889** (v2.1.123, macOS CLI, `Bash` matcher): none of `additionalContext`, `systemMessage`, plain stdout reached the model for Pre or PostToolUse. Closed "not planned", labelled `stale`; no maintainer reply captured. ([16])
- **#79616** (v2.1.210, VS Code extension, 2026-07-21): PostToolUse `additionalContext` (a git-commit reminder) never appeared across 5 calls; closed 2026-09-23 "not planned". The summary of the reporter's snippet shows `additionalContext` at the **top level** of the JSON; if so that is the documented silent-ignore case ([1]) rather than a delivery bug. Unverified. ([16])
- **#24788** (PostToolUse `additionalContext` not surfacing for MCP tool calls) and **#46376** (plugin PostToolUse exit-2 output not injected) were also found; I did not read them beyond the summaries, so no weight placed on them. ([16])
- **Supporting, positive:** #15664 and #15345 (feature requests for PreToolUse `additionalContext`) are closed as implemented; v2.1.110 patched a real defect in the PreToolUse path, which implies the channel was in active use ([12], [13], [16]).

Net: the channels are documented, and the fixes that were acknowledged landed by v2.1.110; later non-delivery reports exist on specific surfaces (VS Code, one Bash-matcher setup). The one-session probe below costs minutes.

## 10. Documented mechanisms for a *model-side* override of a denial (question 6)

| Mechanism | Who decides | Documented? | Notes |
|---|---|---|---|
| **In-command marker** (`#ZIKARON-FORCE`) checked by the hook script | The model, by editing its own command | **Not a harness feature.** It is plain hook logic: the hook reads `tool_input.command`, finds the marker, exits 0 (no decision) so the normal permission flow runs. | Requires the deny reason to tell the model the marker syntax. The reason text reaches the model on `deny` ([1], [3]). Cannot be expressed with the `if` field reliably (best-effort, [1]); do it in the script. A shell comment is harmless at run time. |
| `permissionDecision: "ask"` | The **human** at a permission prompt | Yes ([1]: "show the permission prompt to the user as normal") | The model cannot self-approve. Behaviour in `-p`, `dontAsk`, and auto mode for a *hook*-issued ask is **not stated**. Related, [RAW]: in a `-p` run "with no host, these requests are denied either way" ([7], about permission requests generally). |
| `"allow"` with `updatedInput` | The hook (rewrites the command, e.g. strips the marker) | Yes ([3]) | A rewrite path, not an override. |
| `"defer"` | Outside caller via SDK | `-p` only ([1]) | Not a fit. |
| `PermissionDenied` hook with `retry: true` | tells the model "it may retry" | Documented for **auto-mode classifier denials** only: "When auto mode denies a tool call... Use JSON `hookSpecificOutput.retry: true` to tell the model it may retry" ([1]). Whether a *hook-issued* deny triggers this event is **not stated**. | Not a documented override of a hook deny. |
| Allow rule / `bypassPermissions` | n/a | **No**: they do not beat a hook deny or exit 2 ([1], [5]) | |
| Plugin "mod" `tool.check` | The mod | Yes ([5]): can approve a call a settings-file hook blocked, unless the hook is in managed settings | A security caveat for any hook-as-policy design. |

So: the only documented model-side escape is the one a hook implements itself; the only documented human-side escape is `ask`.

## 11. Verdict on the 2026-08-16 note (`research/claude-code-harness-contract.md`)

- "PreToolUse: stdout destination Unknown": **Resolved.** Exit-2 stderr and deny reason reach Claude; `additionalContext` is supported ("next to the tool result"); plain exit-0 stdout does not reach Claude (debug log only).
- "PostToolUse (cannot inject context on success)": **Refuted** for JSON `additionalContext` (and exit-2 stderr). **Confirmed** for plain stdout.
- Its table row "Exit 2: stderr is shown to the user": **wrong for PreToolUse**, where stderr is the reason fed to Claude.
- Its JSON sketch `"permissionDecision": "allow|deny|escalate"`: **wrong**; current values are `allow | deny | ask | defer`.
- Its timeout unit guess (milliseconds): **wrong**; seconds.
- Its matcher semantics ("INFERRED"): **now documented** (section 6).
- Its "10,000 characters" cap: **confirmed**, and it is a *per-field* cap on `additionalContext`/`systemMessage`/`initialUserMessage`/plain stdout, with a file-plus-2,000-char-preview fallback.

## 12. Implications for the two hooks (my inference, not documentation)

**Hook 1, deny file-editing Bash.**
- Register `PreToolUse` with matcher `Bash` (add `PowerShell` where that tool is enabled), decide inside the script. Return JSON `deny` with a `permissionDecisionReason` that states why and quotes the exact escape syntax, plus an optional `systemMessage` for the user; or exit 2 with the same text on stderr. Pick one approach per hook ([1]).
- Wrap the whole script so an internal error returns exit 2 (fail closed) if that is the intent; the default for a crash or a timeout is **fail-open**.
- The marker path costs the model one retry round trip (it must see the denial, then re-issue). The `ask` path costs a human interaction. The marker is the only option that stays autonomous.
- The block holds under `auto`, `acceptEdits`, `bypassPermissions` and over allow rules. It does not hold against a plugin mod's approval unless the hook is in managed settings, nor if hooks are disabled/`--bare`.
- Do not block read-only `sed -n 'X,Yp'`: the Edit tool treats that command form as satisfying read-before-edit ([4]), and it is the natural way for the agent to "re-read surrounding lines".
- The hook sees all Bash calls including subagents' (settings hooks apply to subagents, `agent_id` present), so a subagent definition cannot escape it without editing settings.
- Writing a script with the Write tool and then running it (a Python or Node file) is outside what a command-text check can see; the docs' own answer for that class is the sandbox ([5]).

**Hook 2, nudge after Edit/Write.**
- Register `PostToolUse` with matcher `Edit|Write|NotebookEdit` (optionally `MultiEdit`; legacy, undocumented whether it fires). Exit 0 with JSON `hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: "..."}`; do not use plain stdout (never reaches the model) and avoid `decision: "block"` (ambiguous, stronger than a nudge).
- Phrase the text as a factual statement ("src/x.py lines 40-60 were edited; ...") rather than an imperative system command, per the doc's prompt-injection note ([2]); keep it far below 10,000 characters; never include `<system-reminder>` tags (escaped as of 2.1.292).
- To nudge once per batch rather than once per edit, the SDK lists `PostToolBatch` ("once per batch before the next model call... inject conventions once for the whole batch", [3]); its `additionalContext` placement is "next to the tool result" per [2].
- The injected text is persisted and replayed on resume ([2]); a timestamped nudge goes stale.

## 13. Undocumented / unverified ledger

1. PreToolUse `additionalContext` **together with `deny`**: not stated; probe.
2. `permissionDecisionReason` visibility to Claude on `allow`/`ask`/`defer`: conflicting; probe if it matters.
3. Hook-issued `ask` in auto, `dontAsk`, `-p`: not stated.
4. Length cap for `permissionDecisionReason` / exit-2 stderr (command hooks): not stated.
5. Whether a hook-issued deny fires `PermissionDenied`: not stated.
6. `MultiEdit` matcher firing on current builds: undocumented (called "legacy").
7. NotebookEdit `tool_input` source-text/mode field names: not in pages read.
8. PostToolUse result field name: `tool_response` (SDK source) vs `tool_output` (an extract of [2]).
9. Where the *user* sees a PostToolUse exit-2 stderr: not stated.
10. `updatedInput` merge-vs-replace and whether a PreToolUse `updatedInput` is re-checked against deny rules: not stated.
11. PostToolUse `decision: "block"` effect on turn continuation for command hooks: ambiguous.
12. "Tool call blocked: [reason]" exact deny framing: single unverified sample.
13. Position of the `additionalContext` reminder relative to the tool result ("next to"): no finer statement.

## 14. Method: queries and fetches

Fetches (all WebFetch): hooks guide; hooks reference (13 differently-prompted fetches, to cross-check the extractor); `hooks.md` variant; tools reference; permissions; permission-modes; headless; sub-agents; Agent SDK hooks (via 307 redirect from platform.claude.com); Agent SDK TypeScript and Python references (both truncated before the type sections); changelog page (returned only 2.1.285-2.1.292); GitHub raw `CHANGELOG.md` (same window); GitHub release pages for v2.1.9, v2.1.110, v2.1.288, v2.1.292; raw `bash_command_validator_example.py`; raw `claude-agent-sdk-python/.../types.py`; raw plugin-dev `hook-development/SKILL.md` (extract looked stale/unreliable: "stdout shown in transcript"; **not relied on**); GitHub issues #15345, #15664, #19432, #55889 and claudeissues.com mirrors of #18465, #18534, #30899, #46376, #67442, #72996, #79616.

WebSearch queries:
1. `Claude Code changelog PreToolUse hook additionalContext permissionDecision "ask" hook output model sees`
2. `Claude Code release notes "PreToolUse" hooks "additionalContext" "now" version 2.1`
3. `"additionalContext" PreToolUse hook "tool failure" changelog Claude Code 2.1.110 fixed dropped`
4. `Claude Code "updatedToolOutput" PostToolUse hook "all tools" release notes updatedMCPToolOutput deprecated`
5. `claude-code issue PostToolUse hook additionalContext not reaching model Edit Write 2.1.2 hook context dropped bug`
6. `Agent SDK "Tool Input Types" FileEditInput old_string new_string replace_all FileWriteInput file_path content BashInput command`

Limits: no shell, so I could not `curl` the raw hooks reference; I could not read the changelog before 2.1.285 except through GitHub release pages for the four versions above; third-party blogs surfaced by search were not used as evidence (except the v2.1.121 `updatedToolOutput` date, marked secondary).

## 15. Evidence quality and open debate

- **Strongest (vendor docs read raw):** guide [1] and SDK hooks page [3] on exit 2, deny reason to model, permission-mode precedence, timeouts in seconds, subagent firing, `additionalContext` shape; permissions [5] on hook precedence and mods; tools reference [4] on field names; SDK source [11] on field and type names.
- **Medium (vendor docs via lossy extractor, cross-fetch consistent):** exit-2 table, 10,000-char cap, `additionalContext` placement, subagent sentence, command-hook timeout fail-open.
- **Weak (single extract or conflicting):** everything in section 8.
- **Third-party:** GitHub issues are user reports. They show a delivery risk, but closure reasons ("stale", "duplicate", "not planned") mean none is a vendor-confirmed defect or fix beyond v2.1.110.
- **Debate:** none in the docs; the open question is empirical (does each documented channel deliver on the harness version Zikaron targets).

## 16. Leads / probes (cheapest first)

1. **One-session probe on the installed version** (CLI and, if used, VS Code): a `PostToolUse` Edit hook returning `hookSpecificOutput.additionalContext` with a unique token; ask the agent to quote it. Repeat for `PreToolUse` `additionalContext` on an *allowed* Bash call, and on a *denied* one (item 1 of section 13). This settles whether the #19432 / #55889 / #79616 reports still bite.
2. Probe `deny` + exit-2 text framing in the transcript (does the model see "Tool call blocked:"?).
3. Probe a hook-issued `ask` under `-p` and under auto mode, only if the `ask` path is to be offered.
4. Check `MultiEdit`: does the current tool list include it? (`/mcp` or "What tools do you have?").
5. Read the hooks reference raw (needs a shell: `curl https://code.claude.com/docs/en/hooks.md`); the tools reference itself recommends `curl` via Bash for the unprocessed page. That would close every [SUMM] row and section 8 in one read.

## Sources

1. Automate actions with hooks (hooks guide). https://code.claude.com/docs/en/hooks-guide (read in full; current as of 2026-10-06) [RAW]
2. Hooks reference. https://code.claude.com/docs/en/hooks (fetched ~13 times through the page's lossy extractor; no verbatim full read possible) [SUMM]
3. Intercept and control agent behavior with hooks (Agent SDK). https://code.claude.com/docs/en/agent-sdk/hooks (redirected from platform.claude.com/docs/en/agent-sdk/hooks) [RAW]
4. Tools reference. https://code.claude.com/docs/en/tools-reference [RAW]
5. Configure permissions. https://code.claude.com/docs/en/permissions [RAW]
6. Choose a permission mode. https://code.claude.com/docs/en/permission-modes [RAW]
7. Run Claude Code programmatically (headless). https://code.claude.com/docs/en/headless [RAW]
8. Sub-agents. https://code.claude.com/docs/en/sub-agents [SUMM]
9. Claude Code changelog. https://code.claude.com/docs/en/changelog (extract covers 2.1.285-2.1.292 only) [SUMM]
10. Official example hook. https://raw.githubusercontent.com/anthropics/claude-code/main/examples/hooks/bash_command_validator_example.py [RAW]
11. claude-agent-sdk-python `types.py` (hook input/output TypedDicts). https://raw.githubusercontent.com/anthropics/claude-agent-sdk-python/main/src/claude_agent_sdk/types.py [RAW]
12. Release v2.1.9, 2026-01-16. https://github.com/anthropics/claude-code/releases/tag/v2.1.9
13. Release v2.1.110, 2026-04-15. https://github.com/anthropics/claude-code/releases/tag/v2.1.110
14. Release v2.1.292, 2026-10-06. https://github.com/anthropics/claude-code/releases/tag/v2.1.292
15. Release v2.1.288, 2026-10-02 (the page's extract printed the year as 2024; the docs changelog dates it 2026). https://github.com/anthropics/claude-code/releases/tag/v2.1.288
16. GitHub issues (user reports, third-party): #15345 https://github.com/anthropics/claude-code/issues/15345 ; #15664 https://github.com/anthropics/claude-code/issues/15664 ; #19432 https://github.com/anthropics/claude-code/issues/19432 ; #55889 https://github.com/anthropics/claude-code/issues/55889 ; #18465 https://claudeissues.com/issue/18465-docs-update-sdk-and-cli-hook-documentation-to-include-additionalcontext-support ; #18534 https://claudeissues.com/issue/18534-bug-additionalcontext-in-posttooluse-hook-is-documented-but-not-implemented ; #30899 https://claudeissues.com/issue/30899-bug-pretooluse-hook-with-additionalcontext-causes-model-turn-to-terminate-on-too ; #46376 https://claudeissues.com/issue/46376-plugin-posttooluse-command-hook-exit-2-output-not-injected-into-model-context ; #67442 https://claudeissues.com/issue/67442-posttooluse-updatedtooloutput-silently-ignored-for-built-in-tools-bash-webfetch ; #72996 https://claudeissues.com/issue/72996-docs-posttoolusefailure-documented-as-firing-after-a-tool-call-fails-but-built-i ; #79616 https://claudeissues.com/issue/79616-bug-posttooluse-hook-additionalcontext-memo-reminder-sh-not-reaching-claude-in-v ; (#24788 seen in search only: https://claudeissues.com/issue/24788-posttooluse-hooks-with-additionalcontext-not-surfacing-for-mcp-tool-calls)
17. Existing note: `/home/nathan/Zikaron/research/claude-code-harness-contract.md` (2026-08-16), the document under verification.
18. Secondary only (date of `updatedToolOutput`, v2.1.121, 2026-04-28): search synthesis citing https://claudeissues.com/issue/54161-docs-posttooluse-docs-still-describe-mcp-only-updatedmcptooloutput-instead-of-al
