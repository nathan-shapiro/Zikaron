# M40-4 — the grep reminder: brief review

Artifact: `design/build-plan.md` §"M40-4 — A grep through a documented module, by an agent that
forgot its documents" (lines 6998–7122 at round 1).

## Round 1 — 2026-10-20

**Summary judgment.** The brief is grounded: every claim it makes about `claude_hooks_value`,
`_plan_settings`, `_refuse_differing_hook_groups`, `connect_once`, `read_grep`, `ServiceContext`
and the cited design sections is true of the tree as it stands, and the shape — service decides,
hook stays stdlib-only and never starts a service, `agent_type` excludes the two code-knowledge
agents, a time throttle reset by `memory_surface` — is the right one. It is not yet executable
without guessing in four places that decide what ships: whether a `grep` that matches nothing
(exit 1) fires `PostToolUse` at all, which session id the throttle keys on inside a subagent and
whether the reminder path inherits the push path's session comparison and tripwire, how the `if`
filter coexists with the `Grep`/`Glob` arm (one group or two, and what the per-program ownership
rule then compares), and the root module's corpus name, which the brief's own matching rule
misses. The cost of firing on every search in every memory install — documented module or not —
is unbudgeted, and two normative sections the merge rule rewrites are missing from the list.

### Findings

1. **[BLOCKER] A `grep` that matches nothing exits 1, and the brief does not say which event
   that fires.** Item 3 (lines 7044–7059) and probe 2 (lines 7024–7029) treat every `Bash` search
   as a `PostToolUse`. `grep`, `egrep`, `fgrep` and `rg` all exit 1 on no match — half of all
   searches an agent runs, and the half where a lead is worth most, since its own search just
   came back empty. `research/claude-code-tool-hooks-docs.md` §4 says `PostToolUse` fires "after
   a tool call succeeds" and a failure fires `PostToolUseFailure`; nothing in `research/` records
   whether Claude Code reports a non-zero `Bash` exit as a failed call (`claude-code-tool-hook-probe.md`
   has no such row). If it does, the `Bash` arm never fires on a miss. The `Grep` tool is
   unaffected — "No matches found" is a success result. **Fix:** add a third probe to item 1: a
   `Bash` `grep` that matches nothing, under a logging hook registered on both `PostToolUse` and
   `PostToolUseFailure`, recording which fires and whether the failure payload carries `cwd`,
   `tool_input` and `agent_type` alike. State the consequence in item 2: where a non-zero exit
   fires `PostToolUseFailure`, the `Bash` arm is registered on both triggers with the same
   matcher, `if` and command, `HarnessSpec` carries both names, `_trigger_vocabulary` maps both
   to the one new event, and the hook treats them identically (it never reads the result). Add
   to the invariants: a `Bash` search that exits 1 is reminded as one that exits 0; and to
   done-when 2: the live `Bash` grep is one that matches nothing.

2. **[IMPROVEMENT] Say which session id the throttle keys on, and that the reminder path makes
   no session comparison.** Item 4 (lines 7062–7064) keys the throttle "for each session label";
   probe 1 (lines 7020–7023) checks the payload's `session_id` is "equal to its session's". But
   the label the service resolves comes from the envelope, which the hook builds from the
   **environment's** `CLAUDE_CODE_SESSION_ID` (`push.run`: `detect.session_label(spec)` →
   `envelope.build_envelope`), not from the payload. Inside a subagent's hook process the
   environment value is unmeasured for tool events. If it differs from the parent's — or is
   absent, giving the bootstrap form — a subagent's reminders key on a label `memory_surface`
   never resets. Worse, a builder taking `push.run` as the template inherits
   `envelope.is_subagent_session` and `tripwire.record_if_misdetected`: a subagent payload whose
   `session_id` differs from the environment's would then write a `session_env_mismatch` line to
   `hook.log` on every subagent search, polluting the closed vocabulary that file exists to keep.
   **Fix:** in probe 1, record both the payload's `session_id` and the hook process's
   `CLAUDE_CODE_SESSION_ID` inside a subagent's `PostToolUse`, and the parent's; in item 4, say
   the key is the envelope's session label resolved as every hook call's is; in item 5, say
   `agent_type` is this path's only subagent test — it compares no session ids and never calls
   the tripwire — and add "a payload `session_id` differing from the environment's is neither
   suppressed nor logged" to the invariants.

3. **[IMPROVEMENT] The root module's corpus is named `code-knowledge`, with no `/<module>`.**
   Item 3's last sentence (lines 7058–7059) ranges M over corpora named `code-knowledge/<module>`.
   `design/code-knowledge.md` §5.2 step 6 (line 585) names the root module's corpus
   `code-knowledge`, so a project whose documented module is `.` is never reminded, by the brief's
   own rule. **Fix:** "…or the bare name `code-knowledge`, which is the root module and is
   reached by every search inside the project", and add "the root module" to the matching
   table's invariants.

4. **[IMPROVEMENT] Budget the cost in every memory install, documented module or not.** Because
   the hook may never read the registry (`architecture.md` §"Degraded modes": never a reader of
   the store), item 4's design starts a hook process, connects, runs `health()` and
   `knowledge_remind`, and writes a `call` row on **every** `Grep`, `Glob` and filter-passing
   `Bash` call in every project with the memory component — including the many with no
   code-knowledge corpus at all, where the answer is always `null`. The brief's own figure of ~70
   `Grep` calls per treatment run is ~70 hook starts, ~140 round trips and ~70 `event` rows per
   run, in every project, and done-when 2 measures only a project that has a documented module.
   Nothing in the brief says this. **Fix:** state the per-search cost as a property of the design
   (one process start, two round trips, one `call` row, in every memory install), have
   done-when 2 report the hook's wall time in a project with **no** corpus as well, and either
   adopt or decline, with the reason, the cheap short-circuit: before connecting, the hook
   `stat`s `.zikaron/knowledge/` — the directory every corpus database lives in
   (`schema.md` §registry: `.zikaron/knowledge/<id>.db`) — and is silent when it is absent or
   holds no `.db`. That is a directory listing, not a store read, and it costs the no-corpus
   project only the process start. The `call` rows are also the one instrument that will show
   whether the hook fires at all (finding 7), so say that too.

5. **[IMPROVEMENT] The `if` filter and the `Grep`/`Glob` arm cannot share one group as written,
   and the ownership rule must survive two groups of ours on one trigger.** Item 1's second probe
   and item 2 (lines 7024–7043) describe one memory group on `PostToolUse`. The `if` field takes
   permission-rule syntax (`research/claude-code-tool-hooks-docs.md` §6); a group whose matcher
   is `Grep|Glob|Bash` and whose `if` is `Bash(grep *)` never starts the hook for a `Grep` call,
   because no `Bash(...)` rule matches it. So memory writes either two groups on `PostToolUse` —
   `Grep|Glob` without `if`, `Bash` with it — or one whose `if` also names `Grep` and `Glob`,
   whichever shape the field accepts (a string or a list; on the inner entry or on the group),
   which probe 2 should record. Either way item 2's new rule — "compares, replaces and reports
   only the groups running a program it writes there" — must compare **per program**, not per
   trigger: today's `_is_ours` flattens a trigger's expected groups into one program list
   (`targets.py` lines 990–1000), so with two memory groups on `PostToolUse` an existing one
   compares unequal to the pair and is refused as another install's. **Fix:** say the group shape
   is the probe's to settle, that memory may write two groups on `PostToolUse` both running
   `zikaron-hook`, and that ownership is decided group by group against our group running the
   same program; add "two memory groups on one trigger re-install unchanged" to the invariants.

6. **[IMPROVEMENT] Two normative sections the merge rule rewrites are missing, and five counts
   this change moves are not named.** The sentence item 2 changes — a settings hook group's
   programs "as a list equal to ours rather than merely containing it" — is stated in
   `design/harness.md` §"The installer's two targets" (lines 596–602) and
   `design/architecture.md` §"The install contract" (lines 2529–2533); neither is in the brief's
   normative list (lines 7000–7004), which names §"The table", §"What a Claude Code install
   writes" and §"Service RPC surface". The brief catches architecture's "Six methods" (line 7062)
   but not: `design/harness.md` line 95 "many-to-three"; `zikaron/harness/spec.py` `HookEvent`'s
   docstring "many-to-three"; `zikaron/hook/main.py` line 15 "the three events";
   `zikaron/install/entries.py` line 84 "Claude Code's three triggers"; `README.md` line 365
   "three hooks"; and `tests/test_install_targets.py` line 1389 `"two servers and three hooks"`.
   **Fix:** add both sections to the normative list, and a sentence in item 8 naming the counts
   and requiring each be restated as its predicate (`CLAUDE.md` §"How this project works") rather
   than as the next number — the harness table's own paragraph records what happened the last
   time that count was appended to instead of moved.

7. **[IMPROVEMENT] "As the push hook's are" is the wrong model for failure, and nothing says how
   anyone would learn the reminder stopped firing.** Item 7 (lines 7084–7085): the push hook's
   failures are not silent — `push._degrade` writes a `hook.log` line and returns a model-facing
   relay. The silent-allow model is the guards' (`design/guards.md` §6). The brief must also pick
   whether a failing call writes `hook.log`: a reminder that breaks silently — the `if` filter
   wrong, the matcher wrong, `additionalContext` undelivered on some surface (§2's "fragile
   half") — is the working-looking-inert failure this corpus keeps paying for, and after
   done-when 2's one session nothing would ever say so. **Fix:** cite `design/guards.md` §6; say a
   serving service that answers an error, or a transport failure to one, writes one `hook.log`
   line in the closed vocabulary while no-service and not-a-search write none; and name the
   instrument: `call` rows with `method = 'knowledge_remind'` per session, with the row's
   `detail` recording whether a line was returned and how many modules the search reached — the
   only data the 300 s interval could later be tuned from, since no base rate precedes it, and a
   query `experiments/m33_call_log_queries.py` can carry.

8. **[IMPROVEMENT] Name the hook's own deadline and the entry's `timeout`, and correct the
   fence.** Item 7 says "within an explicit `timeout` on the entry" with no value, and nothing
   bounds the `knowledge_remind` exchange itself. `HOOK_TIMEOUT_SECONDS` is 10 s, sized for a
   cold start this path never makes; `connect._CONNECT_TIMEOUT_SECONDS` (0.3 s) covers only
   connect and `health()`. A wedged service — the case M35 was built around — would then stall
   every search for the full entry timeout, and the fence's "**Not** … anything that delays the
   search" (line 7118) is false by up to 10 s a call. **Fix:** state a short budget for the whole
   exchange (the push's running-service `_DEADLINE_SECONDS` of 2 s is the ceiling; 1 s is
   plenty for a registry read) and the entry's `timeout` (the guard's 10 s constant or the
   hook's — say which); and reword the fence: a `PostToolUse` hook runs after the search and
   delays the turn by its wall time, which done-when 2 measures.

9. **[IMPROVEMENT] Probe 2's failure branch names no decision, and done-when 2 exercises one arm.**
   Item 1 (lines 7027–7029): if the filter does not hold, the cost "is measured and reported
   before the build goes on" — FINDINGS §"How the next review should be briefed" asks what changes
   at each outcome; here the honest answer is a decision, since a ~100 ms process on every `Bash`
   call in every memory install (two, under `both`, beside the guard) is a cost the operator may
   not want for the `Bash` arm alone. Done-when 2 (lines 7111–7113) says "a grep there", which
   does not say whether the `Grep` tool or a `Bash` grep ran, and the two arms rest on different
   mechanisms (matcher vs `if` filter plus parser). **Fix:** "if the filter does not hold, the
   `Bash` arm ships only on the operator's say-so, given the measured cost"; and done-when 2 shows
   the reminder after a `Grep` tool call **and** after a `Bash` grep (one that matches nothing,
   per finding 1), and none after a second of either within the interval.

10. **[IMPROVEMENT] `git grep` is at least as common an agent idiom as `rg`.** Item 3 names
    `grep`, `egrep`, `fgrep` and `rg`. `git grep -n foo` from the project root searches every
    tracked file and names every module; it misses the `if` patterns and the command-word rule
    alike. One more row — command word `git` whose first non-option word is `grep`, pathspecs
    after `--` or after the pattern, else the `cwd` — and one more pattern, `Bash(git grep *)`.
    Decline with the reason if the operator would rather keep the set small.

11. **[NITPICK] Operand and path rules worth one sentence each, so the known misses are
    recorded rather than discovered.** `--` ends options (today `_read_long` reads it as an
    unknown long option, so `grep -- -A file` consumes `file`); a `~`-prefixed operand is
    unexpanded and so never matches; comparison is lexical on normalised paths with no filesystem
    touch, so a glob operand (`src/*.py`) still lies under `src` and the path need not exist;
    `find … -exec grep … {} +` and `… | xargs grep` are misses, since `{}` is no path and a piped
    grep "reads its input". Put the misses in `design/code-knowledge.md` §6's text or §8's gaps.

12. **[NITPICK] Bound the line from the root.** Item 6 names "each corpus the search reached"; a
    root search in a project with many documented modules lists them all, in every reminder,
    persisted in the transcript. Name up to a handful and say how many more `knowledge_list`
    holds. Likewise say a corpus is named whatever its state — never built, `indexing`,
    `reindex_required` — since checking state would open every corpus database per search; the
    search itself reports the state.

13. **[NITPICK] The tool's spelling in the line.** Under Claude Code the model sees
    `mcp__zikaron__zikaron_knowledge_search` (`design/harness.md` §"Tool names are a substitution
    point"). The push block already ships the bare `zikaron_memory_fetch` from the service and the
    agent resolves it (`core/retrieval/block.py` line 70), so the bare name has precedent; say
    which the line uses and why, since the service that builds it knows no harness while the hook
    does.

14. **[NITPICK] Two invariants the list implies but does not state.** `knowledge_remind` is
    answered while the model is still loading (`model_loaded=False`), since it touches no
    encoder — a D22-adjacent property worth pinning; and the new `HookEvent` maps to
    `ADDITIONAL_CONTEXT` in `CHANNELS` with `hookEventName` echoing the trigger that fired,
    which is what `_emit` already does and a test should hold for the new event.

15. **[NITPICK] The evaluation's install.** `experiments/m40_eval.py`'s `prepare` installs into
    the Warp clone; a re-install after M40-4 lands puts the reminder into the treatment arm the
    slice ran without. Say in the brief whether the repeats carry it, so `research/m40-evaluation.md`
    §7 records the difference rather than discovering it.

VERDICT: NEEDS_CHANGES

### Author's response to round 1

- **1, accepted**: a third probe under a logging hook on both triggers; item 2 registers the `Bash`
  arm on `PostToolUseFailure` too where it fires; an invariant and done-when 2 follow.
- **2, accepted**: probe 1 records both ids in a subagent and its parent; item 4 keys on the
  envelope's label; item 5 states `agent_type` is the only subagent test, no tripwire; invariant
  added.
- **3, accepted**: the root module's bare `code-knowledge` corpus, and its invariant.
- **4, accepted**, the short-circuit adopted: the hook lists `.zikaron/knowledge/` before
  connecting; the per-search cost is stated in item 4; done-when 2 measures a no-corpus project.
- **5, accepted**: probe 2 records the field's shape and so the group count; ownership is judged
  per program; the two-groups re-install invariant added.
- **6, accepted**: both sections are in the normative list, and item 8 names each count to be
  restated as its predicate.
- **7, accepted in part.** `design/guards.md` §6 is the model cited, and a serving service's error
  or a transport failure after connecting writes one `hook.log` line. **Declined: recording in the
  `call` row's `detail` whether a line was returned and how many modules were reached** — that is a
  change to the `call` kind's per-kind shape, which `design/schema.md`'s table and
  `tests/test_event_kinds.py` hold verbatim, for an instrument the harness's transcripts already
  are, since they carry what the agent did after each reminder as well. Done-when 2 now checks
  that the transcript records the line.
- **8, accepted**: 1 s for the whole exchange under `HOOK_TIMEOUT_SECONDS`; the fence reworded.
- **9, accepted**: the `Bash` arm needs the operator's say-so if the filter fails; done-when 2
  exercises both arms.
- **10, declined on measurement**: `git grep` appears four times in this repository's transcripts
  since 2026-10-01, subagents included, and never in LeibaTrader's, against 1,542 main-session
  `grep`s (`research/m40-4-search-tool-use.md`); it is listed among the known misses.
- **11, accepted**: `--`, `~`, lexical comparison, and the misses entered in
  `design/code-knowledge.md` §8.
- **12, accepted**: up to five corpora and a count of the rest; named whatever their state.
- **13, accepted**: the bare name, on the push block's precedent.
- **14, accepted**: both invariants.
- **15, accepted**: item 8 says the copies are not re-installed and that the choice before the
  repeats must cover `zikaron/hook` and `zikaron/service`.

Also changed, not from a finding: item 2 says why both arms are needed, citing the new
`research/m40-4-search-tool-use.md` — a main session in this Claude Code build has no `Grep` or
`Glob` tool, while subagents granted them without `Bash` use nothing else.

## Round 2 — 2026-10-20

**Summary judgment.** Round 1's dispositions are applied as recorded, and every claim the brief
now makes about the code holds: `read_grep` keeps one operand and reads `--` as an unknown long
option; `claude_hooks_value` assigns one group per trigger so the guards' loop overwrites a memory
`PostToolUse` group; `_is_ours` flattens a trigger's expected groups into one program list;
`_refuse_differing_hook_groups` judges every Zikaron group on a trigger the install writes; the
guard parser is stdlib-only under `tests/test_hook_stdlib_only.py`; `_emit` echoes the trigger;
`ServiceContext.spawned_builds` is where an in-memory table would sit; both timeouts are 10 s; the
six counts stand where item 8 names them. What is left is narrower than round 1 and none of it is a
design change: one probe-1 outcome has no stated consequence and its failure mode is a reminder on
every search; done-when 2 asks for a `Grep` tool call the brief's own evidence says the main session
cannot make; a reminder failure in `hook.log` is indistinguishable from a push failure; a README
sentence becomes false; the section that states the no-store-read rule is not in the normative
list; and the outcome quantity the transcripts would later yield is unnamed.

### Findings

1. **[IMPROVEMENT] The one probe-1 outcome with no consequence turns the throttle off.** Item 1
   (lines 7022–7026) records the hook process's `CLAUDE_CODE_SESSION_ID` inside a subagent
   "since item 4's throttle keys on the label the hook resolves from them", and item 4 (lines
   7088–7089) keys on "the envelope's, resolved as every hook call resolves it". If that variable
   is absent or empty in a subagent's hook process, `detect.session_label` answers `None`, the
   envelope goes out in the bootstrap form, and `service/envelope.py`'s `resolve` **mints a fresh
   `zk-` label per request** — and every hook invocation is a fresh process, so no two of a
   subagent's searches share a key: the throttle never repeats, every search is reminded, and
   each files a `call` row under a label of its own. The heaviest searchers in the corpus are
   exactly such subagents (3,183 `Grep`/`Glob` calls by memory-reviewer in this repository since
   2026-10-01, `research/m40-4-search-tool-use.md`). The `agent_type`-absent branch says "the
   build stops"; this branch says nothing. **Fix:** one sentence in item 4 — "a hook that
   resolves no label sends the payload's `session_id` as its label, which is the value the
   variable carries wherever both exist under this harness (`envelope.is_subagent_session`'s
   docstring), and asks for nothing when the payload has none either; the service never keys a
   reminder on a minted label" — and the matching invariant cell under **The throttle**. That
   stays inside item 5's rule: it is a fallback, not a comparison, and the tripwire is still never
   called.

2. **[IMPROVEMENT] Done-when 2's `Grep` tool call cannot be made where the brief says to make it.**
   Done-when 2 (lines 7165–7169) wants "the reminder after a `Grep` tool call there and after a
   `Bash` `grep`" in "one live session"; item 2 (lines 7046–7049) and the research note say a main
   session in this build has no `Grep` or `Glob` tool. So the `Grep` half can only come from a
   subagent whose definition grants `Grep` — which is also the only way probe 1 can be run — or
   from a headless `-p` with `--allowedTools Grep`, and the line is then looked for in the
   subagent's transcript under `*/subagents/*.jsonl`, not the session's. A subagent also makes the
   throttle test sharper: the second search, from the other agent, within the interval, is the
   shared-key case item 4 relies on. **Fix:** say in done-when 2 that the `Grep` call is a
   subagent's (naming its grant) or a headless allowlist's, and which transcript records the line.

3. **[IMPROVEMENT] A reminder failure in `hook.log` reads as a push failure.** Item 7 (lines
   7121–7124) has a serving service's error or a transport failure after connecting write "one
   `hook.log` line in that file's closed vocabulary". `hook/failure.py`'s line is
   `<timestamp> <kind> [detail] [code]`, and the vocabulary is the push path's — `transport`,
   `rejected_<code>`, the store codes. A burst of `transport` lines after a search-heavy turn
   would send an operator to the push path, where nothing is wrong; and the one existing reader
   of that file, `architecture.md` §Paths' row for `hook.log`, says it holds "a fixed failure-kind
   label and an error code" plus `starting`'s one word. **Fix:** item 7 states that the reminder
   path's line carries a fixed second word, `remind`, in the position `starting` uses for its
   detail — one word, no path, no corpus name, so the row's secrets claim stands — and that §Paths
   and §"Degraded modes" name it; add "a reminder failure's line is told from a push's" to the
   invariant at lines 7151–7152.

4. **[IMPROVEMENT] `README.md` line 772 becomes false and is not in item 8.** "Nothing tells your
   agent to search it unprompted; say so in your prompt" is the README's mirror of
   `design/code-knowledge.md` §6's sentence, which the normative list rewrites; item 8 (lines
   7125–7128) names only the README's "account of what an install writes". After M40-4, under
   Claude Code, a search of a documented module does tell it — once a turn and at most once per
   interval — while the prompt instruction stays the way to make a reader *use* the documents.
   Nothing in the gate reads that sentence. **Fix:** add the README's "Using it" paragraph to item
   8, with the predicate it should now state (what the reminder does and does not do, and that
   kiro gets none, per the kiro-gaps row).

5. **[IMPROVEMENT] The section that states the no-store-read rule is not in the normative list.**
   The list (lines 7000–7005) names §Components for "what the hook does", but the rule item 4
   leans on — a directory listing is not a store read — is stated nowhere, and the section a
   reader will hold `os.listdir(.zikaron/knowledge)` against is `design/architecture.md`
   §"Degraded modes", whose heading says the hook "never reads the store itself" and whose body
   says "never a reader of the store, under any failure" and "there is no case where the hook
   proceeds". That section also owns the five-step start-if-absent the reminder path deliberately
   skips (item 4, lines 7092–7095). **Fix:** add §"Degraded modes" to the normative list with the
   two sentences it owes: the reminder path's own order (`agent_type`, the listing, connect only
   if serving, one request, exit 0, never a start), and that listing a directory for the presence
   of corpus files is outside the no-read rule, which is about opening a database.

6. **[IMPROVEMENT] Name the quantity the transcripts would later answer, not only that they record
   the line.** Done-when 2 (lines 7168–7169) says the transcript recording the line is "what
   reminders delivered would later be counted from", and round 1's instrument was declined for
   the transcripts on the ground that they "carry what the agent did after each reminder as
   well". Then say what that is: the rate at which a `zikaron_knowledge_search` naming a reminded
   corpus follows within the next few tool calls, against the same window after an unreminded
   search of the same module — the one number that says the line earns its tokens, and the shape
   `FINDINGS.md` §"Owed work"'s decay item already proposes. Not a bar, and not the base rate the
   operator declined; one sentence in done-when 2 or item 8 naming the quantity and that the
   `research/` note carries the command, as `research/m40-4-search-tool-use.md` §Re-derive does.

7. **[NITPICK] Item 6 should ask for a factual line that names its origin.** The documentation's
   note that text framed as an out-of-band instruction can trip the model's injection defences
   (`research/claude-code-tool-hooks-docs.md` §3.3) is what the guards answered with start text
   saying where the nudge comes from (`design/guards.md` §5); this brief's fence rules that route
   out. One clause in item 6: the line is a statement, not an instruction, and opens by naming the
   project's hook — wording still memory-reviewer's.

8. **[NITPICK] Two directories the brief leaves to be inferred.** Item 4 (line 7092) lists
   "`.zikaron/knowledge/`" without saying whose: the store's, as `HarnessSpec.store_scope_dir`
   resolves it from `CLAUDE_PROJECT_DIR`, never the payload's `cwd`, which wanders — the hook
   already has both through `_scope_dir`. And item 3 compares module paths "relative to the
   project's directory" without saying which form the service holds it in; the hook's absolute
   paths come from the payload's `cwd`, so a symlinked project variable against a real-path `cwd`
   is a lexical miss. State the first; the second may go to §8's misses, under the operator's
   edge-case line.

9. **[NITPICK] Three invariant cells and one probe detail.** The cap in item 6 — six modules
   reached from the root name five and say one more; interval `0` reminds on every such search; a
   `grep` behind a wrapper or an assignment (`timeout 5 grep …`, `LC_ALL=C grep …`) is an `if`
   miss the parser would have caught, worth a line in §8's misses; and probe 3 should record
   whether the `if` filter holds on `PostToolUseFailure` too, since a filter honoured on one
   trigger and not the other starts the hook on every failing `Bash` call — a gate's red run
   included.

VERDICT: NEEDS_CHANGES

### Author's response to round 2

All nine accepted.

- **1**: item 4's fallback to the payload's `session_id`, nothing asked with neither, and the
  throttle's invariant cell. The comment it rests on is cited as a claim probe 1 checks for tool
  events, not as measured fact.
- **2**: done-when 2 runs in order: a main-session `Bash` miss reminds, a subagent's `Grep` within
  the interval does not, and a subagent's `Grep` after the next prompt does. Granting `Grep`
  without `Bash` is named, and so are both transcripts.
- **3**: the fixed word `remind`; §Paths and §"Degraded modes" name it; invariant updated.
- **4**: the README's "Using it" paragraph is in the normative list and item 8, with what it then
  says.
- **5**: §"Degraded modes" is in the normative list; item 7 gives the two sentences it owes.
- **6**: done-when 2 names the follow-on-search rate, with its command.
- **7**: item 6 asks for a statement that names its source, citing §3.3.
- **8**: the listing is the store's, by `HarnessSpec.store_scope_dir`; the symlinked project is
  among the known misses.
- **9**: the three invariant cells; the wrapper miss is conditional on what probe 2 finds; probe
  3 records the filter on `PostToolUseFailure`.

**Round 1's finding 10 reversed on the operator's direction** (2026-10-20: *"git grep actually I
want to support"*). Item 3 now reads `git grep`, measured on a scratch repository. With no
pathspec it searches the `cwd` and below; `-C <dir>` moves that directory; `:/` is the
repository's top; a miss exits 1. Probe 2 tests `Bash(git grep *)` and `Bash(git -C * grep *)`.
The matching table gains four `git grep` cells, and it is gone from the known misses.

## Round 3 — 2026-10-20

**Summary judgment.** Every round-2 disposition is applied as recorded, and the brief's claims
about the tree still hold: `claude_hooks_value` assigns one group per trigger and the guard loop
overwrites; `_is_ours` flattens a trigger's groups into one program list; `_refuse_differing_hook_groups`
judges every Zikaron group on a written trigger; `detect.session_label` and `envelope.resolve` behave
as item 4 says; `failure._format_line` has the slot the `remind` word goes in; `HOOK_TIMEOUT_SECONDS`
is 10; `research/claude-code-tool-hooks-docs.md` §3.3 line 89 carries the injection-defence note and
§6 the `if` field; `README.md` line 772 and the `architecture.md` sections exist as cited. What is left
is one design gap the brief's own evidence exposes — the throttle merges a subagent with its parent,
and a subagent's context is the one place the parent's reminder cannot be — plus three cheaper
improvements and four nitpicks. None of it changes the shape of what ships.

### Findings

1. **[IMPROVEMENT] The throttle key merges a subagent with its parent, so the `Grep`/`Glob` arm is
   suppressed for the agents it exists for.** Item 4 (lines 7101–7102) keys the time on the session
   label, and done-when 2 (lines 7200–7201) makes "none after a subagent's `Grep` within the
   interval" a pass criterion, calling it "the shared key item 4 relies on". The key *is* shared:
   a subagent's payload `session_id` is the parent's (`research/claude-code-harness-probe.md`
   lines 82–83) and its `CLAUDE_CODE_SESSION_ID` is inherited, so both resolve the parent's label.
   But a subagent starts with a fresh context — the corpus's own reason `SubagentStart` exists is
   that "a subagent would otherwise inherit Zikaron's tools having never seen the write policy at
   all" (`design/harness.md` §Subagents) — so the parent's reminder is not in it, and item 2 says
   the arm is needed *because* subagents without `Bash` search through `Grep`/`Glob` alone
   (3,183 such calls by memory-reviewer, `research/m40-4-search-tool-use.md`). Under the brief, a
   subagent spawned within 300 s of the parent's first search of the turn — the ordinary case, and
   most subagents live shorter than the interval — is never reminded, and done-when 2 would pass
   on exactly that. **Fix:** key the time on the label **and the payload's `agent_id`** — present
   with `agent_type` in every subagent tool event (`claude-code-tool-hooks-docs.md` §6 lines
   143–144), absent for the main session; probe 1 records it beside `agent_type` and that it is
   constant across two calls of one subagent. `memory_surface` clears the main session's entry,
   as now, and never fires for a subagent, which needs no reset: its first search reminds and its
   lifetime bounds the rest. Drop entries older than the interval whenever the table is touched,
   so it is bounded by live agents. Done-when 2 then reads: the main-session `Bash` miss reminds;
   a subagent's **first** `Grep` within the interval reminds and its second does not; after the
   next prompt the main session's next search reminds again. Item 5's sentence becomes
   "`agent_type` is this path's only subagent *exclusion*; `agent_id` is read for the key and
   compared with nothing", and the throttle's invariant gains "a subagent's first search is
   reminded whatever its parent was shown, and a parent's time is not moved by a subagent's".
   Round 2's fallback for the label half stands unchanged.
   *A cheap refinement, decline with the reason if not wanted:* key per corpus as well, so an
   agent that moves from module A to module B inside the interval is told about B — the line
   then names only the corpora due, and a search reaching only corpora already named within the
   interval is silent. The dict key is the only thing that changes.

2. **[IMPROVEMENT] The workflow the README recommends gets a redundant reminder every turn.**
   `README.md` lines 772–776 and `design/code-knowledge.md` §6 tell the user to prompt *"using the
   knowledge tool, and then verify it against the actual code"*. Under item 4 each prompt clears the
   time, so in that very turn the first `grep` — the verification step, issued right after a
   `zikaron_knowledge_search` of the same corpus — is reminded that the corpus exists. That is the
   predictable case of the line costing tokens for nothing, and it also biases done-when 2's
   quantity: a reminder that follows a knowledge search is followed by another for reasons the line
   had no part in. **Fix:** a `knowledge_search` under a session label stamps that label's
   main-session entry as a reminder (the MCP envelope carries no `agent_id`, so a subagent's own
   knowledge search cannot be attributed; say so). One more write to the same table. If declined,
   done-when 2's command should exclude reminders preceded by a `zikaron_knowledge_search` within
   the same window, or the rate measures the prompt rather than the hook.

3. **[IMPROVEMENT] The throttle can stamp a reminder the agent never saw.** The hook gives the
   exchange 1 s (line 7117); a service that answers at 1.2 s has stamped the session while the hook
   has exited, so nothing is shown and nothing is shown for the next 300 s either. This is the case
   `architecture.md` §"A push the agent never saw is never recorded as shown" closes for
   `memory_surface` with `deadline_at_ms` (`dispatch.py`'s `surface_deadline`), on a host
   `FINDINGS.md` records as busy. **Fix:** `knowledge_remind(paths, deadline_at_ms)`, the hook
   sending the instant it stops waiting as `rpc.PushDeadline` already produces it; past it the
   service answers `deadline_passed` and moves no time — one invariant cell, "an answer past the
   hook's deadline leaves the time alone". If declined, state the cost: one reminder lost per
   interval whenever the service is slow.

4. **[IMPROVEMENT] Three probe outcomes still have no stated consequence.** Probe 3 (lines
   7038–7046) asks whether the failure payload carries `cwd`, `tool_input` and `agent_type`, and
   whether the `if` filter holds on `PostToolUseFailure`, and says what follows only for the
   positive case. **Fix**, one clause each: without `tool_input` there is no command to read, so
   the exit-1 search is a known miss in §8 and done-when 2's `Bash` grep becomes one that matches;
   without `cwd`, a relative operand resolves against the store directory (`_scope_dir`), the one
   directory the hook still knows; where the filter does not hold on `PostToolUseFailure`, the
   `Bash` arm is not registered there — the alternative is a hook start on every failing `Bash`
   call, a red gate run included — and the miss case is again a known miss. Likewise probe 2's
   `Bash(git -C * grep *)` (line 7029): where the field takes no mid-pattern wildcard, `git -C`
   is a known miss rather than a parser case.

5. **[NITPICK] The `git grep` revision sentence states the wrong consequence.** Item 3 (lines
   7083–7084): "a revision among the operands is read as a path, which reaches no module". `HEAD`
   resolved against the `cwd` is `<cwd>/HEAD`, which lies under the `cwd` and so reaches whatever
   a search of the `cwd` reaches — the right answer, since `git grep foo HEAD` from a subdirectory
   searches that subtree of the tree, but the opposite of what the sentence says, and a table cell
   written from it would assert the wrong thing. Replace the clause with "which lies under the
   `cwd` and reaches what the `cwd` reaches".

6. **[NITPICK] The key's name falls outside `schema.md`'s own taxonomy.** §"Configuration keys"
   (lines 559–563) classifies the knowledge index's keys as "every `knowledge_`-prefixed key …
   inside a shared section"; `retrieval.code_knowledge_reminder_seconds` (line 7121) is not
   `knowledge_`-prefixed, so that sentence misfiles it. Either name it
   `retrieval.knowledge_reminder_seconds`, with `ConfigKey.unit = SECONDS` as `run_lease` has, or
   add the taxonomy sentence to item 8's list of prose the change moves.

7. **[NITPICK] Two enumerations item 8 does not name, and nothing in the gate reads.**
   `zikaron/service/dispatch.py` lines 32–35 list "`memory_surface`, `memory_plan_groups` and
   `knowledge_unlock`" as "the methods with no tool", which `knowledge_remind` joins; and
   `zikaron/hook/main.py` lines 3–4 enumerate the payload — "`{hook_event_name, cwd, session_id}`
   always, plus `prompt` … and `agent_type` for the subagent trigger" — which the tool events
   extend with `tool_name`, `tool_input`, and `agent_type`/`agent_id` inside a subagent. Add both
   to item 8's sentence on counts, as predicates.

8. **[NITPICK] One sentence in item 4 reads as if the fallback were measured.** Line 7106–7107:
   "which the comment on `CLAUDE_CODE`'s `fires_hooks_for_subagent_sessions` says carries the same
   value wherever both exist — probe 1 checks that for tool events". The comment (`spec.py` lines
   292–295) actually derives the equality from `UserPromptSubmit` not firing for subagents, a
   premise the tool events break; probe 1 is right to check it. Say "asserts" rather than "says",
   so the builder does not take it as a measured fact; and if the probe finds a subagent's tool
   event differs, that comment is one more sentence the change moves.

VERDICT: NEEDS_CHANGES

### Author's response to round 3

- **1, accepted**: the key is the label plus the payload's `agent_id`; probe 1 records `agent_id`
  and its constancy; `memory_surface` clears only the main session's time; entries older than the
  interval are dropped; done-when 2 now has a subagent's first `Grep` remind and its second not;
  item 5 and the throttle invariants follow. **The per-corpus refinement is declined**: the
  operator set at most one reminder each interval (2026-10-19), and keying per corpus would make
  it one per corpus each interval — a change to that rule rather than an implementation detail.
  Projects document one or two modules, so it would rarely differ either way.
- **2, accepted**: a `knowledge_search` sets its label's main-session time, and item 4 says that a
  subagent's knowledge search sets it too, since the MCP envelope carries no `agent_id`. The
  fence now says this changes no search result.
- **3, accepted**: `deadline_at_ms` on the method, `deadline_passed` past it, no time moved; the
  invariant cell added.
- **4, accepted**: probe 3 states the consequence when `tool_input` is missing or the filter does
  not hold on the failure trigger, and the fallback when `cwd` is missing; probe 2 states the one
  for `git -C`.
- **5, accepted**: the revision clause corrected.
- **6, accepted**: renamed `retrieval.knowledge_reminder_interval`, in seconds as `run_lease` is.
- **7, accepted**: both enumerations added to item 8.
- **8, accepted**: "asserts", and the comment is listed as a sentence the change moves if probe 1
  contradicts it.

## Round 4 — 2026-10-20

**Summary judgment.** Every round-3 disposition is applied as recorded, and the brief's claims about
the tree hold on a fresh read: `claude_hooks_value` assigns one group per trigger and the guard loop
overwrites it; `_is_ours` flattens a trigger's groups into one program list; `_refuse_differing_hook_groups`
judges every Zikaron group on a written trigger; `Method.deadline` is per method and `surface_deadline`
reads `deadline_at_ms` less `DEADLINE_MARGIN_MS`; `PushDeadline.after` produces the instant; `Handler`
receives the resolved envelope, so `knowledge_search` can stamp its label; `design/harness.md` line 113
has `CLAUDE_CODE_SESSION_ID` in the MCP server's process, so the hook's and the MCP client's labels
agree and item 4's stamp is coherent; `ConfigUnit.SECONDS`, `run_lease`'s bounds, `HOOK_TIMEOUT_SECONDS`
(10), `_CONNECT_TIMEOUT_SECONDS` (0.3), `ServiceContext.spawned_builds`, `CONSOLIDATOR_AGENT_TYPE`,
`DOCUMENTER_AGENT_NAME`/`ORCHESTRATOR_AGENT_NAME`, the cited design and research sections and
`README.md` line 772 all exist as cited. Item 4's sub-bullets are now executable without guessing.
Two things remain that a builder would otherwise decide alone: where the reminder's tool names and
`if` patterns live, which the seam rule and the guards' own precedent already answer; and two
sentences in `design/knowledge-index.md` that go false and are named nowhere in a brief whose item 8
exists to name them. Four nitpicks follow. Nothing changes the shape of what ships.

### Findings

1. **[IMPROVEMENT] The matcher, the `if` patterns and the tool names belong on `HarnessSpec` in
   `GuardHook`'s shape, and the hook reads the tools it judges from that field.** Item 2 (lines
   7054–7056) carries "the trigger" as data on `HarnessSpec`, `None` under kiro, and says nothing
   about where `Grep`, `Glob` and `Bash`, the `Grep|Glob` matcher and the six `Bash(…)` patterns of
   probe 2 live. Three consumers need them: the installer, which writes the groups
   (`entries.claude_hooks_value`); the hook, which must dispatch on `tool_name` to read `path`
   from one tool and `command` from another; and `tests/test_harness_table.py`, which asserts the
   spec against §"The table" and so needs the row to carry whatever the field carries. A builder
   who spells `"Grep"` in `zikaron/hook/` has put a harness name downstream of the seam, which
   `CLAUDE.md` §Harness forbids ("as data, never as a branch downstream of it") and which the
   guards already resolved: `design/guards.md` §5 lines 587–590, "The tool names live once, in the
   spec field's matchers … The guard reads its `tool_name` checks from that field by splitting
   each matcher on `|`", implemented at `zikaron/guard/main.py` lines 72–73 through
   `GuardHook.tools`. **Fix:** in item 2, "carried as data on `HarnessSpec` as one field in
   `Guards`' shape — its trigger or triggers, its matcher, and the `if` patterns — `None` under
   kiro; the installer writes the groups from it and nothing else, the hook reads the tools it
   judges from the matcher as `zikaron-guard` does (`design/guards.md` §5), and §"The table"'s row
   carries all three". Add to the invariants: the hook's tool names and the installer's matcher
   are read from the one field, as `tests/test_guard_rule_table.py`'s matcher test holds for the
   guards.

2. **[IMPROVEMENT] Two sentences in `design/knowledge-index.md` go false, and neither the document
   nor the sentences are in the brief.** Line 1956: "**`knowledge_unlock(knowledge_base)` is an
   eighth RPC method with no tool beside it**"; line 2994: "`knowledge_unlock`, the only
   **knowledge method with no tool**". `knowledge_remind` makes the first a ninth and the second
   false outright. Item 8 (lines 7184–7190) names `dispatch.py`'s list and architecture's count
   sentence, and the normative list (lines 7000–7011) names `design/architecture.md` §"Service
   RPC surface" — whose own method list at lines 2411–2417 also says "The last has **no tool**",
   a clause item 4's "names it" does not obviously reach. Nothing in the gate reads any of the
   three. **Fix:** add to item 8's sentence on counts: `design/knowledge-index.md` §8.5's "eighth
   RPC method with no tool" and §9's "the only knowledge method with no tool", and architecture's
   "The last has no tool", each restated as its predicate (a method with no tool is one an agent
   must not be able to call: the lock a human judges, the reminder a hook asks for). Either list
   `design/knowledge-index.md` in the normative list for that purpose or say in item 8 that it is
   touched for those two sentences alone, so its K-decisions and invariants are not reopened.

3. **[NITPICK] Two more sentences the change moves, one count among them.** `zikaron/service/methods.py`
   line 47, `Method`'s docstring: "Every method but `memory_surface` takes the service's budget" —
   false once `knowledge_remind` sets `deadline=` too; and `design/schema.md` §"Configuration keys"
   line 562: "four belong to the knowledge index … (every `knowledge_`-prefixed key)", whose own
   parenthetical the fifth such key breaks, though the paragraph says later keys move none of its
   figures. Add both to item 8; the second restated as "the `knowledge_`-prefixed keys, whichever
   section they sit in".

4. **[NITPICK] Probe 3's consequence sentence is ambiguous at the word that carries it.** Lines
   7045–7051: "… treats them alike — unless the failure payload carries no `tool_input` …, or the
   filter does not hold there …. Either way the `Bash` arm is not registered on
   `PostToolUseFailure`". "Either way" reads as covering the positive case too, which the preceding
   sentence contradicts. Write "In either of those two cases". And done-when 2 (line 7231) asks for
   a `Bash` `grep` "that matches nothing" unconditionally, where item 1 makes that the positive
   case's test; add "where probe 3 says a miss fires a hook, else one that matches".

5. **[NITPICK] Two throttle details a builder would otherwise settle by accident.** (a) Item 4
   (line 7124) has each `memory_surface` call clear the main session's time; say it clears on
   receipt, before `surface_deadline`'s check and whatever the call then answers, so a push
   refused `deadline_passed` or `store_busy` on the busy host `FINDINGS.md` records still opens the
   turn — else that turn's first search is unreminded. (b) The main session's entry is the one
   with no agent half; `research/claude-code-tool-hooks-docs.md` §6 line 144 says `agent_id` is
   populated inside a subagent, not that it is absent outside one. Have probe 1 record that the
   parent's payload carries none, and say that where it carries one the hook sends no `agent_id`
   for a payload without `agent_type`, since `memory_surface` would otherwise never find the entry
   it clears. Done-when 2's third step would catch that; the probe is where it is cheap.

6. **[NITPICK] A bound on `paths`, and what the hook does past it.** `design/schema.md` §Bounds
   gives every list parameter a length, and a refused `bounds` is "a serving service that answers
   an error" (item 7) — one `hook.log` line and no reminder for a `grep foo a.py b.py …` long
   enough to cross it. Say the hook sends at most the bound's count of paths, the first in command
   order, since the line is one whatever the count and a search of the first N is still a search
   of their modules; and that a `knowledge_search` stamps the time only when its scope reaches a
   code-knowledge corpus — `knowledge_bases` empty, or naming `code-knowledge` or a
   `code-knowledge/` name — since a search scoped to a hand-written corpus says nothing about the
   agent remembering the documents, and the handler already holds the names. Decline the second
   half with the reason if the one-rule form is preferred; projects with both kinds of corpus are
   the case.

VERDICT: NEEDS_CHANGES

### Author's response to round 4

All six accepted.

- **1**: one `HarnessSpec` field in `Guards`' shape. The installer writes from it, the hook reads its
  tools from the matchers, and §"The table"'s row carries it; there is an invariant. The test the
  finding cites as precedent is `tests/test_guard_main.py`'s
  `test_the_tool_sets_are_the_spec_fields_matchers`, not one in `tests/test_guard_rule_table.py`,
  and the brief cites that one.
- **2**: both `design/knowledge-index.md` sentences and architecture's "The last has no tool",
  restated as a predicate; `knowledge-index.md` is touched for those two sentences alone.
- **3**: the `Method` docstring and `schema.md`'s taxonomy sentence.
- **4**: "In either of those two cases"; done-when 2's `grep` depends on probe 3.
- **5**: `memory_surface` clears the time on receipt, whatever it then answers; probe 1 records
  that the parent's payload carries no `agent_id`; the hook sends no `agent_id` without
  `agent_type`.
- **6**: the hook sends at most the bound's count of paths, first in command order; a
  `knowledge_search` moves the time only when its scope reaches a code-knowledge corpus. Both have
  invariants.

## Round 5 — 2026-10-21

**Summary judgment.** Every round-4 disposition is applied as recorded, and the brief's claims about
the tree hold on a fresh read: `GuardHook`/`Guards` and `GuardHook.tools` (`spec.py` lines 86–108);
`guard/main.py` choosing a rule by membership in a member's `tools` (lines 72–75); `_is_ours`
flattening a trigger's groups (`targets.py` 990–1000) and `_refuse_differing_hook_groups` returning
early under `--force` (973); `connect_once`'s start under lock being separable from its connect,
`_health_or_close` and `_verify_identity` (`connect.py` 162–204); `surface_deadline` and
`DEADLINE_MARGIN_MS` (`dispatch.py` 170–199); `failure._format_line`'s detail slot;
`IntBounds(60, 86400)` with `ConfigUnit.SECONDS` on `run_lease`; `CONSOLIDATOR_AGENT_TYPE` held equal
to the installer's name by `tests/test_hook_subagent_policy.py`; corpus files living flat as
`knowledge/<uuid>.db` (`core/knowledge/paths.py` 43), so the hook's listing is one `listdir`;
`research/claude-code-tool-hooks-docs.md` §3.3 line 86 naming `PostToolUseFailure` among the
triggers whose `additionalContext` lands "next to the tool result", which backs item 2's
registration; and every cited heading in `code-knowledge.md`, `architecture.md`, `guards.md` and
`harness.md`. One claim does not hold, and it is one round 4 introduced: there is no bound on list
parameters in `design/schema.md` §Bounds or in `params.optional_str_list`, so the `paths` bound item 4
and two invariants rest on has no number. That is a one-sentence, one-row fix. The rest is nitpicks.

### Findings

1. **[IMPROVEMENT] The list bound `paths` is said to inherit does not exist, so the invariant has no
   number.** Item 4's first sub-bullet (line 7119): "`paths` is bounded as every list parameter is
   (`design/schema.md` §Bounds), and the hook sends at most that many"; the invariants (line 7241):
   "A search naming more paths than the bound sends the first that many". §Bounds (`schema.md`
   lines 1577–1587) bounds `uuids` on `fetch` (1–50, `params.UUIDS_MIN`/`UUIDS_MAX`), `absorb`,
   `limit` and query terms, and states no rule for lists; `params.optional_str_list`, which
   `knowledge_search`'s `knowledge_bases` goes through, checks type alone and bounds nothing. Round
   4's finding 6 asserted the general rule; that was wrong, and the brief adopted it. A builder
   looking for the rule finds none and picks a figure, and the invariant cannot be mutation-verified
   against a bound nobody has named. **Fix:** name it — `paths` on `knowledge_remind`, 1–50 per
   call, the `uuids` row's figure, as a row in §Bounds, with `design/schema.md` §Bounds added to
   the normative list beside its configuration table; the hook sends at most 50, the first in
   command order, so a refused `bounds` is unreachable from what the hook itself builds. Say in the
   same sentence why the list is never empty: a `Grep`/`Glob` with no `path` and a recursive `grep`
   with none send the `cwd`, and a search that names no module — a pipe filter, a `grep` with
   neither path nor `-r` — asks nothing (item 3 already says so; the bound's row should not read
   as admitting zero).

2. **[NITPICK] Say `--force` in the ownership invariant.** Line 7245–7247: "memory over guards,
   guards over memory, and `both`, each leave both selections' `PostToolUse` groups". Under
   `--force` the refusal is skipped (`targets.py` 973), so the write and `_rewritten_hook_notes`
   (1054–1067) are the only places judging ownership, and the note today says what it replaced per
   trigger. Add "with and without `--force`, whose note names only the groups it replaced" — the
   case item 2 names as removing the nudge today is the forced one.

3. **[NITPICK] Have probe 3's logging hook return a token in `additionalContext` on
   `PostToolUseFailure`.** Item 1's third probe (lines 7041–7054) records which event fires and what
   the payload carries, not whether that trigger's `additionalContext` arrives; the docs say it
   does (`research/claude-code-tool-hooks-docs.md` §3.3 line 86) and §2 of the same note asks for a
   one-session probe on the installed version before relying on the channel. As written, a dead
   channel on the failure trigger first shows at done-when 2's first step, after the build, with
   no stated fallback. One clause: the hook returns a token on both triggers and the probe records
   whether the agent quotes it; where it does not arrive on `PostToolUseFailure`, the `Bash` arm is
   not registered there and a miss is a known miss — the branch the brief already has for a
   failure payload without `tool_input`.

4. **[NITPICK] Say what "`Guards`' shape" buys, so the hook never spells `Bash`.** Item 2 (lines
   7056–7061) puts the field "in `Guards`' shape" and has the hook read "the tools it judges from
   its matchers", but the two arms read different input fields — `tool_input.path` for one,
   `tool_input.command` for the other — and a builder has to tell them apart somehow. The guard's
   precedent is membership in a *named member's* `tools` (`guard/main.py` 72–75: `guards.command`
   against `guards.reread`), so one clause: the field has one named member per arm, and the hook
   reads `path` or `command` by which member's matcher names the tool. Also note that
   `tests/test_harness_table.py`'s `test_guard_hooks` reads the guards cell's first four
   backticked tokens positionally (lines 196–203), so the reminder's row needs a parser of its own
   rather than a fifth and sixth token in that cell.

5. **[NITPICK] The cost bullet omits the aggregate the cited note measured.** Item 4's last
   sub-bullet (lines 7158–7161) prices one search; item 5 excludes the documenter "before it
   connects" without saying the process still starts. `research/m40-4-search-tool-use.md` has it:
   a matcher selects a tool, not an agent, so every documenter `Grep`/`Glob` starts the hook, ~95 ms
   each on this host, 1,835 calls about three minutes across LeibaTrader's documenters at 19 at a
   time. One clause in item 5, so the exclusion is not read as free.

VERDICT: NEEDS_CHANGES

### Author's response to round 5

All five accepted.

- **1**: the bound is named: `paths` on `knowledge_remind`, 1–50 per call, as a new row in
  `design/schema.md` §Bounds, which joins the normative list. The hook sends at most 50, and the
  list is never empty. Round 4's general rule was wrong, and verified so:
  `params.optional_str_list` checks types only.
- **2**: `--force` is in the ownership invariant.
- **3**: probe 3's hook returns a token on both triggers, and a token that does not arrive on
  `PostToolUseFailure` is the third case the arm is not registered there.
- **4**: one named member per arm, read by member; the harness table's row has a parser of its own.
- **5**: item 5 says the process still starts for a documenter, with the measured figures.

Not re-spawned: this is the fifth round without approval, so per the protocol the open state goes
to the operator before any further round.

### Between rounds 5 and 6: the probes

The operator's direction (2026-10-21): *"Ok, do the probes and once they're settled continue
reviewing"*. The probes ran in two headless sessions, recorded in
`research/m40-4-hook-probes.md`, and item 1 now states their results rather than what they would
test. What they changed in the brief:

- **Who is calling**: `agent_type` and `agent_id` are present inside a subagent and absent in the
  main session; a subagent's payload `session_id` and its hook's `CLAUDE_CODE_SESSION_ID` are both
  the parent's. The payload-`session_id` fallback is gone. A hook with no label asks nothing, the
  degraded case. The fallback's invariant cell is gone too.
- **One `PostToolUse` group**, matcher `Grep|Glob|Bash`, with a string `if` on each handler. The
  "two memory groups" invariant is gone, and ownership is still judged per program, beside the
  guard's group.
- **`PostToolUseFailure` is not registered.** Claude Code reads a search command's exit 1 as "No
  matches found", so a miss fires `PostToolUse`. Only a search that errors fires the failure
  trigger, and it is a known miss. The probe-3 branches in item 1, the invariant and done-when 2
  lose their conditionals.
- **Known misses from what was measured**: `timeout 5 grep …` does not start the filtered handler,
  and an erroring search is missed. `LC_ALL=C`, pipes, `cd … &&` and `git -C * grep *` all
  matched.

## Round 6 — 2026-10-21

**Summary judgment.** Round 5's dispositions are applied as recorded, and item 1 now states what
the probes measured, consistently with `research/m40-4-hook-probes.md` and with the logs it was
written from (checked: `timeout 5 grep` is one line in `hook-log-run1.jsonl`, the control's; the
eight `agent_id` strings are all on `probe-searcher` lines and every one of the 38 main-session
lines carries `agent_id` and `agent_type` null; `CLAUDE_PROJECT_DIR` and `CLAUDE_CODE_SESSION_ID`
are present in the subagent's hook process, and its `cwd` follows the parent's `cd` into `src`).
Every claim about the tree holds on a fresh read: `claude_hooks_value` assigns one group per trigger
and the guard loop overwrites; `_plan_settings` keeps only non-Zikaron groups on a written trigger;
`read_grep` keeps the first operand and reads `--` as an unknown long option; `connect_once`'s
start under lock is separable from its connect and identity check; `_format_line` has the slot;
`surface_deadline` and `DEADLINE_MARGIN_MS`; `Method`'s "Every method but `memory_surface`";
`resolve` minting per request; `session_label`; `test_guard_hooks` reading four positional tokens;
corpus files flat as `knowledge/<uuid>.db`; `experiments/m40_eval.py` line 351 checking the whole
`zikaron` package; and every cited heading. **What the one-group shape introduces, and no prior
round could weigh because every round before this assumed two groups**: a group of eight handlers
running one program makes the handler count part of ownership under `_is_ours`'s list equality, so
the first later change to the `if` set refuses every existing install without `--force`; and under
the documented fallback for a `Bash` input Claude Code cannot parse, every `Bash(...)` handler
starts, so one such call is six hook starts — unmeasured, and item 4 prices one. Both are cheap.
The rest is nitpicks.

### Findings

1. **[IMPROVEMENT] Ownership by program *list* makes the handler count an ownership signal, so
   the first change to the `if` set refuses every existing install.** Item 2 (lines 7059–7065):
   "an install compares the Zikaron groups running a program it writes there with the groups it
   writes for that program". `_is_ours` (`targets.py` 990–1000) compares `_programs_in(group)` —
   one entry per handler, the program's full path — as a list equal to the expected groups'
   flattened list. Today every Zikaron group has one handler, so that is a comparison of one
   program; the memory `PostToolUse` group has a handler per tool and per command word, eight at
   item 1's set, each running `zikaron-hook`, so its program list is eight copies of one path, and
   an installed group with seven or nine compares unequal and is refused by
   `_refuse_differing_hook_groups` as another install's unless `--force` — the case the function's
   own docstring records ("comparing groups whole made every existing install refuse its own") and
   `architecture.md` §"The install contract" (2537–2538) rules out ("would block every existing
   install's upgrade the day a timeout moved"). The sentence item 2 rewrites says list equality in
   so many words — `harness.md` 598–601 and `architecture.md` 2531–2533, "programs … as a list
   equal to ours rather than merely containing it" — so a builder restating it per program inherits
   the count, and the invariants (7235–7238) test only re-installs of an unchanged set. **Fix:** in
   item 2, state ownership per program as membership rather than equality: a Zikaron group on a
   trigger belongs to the selection whose program every one of its commands runs; a group whose
   commands all run our program is ours whatever their number and `if` fields, and one that differs
   from what the install writes is rewritten and reported by `_rewritten_hook_notes` (which already
   compares whole groups); a group carrying our program beside a command of the user's own is still
   refused, since that command's program is not ours — the case the list rule existed for. Restate
   the two design sentences the same way, and add to the invariants: an installed memory
   `PostToolUse` group with a handler more or fewer than the install writes is rewritten and
   reported, not refused; one carrying a user's command beside ours is refused. Mutation: drop one
   handler from the expected set and re-run the install over a snapshot of the current one.

2. **[IMPROVEMENT] A `Bash` input the filter cannot read starts every `Bash(...)` handler, which
   the brief neither measured nor priced — and two hooks for one call must yield one line.** Item 1
   (7029–7034) and item 2 (7044–7045) ship one group with six `Bash(...)` handlers, each running
   `zikaron-hook`. `research/claude-code-tool-hooks-docs.md` §6 line 139: "When Claude Code can't
   determine which commands the Bash input runs, it runs your hook regardless of the pattern." Under
   that rule such a call starts all six — six processes at ~95 ms each for one `Bash` call, in every
   memory install, documented module or not — and where the command does hold a search (a heredoc
   script followed by a `grep`) six concurrent `knowledge_remind` requests. Item 4's cost line
   (7148–7151) prices one process start per search, and probe 2 ran no such command, so nothing
   says which inputs Claude Code gives up on or how many handlers then start; a heredoc
   (`cat <<'EOF' … EOF`), `bash -c '…'` and a `$(…)` substitution are the likely ones, and the
   first is a routine agent idiom. **Fix:** one more row in probe 2 — a heredoc command with a
   `grep` after it — recording which `if` handlers started, with the consequence stated either way:
   where every `Bash(...)` handler starts, collapse the six into one handler whose `if` is the list
   of patterns, if the field takes a list (the note says a list "was not tried, since nothing needs
   it"; this is what needs it), else keep the six and price them in item 4 as "up to one start per
   `Bash(...)` pattern for a command the filter cannot read". In either shape, say in item 4 that
   the throttle's read and stamp are one synchronous step after the registry read, so the two
   hooks one call can start — a pipeline of two search programs, `grep … src | rg …`, starts a
   handler per pattern under the matching probe 2 measured — yield one line and not two. Mutation:
   an `await` between the read and the stamp, two concurrent requests.

3. **[NITPICK] A parser case the filter never delivers, and the `git` spelling it misses.** Item 3
   (7078–7081) passes over `-c <name=value>` to find `git`'s subcommand, but item 1's set has no
   `Bash(git -c * grep *)`, so that branch is dead on the shipped filter; and `git --no-pager grep …`
   matches no pattern either. Either add both — `-c` is the measured `-C` shape with another letter,
   and `Bash(git --no-pager grep *)` has no mid-pattern wildcard at all — or drop the `-c` clause and
   list `--no-pager` among §8's misses. Decline with the reason if the set should stay what was
   measured.

4. **[NITPICK] Four sentences the change moves that item 8 does not name.** `design/harness.md`
   line 644, "**Three hook entries, because M14 built a third path.** `SessionStart`,
   `UserPromptSubmit` **and `SubagentStart`**" — under a section in the normative list, but it is
   the install's own entry count and item 8 exists to name each; `zikaron/harness/spec.py` 352–353,
   the `CHANNELS` comment's "one unreachable cell", two once the reminder's event is Claude Code's
   alone; `zikaron/hook/failure.py` line 1, "exactly one line per failed `userPromptSubmit`", which
   item 7's line makes false; and `design/architecture.md` 597–598, "for the hook — … one line to
   `hook.log` plus a model-facing relay on stdout", where the reminder path's identity mismatch
   logs with no relay.

5. **[NITPICK] Say what item 1 measured of the shipped group, and how its matcher is derived.**
   Item 2 (7044): "as the one group item 1 measured" — group B carried three handlers (`Grep`,
   `Glob`, `Bash(grep *)`); the other five `Bash` patterns were measured under group A's two-group
   shape, and the eight-handler group itself was not run. Say so, so the build does not read it as
   measured whole. And since the field has a member per arm (7045) and the installer writes one
   group from it, say the group's `matcher` is the members' matchers joined with `|` — the one
   derivation the installer and `tests/test_harness_table.py`'s new parser must agree on.

VERDICT: NEEDS_CHANGES

### Author's response to round 6

Finding 2 was measured rather than reasoned about: two more probe runs, now in
`research/m40-4-hook-probes.md` §"Probe 2, continued". Both kinds of command multiply hook starts:

- **A heredoc**, with a `grep` after it or with none, starts every filtered `Bash` handler.
  `$(grep …)` starts some.
- **The handlers start together**, within 7 ms of each other.

Two more results:

- **A list-valued `if` is silently never matched**, so finding 2's collapse into one list-`if`
  handler is impossible.
- **A leading wildcard works**: `Bash(*grep *)` matches `grep`, `egrep`, `git grep` and
  `git -C … grep`. It also matches `pgrep`, which the parser reads as no search.

`bash -c '…'` starts no filtered handler.

- **1, accepted**: ownership is membership. A group whose commands all run our program is ours
  whatever its handler count; one beside a user's command is refused. Both design sentences are
  named for restatement, and the invariant cells are added.
- **2, accepted, through the measurement**: the six `Bash` handlers become two, `Bash(*grep *)`
  and `Bash(rg *)`. Item 4 prices a command the filter cannot read at both handlers starting
  together, about one start's wall time. The throttle's read and stamp are one synchronous step,
  with an invariant.
- **3, settled by the measurement**: `Bash(*grep *)` reaches `git -c … grep` and
  `git --no-pager grep`, so the parser's `-c` branch is live. Both are in the matching table.
- **4, accepted**: all four sentences are added to item 8.
- **5, accepted**: item 2 says the group was measured in parts, and gives the `matcher` as the
  members' matchers joined with `|`.

## Round 7 — 2026-10-21

**Summary judgment.** Round 6's dispositions are applied as recorded, and the three changes since —
`Bash(*grep *)` and `Bash(rg *)` as the group's `Bash` handlers, ownership as membership, the
throttle's read and stamp as one synchronous step — are consistent with the logs behind
`research/m40-4-hook-probes.md` §"Probe 2, continued" and with the tree: `_program` (`targets.py`
912–922) returns a Zikaron command's full path, so "a program this install writes there" is
path-based and the membership rule is implementable in `_is_ours` without touching the recogniser;
`_rewritten_hook_notes` (1021–1084) already compares whole groups and partitions user commands, so
the "rewritten and reported" and "refused beside a user's command" outcomes fall out of it; the
service is one asyncio loop with `to_thread` only on encoder loading and consolidation, so "no
`await` between" is the atomicity rule that holds; the guard parser delimits heredocs and same-line
`$(…)` (`guard/heredoc.py`, `guard/grammar.py` 9–10), so the "grep after a heredoc" cell is
parseable as stated; `claude_hooks_value` (`entries.py` 334–336) assigns the guard's group per
trigger as item 2 says; and every figure item 5 quotes is in `research/m40-4-search-tool-use.md`.
The brief is executable without guessing. What follows is five nitpicks, each one clause, none
changing what ships.

### Findings

1. **[NITPICK] Name the fourth ownership outcome, which exists today and has no sentence.** Item 2
   (lines 7069–7083) and the invariants (7265–7270) give three: ours, rewritten and reported; the
   other selection's, kept; ours beside a user's command, refused. A fourth is a Zikaron group whose
   command runs at a path this install would not write — another install's, of either selection —
   which `_refuse_differing_hook_groups` refuses today (949–955) and `--force` replaces without a
   note (1040–1044), and whose refusal `tests/test_install_targets.py` already pins (688, 1285).
   Read with `_program`'s path-based "program" the brief is determinate — such a group is neither
   ours nor the other selection's and falls to refusal — but the helper a builder reaches for to
   recognise "the other selection's" is `_zikaron_script`, which answers by **file name**, and
   keeping by name would keep a foreign venv's guard group silently, reversing the recogniser's own
   reason for matching by name (934–937). One clause after "Groups running the other selection's
   program are kept": "at this install's path; a Zikaron program at any other path is another
   install's, of either selection, and is refused as today, replaced under `--force`"; and the cell.

2. **[NITPICK] Price what the leading wildcard matches beyond searches.** Item 4's cost bullet
   (7165–7171) prices a search and an unreadable command. `Bash(*grep *)` is matched against a
   simple command's text — `Bash(git -C * grep *)` matching `git -C src grep -n needle` and
   `Bash(*grep *)` matching `git -C src grep` show `*` spanning words — so any simple command whose
   text carries `grep ` anywhere starts the handler: `git commit -m "fix grep …"`, an `echo`, this
   repository's own `pgrep -af '[c]heck…'` gate check. The parser finds no search and the hook
   asks nothing, so it is one start and no connect, unmeasured. One clause in the cost bullet, or a
   row in probe 2 if the run is cheap. In the same place, since a list-valued `if` is ignored
   rather than rejected (7029–7030), say what version the probes measured (2.1.304, the note's
   line 3) so the README's account of the install can name it; a harness without the field would
   presumably ignore a string `if` the same way and start all four handlers on every matched call,
   still fail-open and asking nothing. Declinable under the operator's line on unlikely cases.

3. **[NITPICK] The two-at-once invariant does not hold at interval 0.** Line 7271, "Two
   `knowledge_remind` requests for one agent at once yield one line", against 7152–7153, "0
   reminds on every such search": with the interval 0 a stamp expires as it is written, so two
   concurrent requests each earn a line, and a test of the cell at that value is red by design.
   Write "under a non-zero interval".

4. **[NITPICK] Say which five.** Item 6 (7189–7190) names "up to five corpora the search reached"
   and the cell (7249) "six modules reached name five"; nothing says which five, so the test's
   assertion and the line's content are the builder's choice. Name an order — the deepest module
   first, then by name — which also puts the most specific corpus at the head of the line, where a
   search of `src/a/b.rs` in a project documenting `src` and `src/a` wants `src/a`.

5. **[NITPICK] Two more sentences the change moves.** `zikaron/install/entries.py` 318–320, "The
   memory groups carry no `matcher` — `UserPromptSubmit` accepts none at all, and the start
   triggers must fire for every session and every subagent", goes false once the memory
   `PostToolUse` group carries `Grep|Glob|Bash`; it is in the file the build edits, so one more
   phrase in item 8's list. And `research/m40-4-hook-probes.md` §"What it decides" (123–124) says
   of an unreadable command that "the hook's parser finds no search and asks nothing", where item
   4 (7170) says "in most such commands" and the matching table makes a `grep` after a heredoc a
   search; the word "most" keeps the note from contradicting the cell. The second is declinable
   under the operator's line on research notes.

VERDICT: APPROVED

### Author's response to round 7

All five nitpicks applied:

- the fourth ownership outcome, matched by path as `_program` returns it, and its cell;
- the cost of a command whose text carries `grep ` without searching, and the version measured;
- "under a non-zero interval" on the two-at-once cell;
- the order, deepest module first and then by name, in item 6 and its cell;
- `entries.py`'s "The memory groups carry no `matcher`" in item 8's list, and "most" in the
  research note.
