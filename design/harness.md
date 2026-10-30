# Harness — one codebase, two harnesses

> **Normative for every harness-coupled fact in Zikaron.** Where this document and an older section of
> **another design document** disagree about kiro-versus-Claude-Code behaviour, this one is right and the
> other is stale — say so and fix it rather than reconciling them in your head.
>
> **Evidence, scoped precisely.** Every **Claude Code** claim below is either traceable to a numbered
> section of `research/claude-code-harness-probe.md` (measured, 2026-08-16, Claude Code 2.1.233) — cited as
> a bare `§n` — or to `research/claude-code-installer-probe.md` (same date and version, the four things the
> *installer* writes config against), cited as `installer-probe §n` — or explicitly marked **unmeasured** or
> **decided**. **kiro** means kiro-cli's **V3 agent engine**, at 2.35.1 or later (D34). Its claims trace to
> `research/kiro-v3-probe.md` (measured 2026-10-28 on 2.35.1 under `--v3`), cited as kiro-probe §n, or to
> `research/kiro-cli-v3-migration.md`, the V3 documentation read the same day, cited as
> kiro-cli-v3-migration §n — or are marked **unmeasured**. Nothing measured on kiro's V2 engine describes
> a supported harness.
> `research/claude-code-harness-contract.md` is a documentation reading of Claude Code and is the **weaker**
> source: it got the load-bearing question — whether an MCP server can learn the session id — wrong. kiro's
> documentation does not answer that question at all (kiro-cli-v3-migration §7), which is why kiro-probe §4
> measured it.

## D34 — Two harnesses, one implementation

Zikaron supports **kiro-cli** and **Claude Code** from a single codebase. Harness differences are carried as
**data in the table below**, not as forked code paths. There is one seam — `zikaron/harness/` — and
everything downstream of it is written once.

The one place that legitimately varies in *shape* rather than in *value* is the installer, because the
artefacts genuinely differ: kiro writes one agent JSON with `hooks` and `mcpServers` inline, while Claude
Code writes two JSON files and several YAML-frontmatter Markdown ones. That is an adapter with two
implementations behind one interface, and it is the only one.

**Why not fork, and why not pick one.** Forking doubles every future change to the hook and MCP clients,
which are the two components the design deliberately keeps thin. Picking one abandons a working deployment.
The table is small enough that neither is justified.

### The seam's cost constraint is measured, and it is easy to violate

`zikaron/harness/` is imported by `zikaron-hook`, which runs **once per user message**. `hook/envelope.py`
records the measurement that governs this: importing `zikaron.core.events` alone costs **28 ms** against a
whole-process hook budget of ~48 ms without it, which is why that module keeps its own guarded copy of the
request envelope rather than importing the canonical one. **The harness seam must be stdlib-only and
trivial** — no dataclasses, no logging, no core imports. A drift test guards the copy; it does not guard
against someone adding an expensive import.

**`enum` and `typing` are the two imports the seam does take, and both were measured before being
taken.** Adding `enum` costs nothing measurable, `socket` on the hook's existing floor having already
imported it, and `typing` costs ~2 ms, which `hook/envelope.py` already pays for its own `NamedTuple`.
So the closed sets `coding-standards.md` §2 asks for are affordable here. A frozen dataclass is not:
`dataclasses` pulls in `inspect`, which `envelope.py` records as most of that import's own cost.

## The table

| Fact | **kiro-cli** | **Claude Code** |
|---|---|---|
| Marker variable (detection) | absent | `CLAUDECODE` (§1) |
| Session variable | `KIRO_SESSION_ID`, equal to the payload's `session_id` in every hook (kiro-probe §4) | `CLAUDE_CODE_SESSION_ID` (§1) |
| Session variable reaches | **hooks** and the agent's shell (kiro-probe §4, §30), and no MCP server: no server's environment carries it, and `${KIRO_SESSION_ID}` in a server's `env` arrives literally, so the hook relays it — §"The session relay" | **both** clients: the hooks and the MCP stdio server alike (§1) |
| Project-directory variable (D17 store scope) | **none** — measured: six KIRO_ variables across all the hook and MCP server records the V3 probe logged, not one spatial (kiro-probe §25) | `CLAUDE_PROJECT_DIR` — measured in **both** clients' processes (hook processes, and all six MCP server starts in `spikes/claude-code-harness/mcp.log`) and fixed while the payload `cwd` wanders (`dogfood-checkpoint` §11b) |
| Spawn trigger | `SessionStart`, which the payload names even for an entry configured with the camelCase `agentSpawn` (kiro-probe §3) | `SessionStart` (§2) |
| Prompt trigger | `UserPromptSubmit` (kiro-probe §3) | `UserPromptSubmit` (§2) |
| Prompt field | `prompt`, the whole prompt; the documented `USER_PROMPT` variable is empty (kiro-probe §3) | `prompt` (§2) |
| Tool event payload | `hook_event_name`, `session_id`, `cwd`, `tool_name` — the tool id, `execute_bash` for the shell — and `tool_input` as a JSON object, the shell's carrying `command`, `description`, `cwd` (`null` in every call), `run_in_background` and `timeout`; a matcher naming the tool id selects that tool alone (kiro-probe §32, §48) | `hook_event_name`, `cwd`, `tool_name`, `tool_input` as an object, `scratchpad_dir` since 2.1.304, and `tool_response` after a call (`design/guards.md` §2) |
| Subagent triggers | none — a subagent's own hooks never fire, so it gets neither a session-start nor a prompt hook, and its tool calls fire the root session's tool hooks, under the root's session id (kiro-probe §12, §38) | `SubagentStart`, `SubagentStop`, carrying `agent_id` + `agent_type` (§3) |
| Output channel, spawn/prompt | exit-0 stdout, reaching the model in a `HOOK_INSTRUCTION` block (kiro-probe §6) | exit-0 stdout (§5) |
| Output channel, subagent | n/a | **`hookSpecificOutput.additionalContext` only** — plain stdout reaches nobody (§7b) |
| Output channel, tool event | none after a call: no post-tool output reaches the model on any exit code — `PostToolUse` after a shell, write, search or MCP call, nor `PostFileCreate` or `PostFileSave` (kiro-probe §6, §35, §36). Before a call, a `PreToolUse` hook's exit 2 blocks it and its stderr reaches the model framed as a hook instruction, a 5,000-character stderr whole; exit 0 stdout and exit 1 stderr reach nobody, and exit 1 lets the call run (kiro-probe §33, §34) | **`hookSpecificOutput.additionalContext`** — plain stdout goes to the debug log alone (`tool-hook-probe`), measured reaching the main session and a subagent alike (`m40-4-hook-probes`) |
| Injection budget | fixed **3,000 characters** per hook, on the spawn and prompt hooks alike, no field to raise it: neither spelling of an entry's size field moved it, it counts characters rather than bytes — *which* kind is unmeasured, see §"Injection budgets" — and two entries on one trigger each arrived whole just under it (kiro-probe §21, §49) | fixed **10,000 characters**, no field to raise it — and *which* kind of character is now measured rather than inferred: see §"Injection budgets" (§5, §7a) |
| Overrun behaviour | cut, and marked `...[truncated]` to the model and to no one else (kiro-probe §21) | loud: notice + 2 KB preview + path to full text (§5) |
| Subagent budget | n/a | `additionalContext` ≥12,000 characters, ceiling unmeasured (§7f) |
| MCP server process scope | one per **agent instance**, a child of the agent server that also parents every hook; each launch had an agent server of its own, and two sessions in one TUI process were not run (kiro-probe §5, §18) | **one or more per session** — two observed starting, only one ever served — shared by subagents (§4, §7g) |
| Harness binary | `kiro-cli`, release 2.35.1 or later on its V3 engine (kiro-probe §20) | `claude` |
| Unknown model id | **replaced by a default**, as V3 documents it and **unmeasured** here: the TUI's first prompt can fail, and a headless run warns on stderr and continues, which is still a substitution — hence the install-time check (kiro-cli-v3-migration §9) | **refused at spawn**, loudly, before any turn (§7d) |
| Shipped consolidator `model` | pinned `claude-sonnet-5.5`, the model Claude Code's `sonnet` resolves to, which `--list-models` lists under `--v3` (kiro-probe §10); an alias would fail that check — *inferred*, not measured — see §"The consolidator's model" | the `sonnet` alias — *decided*, see §"The consolidator's model" |
| Shipped documenter `model` | pinned `claude-haiku-5.5`, the model Claude Code's `haiku` resolves to, listed by `--list-models` (kiro-probe §10) | the `haiku` alias — *decided* (operator, 2026-10-20); Claude Code 2.1.304 serves it as `claude-haiku-5-5`, measured, where 2.1.292 resolved it to Haiku 4.5 — not pinned, since Haiku 5.5 is a month old and every Claude Code release from here resolves the alias to it (operator) |
| Shipped orchestrator `model` | pinned `claude-opus-5.5`, the model Claude Code's `opus` resolves to, listed by `--list-models` (kiro-probe §10) | the `opus` alias — *decided* (operator, 2026-10-20), for following the documentation skill's spawn rules |
| Hook timeout | `timeout`, **seconds**, documented default 60 (kiro-cli-v3-migration §2), stated explicitly in every entry | `timeout`, **seconds**, default **30 s on `UserPromptSubmit`** (600 s elsewhere), stated explicitly in every entry (`installer-probe` §2, §3) |
| Hook timeout overrun | **unmeasured** under V3 | **silent** — output discarded, nothing on stderr, nothing in the result object (`installer-probe` §4) |
| Hook `command` | `exec`, then the shell-quoted path: a shell command line, run as `sh` under the agent server, and `exec` makes the agent server the hook's own parent, as it is the MCP server's (kiro-probe §5, §13) | none prefixed — a **shell command line** too — an unquoted path containing a space does not run at all, so the path is shell-quoted and a start entry's `--components` is its arguments (`hook-command-shell-probe`) |
| Guard hooks (`guards`) | `PreToolUse` matcher `execute_bash`, the shell tool's id, which selects it and nothing else (kiro-probe §32, §48); no re-read hook, since no post-tool output reaches the model (kiro-probe §35, §36) | `PreToolUse` matcher `Bash\|Monitor`; `PostToolUse` matcher `Edit\|MultiEdit\|NotebookEdit\|Write` — each matcher a `\|`-joined list of bare tool names, which the guard splits to get the tools it judges (`design/guards.md` §5) |
| Guard deny (`guards.deny`) | **stderr** — exit 2, the reason on stderr and nothing on stdout, which blocks the call and reaches the model framed as a hook instruction; an accepted override prints nothing, since exit-0 output reaches nobody (kiro-probe §33, §34) | **envelope** — exit 0 with `hookSpecificOutput.permissionDecision: "deny"`, whose reason becomes the tool result, and `additionalContext` acknowledging an accepted override (`design/guards.md` §2) |
| Search reminder (`search_reminder`) | none — a post-tool hook's output was measured not to reach the model (kiro-probe §6), so a memory install writes no reminder (kiro-gaps) | `PostToolUse`; files matcher `Grep\|Glob`, a handler for each of `Grep` and `Glob`; shell matcher `Bash`, a handler for each of `Bash(*grep *)` and `Bash(rg *)` — installed as one group whose matcher joins the two, each handler's filter a string, since a list is never matched (`m40-4-hook-probes`) |
| MCP tool-call duration | a 330 s call **completed** under V3, with no `requestTimeout` on the server entry: the call returned `slept 330.0s` (kiro-probe §9) | a 330 s call **completed**, headless `-p`, 2.1.280: the model's reply carried `slept 330.1s` (same probe) — so the consolidator's 300 s planning wait fits under both |
| Consolidator tool grant | `tools: ["@zikaron", "read"]`, an `mcp` rule over `zikaron/*`, an `fs_read` allow rule matching `./.zikaron/spill/**` and an `fs_read` deny rule excluding it, in the agent config, server registered in that same config; its `next_group` call succeeded headless under the `mcp` rule alone (kiro-probe §17), and the deny refused reads and searches outside the directory (kiro-probe §53, §55) | frontmatter `tools:` as a YAML block list with the single entry `mcp__zikaron-consolidator` — a **whole-server wildcard**, in the spelling that was measured, and measured to exclude the other server's tools (`installer-probe` §7) — and `Read` |
| Over-large MCP tool result | at **30,000 characters** or more, replaced by a notice, the first and last 500 characters, and the path of a file under `~/.kiro/sessions/<hash>/<session id>/tool-outputs/` holding the whole; counted on the text block alone, so a result `zikaron-mcp` sends as text and again as structured content arrived intact at 29,500 (kiro-probe §40, §51) | replaced wholesale by `Error: result (N characters) exceeds maximum allowed tokens.`, with the full result written to `…/tool-results/mcp-<server>-<tool>-<ms>.txt` — **one line of JSON**, which `Read` cannot paginate; delivered at 44,000 characters of dense filler and refused at 50,012 (`mcp-result-truncation`) |
| MCP server start-up refusal (`zikaron-mcp` prints one line to stderr and exits 1) | **unmeasured** — no probe has recorded where kiro puts an MCP server's stderr, or whether a server that exits before serving is reported at all | **unmeasured** — same; `claude-code-harness-probe` §7g observed servers *starting*, never one that failed to |
| Reading a spilled payload | no prompt where the session's rules allow `fs_read` over the store, as the `./**` rule `kiro-cli agent create` writes does (kiro-probe §22, §47), since a subagent's read is decided by the session's rules; an ask otherwise, which a headless run refuses (kiro-probe §28, §52, §54) | **prompts**, measured in an operator-driven session: the consolidator's first `Read` of a spill file raises a permission request offering to allow that directory for the session. Deliberately **not** answered by `permissions.allow` — `Read` is unscopable in subagent frontmatter, so this is the one place D32's widening is a check an operator *answers* rather than prose (`m18-spill-end-to-end` §"The approval gate") |
| Documenter tool grant (`file_tools`) | `read`, `grep`, `glob`, `write`, then `@zikaron`, beside the config's own `mcpServers` entry for the primary server, with `fs_read`, `fs_write` and `mcp` rules: a hand-written profile carrying those loaded and ran headless, using `read_file`, `fs_write` and `str_replace` (kiro-probe §17). What the `grep` and `glob` selectors select is unmeasured, since V3's `read` covers searching too (kiro-cli-v3-migration §3) | `Read`, `Grep`, `Glob`, `Write`, `Edit` in the agent's frontmatter `tools:`, then `mcp__zikaron` — no shell, no spawn tool; `Edit` because a Haiku 5.5 documenter corrects its draft in place half the time (`design/code-knowledge.md` §5.1) |
| Consolidator reads files | **yes** — `read` in the agent config's `tools`, confined by its rules to the spill directory, and the client writes an over-threshold consolidator result to a line-paginable file there, returning a pointer; `read_file` pages a file by line offset, 30,000 characters a read (kiro-probe §41) | **yes** — `Read` in the agent's frontmatter `tools:`, and the client writes an over-threshold consolidator result to a line-paginable file in the runtime directory, returning a pointer |
| Spill file location (`spill_location`) | **store** — the store directory's `spill/`, where the consolidator's own rules can name it, under a project its session's rules allow reading | **runtime** — the runtime directory beside the socket, shared by every store of the user |
| Tool ids the model sees (`tool_ids`) | `read_file`, `str_replace`, `fs_write`, `execute_bash` — the read, edit, write and shell tools as a payload and a policy line name them (kiro-probe §7, §32), not the profile selectors `file_tools` holds | `Read`, `Edit`, `Write`, `Bash` |
| Tool name the model sees | `zikaron::zikaron_memory_search`, the `<server>::<tool>` form behind `tool_load` (kiro-probe §7) | `mcp__zikaron__zikaron_memory_search` — byte-identical to the config form (`installer-probe` §6) |
| Injected block placement | **after** the user message, in a `HOOK_INSTRUCTION` block (kiro-probe §6) | **after** the user message, no framing wrapper (§5) |
| Hook config lives in | the agent profile's `hooks` array; kiro also reads standalone `.kiro/hooks/*.json` files, which this install does not write (kiro-probe §15) | `.claude/settings.local.json` — *decision, M15*: shipped `command`s are absolute venv paths and therefore machine-local, so they must not enter the checked-in `settings.json` layer, which would break every other clone |
| MCP config lives in | the agent config's `mcpServers` field | `.mcp.json` (project-scoped) |
| Approval gates | **two**: an interactive **trust screen** on a folder's first launch, before any of its agents, hooks or MCP servers load, whose answer is recorded outside the repository so no install can pre-answer it, and whose decline exits kiro with no session (kiro-cli-v3-migration §8; kiro-probe §30, §31, §44); and a tool call no permission rule allows, which asks — a subagent's call allowed by the session's rules, less what any rule in the chain denies, its own allow rules adding nothing (kiro-probe §28, §52 to §56). Headless, every ask is refused, so the install writes the rules (kiro-probe §17, §24), and a headless run loads a workspace with no trust record (kiro-probe §43) | **three**, in order: folder trust (the *user's* own — the install's entries are read back at them there), MCP load, per-call; the install pre-answers the last two — measured, see §"Three approval gates" — **plus the spill-`Read` prompt, deliberately left live** (row above) |
| Tool availability to the model | MCP tools are **deferred** behind `tool_load` and `tool_call`, a tool's description arriving in the `tool_load` result; the identity vocabulary the consolidator's prompt and both skills use was measured to work anyway (kiro-probe §7, §8, §11) | MCP tools may arrive **deferred**: present to the harness, absent from the model's initial tool list until it loads them *by exact name*. Measured (`dogfood-checkpoint` §2) |
| Consolidator agent | `.kiro/agents/zikaron-consolidator.json` | `.claude/agents/zikaron-consolidator.md`, YAML frontmatter + prompt as body — frontmatter `tools:`/`model:` exercised by §6/§7c/§7d; the file layout itself is *documented* |
| Skill | `.kiro/skills/zikaron-consolidate/SKILL.md` — **measured**: consolidation ran end to end through it under V3, spawning the consolidator on its own `--mode consolidator` server (kiro-probe §11) | `.claude/skills/zikaron-consolidate/SKILL.md` — **measured**: M16 drove it end to end, spawning the consolidator subagent (`dogfood-checkpoint` §7) |
| Documenter agent and its skill | `.kiro/agents/zikaron-documenter.json`, `.kiro/skills/zikaron-document-code/SKILL.md`, and `.kiro/agents/zikaron-code-orchestrator.json`, the agent the skill has the session spawn and wait for, its prompt carrying the loop; a subagent spawns a subagent under V3 (kiro-probe §37) | `.claude/agents/zikaron-documenter.md`, `.claude/skills/zikaron-document-code/SKILL.md`, and `.claude/agents/zikaron-code-orchestrator.md`, the agent the skill has the session spawn in the background, its definition carrying the loop (`design/code-knowledge.md` §5.2, §5.4) |

Trigger names normalize internally onto `HookEvent`'s members, each name to the one member it
means: spawn and prompt under both harnesses, and under Claude Code alone the subagent start,
which carries the policy and nothing else, and the search reminder's `PostToolUse`
(`design/code-knowledge.md` §6). Under V3 both harnesses name the spawn and prompt triggers alike,
so the vocabulary is one set of names.

## Detection, session identity, and the nesting limit

**For the hook and the MCP client, detection is the marker variable and nothing cleverer**:
`CLAUDECODE` present ⇒ Claude Code, else kiro. Measured present in both hook processes and both MCP
server starts (§1). *The scope matters: the **installer** detects differently — it reads the
project's own `.claude/`/`.kiro/` directories first and treats the marker as a fallback, refusing
outright when the project names both or when neither the project nor the marker says. That is
§"The installer's two targets" below, and an unscoped "detection is the marker variable" here read
as covering it.*

**Session identity ports as a rename.** `CLAUDE_CODE_SESSION_ID` is exported into every process Claude Code
spawns — both hooks, the MCP stdio server, and a subagent's subprocesses — and equals the hook payload's
`session_id` (§1). So `architecture.md` §"Both clients resolve the same label" holds verbatim: the two-rung
ladder is `harness` (read the detected harness's variable, send it) and `minted` (absent ⇒ send null, adopt
the service's `zk-<uuid4>`), with `label_source` still a pure function of the label's prefix. **The reserved
`zk-` namespace check applies to whichever variable wins**, so no harness can claim a service-minted label
under either name.

Consequences that were feared and did not materialise: linked sessions, link coverage, both cross-client D30
signals and the per-session recall instrument all survive the move unchanged. The session id also **survives
`--resume`** (§7h), so a resumed session accumulates instrument counts correctly rather than splitting.

**`CLAUDE_PID` must never be read.** Measured: it is *not* overridden for child processes — a nested run
reported the outer session's pid while its actual parent was different (§1). `os.getppid()` is trustworthy;
that variable is not.

### The session relay

**Under kiro the session variable reaches hooks and no MCP server** (kiro-probe §4). Every hook process
had `KIRO_SESSION_ID`, equal to its payload's `session_id`; no MCP server's environment had it, and
`${KIRO_SESSION_ID}` in a server entry's `env` arrives literally. Left alone, the two clients' labels split
— measured in the store, the hook's events under `sess_…` and the MCP client's under a minted `zk-…` — and
linked sessions, link coverage, both cross-client D30 signals and the per-session recall instrument split
with them. `HarnessSpec.session_variable_misses_mcp_server` states the fact for kiro. The agent's shell
has the variable too (kiro-probe §30).

**kiro's agent server parents both clients** (kiro-probe §5, §13, §18). The MCP server's parent is the agent
server, a `node` process, and an install's hook command opens with `exec`, so that the same process is the
hook's parent rather than the `sh` the command runs under. Under a spec that says so:

- **The hook writes its payload's `session_id`** at every `SessionStart` and `UserPromptSubmit`, to a file
  named for its parent's pid in `paths.session_relay_dir`, a directory of its own under the runtime
  directory with the socket's `0700` rule. Only a non-empty string is written; the payload is untrusted
  JSON, and a malformed one leaves the previous label. **It is written first**, before the suppression check
  and before any socket, since a cold-start prompt hook can spend its deadline waiting on the service and be
  killed at kiro's timeout. **Atomically**, through a temporary name and `os.replace`, so a hook killed
  mid-write leaves the old label or the new one. **Best-effort as a whole**, as the warm-helper spawn is: a
  failure costs only the relay, and the MCP client mints. It adds no library module to the hook's import
  set (§"The seam's cost constraint is measured, and it is easy to violate").
- **The last writer wins.** Hooks fire only for top-level sessions (kiro-probe §12), and both run before any
  tool call of their turn, so the file names the session whose turn is running.
- **At `SessionStart` the hook also removes every file whose process is gone**, which bounds the directory to
  about one file per live agent server. A process this user cannot signal counts as alive.
- **`detect.session_label` reads the file for its own parent when the variable is absent**, and the reserved
  `zk-` check applies to what it reads. Both clients derive the directory from one function, so the writer
  and the reader cannot name two.
- **`ServiceConnection` resolves its label at its first labeled request**, since a kiro MCP server starts in
  the same second as the `SessionStart` hook (kiro-probe §4). `handshake()`'s `health` carries no label, and
  the label does not change once a request has carried it.

**What it covers.** A consolidator's server is a child of the same agent server (kiro-probe §18), so it takes
the label of the session that spawned it, which is how Claude Code labels a shared server too. Each launch
had an agent server of its own and no pid recurred (kiro-probe §5), so two terminals on one project get two
files. An install whose hook command lacks the `exec` writes a file for an `sh` nobody reads, and its MCP
client mints, exactly as it did before the relay.

**Two known limits, stated rather than built for.**

- **Two sessions inside one TUI process**, such as a tangent or the session dashboard, would share an agent
  server and an MCP process whose label is fixed at its first request, so the second session's MCP writes
  would carry the first one's label. Unmeasured.
- **A `zikaron knowledge` command typed from a shell no harness spawned** has no variable and goes through
  the same ladder; its parent is a shell no hook writes for, so it mints — unless that shell's pid was an
  agent server that died and was not yet swept, when it adopts that dead session's label. Unlikely, and a
  `cli` event is the cheapest kind to mislabel. One the agent runs through its shell takes rung 1 from its
  environment, since kiro exports `KIRO_SESSION_ID` to the agent's shell (kiro-probe §30), so its `cli`
  events link to the session as D31 intends and the relay is never read.

### The nesting limit, stated rather than engineered around

**The limit is directional, and an earlier draft of this section stated it symmetrically — wrongly.** §1
measured the Claude-Code-inner direction **safe**: a nested `claude -p` launched from inside another session
got its *own* fresh `CLAUDE_CODE_SESSION_ID`, correctly overridden rather than inherited. The exposed case
is the other one: **a kiro session — or any process tree — running under an enclosing Claude Code session
inherits `CLAUDECODE` and `CLAUDE_CODE_SESSION_ID`.** The root failure there is **misdetection of the
harness**; the stale session variable is one consequence, and the misdetected hook would also apply Claude
Code's channel table and 10,000-character budget (harmless today, but it is the mechanism, not a detail).

**A consequence that is not harmless was added on 2026-08-18, by D17's amended store scope.** The
inherited variables now include `CLAUDE_PROJECT_DIR`, and it names a directory that *exists* — so
`HarnessSpec.store_scope_dir`'s refusal of unusable values does not catch it, and the resolver
**adopts the enclosing project's directory**. A nested kiro session therefore reads and writes the
*outer* project's store: its `remember` lands there and its `search` answers from another project's
lore, silently. Before the amendment its MCP client keyed the correct inner store through
`Path.cwd()`, so this is a regression the amendment introduces rather than an existing hazard it
inherits, and it is durable memory rather than a lost push. The hook half is partly guarded by the
payload-versus-environment tripwire below; the MCP write path is not. **The suite's own exposure to
it was measured and is not there in this Claude Code version:** `CLAUDE_PROJECT_DIR` is exported to
hooks and *not* to the agent's shell, so `pytest -m integration_kiro` run from a Claude Code session
inherits no such value (`research/claude-project-dir-reaches-hooks-not-shells.md`).
`conftest._no_inherited_harness_environment` deletes it anyway, which costs nothing and stays
correct if a future version exports it. The hazard itself is unchanged for any process that *does*
inherit the variable, and nothing guards a human running kiro by hand inside another session. **The recorded remedy repairs the hook only, and that is the half
already guarded.** `detect.py` records it precisely: the hook holds its payload's own `session_id`,
so it can select whichever harness's variable actually equals that and detect by agreement. Note
what this is *not* — agreement between the marker and the session variable would not discriminate
here, because both are inherited and both agree, staleness and all. And the mechanism is **hook-only
by construction**: an MCP client holds no payload, so nothing in it can tell an inherited variable
from its own. **So the MCP write path — the half named unguarded above — has a named cost and no
named repair.** The resolver is deliberately not the place to invent one; the root cause is
misdetection.

**Two more consequences follow for a nested kiro session, and both are stated limits with no
mechanism.** *The spill:* its consolidator's `zikaron-mcp` misdetects too, so `_spill_policy` writes an
over-large group to the runtime directory, where the kiro consolidator's deny rule refuses its read, and
that group stalls as it would with no spill. *The guard start text:* `zikaron-hook --components guards`
prints the start text of the harness it detects, so a nested kiro session reads Claude Code's tool
names in it (`design/guards.md` §7). The guard itself is immune, since it takes its harness from its
command line, which the installer wrote for kiro (`design/guards.md` §5).

**Marked, per this document's own rule: the inheritance mechanism is *unmeasured*, argued by construction
from how environment variables descend.** What §1 *does* measure, and the honest evidence that outer-session
values leak into nested trees, is a stale **`CLAUDE_PID`** — observed while the session variable itself was
correctly fresh. An earlier draft claimed the stale-session-variable scenario "was hit accidentally during
the probe"; it was not, and that sentence is withdrawn.

**Link coverage cannot detect it.** Both clients read the environment by construction, so both read the same
stale value, they **agree**, coverage reads ~1.0, and the inner session's writes and searches are silently
attributed to the outer, live session's instruments (its *pushes* are not attributed but **suppressed**, by
the tripwire decision below — this sentence describes the un-tripwired baseline the argument starts from). Agreement-by-construction is precisely what
prevents the shortfall from appearing, so this must not be claimed as observable there.

**The tripwire's predicate is the suppression check's own.** The hook compares its payload's `session_id`
with the resolved environment value — `hook/envelope.py::sessions_diverge` — and since neither harness fires
a spawn or prompt hook for a subagent session (§3; kiro-probe §12, §38), the two agree in every hook either
harness fires. So a divergence is a misdetection wherever it is seen. Therefore:

- **The tripwire fires under both harnesses.** Payload-equals-environment is measured invariant under
  Claude Code (§1) and under kiro's V3 engine (kiro-probe §4, §12), whose subagents' tool calls fire the
  session's tool hooks under the session's own id (kiro-probe §38). Should a V3 build ever fire a start or
  prompt hook for a subagent, the cost is one line per such turn with the push still suppressed — noise,
  not a push into the consolidator.
- It writes one line of kind **`session_env_mismatch`**, named so `hook.log`'s vocabulary stays closed.
- **On that divergence the hook prints nothing and makes no RPC, and this is a decision rather than an accident.** Making no call is what delivers the rationale, not merely printing nothing: a push
  resolved under the stale label would be injected into — and counted against — a different, live session's
  instrument stream, and `surface_call` is emitted by the **service**, so a call made but not printed would
  corrupt the instrument anyway, which corrupts the measurement the store exists to support; a lost push is recoverable
  through pull, which is the arm that does not depend on a hook at all.

**The consequence, stated plainly: in the misdetected case the nested session loses push entirely, silently
except for that one log line.** This is the cost of detection-by-marker, which is the deliberate choice
(operator decision: consult `CLAUDECODE`, do not over-engineer). The known remedy, if it ever bites, is
cheap and needs no new mechanism: the hook already holds the payload's `session_id`, so it can select
**whichever harness's variable actually equals it** and detect by agreement rather than by marker. It is
recorded here so a future session does not have to rediscover it.

**A hook run by hand from inside a Claude Code session is this case, and it is the only one observed.**
The command inherits that session's `CLAUDE_CODE_SESSION_ID`, so a probe payload carrying any other
`session_id` is suppressed — it prints nothing, which reads as an empty push — and leaves one
`session_env_mismatch` line in the target project's `hook.log`. Both such lines on record came from an
agent probing another project's hook this way. **A probe passes `"session_id"` as
`$CLAUDE_CODE_SESSION_ID`**, and its push is then counted against the probing session in that store.
Separate sessions in separate terminals each get their own variable and never meet this.

## Subagents

**`UserPromptSubmit` does not fire for subagents** (§3). This closes, by the harness's own construction, the
door D32's push-suppression rule was built to guard: no push can inject retrieval into a consolidator's
context, because no push fires there at all.

- **Under kiro a subagent's own hooks never fire, and its tool calls fire the root session's tool
  hooks, under the root's session id** (kiro-probe §12, §38). A child agent got no `SessionStart` and no
  `UserPromptSubmit`, from its own profile or the session's, and every tool call of a subagent and of
  the subagent it spawned fired the session's `PreToolUse` and `PostToolUse`, carrying the session's id
  in both the payload and the environment. So no session-start or prompt hook fires for a subagent, the
  push and the policy never reach one by a hook, and the divergence check `push.py` and `spawn_warm.py`
  run is no subagent check under either harness: a divergence means the harness was misdetected, which the
  tripwire records under both (§"The nesting limit"). A subagent's tool hooks carry the root's id, so the
  tripwire holds; should a V3 build ever fire a start or prompt hook for a subagent, the cost is one
  `session_env_mismatch` line per such turn, with the push still suppressed. **A session's guard judges its
  subagents' shell calls**, and its exit 2 blocks a subagent's call, the stderr reaching the subagent as
  its tool result (kiro-probe §57), so Zikaron's subagent profiles carry no `hooks` of their own.
- **Per-agent rules are exact here**, because `SubagentStart` and `SubagentStop` carry `agent_id` **and
  `agent_type`**. kiro has no subagent trigger at all, so under kiro the write policy reaches a subagent
  only in its prompt: the install ends the documenter's and the orchestrator's prompts with
  `SUBAGENT_WRITE_POLICY_PROMPT`, fixed at install, and a subagent of the user's own that holds the memory
  verbs meets no policy — a row of `design/kiro-gaps.md`.
- **A kiro subagent may do what the session's rules allow, less what any rule in the chain denies; its
  own allow rules add nothing** (kiro-probe §28, §52 to §56). A child allowed to read one directory read
  outside it under a session allowing every read (§52); the same child with a deny rule carrying
  `exclude` was refused outside the excluded path (§53), for reads and for the search and listing tools
  (§55); a session's `fs_write` rule decided a leaf's write two levels down, through a middle agent with
  no rule of its own (§54); and a child with no rules did what the session allowed (§56). Measured for
  Zikaron's agents: a documenter spawned under a session with no `fs_write` rule asked before each write
  and, headless, wrote nothing, and one under a session allowing `fs_write` over `./code-knowledge/**`
  wrote; a consolidator spawned under a session with no `mcp` rule, as `--no-trust-tools` leaves it, had
  each of its `next_group` calls ask, headless refused, and the journal entry stayed where it was
  (kiro-probe §28). **So a shipped agent's allow rules decide nothing for it spawned**, and decide only
  where it runs as a session of its own; a deny in its profile does confine it, which is how the
  consolidator's read is held to the spill directory (§"The consolidator's model" has its grant). An
  interactive session puts a subagent's question to the user (kiro-probe §30).
- **A kiro subagent spawns a subagent** (kiro-probe §37), so the code orchestrator runs under kiro too,
  spawned by the session, which waits for it, and it spawns the documenters (`design/code-knowledge.md`
  §5.2). `research/nested-subagent-probe.md`'s stripped `subagent` tool was V2's.

**The write policy is delivered to subagents, precisely.** `SessionStart` fires once per session, so a
subagent would otherwise inherit Zikaron's tools having never seen D30's policy. The rule is: inject the
policy — its subagent variant, `SUBAGENT_WRITE_POLICY_PROMPT`, which says nothing is pushed because nothing
is — on `SubagentStart` for every `agent_type` **except `zikaron-consolidator`**, whose policy is its own
system prompt. M40's documenter and orchestrator receive it like any other subagent, since both hold the
memory verbs (`design/code-knowledge.md` §5.4).

**The channel is not the one the rest of the design uses**, and this was measured only after a draft asserted
otherwise: plain exit-0 stdout from `SubagentStart` reaches **nobody** — not the subagent, not the parent.
The policy arrives only via `hookSpecificOutput.additionalContext`, which the subagent then quotes verbatim
while the parent still cannot see it (§7b) — the isolation this delivery wants. **So the seam owns which
channel each event uses**, ~~and `hook/main.py`, which writes plain stdout unconditionally today, cannot
continue to.~~ **— stale as written: `harness/spec.py`'s `CHANNELS` maps the subagent trigger to
`ADDITIONAL_CONTEXT` and `hook/main.py` branches on `channel_for(event)`, wrapping the envelope for
anything that is not `STDOUT`.**

The `SubagentStart` path is **policy-only**: it does *not* spawn the warm helper (the session's own
`SessionStart` already did, and a second spawn per subagent is pure cost), and it *does* honour the
`.zikaron/write-policy.md` override through the same best-effort reader, so an operator experimenting with
the policy text sees it in both places.

**`SessionStart` re-fires on resume** with `source: "resume"` (§7h), so the policy is re-injected. That is
desirable rather than a defect — a resumed session may have lost it. If `source: "compact"` fires as
documented (**unmeasured**), the policy is restored automatically after a compaction, which is exactly when
it is most likely to have been dropped. **Under kiro, `SessionStart` fires on neither, and the policy
stays in context through both**: `--resume` kept the session id and fired only the prompt hook;
`/compact` kept the session, its label and the policy, whose session-start output kiro stores as a record
of its own, though the compaction summary does not carry it; and an interactive resume of the compacted
session quoted the policy's first sentence (kiro-probe §42, §45, §46). Compaction did drop the loaded
MCP tools, which the agent loaded again — kiro's behavior, not Zikaron's.

## Tool gating — D32 splits, and only one half ports

Measured across four configurations (§6):

- **Subagent frontmatter `tools:` genuinely restricts MCP tools.** So the consolidator still receives the
  four consolidation verbs and **nothing that reads** — no `search`, no `fetch`, and no knowledge search. **The half of D32 that carries D7's enforcement is
  mechanical here exactly as it is under kiro**, and that is the half that matters: code picks the
  candidates, and the consolidator cannot wander outside the group it was handed.
- **The other half cannot be reproduced.** An MCP server must be registered session-wide to be reachable by
  any subagent at all, so the primary agent necessarily also sees the four verbs. `permissions.deny` cannot
  claw them back from the primary alone: deny is **global** and *unregisters* the tool, after which a
  subagent whose frontmatter names it is refused at spawn with "zero tools". There is no per-subagent MCP
  registration — a frontmatter `mcpServers:` block is silently ignored.

**Both `--mode` registrations live session-wide in `.mcp.json`** — two entries, `zikaron` with
`--mode primary` and `zikaron-consolidator` with `--mode consolidator` — because that is the only way
a subagent can reach a server at all. Each carries `alwaysLoad` (§"MCP tools may arrive deferred").
The consolidator subagent's frontmatter `tools:` therefore *selects among session-visible tools*
rather than getting a registration of its own, which is exactly why the exposure below follows. Under kiro the two modes are registered in two different agent configs, which is
what made the gating mechanical there.

**The exposure, stated at its true size.** The primary agent holds the four verbs *and* `search` and `fetch`,
and because consolidation ownership is `(session_id, pid)` over a **shared** server process, it presents the
same pair a real consolidator in that session would — so it triggers the lazy `plan_groups`, or inherits a
live lease, and is served groups **as the owner**. The honest consequence is *an unauthorized consolidation
performed by a model with broad retrieval in hand*: wasted tokens, and possibly a poorly-judged merge written
to the long-term tier, which is the "manufactures a false record" failure `consolidation.md` names.
Never-lose, the receipts, row-level completion and the journal are all untouched; long-term **content** is
not. Under kiro it is mechanically impossible: the consolidator runs on its own `--mode consolidator`
server, which the primary agent's profile does not register (kiro-probe §11).

**Operator decision, 2026-08-16, re-confirmed after the exposure was restated at this size: accepted.** The
gating of the primary agent is **prompt-only** under Claude Code. The installer reports it rather than
letting the weaker guarantee pass silently.

## Consolidation ownership under a shared MCP process

Claude Code runs **one or more** MCP server processes per session — two observed starting, of which **only
the second ever served**, across calls that spanned two subagent launches, with no restart (§4, §7g). No
process is spawned per subagent. So `(session_id, pid)` cannot distinguish two consolidators in one session.

Two consequences:

- `_PlanBridge`'s "at most one successful `plan_groups` per client process" becomes **per session**, so two
  consolidators launched from one session are served the same run rather than told busy.
- The guard is per *process*, so a second serving process would get a fresh one and its first forwarded
  `next_group` would lazily fire `plan_groups` — **a spurious takeover of the session's own live run with no
  human invocation behind it.** This is open question 10's residual, and §7g bounds it tightly: only one
  process ever served, so the hazard needs a *serving* server to be restarted mid-session, which was not
  observed. The never-serving process costs nothing, since `zikaron-mcp` opens no socket and makes no RPC
  until a tool is called.

**Operator decision, 2026-08-16: accept both.** The lease still lapses, so crash recovery works, and the cost
is bounded — a spurious self-takeover costs one worker's in-flight reasoning and a replan, never a journal
row. Cross-session mutual exclusion, the case the lease was actually built for, is untouched. A run-token
design is named and deliberately **not** built.

**So the consolidation skill runs in the session that invoked it, and does not fork** (operator,
2026-10-21), as the code-documentation skill does not either. A second consolidator of one session is
served the same run, so what stands between a second invocation and two workers on one run is the
invoking session seeing the first one it spawned; a fork would start each invocation's consolidator
directly, with no such session.

## The consolidator's model

**Claude Code refuses an unknown model id at spawn**, loudly, before any turn executes (§7d). That is the
opposite of kiro, which documents replacing an unknown id with its default, with no more than a warning,
and that substitution is the *sole* reason the install-time `kiro-cli chat --list-models -f json` check
exists. **So no install-time validation is needed under Claude
Code** — the harness enforces no-silent-fallback itself.

**Both harnesses run the same model for the same agent** (operator, 2026-10-29: *"We should make sure
that both claude code and kiro use the same models for the same tasks, with only difference is that in
claude code we use alises while in kiro we have to use a specific version because there are no aliases
in kiro"*). **Under Claude Code each shipped default is an alias; under kiro it is kiro's id for the
model that alias was measured to resolve to, pinned, with its install-time check, because an alias
would fail `--list-models`.** Claude Code 2.1.306 and 2.1.308 resolve `sonnet` to `claude-sonnet-5-5`,
`haiku` to `claude-haiku-5-5` and `opus` to `claude-opus-5-5` (`research/claude-code-alias-resolution.md`),
so kiro ships the consolidator on `claude-sonnet-5.5`, the documenter on `claude-haiku-5.5` and the
orchestrator on `claude-opus-5.5`, each listed by `--list-models` (kiro-probe §10) — kiro's spelling
of each model, matched to Claude Code's resolved id by name, since the two lists spell one model
differently and nothing but the name ties them. **No test can see what an alias resolves to**: when
Claude Code moves an alias to a newer model, this section and the kiro ids are updated by hand, from
a measured resolution. So each model *is* harness-varying data and
has a table row — probe §7d's own closing inference that it was not is a probe-note conclusion the
design deliberately did not adopt, for the reason below. **Experiments pin, on both harnesses.** `architecture.md` §"The consolidator's model
is a shipped config field" requires the field to be **present explicitly** and to be **an id the harness
accepts** — an alias satisfies both, so *no silent inheritance* holds (the field is written, not omitted) and
*no silent fallback* holds (the harness serves exactly what was asked for). A third rule — *the value must be
stable over time* — is **not in the design**, and an earlier draft of this port inferred it from D29's
comparability goal and then treated it as binding, building a per-run recording path, a new RPC method, a
schema column, a version bump and a migration milestone on top of it. All of that is deleted.

- A **pinned default rots**: an install a year from now would ship last year's model, and once that id is
  retired the consolidator fails at spawn — breaking the product, which is worse than blurring an experiment.
- **The A/B `consolidation.md` calls for pins on each arm**, so a moving default never interferes: during the
  comparison the value is concrete by construction.
- **What the alias costs is narrow**: you cannot say retrospectively which concrete model ran a past
  consolidation. That bites only across a vendor upgrade, which is when you would have pinned. If a specific
  past run's model is ever wanted, the harness's own subagent transcript records it on disk (§7c) — it is
  simply not copied into the store, and no column is needed to make that true.

**A model's self-report is not a provenance source**, and was rejected on principle rather than on failure: a
subagent's self-report matched its transcript exactly (§7e), but only because Claude Code injects the model
id into the system prompt. It is the harness's own fact, read back by a model that can also paraphrase it or
be talked out of it, and putting it on a tool signature would reverse D27 to obtain a value the harness
already holds.

**The documenter's and the orchestrator's models are fields of their own**, `documenter_model` and
`orchestrator_model`, each with its own row in the table above, on the same terms: an alias under
Claude Code, the pinned id it resolves to under kiro, each checked against `--list-models` there, and
set by `--documenter-model` and `--orchestrator-model`, or by `--model` with every other agent
(`design/code-knowledge.md` §5.1). The consolidator's is set by `--consolidator-model`, or by `--model`
(§"The flags, and what each refuses").

## Three approval gates, and the one that reads our own config back at the user

Measured interactively in M16 (`research/claude-code-dogfood-checkpoint.md` §1); neither of the two the
installer names was observable before, because a headless run approves everything.

**A fourth interaction was added in M18 and is deliberately *not* pre-answered**: the consolidator's
first `Read` of a spilled payload prompts, offering to allow that directory for the session. It is
left live because Claude Code cannot scope a file-reading tool to one path in subagent config, so the
prompt is the only point at which that grant is put to the operator as a question — see the "Reading a
spilled payload" row above and `research/m18-spill-end-to-end.md` §"The approval gate". kiro can scope
one, by a deny rule in the subagent's own profile, which is how its consolidator's read is held to the
spill directory ("Consolidator tool grant" above; kiro-probe §53, §55). So a default install **pre-answers two** and leaves
two questions for a human: folder trust, once per directory, and the spill-`Read` prompt, once per
consolidating session.

| Gate | Fires | Answered by | Observed |
|---|---|---|---|
| 1. Folder trust | first entry to a directory Claude Code has not seen | nothing we write — it is the *user's* decision | fires, and **names our `permissions.allow` entries as a warning** |
| 2. MCP load | project-scoped `.mcp.json` servers | `enabledMcpjsonServers` | **no prompt** — the key works |
| 3. Per-call | each MCP tool call | `permissions.allow` | **no prompt**, across 6 writes and 8 reads |

Gate 1 is new to this design and is a **product cost, not a defect**: installing Zikaron makes a folder
look less trustworthy on first entry, because the trust dialog reads `permissions.allow` and surfaces it
as *"⚠ This folder pre-approves 2 tool permissions … Only proceed if you trust this configuration."* The
default trade stands — per-write prompts push against the write policy, and D30's evidence is that
under-writing already dominates, so friction on writes is the wrong direction — but the cost belongs in
writing. `--no-trust-tools` is the escape for an operator who would rather have the prompts.

Gate 1 **presumably does not fire in an already-trusted directory** — *inferred, unmeasured*
(`dogfood-checkpoint` §1); it is why the question could only be answered in a throwaway at all.
**If that inference holds it is the more consequential half:** installing into an already-trusted
directory pre-approves both servers with **no disclosure shown to anyone, ever**, since the trust
dialog is the only disclosure point in the flow and it is skipped exactly where installs normally
happen — a developer's own existing project. `--no-trust-tools` is the escape, and this is the
argument for weighing it rather than treating the default as settled.

## MCP tools may arrive deferred, and how the agent recovered their names is not established

Measured in M16: the zikaron tools were **not in the agent's initial tool list**, and its first action of
the session was to load their schemas *by exact name* — `select:mcp__zikaron__zikaron_memory_search,…`.

~~It knew the names because the injected write policy names them, and it got them right because
§"Tool names are a substitution point" rewrites the bare names to the `mcp__<server>__<tool>` form
for this harness. **So the substitution is load-bearing twice over.** It was built so the spawn
instruction would be correct; it is also the only thing that makes the tools *discoverable* when
they are deferred. A policy carrying bare names would **likely** leave an agent unable to find them
— *likely* because `ToolSearch`'s matching on a bare name was never probed
(`dogfood-checkpoint` §2) — and the failure is silent, since the agent simply concludes there are
no memory tools. Any future edit to the policy's tool-name handling must keep this property, and it
is not optional cosmetics.~~

**— the stated mechanism does not exist and never has.** `WRITE_POLICY_PROMPT` contains **no tool
name at all**: `re.findall(r"zikaron_[a-z_]+", …)` over the constant returns `[]`, and
`git log -S "zikaron_memory" -- zikaron/hook/write_policy.py` returns nothing, so no edit ever
removed one. Nor is the policy rewritten: `resolved_policy_text` returns the constant or the
operator's override verbatim, and `assets.render`'s call sites are the two skills and the
consolidator prompt. ~~So the substitution is load-bearing **once** — for the spawn instruction —~~
**— that overshoots the evidence, which reaches the write policy and stops there. What is refuted is
narrower: the substitution is not load-bearing *for the write policy*. It stays load-bearing wherever
`render` does run** — every `zikaron_` token in `CONSOLIDATOR_PROMPT`, in both skill bodies, and in
the Claude Code spawn instruction, which is substituted into the consolidation skill's body before
the rewrite. §"Tool names are a substitution point, not just the spawn instruction" is
the statement of it. And the deferred-listing surface names the tools directly, which is the likelier
explanation for how the agent had them.

**What this cost is the instruction, not the measurement.** The observation stands; the sentence
built on it told a maintainer that *"any future edit to the policy's tool-name handling must keep
this property"*, and there is no such handling to keep. **A directive to preserve a mechanism that
was never built preserves nothing and misdirects whoever obeys it** — and it survived because the
claim is internally coherent, cites a real measurement, and names a substitution that genuinely
exists somewhere else in the same file.

This is also **a better explanation for §9's `installer-probe` observation** that both servers were
"still connecting" and could not be named: a model cannot name tools that are not in its context.
Neither reading is refuted at n=1 apiece, but connection state was *inferred from* the naming failure,
and deferral explains the naming failure directly.

**And deferral withholds the *descriptions*, which is why the install writes `alwaysLoad`.** A deferred
tool is listed **by name alone**, its schema unloaded, and the description arrives only when the agent
loads that verb. What that looks like in practice: M16 found the zikaron tools absent from the initial
list, and a `~/Trading/LeibaTrader` transcript shows an agent loading each verb by exact name just
before first use — piecemeal and late. **What it did between session start and each of those loads is
not established**, and the agent's own account of it is not evidence: asked afterwards, it reported
never having had the descriptions at all, which the transcript's loads contradict. That is the same
*class* of error `FINDINGS-archive.md` §"The read path is barely used" records — a self-report
contradicted by the log — though not the same direction: that one flattered the system, this one
flatters the agent. Either way the log is what counts, and it is why the heading above hedges.

**So the claim `write-policy.md` and `build-plan.md` §M32 both rest on — that a description is in context
at the instant the argument it governs is being filled — holds only for a verb already loaded.** Whether
that is so depends on how crowded the harness's tool list is, which is the user's environment rather
than ours — so the fix below exempts our servers instead of trying to change it.

**The fix is `alwaysLoad: true` on both `.mcp.json` entries, and it is the installer's to write.**
Claude Code takes a per-server exemption from deferral, and the install writes it for the primary and
the consolidator both. Verified in a session after the change: **nineteen tools deferred, none of them
Zikaron's.** Re-verified from a fresh session once the descriptions were brought under budget —
**every verb on both servers carried a full description, none name-only and none truncated**, which is
the whole claim this key and §"Tool descriptions are capped" exist to make.

**It stays on the consolidator even though nothing needs it today — operator decision 2026-09-29,
taken as a defensive default rather than on the measurement.** Measured without the key, that
subagent's five entries — its four verbs plus `Read` — all arrived with full descriptions, because
deferral fires on a crowded list and that one is not. **That is a fact about the current verb count,
not about the design**, and it expires the day a fifth verb lands or a user grants that subagent tools
of their own. A guarantee that holds only while a list stays short is the kind that fails silently when
it is extended, so the measurement is evidence the key is idle rather than grounds to drop it.

**`ENABLE_TOOL_SEARCH` is rejected on scope.** It turns deferral off for *every* server in the project —
the user's context budget, not ours — where the per-server key spends only our own. It is also the
user's global setting, which an OS-level managed one can override. Both it and `alwaysLoad` are present
in 2.1.277.

**What it costs**: Zikaron's tool schemas are in context from session start, which is the budget
deferral exists to protect — bounded by the per-description cap (§"Tool descriptions are capped"). A
server-level `instructions` field would carry prose for a fraction of that, and whether it delivers is
an unrun probe rather than a plan. **The consolidator's share is paid in every *primary* session**,
since registration is session-wide, while the benefit accrues only inside a subagent granted one
server and `Read` — a list short enough that deferral does not fire on it today, per the measurement
above, which is why that key is insurance against a longer list rather than a live need.

**An install predating the key is an upgrade, not a conflict** — §"The installer's two targets".

## Tool descriptions are capped, and the cut takes the tail

**Claude Code truncates a long MCP tool description, appending `… [truncated]`.** Measured on the wire
descriptions this server sends: one at 2,054 characters truncates, one at 1,848 does not, which first
bracketed the cap to **[1,848, 2,054)** — at or above the shorter, strictly below the longer. A fresh
session has since carried **every** shipped description untruncated (§"MCP tools may arrive deferred"),
so the verified lower bound is now the longest one this server sends — a few characters under
`DESCRIPTION_BUDGET` rather than far under it. **The exact value is not established here**: 2,048 is the
power of two inside the range and so the likeliest constant, but no documentation was read for it and
2,000 is not excluded either.

**Counted in code points**, which is what the guard asserts with `len()`. The harness is Node and
§"Injection budgets" measured its other cap in UTF-16 units; the two counts agree only while every
description stays in the BMP, which the same guard asserts rather than assumes — a description that
gained an emoji would redden it, which is the point.

**So two claims hold with different strength, and the weaker one is the budget itself.** That every
description this server ships survives is **measured**, in a live session. That one could grow to
1,900 and still survive is **inferred from 2,048 being the likely constant** — the measurements put the
cap at or above the longest description sent, and the longest sent is short of 1,900, so nothing has
ever exercised the budget itself. It is a bet on the constant rather than a tested margin:
`DESCRIPTION_BUDGET` in `tests/test_mcp_tool_descriptions.py`, asserted against the wire per mode.
`CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH` does not appear in 2.1.277, so nothing here assumes the cap is
configurable.

**The cut takes the end, so ordering is a delivery decision.** Rules appended to a long description are
the first thing lost — which is what happened to the citation rule M33 shipped and to `remember`'s
entire `Returns` block, including how to resolve a `near_duplicates` offer. Order a description by
consequence, not by narrative.

**Measure the wire, not the file — and note that the wire is still not what the model sees.** The
description FastMCP sends is the dedented docstring, so a guard reading `primary.py` passes on text the
server never sends. But the wire is only necessary, not sufficient: the harness cuts *afterwards*, which
is how `test_mcp_tool_descriptions.py` came to pin a phrase past the cut while reading the wire
correctly. That gap is what `DESCRIPTION_BUDGET` closes and no phrase pin can. To measure:

```
.venv/bin/python -c "
import asyncio, tempfile
from pathlib import Path
from zikaron.mcp.server import build_server
for mode in ('primary', 'consolidator'):
    mcp = build_server(mode, scope_dir=Path(tempfile.mkdtemp()))
    for t in asyncio.run(mcp._list_tools()): print(len(t.description or ''), mode, t.name)"
```

## Injection budgets

**Both harnesses cut a hook's output at a fixed number of characters, and neither offers a field to
raise it.** The write policy and the push block share each harness's one budget, which
`HarnessSpec.injection_budget` carries and `HarnessSpec.exceeds_injection_budget` checks, counting UTF-16
code units under both.

**kiro's V3 engine cuts at 3,000 characters**, on `SessionStart` and `UserPromptSubmit` alike: 3,000
arrived whole and 3,001 arrived ending in `...[truncated]`, and neither `maxOutputSize` nor
`max_output_size` moved the cut (kiro-probe §21). **The cut is per hook, not per trigger**: two
`SessionStart` entries of 2,902 and 2,904 characters both arrived whole (kiro-probe §49). So under
`--components both` a kiro profile carries two start entries, the memory store's printing the write
policy and the guards' printing the guard start text, each inside the cut, where one entry printing both
would be cut (`design/guards.md` §5); a test asserts each entry's output against the budget. It counts characters rather than bytes — 2,080
characters of `é`, 4,060 bytes, arrived whole. **Whether it counts code points or UTF-16 units is
unmeasured**, since `é` lies in the Basic Multilingual Plane, where the two agree; the check counts units,
the larger of the two, so it bounds either. **The cut is marked to the model and to no one else**: the
run's event stream carries only the hook's `status: completed`. Both shipped policies fit, which
`tests/test_hook_write_policy.py` asserts against every harness's budget, so the next sentence added to
one turns a test red rather than arriving cut. An operator's override over the budget is printed anyway and
labeled `write_policy_override_oversize` in `hook.log` (`architecture.md` §"The install contract" says why it
is not refused); under kiro that label means the model saw the first 3,000 characters and the marker.

**Claude Code's is one shared conservative bound of 10,000 characters**, and the unit is **characters, not
bytes** — bisected on ASCII (9,503 intact, 10,502 truncated), then pinned separately because the ASCII
bisection could not distinguish the units and this corpus has been burned by exactly that conflation: 9,016
characters of `漢`, **27,016 bytes**, arrived whole (§5, §7a).

**Which *kind* of character it counts is now measured: UTF-16 code units.** The reason the question
existed is that `漢` is a Basic Multilingual Plane character, so it is one code point *and* one UTF-16 code
unit; §7a therefore separated characters from bytes and said nothing about code points versus UTF-16 code
units. Claude Code is a Node application, whose native string length is UTF-16 code units, so the second
reading was live rather than theoretical: every astral character — emoji included, and real gists contain
them — counts two there and one under a naive `len()`. M16 ran the decisive experiment this section called
for, an **astral** character, which separates all three candidates at once
(`research/claude-code-dogfood-checkpoint.md` §3):

| Content | code points | UTF-16 units | UTF-8 bytes | Result |
|---|---|---|---|---|
| ASCII | 9,503 | 9,503 | 9,503 | intact |
| ASCII | 10,502 | 10,502 | 10,502 | truncated |
| `漢` | 9,016 | 9,016 | 27,016 | intact |
| **U+1F9FF** | **6,000** | **12,000** | **24,000** | **truncated** |
| **U+1F9FF** | **4,600** | **9,200** | **18,400** | **intact** |


**What each row counts, because the rows do not agree and the corpus's own rule is to say so.**
The astral rows are **content only** — 6,000 and 4,600 characters exactly, hence the exact
multiples of 2 and 4. The `漢` row is quoted as M13 reported it, and 9,016 code points of pure
`漢` would be 27,048 UTF-8 bytes rather than 27,016, so that row evidently counts ~9,000 `漢`
**plus its marker characters**. No conclusion moves — every margin here is in the hundreds or
thousands of units and the discrepancy is 32 bytes — but a table whose rows measure different
things should say which.

**Bytes are refuted** — 27,016 B and 18,400 B arrive intact while 10,502 B truncates. **Code points are
refuted** — 6,000 code points truncates. **UTF-16 code units survive all five**, with the cap in
**[9,503, 10,502)** — intact at 9,503 puts it at or above, truncated at 10,502 puts it strictly
below. So `HarnessSpec.exceeds_injection_budget` counting UTF-16 units, chosen in M14 as the
conservative reading that upper-bounds every candidate, is the **measured** reading rather than a hedge —
and the gist bound below rests on measurement rather than on the budget holding "whichever is true".

**The D34 table above says "characters" rather than the measured unit** because
`tests/test_harness_table.py` parses each budget cell for exactly one number, and "UTF-16" carries a digit.
The precise unit lives here, where there is room for it.

**The push block needs a character bound**, since *tokens* bound neither characters nor bytes: the deployed
WordPiece tokenizer maps an unbroken 4,000-character run to a single `[UNK]`. `schema.md` §Bounds sets it at
1,024 UTF-16 units per gist, counted in the budget's own unit, and states the worst-case five-row block it
admits.

**That bound closes open question 11 for Claude Code, and does not for kiro.** The worst-case block fits
Claude Code's 10,000 with room to spare. Under kiro's 3,000 a five-row block fits only while its gists stay
within **404** units per gist: what the block's framing leaves of the budget, divided among five rows,
which `tests/test_install_limits.py` measures from `block.render`. No store has written gists near that.
Measured on the 652 gists in the four real stores, the longest is 246 characters and the five longest sum
to 1,148, which puts the real worst block near 2,125 (kiro-probe §21). So a kiro block overruns the cut
only with gists near the bound. When one does, the hook writes `push_oversize` to `hook.log` and prints the
block whole; kiro cuts it, and the model alone sees the marker. The remedy — render rows only while the
block fits, and record surface rows for what was shown — is in `FINDINGS.md` §"Owed work", to be built if
a truncated push is ever seen.

Overrun under Claude Code is **loud** — an explicit notice, a 2 KB preview, and a path to the full text the
model can read — which is strictly better than kiro's cut, which only the model sees. But the preview is
small enough that the bound does the real work and the file is a backstop, not a plan.

## The installer's two targets

**The installer is the one place a harness difference may take a different *shape* rather than a different
value.** Everywhere else — every client — the difference is data in `zikaron/harness/spec.py`, because
forking doubles every future change to components the design keeps deliberately thin. The installer
cannot be written that way and the reason is structural rather than a concession: kiro's artefacts are
**one** file whose path the *user* supplies, and Claude Code's are files at paths the *project*
fixes. That is not two values of one parameter. So `main.py`'s flow, preflight order, collision policy and
backup discipline stay single-sourced, and serialization and merge sit behind one `HarnessTarget` interface
with two implementations.

**Values still come from the seam.** The split is: a *value* that differs (a session variable, a trigger
name, an injection budget, the consolidator's model default) is a `HarnessSpec` field with a row in §"The
table" and a drift-guard test; a *shape* that differs (which files exist, how they are merged) is a
`HarnessTarget` method. A value that migrates into a `HarnessTarget` method is the seam failing.

**What refuses an entry is ownership rather than equality, on both harnesses**, so a field this
installer changes is an upgrade: `MCP_OWNERSHIP_FIELDS` for a server entry — `.mcp.json`'s or kiro's
`mcpServers` — and a hook's command. Under Claude Code that is a settings hook group's **programs** —
each command's first shell word, since a start entry's `--components` is a selection the install
unions with rather than a sign of another install — judged by membership: a group of this
selection's is this install's when every one of its commands runs a program this install writes
on that trigger, whatever their number and their `if` filters, so a group carrying our command
beside one of the user's is refused, not rewritten. Anything else is rewritten and reported. A
group running only the other selection's script is that selection's and is copied verbatim, since
two selections write one trigger (`zikaron/install/settings_hooks.py`). The server rule is written
once, in `zikaron/install/ownership.py`, and both targets import it; `architecture.md` §"The
install contract" states the predicates and the merge.

### What a kiro install writes

**It refuses a kiro-cli older than 2.35.1**, reading `kiro-cli --version` — which prints `kiro-cli 2.35.1`
(kiro-probe §20) — field by field as numbers over the `N.N.N` after the binary's name, so a suffix such as
`3.0.0-rc1` is read rather than refused, and an output with none is refused. Under `--print-only` the floor is
a note, as an absent harness is. The report says that V3 must be the engine, 3.0's default or `--v3` on
2.35, since under V2 the shipped agents' first tool call asks with nobody to answer; and that a headless run
needs `--require-mcp-startup`, because kiro starts the first turn without waiting for its MCP servers and
`zikaron-mcp` takes about two seconds to answer (kiro-probe §8, §16). The flag does not make an interactive
session wait, even one given its first prompt on the command line (kiro-probe §29), and a first turn without
Zikaron's tools is expected there, as it is under Claude Code (operator, 2026-10-29).

**Shipped outright, by a memory install:** `.kiro/agents/zikaron-consolidator.json`,
`.kiro/agents/zikaron-documenter.json` and `.kiro/agents/zikaron-code-orchestrator.json`, and the two
skills. No agent carries a V2 trust field: `permissions.rules` allows what each needs — the consolidator
an `mcp` rule over `zikaron/*` and `fs_read` over `./.zikaron/spill/**`, with a deny excluding that
directory; the documenter `fs_read`, `fs_write` and the same `mcp` rule; the orchestrator `fs_read`,
`shell`, `subagent` and the `mcp` rule — whatever `--no-trust-tools` says, since headless V3 refuses every
ask. Spawned, an agent's allow rules add nothing to the session's (§Subagents), so they decide only where
it runs as a session of its own, which is why the primary's `mcp` rule matters to the consolidator and why
the report names the rules the session needs. The documenter and the orchestrator carry `effortLevel`,
`medium` and `high`, which kiro reads though it does not document it (kiro-probe §39), and their prompts
end with the subagent write policy, since kiro has no subagent trigger to deliver it. `kiro-cli agent
upgrade --dry-run` classifies the consolidator and the orchestrator `v3-only` and the documenter `already
universal`, none "would upgrade" nor "out of sync" — `tools` sorted, since in another order the upgrader
calls a profile holding `grep` or `glob` out of sync (kiro-probe §26) — which
`tests/test_install_kiro_live.py` checks against the real binary. Both skills name the subagent and the
prompt and nothing else: V3 offers each subagent as a spawn tool of its own, with a prompt and an
explanation as its parameters (kiro-probe §11). The code documentation skill has the session spawn the
orchestrator and wait for it, writing the arguments on the spawn prompt's second line itself, since kiro
replaces `$ARGUMENTS` only for a skill invoked by its slash command (kiro-cli-v3-migration §5;
`design/code-knowledge.md` §5.2).

**Merged into the profile `--agent` names**, which the installer reads as one of three shapes, by predicates
of its own rather than the upgrader's words (`zikaron/install/kiro_merge.py`):

- **V2-only** — a V2 trust field (`allowedTools` set, or `toolsSettings` a non-empty object) and no
  `permissions`. V3 refuses such a profile and runs its default agent (kiro-probe §1), so it is **refused**
  here too, naming
  `kiro-cli agent upgrade <dir>`: converting a user's trust settings is the harness's job.
- **Universal** — `permissions` and `allowedTools` both, which is what `kiro-cli agent create` writes
  (kiro-probe §22). It gains `@zikaron` in `allowedTools` as well as the rules, and a non-empty
  `availableAgents` gains Zikaron's three agents, so that a TUI rebuild of its V3 half from its V2 one — documented,
  and not triggered by a launch or a reselection in the one session measured (kiro-probe §30), so the
  install writes for it rather than relying on it — keeps Zikaron's grant.
- **V3-only** — every other profile. It gains the rules alone, and its `toolsSettings` is neither read nor
  written.

What every shape gains, from a memory install: the two hook entries in the array form, `exec '<hook>'`
under `SessionStart` and `UserPromptSubmit`, with `timeout` in seconds and no size field; the
`mcpServers` entry; `@zikaron` in `tools`, unless `tools` holds `*`; and, unless `--no-trust-tools`, the
`mcp` rule and
`{"capability": "skill", "effect": "allow"}` — the rule without which the tool that loads a skill asks and
headless neither skill loads (kiro-probe §24), and the one the upgrader derives from a V2 profile. A rule
already present is not added twice. An **object-format `hooks`** holding only Zikaron's entries is rewritten
in the array form; one holding an entry of the user's is refused, showing that entry in the array form,
since a key is either the one or the other. **Ownership reads past a leading `exec` and matches a trigger by
meaning**, through a map from kiro's camelCase names to V3's, so a pre-V3 install the upgrader converted —
entries named `agentSpawn-0` and `userPromptSubmit-0` on camelCase triggers (kiro-probe §2) — is
recognized and rewritten, not refused or doubled. A profile carrying a `kiroUpgrade` block, which
`kiro-cli agent upgrade` and `kiro-cli agent create` both write, is out of sync after any such edit
(kiro-probe §14), and the report says so. The grants the session's rules must carry for Zikaron's
spawned agents stay the user's decision (operator, 2026-10-29: *"We should have note, not grant
permissions automatically"*), and the report names each rule they take: `subagent`, in `tools` and as
a rule, for the skills to spawn the consolidator and the orchestrator and for the orchestrator's
documenters; `shell` as a rule, for the orchestrator's planner, with no need for `shell` in `tools`;
`fs_read`, for each documenter's sources and the consolidator's spilled groups; and `fs_write` scoped to
`./code-knowledge/**`, the planner's default documents directory (kiro-probe §28, §54).

**A guards install writes hook entries into the profile and nothing else** (`design/guards.md` §5):
`zikaron-guards-SessionStart`, running `exec '<hook>' --components guards` to print the guard start
text, and `zikaron-guards-PreToolUse`, running `exec '<guard>' --harness kiro` with the matcher
`execute_bash` and the guard's own `timeout`. No agent, no skill, no `mcpServers` entry and no rule, and
none of the memory install's notes; without `--agent` it is refused, unless `--print-only`, since it
would write nothing and exit 0. **Ownership is per selection**: an entry is a selection's when its
reserved `name` is one the selection writes, or when its command, read past `exec`, runs a program of
the file name the selection writes on that trigger with the arguments it writes there — so the memory
store's `zikaron-hook` and the guards' `zikaron-hook --components guards` on `SessionStart` are told
apart — and an install replaces its own selection's entries, refuses one at another program path as
another install's unless `--force`, and keeps the other selection's untouched.

### What a Claude Code install writes

The memory store's artefacts are the rows below whose selection is `memory`, against kiro's shipped
files and one merge; `--components` selects the memory store, the guards (`design/guards.md` §5),
or both:

| Artefact | Path | Selection | Notes |
|---|---|---|---|
| Prompt entry | `.claude/settings.local.json`, merged, under `UserPromptSubmit` | memory | `zikaron-hook`, the per-message push; with the start entries, a memory install's hooks — see below |
| Start entries | the same file's `SessionStart` and `SubagentStart` | every selection | `zikaron-hook`, carrying `--components guards\|both` beside the guards — the union of what is installed |
| Search reminder entry | the same file's `PostToolUse`, beside the guards' group there | memory | `zikaron-hook`, one group, the seam's matcher and a handler per `if` filter (§"The table", `design/code-knowledge.md` §6) |
| Guard entries | the same file's `PreToolUse` and `PostToolUse` | guards | `zikaron-guard`, each group with its matcher and its own `timeout` |
| Tool approval | the same `settings.local.json` | memory | **two keys, not one**: `enabledMcpjsonServers` and `permissions.allow` — see below |
| MCP servers | `.mcp.json` | memory | two: `zikaron` (`--mode primary`), `zikaron-consolidator` (`--mode consolidator`), each with `alwaysLoad: true` |
| Consolidator | `.claude/agents/zikaron-consolidator.md` | memory | YAML frontmatter, prompt as body |
| Skill | `.claude/skills/zikaron-consolidate/SKILL.md` | memory | YAML frontmatter, body |
| Documenter | `.claude/agents/zikaron-documenter.md` | memory | YAML frontmatter with `effort: medium` and `tools:` the file tools and `mcp__zikaron`, prompt as body (`design/code-knowledge.md` §5.1, §5.4) |
| Code orchestrator | `.claude/agents/zikaron-code-orchestrator.md` | memory | YAML frontmatter with `effort: high`, `background: true` and `tools:` `Agent`, `Bash`, `Read` and `mcp__zikaron`; its prompt, then the loop, as body |
| Code documentation skill | `.claude/skills/zikaron-document-code/SKILL.md` | memory | YAML frontmatter, body telling the session to spawn `zikaron-code-orchestrator` |

**An install touches only its own selection.** Triggers it does not write are copied verbatim, and
so is the other selection's group on `PostToolUse`, which both write, so the guards over a memory
install keep every memory hook and both approval keys byte-identical, and the reverse; nothing
removes a selection.

**`settings.local.json`, never `settings.json`.** The installer writes absolute venv paths — machine-local by
construction, for the reason §"The install contract" gives about console scripts — and `settings.json` is the
shared, checked-in layer. Writing machine-local paths into a file the user commits breaks every other clone
of the repository.

**`.mcp.json` is committed by design, and that cuts against the reason `settings.local.json` was
chosen.** The rule above keeps machine-local absolute paths out of the checked-in `settings.json`
because they break every other clone. `.mcp.json` has exactly that problem and no untracked sibling
to escape to: it is project-scoped by definition, sits at the repository root, and a routine
`git add -A` commits it. **Accepted, with the residual named** — no per-project, declaratively
writable, machine-local MCP scope exists, so the choice is between this file and not registering the
servers at all. It degrades safely rather than silently: a clone-mate's install refuses on the
differing `command` rather than merging over it, and the README tells them to ignore the file or re-run
the installer.

**A memory install's hook entries are a trigger each for the start, the prompt, the subagent start
and the search reminder.** `hook/main.py`'s dispatch falls through to `subagent_policy.run` for
`SubagentStart`, routed to the `additionalContext` channel, as the reminder's `PostToolUse` is.
Registering only the triggers kiro has would leave both paths dead with nothing anywhere failing: no
error, no log line, just subagents that never receive the write policy and searches never reminded.
kiro has no subagent trigger, and a subagent's own hooks never fire (kiro-probe §12, §38), so it has no
analogue of the first: Zikaron's two code-knowledge agents carry the policy in their prompts, and a
subagent of the user's own gets none — a row of `design/kiro-gaps.md`.

**The timeout is stated in seconds, as both harnesses' entries now state it** (measured for Claude Code,
`installer-probe` §2; documented for kiro, kiro-cli-v3-migration §2). A millisecond figure in that field
installs a budget a thousand times too long — hours in which a wedged hook blocks every user message, with
the harness doing exactly as told and nothing reporting a problem — so the one constant is kept in
seconds. The value is stated rather than inherited for the reason
`hook/limits.py` gives, sharpened by measurement: the `UserPromptSubmit` default is **30 s**, not the 600 s
that applies to other events, so the stated value sits inside the *tightest* default in the table and never
raises a budget. `push.py`'s longest internal deadline — the one for a push that has to wait for the service
to start — is derived from the stated value, not from either default.

### The flags, and what each refuses

- **`--components` selects the memory store, the guards or both, on either harness.** `memory` is
  the default and writes what an install wrote before the flag existed. A harness whose
  `HarnessSpec.guards` is `None` would refuse `guards` and `both` before anything is written — the
  refusal is read from the seam, never from the harness's name — and both harnesses offer them.
  Under kiro a guards-only install needs `--agent`, unless `--print-only`. Every model flag under
  `guards` is refused too, since that selection ships no agent and checks no model;
  `--no-trust-tools` asks nothing of the guards and is a no-op.
- **`--model` sets every agent, and an agent's own flag sets that agent alone, over `--model`** —
  `--consolidator-model`, `--documenter-model` and `--orchestrator-model`; with neither, each agent
  takes its own default. **A model id is the harness's own** — one `kiro-cli chat --list-models`
  lists, or a Claude Code alias or full id — so a project set up for both harnesses installs twice,
  each run with that harness's ids. Each distinct model an install writes is checked once against
  its harness, all three agents' under kiro.
- **`--agent` is kiro-only.** It names the config to merge into, and Claude Code has no such thing — its two
  merge targets are fixed project paths. Passed under Claude Code it is **refused**, rather than ignored:
  ignoring it would silently discard the one instruction the user gave about where their config lives.
- **`--print-only` replaces "omit `--agent`".** Under kiro, printing the entries instead of writing them was
  an *accident of omission*. Made explicit, it works on both harnesses, and a Claude Code install stops
  having to choose between writing its artefacts and doing nothing.
- **`--harness auto` refuses when there is no positive evidence.** `harness.detect` falls back to kiro when
  `CLAUDECODE` is absent, which is correct **for the hook** — kiro exports no marker, so absence *is* the
  signal. It is wrong for an installer: run from a plain terminal, `auto` would write kiro artefacts into a
  Claude Code project and exit 0. That is the working-looking-but-inert failure this corpus has already paid
  for once, in the agent whose `mcpServers` was configured and whose `tools` did not select it. So the
  installer's `auto` is a **different question** from the hook's — "which harness is this project set up
  for", not "which harness am I running under" — and it refuses rather than guessing, naming both `--harness`
  values in the refusal.
  **From a terminal outside a session, that refusal is the ordinary first-install outcome rather
  than an edge case**, measured in `research/m30-docker-end-to-end.md`: a freshly trusted Claude Code
  project has no `.claude/` — neither the trust dialog nor an ordinary tool use creates one — so the
  project says nothing. `CLAUDECODE` is exported into the processes a session spawns, and it is the
  *only* marker `_resolve_harness` reads, which splits the first install unevenly. Agent-run under
  Claude Code, detection succeeds; under kiro, which exports no marker, an agent-run install is
  detected only from a `.kiro/` already in the project; person-run into a project not yet set up, on
  either harness, nothing says anything and the harness has to be named.

### Tool names are a substitution point, not just the spawn instruction

Claude Code addresses an MCP tool as **`mcp__<server>__<tool>`**, and the model sees that string verbatim
(`installer-probe` §6). So every bare `zikaron_memory_next_group` / `zikaron_memory_search` in the shipped consolidator
prompt and skill body names a tool that does not exist under this harness — and a model told to call a tool
it cannot find improvises rather than failing. The shipped prose therefore stays **one constant per
artefact** with the tool vocabulary *and* the spawn instruction substituted per harness, asserted as a
property rather than duplicated.

**The consolidator's grant is a whole-server wildcard**, `mcp__zikaron-consolidator`, written as a YAML
block list because that is the spelling the probe ran, and measured to exclude the other server's tools
(`installer-probe` §7). The inline `[…]` form is semantically identical YAML and is **not** what was
measured; this project ships the measured spelling, and the probe note now quotes the fixture rather than
paraphrasing it. Preferred over listing the four verbs explicitly for
a reason stronger than brevity: an unrecognised name in frontmatter **refuses the spawn** with "zero tools"
(probe §6), so an explicit list is a second declaration of a fact `mcp/consolidator.py` already owns, whose
drift mode is a consolidator that will not start. The wildcard delegates the question to `--mode
consolidator`, which is where D32 implements it anyway.

### What the install reports rather than enforces

- **Approval is asked twice over, and the install answers both — which is two keys, not one.**
  `enabledMcpjsonServers` governs whether a project-scoped `.mcp.json` server **loads** at all;
  `permissions.allow` governs whether each tool **call** goes through without a prompt. Conflating
  them is easy and was done once: an install writing only the first loads the servers and then puts
  every `zikaron_memory_remember` behind an approval prompt — the per-write friction
  `architecture.md`
  §"The install contract" calls worse than not asking at all, on the harness this project is
  migrating *to*. Both go into the same `settings.local.json`, as server-level `mcp__<server>`
  wildcards rather than one entry per tool, so there is no second list to drift from
  `zikaron/mcp/tool_names.py`.

  **The consolidator's server is granted unconditionally, and the primary's follows
  `--no-trust-tools`.** A subagent has nobody to answer a permission prompt, so an
  available-but-not-allowed tool there does not ask — it fails at the moment consolidation needs
  it. `--no-trust-tools` is a statement about *your* writes, not about
  whether consolidation can run.

  **Both keys are now measured to have their intended effect** — interactively, in M16
  (`dogfood-checkpoint` §1; §"Three approval gates" above): no load-time prompt and no per-call
  prompt across six writes and eight reads. **The install still states the approval step in its
  output anyway**, and the reason survives the measurement rather than being retired by it: no
  install-time or headless check can verify the effect, because a headless run approves everything
  (`installer-probe` §8), so nothing in the shipped software can notice the day a key stops working.
  Belt and braces, because the failure it guards is a fresh install with no Zikaron tools at all and
  nothing saying why. The notes are conditioned on the grants being genuinely absent, since the merge never
  removes one and an unconditional note would contradict the file on a re-run.
- **The primary agent's exposure to the four consolidation verbs.** A server must be registered session-wide
  to reach any subagent, so the primary necessarily sees both tool sets; D32's other half is prompt-only here
  (§"Tool gating"). Reported, not silently accepted.
- **No model check.** Claude Code refuses an unknown id at spawn, loudly (§"The consolidator's model"), so
  the `--list-models` membership test has no analogue and needs none.
- **Subagents whose `tools:` allowlist cannot reach Zikaron's server.** An explicit `tools:` list in a
  Claude Code subagent's frontmatter **overrides** the project-wide MCP registration the target otherwise
  relies on, so such an agent sees no Zikaron verb and every artefact this install writes is still
  correct — the case `~/Dividends` cost an hour to diagnose in 2026-09. The install scans the project's
  `.claude/agents/*.md`, parsing **only the block between the first two `---`, and only when the file
  opens with one** — the prose body that follows is not YAML, and a file not opening with `---` has no
  frontmatter at all, so it sets no `tools:` and inherits everything. The key resolves at column zero
  with or without a space before its colon, which YAML accepts and whose omission would read the file
  as setting no list at all — the *silent* direction. Its value may be a block list, a comma-separated
  inline string, or a **flow sequence** `[Read, mcp__zikaron]`, whose brackets are stripped before
  splitting or the first and last entries match nothing and a sound agent is named; entries may be
  quoted and may carry a trailing `#` comment. **Two spellings YAML accepts are deliberately not
  read** — a block scalar (`tools: >-` with the entries indented beneath) and a flow sequence whose
  bracket closes on a later line — because neither is a plausible way to write a tools list and both
  fail by naming an agent that is fine, which costs a name to check rather than a silence. It names
  each agent whose
  list holds no entry equal to `mcp__{MCP_SERVER_NAME}` or
  beginning `mcp__{MCP_SERVER_NAME}__`. **Equality-or-`__`-prefix, never a bare prefix**: the
  consolidator's server is `zikaron-consolidator`, so a `startswith` test would pass an agent that can
  reach only the consolidator. **The consolidator, which the installer writes itself, is skipped**,
  matched on the filename from `CONSOLIDATOR_AGENT_NAME` — its narrow grant is D32 working — while
  any *other* agent holding only the consolidator's grant is named, because it belongs to the
  consolidator alone. The documenter and the code orchestrator hold `mcp__zikaron`, so the scan
  passes them unskipped (`design/code-knowledge.md` §5.4). Two cases are
  **out of scope**: an agent with no `tools:` list and `disallowedTools: mcp__zikaron` is equally blind, and
  so is a **user-level agent under `~/.claude/agents/`**, which takes the same frontmatter and is usable in
  any project while sitting outside a scan of the project's own directory. Neither is named, said here so
  the next diagnosis does not re-derive it. Detection only — a user's
  allowlist is a deliberate grant, and widening it to reach our own tools is a decision that is not ours.
  **kiro has no analogue**, because its entries go *into* an agent config and `--agent` makes the merge
  explicit. **`zikaron doctor` runs the same function** (`distribution.md` §"The front door"), which is
  what makes this outlive the install: the agent that cannot see Zikaron is usually written after it.
