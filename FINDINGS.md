# FINDINGS — Zikaron

> **Working memory for this project**, maintained by the **memory-researcher** agent. It loads every
> session, so it stays lean: the decision index, where the work stands, and what is still open.
>
> **The design lives in `design/overview.md`** — what we are building, the shape of the system, and the
> full D1–D33 decision table *with rationale*. §"Settled decisions" below is a one-line index only. Read
> `design/overview.md` before revisiting any decision, and never re-litigate one from the index alone.
>
> **The finished record lives in `FINDINGS-archive.md`** — build history, the milestone plan, the
> dogfooding evidence, and the references. Read on demand, not every session. It was split out when this
> file reached ~49k tokens and stopped being the lean hub this header claims it is; keeping it lean is
> an ongoing job, not a one-off. When a section here stops being live, move it there rather than
> letting it accumulate.

## Settled decisions — index
One line each. **Rationale, measurements and rejected alternatives are in `design/overview.md` §4.**

| # | Decision |
|---|---|
| D1 | Tribal knowledge only; codebase KB is a separate system |
| D2 | No extra LLM on the write path — hard constraint |
| D3 | Two tiers: journal (unconsolidated) + long-term (consolidated) |
| D4 | Memory record = `{uuid, gist, content}` |
| D5 | Read = hybrid vector + full-text top-K → ids + gists |
| D6 | Write = primary agent's own judgment: new entry / amend (if read first) / nothing; it authors its own gist |
| D7 | Consolidation is the only extra LLM; code picks candidates, model judges |
| D8 | Store scoped to the harness's directory; no global tier in v0 |
| D9 | Delivered as an MCP server plus a distributed skill and hooks |
| D10 | Consolidation trigger = a manually-invoked skill spawning a subagent (no compaction hook exists) |
| D11 | Staleness is repaired in-band by the agent the memory misled |
| D12 | Read = push **and** pull; a `userPromptSubmit` hook injects the top 5 gists |
| D13 | The gist's job is relevance triage |
| D14 | End-to-end task-benefit evaluation stoved until an implementation exists (component benchmarks are not) |
| D15 | Write-time dedup, agent-resolved: `remember` writes, then hands back near-duplicates for the agent to resolve |
| D16 | Soft delete only — retire, never `DELETE` |
| D17 | Scope key = literally the current working directory |
| D18 | Write policy injected by an `agentSpawn` hook |
| D19 | Python venv, latest stable; SQLite + FTS5 + sqlite-vec + fastembed; store never in git |
| D20 | Keep `bge-small-en-v1.5`, pass the BGE query prefix, record model id + dim per vector |
| D21 | Embed gist + content, not gist alone |
| D22 | The hook must never load an embedding model |
| D23 | No cross-encoder reranker on the push path; open for pull |
| D24 | Reject the extracted-identifier `tokens` column as specified |
| D25 | Supersession is structural via `superseded_by`, and it **demotes rather than hides** |
| D26 | Optimistic concurrency: `version` + a read receipt required on every `amend`/`retire` |
| D27 | Provenance = `created_at`, `updated_at`, `session_id` only |
| D28 | Chunk the dense side, parameterized; FTS5 stays unchunked; `max` rollup |
| D29 | Consolidation groups topically using retrieval as the adjacency function, mutual-K plus a cohesion pass; session grouping rejected |
| D30 | Write policy v0 drafted, to be experimented against; six signals instrumented |
| D31 | Four components: core / service / mcp / hook, over a Unix-socket JSON-RPC |
| D32 | Two tool sets: five for the primary agent, four for the consolidator |
| D33 | Config = two TOML layers (system-wide + `.zikaron` override, per-key amend); `meta` keeps only store-coupled values |

## Current state — resume here

### Phase: porting to Claude Code. **M16 is the last milestone, and it is landing.**
Every milestone **M0–M15 is built and reviewed**, and **M16's measurement half is done** — the
dogfooding checkpoint ran on 2026-08-16 and its evidence is
`research/claude-code-dogfood-checkpoint.md`. What remains of M16 is the review round it is in.
M15 (the installer adapter) landed 2026-08-16,
APPROVED after six rounds; what it built and what its rounds taught is in `FINDINGS-archive.md`
§"M15 as built" — read that only if you need the history, not to start M16.

**Where M16 starts: `design/build-plan.md` §M16.** Read the brief, then `design/harness.md`, which is
normative for every harness-coupled fact — do not re-derive one from an older section of
`architecture.md`.

**What is true of the product right now, which M15 changed.** Both thin clients *and* the installer
speak both harnesses. `python -m zikaron.install --project .` writes either harness's artefacts, runs
from a plain shell with no harness process, and refuses when the harness's own binary is absent.
**But nothing is installed into this repository yet** — that is a choice, not a gap. Until someone
runs it, the memory tools and the push hook are **not live in this session**, and M16's first act is
to change that:

```bash
.venv/bin/python -m zikaron.install --project . --harness claude-code
```

`--harness` is stated because `auto` deliberately **refuses here**: this repo carries both `.kiro/`
and `.claude/`, which is genuinely ambiguous. Add `--print-only` first if you want to see the four
artefacts before they land. Then **restart the session** — hooks and `.mcp.json` are read at start.

**M16 inherited four open things, and answered all four** (detail:
`research/claude-code-dogfood-checkpoint.md`):
(a) both `.mcp.json` **approval** properties are **measured** — no load-time prompt, no per-call
prompt — and a **third gate** nobody had named turned up first: Claude Code's folder-trust dialog,
which reads our `permissions.allow` back to the user as a warning (§1);
(b) **MCP server readiness** did not reproduce interactively, and the n=1 *"still connecting"*
observation now has a better explanation than connection state — the tools arrive **deferred** and a
model cannot name what is not in its context (§2). Neither reading is refuted at n=1 apiece;
(c) the **astral-character bisection** ran and closed the question: the budget counts **UTF-16 code
units**, refuting both bytes and code points (§3);
(d) the **recall baseline reset** was taken as a new baseline — 0.83 searches per user turn, with
conditions — and the pre-migration numbers remain **not to be compared against**, in either
direction.

**The gate is hermetic and that is verified, not assumed.** `./check.sh` excludes `integration_kiro`
and `integration_claude`; the whole default suite passes with **neither harness binary on `PATH`**.
Run the tiers by name when you mean to. Nothing lives only in those tiers, and a skip inside one is
converted to a failure by `conftest.pytest_runtest_makereport` — see `coding-standards.md`
§"five tiers", which is binding.

Every milestone M0–M12 is built and reviewed; **M13** (the Claude Code design delta) landed
2026-08-16, APPROVED after three review rounds
(`reviews/claude-code-harness-design-review.md`); and **M14** (the harness seam, both clients, and
the gist character bound) landed 2026-08-16, APPROVED after **four** rounds
(`reviews/m14-harness-seam-review.md`). **M16's measurement half is done** and it is in review — see item 0 below.
**Milestones are cited here by commit *subject*, not by hash, and that is deliberate.** This file
recorded M13 as commit `7628946`; that hash does not exist in the repository — the history was
rebased, as `backup-pre-rebase` and `backup-pre-rebase-2` attest. A hash is the most confident-looking
pointer available and the one most easily falsified by an ordinary operation nobody thinks to
re-record. Subjects survive rebases; `git log --oneline --grep` finds them.
**What M14's four rounds are evidence of, since the count is unusual:** the gate was green while
something material was wrong three separate times — a test asserting two things agree that could
pass vacuously, a universal claim proven only by its best-case fixture, and this always-loaded file
saying both "closed" and "open" about one defect. `check.sh` can see none of those. The practice
that caught the first two, and is worth keeping: **verify an agreement-test by breaking the code it
guards** — every such test in M14 was confirmed to fail on a deliberate mutation before being
trusted.
`design/harness.md` is now **normative for every harness-coupled fact**; read it before touching the
hook, the MCP client or the installer, and do not re-derive a harness fact from an older section of
`architecture.md`.

Between the build finishing and the port starting, the work was **using** the system on two real stores
and fixing what use exposed. Two review trails cover that period and should not be re-run: `reviews/m12-distribution-review.md` (seven rounds, APPROVED) for the milestone,
and `reviews/m12-dogfooding-delta-review.md` (two rounds, APPROVED) for everything changed afterwards.
Read `FINDINGS-archive.md` §"Dogfooding notes" before proposing anything — most of what a fresh session
would think to try has already been measured, and several plausible ideas are already refuted there.

**Where the stores are.** `<project>/.zikaron/`, one per directory, no global tier. This repository has
a small store from a seeding experiment. `~/Memory` is the **primary real-work store** — 31 long-term
records and 26 journal entries at last count, one consolidation run completed (all 31 promoted in place,
zero merges), and it is the corpus the next consolidation should run against. `~/Memory` is otherwise
**read-only for this agent**; writing there needs the operator's explicit say-so, which has been given
once, per-task.
Two snapshots exist for comparison, **in `/tmp`, so they will not survive a reboot**:
`memory-backup-before-consolidation.db` (31 journal, pre-run-1) and `memory-run1-post-consolidation.db`
(15 long-term + 29 journal, the merge-heavy run). Move them somewhere durable if the A/B still matters.
Both were **checked in M16 and are intact**, which was not a given — see the next paragraph.

**Never snapshot a store with `cp memory.db`.** Measured in M16, against a live store: copying that
file alone while the service holds a WAL produced **27 events and 2 memories** against the live **38
and 4** — an entire working session missing. Nothing announces it; the truncated copy opens cleanly
and answers every query. Use `sqlite3.Connection.backup()` or `VACUUM INTO`, which are consistent by
construction, or copy **all three** of `memory.db`, `-wal` and `-shm` together. This matters here
specifically because this file tells sessions to snapshot stores before consolidation experiments,
and a silently-truncated baseline would corrupt exactly the A/B it was taken for.
**How far the failure can go, from the same store 18 minutes earlier:** `memory.db` was **4,096
bytes** with a **3.8 MB** `-wal`, so a `cp` of the main file at that moment would have yielded a
database that opens, answers, and contains *nothing*. The later copy only looked plausible because a
checkpoint had flushed most of it first — the bug's visibility depends on checkpoint timing, which is
why it cannot be caught by looking at the copy.
**What actually caught it is the part worth recording.** Not `check.sh`, which cannot see it, and not
verification — the copy passed every check available, which is what made it dangerous. It was caught
by the **operator independently backing the store up because he did not trust the agent's snapshot**
(`~/zk-dogfood-backup`, all three files, and the only surviving capture of the pre-consolidation
state at 13 events / 2 journal records), and by a **review finding forcing a recount against the live
store**. Both lie outside the loop the agent controls.

**What to do next, in priority order.**
0. **M16 — the dogfooding checkpoint under Claude Code**, the last milestone of the port. Brief:
   `design/build-plan.md` §M16; what it inherits is in the resume block above. It **gates items 1
   and 2**, which both need the memory tools and the push hook live in whichever harness the work
   happens in — and after M15 that is a matter of running the installer, not of building anything.
   The M13–M15 detail a fresh session might go looking for is in the briefs and in
   `FINDINGS-archive.md`; nothing outstanding remains in any of them.

   **M16's dogfooding half is DONE, 2026-08-16. Evidence:
   `research/claude-code-dogfood-checkpoint.md`; raw artefacts in `~/zikaron-m16-evidence/` —
   `store.db` plus both session transcripts and the consolidator's, since Claude Code prunes
   `~/.claude/projects/` on `cleanupPeriodDays` and the note's every quoted line came from there.** Every done-when clause is met and five findings arrived
   that the brief did not ask for. **Read the note before proposing anything about the write
   policy, the budget, or recall** — it is the only measurement of this system under real use by an
   agent that was never told to use it.
   What it settled: **three** approval gates, not two (folder trust reads our `permissions.allow`
   back at the user as a warning); MCP tools arrive **deferred**, so the policy's tool-name
   substitution is what makes them discoverable at all; the injection budget counts **UTF-16 code
   units**, measured by astral bisection, closing open question 11 outright; **link coverage 1.00**;
   the consolidator ran under the alias `sonnet` resolving to `claude-sonnet-5` **in the harness's
   own transcript**, which measures `harness.md`'s no-column escape hatch true.
   What it opened: open questions 13–15 below.

   **How M16 was executed, and why the obvious reading of the brief is wrong.** The brief says
   "against this repository's own seeded store or a throwaway"; a fresh session reads that as
   *install into this repo*, which is what this session first proposed and the operator corrected.
   - **Under kiro, dogfooding was a *controlled* experiment and the control is easy to lose.**
     `.kiro/agents/zikaron-dogfood.json` carried its **own** `hooks` and `mcpServers`, and its
     prompt says nothing about memory *on purpose*, so the only guidance it gets is the shipped
     write policy. The crew agents were never the subject here. `FINDINGS-archive.md` line ~871
     flagged that Claude Code's directory-scoped settings would destroy this, and it was never
     resolved until now.
   - **The direct translation is dead twice over.** A Claude Code subagent gets no MCP registration
     of its own (frontmatter `mcpServers:` is *silently ignored*) and `UserPromptSubmit` never
     fires for subagents, so a subagent cannot receive push at all. The dogfood agent must be a
     **top-level** session (`claude --agent zikaron-dogfood`).
   - **The arrangement: an empty throwaway at `~/zk-dogfood`**, project-wide install, operator
     driving a memory-naive agent. Not this repo (the crew's wiring and my own memory-saturated
     prompt are confounds) and not a clone of it (drags in the same confounds plus a store).
     A throwaway also tests the **shipped** arrangement rather than a bespoke one, and is the only
     place the inherited approval-gate question is cleanly askable, since this repo may hold cached
     approvals.
   - **The corpus is shell scripting**, operator's choice: conventions plus the gotchas that are
     unlearnable from code (`set -e` not firing in a pipeline without `pipefail`, `[[ ]]` under
     `#!/bin/sh`, `local x=$(cmd)` swallowing the exit code). Fast to test, and it sets up a real
     test of D30's scope line — a convention is *not* derivable from an empty project but *is*
     derivable once three scripts exist.
   - **Recall needs two sessions, not one.** Session 1 works and writes; session 2 starts cold on
     related work while we watch whether it searches unprompted. The baseline is **opened** at this
     boundary, not established. **Done, and the answer was push rather than pull**: the restarted
     session had the convention in its *first thought*, four seconds before it called any tool,
     from the injected block alone — then pulled for the detail. Push triaged, pull deepened.
   - **Measured on the way, and new to this corpus** (`/tmp/zk-settings-probe`, n=1): `claude -p
     --settings <file>` fires a `UserPromptSubmit` hook declared in that file and its stdout reaches
     the model, while the identical command in the same directory **without** the flag gets nothing.
     So hook wiring can be scoped **per launch**, not only per directory — the mechanism that would
     preserve a kiro-style control arm inside a directory hosting other sessions. Descoped from M16
     by the throwaway decision; recorded so it is not re-derived.

1. **The next consolidation, on a journal grown by real work.** That is when open question 12's *positive*
   merge criterion gets designed and tested. The prompt currently has reasons to split and none to merge,
   deliberately, on operator decision — do not revert it on the strength of the 11-merges-to-0 result.
2. ~~**Read the recall instrument.**~~ **— done in M16, and the number is a fresh baseline that must
   not be compared across the harness boundary.** Claude Code, memory-naive `zikaron-dogfood` agent,
   **zero operator nudges**: **0.83 searches per user turn** over 2 sessions and 6 turns, every turn
   containing a search or a write, and of the **3** searches issued after the store held anything
   **0 came back empty** — the other 2 hit an empty store on turn 1. The
   conditions are the number — tiny n, one task family, a store that grew 0 → 4 records *during* the
   measurement. Full table and caveats: `research/claude-code-dogfood-checkpoint.md` §10.
   **The prose was enough for the framing half.** Recall fired on turn 1, unprompted, and the agent
   *named the policy's own occasion in its reasoning first*: "Since I'm about to propose a script
   design, it's worth doing a quick memory search." The proposal gate fired twice in user-facing
   text, including the "found nothing relevant" case it was written for. **Fired as designed, twice,
   unprompted** — deliberately not "it earns its sentence", since the keep-or-wind-down decision has
   its own named criterion and two firings do not settle it; the researcher's objection is withdrawn. **The mechanism half is untouched**: every search
   in the checkpoint happened at task-framing time, so open question 1's mid-task moment — twenty
   tool calls in, where no injectable hook fires — is still the real work.
   Original text: *"`search` calls per session; its pre-change value is **0** across 17
   hours of real work, which is what the recall paragraph was added to move. One working session answers
   whether prose was enough or whether the mechanism half of open question 1 is the real work."*
3. ~~**A byte bound on `gist`**~~ **— done in M14, and it is a *character* bound rather than a byte one.**
   `GIST_MAX_CHARACTERS = 1024`, a fixed constant in `core/indexing/chunking.py`, enforced in the
   preflight ahead of the token bound and reported against field `gist.characters` (the error payload
   carries no unit, so the field name must). **Counted in UTF-16 code units, not code points** — the same
   conservative unit the injection budget uses, because the two halves of one argument must measure the
   same thing; the review caught the first version counting code points here while the budget counted
   units, which made the worst case (five all-astral gists, 11,207 units) exceed the budget the bound
   exists to prove. Units bound bytes because UTF-8 needs at most **3 bytes per UTF-16 unit** — and the
   widest per unit is therefore a 3-byte BMP character, *not* a 4-byte astral one, which is asserted
   rather than assumed. This closes open question 11 for **both** harnesses at once. Two things measured
   while choosing the number, neither previously in the corpus: the injected block's fixed framing for
   five demoted rows is **967 units**, and prose runs **3.89–6.55 characters per token** by style. So the
   ceiling is 1,806/gist, and 1024 puts a five-row block at 6,087 units (61% of 10,000) and 18,261 bytes
   at the 3×/unit worst case (28% of 65,536) — both now asserted rather than hoped.
   **The trade, recorded because it is observable and was not foreseen:** at 1024 the bound cannot be
   reached at the default `gist_max_tokens` of 64 (worst case 363 characters) but *is* the binding
   constraint near the top of that key's 8–256 range — admitting prose at 256 tokens needs ≥1,584
   characters per gist, which puts the same block at 89% of budget. A loud rejection naming the character
   count was judged the better failure than a block that fits by luck. If raising `gist_max_tokens` ever
   becomes real practice, this is the number to revisit.
4. ~~**The installer has no notion of *same install, older version*.**~~ **— fixed in M15.**
   Staleness is now a **content comparison**, which subsumes the old interpreter check and extends it
   to every shipped file — kiro's skill could previously never be refreshed at all, its staleness
   predicate being the constant `False`. It is a **trade**, recorded because the losing side is real:
   content is the only evidence available, so a hand-edited artefact is backed up and reverted rather
   than kept. `architecture.md` §"The install contract" carries the argument and names two ways to
   remove the trade that were deliberately **not** built.

5. **`BudgetUnit.CHARACTERS` is now known to be the ambiguous word, and the D34 table cannot say
   otherwise.** M16 measured the Claude Code injection budget in **UTF-16 code units**, which is
   exactly the distinction "characters" fails to make — and `exceeds_injection_budget` already
   implements it. But `tests/test_harness_table.py::test_injection_budget_value_and_unit` parses that
   table cell for **one number and one unit word**, and the string "UTF-16" carries a digit, so
   naming the measured unit there turns the row unparseable and the test red. Found by doing it.
   The precise unit lives in `harness.md` §"Injection budgets" instead. The honest fix — rename the
   enum and teach the parser a unit containing a digit — is small, is a code change rather than a
   documentation one, and was deliberately not made inside a checkpoint milestone.
6. **A known intermittent**, diagnosed and left: `test_idle_self_stop_unlinks_the_socket_before_the_process_exits`
   fails under load because the signal handlers are installed after the socket is bound. Low impact, wants
   a test that pins the race deterministically.
   **Timing nondeterminism's impact is wider than this one flaky test: the coverage number itself
   varies.** Measured in M16 over three consecutive `./check.sh` runs on a tree whose only diffs
   were comments — **97.64%, 96.85%, 97.64%** — with all 1702 tests passing every time. 0.79 points
   of 5,882 statements is ~46 statements, and the per-file report points at the same *class* of
   cause: `service/server.py` (85%) and `service/lifecycle.py` (90%) are socket-and-timing code
   whose error branches are taken or not depending on how a race lands. **Which** race is not
   localised — no cross-run per-file diff was taken — so do not read this as a prediction that
   pinning the intermittent above would end the flap. **The consequence is about the ratchet, not
   the tests:** `fail_under` is 90% against an actual ~97%, so today the margin absorbs the flap —
   but that margin is the only thing preventing a red gate for reasons unrelated to the change under
   test, and this project has already been burned once by a floor that was not doing its job
   (`check.sh`'s own comment records it). Do not raise `fail_under` close to the observed value
   without pinning the race first.
   **A second instance, measured 2026-08-18 — and the diagnosis moved twice before it was right.**
   Two `test_hook_connect_real_service_integration.py` tests failed deterministically at load ~6.
   First reading: a load-sensitive test. Second: `hook/connect.py`'s `HEALTH_POLL_DEADLINE_SECONDS =
   1.2` is a *product* constant the test inherits, so do not raise it. **The correct reading is
   sharper than both — the test asserted a guarantee the design explicitly declines to make.** That
   constant's own comment says a cold spawn racing it and losing *"is exactly the case that must
   degrade (log to hook.log, relay on stdout) rather than make the user wait"*. Losing is a
   **specified outcome**, covered against a fake service that binds 5 s after spawn. Asserting that
   a *real* cold start wins the race asserts something the product never promised, and whether it
   holds depends on the machine: a real service takes **1184-1235 ms merely to bind its socket**,
   because `main.py` assembles the store and loads the encoder first, deliberately, so it never
   advertises a store it could not open. **The number that constant was calibrated against never
   described this peer** — `spike-results.md` §"Cold start" measured ~101 ms "dominated by Python
   interpreter start" against spike 3's *toy* server, with no store and no fastembed. Fixed by
   giving those two tests their own 30 s deadline via an autouse fixture that states all of this, so
   they assert the mechanism while the shipped value stays asserted where it belongs. Mutation-
   verified: a server that never starts still fails them. **The shipped constant is unchanged, and
   is still right for the user.** What this does leave open, and it is a product question rather
   than a test one: a cold start-if-absent loses the race on a loaded machine, so the warm helper is
   load-bearing rather than an optimisation, and a user message that races it silently loses push.

**Two instrument properties worth knowing before quoting a number.** The dedup signal reports nothing for
30 days unless `signal_horizon_days` is lowered (only the fully-resolved outcome closes early), and
amend-after-surface currently reads `rate=1.00` meaning *3 of 3 resolved pairs* with 51 still pending.

### Harness: kiro-cli and Claude Code, both supported
**The crew moved in M13, and the product finished moving in M15.** `.claude/` carries
memory-researcher, memory-reviewer, memory-assistant, py-runner and the `self-review` skill, plus a
`CLAUDE.md` holding the static half of this document. `.kiro/` stays in the repository unedited — it
is the reference for what the installer ships for that harness, and the fallback.

**What is true now.** Both thin clients and the installer speak both harnesses. `zikaron-hook` reads
either harness's trigger names through `zikaron/harness/`, resolves the session label from whichever
variable that harness exports, and writes each event on the channel that harness delivers;
`zikaron-mcp` resolves the same label the same way; and `zikaron/install/targets.py` writes either
harness's artefacts. **`design/harness.md` is normative for every harness-coupled fact** — read it
before touching the hook, the MCP client or the installer, and do not re-derive one from an older
section of `architecture.md`. The probe evidence that settled these, with the documentation reading
it refuted, is in `FINDINGS-archive.md` §"The Claude Code probe".

**Nothing is installed into this repository**, which is a choice rather than a gap: the memory tools
and the push hook are **not live in this session** until someone runs the installer. `--harness auto`
refuses here, since this repo carries both dotdirs.

Original text, superseded 2026-08-16 by M15: *"**The installer does not**: it still writes kiro
config and only kiro config, which is M15's whole subject."* Kept because it is exactly the
confidently-stale claim this file exists to avoid — a fresh session reading it would have built M15
a second time.

**Decided 2026-08-16: accept a baseline reset.** The recall instrument is read fresh under Claude
Code (M16), and the pre-migration numbers are recorded as a **different-harness baseline that is not
to be compared against** — the harness, the model, the injection position and the write-policy
delivery all change at once. **Do not quietly compare across the boundary.**

**Crew fidelity lost in the move, both deliberate.** memory-reviewer ran `gpt-5.6-sol`; Claude Code
takes Claude models only, so it now runs `fable` — same family, so **cross-family independence is
gone** and an `APPROVED` is weaker evidence than it used to be wherever shared-family blind spots are
plausible. And per-agent write scoping (`allowedPaths`) has no frontmatter equivalent; it is now
stated in each agent's prompt and enforced by nothing. Both are recorded in
`.claude/skills/self-review/SKILL.md`, where the loop that depends on them lives.

## Open questions
1. **Pull is now used, and the instrument cannot say by whom or why — so the question it exists to
   answer is still open.** Recall went from **10 searches to 188** after the 2026-08-05 policy
   change (fetch 17 → 90), measured on `~/Memory` across 898 turns and 4,490 pushed gists: 64, 77
   and 46 in the three real working sessions, spread from turn 29 to turn 443 rather than clustered
   at the start, and productive — **0 of 188 came back empty**, 165 hit the 5-result limit, 32% were
   followed closely by a `fetch` and 32% by a write. On its face the prose fix worked.
   **Two operator corrections removed almost all of that as evidence, and the first reading of it
   here was wrong.** Many of those searches were **explicitly nudged by the operator**, and the
   `search` event records no occasion, so a prompted search and a self-initiated one are the same
   row. And a large share came from **`memory-reviewer`, which runs a different model family
   (gpt-5.6) and searches eagerly**, while the Claude primary agent needs nudging — but every agent
   instance in a session shares one `KIRO_SESSION_ID` (measured in the MCP lifecycle probe), all
   five sessions contain both searches and pushes with no pure-subagent session among them, and
   `client_kind` separates only `mcp` from `hook`. So the log **cannot attribute a search to an
   actor or to an occasion**, and 188 does not measure autonomous recall by the primary agent. An
   earlier revision of this entry claimed the store refuted the agent's self-report; that claim is
   **withdrawn**, and it is this corpus's own "name the quantity before quoting a number about it"
   committed against a live store rather than in a design document.
   **Attribution without new instrumentation, by operator direction: read the time clustering.** The
   researcher works for a stretch and then goes through review rounds, so the reviewer's searches
   arrive in dense intervals. That fits the one shape the data does show whoever searched: recall is
   **bursty** — only **6–11% of turns contain any search**, in bursts of up to 9. If the bursts are
   the review rounds, the primary agent's unprompted rate is *lower* than 6–11%, not higher.
   Recording the caller's pid and an `occasion` argument were both considered and **deliberately
   deferred**: pid is the only discriminator the lifecycle probe found between agent instances, and
   `(session_id, pid)` already exists for consolidation ownership, so the fix stays cheap for
   whenever clustering stops being enough.
   **Under Claude Code the attribution problem is answerable outside the store, for free — for as
   long as the transcripts survive** (M16). *Solved* would overstate it: Claude Code prunes
   `~/.claude/projects/` on `cleanupPeriodDays` (default ~30), so the affordance expires; M16's own
   transcripts are copied into `~/zikaron-m16-evidence/` for that reason. The
   `session_id` is **byte-identical** to the harness's transcript filename —
   `~/.claude/projects/<escaped-cwd>/<session_id>.jsonl`, with subagent transcripts under
   `<session_id>/subagents/` — so a `search` row joins to a full record of who searched and what they
   were thinking when they did. Every quoted line of reasoning in
   `research/claude-code-dogfood-checkpoint.md` came from there, including the agent naming the
   policy's own occasion *before* it searched. That is exactly the "the log cannot attribute a search
   to an actor or to an occasion" limitation above, answered — **externally, and only for this
   harness**, which is why the `occasion` argument stays deferred rather than cancelled.
   **What changed 2026-08-14, from the using agent's own account of why it does not reach out
   unprompted.** Three things, all prose, none in the schema. (a) **The trigger was a category
   requiring a self-assessment** — "search whenever you are about to spend real effort" — and the
   agent's report is that this judgement fails mid-task because *effort feels like progress*. It is
   now four detectable occasions: something surprised you; you are about to propose a design,
   mechanism or plan; you are about to say an approach will not work; you are about to rename, move
   or delete something other work depends on. The third is new and is what the store is most
   directly for. (b) **The injection creates a sufficiency illusion**: five on-point gists make
   memory feel already consulted, while they matched *the user's words* and go stale the moment the
   problem is reframed, with nothing arriving to say so. That is now stated in the **injected block
   itself** (+187 bytes on every push against a 65536-byte cap) rather than only in the policy,
   because the block fires once per message and the policy once per session. (c) **A gate**, which
   the agent ranked first by a distance and which is the only lever carrying its own check: a
   design, a plan, or a claim that an approach is a dead end must state what was searched for and
   what came back, including "found nothing relevant" so silence is not compliance. I argued against
   putting the gate in Zikaron's own policy on scope grounds — a memory system dictating the shape
   of every proposal — and the **operator overruled it, to be wound down if it overfires**; it is
   one sentence, so that is a one-line revert.
   **How we will know if the gate overfires:** searches per turn rising while the fetch-follow rate
   falls below the current 32%, and the burst structure flattening toward one search per proposal.
   The agent predicted that shape itself, about numeric floors: "I would satisfy it hollowly."
   Unchanged below: the mechanism half.
1. **The push hook fires at the wrong moment for half the use case.** `userPromptSubmit` fires **once per
   user message** with `{hook_event_name, cwd, session_id, prompt}`. Good: the query is clean human text.
   Bad: one user message spawns dozens of agent turns, and the moment a memory is most needed ("this
   protobuf step just failed silently") arrives twenty tool calls later, when **no injectable hook fires**.
   Push therefore covers only *task-framing* recall. `postToolUse` fires per tool call and receives
   `tool_response`, but has **no documented stdout→context path**. Options: lean on pull plus D18's
   instruction; use `postToolUse` as a side-channel priming the next injection; or use `stop` (which can
   return `{"decision":"block","reason":...}` as a new user message) as an end-of-turn nudge.
2. **Unweighted RRF is discarding exactly the signal an embedder upgrade would buy.** The strongest finding
   of the benchmark, and unasked-for. Dense-only, `bge-large` **beats** `bge-small` (MRR@10 **+0.0705, CI
   [+0.0283, +0.1156]**); the RRF hybrid **erases it** (0.922 vs 0.938). Mechanism measured: all **960 of
   960** fused top-5 slots are held by documents *both* arms returned, while the arms intersect in only
   ~28% of their union — so ~72% of the candidate pool structurally cannot reach the injection budget. Ties
   were investigated as the cause and **refuted** (max movement 0.0052). RRF `k`, arm weighting and fusion
   depth deserve their own pass; plausibly worth more than any model swap. All three are now named `meta`
   keys (`rrf_k` 60, `fusion_depth` 50) rather than constants, so the pass is a config sweep. Needs no
   reindex, so it is safely post-build. Detail in `design/retrieval.md`.
3. **The real length distribution of memories is now partly measured, and chunking turns out to be a
   *post-consolidation* phenomenon.** First real data, from 31 journal entries and the 15 long-term
   records consolidation made of them: journal entries ran **162–378 tokens** (median 259) against a
   `chunk_max_tokens` of 450, so **not one of them chunked at all**. The consolidated records run
   **184–1877 tokens**, and **9 of 15 chunk**, up to 6 parts. So the chunking path — and the dense
   arm's `max` rollup over parts — was at first credited to **merging specifically**, on the strength of
   the A/B: run 1 (11 merges) produced 9 multi-chunk records of 15, up to 6 parts, while run 2 (0
   merges) produced **0 of 31**, all 162–378 tokens. **That attribution was wrong, and a second working
   session refuted it within a day.** 26 entries written during real work ran **230–879 tokens** and
   **8 of them chunk**, one into 3 parts, with no merging involved at all. So chunking follows entry
   *length*, regardless of provenance, and the first day's corpus was simply uniformly short — a
   seeding session summarising known facts produces shorter entries than live work does. The
   distribution over all 93 authored writes so far: **162–879 tokens, median 273**, against a
   `chunk_max_tokens` of 450.
   **M16 adds a third driver, and it is neither length-at-write nor merging: a record can *become*
   chunked by being amended.** One dogfood record went **377 tokens / 1 chunk** at `remember` to
   **1025 tokens / 3 chunks** at `amend`, when a reframing made the original half-wrong and the agent
   rewrote it to carry both the new finding and the rejected alternative. So the repair loop D11 is
   built on is itself a growth mechanism, and a corpus's chunk distribution drifts with how often its
   memories are corrected rather than only with how they were written. The lesson about the claim rather than the parameter: one day of one
   corpus attributed a phenomenon to the wrong cause, and only a differently-shaped session could tell. 450 looks comfortably above the natural length
   of one written lesson and comfortably below a merged record. Original text below.
3. **The real length distribution of memories is unknown.** D28 settles the chunking mechanism, but its
   parameters rest on zero real data, and the benchmark's six over-length fixtures turned out to be one
   template wearing six hats. `token_count` and the `truncated` canary are instrumented so revisiting
   `chunk_max_tokens` — and chunking itself — becomes a measurement.
10. **Takeover's caller is specified and its premises are now measured — one item remains open.** The
   consolidation lease is taken over by an explicit `plan_groups`, on the reasoning that a human
   reinvoking the skill is the only liveness evidence that exists. A targeted review caught that nothing
   *converted* that invocation into the call: a fresh consolidator's own first tool call is `next_group`,
   which refuses a live foreign run, so the takeover path was unreachable through the real client path.
   The bridge is now **built and tested, not only specified** — `zikaron-mcp` calls `plan_groups` with its
   own `(session_id, pid)`, **lazily, immediately before the first `next_group` it forwards, and at most
   once *successfully* per client process**, exactly the three-state machine (`unplanned | ready | failed`)
   M10's `_PlanBridge` implements, including its own awkward transition (a first `plan_groups` answering
   `store_busy` leaves the client `unplanned` so a retry replans) and, found during M10's own review, its
   cancellation edge: a tool call cancelled while `plan_groups`'s *response* is still in flight moves the
   bridge straight to the terminal `failed` state rather than back to `unplanned`, since the takeover may
   already have committed on the service side by the time the cancellation reached the client, and a
   mistaken retry there would risk the second successful takeover the whole "at most one" bound exists to
   rule out.
   **Both premises were measured 2026-08-02** (`research/kiro-mcp-lifecycle-probe.md`): kiro runs one MCP
   server process **per agent instance**, so each invocation carries its own fresh takeover guard — the
   process supplies the guard, not a limit on attempts, since a failed plan displaces nobody; and the handshake is
   **eager**, which is why the call is made lazily on the first forwarded `next_group` — a start-wired call
   would take the
   lock before the model had been asked anything, so a spawn that then did nothing would displace a live
   worker for nothing. The operator's constraint, stated directly: *do not take the consolidation lock
   unless we plan to consolidate.* **Still open:** whether kiro ever restarts a client mid-subagent for its
   own reasons, which would supply a fresh guard for the next forwarded `next_group` to consume with no new
   human invocation behind it. Three instances showed no such restart,
   which is weak evidence at that sample size, and nothing depends on it being false — a spurious takeover
   costs one worker's in-flight reasoning, never a journal row.

4. **Hook→service transport: designed, and now smoke-tested (M0, spike 3).** D31 settles the shape.
   **Resolved 2026-08-01:** RPC round-trip latency (cold start-if-absent ~101 ms end to end, dominated by
   interpreter start; warm p50 0.146 ms over an established connection); `busy_timeout` at 5 s behaves exactly
   as documented under two real writers, once the service's own blocking `sqlite3` calls are kept off the
   event loop — getting that wrong produces a self-inflicted deadlock that *presents* as a `busy_timeout`
   failure, which is now a normative note in `design/architecture.md`; start-if-absent holds under two clients
   racing the same cold store, converging on one server with no thundering herd; and the connect-as-server-
   exits race is real and reproducible, with the client's own retry-through-start-if-absent logic recovering
   unmodified. Measurements: `research/spike-results.md` §"Spike 3". **Still open:** none of this was measured
   from an actual hook process invocation (the spike used a plain client script, not the real
   `zikaron-hook`/`zikaron-mcp` clients, which do not exist yet), and **whether a consolidation lease survives
   a service restart in practice is untouched** — M0 had no consolidation state to restart against. Both are
   real integration-test material for M9 rather than open design questions. **Three earlier sub-items closed
   2026-08-01.** The `/proc`-ancestry unknowns
   (process topology, Linux-only `/proc`, pid namespaces, the MCP-first race) are gone with the rung — see
   current-state item 4. The round-7 `session_client` resolution-write cost is gone with the write: the preamble
   no longer touches the store. And **where hook stdout lands is now partly answered**: it arrives as a context
   entry framed *"I have gathered this context from valuable programmatic script hooks"*, positioned **before**
   the user message in the same turn. **The size-cap half is now closed and the answer is a number**: every
   object-format hook entry takes `max_output_size`, default **10240 bytes**, and overrunning it truncates
   **silently**. Shipped entries state **65536** explicitly. What that does *not* buy is a proof — see open
   question 11. What stays open here is that placement is *early*, which contradicts `~/Memory`'s "place
   surfaced memories late" lesson; we cannot choose.
   Worth noting the framing instructs the model to follow requests found in the injected text, directly against
   the untrusted-reference-data preamble `retrieval.md` puts on the push block. Still to carry from
   `~/Memory`: keep surfacing ephemeral and exclude it from the summarizer input — kiro exposes
   `compaction.excludeMessages` and `compaction.excludeContextWindowPercent`.
5. **What tells the agent *why* a demoted memory is being shown?** D25 keeps superseded records surfacing
   rather than hiding them, and D27 cut provenance to three fields. **Narrowed by the corpus review:** the
   display half is now specified — the injected block labels a demoted row and names its replacement's uuid,
   and every retrieved replacement is ordered ahead of every record it replaced
   (`design/retrieval.md` §"Supersession: eligible, demoted, and labelled"; round 2 replaced an
   unsatisfiable "immediately above" rule with this precedence rule, since a merge gives several rows one
   shared replacement; round 3 added the dead-lineage case — an ordinary `retire` of a replacement is legal
   and makes a *terminal component*, so `fetch` now reports `superseded_by_latest_state` and the block's label
   deliberately names only the immediate replacement, keeping the graph out of the ranking path). What stays
   open is *editorial*:
   D27 keeps no reason-for-supersession field, so the block can say "replaced, by that" but not "because the
   pin was bumped", and nothing measures whether the agent needs the reason or whether fetching the
   replacement suffices.
6. **Residual staleness under D11.** The repair loop only fires when a memory (a) surfaces, (b) is acted on,
   and (c) fails *loudly* enough for the agent to attribute the waste to it. It misses silently-obsolete
   memories and memories that stopped surfacing. A known limit, and after D27 there is no cheap mechanism
   behind it. One idea that survives D27's objection: an `amend` variant meaning "confirmed, no change",
   which would make `updated_at` mean *last confirmed working* — real freshness evidence with no false
   positives. Parked, because it adds a discretionary verb and cuts against open question 7.
7. **Write discipline.** Delivery is settled (D18); the content is a v0 draft to experiment against (D30).
   `~/Memory`'s evidence says under-writing dominates, so the draft biases toward recording. Six
   deterministic signals are instrumented to reveal which way it actually errs. Still unaddressed: how much
   detail belongs in `content` versus `gist`, and when to supersede rather than amend in place.
8. **Does model capacity actually help identifier discrimination? Still untested.** The counterfactual
   instrument confirms the weakness is **mechanistically real** — discrimination index **0.194–0.233** for
   all four models, direction right in 14/14 blocks (sign test p≈1.2×10⁻⁴), margin thin. `bge-large −
   bge-small` on that index is **+0.029, CI [−0.016, +0.062]** against a preregistered 0.15 bar, so no
   demonstrated remedy. But fastembed serves a *quantized* small against an *unquantized* large, so this
   compares deployed artifacts, **not** capacity. Matched fp32 exports of one family would settle it.
11. ~~**Nothing bounds a gist's length in bytes, and the hook's output cap is therefore unprovable.**~~
   **CLOSED in M14, and its last assumption removed by measurement in M16** — by a **character** bound
   rather than the byte bound this entry proposed, counted in
   UTF-16 code units, which bounds bytes for both harnesses at once. **M16 measured the unit itself**,
   by the astral bisection `harness.md` reserved for it: 6,000 astral code points (12,000 UTF-16 units)
   **truncate** while 4,600 (9,200 units) survive, which refutes the code-point reading; bytes were
   already refuted by 27,016 B of `漢` arriving whole. UTF-16 code units survive all five data points.
   So `exceeds_injection_budget`'s unit is now the **measured** one rather than the conservative one
   that merely upper-bounded the candidates. Detail and the arithmetic: current-state
   item 3. The original text stands below, per this project's withdraw-in-place rule; the diagnosis was right
   and only the unit was wrong.
   Original text:
   **Nothing bounds a gist's length in bytes, and the hook's output cap is therefore unprovable.**
   Found at distribution time, measured rather than reasoned: `gist_max_tokens` (default 64, maximum 256)
   bounds **tokens**, and the deployed WordPiece tokenizer maps anything outside its vocabulary to a single
   `[UNK]` — so an unbroken 4000-character run counts as **one token**, as do 256 emoji. A gist that passes
   every bound the write path states can therefore be arbitrarily long in bytes, and five of them overflow
   any `max_output_size`, after which the harness truncates the injected block in silence. Ordinary prose
   is nowhere near it: the shipped policy is 2950 B and five prose gists at the 256-token ceiling are a few
   kB, both far inside 65536. The fix is a byte bound on `gist` in `schema.md` §Bounds — a write-path
   change, deliberately not made inside a distribution milestone. Asserted as a test
   (`tests/test_install_limits.py`), stated in `architecture.md` §"The install contract", and named in the
   README's troubleshooting notes so it is not a limit only a test knows. **An earlier version of that test
   asserted the opposite**, by multiplying tokens by an invented four-bytes-per-token factor and calling the
   product a worst case — the review caught it, and the lesson is the corpus's own: name the quantity before
   quoting a number about it.
12. **Merging degrades the gist's triage value, and the tension is structural.** Measured on the first
   real consolidation: **6 of 15** long-term gists came back index-shaped — "three live-debugging
   findings: …, …, …" and, worst, "illness/felt-state+energy findings: placement, attribution,
   code-vs-prompt, severity scale, time-freeze, chronotype calibration" in front of 1877 tokens of
   content. The originals were symptom-first one-liners ("grepping session.log for prompt text returns
   zero because it never logs assembled prompts"), and the consolidator kept that shape wherever it
   promoted a single entry. It could not for a merge, and that is arithmetic rather than disobedience:
   one 64-token gist cannot lead with the observable symptom of six different findings. **The damage is
   asymmetric between the two read arms**, which is what makes it a design question rather than a
   prompt tweak: D21 embeds gist *and* content, so pull survives — a symptom-shaped query still
   returned the right record at rank 1 — while the injected block shows gists **only**, so push
   degrades exactly where D13's relevance triage lives. Levers, none yet tried: a stricter merge
   cutoff so fewer unlike findings fuse; permitting a longer gist on a merged record; or having the
   block show something other than the gist for a multi-finding record. Nothing in the corpus named
   this before it happened.
   **The lever was pulled and measured against a byte-identical store, and it over-shot: 11 merges
   became 0.** Run 1 (old prompt) turned 31 journal entries into 15 long-term records — 13 created, 23
   absorbed, 2 in-place flips, 5 merge targets. Run 2 (new prompt, same store restored from backup)
   promoted all **31 in place**, byte-identical prose, zero merges and zero new rows: consolidation
   flipped tier bits and did nothing else, so the long-term tier is now a copy of the journal.
   **And on this corpus that may well be the better outcome**, which is what makes the result awkward
   rather than clean. Run 1's merges look like exactly the over-fusing `consolidation.md` warns about —
   "two appraiser pitfalls" fused two distinct failures of one component, and "three live-debugging
   findings" fused three unrelated gotchas that merely shared arc vocabulary. Corroborating: **zero
   identical gists** in the corpus, and the 7 dedup offers (0.80–0.84) were judged false positives
   independently by the writing agent, the consolidator, and this session.
   **The decisive limitation is that neither run tested what consolidation is for.** The motivating
   case is the same lesson arriving twice, weeks apart — "the protobuf lesson learned today and the
   protobuf lesson learned three weeks ago". All 31 entries were written in **one session by one
   agent**, so no such pair exists. Run 1 merged things that should not have merged; run 2 merged
   nothing; neither had a true duplicate available to merge. So this experiment cannot distinguish
   "correctly refuses bad merges" from "refuses every merge", and tuning further against it would be
   fitting to a corpus with no positive examples in it. The next real test needs a journal containing a
   genuine repeat, which means a second working session rather than another prompt round. What the
   prompt still lacks is the *positive* criterion — it now has reasons to split and none to merge.
   **M16 adds the first split judgment with a concordant second judgment, and a second route to the same
   damage.** On the dogfood corpus, grouping put two records in one group (cosine **0.876**) and the
   consolidator **split** them, promoting both in place with gists byte-identical — reasoning
   *"preferring sharp distinct records over one combined summary"*, the 2026-08-04 change quoted back.
   That verdict has a **concordant second judgment**: the **writing** agent had already rejected the
   same pair as a dedup offer, with the same reasoning. Both earlier runs had nothing to score against.
   **Concordance is not independence and neither is ground truth**, and an earlier revision of this
   entry claimed both: the writer runs `opus` and the consolidator `sonnet`, the **same family**, so a
   shared blind spot is plausible rather than excluded; and **both prompts were revised in the same
   anti-merge direction on 2026-08-04**, with the consolidator quoting its half back verbatim. Two
   correlated judgments agreeing, not two votes — and no human ever labelled the pair.
   **And it is the second consecutive zero-merge outcome** (`~/Memory` run 2: 0 of 31; here 0 of 2 —
   run 1's 11 merges preceded the prompt change), and
   refusing was *correct* here, so it is consistent with both "correctly refuses bad merges" and
   "refuses every merge" and **does not break that tie**.
   **And the index-shaped-gist damage has a second cause that has nothing to do with merging**: the
   same agent folded a *universal* fact — "a POSIX shell cannot hold a NUL byte", true of every POSIX
   shell everywhere — into a record about one script, saying so explicitly (*"folding the NUL-byte fact
   into this same entry rather than creating a separate general fact"*). It will now surface only for
   that script's queries. So one record doing several jobs arises from **amendment** as well as from
   consolidation, and only the consolidation route was ever named here.
   **Operator decision 2026-08-04: the prompt stays as it is, and is not to be reverted on the strength
   of this result.** Reverting would trade a measured over-correction for a measured over-fusion, on a
   corpus that cannot adjudicate between them; the next consolidation runs against a journal grown by
   real work on `~/Memory`, and that is when the positive criterion gets designed and tested.
   **First lever applied 2026-08-04, and both prompts gained a measured length rule alongside it.**
   The consolidator is now told that an inability to lead with one observable symptom is evidence the
   entries are not one finding, and to prefer two records with sharp gists over one with a table of
   contents — the design's own "over-splitting costs one extra call while under-splitting manufactures
   a false record" argument, applied to the gist rather than to the group. Effect unmeasured: it should
   trade record count for push triage, and only a second consolidation on a fresh journal will show by
   how much. Separately, both texts said only "keep it short; over-long gists are rejected", which
   leaves an agent to discover the bound by losing a call — measured across the 49 real gists in the
   two stores, they run **22-53 tokens (median 34, 10-32 words) and not one exceeded the 64-token
   bound**, while 28 words of ordinary technical prose measures 32 tokens, so the ceiling is roughly 50
   words. Both prompts now say "one sentence of about 20 to 25 words", name the 64-token limit and its
   word equivalent, and state that exceeding it costs the call. Worth noting for anyone chasing this:
   a bounds rejection writes **no event**, so a gist that was refused leaves no trace in the store —
   which is why the one the operator saw rejected is invisible to every query above.
9. **Evaluation** (deferred by D14). Grok named LoCoMo, LongMemEval(-V2), BEAM, HaluMem, LongMemCode,
   PersonaMem, LifeBench, AFTER, EvoMemBench; several may be misremembered, and all are conversational or
   codebase-QA proxies rather than tribal-knowledge tests. The benchmark set is the seed but its residual
   threats are the work: 187 synthetic memories is 1–2 orders below real scale, relevance labels were
   authored by the same agent that wrote the corpus, and query-set independence is attested rather than
   mechanically provable. Real memories from a real repository with independent annotators is the fix.
13. **The write policy contains two scope rules that disagree, and an agent obeying it cannot obey
   both.** Opened by M16. The policy says *"could you learn it by reading the code? If yes, leave it
   out … This store is for what cost someone time to discover"* **and** *"Not worth recording: …
   facts about a language or tool in general rather than about this project."* `[[ -f ]]` follows
   symlinks is not learnable from this repo's code and cost a real bug (rule 1 admits it) and is a
   fact about a tool in general (rule 2 excludes it). The dogfood agent resolved toward the
   prohibition and said so.
   **An earlier version of this entry blamed the agent for drifting from the policy; that is
   withdrawn** — grepping the shipped text before propagating the claim is the only reason it did not
   reach the design. **The agent's own boundary is coherent and may be the right answer**: it excluded
   the general bash fact and *recorded* "`find` here is a shell function wrapping bfs", equally a fact
   about a tool but about **this environment**. General-tool-behaviour out, this-environment-behaviour
   in — which is neither sentence's stated rule. What has to be decided is which rule governs
   general-but-hard-won knowledge. **The conflict is one quadrant, and it is plausibly the largest one**: general
   facts that are not learnable from this code and cost time here — `set -e` not firing in a pipeline
   without `pipefail`, `[[ -f ]]` following symlinks, `local x=$(cmd)` swallowing the exit code. Much
   of what bites a coding agent plausibly lives there — an argument from experience, not a measurement. Three costs follow: two agents obeying one policy make
   different calls on the same fact, which is a correctness problem for a shared store; whichever rule
   governs governs the highest-volume category; and consolidation inherits the ambiguity, since it
   cannot judge "is this one finding?" consistently against an inconsistent scope.
   **The tempting fix — recast the test as "will this bite someone again here?" — should be rejected,
   by this corpus's own evidence.** The 2026-08-14 change replaced "search whenever you are about to
   spend real effort" with four *detectable occasions* precisely because a self-assessment fails
   mid-task; "will this recur?" is the same shape of prediction and fails the same way. Prefer a test
   evaluable by inspection.
   **RESOLVED and shipped 2026-08-16: a general fact enters as the decision it forced here, not as an
   encyclopedia entry.** The "not worth recording" clause now reads *"a general fact about a language
   or tool on its own — record the decision it forced here instead"*, with a worked example. That keeps
   rule 2's encyclopedia out, honours rule 1's "cost someone time" by recording the consequence, and
   leaves the record genuinely about this project — and it is what the dogfood agent produced anyway
   when it wrote its convention record. It is also **evaluable by inspection**: "what did this fact
   make me do here?" is a question about the past, and if the answer is nothing it stays out.
   **The example is deliberately not shell-shaped**, on operator direction: a language-specific example
   in a general-purpose policy biases the agent, and ours would have overfitted the policy to the one
   corpus we happened to dogfood on. It uses a test runner, which every ecosystem has.
   **Rejected on the way: recasting the test as "will this bite someone again here?"** — it predicts
   value best but is a *prediction*, and the 2026-08-14 change replaced a self-assessment with four
   detectable occasions precisely because self-assessment fails mid-task. Same shape, same failure.
   Widening has a real cost — a store of manual-copyable trivia is
   what rule 2 exists to prevent, and that is why the clause narrows the *form* rather than the scope.
   The constant and `design/write-policy.md` moved in lockstep;
   `tests/test_hook_write_policy.py` parses the document and compares. **Checked, not assumed:** the
   consolidator prompt carries gist-*authoring* guidance but no scope language, since it decides
   grouping and merging rather than what to record, so it needed no mirror.
   **Unmeasured, and named as such:** whether this changes what agents actually write. The M16 write
   corpus is n=4 records.
14. **Zikaron collects preferences into a store that is designed not to bind.** Surfaced by the dogfood
   agent unprompted: *"memory is explicitly framed as reference material, not directive … if the user
   wants a standing behavioral preference actually enforced, `CLAUDE.md` is the right mechanism, not
   memory."* `retrieval.md`'s untrusted-reference preamble is correct and is what stops a poisoned store
   steering the agent — but a standing preference is exactly the class that wants to be binding, and the
   write policy explicitly invites them (*"conventions and preferences that are settled but written down
   nowhere"*). D1's scope line says nothing about this. Three ways out: declare preferences out of scope
   and have the policy redirect them to the instruction file; keep them and state in the policy that they
   are advisory, so an agent is not misled about their force; or a record class the block presents
   differently, which cuts against the untrusted-reference stance and needs the poisoning argument
   re-examined first. The agent reached the middle option on its own, which is evidence the seam is
   findable rather than confusing.
15. **Records cross-reference each other by gist prose, and a gist is not a stable address.** Observed
   twice in M16, once per session — twice in two sessions by one agent on one model is a pattern worth
   designing for, not yet a law: *"the record whose gist
   begins 'dirdiff.sh is POSIX sh for BSD portability'"*. The schema has no relation field but
   `superseded_by` (D27), so the agent built a soft link out of prose — and **that gist had already been
   rewritten once**, by an `amend` four minutes earlier. The failure is the
   worst-shaped one D11 can catch least: nothing fails loudly, the reference just stops resolving.
   **The agent had the uuid both times** — in the dedup payload and in its own `fetch` — and
   *preferred* gist prose as the address anyway. So this is a choice rather than a workaround for a
   missing identifier, and that is what motivates fixing the *form* of the reference rather than
   exposing uuids better.
   **The first proposed fix — "cite by uuid, never by gist text" — was wrong, and the operator
   refuted it the same day.** Three counts. A uuid is **opaque to a human**, and this store is meant to
   be auditable and user-editable. A uuid **cannot be re-found semantically** when it does fail — store
   rebuilt, copied between projects, or a digit hallucinated — while prose degrades into a search. And
   **a hallucinated uuid is undetectable** where a hallucinated description is obviously wrong to a
   reader, which matters because the agent authors the citation from what it just read. The specific
   worry that prompted the proposal does not even hold: `fetch` calls `load()` with **no active
   filter** and returns `active` as a field, so D16's never-`DELETE` rule makes a uuid permanent — a
   retired record still resolves. The evidence was also weaker than stated: a citation quoting a
   rewritten gist stays *usable*, because a reader resolves it by searching rather than by exact match.
   **So the defect is narrower and the fix is one word.** It is not prose-instead-of-uuid; it is
   **quoting a mutable field verbatim as though it were an identifier**. A citation to the *subject*
   ("the dirdiff.sh POSIX/BSD portability record") has none of the problem; one that quotes today's
   gist string does. A uuid is at best a belt-and-braces addition alongside the description, never the
   primary.
   **RESOLVED and shipped 2026-08-16**, one line in the policy beside the gist guidance: *"Point at
   another record by its subject, not by quoting its gist. A gist is rewritten whenever its record is
   corrected, so a quoted gist becomes a pointer to text that no longer exists."* A second reason this
   beats a uuid, noticed while checking whether the consolidator prompt needed a mirror: **consolidation
   is the actor most likely to rewrite a gist**, and a subject-shaped reference survives that *by
   construction*, with nothing needing to be told to the consolidator at all.
   Whether a real relation field is wanted is a separate and larger question that D27
   deliberately closed once.

