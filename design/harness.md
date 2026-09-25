# Harness — one codebase, two harnesses

> **Normative for every harness-coupled fact in Zikaron.** Where this document and an older section of
> **another design document** disagree about kiro-versus-Claude-Code behaviour, this one is right and the
> other is stale — say so and fix it rather than reconciling them in your head. Deltas are currently placed
> in `architecture.md` (**six**, recounted 2026-09-22 — this said eight) and `schema.md`
> (one); `retrieval.md`'s push section still describes kiro trigger names and placement and has not been
> annotated.
>
> **Evidence, scoped precisely — an earlier draft of this preamble overclaimed.** Every **Claude Code**
> claim below is either traceable to a numbered section of `research/claude-code-harness-probe.md`
> (measured, 2026-08-16, Claude Code 2.1.233) — cited as a bare `§n` — or to
> `research/claude-code-installer-probe.md` (same date and version, the four things the *installer* writes
> config against), cited as `installer-probe §n` — or explicitly marked **unmeasured** or **decided**. **Kiro**
> claims trace to `research/kiro-mcp-lifecycle-probe.md`, `architecture.md` §"Two hook formats",
> §"The consolidator's model is a shipped config field" and §"Subagent sessions" (the 2026-08-01
> hook-probe measurement that hooks fire *for* subagent sessions) — not to the probe, which never ran
> against kiro.
> `research/claude-code-harness-contract.md` is a documentation reading of the same questions and is the
> **weaker** source: it got the load-bearing one — whether an MCP server can learn the session id — wrong.
> This project has been here before; `research/kiro-mcp-lifecycle-probe.md` exists for the same reason.

## D34 — Two harnesses, one implementation

Zikaron supports **kiro-cli** and **Claude Code** from a single codebase. Harness differences are carried as
**data in the table below**, not as forked code paths. There is one seam — `zikaron/harness/` — and
everything downstream of it is written once.

The one place that legitimately varies in *shape* rather than in *value* is the installer, because the
artefacts genuinely differ: kiro writes one agent JSON with `hooks` and `mcpServers` inline, while Claude
Code writes four files — two JSON, two YAML-frontmatter Markdown. That is an adapter with two implementations behind one interface,
and it is the only one.

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
| Session variable | `KIRO_SESSION_ID` | `CLAUDE_CODE_SESSION_ID` (§1) |
| Project-directory variable (D17 store scope) | **none** — measured: 17 KIRO_ variables across 42 probe records, not one spatial | `CLAUDE_PROJECT_DIR` — measured in **both** clients' processes (hook processes, and all six MCP server starts in `spikes/claude-code-harness/mcp.log`) and fixed while the payload `cwd` wanders (`dogfood-checkpoint` §11b) |
| Spawn trigger | `agentSpawn` (array format also accepts PascalCase trigger names generally, and `SessionStart` as an alias) | `SessionStart` (§2) |
| Prompt trigger | `userPromptSubmit` | `UserPromptSubmit` (§2) |
| Prompt field | `prompt` | `prompt` (§2) |
| Subagent triggers | none — hooks fire *for* subagent sessions instead | `SubagentStart`, `SubagentStop`, carrying `agent_id` + `agent_type` (§3) |
| Output channel, spawn/prompt | exit-0 stdout | exit-0 stdout (§5) |
| Output channel, subagent | n/a | **`hookSpecificOutput.additionalContext` only** — plain stdout reaches nobody (§7b) |
| Injection budget | `max_output_size`, stated as 65536, **bytes** | fixed **10,000 characters**, no field to raise it — and *which* kind of character is now measured rather than inferred: see §"Injection budgets" (§5, §7a) |
| Overrun behaviour | silent truncation | loud: notice + 2 KB preview + path to full text (§5) |
| Subagent budget | n/a | `additionalContext` ≥12,000 characters, ceiling unmeasured (§7f) |
| MCP server process scope | one per **agent instance** (`kiro-mcp-lifecycle-probe.md`) | **one or more per session** — two observed starting, only one ever served — shared by subagents (§4, §7g) |
| Harness binary | `kiro-cli` | `claude` |
| Unknown model id | **silent fallback to default** — hence the install-time check | **refused at spawn**, loudly, before any turn (§7d) |
| Shipped consolidator `model` | pinned `claude-sonnet-5` (an alias would fail the `--list-models` check — *inferred*, not measured) | the `sonnet` alias — *decided*, see §"The consolidator's model" |
| Hook timeout | `timeout_ms`, **milliseconds**, default 10000, stated explicitly in every object-format entry | `timeout`, **seconds**, default **30 s on `UserPromptSubmit`** (600 s elsewhere), stated explicitly in every entry (`installer-probe` §2, §3) |
| Hook timeout overrun | silent | **silent** — output discarded, nothing on stderr, nothing in the result object (`installer-probe` §4) |
| Consolidator tool grant | `tools: ["@zikaron"]` in the agent config, server registered in that same config | frontmatter `tools:` as a YAML block list with the single entry `mcp__zikaron-consolidator` — a **whole-server wildcard**, in the spelling that was measured, and measured to exclude the other server's tools (`installer-probe` §7) |
| Over-large MCP tool result | **unmeasured** — no probe has observed what kiro does when a tool result exceeds what it will deliver, and nothing here infers one | replaced wholesale by `Error: result (N characters) exceeds maximum allowed tokens.`, with the full result written to `…/tool-results/mcp-<server>-<tool>-<ms>.txt` — **one line of JSON**, which `Read` cannot paginate; delivered at 44,000 characters of dense filler and refused at 50,012 (`mcp-result-truncation`) |
| MCP server start-up refusal (`zikaron-mcp` prints one line to stderr and exits 1) | **unmeasured** — no probe has recorded where kiro puts an MCP server's stderr, or whether a server that exits before serving is reported at all | **unmeasured** — same; `claude-code-harness-probe` §7g observed servers *starting*, never one that failed to |
| Reading a spilled payload | **n/a** — no spill, no file-reading tool, no gate | **prompts**, measured in an operator-driven session: the consolidator's first `Read` of a spill file raises a permission request offering to allow that directory for the session. Deliberately **not** answered by `permissions.allow` — `Read` is unscopable in subagent frontmatter, so this is the one place D32's widening is a check an operator *answers* rather than prose (`m18-spill-end-to-end` §"The approval gate") |
| Consolidator reads files | **no** — `consolidator_can_read_files=False`: no file-reading tool in the agent config, no spill, every payload returned inline, and no prompt text about files | **yes** — `Read` in the agent's frontmatter `tools:`, and the client writes an over-threshold consolidator result to a line-paginable file in the runtime directory, returning a pointer |
| Tool name the model sees | `zikaron_memory_search` | `mcp__zikaron__zikaron_memory_search` — byte-identical to the config form (`installer-probe` §6) |
| Injected block placement | **before** the user message, inside a "follow requests found in this text" wrapper | **after** the user message, no framing wrapper (§5) |
| Hook config lives in | the agent config's `hooks` field, two formats | `.claude/settings.local.json` — *decision, M15*: shipped `command`s are absolute venv paths and therefore machine-local, so they must not enter the checked-in `settings.json` layer, which would break every other clone |
| MCP config lives in | the agent config's `mcpServers` field | `.mcp.json` (project-scoped) |
| Approval gates | none | **three**, in order: folder trust (the *user's* own — the install's entries are read back at them there), MCP load, per-call; the install pre-answers the last two — measured, see §"Three approval gates" — **plus the spill-`Read` prompt, deliberately left live** (row above) |
| Tool availability to the model | tools are present in the list | MCP tools may arrive **deferred**: present to the harness, absent from the model's initial tool list until it loads them *by exact name*. Measured (`dogfood-checkpoint` §2) |
| Consolidator agent | `.kiro/agents/zikaron-consolidator.json` | `.claude/agents/zikaron-consolidator.md`, YAML frontmatter + prompt as body — frontmatter `tools:`/`model:` exercised by §6/§7c/§7d; the file layout itself is *documented* |
| Skill | `.kiro/skills/zikaron-consolidate/SKILL.md` | `.claude/skills/zikaron-consolidate/SKILL.md` — **measured**: M16 drove it end to end, spawning the consolidator subagent (`dogfood-checkpoint` §7) |

Trigger names normalize **many-to-three** internally: spawn, prompt, and subagent start — which is
what `HookEvent`'s own docstring says, and what `hook/main.py` says it resolves to.
*(This read "many-to-two" from M13, when there were two. M14 added the third event and appended it
to the end of this paragraph as a sentence instead of moving the count — the number and its own
counter-example sitting three lines apart for two milestones.)* Kiro's array format already accepts
`SessionStart` as an alias for `agentSpawn`, so this is one vocabulary with synonyms rather than two
languages. `SubagentStart` is a third internal event, Claude-Code-only, carrying the policy and nothing else.

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

**The tripwire, scoped — and the scoping is load-bearing rather than tidy.** The naive rule ("log when the
payload's `session_id` differs from the resolved environment value") uses the **identical predicate** as
`hook/envelope.py::is_subagent_session`, and under kiro that divergence is the *routine, expected* subagent
case — so an unscoped tripwire would fire on every subagent turn, drowning the signal and polluting a
`hook.log` that `push.py` deliberately keeps to a closed vocabulary. Therefore:

- **The tripwire fires only when the detected harness is Claude Code**, where payload-equals-environment is
  measured invariant (§1) and any divergence is a genuine anomaly. Under kiro the same divergence is the
  subagent case and stays unlogged.
- It writes one line of kind **`session_env_mismatch`**, named so `hook.log`'s vocabulary stays closed.
- **On that divergence the hook prints nothing and makes no RPC, and this is a decision rather than an accident.** Making no call is what delivers the rationale, not merely printing nothing: a push
  resolved under the stale label would be injected into — and counted against — a different, live session's
  instrument stream, and `surface_call` is emitted by the **service**, so a call made but not printed would
  corrupt the instrument anyway, which corrupts the measurement the store exists to support; a lost push is recoverable
  through pull, which is the arm that does not depend on a hook at all. That is the same asymmetry
  §"Subagent sessions" uses to justify suppressing rather than pushing.

**The consequence, stated plainly: in the misdetected case the nested session loses push entirely, silently
except for that one log line.** This is the cost of detection-by-marker, which is the deliberate choice
(operator decision: consult `CLAUDECODE`, do not over-engineer). The known remedy, if it ever bites, is
cheap and needs no new mechanism: the hook already holds the payload's `session_id`, so it can select
**whichever harness's variable actually equals it** and detect by agreement rather than by marker. It is
recorded here so a future session does not have to rediscover it.

## Subagents

**`UserPromptSubmit` does not fire for subagents** (§3). This closes, by the harness's own construction, the
door D32's push-suppression rule was built to guard: no push can inject retrieval into a consolidator's
context, because no push fires there at all.

- **The kiro suppression rule stays in the code and is inert here.** It compares the environment session id
  to the payload's; under Claude Code the comparison is never reached for a subagent. Documented as a no-op
  rather than deleted, because kiro still needs it.
- **The over-breadth kiro accepted is fixable here and is fixed.** `SubagentStart` and `SubagentStop` carry
  `agent_id` **and `agent_type`**, so per-agent rules are exact. `architecture.md` §"Subagent sessions"
  accepts suppressing *all* subagents only because kiro's payload carries no agent identity; that
  justification does not apply to this harness and must not be copied into it.

**The write policy is delivered to subagents, precisely.** `SessionStart` fires once per session, so a
subagent would otherwise inherit Zikaron's tools having never seen D30's policy. The rule is: inject the
policy — its subagent variant, `SUBAGENT_WRITE_POLICY_PROMPT`, which says nothing is pushed because nothing
is — on `SubagentStart` for every `agent_type` **except `zikaron-consolidator`**, whose policy is its own
system prompt.

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
it is most likely to have been dropped. Kiro can do nothing equivalent.

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
`--mode primary` and `zikaron-consolidator` with `--mode consolidator` — because that is the only way a
subagent can reach a server at all. The consolidator subagent's frontmatter `tools:` therefore *selects
among session-visible tools* rather than getting a registration of its own, which is exactly why the
exposure below follows. Under kiro the two modes are registered in two different agent configs, which is
what made the gating mechanical there.

**The exposure, stated at its true size.** The primary agent holds the four verbs *and* `search` and `fetch`,
and because consolidation ownership is `(session_id, pid)` over a **shared** server process, it presents the
same pair a real consolidator in that session would — so it triggers the lazy `plan_groups`, or inherits a
live lease, and is served groups **as the owner**. The honest consequence is *an unauthorized consolidation
performed by a model with broad retrieval in hand*: wasted tokens, and possibly a poorly-judged merge written
to the long-term tier, which is the "manufactures a false record" failure `consolidation.md` names.
Never-lose, the receipts, row-level completion and the journal are all untouched; long-term **content** is
not. Under kiro this was mechanically impossible.

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

## The consolidator's model

**Claude Code refuses an unknown model id at spawn**, loudly, before any turn executes (§7d). That is the
opposite of kiro, whose silent substitution is the *sole* reason the install-time
`kiro-cli chat --list-models -f json` check exists. **So no install-time validation is needed under Claude
Code** — the harness enforces no-silent-fallback itself.

**Under Claude Code the shipped default is the `sonnet` alias; kiro keeps its pinned
`claude-sonnet-5` and its install-time check, because an alias would fail `--list-models`. So this
field *is* harness-varying data and has a table row — probe §7d's own closing inference that it was
not is a probe-note conclusion the design deliberately did not adopt, for the reason below.
Experiments pin, on both harnesses.** `architecture.md` §"The consolidator's model
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

## Three approval gates, and the one that reads our own config back at the user

Measured interactively in M16 (`research/claude-code-dogfood-checkpoint.md` §1); neither of the two the
installer names was observable before, because a headless run approves everything.

**A fourth interaction was added in M18 and is deliberately *not* pre-answered**: the consolidator's
first `Read` of a spilled payload prompts, offering to allow that directory for the session. It is
left live because a file-reading tool cannot be scoped to one path in subagent config, so the prompt
is the only point at which that grant is put to the operator as a question — see the "Reading a
spilled payload" row above and `research/m18-spill-end-to-end.md` §"The approval gate". So a default install **pre-answers two** and leaves
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
operator's override verbatim, and `assets.render`'s only two call sites are the skill and the
consolidator prompt. ~~So the substitution is load-bearing **once** — for the spawn instruction —~~
**— that overshoots the evidence, which reaches the write policy and stops there. What is refuted is
narrower: the substitution is not load-bearing *for the write policy*. It stays load-bearing wherever
`render` does run** — nine bare tool names across two artefacts: four in `CONSOLIDATOR_PROMPT`, four
in the skill body, and the one in the Claude Code spawn instruction, which is substituted into that
body before the rewrite. §"Tool names are a substitution point, not just the spawn instruction" is
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

## Injection budgets

**One shared conservative bound of 10,000 characters** for the push block and the write policy, and the unit
is **characters, not bytes** — bisected on ASCII (9,503 intact, 10,502 truncated), then pinned separately
because the ASCII bisection could not distinguish the units and this corpus has been burned by exactly that
conflation: 9,016 characters of `漢`, **27,016 bytes**, arrived whole (§5, §7a).

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

**Why the D34 table above still says "characters" rather than the measured unit.** That table has a
machine-checked contract — `tests/test_harness_table.py::test_injection_budget_value_and_unit` parses
each budget cell for **exactly one number and one unit word**, matching them against
`HarnessSpec.injection_budget` and `budget_unit`. The string "UTF-16" carries a digit, so naming the
measured unit in that cell makes the row unparseable and the test red — which it duly went, when this
was first written the other way. The precise unit therefore lives here, where there is room for it.
**One residual imprecision is left deliberately:** `BudgetUnit.CHARACTERS` is now known to be exactly
the ambiguous word this section exists to disambiguate. Renaming the enum and teaching the parser a
unit that contains a digit is the honest fix, and it is a code change rather than a checkpoint's
business.

**A character bound closes open question 11 for both harnesses**, and the derivation belongs in writing
rather than in anyone's head. Both the bound and the budget count **UTF-16 code units**, per the paragraph
above, and UTF-8 needs at most **3 bytes per UTF-16 unit** — a Basic-Multilingual-Plane character is one unit
and at most three bytes, an astral character is two units and four bytes, so the widest *per unit* is the
three-byte BMP character rather than the four-byte astral one. A five-row block fitting 10,000 units is
therefore at most 30,000 bytes, comfortably inside kiro's shipped 65,536; the figure at the gist bound is
`schema.md` §Bounds' and moves with the preamble. That ×3 is a real ceiling from the encoding — worth distinguishing from the invented "four bytes
per token" factor an earlier `tests/test_install_limits.py` asserted, which was a guess and was wrong in the
opposite direction. Entirely different standing.

The bound `gist` therefore needs is a **character** bound, since it is *tokens* that bound neither characters
nor bytes: the deployed WordPiece tokenizer maps an unbroken 4,000-character run to a single `[UNK]`.

Overrun under Claude Code is **loud** — an explicit notice, a 2 KB preview, and a path to the full text the
model can read — which is strictly better than kiro's silent truncation. But the preview is small enough that
the bound does the real work and the file is a backstop, not a plan.

## The installer's two targets

**The installer is the one place a harness difference may take a different *shape* rather than a different
value.** Everywhere else — every client — the difference is data in `zikaron/harness/spec.py`, because
forking doubles every future change to components the design keeps deliberately thin. The installer
cannot be written that way and the reason is structural rather than a concession: kiro's artefacts are
**one** file whose path the *user* supplies, and Claude Code's are **four** files at paths the *project*
fixes. That is not two values of one parameter. So `main.py`'s flow, preflight order, collision policy and
backup discipline stay single-sourced, and serialization and merge sit behind one `HarnessTarget` interface
with two implementations.

**Values still come from the seam.** The split is: a *value* that differs (a session variable, a trigger
name, an injection budget, the consolidator's model default) is a `HarnessSpec` field with a row in §"The
table" and a drift-guard test; a *shape* that differs (which files exist, how they are merged) is a
`HarnessTarget` method. A value that migrates into a `HarnessTarget` method is the seam failing.

### What a Claude Code install writes

Four artefacts, against kiro's two-plus-a-merge:

| Artefact | Path | Notes |
|---|---|---|
| Hook entries | `.claude/settings.local.json` | merged; **three** entries, not two — see below |
| Tool approval | the same `settings.local.json` | **two keys, not one**: `enabledMcpjsonServers` and `permissions.allow` — see below |
| MCP servers | `.mcp.json` | two: `zikaron` (`--mode primary`), `zikaron-consolidator` (`--mode consolidator`) |
| Consolidator | `.claude/agents/zikaron-consolidator.md` | YAML frontmatter, prompt as body |
| Skill | `.claude/skills/zikaron-consolidate/SKILL.md` | YAML frontmatter, body |

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
differing entry rather than merging over it, and the README tells them to ignore the file or re-run
the installer.

**Three hook entries, because M14 built a third path.** `SessionStart`, `UserPromptSubmit` **and
`SubagentStart`** — `hook/main.py`'s dispatch falls through to `subagent_policy.run` for the third, routed to
the `additionalContext` channel. Registering only the two triggers kiro has would leave that path dead with
nothing anywhere failing: no error, no log line, just subagents that never receive the write policy. Kiro
needs no analogue because it fires the ordinary hooks *for* a subagent session instead.

**The timeout is stated in seconds and this is the third unit in the family.** Kiro's `timeout_ms` carries
**10000**; Claude Code's `timeout` is **seconds** (measured, `installer-probe` §2). Copying the integer
across installs a 10,000-second budget — nearly three hours in which a wedged hook blocks every user message,
with the harness doing exactly as told and nothing reporting a problem. The two kiro formats already disagree
about this same field's unit between themselves. The value is stated rather than inherited for the reason
`hook/limits.py` gives, sharpened by measurement: the `UserPromptSubmit` default is **30 s**, not the 600 s
that applies to other events, so `push.py`'s ~2 s internal deadline clears the *tightest* default in the
table by 15× rather than the 300× a reader who checked only the general figure would have recorded.

### Three flags, and what each refuses

- **`--agent` is kiro-only.** It names the config to merge into, and Claude Code has no such thing — its two
  merge targets are fixed project paths. Passed under Claude Code it is **refused**, rather than ignored:
  ignoring it would silently discard the one instruction the user gave about where their config lives.
- **`--print-only` replaces "omit `--agent`".** Under kiro, printing the entries instead of writing them was
  an *accident of omission*. Made explicit, it works on both harnesses, and a Claude Code install stops
  having to choose between writing four files and doing nothing.
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
  `--no-trust-tools`.** That asymmetry is kiro's own, restated: a subagent has nobody to answer a
  permission prompt, so an available-but-not-allowed tool there does not ask — it fails at the
  moment consolidation needs it. `--no-trust-tools` is a statement about *your* writes, not about
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
  (§"Tool gating"). Reported, not silently accepted — the same reflex M12 applied to the array format's
  inherited `max_output_size`.
- **No model check.** Claude Code refuses an unknown id at spawn, loudly (§"The consolidator's model"), so
  the `--list-models` membership test has no analogue and needs none.
