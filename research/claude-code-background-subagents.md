# Claude Code background subagents: permissions, nesting and `-p` behavior

**Researched 2026-10-16** from Claude Code's official documentation (code.claude.com/docs). The pages carry no
date of their own. The changelog [12] lists **2.1.301 (2026-10-15)** as the newest release, and the pages cite
versions up to v2.1.301, so what follows describes docs current as of that release. The local probe in
`research/nested-subagent-probe.md` [13] ran on 2.1.287.

## The brief, restated

`zikaron-document-code` is about to change so that, under Claude Code, the invoking session spawns one
**background** orchestrator subagent and returns control at once. The orchestrator runs Bash repeatedly,
spawns documenter subagents with the Agent tool (main -> orchestrator -> documenter, two levels), and the
documenters create files with Write. The coordinator needs, from official docs only, what happens to
permission prompts in that shape, whether `claude -p` waits for a background subagent, and the answers to
Q1-Q6, plus two follow-ups: Q7 (can `tools:` restrict spawnable subagent types) and Q8 (skills with
`context: fork`). Quotes are kept under 30 words each; where a sentence is longer the note paraphrases and
quotes only the load-bearing clause. "NOT DOCUMENTED" means the pages fetched are silent, and nothing is
inferred into that slot. Inferences are labelled **[inference]**.

## Answers at a glance

| # | Question | One-line answer |
|---|---|---|
| 1 | Background-subagent permissions | **No up-front prompt, no auto-deny in an interactive session**: each prompt surfaces in the main session, naming the subagent. With no one to answer (`-p` without a host) the call is **denied** unless a rule or `PermissionRequest` hook allows it. Grandchild: not explicitly documented |
| 2 | Pre-approval mechanisms | `permissions.allow` rules (Bash prefix `Bash(cmd *)`; **file rules must be written `Edit(...)`, a `Write(...)` path rule is never consulted**), `--allowedTools`, hooks. `permissionMode` is **ignored whenever the main session is in auto, acceptEdits or bypassPermissions**. `tools:` only makes a tool available; the docs never call it pre-approval |
| 3 | Foreground vs background | Interactive default (fork mode on): **always background, model cannot choose**. `-p` (fork mode off): model chooses via `run_in_background`, default background. `background: true` in frontmatter forces background; no documented field forces foreground |
| 4 | `claude -p` and background subagents | **It waits**: "the run stays open until that work completes". But idle waiting is capped at **10 minutes by default** and the partial result is dropped; `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` removes the cap |
| 5 | Completion notification | A completion notification in a later turn; the parent sees only the subagent's final result |
| 6 | Nesting limits | Default **three layers** below main; a background subagent keeps `Agent` unless at the limit. Nested spawns are allowed from a background subagent |
| 7 | `tools:` restricting spawnable types | `Agent(type, ...)` syntax **exists but is honored only for a `claude --agent` main thread; in a subagent definition the type list is ignored** |
| 8 | Skill with `context: fork` | Skill body is the prompt of a **new, fresh** subagent of type `agent:` (built-in or custom from `.claude/agents/`, default `general-purpose`). **Background by default interactively** (`background: false` opts out, v2.1.218+); **`-p` waits for it in the turn**. Depth accounting, `Agent` tool, and `allowed-tools` inside the fork: **not documented** |

## Flags against the working assumption

1. **"A background subagent cannot prompt the user interactively" is contradicted for interactive sessions.**
   The current docs say prompts are forwarded to the main session. The assumption holds only in a session with
   no prompt host (`claude -p` without an Agent SDK callback or `--permission-prompt-tool`), where the prompt
   is denied rather than shown.
2. **`Write(code-knowledge/**)` as an allow rule does nothing.** The docs say Claude Code accepts the rule and
   never consults it. Use `Edit(...)`, which covers Write.
3. **A frontmatter `permissionMode` is ignored in the built-in default interactive mode.** Auto mode is the
   built-in starting mode for interactive sessions from v2.1.283, and a subagent's `permissionMode` is ignored
   when the parent is in auto, acceptEdits or bypassPermissions.
4. **A `-p` headless run is not guaranteed to outlive a long orchestrator.** The 10-minute idle ceiling may cut a
   long background run unless raised; whether orchestrator activity counts as "idle" is not documented.
5. **In `-p`, a launcher does not wait for its nested background subagents**, so an orchestrator can end while
   documenters still run, and their results then report to the main conversation. In an interactive session the
   launcher does wait.
6. **A subagent's `tools: Agent(zikaron-documenter)` cannot restrict the orchestrator to one type.**
7. **Project `permissions.allow` rules are not used by a `-p` run in a folder never trusted interactively.**
8. **A `context: fork` skill blocks, rather than backgrounds, in `-p`, and also when the same skill is already
   running** (Q8c). A skill's `allowed-tools` is a per-turn grant and is not documented to reach a background
   fork.

## Q1. Permission handling for a background subagent

**Up-front prompt before launch: no.** The Agent tool reference [5] says "Launching the subagent doesn't itself
prompt for permission. Claude Code checks the subagent's own tool calls against your permission rules as it
runs." The permission-modes page [4] adds one exception under auto mode: "Before a subagent starts, the
delegated task description is evaluated, so a dangerous-looking task is blocked at spawn time" (classifier
review, not a user prompt).

**Auto-denied once running: no, in an interactive session.** The subagents page [1], section "Run subagents in
foreground or background":

- "When a background subagent reaches a tool call that needs permission, Claude Code surfaces the prompt in
  your main session and names the subagent that is asking."
- "Approve to let the subagent continue, or press Esc to deny that one tool call without stopping the
  subagent."
- "Background subagents surface every permission prompt in your main session."
- On the effect of an answer: "Claude Code applies your answer to the whole session, including your main
  conversation" (for a choice that lasts beyond one call, such as a session-long grant).

The tools reference [5] repeats it: "Background subagents surface permission prompts in your main session. The
prompt names which subagent is asking, and pressing Esc denies that one tool call without stopping the
subagent." The interactive-mode page [6] notes that Ctrl+X Ctrl+K (stop all background subagents) can be
pressed while a background subagent's permission prompt is open, which confirms prompts are live objects in the
main UI.

**When nobody can answer (headless).** The hooks page [7], `PermissionRequest`: "In sessions that can't show a
prompt, such as background subagents in non-interactive mode, Claude Code still runs these hooks", and "if no
hook returns a decision, it denies the tool call" (one sentence on the page; the two clauses are quoted
separately). The headless page [2], section "Turn off permission prompts in unattended runs": "In a `-p` run
with no host, these requests are denied either way". `--permission-prompts none` (v2.1.259+) additionally tells
Claude not to retry. The CLI reference [10] gives `--permission-prompt-tool` as the MCP-tool route for
non-interactive prompts. With `--output-format stream-json`, denials appear as `permission_denied` system
messages and in `permission_denials` on the result [2].

**Auto mode** [4], "How auto mode handles subagents": "While the subagent runs, each of its actions goes
through the same decision order as in the parent session, with the same block and allow rules." So under auto
mode the classifier, not the user, decides the ordinary prompts. In-working-directory file edits and read-only
actions are auto-approved by the decision order ("Read-only actions and file edits in your working directory
are auto-approved" [4]); Bash goes to the classifier unless a narrow allow rule matches. In `-p`, repeated
classifier blocks do not stop the run: "the action doesn't run and Claude keeps working" [4].

**Does this apply to the grandchild? NOT DOCUMENTED explicitly.** No page says where a nested subagent's
prompts surface. What the docs do say: "A nested subagent is configured the same way as a top-level one and
resolves from the same scopes" [1]; background subagents surface "every permission prompt" in the main session
[1]; and the nesting section says only that, interactively, "only the top-level subagent's summary returns to
you" [1] (that sentence is about results, not prompts). **[inference]** the grandchild's prompts go to the main
session too, but no sentence says so. This is worth a probe (see Leads).

## Q2. Pre-approval mechanisms

### 2a. `permissions.allow` rules

Evaluation order [3]: "Rules are evaluated in order: deny, then ask, then allow. The first match in that order
determines the outcome". The deny rule documented for subagents: a Bash deny rule in settings "applies to the
main conversation and to subagents" [1]. The docs are otherwise **silent on whether allow rules apply to
subagents** (the fetch of the subagents page found no explicit sentence); the Agent tool reference says the
subagent's tool calls are checked "against your permission rules" [5], which is the closest statement.

**Bash command prefix.** The syntax [3], "Wildcard patterns":

- "A `*` at the end, with a space before it, also matches the bare command." Example rows:
  `Bash(npm run *)` matches `npm run build` and `npm run`; `Bash(ls *)` matches `ls -la` and `ls` but not
  `lsof`; `Bash(ls*)` matches `lsof` too.
- "The `:*` suffix is an equivalent way to write a trailing wildcard, so `Bash(ls:*)` matches the same commands
  as `Bash(ls *)`."
- "The space before a trailing `*` is part of the rule."
- "Claude Code matches everything before the first `*` as written" (the warning box: put the `*` after the
  subcommand; a `*` before the subcommand draws a startup warning).
- A rule with no `*` is exact: `Bash(npm run build)` does not match `npm run build --watch`.

Traps relevant to an orchestrator that runs a planner repeatedly:

- Compound commands [3]: "A rule must match each subcommand independently." Separators recognized: `&&`, `||`,
  `;`, `|`, `|&`, `&`, newlines. A `cd x && planner ...` needs both parts allowed (`cd` into the working
  directory is in the read-only set).
- Wrappers stripped before matching: `timeout`, `time`, `nice`, `nohup`, `stdbuf`, plus `command`, `builtin`,
  zsh `noglob`. A leading assignment of an env var outside the known-safe set defeats an allow rule: "An allow
  rule won't match past an assignment of any other variable." [3]
- Not stripped: `npx`, `docker exec`, `direnv exec`, `mise exec` and similar runners [3].
- Redirects: a `> file` target is checked against the file rules as if Claude had written the file; "A rule
  such as `Bash(git commit *)` allows the command, not the target." [3]
- In auto mode "broad allow rules that grant arbitrary code execution are dropped": a blanket `Bash(*)`,
  "Wildcarded interpreters like `Bash(python*)`", package-manager run commands and `Agent` allow rules.
  "Narrow rules like `Bash(npm test)` stay in effect." [4] Where exactly a rule such as
  `Bash(python -m zikaron.code_knowledge *)` falls between "narrow" and "wildcarded interpreter" is **NOT
  DOCUMENTED**.

**Write restricted to a directory.** The syntax claim to correct. The permissions page [3], section "Read and
Edit":

- "Claude Code checks file permissions against `Edit(path)` and `Read(path)` rules only."
- The page says a path rule for `Write`, `NotebookEdit`, `Glob` or `MultiEdit` is accepted, never consulted,
  and warned about at startup (requires v2.1.210+), and it directs: "Use `Edit(docs/**)` in place of
  `Write(docs/**)`".
- The tools reference [5] table row confirms the coverage: `Edit(/src/**)` applies to "Edit, Write,
  NotebookEdit". It adds that "An `Edit(...)` allow rule also grants read access to the same path".
- The errors page [11] has the matching startup-warning entry ("... is not matched by file permission
  checks"), though its text is vaguer than the permissions page.

Path semantics [3] (gitignore syntax, four anchors):

| Pattern | Meaning |
|---|---|
| `//path` | absolute path from the filesystem root |
| `~/path` | from the home directory |
| `/path` | "Path relative to the settings source" (in `.claude/settings.json`: `<primary working directory>/path`; in `~/.claude/settings.json`: `~/.claude/path`) |
| `path` or `./path` | relative to the current directory |

- "A pattern like `/Users/alice/file` isn't an absolute path. The single leading slash anchors at the settings
  source, not the filesystem root."
- Allow rules: "`Edit(src/**)` matches only `<cwd>/src` and the files under it. To allow a directory name at
  any depth, write `Edit(**/src/**)`." (Deny and ask rules match a single-segment directory at any depth.)
- Example from the page: `Edit(/docs/**)` is "edits in `<primary working directory>/docs/`, not `/docs/` or
  `<primary working directory>/.claude/docs/`".
- So `Edit(code-knowledge/**)` (cwd-relative) or `Edit(/code-knowledge/**)` (project-root anchored when in
  project settings) are the documented forms. **[inference]** the root-anchored form is the safer one for a
  subagent, since the docs do not say what "current directory" means inside a subagent (see Leads).
- Protected paths: writes to `.git`, `.claude` and similar are never auto-approved except in bypass mode [4];
  `code-knowledge/` is not named as protected on the pages read.

Trust gating [3], "Project allow rules and workspace trust": project-level `permissions.allow` rules "grant
capability, so Claude Code applies them only after you accept the workspace trust dialog". The table row for
`claude -p` in a folder never trusted says the allow rules and `additionalDirectories` are "Not used" and a
`this workspace has not been trusted` warning prints to stderr. A skill's `allowed-tools` is not gated. A user
who has accepted the trust dialog in that folder before is not covered by that row. The same page notes that
`hasTrustDialogAccepted` can be set by hand in `~/.claude.json`.

### 2b. `permissionMode` frontmatter

Field [1]: "`permissionMode` | Permission mode: `default`, `acceptEdits`, `auto`, `dontAsk`,
`bypassPermissions`, `plan`, or `manual` as an alias for `default`. Ignored for plugin subagents." (the table
row; the quote is shortened from it.) Interaction with the parent's mode [1], "Permission modes":

- "If you leave it unset, the subagent inherits the main conversation's permission mode."
- "When the main conversation is in `bypassPermissions`, `acceptEdits`, or auto mode, the subagent runs in that
  same mode and Claude Code ignores the `permissionMode` you set."
- "When the main conversation is in `default`, `dontAsk`, or `plan` mode, the subagent runs in the permission
  mode you set", with two exceptions: `bypassPermissions` is kept at the parent's mode (v2.1.267+), and `auto`
  falls back when auto mode is unavailable to the subagent.
- Auto mode page [4]: "Any `permissionMode` in the subagent's frontmatter is ignored."
- `acceptEdits` auto-approves edits and `mkdir`, `touch`, `rm`, `rmdir`, `mv`, `cp`, `sed` "only to paths inside
  your working directory or `additionalDirectories`"; "all other Bash commands except the built-in read-only
  set still prompt" [4]. (`acceptEdits` does not approve an arbitrary planner command.)
- `dontAsk`: "Auto-deny permission prompts. Explicitly allowed tools still work" [1].
- **Honored for background agents?** The pages draw no background-specific distinction: the rules above apply
  by the parent's mode. NOT DOCUMENTED beyond that.
- **[inference]** Built-in starting mode: "With Claude Code v2.1.283 or later, auto mode is the built-in
  starting permission mode for interactive terminal and VS Code sessions" [4], so in a default interactive
  session the frontmatter `permissionMode` is ignored. For `-p` [4] the built-in start is `default` in sessions
  that fetch feature flags, and `auto` (v2.1.285+) in sessions that do not.
- Plugin-supplied subagents ignore `permissionMode`, `hooks` and `mcpServers` [1].

### 2c. `tools:` frontmatter

- "`tools` | Tools the subagent can use ... Inherits every tool available to subagents if omitted." [1]
- "To restrict tools, use the `tools` field as an allowlist or the `disallowedTools` field as a denylist." [1]
- **Does listing a tool pre-approve it? NOT DOCUMENTED as a statement.** Every sentence on the pages treats
  `tools:` as availability; permission is decided afterwards by rules and mode ("Claude Code checks the
  subagent's own tool calls against your permission rules as it runs" [5]). **[inference]** it does not
  pre-approve. The contrast is the skill field: `allowed-tools` "grants permission for the listed tools during
  the turn that invokes the skill" and "does not restrict which tools are available" [9], which is the
  mirror-image semantics and is what makes the omission on the subagent side meaningful. The skills page does
  not say whether a skill's `allowed-tools` grant reaches subagents spawned in that turn (NOT DOCUMENTED).
- Background subagents keep only a reduced built-in set [1]: `Read`, `Grep`, `Glob`, `LSP`, `Bash`,
  `PowerShell`, `Edit`, `Write`, `NotebookEdit`, `WebFetch`, `WebSearch`, `TodoWrite`, `Skill`, `ToolSearch`,
  `EnterWorktree`, `ExitWorktree`, `Monitor`, `TaskStop`, `SendMessage`, `Artifact`, and every MCP tool, with
  `Agent` following the depth rule. `AskUserQuestion` is removed from every subagent. The removal "reports no
  error unless it leaves the `tools` list resolving to nothing".

### 2d. Other pre-approval routes documented

- `--allowedTools` (CLI): "Tools that execute without prompting for permission" [10]; headless page [2]:
  "The `--allowedTools` flag uses permission rule syntax." In a run that starts in auto mode, a bare `Bash`
  entry is dropped [2].
- A `PreToolUse` hook returning allow; `PermissionRequest` hook decisions (`"behavior": "allow"`, optionally
  `updatedPermissions` to add an allow rule or change the mode) [7]. "Deny and ask rules are still evaluated, so
  a hook returning `"allow"` doesn't override a matching deny rule" [7].
- Hooks run inside subagents: "tool events such as `PreToolUse` and `PostToolUse` fire the same configured
  hooks as in the main conversation, and the input carries the `agent_id` and `agent_type`" [7].
- `dontAsk` plus allow rules or `--allowedTools` for locked-down runs [2][4].

## Q3. Foreground vs background

Subagents page [1], "Run subagents in foreground or background": for each Agent-tool subagent, "Claude Code
picks foreground or background from the first of these cases that applies":

1. An in-process agent-team teammate's subagent: foreground.
2. `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`: "Claude Code runs the subagent in the foreground, in every kind of
   session" (paraphrase of the clause; the env-var page [8] says it disables "the `run_in_background`
   parameter on Bash and subagent tools").
3. Fork mode on (interactive default from v2.1.232): Claude Code "runs the subagent in the background, forks and
   non-fork subagents alike, and Claude can't ask for the foreground."
4. Fork mode off: "Claude runs the subagent in the background by default and in the foreground when it needs
   the result before continuing."

- Fork mode and `-p`: "Fork mode is off in non-interactive mode with `-p` and in the Agent SDK unless you turn
  it on." `CLAUDE_CODE_FORK_SUBAGENT=1` turns it on in `-p`; `=0` turns it off everywhere [1][8].
- Parameter: with fork mode on, "Claude Code also removes the Agent tool's `run_in_background` parameter, so
  Claude can't ask for the foreground." [1] So the parameter exists when fork mode is off.
- Frontmatter: "`background` | Set to `true` to keep this subagent in the background even when Claude asks to
  run it in the foreground." [1] The subagents page also has the line: "To keep a particular subagent in the
  background even when Claude wants the result, set its frontmatter `background` field to `true`."
- Manual: "Press Ctrl+B to background a running task" [1].
- **Can an agent definition force background?** Yes: `background: true`. **Foreground?** No documented
  frontmatter field for a subagent definition; only `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` (global) and the
  fork-mode-off model choice. A skill using `context: fork` has its own `background: false` [9] (Q8).
- **[inference]** In an interactive session with defaults, every subagent the orchestrator spawns is also a
  background one, and the orchestrator cannot request foreground; it waits on completion notifications (the
  probe saw each nested Agent call return "running in the background" first [13]). Whether the fork-mode
  default applies identically at depth 2 is not stated.

## Q4. Headless `claude -p` and background subagents

Headless page [2], section "Background tasks at exit" (raw page read):

- "After Claude finishes its turn and stdin has closed, a `claude -p` run can stay open to wait for background
  work that Claude started."
- "Background subagents and workflows: the run stays open until that work completes, because its result is part
  of the final output."
- The ceiling: unless a main-conversation background command is still running, Claude Code "stops whatever is
  still running after 10 minutes of continuous idle waiting by default and drops its partial result." Change it
  with `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`, "or set it to `0` to wait without one."
- Env-var page [8]: "Idle waiting starts over each time Claude takes a turn to handle a background result."
  "When idle waiting reaches the ceiling, Claude Code stops waiting for the remaining background tasks."
  "Set to `0` to wait indefinitely." (requires v2.1.182+).
- Visibility: when stderr is a terminal and the run has waited five seconds, a line starting `Waiting for
  background work to finish` is printed to stderr; with `json`/`stream-json` output it prints only when stdout
  is not a terminal.
- "If the run reaches its `--max-budget-usd` cap, Claude Code stops the remaining background work instead of
  waiting." [2] The CLI page [10] adds that spend from subagents counts toward the cap and that, at the cap,
  "spawning another subagent fails with `Budget limit reached`".
- Output: "When background work starts another turn, the run prints each turn's result with the default `text`
  output and the last turn's result with `json` output." (v2.1.295+ for `text`.)
- Nested case [1]: "In non-interactive mode and the Agent SDK, the launching subagent doesn't wait, so a nested
  background subagent that finishes after its launcher has ended reports to your main conversation instead."
  Interactive: "a subagent that launches background subagents waits for their results before it finishes."
- Related: background Bash. A command a *background subagent* started "is stopped when the run exits" [5];
  unattended sessions apply a time limit to background commands (10 minutes by default in a `-p` run whose
  prompt is passed as text) [5].
- `--bare`: "Background tasks: none run." [2] and the interactive-mode page says bare mode "turns it off as well"
  (it disables background task functionality) [6]. **[inference]** under `--bare`, subagents run foreground by
  the foreground-forcing rule, but no page states this combination.

**Net answer:** `claude -p` waits for a background subagent, bounded by the idle ceiling; it does not exit
immediately. **What is not documented:** whether a single long-running background subagent that produces no
turn-handling in the parent counts as "continuous idle waiting" for the whole run (the text "Idle waiting
starts over each time Claude takes a turn to handle a background result" suggests it does, since the parent
takes no turn while the orchestrator works). **[inference]** a documentation run longer than 10 minutes needs
`CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`, or the orchestrator's work may be cut with partial results dropped.
That should be probed before relying on it.

## Q5. Notification of the parent on completion

- "A background subagent's results reach Claude as a completion notification in a later turn. Claude waits for
  that notification before reporting the subagent's results, and if you ask about progress first, it reports
  that the subagent is still running." [1] (quoted in two clauses.)
- What the parent sees [5], "Agent tool behavior": "The parent doesn't see the subagent's intermediate tool
  calls or outputs, only that final result." For a failure: "the message Claude receives when it ends names the
  API error and includes the subagent's last output" [1].
- Forks: "When it finishes, its result arrives as a message in your main conversation." [1]
- `SubagentStop` hook input carries `last_assistant_message`, `agent_id`, `agent_type`,
  `agent_transcript_path`, and "Both arrays are scoped to the parent session" for `background_tasks` and
  `session_crons` [7]. SubagentStop cannot inject context into the parent; the docs direct that use to a
  `PostToolUse` hook on the `Agent` tool [7].
- Auto mode: "When the subagent finishes, the classifier reviews its work and its final report before the
  parent reads the report", with a prepended warning when flagged [4]. The tools reference lists
  `SubagentHandback` as the tool that "Delivers a subagent's final report to whichever conversation receives
  that subagent's result", provided only in auto mode (v2.1.271+) [5].
- The subagent panel row clears and `/tasks` lists a finished background subagent for 30 seconds [1]
  (interactive UI detail).
- The exact text/format of the notification message is **NOT DOCUMENTED**.
- Multi-level case: interactive, the orchestrator absorbs the documenters' results and only its own summary
  reaches the user [1]; `-p`, a late nested result goes to the main conversation [1].

## Q6. Nesting limits

Section "Let subagents spawn their own subagents" [1]:

- "By default, a subagent can spawn subagents of its own, up to three layers below the main conversation."
- "At the depth limit, Claude Code withholds the `Agent` tool from every subagent except a fork." (A fork at the
  limit keeps `Agent` listed but the call errors.) "A fork can't spawn further forks."
- Limit variable [8]: `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` "Number of subagent layers allowed below the main
  conversation (default: 3)"; "set `1` to turn nesting off"; "the limit can be adjusted but not removed".
  History: v2.1.172-v2.1.216 five layers; v2.1.217-v2.1.218 default 1; v2.1.219 default 3 [1][8].
- Can a **background** subagent spawn? Yes. The background filter lists the kept built-in tools, then says:
  "Apart from `Agent` and `ExitPlanMode`, which follow the first filter's conditions wherever the subagent
  runs" [1], i.e. `Agent` is withheld only at the depth limit, not because the subagent is in the background.
- main -> orchestrator (layer 1) -> documenter (layer 2) is inside the default limit; the documenter still has
  `Agent` at layer 2 unless its definition omits it ("omit `Agent` from its `tools` list or add it to
  `disallowedTools`" [1]); a layer-3 subagent would not.
- Measured locally on 2.1.287: a subagent granted `Agent` spawned a grandchild under `-p` [13]. Depth beyond two
  was not probed there.
- Interactive-vs-`-p` difference in whether the launcher waits is in Q4.

## Q7. Restricting spawnable subagent types from `tools:` (added at the coordinator's request)

Subagents page [1], section "Restrict which subagents can be spawned" (re-fetched to verify):

- Syntax: "When an agent runs as the main thread with `claude --agent`, it can spawn subagents using the Agent
  tool. To restrict which subagent types it can spawn, use `Agent(agent_type)` syntax in the `tools` field."
- Example in the page: `tools: Agent(worker, researcher), Read, Bash`, "This is an allowlist: only the `worker`
  and `researcher` subagents can be spawned." `Agent` without parentheses allows any; omitting `Agent` means
  the agent "can't spawn any subagents with the Agent tool".
- **Honored in a subagent definition? No.** "The `Agent(agent_type)` allowlist syntax applies only to an agent
  running as the main thread with `claude --agent`. In a subagent definition, listing `Agent` in `tools` lets
  that subagent spawn subagents of its own while the depth limit allows it, but any type list inside the
  parentheses is ignored."
- So `tools: Agent(zikaron-documenter)` in an orchestrator subagent grants unrestricted spawning (to the depth
  limit); the type list is silently dropped. (No warning is documented.)
- Documented alternatives, each partial:
  - `permissions.deny` with `Agent(subagent-name)`: "Use the format `Agent(subagent-name)` where
    `subagent-name` matches the subagent's name field" [1], also via `--disallowedTools "Agent(Explore)"`. This
    is a denylist (the page's own advice: "To block specific agents while allowing all others, use
    `permissions.deny`"). The permissions page [3] also lets deny and ask rules match input parameters, e.g.
    `Agent(model:opus)`, but not allow rules. Whether an `Agent(...)` deny rule binds a *subagent's* spawns is
    NOT DOCUMENTED (the docs state this only for a Bash deny rule: it "applies to the main conversation and to
    subagents" [1]).
  - A `PreToolUse` hook on the `Agent` tool: hooks fire inside subagents with `agent_id` and `agent_type` in
    the input [7]; the hook's ability to inspect and deny a `subagent_type` parameter is **[inference]** from
    that plus the general PreToolUse deny semantics; not tested here.
  - Prompt instruction only (not enforced).

## Q8. Skills with `context: fork` (added at the coordinator's request)

Sources: the skills page [9] (sections "Run skills in a subagent", "Frontmatter reference", argument
substitution, "Pre-approve tools for a skill"), the subagents page [1], and the headless page [2] (raw text).
The "Run skills in a subagent" section was extracted twice, and the skills page tail beyond character 100,000
(troubleshooting and related links) was also read and holds nothing relevant.

**(a) What `context: fork` does.** The skill body becomes the task of a **new** subagent, which starts **fresh**.

- "Claude Code starts a new subagent of the type set in the `agent` field and gives it the skill content as its
  prompt." [9]
- "The subagent doesn't see your conversation history, so the skill's instructions have to stand on their
  own." [9]
- "Despite the name, a skill with `context: fork` doesn't run in a fork of the current conversation" [9]. The
  subagents page [1] states it as the inverse of the `skills` field: "With `context: fork` in a skill, the
  skill content is injected into the agent you specify. In both cases the subagent starts without your
  conversation history."
- A warning on the page: "`context: fork` only makes sense for skills with explicit instructions" [9]; a
  guidelines-only skill returns without meaningful output.

**(b) The `agent:` field.** It takes a built-in or a custom agent name.

- Frontmatter row [9]: "`agent` | Which subagent type to use when `context: fork` is set."
- "Options include built-in agents (`Explore`, `Plan`, `general-purpose`) or any custom subagent from
  `.claude/agents/`. If omitted, uses `general-purpose`." [9]
- What applies from the agent definition: the section's walk-through says "The `agent` field determines the
  execution environment (model, tools, and permissions)"; the comparison table gives the forked skill's system
  prompt as "From agent type" and its task as "SKILL.md content" [9]; and "A forked skill using `agent: Explore`
  starts with that content and the agent's own system prompt, and none of your CLAUDE.md files" [9]. What else
  loads follows the agent's own startup context [9].
- Skill `model` with a fork: "With `context: fork`, the value sets the forked subagent's model instead" [9].
  **Precedence between the skill's `model` and the agent definition's `model` is NOT DOCUMENTED.**
- Whether a custom agent's `permissionMode` applies to the fork is **NOT DOCUMENTED** for skills beyond the
  word "permissions" above; the rules in Q2b (inherit-or-ignore by the parent's mode) are the only stated
  mechanism and are written for Agent-tool subagents.

**(c) `background`, and interactive vs `-p`.**

- Frontmatter row [9]: "`background` | Only applies with `context: fork`. Set to `false` to wait for the forked
  subagent's result in the turn that invoked the skill ... Default: `true`. Requires Claude Code v2.1.218 or
  later." (the ellipsis elides a link.) Values: `false`; default `true`.
- Interactive: "The forked subagent runs in the background: you keep working while it runs, and its result
  arrives in your conversation when it completes." [9] So the invoking session stays free.
- Claude Code waits regardless of `background` in these cases [9]: "In non-interactive mode, with the `-p` flag
  or the Agent SDK"; `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`; "When you invoke a forked skill while an earlier
  invocation of the same skill is still running"; a scheduled task firing with the skill as its prompt; and an
  agent in a dynamic workflow (v2.1.295+). **Note for Zikaron:** a second `/zikaron-document-code` while the
  first is running would block the turn.
- `-p`: the turn waits for the fork's result. That is a foreground-style wait inside the turn, not the
  background-at-exit wait of Q4; **[inference]** the 10-minute idle ceiling therefore concerns background work
  and not this wait, but no page says so. A skill passed as the `-p` prompt works: "User-invoked skills and
  custom commands work. Include `/skill-name` in the prompt string and Claude Code expands it before running."
  [2]
- A backgrounded fork gets the background tool set: "A backgrounded fork also runs with the narrower tool set
  that applies to background subagents", and the page's remedy is `background: false` "to keep the full tool
  set" [9]. Per Q2c that narrower set still includes Bash, Write, Edit and (below the depth limit) Agent.
- Edits by a background fork fall outside the session's rewind checkpoints: "The skill's edits to other files
  stay, so use git to revert them." [9]

**(d) Can the forked skill's subagent spawn subagents; depth accounting.**

- Depth accounting (is the forked skill layer 1) and the presence of the `Agent` tool in the fork: **NOT
  DOCUMENTED** by any sentence.
- Implied by the headless page [2]: its minimum-version list includes "Messages of subagents that a forked
  skill spawns, and of forked skills started inside a subagent or another forked skill: v2.1.275 or later", and
  forwarding covers "subagents at every nesting depth, whether each one was spawned with the Agent tool or
  started as a forked skill". So forked skills take part in the same nesting tree as Agent-tool subagents, and
  can start from inside a subagent. **[inference]** the forked skill's subagent counts as a layer and keeps
  `Agent` below the depth limit like any background subagent (Q6); the skills page calls it "a regular agent
  type" ("the skill's subagent is a regular agent type, so the exemption for subagents that fork the
  conversation doesn't cover it" [9]).
- "A fork can't spawn further forks" [1] sits in the conversation-fork section. Because the skills page says a
  `context: fork` skill "doesn't run in a fork of the current conversation", that rule does not apply to it by
  the docs' own definitions; no sentence applies it explicitly. The depth-limit exemption ("withholds the
  `Agent` tool from every subagent except a fork" [1]) likewise concerns conversation forks, so a forked
  skill's subagent at the limit would lose `Agent`.

**(e) Arguments in, result out.**

- "Arguments are available via the `$ARGUMENTS` placeholder." The page's example: the `$ARGUMENTS` placeholder
  "gets replaced with whatever follows the skill name". Also `$ARGUMENTS[N]` and the shorthand `$N`, and named
  arguments declared with the `arguments` frontmatter field and used as `$name` [9]. Quoting is shell-style;
  `$ARGUMENTS` "always expands to the full argument string as typed" [9].
- No placeholder: "Claude Code appends `ARGUMENTS: <your input>` to the end of the skill content so Claude
  still sees what you typed." [9]
- Forked skills: no sentence is specific to arguments in a fork. The page's own fork example uses
  `Research $ARGUMENTS thoroughly` as the skill body and says "The subagent receives the skill content as its
  prompt", so substitution happens in the prompt the fork receives [9].
- Result: "The subagent summarizes its results and returns them to your main conversation when it finishes" [9];
  interactive, "its result arrives in your conversation when it completes" [9]. In a `-p` stream, the messages of
  a forked skill started with `/<skill-name>` as the prompt arrive together after it finishes, and those of a
  forked skill Claude starts via the Skill tool arrive while it works (table in [2], paraphrased).

**(f) `allowed-tools` on a forked skill.** **NOT DOCUMENTED** whether it applies inside the fork or to
subagents the fork spawns; the fetch found no sentence joining `context: fork` and `allowed-tools`.

- General rule [9]: "The `allowed-tools` field grants permission for the listed tools during the turn that
  invokes the skill ... The grant clears when you send your next message." And "It does not restrict which
  tools are available: every tool remains callable, and your permission settings still govern tools that are
  not listed."
- **[inference]** A background fork usually outlives the invoking turn, so a turn-scoped grant is a poor fit
  for it. The page itself names the durable route: "To pre-approve tools for the whole session rather than a
  single turn, add allow rules to those permission settings instead."
- "Workspace trust doesn't gate this field. Claude Code applies a project skill's `allowed-tools` even in a
  `-p` run in a folder you've never trusted." [9] (unlike project `permissions.allow` rules, Q2a.)
- `disallowed-tools` on a fork: NOT DOCUMENTED.

**(g) Minimum versions stated.**

| Item | Stated minimum |
|---|---|
| `background` field on a skill | v2.1.218 ("Before v2.1.218, forked skills always blocked the turn until they finished" [9]) |
| An agent in a dynamic workflow waits for a forked skill | v2.1.295 (before it, the result went to the main conversation) [9] |
| Messages of a forked skill started via the Skill tool: `tool_use`/`tool_result` | v2.1.86; first `user` message and text/thinking: v2.1.265 [2] |
| Messages of subagents a forked skill spawns, and forked skills started inside a subagent or another forked skill | v2.1.275 [2] |
| Messages of a forked skill started by passing `/<skill-name>` as the prompt | v2.1.287 [2] |
| Forwarding at every nesting depth | v2.1.219 [2] |
| `context`, `agent` fields | **NOT STATED** on the pages read |

The local probe ran on 2.1.287 [13] and the changelog's newest release is 2.1.301 [12], so every stated
minimum above is met on current releases.

## Methodology

- Direct fetches of the official docs (no WebSearch needed; the target pages were known). Pages fetched:
  sub-agents, headless, permissions, permission-modes, tools-reference, interactive-mode, hooks, env-vars,
  skills, cli-reference, errors, changelog. Fetched 2026-10-16.
- **Evidence handling.** WebFetch runs a small model over the page, so I cross-checked. Raw page text read
  directly (saved to disk, high confidence): headless (complete, read twice), permissions (complete),
  permission-modes (through the dontAsk section), tools-reference (Agent, Bash and background-command
  sections), interactive-mode (through "Queue messages"), cli-reference (complete). Via prompted extraction,
  with each quote asked "verbatim" and cross-checked by at least two separate fetches or against the raw pages:
  sub-agents (the foreground/background section, the nesting section, the frontmatter table, "Restrict which
  subagents can be spawned", "Disable specific subagents"), hooks (the `PermissionRequest` opening paragraph
  was re-fetched and matched twice), env-vars, skills (the "Run skills in a subagent" section extracted twice
  with matching text; the frontmatter rows and argument section extracted once each). Lower confidence: the
  claim that the subagents page is silent on a point rests on a summarizer scanning the first 100,000 of
  110,964 characters; the last ~11,000 characters of that page were not read.
- A first-pass summarizer paraphrase (e.g. that `tools:` "does not pre-approve") was not accepted as a quote;
  the note marks it NOT DOCUMENTED.
- Did not use blog posts, GitHub issues or third-party reconstructions. No behavior was tested in this session.

## Evidence quality and debate

- Documentation only, not behavior; the docs here are version-annotated and very recently edited (many
  "before v2.1.2xx" notes), so statements can move monthly. The foreground/background rules in particular
  changed at v2.1.211, v2.1.218, v2.1.232 and v2.1.280-295.
- The docs themselves have one tension worth knowing: the headless page says the run "stays open until that
  work completes", while its own preceding paragraph and the env-var page cap the wait at 10 minutes of idle
  waiting by default. The two are reconciled only by reading the ceiling as the exception.
- Older descriptions of Claude Code (an up-front tool-permission prompt before launching a background subagent,
  then auto-deny for anything not pre-approved) circulate in secondary sources; the current official pages do
  not say that. If our earlier assumption came from there, it is out of date for 2.1.301. This note did not
  fetch an older doc version to confirm what it said, so it is a recollection, not a finding.

## Open questions and leads (probes the docs cannot settle)

1. **Grandchild prompts under interactive use**: does a documenter's Write/Bash prompt surface in the main
   session, name both levels, or fail? Probe: interactive, parent in default mode, no allow rules.
2. **`-p` with a >10 minute orchestrator and default ceiling**: is the run cut and the result dropped? Probe:
   a background subagent that sleeps 11 minutes via Bash vs the same with
   `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`.
3. **`-p`: does an allow rule `Edit(/code-knowledge/**)` approve a *subagent's* Write**, and what is a
   subagent's "current directory" for relative `Edit(code-knowledge/**)` rules?
4. **Auto mode and a narrow Bash prefix allow rule** (is `Bash(python -m zikaron.code_knowledge *)` dropped?).
   Documented only by example.
5. **Does an `Agent(name)` deny rule or a `PreToolUse` hook on `Agent` bind a subagent's own spawns?**
6. **`context: fork` skill with `agent: <orchestrator>` as an alternative to a skill that spawns the
   orchestrator itself** (Q8): background by default interactively, waits in `-p`, so it would give the same
   "main session stays free" result interactively with no spawn step in the skill body. Probes needed: (a) does
   the fork's subagent have `Agent` and count as layer 1, so that its documenters sit at layer 2 (depth
   accounting is not documented); (b) does a skill's `allowed-tools` or the agent definition's `permissionMode`
   reach the background fork and its children; (c) skill `model` vs agent `model` precedence; (d) the
   same-skill-already-running rule turns a second invocation into a blocking one.
7. The notification's exact shape, and whether the final `-p` `result` includes the orchestrator's last message
   when it finishes after the main turn.

## Sources

1. Create custom subagents (Claude Code docs). https://code.claude.com/docs/en/sub-agents. Undated; reflects
   v2.1.301. Sections used: Run subagents in foreground or background; Let subagents spawn their own subagents;
   Supported frontmatter fields; Permission modes; Available tools; Restrict which subagents can be spawned;
   Disable specific subagents; Turn fork mode on or off; Fork the current conversation; the `skills` field
   (inverse of `context: fork`).
2. Run Claude Code programmatically (headless / `-p`). https://code.claude.com/docs/en/headless. Sections:
   Background tasks at exit; Auto-approve tools; Turn off permission prompts in unattended runs; Start faster
   with bare mode; Follow subagent messages (forked-skill version minimums).
3. Configure permissions. https://code.claude.com/docs/en/permissions. Sections: Manage permissions; Permission
   rule syntax; Wildcard patterns; Bash; Read and Edit; Agent (subagents); Project allow rules and workspace
   trust.
4. Choose a permission mode. https://code.claude.com/docs/en/permission-modes. Sections: Available modes;
   Which mode a session starts in; acceptEdits; auto mode (How the classifier evaluates actions; How auto mode
   handles subagents); dontAsk.
5. Tools reference. https://code.claude.com/docs/en/tools-reference. Sections: tool table (Agent,
   SubagentHandback); Agent tool behavior; Background commands; Time limit for background commands.
6. Interactive mode. https://code.claude.com/docs/en/interactive-mode. Sections: keyboard shortcuts (Ctrl+B,
   Ctrl+X Ctrl+K); Background Bash commands.
7. Hooks reference. https://code.claude.com/docs/en/hooks. Sections: PermissionRequest; SubagentStart;
   SubagentStop; common input fields (`agent_id`, `agent_type`).
8. Environment variables. https://code.claude.com/docs/en/env-vars. Rows: CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS,
   CLAUDE_CODE_DISABLE_BACKGROUND_TASKS, CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH, CLAUDE_CODE_FORK_SUBAGENT.
9. Skills. https://code.claude.com/docs/en/skills. Sections: Frontmatter reference (context, agent, background,
   allowed-tools, disallowed-tools, model, arguments); Run skills in a subagent; Pass arguments to skills;
   Pre-approve tools for a skill; Skill content lifecycle.
10. CLI reference. https://code.claude.com/docs/en/cli-reference. Flags: --allowedTools, --permission-mode,
    --permission-prompts, --permission-prompt-tool, --bg, --max-budget-usd, --agents, --forward-subagent-text.
11. Error reference. https://code.claude.com/docs/en/errors. Entries: "is not matched by file permission
    checks"; "Agent would be spawned with zero tools".
12. Changelog. https://code.claude.com/docs/en/changelog. Newest entry 2.1.301, 2026-10-15.
13. `research/nested-subagent-probe.md` (this repository, probed 2026-10-13 on Claude Code 2.1.287). Local
    measurement, not documentation.
