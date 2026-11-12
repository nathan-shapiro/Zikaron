# Claude Code agent teams ("teammates") and which hooks fire for a teammate: what the official docs say

Date of reading: 2026-11-09. Source set: code.claude.com/docs only (agent teams, hooks reference, subagents, tools reference, cross-session messaging, hooks guide, settings reference, env vars, changelog and its RSS feed, and the mods pages the changelog pointed to). The docs read as of Claude Code **2.1.321** (newest changelog entry, 2026-11-06 per the RSS feed); the installed build in question is 2.1.311, so where a doc line carries a version floor it is recorded below.

Quotes are kept under ~30 words and are marked with quotation marks; everything else is paraphrase. "Not stated" means I searched the page text I read and found nothing; it is not a claim about the product's behavior.

## 1. The brief, restated

Zikaron pushes retrieved memory headlines into the main session on every user prompt through a `UserPromptSubmit` hook (`hookSpecificOutput.additionalContext`). Under Claude Code 2.1.311 with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, an in-process teammate gets the lead's messages as `<teammate-message>` user turns; its transcript shows `SubagentStart` firing on each message and `UserPromptSubmit` never. Question: which **documented** hook event can carry a per-message push to a teammate, and what does its input payload contain? Six sub-questions: (1) every hook event and which fire for subagents and teammates; (2) exact input fields for `SubagentStart`, `SubagentStop`, `TeammateIdle`, `TaskCompleted`; (3) output channels each honors; (4) in-process vs tmux/split-pane backends and whether a teammate loads project hooks; (5) message delivery timing and "interactive only"; (6) settings and env vars that change any of it.

## 2. Short answer

- The only settings-hook event the docs tie to a teammate **receiving a message** is `SubagentStart`. The hooks reference says it runs "each time an in-process agent team teammate handles a new message" (alongside Agent-tool spawn and subagent resume) [2, `#subagentstart`]. Its one output channel into the model is `hookSpecificOutput.additionalContext`, documented as "added to the subagent's context at the start of its conversation, before its first prompt" [2].
- **Its input carries no message text.** Documented fields are the common ones plus `agent_id` and `agent_type`. There is no prompt/message field, no `agent_transcript_path` (that is `SubagentStop` only), no `teammate_name`, no `team_name`, and no flag that distinguishes a teammate from an ordinary subagent [2].
- `UserPromptSubmit` is documented to fire on typed prompts and on exactly three non-typed triggers: a session-scoped scheduled task or `/loop` iteration, a background subagent reporting back to the session that started it, and a message another session sends to the main conversation [2, `#userpromptsubmit`]. Teammate-inbound messages are not among them, which matches what you observed.
- A per-message payload through `SubagentStart` is the documented route but has two documented hazards: re-run injection is conditional ("only when the subagent's context doesn't already hold the copy from an earlier run"), and the engine treats this context as prompt-prefix material for cache reuse (changelog 2.1.265). What happens when a later run returns **different** text is not stated. Needs a probe (section 9).
- Teammate-named events are `TeammateIdle`, plus `teammate_name` on `TaskCreated`/`TaskCompleted`. Neither fires at message arrival. No event is named for messages or mailboxes in the settings-hook set. The separate **mods** system (JS plugins, not `settings.json` hooks) does have `session.receive`, `session.send`, `agent.spawn` (with `e.isTeammate`) and `turn.start` (hears teammates' turns); whether any can inject context into a teammate is not documented (section 8).

## 3. Every hook event the docs list (33) and where teammates/subagents appear

Source: the "Hook lifecycle" table [2] (verbatim event names; "when it fires" paraphrased except where quoted).

| Event | Fires (docs) | Subagent | Teammate |
|---|---|---|---|
| `SessionStart` | session begins/resumes | not stated | not stated (section on SessionStart never mentions subagents/teammates; `agent_type` there means `claude --agent`) |
| `Setup` | `--init-only`, or `--init`/`--maintenance` with `-p` | n/a | n/a |
| `UserPromptSubmit` | prompt submitted; "Also fires on turns Claude Code starts on its own" | not stated (only "a background subagent reporting back to the session that started it" triggers it **in the parent**) | not stated; no teammate trigger listed |
| `UserPromptExpansion` | user-typed command expands | n/a | n/a |
| `PreToolUse` / `PostToolUse` / `PostToolUseFailure` / `PostToolBatch` | around tool calls | yes: "Tool events such as `PreToolUse` and `PostToolUse` fire for the subagent's tool calls the same way they do in the main conversation" [3] | implied: common field `agent_id` is "the subagent or in-process teammate the hook fires in" [2]; no sentence names `PreToolUse` for teammates |
| `PermissionRequest`, `PermissionDenied`, `Notification`, `MessageDisplay` | see page | not stated | `Notification` type `agent_needs_input` also fires for "an agent team teammate's terminal setup question" (v2.1.248+) |
| `SubagentStart` | "When a subagent is spawned" (table); section adds resume and teammate message | yes | **yes, per message**, in-process teammates |
| `SubagentStop` | "When a subagent finishes" | yes | not stated for teammates |
| `TaskCreated` | via `TaskCreate`; not fired in a session without Task tools | `agent_id` identifies "the subagent or in-process teammate creating the task" (v2.1.290+) | yes, optional `teammate_name` |
| `TaskCompleted` | `TaskUpdate` completion, or "when an agent team teammate finishes its turn with in-progress tasks" | `agent_id` as above | yes |
| `Stop` | "when the main Claude Code agent has finished responding" | converted to `SubagentStop` when defined in a subagent's frontmatter [3] | not stated; the teammate analogue is `TeammateIdle` |
| `StopFailure` | turn ends on API error | not stated | not stated |
| `TeammateIdle` | "When an agent team teammate is about to go idle after finishing its turn" | n/a | **yes, the only teammate-named event** |
| `InstructionsLoaded`, `ConfigChange`, `CwdChanged`, `DirectoryAdded`, `FileChanged`, `WorktreeCreate`, `WorktreeRemove`, `PreCompact`, `PostCompact`, `PreModelSwitch`, `PostModelSwitch`, `Elicitation`, `ElicitationResult`, `SessionEnd` | see page | not stated | not stated |

Notes:
- `TeammateIdle`, `TaskCreated`, `TaskCompleted`, `UserPromptSubmit`, `Stop`, `PostToolBatch`, `WorktreeCreate`, `WorktreeRemove`, `CwdChanged`, `MessageDisplay` take no matcher [2, matcher table; also 4].
- Subagent frontmatter hooks: all hook events supported, "most common" are `PreToolUse`, `PostToolUse`, `Stop` (converted to `SubagentStop`). Settings/managed/plugin hooks "all apply inside subagents" [3]. Whether a teammate spawned from a subagent definition honors that definition's `hooks:` frontmatter is **not stated**: the agent-teams page lists the parts it applies (`tools`, `model`, `disallowedTools`, `effort`, `autoCompactWindow`, body, `mcpServers` for split-pane) and says `skills` are not applied; `hooks` is on neither list [1].
- Changelog: 2.1.290 "TeammateIdle hooks no longer fire from its subagents or forks" (a teammate's own subagents) [9]; a 2.1.311-era bug-fix line fixed "SubagentStop hooks running about twice a minute for each running subagent instead of once" [9] (heading cut off by chunking; sits at the top of the range read above 2.1.310).
- Hook-type support: `SubagentStart` supports `command`, `http`, `mcp_tool` only (no `prompt`/`agent`); `TeammateIdle`, `TaskCompleted`, `TaskCreated`, `SubagentStop`, `Stop`, `UserPromptSubmit` support all five types [2, "Prompt-based hooks"].

## 4. Input payloads (verbatim JSON shapes from the hooks reference [2])

Common fields for all events: `session_id`, `prompt_id` (absent until first user input), `transcript_path`, `cwd`, `scratchpad_dir` (v2.1.257+), `permission_mode` (not every event gets it), `effort`, `hook_event_name`. Plus: "`agent_id` and `agent_type` tell your script which agent a hook fired in, such as a subagent, an in-process teammate, or the agent you chose with `--agent`." `agent_id` = "Unique identifier for the subagent or in-process teammate the hook fires in"; `agent_type` = agent name, "Present when the session uses `--agent` or the hook fires inside a subagent" [2, `#common-input-fields`].

`transcript_path` caveat: the file "is written asynchronously and may lag the in-memory conversation", so it may lack the current turn's latest messages when a hook fires [2].

**SubagentStart** (example in docs):
```json
{"session_id":"abc123","transcript_path":"/Users/.../00893aaf-....jsonl","cwd":"/Users/...",
 "hook_event_name":"SubagentStart","agent_id":"agent-abc123","agent_type":"Explore"}
```
Doc text: hooks "receive `agent_id` with the unique identifier for the subagent and `agent_type` with the agent name that the matcher filters on." Matcher = agent type name; plugin agents use scoped names such as `my-plugin:reviewer` (anchor with `^...$`). **No message text, no `teammate_name`/`team_name`, no teammate flag, no agent transcript path.** What `agent_type` holds for a teammate spawned without a named type is not stated (the team config "omits the field when the lead named none" [1]).

**SubagentStop**: common fields plus `stop_hook_active`, `agent_id`, `agent_type`, `agent_transcript_path`, `last_assistant_message`, and the `background_tasks`/`session_crons` arrays (parent-scoped). "The `transcript_path` is the main session's transcript, while `agent_transcript_path` is the subagent's own transcript stored in a nested `subagents/` folder." Example path `~/.claude/projects/.../abc123/subagents/agent-def456.jsonl` [2]. Also fires for Claude Code's internal agents (prompt suggestions, `/btw`), where `agent_type` can be an empty string.

**TeammateIdle**: common fields plus `teammate_name`, `team_name`, optional `agent_id`.
```json
{"session_id":"abc123","transcript_path":"...","cwd":"/Users/...","permission_mode":"default",
 "hook_event_name":"TeammateIdle","teammate_name":"researcher","team_name":"session-a1b2c3d4"}
```
`team_name` is "Deprecated. Session-derived team name; will be removed in a future release." `agent_id` "identifies the in-process teammate that is about to go idle. May be absent. Requires Claude Code v2.1.290 or later" [2]. No message text.

**TaskCompleted** / **TaskCreated**: common fields plus `task_id`, `task_subject`, optional `task_description`, optional `teammate_name`, deprecated `team_name`, optional `agent_id` (v2.1.290+). No message text [2].

**UserPromptSubmit** (main-session reference): common fields plus `prompt` (and `session_title` when set) [2].

**No event with a message/mailbox/teammate-message payload exists in the 33-event list.** `MessageDisplay` ("While assistant message text is displayed") is display-only and unrelated to inter-agent delivery.

Documented side channels a hook could read (not payload fields):
- Team name derivation: "`session-` followed by the first eight characters of the session ID" [1]. Team config `~/.claude/teams/{team-name}/config.json` has a `members` array "with each member's name and agent ID" and "Teammates can read this file to discover other team members" [1]. So `agent_id` -> teammate name is derivable from documented structures, though the exact JSON key names are not given, and the docs say not to edit the file.
- Mailbox: "`~/.claude/teams/{team-name}/inboxes/{agent-name}.json`"; entries are validated on read, invalid ones "reported as errors and removed from the file" [1]. The entry schema, whether a delivered entry is removed or flagged, and whether the entry is present when `SubagentStart` fires are **not stated**.
- Teammate transcript location: not stated for teammates; for subagents it is `.../{sessionId}/subagents/agent-{agentId}.jsonl` and `agent-{agentId}.meta.json` [2, 3].

## 5. Output channels per event

Cross-event rules [2]:
- Plain stdout reaches the model only on `UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, `PostModelSwitch` (plus `PreCompact` feeding the summary): "For most events, Claude Code writes stdout to the debug log and doesn't show it in the transcript." `SubagentStart` is **not** on the list, so its plain stdout is not documented to reach the subagent; use JSON.
- `additionalContext` is wrapped "in a system reminder and inserted into the conversation at the point where the hook fired". Placement by event: `SessionStart` and `SubagentStart` "at the start of the conversation, before the first prompt"; `UserPromptSubmit` "alongside the submitted prompt"; tool events "next to the tool result"; `Stop`/`SubagentStop` "at the end of the turn" [2, `#add-context-for-claude`].
- Cap: `additionalContext`, `systemMessage`, `initialUserMessage`, and plain stdout are capped at 10,000 characters each; over that, the text is written to a file in the session directory and the model gets the path plus a preview of up to the first 2,000 characters; Claude Code "doesn't ask" the model to read it [2].
- Facts about injected text: saved in the session transcript; replayed (not re-run) on resume [2]. Text framed as imperative system commands "can trigger Claude's prompt-injection defenses"; the docs advise factual statements [2].

| Event | Context to the model | Exit 2 | Other |
|---|---|---|---|
| `SubagentStart` | `hookSpecificOutput.additionalContext` -> the subagent/teammate's context (JSON example uses `hookEventName: "SubagentStart"`) | Not blockable. "Shows stderr to user only"; rendered as a `<hook name> hook error` notice in the subagent's own transcript; "Claude doesn't see it, and the session or subagent proceeds" | "can't block subagent creation". Re-run rule: injects "only when the subagent's context doesn't already hold the copy from an earlier run"; launch copy "stays in place, leaving the subagent's prompt cache intact"; after auto-compaction discards it, the next run injects again |
| `SubagentStop` | `decision:"block"` + `reason` keeps the subagent running and "delivers `reason` to the subagent as its next instruction"; `hookSpecificOutput.additionalContext` is non-error feedback that also keeps it running | Blocks stop; stderr delivered the same way | To inject into the **parent** after a subagent returns the docs say use `PostToolUse` on the `Agent` tool |
| `TeammateIdle` | none documented | Blocks idle: "the teammate receives the stderr message as feedback and continues working" | `{"continue": false, "stopReason": "..."}` "stops the teammate entirely, matching `Stop` hook behavior"; `stopReason` shown to the user. Prompt/agent hooks: `ok:false` stops the teammate by default; `continueOnBlock: true` feeds the reason back and keeps it working |
| `TaskCompleted` | none documented | Task not marked complete; stderr fed back to the model | `continue:false` stops the teammate only when a teammate finishing its turn triggered the event; ignored when `TaskUpdate` did |
| `TaskCreated` | none | Rolls back creation; message returned to Claude as the tool error | `continue:false` ignored |
| `UserPromptSubmit` | `hookSpecificOutput.additionalContext` (nested; top-level is ignored per [4]) or plain stdout; `decision:"block"` | Blocks; stderr shown to the user, not added to context | 30 s default timeout; on timeout output (including `additionalContext`) is discarded and the prompt proceeds |
| `PreToolUse` | `additionalContext` "alongside the tool result"; `updatedInput` rewrites the tool input | Denies; stderr is the reason | matches any tool name except `EndConversation` [2] |
| `PostToolUse` | `additionalContext` "alongside the tool result"; `updatedToolOutput` | stderr shown to Claude (tool already ran) | |

## 6. Teammate backends (question 4)

What the agent-teams page says [1]:
- Two display modes. "In-process: all teammates run inside your main terminal." "Split panes: each teammate gets its own pane ... Requires tmux, or iTerm2." Default `"in-process"`; `teammateMode` values `"auto"` (split panes only when already inside tmux or iTerm2 with `it2`), `"tmux"`, `"iterm2"`; flag `--teammate-mode` is "experimental and doesn't appear in `claude --help`".
- "Each teammate is a full, independent Claude Code session." Architecture table: teammates are "Separate Claude Code instances". The team config "holds runtime state such as session IDs and tmux pane IDs" [1]. Split-pane: "Each teammate has a full view of their own terminal."
- What a teammate loads: "When spawned, a teammate loads the same project context as a regular session: CLAUDE.md, MCP servers, and skills. If you start the lead with `--setting-sources`, teammates load from the same restricted list of sources. Before v2.1.281, split-pane teammates loaded every settings source." Changelog 2.1.281 confirms `--setting-sources` is now forwarded to "teammates, `/bg`, `claude agents` sessions and `--worktree --tmux`" [9].
- A teammate "also receives the spawn prompt from the lead. The lead's conversation history does not carry over."
- Definition application differs by backend: body is appended for in-process teammates but replaces the default system prompt for split-pane ones; split-pane teammates apply the definition's `mcpServers`, in-process ones ignore it and use project/user MCP settings; `autoCompactWindow` ignored by split-pane; `skills` not applied in either mode [1].

What the docs **do not say**:
- Not stated: that a tmux/iTerm2 teammate runs its own `SessionStart`, `UserPromptSubmit` or any hook. "Full, independent Claude Code session" and "Separate Claude Code instances" are the nearest text; hooks are not named in the list of what a teammate loads (CLAUDE.md, MCP servers, skills) [1].
- Not stated: that an in-process teammate loads `.claude/settings.json` hooks as such. The nearest statement is the `agent_id` description (hooks fire "in" an in-process teammate), `TeammateIdle`/`TaskCompleted`/`TaskCreated` being fired for teammates, and `SubagentStart` firing per message [2]. The statement that settings, managed and plugin hooks "all apply inside subagents" is about subagents, not teammates [3].
- Not stated: whether workspace trust (hooks from settings files are held back until the folder is trusted in interactive sessions [2, "Workspace trust"]) is re-evaluated for a split-pane teammate process.
- Hook-event inheritance: for split-pane, the changelog only records permission-flag and `--setting-sources` forwarding fixes (2.1.309, 2.1.281, 2.1.317), nothing about hooks [9].

## 7. Message delivery and "interactive only" (question 5)

Agent teams page [1]:
- "Automatic message delivery: when teammates send messages, they're delivered automatically to recipients. The lead doesn't need to poll for updates." Idle teammates notify the lead and include their final answer. Messages travel via the mailbox files; "Claude Code reports a message as sent only when the write to the recipient's mailbox file succeeds."
- "When Claude messages an in-process teammate that is no longer running, Claude Code brings it back in the same session ... and gives it the message as its next prompt." After `/resume`, teammates are not brought back.
- "A message from the lead or another teammate wakes an in-process teammate that is waiting to retry a failed API request."
- A message from another agent is presented to the receiver as coming from another Claude session, not from the user; the auto-mode classifier reviews each message before delivery [1, "Messages between agents"].
- **Between-turn vs mid-turn delivery to a teammate: not stated on the agent-teams page.** Related text elsewhere, none of it specific to teammates: cross-session messaging says the receiver "reads the message between tool calls during an active turn, so a running tool is never interrupted", and an idle session starts a new turn [6]; a viewed subagent/fork "keeps going and reads your message once that finishes" unless sent with Ctrl+Enter [3]; changelog 2.1.317 "a message to a running background agent arrives earlier: its running command moves to the background"; 2.1.290 and 2.1.277 refer to messages received "mid-run" or "mid-turn" [9]. Whether `SubagentStart` fires for a message that lands mid-turn vs one that wakes an idle teammate is not stated.
- The `<teammate-message>` wrapper tag you observe is **not documented** in any page read.
- "Interactive only": the docs say "Spawning teammates also requires an interactive session" and in `-p`/Agent SDK sessions Claude "doesn't spawn teammates, and a subagent that Claude names runs as an ordinary subagent" [1]. They do not call a teammate "interactive only" beyond that spawn condition. Related: subagents Claude names launch as teammates while agent teams are enabled, in an interactive session, "unless the call is a fork or passes `isolation`" [1, 3]; in-process teammates cannot run background subagents of their own [1].
- A permission deny rule on `SendMessage` "also removes messaging to subagents and agent-team teammates, since the same tool serves both" [6].

## 8. Settings, env vars and flags that touch any of the above (question 6)

| Item | What the docs say | Source |
|---|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | `1` enables; `0` makes named subagents launch as plain subagents again; re-read each time Claude spawns a subagent; settings `env` value re-applied on save; project/local/`--settings`/managed `env` entries of `1` can override a user-settings `0` | [1], [8] |
| `teammateMode` / `--teammate-mode` | `in-process` (default), `auto`, `tmux`, `iterm2` | [1], [7] index row |
| `--setting-sources` | restricts the sources teammates load, forwarded since 2.1.281 | [1], [9] |
| `disableAllHooks`, `allowManagedHooksOnly` | turn off settings hooks (and mods); managed-only restriction | [7] index rows (full entries not read) |
| `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` | raises the 8-continuation cap on `Stop` blocks | [2] |
| `subagentPromptCacheTtl`, `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL` | in-process teammate cache holds 5 minutes by default; `1h` raises it | [1], [7] |
| `CLAUDE_CODE_SUBAGENT_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`, `CLAUDE_CODE_SUBAGENT_EFFORT` (2.1.316) | teammate model/effort selection | [1], [9] |
| `teammateDefaultModel` | removed in v2.1.234 | [1] |
| `crossSessionInbound`, `dialogExpiry`, `isolatePeerMachines` | govern messages from other sessions (accept/hold/refuse); not stated to govern teammate messages | [6] |
| `CLAUDE_CODE_MESSAGING_SOCKET`, `CLAUDE_CODE_MESSAGING_TOKEN` | exported to hooks and Bash so a script or hook can post into **its own session's** inbox socket; "Each session exports its own"; not described for teammates | [6], [8] |
| `CLAUDECODE`, `CLAUDE_CODE_CHILD_SESSION` | set in hook command subprocesses | [8] |

No documented setting or env var switches `SubagentStart`'s per-message firing on or off, or adds message text to any hook payload. I found no teammate-specific hook setting. The env-vars page was read to ~100,000 of 188,974 characters; the settings reference to 100,000 of 455,074 (index rows only for the keys above).

## 9. Assessment against the brief, and leads

**What the docs license:**
1. `SubagentStart` + `hookSpecificOutput.additionalContext` is the documented per-message hook for in-process teammates. It cannot see the message, so a push keyed to the message content would have to find the text elsewhere. Documented candidates are the teammate's transcript (async, may lag the current turn by the docs' own warning) and the mailbox file (location documented, schema and timing not). Neither is promised.
2. A push that does not depend on message content (for example, retrieval keyed off the teammate's task or its `agent_type`, or the lead's last user prompt) needs only `agent_id`/`agent_type`/`session_id` and the documented `~/.claude/teams/session-<first8>/config.json` lookup.
3. The context is documented as living "at the start of its conversation" and deduplicated on re-run, and changelog 2.1.265 records a fix so teammates "no longer move SubagentStart hook context ... out of the prompt prefix on later turns" [9]. Read together, this feature is built for stable prefix context, not a fresh block per message. **Not stated:** whether changed text on a later run is injected, where it lands, or whether it replaces or accumulates.
4. `PostToolUse`/`PreToolUse` `additionalContext` inside the teammate's own tool calls ("next to the tool result") is a documented channel that carries `agent_id` for in-process teammates; it is per tool call, not per message (relates to FINDINGS Q1).
5. `TeammateIdle` exit 2 puts stderr in front of the teammate as feedback and keeps it working: an end-of-turn channel, not a start-of-message one.
6. Sender-side: `PreToolUse` matches any tool except `EndConversation` and can rewrite `tool_input` with `updatedInput`, so a hook matched on `SendMessage` could in principle edit an outgoing message. The hooks reference does not list `SendMessage`'s `tool_input` shape (it lists Bash, PowerShell, Write, Edit, Read, Glob, Grep, WebFetch, WebSearch, Agent, AskUserQuestion, ExitPlanMode); the tools reference documents `summary` and `notify_when_idle` inputs and the sub-agents page a `to` field. Not documented to reach the receiver; covers only model-sent messages, not messages the user types into a viewed teammate.
7. **Mods (a different extension system, not `settings.json` hooks)** [10]: a mod is a JS/TS plugin; "Mods are on by default" from v2.1.287; installed via a marketplace. Events relevant here, from the mods reference: `session.receive` ("A message arrives for this session, before Claude reads it"; fields `e.text`, `e.origin.kind` such as `peer`, `peer-send-message`, `task-notification`, `scheduled-trigger`; documented return `{ consumed: reason }`), `session.send`, `session.append` (rewrite a row's text blocks before it is stored), `prompt.submit` (can add `context` after the prompt), `agent.spawn` (`e.isTeammate`, `e.resume`), and `turn.start` (changelog 2.1.299: now also hears "subagents' and teammates' turns", distinguishable by `e.agentId`; documented as observe-only). Whether `session.receive`/`prompt.submit`/`session.append` run for an in-process teammate's inbound message, and whether any can add context for it, is not stated. Cost: a plugin and a build step, and a mod runs inside Claude Code with the user's full permissions [10]. Flagged as a lead only.

**Probes the docs cannot settle (not doc-derived; suggested):**
- Log the raw stdin of a `SubagentStart` hook for teammate message 1, 2, 3: any undocumented fields (prompt/message/teammate name)? Does `agent_type` hold anything when the lead named no type?
- With a hook that returns a different `additionalContext` per run, check the teammate transcript: is the second string injected, and where?
- Does a split-pane (tmux) teammate fire `SessionStart` and `UserPromptSubmit` from the project's `.claude/settings.json`? (Docs silent.)
- Is the message present in the teammate's transcript and mailbox JSON at the moment `SubagentStart` fires?

## 10. Evidence quality

- All claims come from first-party docs; none is a benchmark. The hooks reference is the authority for fields and channels. The agent-teams page is marked experimental and the feature is flagged "known limitations".
- Fetch method: WebFetch runs a small model over the page, so quotes passed through an extractor; the SubagentStart section, the TeammateIdle/TaskCompleted/TaskCreated/SubagentStop/Stop sections, and the hooks page from offset ~200,000 to its end were additionally seen as raw page text (saved tool output). The per-event "Exit code 2 behavior" table, event table, common-input-fields table and SessionStart section were read only through the extractor. The SubagentStart "each time an in-process agent team teammate handles a new message" sentence was seen three times (extractor on two different offsets, and a search engine's snippet of the live page). One extractor line (UserPromptSubmit stdout and `additionalContext` "injected as a system reminder that starts with the hook's name") could not be re-found in raw text and is not relied on here.
- Version drift: docs are at 2.1.321, the build in question is 2.1.311. Dated behavior: `agent_id` on `TeammateIdle`/`TaskCompleted`/`TaskCreated` needs v2.1.290+; `scratchpad_dir` v2.1.257+. I did not find the version in which per-message `SubagentStart` firing for teammates was introduced (changelog read to ~2.1.196 via keyword extraction, which can miss entries).
- Changelog coverage: chunks 0-800,000 of 1,213,515 characters, keyword-filtered by the extractor, plus the RSS feed (2.1.304-2.1.321).

## 11. Search queries and fetches

Fetches (all code.claude.com/docs/en): `agent-teams`; `hooks` (offsets 0, 60000, 88000, 100000, 108000, 186000, 200000); `sub-agents` (0, 100000); `llms.txt`; `tools-reference`; `cross-session-messaging`; `hooks-guide`; `settings-reference` (0); `env-vars` (0, 100000 unread beyond a preview); `changelog` (0-800000 in 100k steps; keyword-filtered); `changelog/rss.xml`; `plugins/mods/reference`, `plugins/mods/events`, `plugins/mods/api`, `plugins/mods/overview`.

Searches (restricted to code.claude.com): "code.claude.com docs agent teams teammate hooks SubagentStart "teammate" UserPromptSubmit"; "Claude Code changelog "SubagentStart" hook context prompt prefix teammates resumed subagents prompt cache"; "Claude Code changelog TeamCreate TeamDelete removed one implicit team experimental agent teams"; "Claude Code "SubagentStart" hooks now fire "teammate" each message in-process agent team changelog whats-new".

Side facts surfaced by search: agent-teams docs record that `TeamCreate`/`TeamDelete` were removed at v2.1.178 and each session now has one implicit team (search-engine summary of the docs; not re-verified on the page, which now says "One team per session").

## 12. Sources

1. Orchestrate teams of Claude Code sessions (agent teams) - https://code.claude.com/docs/en/agent-teams (read in full)
2. Hooks reference - https://code.claude.com/docs/en/hooks (anchors used: `#hook-lifecycle`, `#common-input-fields`, `#userpromptsubmit`, `#add-context-for-claude`, `#subagentstart`, `#subagentstop`, `#taskcreated`, `#taskcompleted`, `#stop`, `#teammateidle`, `#exit-code-2-behavior-per-event`, `#decision-control`, `#prompt-based-hooks`, `#workspace-trust`)
3. Create custom subagents - https://code.claude.com/docs/en/sub-agents (first 100,000 of 116,972 chars plus a late chunk)
4. Automate actions with hooks (hooks guide) - https://code.claude.com/docs/en/hooks-guide
5. Tools reference - https://code.claude.com/docs/en/tools-reference
6. Message your other Claude Code sessions (cross-session messaging) - https://code.claude.com/docs/en/cross-session-messaging
7. All settings - https://code.claude.com/docs/en/settings-reference (index rows and `subagentPromptCacheTtl` only)
8. Environment variables - https://code.claude.com/docs/en/env-vars (first 100,000 chars)
9. Claude Code changelog - https://code.claude.com/docs/en/changelog and https://code.claude.com/docs/en/changelog/rss.xml (entries cited: 2.1.321 to 2.1.304 via the RSS feed; 2.1.311-era SubagentStop fix; 2.1.299, 2.1.295, 2.1.290, 2.1.289, 2.1.281, 2.1.277, 2.1.265, 2.1.261, 2.1.260, 2.1.199)
10. Mods: overview https://code.claude.com/docs/en/plugins/mods/overview ; events https://code.claude.com/docs/en/plugins/mods/events ; reference https://code.claude.com/docs/en/plugins/mods/reference ; API https://code.claude.com/docs/en/plugins/mods/api
11. Docs index - https://code.claude.com/docs/llms.txt
