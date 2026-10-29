# Review — M41-1 brief (`design/build-plan.md` §"M41" and §"M41-1")

## Round 1 — 2026-10-28

**Artifact:** `design/build-plan.md`, §"M41 — kiro on its V3 engine, and only that" and §"M41-1 — An
install V3 refuses, a session label only the hook can see, and a first turn that does not wait".
**Evidence read:** `research/kiro-v3-probe.md` (all 16 results, "Not measured here", "Re-deriving
this"), `research/kiro-cli-v3-migration.md` (whole), `design/harness.md`, `design/architecture.md`
§"Both clients resolve the same label" and §"The install contract", `design/overview.md` D31/D32/D34,
`design/kiro-gaps.md`, and the code the brief names: `zikaron/harness/spec.py`, `detect.py`,
`zikaron/mcp/connection.py`, `zikaron/hook/{push,spawn_warm,tripwire,main}.py`,
`zikaron/install/{entries,writer,targets,harness,main}.py`, `tests/conftest.py`,
`tests/test_install_harness.py`, `tests/test_harness_table.py`, `spikes/kiro-v3-probe/`.
**Not re-flagged (intentional per brief):** V3-only, the 2.35.1 floor, kiro Memory ignored, the
M41-1/M41-2 split, the race reported rather than engineered around, the no-custom-agent install
fenced, the M40-5 layout.

### Summary judgment

The brief is well built: the relay-by-`ppid`-via-`exec` mechanism is sound, each of its load-bearing
joints (parent process, hook ordering, top-level-only hooks, same-second server start) is cited to a
probe result that actually says it, the done-when is measurable, and the invariants each carry a
mutation. It is not buildable as written on two points: one bullet contradicts `entries.py` and,
followed literally, ships a consolidator that cannot call its own server under `--no-trust-tools`;
and the two `permissions.rules` values it ships — the `mcp` rule's `match` and the documenter's
`fs_read`/`fs_write` capabilities — are sourced to neither evidence note and are never exercised
where a wrong name would fail rather than prompt. The rest is improvements: a refusal whose remedy
may be a no-op, an unordered relay write, an unbudgeted per-turn cost, and a `HarnessSpec` field
that after the flip varies nowhere.

### Findings

1. **[BLOCKER] Item 2's `--no-trust-tools` bullet contradicts the code it names and would break
   consolidation.** §"What ships" item 2, bullet *"Under `--no-trust-tools` there is no `mcp` rule,
   as there is no `allowedTools` entry today."* Today `entries.consolidator_agent_config` (line 470)
   and `documenter_agent_config` (line 562) write `allowedTools` **unconditionally**; `plan.trust_tools`
   is read only in `writer.py:426/445` (the user's own profile) and `targets.py:555/714` (Claude
   Code's `settings.local.json`). `design/harness.md` §"What the install reports" states the
   asymmetry and why: *the consolidator's server is granted unconditionally* because a subagent has
   nobody to answer a prompt — and under V3 headless every `ask` is a deny (migration §8). A builder
   following the bullet ships a consolidator and documenter with no `mcp` allow rule under
   `--no-trust-tools`, and the first `next_group` is refused with nothing saying why.
   **Fix:** delete the bullet from item 2 (the conditional already appears, correctly, in item 3 for
   the user's profile). Add an invariant: *"the shipped consolidator's and documenter's `mcp` rule is
   written whatever `--no-trust-tools` says"* (mutation: omitted under the flag).

2. **[BLOCKER] Two shipped values are sourced to neither note: `match: ["zikaron/*"]` and the
   documenter's `fs_read`/`fs_write` capabilities.** Item 2. Probe §2 says the upgrader "adds
   `permissions.rules`" but quotes none; §11 quotes only the `subagent` rule; `spikes/kiro-v3-probe/`
   holds no converted config (a grep for `capability`, `allowedTools`, `kiroUpgrade` finds nothing
   there). The migration note names `fs_read`/`fs_write` once, in passing, as what the *sandbox* page
   says permission rules "shape" (§8), and gives no `match` syntax for the `mcp` capability at all.
   Item 9 requires every kiro cell to be sourced to the probe or the docs; the brief's own shipped
   rules should meet that bar. The test item 2 promises asserts shape (`permissions` present), not
   that these names are what kiro honours, and the documenter's rule is never exercised headless in
   this milestone: the live code-knowledge test is fenced to M41-2, and done-when 5's TUI run would
   *prompt* on a wrong capability name rather than fail, so it cannot distinguish "the rule allowed"
   from "the operator answered an ask". A wrong name is the silent-dead-documenter failure this
   corpus has already paid for once (`writer._selecting`'s docstring).
   **Fix:** quote into `research/kiro-v3-probe.md` §2 the `permissions.rules` the upgrader produced
   for the consolidator and the documenter (the converted files from the §2 run, or one more
   `agent upgrade --dry-run` over a fresh install), and cite that in item 2. Then have item 12's live
   test exercise one `read`-capability and one `write`-capability call from the **documenter**
   profile headless — a direct `--agent zikaron-documenter` run writing one file is enough — so the
   names are measured where ask = deny. If that is deferred to M41-2, say in item 2 and in the
   install report that the documenter's rule is unmeasured under V3.

3. **[IMPROVEMENT] The object-format `hooks` refusal names a remedy that may be a no-op.** Item 3,
   second bullet. Probe §14 classifies a profile with `permissions` and no trust field as
   *"already universal"*; nothing measured whether `agent upgrade` rewrites the hooks of such a
   profile, and "already" reads as "nothing to do". The case that hits it is not exotic: a
   pre-M41-1 `--no-trust-tools` install into a profile that already carried `permissions` (no
   `allowedTools` was written), whose object-format hooks are **ours**. The user is refused, runs the
   command named, and is refused again.
   **Fix:** (a) our own object-format entries are owned by command already; replace them with the
   array entries rather than refusing on their shape. (b) For a user's own object-format entries,
   either convert with the mapping probe §2 recorded (`<trigger>-<i>`, `timeout_ms` → `timeout`
   seconds, `max_output_size` → `maxOutputSize`) — a single key is either an object or an array, so
   this is the only way to add ours beside theirs — or, if refusing, first run `--dry-run` on a
   `permissions`-plus-object-hooks profile, record whether the upgrader converts it, and cite that.
   Invariant: *"a profile whose only object-format entries are ours is rewritten, not refused"*
   (mutation: refusal kept).

4. **[IMPROVEMENT] The relay must be written before the hook touches the service, and the brief does
   not order it.** Item 4, second bullet. The cold-start session is where the label matters most: the
   first `UserPromptSubmit` can spend the whole `_COLD_START_DEADLINE_SECONDS` waiting and be killed
   at kiro's `timeout: 10`; a write placed after `surface_once` or in `_degrade`'s path is then
   skipped and the MCP client mints — exactly the split this item exists to close, on exactly the
   session where it would be measured. `push.py` also returns before any RPC on the suppression path
   (line 93–102), and `spawn_warm.run` likewise.
   **Fix:** state *"the relay is written first — before the suppression check's early return and
   before any socket is opened"*, and add the invariant *"the relay is written when the service is
   unreachable and when the push is suppressed"* (mutation: the write moved after the RPC; test: no
   service listening, file present). Write it atomically (`os.replace` from a temp name in the same
   directory): a hook killed mid-write otherwise leaves a truncated, shape-valid label the service
   will accept.

5. **[IMPROVEMENT] "A consolidator's server shares the agent server" is asserted, not measured, and
   the live test does not check it.** Item 4, last bullet, cites nothing. Probe §5 measured the
   process tree for the *primary's* two server processes; §11 says kiro "started a second server
   instance" for the subagent and records no parent; its label was minted (pre-relay). Under
   `(session_id, pid)` ownership nothing breaks if it mints, but the brief claims a property and item
   12 asserts "both clients resolve one session label" over hook and primary only.
   **Fix:** mark the sentence inferred, and extend item 12's assertion to *"the consolidator's
   `client_kind = consolidator` events carry the hook's `sess_` label"* (the probe already reads the
   store this way, §4 and §11). If it does not hold, the consolidator mints as it does today — say
   so rather than claim otherwise.

6. **[IMPROVEMENT] `fires_hooks_for_subagent_sessions` becomes `False` on every spec — a field with
   one value is not harness data.** Item 6. `design/harness.md` §"The installer's two targets": a
   value that *differs* is a `HarnessSpec` field. After the flip it differs nowhere;
   `tripwire.record_if_misdetected`'s early return (line 50) is dead on both harnesses;
   `test_harness_table.py::test_the_harness_firing_hooks_for_subagents_is_the_one_without_a_subagent_trigger`
   derives the field from the "Subagent triggers" cell being "none" and goes red on the flip anyway,
   so the drift guard has to be rewritten either way.
   **Fix:** delete the field, let the tripwire fire on both harnesses unconditionally, rename
   `envelope.is_subagent_session` to what it now means on both (payload/environment divergence =
   misdetection), and replace the invariant *"The tripwire fires under kiro on a divergence (field
   back to `True`)"* with *"the tripwire fires on a divergence under either spec (the kiro branch
   suppressed)"*. Less code than the flip, and the table loses a derived row instead of gaining a
   rewritten one.

7. **[IMPROVEMENT] The hook's camelCase synonyms are dead under V3; the spelling map belongs to the
   installer's ownership rule alone.** Item 3, third bullet: *"the hook's normalization keeps the old
   spellings as synonyms"*. Probe §3: the payload's `hook_event_name` is PascalCase *"including for an
   entry configured as `agentSpawn`"*, and `hook/main.py:63` dispatches on the payload. So the hook
   never sees `agentSpawn` under V3, and `_trigger_vocabulary` derives from spec fields — keeping the
   synonyms means a new constant with its own drift guard for a name no payload carries. What
   genuinely needs `agentSpawn` ↔ `SessionStart` is item 5's ownership match on the *config's*
   `trigger`.
   **Fix:** drop the hook synonyms; put the spelling map in `zikaron/install/` beside the ownership
   rule; reword the item 5 invariant to name that map.

8. **[IMPROVEMENT] The relay's per-turn cost is unbudgeted.** Item 4 adds a file write plus a
   directory sweep with a liveness check to every `SessionStart` and `UserPromptSubmit`, inside the
   hook whose whole-process budget `design/harness.md` §"The seam's cost constraint" puts at ~48 ms
   and calls "easy to violate". The sweep as written walks `$XDG_RUNTIME_DIR/zikaron`, which also
   holds every store's socket and `.sock.lock` — `conftest` measured 1,388 lock files accumulating
   there before the suite was isolated.
   **Fix:** put relay files in their own subdirectory so the sweep lists relays only; run the sweep
   on `SessionStart` alone (once per session is enough to bound growth); and add to done-when 3 an
   A/B of hook wall time with and without the write+sweep, same machine, same load (CLAUDE.md
   §"Measure before you assert"), recorded in `research/`.

9. **[IMPROVEMENT] The decision table's D31 and D32 rows carry the refuted facts and are not
   named.** Item 9 amends D34's row only. `design/overview.md` D31's rationale: *"`KIRO_SESSION_ID`
   is exported into every process kiro spawns … live MCP servers"* and *"hooks fire for subagent
   sessions … the hook now prints nothing when the two differ"*; D32's: *"Hooks were measured to fire
   for subagent sessions … The push hook therefore suppresses itself in subagent sessions."* The
   table rows are the standing case for strike-beside-replacement (CLAUDE.md §"How this project
   works"), and done-when 2's meaning-sweep is exactly where an unnamed row gets missed.
   **Fix:** add D31 and D32 to item 9's last bullet under the same strike rule. (`FINDINGS.md`'s D31
   and D32 lines do not carry either claim; only the rows do.)

10. **[IMPROVEMENT] Write-policy delivery to subagents needs a `kiro-gaps` row.** Under Claude Code
    `SubagentStart` delivers `SUBAGENT_WRITE_POLICY_PROMPT` to the documenter (harness.md
    §Subagents), which holds the memory verbs. Under V3 kiro no hook fires for a subagent (probe
    §12) and there is no subagent trigger, so the documenter never sees the policy. Under V2 the
    suppression rule had the same effect, but the reason the table and `README.md` (~line 377) give —
    *"kiro achieves [it] by firing its ordinary hooks for subagent sessions instead"* — is now false,
    and the gap has no row, so nobody closes it (`design/kiro-gaps.md` preamble's standing rule).
    **Fix:** add a `harness limit` row in this change; "closing it takes": the policy carried in the
    documenter's own prompt under kiro, as the consolidator's is — cheap, and M41-2's.

11. **[IMPROVEMENT] Weigh making a universal profile V3-only instead of feeding both halves.** Item
    3's universal bullet writes `@zikaron` into `allowedTools` so a TUI rebuild — *unobserved*, probe
    §14 — regenerates the `mcp` rule, and done-when 5 has to test this blind, with "item 3's rule
    changes before this lands" as the fallback. Under the V3-only decision the V2 half
    (`allowedTools`, non-null `toolsSettings`, `kiroUpgrade`) carries nothing Zikaron needs; removing
    it *after* the upgrader has converted the user's trust settings into `permissions` yields the
    `v3-only` shape probe §14 measured loading, which the TUI never rebuilds, and removes the
    out-of-sync note, the dual write, and the riskiest leg of done-when 5. The upgrader's `.json.bak`
    keeps the original. If the operator would rather not delete a user's fields, keep the design —
    but record in the brief that this was weighed, since the build's reviewer will ask.

12. **[NITPICK]** §M41: *"three defects, any one of which leaves a kiro install dead"* — only the
    refused profile does; the split leaves it working with split instruments, the race leaves the
    first turn without tools. Say which.

13. **[NITPICK]** §"What was found": *"all 12 tools answer"* — probe §8 lists all 12 and calls
    three. Write "all 12 listed, three called".

14. **[NITPICK]** Item 1: `kiro-cli --version`'s output shape is in neither note. Say the parser is
    checked against the real binary in the `integration_kiro` tier as `--list-models` is, and that a
    suffix (`3.0.0-rc1`) is tolerated, not refused.

15. **[NITPICK]** Item 12: the test must write its own V3-only primary profile carrying `subagent`
    in `tools` and its allow rule, since item 3 leaves that grant to the user; the existing
    `integration_kiro` classes never run `chat`, so this is the first fixture of its kind. Say so.

16. **[NITPICK]** Item 10: `kiro-cli agent upgrade --no-backup .kiro/agents` — the originals are in
    git and `.json.bak` files otherwise land in a tracked directory. Done-when 6: say whether
    `agent list` is engine-independent or needs `--v3`.

17. **[NITPICK]** Done-when 2 lists "silent fallback for an unknown model" among facts to rewrite but
    the brief never says whether the install-time `--list-models` check stays. Migration §9: headless
    V3 "warns and continues" — still a substitution. Say "the check stays; the row's reason becomes
    the documented behaviour, unmeasured".

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-10-28

**Artifact:** `design/build-plan.md` §"M41" and §"M41-1" (lines 7615–7947), re-read whole.
**Evidence re-read:** `research/kiro-v3-probe.md` (all 20 results), `research/kiro-cli-v3-migration.md`
(whole, §11 and §16 in particular), `design/harness.md` (whole), `design/architecture.md` §"Both clients
resolve the same label", §"Subagent sessions", §"Two hook formats", §"The install contract",
`design/overview.md` D31/D32/D34, `design/kiro-gaps.md`, `README.md`'s kiro passages,
`zikaron/harness/{spec,detect}.py`, `zikaron/hook/{push,spawn_warm,tripwire,main,envelope,limits,
connect}.py`, `zikaron/mcp/connection.py`, `zikaron/install/{entries,writer,targets,harness,
ownership,main}.py`, `zikaron/service/{paths,security}.py`, `tests/{test_harness_table,
test_hook_tripwire,test_install_harness,test_install_claude_live,conftest}.py`, `spikes/kiro-v3-probe/`,
`.kiro/agents/*.json`.
**Round 1 verified applied:** findings 1–7, 9, 10, 12–17 as proposed; 8 in the import-set form; 11 as a
recorded rejection. None is re-raised.

### Summary judgment

The brief is now buildable and its load-bearing joints are each cited to a probe result that says what
the brief says. What remains is precision at the edges the build will hit first: one citation says the
opposite of its source, the `exec` prefix is placed on the wrong side of the seam the design is strict
about, the shipped documenter's rules and `tools` are still not quoted anywhere a builder can read them,
and the done-when's enumerated fact list and the normative list each omit passages that state a refuted
fact as a dated measurement. No blocker; the fixes are sentences, one probe run, and one command.

### Findings

1. **[IMPROVEMENT] A citation inverted: §11 does not say 3.0 keeps `--v2`.** Item 3, universal bullet:
   *"trust settings the user may still use with `--v2`, which 3.0 keeps
   (`research/kiro-cli-v3-migration.md` §11)"*. §11 says the reverse — *"whether the 3.0 binary keeps
   `--v2` is **NOT DOCUMENTED**"* — and the Bottom line only that nothing documents V2's removal. The
   decision stands on the installer's deletes-nothing rule, which needs no V2 claim at all.
   **Fix:** *"…which nothing documents 3.0 removing (§11), and which the installer would not be
   entitled to delete even if it had"*.

2. **[IMPROVEMENT] The `exec` prefix is a harness *value* and belongs in `HarnessSpec`, not in the kiro
   target.** Item 5: *"This is a shape the kiro target writes."* `design/harness.md` §"The installer's
   two targets" draws the line the brief is bending: a *value* that differs is a spec field with a table
   row and a drift guard; a *shape* is which files exist and how they merge. A command-string prefix is
   a value — `entries.hook_command_string` already builds both harnesses' commands from one function —
   and CLAUDE.md §Harness says *"a value that migrates into a `HarnessTarget` method is the seam
   failing"*. The invariant *"a kiro hook command opens with `exec`"* then has nothing to read it from.
   **Fix:** a spec field (e.g. `hook_command_prefix: str`, `"exec "` for `KIRO`, `""` for
   `CLAUDE_CODE`), the table's "Hook `command`" cell gaining *"prefixed `exec`, so the agent server is
   the hook's parent (probe §13)"*, read by `hook_command_string` and covered by `test_harness_table.py`
   like item 4's new field.

3. **[IMPROVEMENT] The documenter's shipped rules are still not quoted where a builder can read them,
   and `file_tools` is not addressed.** Item 2 says the documenter's rules *"add `fs_read` and
   `fs_write`"* — no `match`. Probe §2 quotes `fs_read` with `match: ["./**"]` and nothing for
   `fs_write`; probe §17 lists capability names only; `spikes/kiro-v3-probe/` holds no profile (grep
   for `capability`/`permissions` is empty). Nor does either note say what `tools` the §17 documenter
   carried: today `KIRO.file_tools` is `("read", "grep", "glob", "write")`, and migration §16's table
   marks whether a hand-written profile with `grep`/`glob` selectors loads *"NOT DOCUMENTED"* — the
   upgrader keeps both only because it rewrites them. Under V3 `read` covers `grep_search` and
   `file_search` (migration §3), so the two are redundant at best.
   **Fix:** quote both §17 profiles' `tools` and `permissions.rules` verbatim into the probe note (they
   are in `PROBE_DIR`), cite that in item 2, and state whether `KIRO.file_tools` becomes
   `("read", "write")` — with the table row "Documenter tool grant (`file_tools`)" rewritten and that
   fact added to done-when 2.

4. **[IMPROVEMENT] Done-when 2's fact list omits rows the probe refutes.** The list is written as *"The
   facts:"* and a builder sweeping by it will stop at it. Missing: **"Tool availability to the model:
   tools are present in the list"** — probe §7 measures deferral behind `tool_load`; **"Tool name the
   model sees: `zikaron_memory_search`"** — probe §7 measures `<server>::<tool>`, and the identity
   vocabulary in the consolidator prompt and both skills was measured to work anyway (§8, §11), which the
   rewritten cell should say so nobody re-renders the kiro vocabulary; the `file_tools` row (finding 3);
   "Hook config lives in … two formats"; and D31's *"shell-tool subprocesses"* half of the
   `KIRO_SESSION_ID` claim, which probe §4 did not measure (hooks and the MCP server only) — relevant
   because `zikaron knowledge`'s `cli` events link through it.
   **Fix:** add the four, mark the shell-subprocess case unmeasured (or have done-when 5 type
   `echo $KIRO_SESSION_ID`, one line), and say the list seeds the sweep rather than bounds it — the
   predicate is every kiro cell the probe or the docs contradict.

5. **[IMPROVEMENT] The normative list omits the two `architecture.md` sections that state the refuted
   facts as dated measurements.** §"Subagent sessions — the push hook suppresses itself" opens *"Hooks
   fire for subagent sessions. Measured 2026-08-01"* and carries the rule as kiro's; §"Two hook formats,
   both inside the stable agent config" is the object/array table with `timeout_ms`, `max_output_size`
   and *"Zikaron ships object format by default"*. `harness.md`'s preamble (lines 15–18) names the
   2026-08-01 measurement as the kiro evidence source for the whole document. The build reads the
   normative list before it reads done-when 2.
   **Fix:** add both sections and the preamble's evidence paragraph to the list, the first two under the
   strike rule where a reader would otherwise re-propose the suppression as kiro's.

6. **[IMPROVEMENT] The relay rests on one agent server per session, which is inferred from single-session
   runs.** Item 4 keys the file on `os.getppid()` and argues last-writer-wins from hook ordering within a
   turn. Probe §5, §13 and §18 each measured one session. If the `node` agent server were shared across
   sessions in one project, two sessions' hooks would overwrite one file and the MCP client's first
   request would adopt whichever session's hook ran last — **mislabeled, not minted**, which
   `architecture.md` §"Both clients resolve the same label" calls the worst direction for the
   instrument. Two terminals on one project is routine (M40-5's field run was that).
   **Fix:** state the assumption as inferred in item 4, and check it where it is free: item 12 runs two
   headless turns concurrently in one project and asserts two relay files and two distinct `sess_`
   labels in the store; or done-when 5 opens a second TUI session and reads the relay directory.

7. **[IMPROVEMENT] `maxOutputSize` is written and unmeasured, while `KIRO.injection_budget` stays 65536
   and gates the runtime check.** Probe §2: *"Whether V3 honors it was not measured"*; the probe's own
   "Not measured" list includes *"a hook output past `maxOutputSize`"*. `MAX_OUTPUT_SIZE` reads
   `KIRO.injection_budget`, and `exceeds_injection_budget` would pass a 30,000-byte push block (the
   five-row worst case `harness.md` §"Injection budgets" derives) that a harness enforcing its old
   10240 default would cut silently — the exact failure `architecture.md` §"Two hook formats" names.
   **Fix:** one probe run with `probe_hook.py` emitting ~20 KB ending in a canary, which either confirms
   the number or moves it; record in the probe note and the table row. Measurement, not engineering.

8. **[IMPROVEMENT] The modal first install is unmeasured: what `kiro-cli agent create` emits on 2.35.1.**
   `writer._is_unset`'s docstring records this installer once refusing the harness's own default output.
   If `agent create` emits `allowedTools: []`, probe §14 says that profile *"would upgrade"* — V2-only
   under item 3's predicate — so a user following `README.md` line 239 (`agent create`, then `zikaron
   install --agent`) is refused and told to run `agent upgrade` on a file they made ten seconds ago.
   Correct, but the recipe should say it.
   **Fix:** run `kiro-cli agent create` once (and under `--v3`), record the shape in the probe note,
   and write the README recipe to match — an `agent upgrade` step between create and install if needed.

9. **[IMPROVEMENT] "Built in a git worktree" states no setup, and the live tier can test the wrong
   code.** A worktree has no `.venv`; the gate runs `.venv/bin/…`; and the installer resolves hook and
   MCP commands *"from its own interpreter"*, so `integration_kiro` run with this tree's `.venv` installs
   this tree's unchanged hook into the scratch project and tests old code against new configs.
   **Fix:** say the worktree gets CLAUDE.md's setup step 3 (`uv venv --seed .venv` and the editable
   install) and that done-when 3–4 run from the worktree's `.venv`; this tree's `.venv` keeps serving
   the four live projects, which is the point of the worktree.

10. **[NITPICK]** Item 3 defines V2-only and universal but leaves the third shape — no trust field at
    all, which probe §14 and §17 classify *"already universal"* and which the §17 documenter *is* —
    without a stated branch. Define the three by predicate: trust field and no `permissions` → refused;
    `allowedTools` and `permissions` → both halves fed; otherwise → V3-only treatment.

11. **[NITPICK]** Item 4's import-set claim is easy to violate in the natural implementation: `tempfile`
    pulls `random` and `shutil`. Say the temporary name is `os.open(…, O_CREAT|O_EXCL)` with a pid
    suffix; the relay directory goes through `security.ensure_runtime_dir` (already imported via
    `connect.py`) rather than a bare `mkdir`; `os.kill(pid, 0)` raising `PermissionError` reads as alive.
    And "first request" includes `handshake()`'s `health` if that carries the envelope
    (`zikaron/knowledge/client.py:185`).

12. **[NITPICK]** Done-when 6 measures more than it says: after item 10 the dogfood config is an
    upgraded profile installed over — out of sync — and probe §14/§19 classify that shape without
    loading it. Say the run answers *"an out-of-sync universal profile loads headless"*, the modal
    upgrade path item 5 names, and record it in the probe note under that description.

13. **[NITPICK]** Item 3: a re-install must add the `mcp` rule only when no equal rule is present
    (as `_selecting` does for `tools`), and `writer.py:445–450`'s `--no-trust-tools` note names
    `allowedTools` and must name the rule — done-when 2 covers the second by meaning; say the first.

14. **[NITPICK]** Item 6 deletes the field on one run (probe §12). Say the failure mode if a V3 build
    ever fires a hook for a subagent: one `session_env_mismatch` line per such turn, the push still
    suppressed — noise, not a push into the consolidator.

15. **[NITPICK]** Done-when 4: say whether `validate_agent_config` needs an engine flag on 2.35.1, and
    that `test_the_real_validator_accepts_the_config_we_actually_ship` now validates the V3-only
    consolidator and the documenter, not the V2 shape it reads today.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-10-28

**Artifact:** `design/build-plan.md` §"M41" and §"M41-1" (lines 7615–8033), re-read whole.
**Evidence re-read:** `research/kiro-v3-probe.md` (all 23 results, "Not measured here", "Re-deriving
this"), `research/kiro-cli-v3-migration.md` (whole; §1, §3, §4, §8, §16 and the conflicts register in
particular), `design/harness.md` (whole), `design/architecture.md` §"Both clients resolve the same
label", §"Subagent sessions", §"Distribution artefacts" through §"The install contract",
`design/overview.md` D31/D32/D34, `design/schema.md` §Bounds, `design/kiro-gaps.md`, the M40-5 brief
for layout, `zikaron/harness/{spec,detect}.py`, `zikaron/hook/{push,spawn_warm,tripwire,envelope,
main,connect,limits,write_policy}.py`, `zikaron/mcp/{connection,server}.py`,
`zikaron/install/{entries,writer,ownership,targets,harness,main}.py`, `zikaron/service/security.py`,
`zikaron/service/paths.py`, `tests/{test_harness_table,test_install_limits,test_install_harness,
test_install_claude_live,conftest}.py`, `spikes/kiro-v3-probe/`, `.kiro/agents/`.
**Round 2 verified applied:** findings 1–15 as the brief for this round describes, including item 13
and the probe note's §21–§23. None is re-raised. Each "probe §N" citation was checked against the
numbered result; one does not say what the brief says (finding 2 below).

### Summary judgment

The brief is now close: the mechanism is sound, the layout matches M40-5's, the done-when is
measurable, and the new item 13 reads the 3,000-character cut into the budget machinery correctly,
with the per-harness proof and the real-store gist measurement doing exactly what they should. What
stops it is small and cheap: one sentence tells the builder to do the opposite of what the design and
the code it names decide; one "measured" claim cites three results none of which records it; and
three decisions the build will hit on its first headless run — whether the merge still feeds
`toolsSettings.crew`, whether a V3-only primary needs a `skill` rule, and whether the relay write can
take the hook down — are left for the builder to guess. The rest is wording.

### Findings

1. **[BLOCKER] Item 13 says an oversize policy override is "refused", and the check it names does
   the opposite.** Line 7906–7907: *"An operator's policy override over 3,000 characters is refused as
   oversize under kiro, by the check that already exists."* The check that exists —
   `write_policy.read_policy`, docstring's sixth condition — uses the override **anyway** and writes
   `write_policy_override_oversize` to `hook.log`; `architecture.md` §"The install contract" records
   the decision (*"printed anyway and recorded in `hook.log`"*) and the reasoning (refusing discards
   the operator's stated intent; truncating it ourselves is the same failure with our name on it). A
   builder following the brief adds a refusal the design argued against, or stops to ask which to
   believe. Under kiro at 3,000 the existing behaviour is still right: the model sees 3,000 characters
   and `...[truncated]` (probe §21), the operator sees the label.
   **Fix:** *"…is printed anyway and labelled `write_policy_override_oversize` in `hook.log`, by the
   check that already exists — and under kiro that label now means the model saw the first 3,000
   characters and `...[truncated]`."*

2. **[IMPROVEMENT] "One agent server per launch is measured" cites three results that do not
   record it.** Item 4, lines 7808–7809: *"Every probe run had its own `node` agent server, a child
   of its own `kiro-cli-chat` (probe §5, §13, §18)."* §5 records the tree *within* one session, §13
   the hook's parent under `exec`, §18 both modes' servers under one `node`; none names
   `kiro-cli-chat`, and none compares `node` pids across runs. `spikes/kiro-v3-probe/ancestry.py`
   walks twelve ancestors with their `comm`, so the observation was captured — it is simply not in
   the note. Item 9 makes every kiro cell sourced to the probe or the docs, and this sentence goes
   into `design/harness.md` as the relay's standing assumption.
   **Fix:** add to probe §5 (or §13) what the chains showed — the `node` pid per run and its parent's
   `comm` — and cite that; or write "inferred from each run being its own `kiro-cli chat` process"
   and leave done-when 5's second-terminal check to measure it.

3. **[IMPROVEMENT] "V3 has no crew" is a documentation conflict, and the bullet leaves the merge
   undecided.** Item 3, lines 7768–7771: *"The `toolsSettings.crew` notes go, since V3 has no crew."*
   The migration note records the opposite as unresolved: `toolsSettings` is "removed in V3" on one
   page and "deprecated… still supported" on another, and the subagents page still names
   `toolsSettings.subagent`'s `availableAgents`/`trustedAgents` (§4; conflicts C5). The upgrader
   converts `toolsSettings` into `permissions.rules` (§1). So on a universal profile — the shape item
   3 keeps feeding on both halves precisely so a TUI rebuild regenerates V3 rules from V2 fields — an
   `availableAgents` that lists the user's agents and not ours would, on a rebuild, regenerate a
   `subagent` rule that excludes the consolidator and the documenter. The bullet says the *notes* go
   and nothing about `_merged_tools_settings`'s extension of a non-empty `availableAgents` or
   `_guard_crew_shape`.
   **Fix:** decide in the bullet. Consistent with the `allowedTools` rule: *"on a universal profile a
   non-empty `availableAgents` still gains both agents, for the reason `allowedTools` gains
   `@zikaron`; on a V3-only profile `toolsSettings` is neither read nor written; the crew notes go."*
   Add it to the universal/V3-only invariant (mutation: the extension applied to a V3-only profile;
   dropped from a universal one), and let done-when 5's rebuild leg read the regenerated rules.

4. **[IMPROVEMENT] Every measured skill invocation ran under a primary profile carrying a `skill`
   allow rule the installer does not write.** Probe §2: the upgrader derived a `skill` rule for the
   primary; §11, §14 and §17's consolidation legs all ran under that upgraded primary. Item 3's note
   covers `subagent` only (lines 7768–7771); a hand-written V3-only primary gets `tools`, the `mcp`
   rule, hooks, servers and `resources` entries, and no `skill` rule. Headless, an `ask` is a deny
   (migration §8); interactively it is a prompt. Item 12 then *"writes its own V3-only primary profile
   carrying `subagent` in `tools` and its allow rule"* (line 7896) — if that profile also carries a
   `skill` rule, the test measures a profile the install does not produce; if it does not, the
   consolidation-through-the-skill assertion is the measurement of whether one is needed.
   **Fix:** say item 12's profile carries **no** `skill` rule, so the run answers it; if it is needed,
   item 3's note gains it beside `subagent` (or the install writes `{"capability": "skill", "effect":
   "allow"}` — a grant narrower than `subagent`, so state which and why).

5. **[IMPROVEMENT] The relay write must be best-effort, and "written first" puts it outside every
   guard the hook has.** Item 4, lines 7784–7789: the write precedes the suppression check and any
   socket. `push.run`'s degraded boundary opens *after* `store_dir`/`hook_log_path` are resolved; a
   write placed before it, through `security.ensure_runtime_dir` — which raises `ZikaronError` on a
   hostile directory — propagates to `main()`'s outer `suppress`, which prints nothing: no policy on
   `SessionStart`, no push on `UserPromptSubmit`, and no `hook.log` line, on exactly the machines
   where the runtime directory is wrong. `spawn_warm._spawn_warm_helper_best_effort` guards its
   whole body for this reason.
   **Fix:** state that the relay write is guarded whole, like the warm-helper spawn — a failure costs
   the relay (the MCP client mints) and never the policy or the push — and add the mutation to the
   "written when the service is unreachable" invariant (the guard removed; tested with the runtime
   directory refused: the policy still prints).

6. **[NITPICK]** Item 2, lines 7715–7716: *"those selectors loaded and ran there"* — §17 measured
   the profile loading and `read_file`/`fs_write`/`str_replace` running; neither `grep_search` nor
   `file_search` was called, so whether `grep` and `glob` select anything is unmeasured, and under V3
   `read` covers both (migration §3). The table cell should say so rather than "ran".

7. **[NITPICK]** Item 13, lines 7901–7903: probe §21's `é` is a BMP character, so code points versus
   UTF-16 units is undistinguished for kiro — the same gap `harness.md` §"Injection budgets" closed
   for Claude Code with an astral run. `BudgetUnit.CHARACTERS` counts UTF-16 units, the larger of the
   two, so the check is a bound either way; say that in the §"Injection budgets" rewrite and list the
   astral run under the probe note's "Not measured here". Also say whether `BudgetUnit.BYTES` and the
   byte branch of `exceeds_injection_budget` go with their last user — `test_harness_table.py`'s two
   byte tests assert `KIRO.budget_unit is BudgetUnit.BYTES` and go red either way.

8. **[NITPICK]** Invariant "The floor is numeric", lines 7927–7928: the mutation *"floor lowered to
   2.35.0"* reddens none of the three listed cases. Add *"2.35.0 refused"*.

9. **[NITPICK]** Item 1: `main.py` downgrades `refuse_absent_harness` to a note under `--print-only`
   (lines 210–227). Say the floor is downgraded there too, since a preview on a machine without kiro
   has no version to read.

10. **[NITPICK]** Item 3, lines 7724–7731: the brief's "universal" (both `allowedTools` and
    `permissions`) is narrower than the upgrader's "already universal", which covers the §17
    documenter and any profile with no trust field — so *"follows V3's classification"* is not quite
    what it does. Say the three shapes are the installer's own predicates, named to avoid the
    upgrader's words, and that a profile with `permissions` and `kiroUpgrade` but no `allowedTools`
    (a `toolsSettings`-only V2 profile after upgrade) falls to V3-only, where a rebuild would read a
    V2 half carrying nothing of ours — the same blind spot done-when 5 covers.

11. **[NITPICK]** Item 3's V2-only predicate counts a non-null `toolsSettings` as a trust field, and
    `agent create` now writes `"toolsSettings": {}` (probe §22). With `permissions` absent, `{}`
    alone would be refused and sent to an upgrader that classifies "no trust field" as already
    universal (§14) — a refusal with no remedy. Make it *"`allowedTools` present, or `toolsSettings`
    a non-empty object"*.

12. **[NITPICK]** Item 13 withdraws `MAX_OUTPUT_SIZE`; `TIMEOUT_MS` is the other object-format
    constant in `hook/limits.py`, read by `test_install_limits.py::test_the_stated_timeout_leaves…`.
    Say it goes too (the test reads `HOOK_TIMEOUT_SECONDS`), so the builder does not meet it only
    through done-when 2's sweep.

13. **[NITPICK]** Done-when 5, line 7994: *"a project installed from this tree"* — the worktree
    paragraph has done-when 3–6 run from the worktree's `.venv`; say "installed from the worktree".

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-10-28

**Artifact:** `design/build-plan.md` §"M41" and §"M41-1" (lines 7615–8073), re-read whole.
**Evidence re-read:** `research/kiro-v3-probe.md` (all 24 results, "Not measured here", "Re-deriving
this"), `research/kiro-cli-v3-migration.md` (whole; §1, §2, §3, §4, §6, §7, §8, §16, the conflicts
register), `design/harness.md` (whole), `design/architecture.md` §"The request envelope" through
§"Both clients resolve the same label", §"Subagent sessions", §"Distribution artefacts" through
§"The install contract", `design/overview.md` D31/D32/D34, `design/schema.md` §Bounds
(`gist.characters`), `design/kiro-gaps.md`, `FINDINGS.md` §"Owed work", `README.md`'s kiro
passages, `zikaron/harness/{spec,detect}.py`, `zikaron/hook/{push,spawn_warm,tripwire,envelope,
main,limits,write_policy,connect}.py`, `zikaron/mcp/connection.py`, `zikaron/knowledge/client.py`,
`zikaron/install/{entries,writer,ownership,targets,harness,main,assets,code_knowledge}.py`,
`zikaron/service/security.py`, `tests/{test_harness_table,test_install_limits,
test_install_claude_live}.py`.
**Round 3 verified applied:** findings 1–13 as the brief for this round describes. Each "probe §N"
citation was checked against the numbered result; all say what the brief says. The brief's two
claims I could check directly hold: the render-fit remedy is in `FINDINGS.md` §"Owed work" (lines
186–189), and `hook/connect.py` already imports `zikaron.service.security`, so the relay's use of
`ensure_runtime_dir` adds no module.

### Summary judgment

The brief is buildable and its mechanism is sound; the round-3 fixes landed cleanly and the new §24
result closes the question it was asked. What remains is at the edges the build and the operator's
interactive test will hit: one normative document whose stated figures the budget change refutes is
not on the list; the interactive leg that exists to observe a TUI rebuild is run on a profile the
install may not make out of sync, so it can pass without observing one; the `skill` rule added in
round 3 has no stated V2 source for a rebuild to regenerate it from and its upgrader shape is still
unquoted; and one invariant names a deselected live test as its only red witness. Each fix is a
sentence or a quoted line. No blocker.

### Findings

1. **[IMPROVEMENT] `design/schema.md` §Bounds' `gist.characters` row is refuted twice by item 13
   and is not in the normative list.** The row (line 1582) says the bound makes a five-row block
   *"6,097 units, 61% of the smallest budget any supported harness states"* — with kiro at 3,000 the
   smallest budget is 3,000 and the block is 203% of it — and *"18,291 bytes, 28% of the largest
   byte-denominated one"*, and item 13 (line 7938) deletes the last byte-denominated budget.
   `tests/test_install_limits.py::test_the_designs_stated_worst_case_block_matches_what_the_block_actually_renders`
   reads that cell for exactly a "units" and a "bytes" figure (`_STATED_WORST_CASE`, line 70) and
   compares neither to a budget, so the row stays green while stating a false percentage. The
   rubric names this bound; item 13 says the derivation *"is restated per harness"* in
   `harness.md` §"Injection budgets" (line 7944) but never names the row that states the number,
   and the normative list (lines 7638–7653) does not carry `schema.md`. The same clause lives in
   D34's rationale — open question 11 *"is closed for both harnesses by a character bound plus
   UTF-8's ceiling"* — and item 9's D34 bullet (line 7886) amends the row for V2 only.
   **Fix:** add *"`design/schema.md` §Bounds, the `gist.characters` row"* to the normative list and
   say what it becomes: the units figure and its percentage of Claude Code's 10,000 stay, the byte
   figure and "largest byte-denominated" go, and the kiro overrun is pointed at `harness.md`
   §"Injection budgets". Add the Q11 clause to item 9's D34 bullet under the same strike rule
   (closed for Claude Code; under kiro the bound does not prove the block fits). Say the limits
   test's regex reads one figure.

2. **[IMPROVEMENT] Done-when 5's rebuild leg is run on a profile the install may not make out of
   sync, so it can pass without observing a rebuild.** Lines 8042–8045: *"a profile that `kiro-cli
   agent upgrade` converted from a pre-M41-1 install, then installed over … after whatever the TUI
   does to an out-of-sync profile."* A pre-M41-1 install already carries `@zikaron` in `tools` and
   `allowedTools`; the upgrader derives the `mcp` rule from it (probe §2); an install over the
   converted file finds `tools`, `allowedTools` and the `mcp` rule equal and adds none of them
   (item 3: *"an equal rule is there already"*, *"adds nothing twice"*), so the only change is
   `hooks` — and probe §14 classifies *"an upgraded one whose hook commands were edited by hand"*
   as **already universal**, not out of sync. The TUI then has nothing to rebuild, the leg passes,
   and the fallback it exists to trigger (*"item 3's rule for universal profiles changes before this
   lands"*) is unreachable. Whether this profile is out of sync at all turns on the one thing still
   unquoted (finding 3). The profile the install provably makes out of sync is item 3's own modal
   case: `agent create`'s (`allowedTools: []`, `permissions` with `fs_read` alone, probe §22),
   which gains `@zikaron` in `tools` and `allowedTools` and both rules — edits §14 measured to mark
   it out of sync. Done-when 6 (line 8055) makes the same assumption about the dogfood config.
   **Fix:** run the rebuild leg on an `agent create` profile installed into; keep the converted
   pre-M41-1 profile as the leg for item 5's ownership recognition (it is the right profile for
   that); extend the rebuild leg's checklist to the `skill` rule (finding 3); and in done-when 6
   write *"out of sync or already universal, whichever the upgrader says; both were measured to load
   headless (probe §13, §14)"*.

3. **[IMPROVEMENT] The `skill` rule has no stated V2 source for a rebuild to regenerate it from,
   and the upgrader's shape of it is still unquoted.** Item 3's universal bullet (lines 7765–7769)
   argues that a rebuild regenerates the `mcp` rule because the V2 half carries `@zikaron`; the
   `skill` rule the next bullet adds (lines 7777–7781) has no V2 field named that implies it. Probe
   §2 says the upgrader derived `skill` for the primary and not from what, nor with what `match`;
   migration §1 says a rebuild *"overwrites your manual V3 edits"*. If the rebuild derives no
   `skill` rule, the consolidation skill stops loading until the user answers an `ask` — not dead
   interactively, but a silent reversal of what the install wrote, on the modal profile. And item 3
   says the install writes *"the same rule"* the upgrader derives, which is unverified: a `match`
   on the upgrader's rule makes ours unequal, so a re-install over an upgraded profile adds a
   second `skill` rule (harmless) and marks the file out of sync (which decides finding 2's
   classification). This is round 1 finding 2's class, one rule later.
   **Fix:** quote the upgrader's primary `skill` rule from the §2 run into the probe note (the
   converted files are in `PROBE_DIR`) and write that shape; add *"and `skill` rule"* to done-when
   5's rebuild leg; and say in the universal bullet what a rebuild that drops it costs and that the
   install report says so.

4. **[IMPROVEMENT] The `skill`-rule invariant names a deselected live test as its only red
   witness.** Lines 7966–7967: *"(the `skill` rule omitted: item 12's consolidation leg fails at
   `disclose_context`)"*. The invariants' preamble (line 7958) says each mutation is *"applied in
   memory by a pytest plugin"* and done-when 1 says every new test was seen red; `integration_kiro`
   is deselected by `addopts`, so the gate never runs the witness named, and the invariant has no
   hermetic test behind it. The merge-side invariant is what the plugin can redden.
   **Fix:** *"both rules in `plan_kiro_merge`'s document, neither under `--no-trust-tools`, neither
   twice on a re-install (either omitted; written under the flag; added beside an equal one)"* — and
   keep item 12's leg as the measurement that the rule is needed, which is a different claim.

5. **[IMPROVEMENT] The "MCP tool-call duration" row is a V2 measurement the seeds do not name, and
   V3 measured 150 s against a 300 s wait.** `harness.md`'s row says a 330 s call completed under
   kiro, *"so the consolidator's 300 s planning wait fits under both"*. Probe §9 under V3: a 150 s
   call completed with no `requestTimeout` set, so the documented 120 s default (migration §6) was
   not enforced at 150 s — which says nothing about 300 s. Item 9's general rule (*"a fact neither
   measured nor documented under V3 says so"*) covers it in principle; done-when 2's seed list
   (lines 8010–8025) is where the build looks, and a 330 s cell that reads as a measurement is the
   kind a sweep keeps.
   **Fix:** add it to the seeds as *"the 330 s call: 150 s measured under V3, 300 s unmeasured"*, or
   re-run `spikes/m34_tool_call_duration_stub.py` at 330 s under `--v3` once and cite it. Either is
   one line.

6. **[NITPICK]** Item 4, lines 7827–7830: *"That first request includes `handshake()`'s `health`,
   if `health` carries the envelope."* `architecture.md` §"The request envelope" answers the
   conditional: `health()` *"takes no `client` envelope, resolves and returns no label, and nothing
   is adopted from it"*. So the label is resolved at the first **labelled** request, which
   `handshake()` is not — for `zikaron knowledge` that is its first verb after `connected()`. State
   it rather than hedge it.

7. **[NITPICK]** Item 4, lines 7799–7802: *"the reasoning is measured: hooks fire only for top-level
   sessions (probe §12), and both of those hooks run before any MCP call of their turn."* The first
   half is §12; the second is by construction (the prompt hook fires on submit, the model's calls
   follow), and probe §4 and §8 measure the opposite ordering for the *start* — which is why the
   label is resolved at first request. Say "the first measured (§12), the second by construction".

8. **[NITPICK]** Item 1, lines 7700–7703: say what an output with no leading `N.N.N` does
   (`kiro-cli (dev)`, a bare name). Refuse, naming the raw output, as `_parse_model_ids` fails
   closed — and add it to the floor invariant's cases.

9. **[NITPICK]** Item 12, lines 7918–7921: every measured consolidation run's primary (§11, §14,
   §17, §24) carried an `fs_read` rule, and the test profile is described as `subagent` and its
   rule *"and nothing else of what the install writes"* — `fs_read` is not something the install
   writes, so the sentence does not say whether the profile has it. Say which; without it a failure
   at skill load has two candidate causes.

10. **[NITPICK]** Item 3, lines 7788–7790: the `subagent` spawning note gets V3 wording; the
    `shell` note beside it (`writer.py:458`, the planner) needs the same — `shell` in `tools` and a
    `{"capability": "shell", "effect": "allow"}` rule (migration §3: `execute_bash` under the
    `shell` tag), or the harness asks and headless refuses. Done-when 5's code-knowledge leg is
    interactive and answers the ask, so the note says the rule is unmeasured.

11. **[NITPICK]** Item 5, lines 7853–7854: *"since 3.0 converts their profiles"* overstates
    migration §1 — automatic upgrades are enabled for users who took the startup choice or whom the
    3.0 switch migrates, the trigger set unspecified, and "externally managed agents" are skipped,
    undefined. The design handles both outcomes, so write "may convert".

12. **[NITPICK]** Invariant lines 7978–7979: *"(the budget back at 65,536 bytes; …)"* — after item
    13 deletes `BudgetUnit`, "bytes" is not expressible; the mutation is "the budget back at
    65,536".

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-10-28

**Artifact:** `design/build-plan.md` §"M41" and §"M41-1" (lines 7615–8102), re-read whole.
**Evidence re-read:** `research/kiro-v3-probe.md` (all 24 results, "Not measured here", "Re-deriving
this"), `research/kiro-cli-v3-migration.md` (whole), `design/harness.md` (whole),
`design/architecture.md` §"The request envelope" through §"`label_source` is derived", §"Subagent
sessions", §"Distribution artefacts" through §"The install contract", `design/overview.md` D31/D32/D34,
`design/schema.md` §Bounds (`gist.characters`), `design/kiro-gaps.md`, `FINDINGS.md` §"Owed work",
`README.md`'s kiro passages, the M40-5 brief for layout, `zikaron/harness/{spec,detect}.py`,
`zikaron/hook/{push,spawn_warm,main,tripwire,envelope,limits,write_policy}.py`,
`zikaron/mcp/connection.py`, `zikaron/knowledge/client.py`,
`zikaron/install/{entries,writer,ownership,harness,main}.py`, `tests/{test_harness_table,
test_install_limits,conftest}.py`, `.kiro/agents/`.
**Round 4 verified applied:** findings 1–12 as the brief for this round describes. The brief's citable
claims I could check directly hold: the render-fit remedy is in `FINDINGS.md` §"Owed work" (lines
185–190); probe §9 now records the 330 s call; probe §2 quotes the upgrader's three rule sets and says
the `skill` rule's V2 source is not visible; `health()` is the one unlabelled primitive
(`architecture.md` line 150); `_parse_model_ids` fails closed (`harness.py` line 106). Each "probe §N"
citation was checked against the numbered result; all say what the brief says.

### Summary judgment

The brief is buildable: the relay mechanism is sound and each of its joints is cited to a result that
records it, the three profile shapes are now predicates a builder can implement, the `skill` rule has
its measured source and its unknown stated, and the layout matches M40-5's. What remains is three
places where the brief states an outcome without the thing that would make it checkable: the kiro
half of the rewritten per-harness proof is unspecified and its figure is "roughly"; the owed remedy's
trigger — "if a truncated push is ever seen" — has no observer, since the probe says the cut is marked
to the model alone; and one shipped README claim about `--require-mcp-startup` on an interactive
launch is sourced to neither note, against the brief's own rule for kiro facts. Each is a sentence or
one assertion. No blocker.

### Findings

1. **[IMPROVEMENT] The kiro half of the per-harness block proof is unspecified, and its one figure
   is "roughly".** Item 13, lines 7956–7968: *"The derivation is restated per harness … under kiro a
   block fits only while its five gists average under roughly 400 characters"* and
   *"`tests/test_install_limits.py` … is rewritten for the per-harness proof."* Today
   `test_a_worst_case_block_fits_every_supported_harnesss_injection_budget` asserts the 6,097-unit
   block fits `KIRO`, which goes red at 3,000 — so the kiro leg has to assert something else, and the
   brief does not say what. A builder can satisfy "rewritten" by dropping `KIRO` from that loop, which
   proves nothing for kiro, and `harness.md` §"Injection budgets" then carries "roughly 400" with no
   test reading it — the hand-carried-figure class `schema.md`'s own row warns about. The figure is
   derivable: the five-superseded-row framing is 6,097 − 5 × 1,024 = 977 units, so
   `(3,000 − 977) // 5` = 404.
   **Fix:** state the kiro assertion: *"the framing of a five-row block, measured from `block.render`
   as the schema test does, leaves `(KIRO.injection_budget − framing) // 5` units per gist; the test
   asserts a block of five gists at that length fits and at one more does not, and reads the figure
   from `harness.md` §'Injection budgets' the way `_STATED_WORST_CASE` reads `schema.md`."* Write
   404, not "roughly 400", in the brief and the section.

2. **[IMPROVEMENT] "To be built if a truncated push is ever seen" names a trigger nothing can
   observe.** Item 13, line 7966, and `FINDINGS.md` lines 185–190. Probe §21: *"The truncation is
   marked to the model and to no one else. The event stream carries only the hook's
   `status: completed`."* `push.run` never calls `exceeds_injection_budget` on the surface text (the
   only caller is `write_policy.read_policy`, line 310), so an overrun leaves no `hook.log` line, no
   store row and no stream event; the only witness is the model choosing to mention `...[truncated]`.
   The owed item is therefore gated on an event that can occur repeatedly without being seen.
   **Fix, the minimal form:** in item 13, have the hook write one closed-vocabulary `hook.log` line
   (`push_oversize`, beside `write_policy_override_oversize`) when `spec.exceeds_injection_budget`
   is true of the text `surface_once` returned, printing it unchanged — the method already exists, it
   adds no import, and it costs one UTF-16 encode of ~2 KB per push. Then the owed entry's trigger is
   a grep. If the operator would rather not touch `push.py` here, state the honest trigger instead —
   *"if the model reports `...[truncated]` or an operator reads one in a transcript"* — so the entry
   does not read as monitored.

3. **[IMPROVEMENT] The interactive `--require-mcp-startup` clause is a shipped claim sourced to
   neither note.** Item 8, lines 7884–7886: the install report and `README.md` say *"a headless run
   needs `--require-mcp-startup`, and so may an interactive run whose first prompt is given on the
   command line."* Probe §8 measured the flag headless only; migration §8 and §10 list it among
   *headless* flags (exit 3) and document nothing about an interactive launch accepting it. Item 9's
   own rule — *"A fact neither measured nor documented under V3 says so"* — applies to the README
   line as much as to a table cell, and a user who follows it into a flag the TUI refuses gets a
   usage error for a sentence we wrote.
   **Fix:** either add one launch to done-when 5 — `kiro-cli chat --v3 --require-mcp-startup
   "<prompt>"` from the terminal, recording whether the flag is accepted and whether the prompt's
   turn had the tools — and let the README sentence follow the result; or write the README clause
   as *"whether `--require-mcp-startup` is accepted on an interactive launch is unmeasured"* and
   leave only the headless half as advice.

4. **[NITPICK]** Item 4, lines 7835–7836: *"the relay's directory is either derived inside the seam
   or passed to it by each caller"* leaves the writer (`hook`) and the reader (`detect`, via the MCP
   client) free to derive it in two places. Say *"passed by each caller, from `paths.runtime_dir`"* —
   one function, already imported by both clients — so the two cannot name different directories.

5. **[NITPICK]** Item 4's reader (lines 7833–7834) reads the file for its own `getppid()`, and
   `zikaron knowledge` (`ServiceConnection`, `kind = cli`) goes through the same ladder. If done-when
   5's `echo $KIRO_SESSION_ID` leg prints nothing, that client's parent is the agent's shell, which
   no hook writes for — so it mints, as the brief says — unless the shell's pid is a dead agent
   server's not yet swept, in which case it adopts a dead session's label (and the `SessionStart`
   sweep keeps that file, since `os.kill` says the pid is alive). Unlikely, and a `cli` event is the
   cheapest kind to mislabel; state it as a known limit in `harness.md` beside the one-TUI-two-sessions
   case rather than building for it.

6. **[NITPICK]** Item 1, lines 7708–7709: the report says V3 must be the engine; say what fails when
   it is not, since on 2.35.1 the default launch is V2 and the shipped consolidator then has no
   `allowedTools` — *"under V2 the consolidator's and documenter's first tool call prompts with nobody
   to answer"* — so the user who forgot `--v3` can read the failure. One sentence; nothing tests V2.

7. **[NITPICK]** Item 3, lines 7732–7735: *"`allowedTools` present"* — say *present and not
   `null`*, since `_is_unset` already reads `null` as absent and a profile with `"allowedTools":
   null` and no `permissions` would otherwise be refused with no remedy. And line 7763: `agent
   create` writes `"tools": ["*"]` (probe §22), which selects every tool; adding `@zikaron` beside it
   is harmless but the note *"without it Zikaron's tools are simply absent"* is then false of that
   file — skip the add, or the note, when `*` is present.

8. **[NITPICK]** Item 13, lines 7952–7954: with `BudgetUnit` deleted, `test_harness_table.py`'s
   `_quantity` has no enum to read unit words from and `test_injection_budget_value_and_unit` has no
   `budget_unit` to compare; say the parser reads the literal word `characters`, and that the kiro
   cell must carry no other digit — not `V3`, not `2.35.1`, not `§21` outside the stripped
   `§` form — or the one-number rule reddens it.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-10-28

**Artifact:** `design/build-plan.md` §"M41" and §"M41-1" (lines 7615–8130), re-read whole.
**Evidence re-read:** `research/kiro-v3-probe.md` (all 24 results, "Not measured here", "Re-deriving
this"), `research/kiro-cli-v3-migration.md` (whole), `design/harness.md` (whole),
`design/architecture.md` §"The request envelope" through §"Both clients resolve the same label",
§"Degraded modes", §"The install contract" (the override paragraph), `design/overview.md`
D31/D32/D34, `design/schema.md` §Bounds (`gist.characters`), `design/kiro-gaps.md`,
`design/retrieval.md`'s push passages, `README.md`'s kiro passages, `zikaron/harness/{spec,detect}.py`,
`zikaron/hook/{push,spawn_warm,tripwire,envelope,failure,limits,write_policy}.py`,
`zikaron/mcp/connection.py`, `zikaron/install/{entries,writer,ownership,harness}.py`,
`zikaron/service/{paths,security}.py`, `tests/{test_harness_table,test_install_limits,
test_install_harness,test_hook_push}.py`.
**Round 5 verified applied:** findings 1–8 as the brief for this round describes. Checked directly:
6,097 − 5 × 1,024 = 977 and (3,000 − 977) // 5 = 404, with 977 + 5 × 404 = 2,997 and
977 + 5 × 405 = 3,002; probe §5 now records a `node` per launch under its own `kiro-cli-chat` with no
pid recurring; `paths.runtime_dir` is the one function (`paths.py:88`) and `ensure_runtime_dir`
creates an absent directory or vets an existing one; `writer._is_owned` compares the **unquoted
single-token** command, so `exec '<path>'` splits to two words and item 5's prefix-stripping is needed
exactly as stated; `ServiceConnection.__init__` resolves the label at construction today
(`connection.py:206`), which item 4 moves. Each "probe §N" citation was checked against the numbered
result; all say what the brief says.

### Summary judgment

The brief is buildable and I would ship it. Every load-bearing joint is cited to a result that records
it, the three profile shapes are predicates a builder can implement, the budget change carries its
per-harness proof and the figure a test reads, the overrun is now observable in `hook.log`, and each
interactive leg of done-when 5 names what it decides. What remains is wording a builder could misread
for a sentence or two, and one invariant clause whose mutation has nothing to apply to; none changes
what ships, and done-when 4 catches the one that could.

### Findings

1. **[NITPICK]** Item 1, lines 7703–7705, and the floor invariant, lines 8006–8008: *"over the leading
   `N.N.N`"*, with hermetic cases written as bare versions (`2.4.0`, `2.35.0`, `2.35.1`, `3.0.0-rc1`)
   while the real output is `kiro-cli 2.35.1` (probe §20) — only the `kiro-cli (dev)` case carries the
   prefix. A parser anchored at the output's start passes those cases and refuses every real binary;
   done-when 4's live run catches it, but the hermetic test should not be green for the wrong reason.
   **Fix:** write the cases in the real shape (`kiro-cli 2.4.0` … `kiro-cli 3.0.0-rc1`) and *"the
   first `N.N.N` in the output, after the binary's name"*.

2. **[NITPICK]** Item 2, lines 7712–7713: *"carry `tools`, `permissions.rules`, `mcpServers`, `model`
   and `prompt`, and no `allowedTools`"* reads as the whole field set, and both builders also write
   `name` and `description` today (`entries.py:463–464`, `557–558`); V3 selects a subagent by
   `description` (migration §4) and spawns it by name (probe §11). **Fix:** *"carry what they carry
   today less `allowedTools`, plus `permissions.rules`"*.

3. **[NITPICK]** Invariant lines 8028–8030: *"`push_oversize` is in `hook.log`'s closed vocabulary
   (left out of it)"* names a mutation with nothing to apply it to. No list enumerates the vocabulary:
   `failure.REJECTION_KINDS` is pinned to `ErrorCode` wire names (`test_hook_push.py:868`), the
   override kinds and `session_env_mismatch` are per-module constants, and `architecture.md` names
   none of the override kinds literally (§"The install contract" says only *"recorded in
   `hook.log`"*). Done-when 1 cannot be met for that clause as written. **Fix:** *"written from a
   module constant beside `OVERRIDE_OVERSIZE`, and named in `architecture.md` §'Degraded modes' beside
   `session_env_mismatch`"*, with no mutation — or drop the clause.

4. **[NITPICK]** Item 3, line 7739: the universal predicate says *"both `allowedTools` and
   `permissions`"* without the *"present and not `null`"* reading line 7735 gives the V2-only one.
   `allowedTools: null` beside `permissions` should fall to V3-only rather than have `@zikaron`
   written into a null list. One clause: *"`allowedTools` as read above"*.

5. **[NITPICK]** Item 3, line 7770: *"The `--no-trust-tools` note names that rule rather than
   `allowedTools`"* — the flag now withholds the `skill` rule too (line 7783), so the note should name
   both and say what the second costs: either skill asks before loading interactively, and neither
   loads headless (probe §24).

6. **[NITPICK]** Item 4, lines 7810–7811: say the relay is written only when the payload's
   `session_id` is a non-empty string. The payload is untrusted JSON — `is_subagent_session` types it
   `object` for that reason (`envelope.py:82`) — and a malformed payload should leave the previous
   label in place rather than write `None` into the file.

7. **[NITPICK]** Done-when 2's seeds, line 8066: *"The injected block placed before the user
   message"* — `design/retrieval.md:759` states the other half of that row, kiro's *"follow requests
   found in it"* wrapper, which probe §6 also refutes, and `harness.md`'s preamble (line 7) flags
   `retrieval.md`'s push section as the one never annotated. Add *"and its wrapper"* to the seed, or
   `retrieval.md`'s push section to the normative list.

8. **[NITPICK]** Probe §10 lists three models and the shipped pin `claude-sonnet-5` is not among them,
   yet §11 logged `modelId: claude-sonnet-5` and results 4 and 8 installed through the `--list-models`
   check. Item 12's install depends on that pin passing the check, so §10 should quote the list whole
   or say the three are the 5.5 subset.

VERDICT: APPROVED
