# kiro-cli's V3 engine, measured against Zikaron's kiro install

**Run 2026-10-28, and result 28 and every result from 32 on 2026-10-29,** on kiro-cli **2.35.1** with `--v3` (KAS
0.66.70), headless (`--no-interactive --output-format stream-json`), model `claude-haiku-5.5`,
Linux. kiro-cli 3.0 makes this engine the default by auto-update at the end of October 2026
(`research/kiro-cli-v3-migration.md` §11). That note is the documentation side. This one is what
the binary did. Probe scripts: `spikes/kiro-v3-probe/` (a logging hook, a stub MCP server,
`run.sh`, the four prompts), and for round 2 `spikes/kiro-v3-probe/r2/`.

**Conditions that bind every result here**, except results 29 to 31 and 44 to 46, which come from
interactive sessions the operator drove on 2026-10-29 in the TUI, under kiro's `auto` model for the
primary agent. Headless only: the interactive trust screen, which V3 puts in front of a
workspace's agents, hooks and MCP servers, was not exercised. No
`--trust-all-tools`: each probe agent was granted only `read` and its MCP server, so headless V3's
"ask is deny" left shell and write calls unavailable, except in results 32 to 36, whose agent had
`shell` and `fs_write` rules. **Every `CLAUDE*` variable was stripped** for
the runs that used Zikaron's own hook. With them inherited from the Claude Code session that
launched kiro, the hook detected Claude Code, logged `session_env_mismatch` twice and pushed
nothing. That is `design/harness.md` §"The nesting limit", reconfirmed under V3. One run per
condition, so nothing here is a rate.

## Results

1. **The installer's current output is refused.** The installer writes a V2-shape agent config:
   `allowedTools`, object-format hooks, no `permissions` block. Launching it gave `runError`
   `stage: init`: *`agent "v2shape" needs upgrading for this agent engine, using "default" — run
   /upgrade-agent to convert v2shape.json`*, exit 4. Interactively, the documented behavior is the
   same fallback, which means a session with none of Zikaron's hooks or tools. `kiro-cli agent list`
   had listed that agent beside the others without comment.
2. **`kiro-cli agent upgrade <dir>` converts all three installed configs** (primary, consolidator,
   documenter) at no credit cost. It adds `permissions.rules` and a `kiroUpgrade` block
   (`revision: 2`, `fingerprint`, `source`). It rewrites each object-format hook as
   `{"name": "agentSpawn-0", "trigger": "agentSpawn", "action": {"type": "command", "command": …},
   "timeout": 10, "maxOutputSize": 65536}`. So an array-format entry under V3 does carry a size field,
   `maxOutputSize`. V3 does not honor it (result 21). The rules it derived were:
   - for the consolidator, `{"capability": "mcp", "match": ["zikaron/*"], "effect": "allow"}` and
     `{"capability": "fs_read", "match": ["./**"], "effect": "allow"}`;
   - for the documenter, `{"capability": "fs_read", "effect": "allow"}`, `{"capability": "fs_write",
     "effect": "allow"}`, the same `mcp` rule, and `{"capability": "skill", "effect": "allow"}`;
   - for the primary, `{"capability": "fs_read", "effect": "allow"}`, the same `mcp` rule, and
     `{"capability": "skill", "effect": "allow"}`, with no `match`.

   Which V2 field the `skill` rule was derived from is not visible. The primary's V2 profile
   carried `resources` naming the two `skill://` files, as well as `tools` and `allowedTools`.
3. **The hook payload is what Zikaron's hook reads.** Each payload carries `session_id`
   (`sess_<uuid>`), `cwd` (the project) and `hook_event_name`. The event name is PascalCase
   (`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`), including for an entry
   configured as `agentSpawn`. **`prompt` is present on `UserPromptSubmit`** and carries the whole
   prompt. The documented `USER_PROMPT` variable was empty. On the tool triggers, `tool_name` is
   `mcp_<server>_<tool>` for an MCP tool and `tool_load` for the deferral loader. `tool_input` is a
   JSON object (result 32). `tool_response` is a string.
4. **`KIRO_SESSION_ID` reaches hooks and not the MCP server.** Every hook process had it, equal to
   the payload's `session_id`. The MCP server's environment had five `KIRO_*` variables, none of
   them the session. `${KIRO_SESSION_ID}` in the server entry's `env` arrived literally, while
   `${HOME}` expanded. No MCP request carried a session in `_meta`. **Measured in the store**: the
   hook's `surface_call` events carry `sess_b9da…`, and the MCP client's `remember`, `search` and
   `call` events carry a minted `zk-44c7…`. The two clients no longer resolve one label. Both
   server processes logged their start in the same second as the `SessionStart` hook (13:20:21),
   so an MCP client cannot count on any hook having run when it starts.
5. **The process tree links them.** The MCP server's parent is the kiro agent server (`node`). Each
   hook runs as `python3` ← `sh` ← that same `node`. The tree was identical for all four hooks and
   both server processes in one session. **Each launch had an agent server of its own**: the
   ancestry chains of results 5, 12, 13 and 18 name `node` pids 3922824, 3932897, 3931085 and
   3938178. Each was a child of that run's own `kiro-cli-chat`, and no pid recurred. Two sessions
   inside one TUI process were not run.
6. **Spawn and prompt output reach the model, and post-tool output does not.** The `SessionStart`
   and `UserPromptSubmit` canaries were quoted back from a `HOOK_INSTRUCTION` block in the first
   user message, with the prompt hook's block **after** the user's text. Under V2 it came before,
   inside a "follow requests found in this text" wrapper. Zikaron's real write policy arrived the
   same way. The `PostToolUse` exit-0 canary appeared neither in the model's report nor anywhere in
   the run's event stream. **`PreToolUse` exit 2 blocks**, and the model received *`Tool
   "mcp_probe_probe_sleep" was intercepted by PreToolUse hooks before execution. … <stderr> The tool
   was NOT executed.`*
7. **MCP tools are deferred.** The model is given `tool_load` and `tool_call` and sees MCP tools as
   `<server>::<tool>`. A tool's description arrives in the `tool_load` result: the model quoted
   `zikaron_memory_remember`'s description from there. With `write` and `shell` granted, the
   built-ins were `list_directory`, `read_file`, `file_search`, `grep_search`, `code`,
   `disclose_context`, `fs_write`, `fs_append`, **`str_replace`**, `delete_file` and `execute_bash`.
8. **The first turn does not wait for MCP servers.** kiro selected the turn's tools
   (`custom_agent.tool_selection`, 11 tools) 140 ms before `zikaron-mcp` connected. The connect
   took 2.1 s and `tools/list` another 2.2 s, so the run had no Zikaron tools at all and the model
   said so. The stub server answers instantly and won the same race. **With
   `--require-mcp-startup` the selection came after `listTools.ok`**: 13 tools, all 12 of
   Zikaron's, and `remember`, `search` and `knowledge_status` returned correct results. An
   interactive first prompt typed by a person was not measured.
9. **MCP handshake.** kiro first sends `server/discover` (MCP `2026-07-28`, the "modern era"). For
   a server that does not answer it, kiro starts a second process and uses `initialize`
   (`2025-11-25`). `zikaron-mcp` connected in the modern era. A **150 s tool call completed** with
   no `requestTimeout` set, so the documented 120 s default was not enforced on this build. **So
   did a 330 s call**, run later with the same profile, which returned `slept 330.0s`. The
   consolidator's 300 s planning wait fits under V3.
10. **Models.** `kiro-cli chat --list-models -f json` lists `auto`, `claude-opus-5.5`,
    `claude-sonnet-5.5`, `claude-haiku-5.5`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`,
    `kimi-k3`, `claude-opus-5`, `claude-sonnet-5`, `claude-opus-4.8`, `claude-opus-4.7`,
    `claude-opus-4.6`, `claude-sonnet-4.6`, `claude-opus-4.5`, `claude-sonnet-4.5`,
    `claude-haiku-4.5`, `deepseek-3.2`, `minimax-m2.5`, `minimax-m2.1`, `glm-5` and
    `qwen3-coder-next`, with the same list under `--v3`. So the shipped pin `claude-sonnet-5`
    passes the installer's check. The 2026-10-20 list had no Haiku 5.5.
11. **Consolidation runs end to end through the installed skill.** The primary agent was granted
    `subagent` in `tools` and a `{"capability": "subagent", "effect": "allow"}` rule. It spawned the
    consolidator as `subagent_zikaron-consolidator`, with `prompt` and `explanation` parameters,
    and reported that *"the skill's `role:` line has no matching parameter in this tool"*. kiro
    logged `mcp.subagentScope.acquired` (`serverCount: 1`) and started a second server instance.
    Every consolidator event in the store is `client_kind = consolidator`, so the consolidator used
    its own `--mode consolidator` server and D32's withholding holds. Its label was minted too
    (`zk-17d8…`). The served group was promoted in place, with no error. kiro logged
    `invoke_subagent.starting` with `modelId: claude-sonnet-5`, `effortLevel: high` and
    `effortOverride: false`.
12. **Hooks never fire for a subagent session.** A parent agent spawned a child agent. The child
    got no `SessionStart` and no `UserPromptSubmit`. Its own tool call fired `PreToolUse` with the
    **parent's** `session_id` in both the payload and `KIRO_SESSION_ID`. The spawn appeared as
    `tool_name: subagent_child`, and its return as `subagent_response`. The payload and the
    environment agreed in every hook of every run.
13. **`exec` makes the agent server the hook's parent.** With each hook command prefixed by
    `exec `, every hook process's parent was the `node` agent server, the same pid that parents
    the MCP server.
14. **Profile shapes, as `kiro-cli agent upgrade --dry-run` classifies them.** A profile with
    `permissions` and neither `allowedTools` nor `kiroUpgrade` is `v3-only`, and it loaded and ran
    with its hooks and MCP server. A profile with no trust field at all is `already universal`, as
    is an upgraded one whose hook commands were edited by hand. One that carries `allowedTools`, even
    `[]`, "would upgrade". **Any edit to an upgraded profile's `tools`, `permissions` or
    `allowedTools` makes it `out of sync (not rebuilt)`.** The docs say the TUI then rebuilds the
    V3 fields from the V2 ones when the agent is selected. That rebuild was not observed. **An
    out-of-sync profile loads and runs headless**: the scratch project's primary profile was
    upgraded, then edited in `tools` and `permissions`, and `--dry-run` classified it out of
    sync. Both consolidation runs of results 11 and 18 ran under it.
15. **Workspace files work with no custom agent.** A standalone `.kiro/hooks/probe.json`
    (`"version": "v1"`, PascalCase triggers) fired `SessionStart`, `UserPromptSubmit` and
    `PreToolUse` for the default agent, and both canaries reached the model. A workspace
    `.kiro/settings/mcp.json` server started and its tool was offered. Each call to it, though, *"The
    permission request failed before it was answered"*. `autoApprove` did not pre-approve it
    headless.
16. **Where `zikaron-mcp`'s start-up goes**, measured outside kiro on a warm store:
    `initialize` answers in 2.0 s, of which importing the server is 1.85 s (fastmcp 0.97 s,
    `mcp.server` 0.70 s). The first `tools/list` takes 0.26 s. In kiro the list took 2.2–2.3 s,
    while the session's own hook was starting the service.
17. **Minimal hand-written profiles work where ask means deny.** Two profiles had no
    `allowedTools`, no `kiroUpgrade` and only the rules listed here.
    - The consolidator's one rule was the `mcp` rule. `agent upgrade --dry-run` classified it
      `v3-only`, and its `next_group` call succeeded through the skill.
    - The documenter's rules were `fs_read`, `fs_write` and the `mcp` rule. It was classified
      `already universal`, not `v3-only`. Run headless as `--agent zikaron-documenter`, it used
      `read_file`, `fs_write` and **`str_replace`**, with no prompt and no error. The edited file
      held the replacement.

    The two profiles, as run:
    - The consolidator had `"tools": ["@zikaron"]` and `"permissions": {"rules": [{"capability":
      "mcp", "match": ["zikaron/*"], "effect": "allow"}]}`.
    - The documenter had `"tools": ["@zikaron", "glob", "grep", "read", "write"]` and
      `"permissions": {"rules": [{"capability": "fs_read", "effect": "allow"}, {"capability":
      "fs_write", "effect": "allow"}, {"capability": "mcp", "match": ["zikaron/*"], "effect":
      "allow"}]}`.

    So a hand-written profile with the `grep` and `glob` selectors loads under V3.
18. **A subagent's MCP server has the same parent as the primary's.** `zikaron-mcp` ran under a
    logging wrapper. Both `--mode primary` processes and both `--mode consolidator` processes were
    children of one `node` agent server. Each mode started two processes, as in result 9.
19. **The upgrader leaves object-format hooks in a profile that already has `permissions`.** Such a
    profile is `out of sync (not rebuilt)`, and its `hooks` came back unchanged. A profile with no
    trust field and object-format hooks "would upgrade", and its hooks were converted. `timeout_ms:
    10000` became `timeout: 10`, and no `maxOutputSize` was written for an entry that had no
    `max_output_size`.
20. **`kiro-cli --version`** prints `kiro-cli 2.35.1`.
21. **A hook's output is cut at 3,000 characters, whatever the profile says.** One hook printed
    exactly *N* characters, opening with one canary and ending with another.
    - On `UserPromptSubmit`, 3,000 arrived whole. 3,001 and 3,002 arrived ending in
      `...[truncated]`, which the model saw and reported. 9,000 lost the closing canary.
    - `SessionStart` has the same cut: 2,950 arrived whole, and 3,050 lost the closing canary.
    - Neither key changed it. `maxOutputSize: 65536` did not, and nor did snake_case
      `max_output_size: 65536` in an array entry. With neither key the cut was the same.
    - **It counts characters, not bytes.** 2,080 characters of `é`, 4,060 bytes, arrived whole.
    - The truncation is marked to the model and to no one else. The event stream carries only
      the hook's `status: completed`.
    - Zikaron's own `SessionStart` output, `WRITE_POLICY_PROMPT`, is 2,929 characters, all ASCII.
      It arrives whole, 71 characters under the cut.
    - The gists a push would carry, measured the same day: the four real stores held 652, of
      which the longest is 246 characters and the five longest sum to 1,148. That is `select
      gist from memory` over each store's `memory.db`, opened `mode=ro`.
22. **`kiro-cli agent create` writes a universal profile.** That covers `kiro-cli agent create made
    -d <dir>` on 2.35.1, with `EDITOR=true`. The profile has `"tools": ["*"]`, `"allowedTools":
    []`, `"toolsSettings": {}`, `"includeMcpJson": true`, a `permissions` block with one `fs_read`
    rule over `./**`, and a `kiroUpgrade` block. `agent upgrade --dry-run` leaves it unchanged.
23. **`kiro-cli agent validate --path` proves nothing about V3.** It printed nothing and exited 0
    for the V2-shape profile V3 refuses (result 1), as for both minimal profiles of result 17.
24. **A skill does not load without a `skill` rule.** The consolidation run of result 11 was repeated
    with the primary profile's `skill` rule removed, leaving `fs_read`, `mcp` and `subagent`. The
    model called `disclose_context` with `{"name": "zikaron-consolidate"}` twice. kiro logged
    `acp.policy-eval.complete {"toolId":"disclose_context","effect":"ask"}`, and headless both calls
    failed with *"The permission request failed before it was answered"*, so the consolidator never
    started. The same run's prompt hook pushed the store's one gist, which the model quoted: the
    first push of a real gist measured under V3.
25. **No `KIRO_*` variable names a directory.** Across every probe record that logged the
    environment, 85 from hooks and 185 from MCP servers, six `KIRO_*` names appear:
    `KIRO_CONTENT_COLLECTION_ENABLED`, `KIRO_CUSTOM_USER_AGENT`, `KIRO_REMOTE_SESSIONS_ENDPOINT`,
    `KIRO_SESSION_ID`, `KIRO_TELEMETRY_IS_ENTERPRISE` and `KIRO_TELEMETRY_IS_INTERNAL_AMAZON`. So
    D17's store scope still falls back to the working directory under V3, and that directory is the
    right one: every one of the 185 MCP server records reports as its `cwd` the directory kiro was
    launched from.
26. **The order of `tools` decides a classification.** `kiro-cli agent upgrade --dry-run` was run
    over profiles that differ only in `tools`, each with the documenter's three rules and no V2
    field. `["@zikaron", "glob", "grep", "read", "write"]`, sorted as the upgrader writes `tools`,
    is `already universal`, as in result 17. The same five in the installer's first order,
    `["read", "grep", "glob", "write", "@zikaron"]`, are `out of sync (not rebuilt)`, a class the
    TUI answers by rebuilding the profile. Without `grep` and `glob` the order did not matter:
    `["write", "read"]`, `["read", "@zikaron"]` and their sorted forms, and `["*", "@zikaron"]`,
    were all `v3-only`. So `grep` or `glob` in `tools` appears to make the upgrader derive a V3
    projection and compare it, sorted, with the file.
27. **An install `kiro-cli agent upgrade` converted is installed over once per trigger.** The
    pre-M41-1 installer wrote its object-format hooks into a profile carrying `allowedTools`, and
    the upgrader converted them to `agentSpawn-0` and `userPromptSubmit-0` on the camelCase
    triggers. M41-1's installer, run from the same venv, replaced them with one
    `exec '<hook>'` entry each under `SessionStart` and `UserPromptSubmit`, added no rule the
    upgrader had already derived, and left the profile `already universal`. Run from a different
    venv, it refused the profile as another install's, naming the `mcpServers` command, as its
    ownership rule says.
28. **A subagent gets only what its own rules and its parent's both allow**, as the documentation's
    "deny-wins intersection" says (`research/kiro-cli-v3-migration.md` §4). Run 2026-10-29: a
    primary with `fs_read` and `subagent` rules spawned the installed `zikaron-documenter`, whose
    own rules allow `fs_write`, to write one document. With no `fs_write` rule in the primary,
    kiro logged `acp.policy-eval.complete {"toolId":"fs_write","effect":"ask"}` and headless no
    document was written. With `{"capability": "fs_write", "match": ["./code-knowledge/**"],
    "effect": "allow"}` in the primary, the same write logged `"effect":"allow"` with
    `"capability":"fs_write"` and the document was written; the path the documenter was given was
    absolute. Result 30 saw the first case interactively: three such asks, answered by the operator.
    The same holds for Zikaron's tools: a primary with `fs_read`, `subagent` and `skill` rules and
    no `mcp` rule, as under `--no-trust-tools`, loaded the consolidation skill and spawned the
    consolidator, whose own `mcp` rule allows `zikaron/*`. kiro logged `"effect":"ask"` on each of
    its three `zikaron_memory_next_group` calls, headless refused them, and the journal entry a
    first run had written stayed in the journal.
29. **`--require-mcp-startup` does not make an interactive session wait.**
    `kiro-cli chat --v3 --require-mcp-startup --agent <profile> "<prompt>"`, launched from a
    terminal, opened the TUI with that prompt as its first turn. kiro logged `model.invoke.start`
    at 06:56:44.397, the Zikaron server's `mcp.connect.ok` at 45.337 and `mcp.listTools.ok` at
    46.647, and the turn answered that it had no Zikaron tools. Headless, the flag waits (result 8).
30. **Done-when 5, interactive.** On a project made by `kiro-cli agent create live -d .kiro/agents`,
    which refuses a directory that does not exist, and an install over it:
    - The trust screen appeared on the first launch, and once answered the write policy arrived.
    - The installed-over profile is `out of sync (not rebuilt)`: the install edits `tools`,
      `permissions` and `allowedTools`, and `agent create` writes the `kiroUpgrade` block that
      result 14's rule keys on. Launching it with `--agent` and selecting it again through
      `/agent`, whose picker shows no sync state, left it byte-identical on disk, and Zikaron's
      calls ran unasked afterward.
    - `remember`, written unprompted from a remark in passing; a push that led the next session's
      agent to `fetch` the record and act on it; `amend` under the fetch's version; consolidation
      through the skill; and a two-file code-knowledge run to `up_to_date`, with a knowledge
      search afterward. Each session's hook, MCP and consolidator events carried one label, its
      own. Two sessions open at once got labels of their own too, from hook events alone, since
      neither called a Zikaron tool.
    - The agent's own shell printed `KIRO_SESSION_ID` as the label the hook had used.
    - A dead session's relay file was gone after the next session started.
    - What asked: each subagent spawn and each shell command, which the profile had no rule for,
      and the documenter's writes (result 28). Nothing else did.
31. **Where kiro keeps a session's record.** The trust screen's answer is
    `~/.kiro/workspace-roots/<hash>/permissions.yaml`, holding `rules: []` and
    `workspaceTrusted: true`; a session's transcript is
    `~/.kiro/sessions/<hash>/<session id>/messages.jsonl`; and each launch's
    `~/.kiro/logs/<timestamp>/kiro.log` holds an `acp.policy-eval.complete` line per tool call
    naming its effect and, when a rule decided it, its capability. A subagent spawn logs
    `invoke_subagent.starting` with its `subagentId` and `modelId`. The primary agent's model under
    `auto` is logged only as `auto`, `simple-task` or `qdev::auto`.

Every result from 32 on is round 2, run 2026-10-29 for M41-2 from `spikes/kiro-v3-probe/r2/`.
Results 44 to 46 ran Zikaron's own install over a `kiro-cli agent create` profile
(`spikes/kiro-v3-probe/r2/interactive.md`); every other probe agent is a hand-written V3-only
profile, with its hooks inline. Each result is one run, and what "reached the model"
means is the model's own report, checked against the session's `messages.jsonl` for each canary.

32. **The shell tool's `PreToolUse` payload.** Keys: `cwd`, `hook_event_name`, `session_id`,
    `tool_name` and `tool_input`, plus `tool_response` on `PostToolUse`. `tool_name` is
    `execute_bash`. **`tool_input` is a JSON object** in all 56 of the round's hook records that
    carry one, and none is a string. For the shell tool it is `{"command", "description", "cwd",
    "run_in_background", "timeout"}`, and `cwd` was `null` in every call. Those of the file tools are: `fs_write`
    `{"path", "text"}`; `str_replace` `{"path", "oldStr", "newStr", "replace_all"}`; and
    `grep_search` `{"query", "caseSensitive", "excludePattern", "explanation", "includePattern"}`.
    Every file path was absolute. An MCP call without arguments had `{}`, and round 1's own hook read
    `tool_input.seconds` from an MCP call as an object, which is how its block in result 6 fired.
    `tool_response` is a string, such as `"Output:\nhello-plain\n\n\nExit Code: 0"`. **The matcher
    `shell` fired for `execute_bash` alone**, while a matcherless entry fired for every tool,
    `tool_load` and the subagent tools included.
33. **`PreToolUse` exit 2 blocks the shell tool, and its stderr arrives framed.** The model received
    *`Tool "execute_bash" was intercepted by PreToolUse hooks before execution. Each
    <HOOK_INSTRUCTION> block below is a separate request that you must address: <stderr> The tool
    was NOT executed. Address each hook instruction, then decide whether to proceed with the
    original tool call, modify your approach, or take a different action. If the instructions show
    an ExitCode that is not 0, it means that the hook failed and you should not process with the
    origin tool call.`* It did not retry. **A 5,000-character stderr arrived with both ends**: the
    model reported the opening and the closing canary and the run of filler between them, with no
    truncation marker. So result 21's 3,000-character cut was not seen here. Neither the session
    record nor that launch's `kiro.log` keeps a tool result or a hook's stderr: the deny's text is
    not in `kiro.log` at all, and is in the session record only where the model quoted it. So the
    delivered length was not counted.
34. **`PreToolUse` exit 0 stdout and exit 1 stderr reach nobody, and exit 1 lets the call run.**
    `echo ACKME`, answered with a stdout canary and exit 0, ran. So did `echo CRASHME`, answered
    with a stderr canary and exit 1. Neither canary reached the model. A crashed `PreToolUse` hook
    fails open.
35. **No `PostToolUse` output reaches the model, on any exit code.** A post hook answered each kind
    of call with a stderr canary and a non-zero exit: `execute_bash` with exit 1 and with exit 2,
    then `fs_write`, `str_replace`, `grep_search` and an MCP tool with exit 1. Every hook fired and
    every tool's result was unchanged. None of the five canaries reached the model, or appears in
    the session's `messages.jsonl`. With result 6's exit-0 stdout, that covers every documented
    post-tool route.
36. **`PostFileCreate` and `PostFileSave` fire, and reach nobody either.** Their payload is
    `{"cwd", "file_path", "hook_event_name", "session_id"}`. `fs_write` creating a file fired both,
    and `str_replace` fired `PostFileSave`. The canaries were stdout with exit 0 on
    `PostFileCreate` and stderr with exit 1 on `PostFileSave`, and neither reached the model.
37. **A subagent spawns a subagent.** A primary spawned `nc`, whose profile grants `subagent`, and
    `nc` listed `subagent_<name>` for every agent in the workspace among its tools. It then spawned
    `ng`, headless with no question asked, and both returned their own `probe_whoami`. Each
    subagent had its own pair of MCP server processes, and all were children of the one agent
    server. `research/nested-subagent-probe.md`, on 2.28.0 under the V2 engine, saw the `subagent`
    tool stripped from a subagent. That does not hold under V3.
38. **A subagent's tool calls run the root session's tool hooks, and none of its own.** Each of
    the three profiles carried labeled `SessionStart`, `PreToolUse` and `PostToolUse` hooks. Every
    tool call `nc` and `ng` made fired the primary's `PreToolUse` and `PostToolUse`, with the
    primary's `session_id` in the payload and in `KIRO_SESSION_ID`. That covers `tool_load`, the
    MCP call, `subagent_ng` and `subagent_response`. No hook from `nc`'s or `ng`'s profile ever
    fired, `SessionStart` included. Result 12 is the same observation, now with the owner of each
    hook told apart.
39. **A profile's `effortLevel` sets a subagent's effort.** KAS 0.66.70's agent loader reads an
    `effortLevel` field from JSON and Markdown profiles, and the subagent launcher passes it on.
    The field is undocumented (`research/kiro-cli-v3-migration.md` §1). The launcher's
    `effortOverride` is true exactly when the profile set one. Measured: a subagent whose profile
    has `"effortLevel": "low"` logged `invoke_subagent.starting` with `"effortLevel":"low",
    "effortOverride":true`. One without logged the session's `"medium"` and `false`. `agent upgrade
    --dry-run` classified the profile `v3-only`.
40. **An MCP result of 30,000 characters or more is replaced by a preview and a file.** At 30,000,
    60,000, 120,000 and 400,000 characters the model received *`The output from
    "mcp_probe_probe_big" (30,000 chars) exceeded the 30,000-char limit; here is a preview of the
    tool's result:`*. Then came the first and last 500 characters, *`--- 29,000 chars omitted ---`*,
    and a path under `~/.kiro/sessions/<hash>/<session id>/tool-outputs/` holding the full output,
    with advice to inspect it with shell commands. The bundle's constants are `CHAR_THRESHOLD:
    3e4`, `HEAD_PREVIEW_SIZE: 500` and `TAIL_PREVIEW_SIZE: 500`.
41. **`read_file` pages a long file by line offset.** An agent granted only `read` read a
    2,002-line, 202,020-character file in seven calls, `offset` 297, 594 and onward. Each call
    stopped at *`Note: This read hit the 30000-character limit. To continue, use offset 297.`*, and
    the seventh ended at the last line. The first call's last line was cut partway, and the next
    call returned it whole.
42. **`--resume` keeps the session id, and fires no `SessionStart`.** A headless run was resumed
    with `--resume` and recalled the word it had been given. The payload, `KIRO_SESSION_ID` and
    `runFinished` carried the first run's `sess_…` id. The resumed run had a new agent server and
    new MCP servers. Its `UserPromptSubmit` fired, and no `SessionStart` did.
43. **A headless run loads a workspace that has no trust record.** `~/.kiro/workspace-roots/` held one
    record, result 31's, while every round-2 run loaded `p3`'s agents, hooks and MCP servers. So the
    trust screen gates the TUI alone.
44. **Declining the trust screen exits kiro.** The operator declined it on a project no kiro had
    launched in, and kiro quit with no session, so there was no prompt to type. The decline wrote no
    record under `~/.kiro/workspace-roots/` and no launch directory under `~/.kiro/logs/`. The
    project's store held no event, so no hook ran. Under Claude Code, by contrast, declining trust
    decides what tools a session may use.
45. **Compaction keeps the session, its label and the write policy, and drops loaded tools.** On
    the relaunch, now trusted, a search came before `/compact` and another after it. kiro logged
    `compaction.start` and `compaction.done` under the same `sess_…` id. It wrote a tombstone
    truncating 22 messages, and a 1,638-character summary that does not mention the write policy.
    Every hook and MCP event in the store carried that one id. The session-start hook's output
    (5,063 characters with kiro's own preamble) is stored as a record of its own,
    `session_start_<session id>_<agent>`. **After compaction the search tool had to be loaded
    again**: the first call was refused with *`Tool "zikaron::zikaron_memory_search" has not been
    loaded yet. Load it first`*, and the model called `tool_load` again.
46. **An interactive resume of the compacted session keeps its label, and the write policy is still
    in context.** `kiro-cli chat --v3 --agent live --resume` brought up that session. Asked for the
    first sentence of any "Project memory (Zikaron)" instructions in its context, the model quoted
    the policy's first sentence verbatim. Only the prompt hook fired on that resume, and no
    `SessionStart` did. Neither the summary nor any later message carries the policy, so it came
    from the stored session-start record. The store's 14 events, hook and MCP alike, all carry the
    one label.
47. **An `fs_read` rule matching `./**` covers a dot-directory.** An agent whose one rule was
    `{"capability": "fs_read", "match": ["./**"], "effect": "allow"}` read `.hidden/spill.txt`, with
    `acp.policy-eval.complete {"toolId":"read_file","effect":"allow","capability":"fs_read"}`.
48. **A hook matcher can name the tool id.** One profile carried five `PreToolUse` entries with
    the matchers `execute_bash`, `^execute_bash$`, `execute_bash|Monitor`, `shell` and none. A
    shell call fired all five, and a `read_file` call fired only the matcherless one. So a
    `|`-joined list of tool ids selects as the tag does, and a name in it that no tool has, such as
    `Monitor`, selects nothing.
49. **The 3,000-character cut is per hook, not per trigger.** A profile with two `SessionStart`
    entries, printing 2,902 and 2,904 characters between each one's own opening and closing canary,
    delivered all four canaries, 5,806 characters in all, with no truncation marker. The model said so, and
    the session's `messages.jsonl` holds each canary.
50. **kiro runs a shell command as `/bin/bash -c <command>`**, so the shell's own command line
    carries the command's text, which is the self-match rule's premise (`design/guards.md` §9). The
    command `pgrep -af 'selfmatch-zz-probe'; echo exit=$?` listed its own shell, `/bin/bash -c pgrep
    -af 'selfmatch-zz-probe'; echo exit=$?`. It also listed the headless `kiro-cli` processes,
    whose arguments held the prompt quoting the pattern, which an interactive session's do not.
    Linux only.
51. **The 30,000-character cap counts the text block, not the structured copy.** The stub
    returned one object as a text block of its compact JSON and again as `structuredContent`, the
    shape `zikaron-mcp` sends (`research/claude-code-mcp-result-truncation.md`). At 29,500 and
    15,500 characters it arrived intact, both sentinels present and no notice. At 31,000 it was
    replaced by result 40's preview.
52. **A subagent's own allow rule does not confine it.** A parent allowing `fs_read` everywhere
    spawned a child whose one rule allowed `fs_read` over `./.hidden/**` alone. The child read
    `.hidden/spill.txt` and also `notes.txt`, outside that match, and both reads logged `"effect":
    "allow"`.
53. **A deny rule with `exclude` does confine it.** The same child, given the allow rule above and
    `{"capability": "fs_read", "exclude": ["./.hidden/**"], "effect": "deny"}`, read
    `.hidden/spill.txt` and was refused `notes.txt` with *`Blocked by a permission rule (deny
    fs_read matching "*"); the user did not reject it. Source: subagent-profile.`* `agent upgrade
    --dry-run` classified the profile `v3-only`.
54. **The session's rules decide two levels down, and a silent middle agent passes them
    through.** A session spawned a middle agent with no `fs_write` rule, which spawned a leaf
    allowing `fs_write`. With the session allowing `fs_write` over `./out/**`, the leaf's write
    logged `"effect":"allow"` and the file was written. With no `fs_write` rule in the session, both
    of the leaf's attempts logged `"effect":"ask"`, and headless nothing was written. With results
    28, 52 and 53: a subagent's own allow rules grant it nothing beyond the session's. What it may
    do is what the session's rules allow, less what any rule in the chain denies.
55. **Result 53's deny refuses the search and listing tools too.** The same child was asked to
    `grep_search` for a word, `list_directory` the project and `file_search` for a name. Each
    logged `"effect":"deny"` with `"capability":"fs_read"`, and each was refused with result 53's
    message: none of them names a path the `exclude` could match.
56. **A subagent with no rules of its own does what the session allows.** A child whose
    `permissions.rules` was empty read `notes.txt` under a session allowing `fs_read`. The allow is
    logged under the child's own `conversationId`, apart from the session's and from its sibling's.
57. **The session's `PreToolUse` exit 2 blocks a subagent's call, and the subagent gets the
    stderr.** A session whose one hook, matcher `execute_bash`, exits 2 on `BLOCKME-SHORT` spawned
    a child with `shell` and no rules, which ran `echo BLOCKME-SHORT > blocked.txt`. The hook fired
    under the session's id. No file was written, and the child quoted result 33's framing with the
    hook's stderr as its own tool result. `kiro.log` has no `acp.policy-eval.complete` line for the
    blocked call, only the spawn's, so kiro runs a `PreToolUse` hook before it evaluates a call's
    permissions, or does not evaluate a call the hook blocked.

Results 58 to 61 come from M41-2's own live tests (`tests/test_guard_kiro_live.py`,
`tests/test_code_knowledge_kiro_live.py`, `tests/test_install_kiro_live.py`), run on 2026-10-29
against the install that milestone ships, under the conditions above.

58. **The shipped install works end to end.** The guards denied the `sed -i`, let the overridden
    one run, spared the scratch target and denied the self-matching `pgrep -f`. Both start texts
    arrived whole in the session record, and the model quoted each deny's opening. In code
    knowledge, each run spawned one `zikaron-code-orchestrator` on `claude-opus-5.5` at `high`,
    which spawned three `zikaron-documenter`s on `claude-haiku-5.5` at `medium`, all with
    `effortOverride: true`. The planner reported the module `up_to_date` after each run, and the
    changed source's document was a new file. A consolidation group over the spill threshold was
    written to the store's `spill/`, the consolidator's `read_file` there was allowed by its
    `fs_read` rule, and it decided the group. That leg first failed on its seed data, a defect in
    the memory store's chunker unrelated to kiro (`research/hard-split-word-cut.md`), and passed
    once it was fixed.
59. **`kiro.log` names two tools differently from the model and the hook.** Its
    `acp.policy-eval.complete` lines log a shell call as `toolId: run_command`, capability `shell`,
    and a spawn as `invoke_sub_agent`. The hook payload still names the shell tool `execute_bash`
    (result 32): the guard's `execute_bash` matcher fired, since the denied `sed` did not run. So a
    test that reads `kiro.log` must look for `run_command`, and a matcher must name
    `execute_bash`. The file tools keep one name in both places: `read_file`, `fs_write`,
    `str_replace`, `grep_search`, `file_search` and `list_directory`.
60. **A documenter corrected its draft in place.** On the second run, one of the three documenters
    called `str_replace` after its `fs_write`. The other two wrote once.
61. **The orchestrator wrote a memory.** On the second run it called `zikaron_memory_remember`
    once, as its last call. What it wrote was not kept: the test's store was removed with its
    temporary directory, and no session record under `~/.kiro/sessions/` names the orchestrator's
    conversation.

Result 62 is M41-2's done-when 7, an interactive TUI session the operator drove on 2026-10-30 (UTC)
on kiro-cli 2.35.1 with `--v3`, in a project of three sources under `pkg/` installed from the M41-2
worktree with `--components both`. The profile carried `subagent` and `shell` allow rules, `fs_read`
over `./**` and `fs_write` over `./code-knowledge/**`. The session ran on kiro's `auto` model, which
routes each request by kiro's own heuristics. `kiro.log` records only `"modelId":"auto"`, never the
model a request was routed to; from its replies, the operator judged it a light model. So a light
session model followed the launch skill to the orchestrator. Evidence: that launch's `kiro.log` and
the session's `messages.jsonl`.

62. **The shipped install passes the operator's run.**
    - **Both start texts reached the model**: asked for the first sentence of each note it was
      given, it quoted the write policy's and the guard start text's, each word for word, its
      wrapping and backticks aside.
    - **The guard denied a `sed -i` on `notes.txt`**, and the model added the override itself,
      citing the user's request as its reason. The overridden command ran, and the model then
      re-read the file "as the hook asks": the deny's own re-read clause, since kiro acknowledges
      no override.
    - **Asked to document `pkg`, the session loaded the skill and spawned
      `zikaron-code-orchestrator`**, the spawn prompt's second line reading `pkg`. The orchestrator
      ran on `claude-opus-5.5` at `high` and spawned four `zikaron-documenter`s on
      `claude-haiku-5.5` at `medium`, all with `effortOverride: true`: three in one batch, within
      3.1 s, then one for the README. The planner then reported `up_to_date`, each document carried
      its K14 link to its source's blob, and `code-knowledge/pkg` was registered and built, 4 files
      indexed.
    - **kiro asked nothing**: every one of the 43 `acp.policy-eval.complete` lines was an `allow`.
    - **The batch's cost**: 16.4 s from the orchestrator's spawn to its first documenter's first
      tool call. That is 3.6 s to the orchestrator's first call, the planner run, then 1.8 s from
      the documenter's spawn to its first call. The whole run took 81 s from that spawn to the last
      subagent's release. `kiro.log` records one `mcp.subagentScope.acquired` per spawned agent,
      each with `serverCount: 1`, five in all. It does not record processes. Results 9, 18 and 37
      saw two `zikaron-mcp` processes per agent instance under a logging wrapper, so this run
      started about ten. That count is inferred from those results, not measured here.
    - **Two documenters edited in place**, calling `str_replace` after `fs_write`, and one called
      kiro's `code` tool (result 7's built-ins). Its profile selects `read`, `grep`, `glob`,
      `write` and `@zikaron`, so one of those four file selectors grants `code`; which one is not
      measured.

## Not measured here

The TUI's rebuild of an out-of-sync profile, which neither a launch nor a reselection triggered
(result 30); whether the 3,000-character cut counts code points or UTF-16 units, since result 21's
`é` is in the Basic Multilingual Plane; the sandbox; and kiro's own Memory beside Zikaron.

## Re-deriving this

`PROBE_DIR=<dir> spikes/kiro-v3-probe/run.sh <agent> <tag> [kiro args]` runs `prompt-<tag>.txt` in
`<dir>/p2`, a `git init` outside any repository. That directory holds two agent configs. One is
V2-shape, with `allowedTools`, the four object-format hooks running `probe_hook.py <label>`, and the
stub as its only MCP server. The other is a copy of it put through `kiro-cli agent upgrade`.
Results 4 and 8 used Zikaron's own install instead. That is `python -m zikaron.install --harness
kiro` into a scratch project, followed by `kiro-cli agent upgrade` over its `.kiro/agents`. Run
from a shell with no `CLAUDE*` variables: `env $(env | grep -o '^CLAUDE[A-Z_]*' | sed 's/^/-u /')
…`.

Round 2: `python3 spikes/kiro-v3-probe/r2/setup2.py <dir>` writes `<dir>/p3`, a `git init` holding
the V3-only profiles, and the prompts. Then `PROBE_DIR=<dir> spikes/kiro-v3-probe/r2/run2.sh <agent>
<tag> [kiro args]` runs one, strips the `CLAUDE*` variables itself, and copies that launch's
`kiro.log` beside the output. The pairs are `ap a`, `ap a2`, `np n`, `ep e`, `bp b`, `rp r1` and
then `rp r2 --resume`. The agents of results 41 and 47 to 50 were written by hand into the same
project and run through `run2.sh` as `rf rf`, `dot dot`, `mt mt`, `ss ss` and `mt sm`: `rf` with
its 2,002-line file, `dot` with `.hidden/spill.txt`, `mt` with the five matchers of result 48 and a
`shell` rule, and `ss` with the two `SessionStart` entries of result 49. Results 51 to 54 added
`probe_obj` to the stub and the agents `sp`, `spc`, `spd`, `tw`, `tn`, `tm` and `tl`, run as `bp ob`,
`sp sp`, `sp sd`, `tw tw` and `tn tn`. Results 55 and 56 added `spg`, with `spd`'s rules, and `spn`,
with none, run as `sp sg`. Result 57 added `gp`, with `hook2.py`'s `pre-shell` role, and `gc`, run as
`gp gb`.
