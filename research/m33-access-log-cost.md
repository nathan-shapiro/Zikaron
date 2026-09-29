# What the access-log row costs a caller

> **Closed 2026-09-28. The operator accepted the cost as measured; the write is not moved.** The bar
> below should not have been written: it gated a per-call delta of about 1 ms against a
> `push._DEADLINE_SECONDS` of 2,000 ms, and the first figure it produced — `memory_surface`'s p95 two
> orders of magnitude inside that budget — was already the answer. Everything after that refined a
> number nobody was going to act on. **Read this for the mechanism if you need it; do not reopen it to
> improve it.**

Re-derive with `.venv/bin/python experiments/m33_access_log_cost.py 300`, **on an idle machine** — the
condition the bar below names. The script prints `load1` before and after, the store connection's
`synchronous` and the scratch filesystem, so a run says for itself whether it met the condition and
whether the two things this project does not set were what the measurement assumed.

## The bar, set 2026-09-28 before the run

Preregistered on M26's precedent, and written above the results so that "preregistered" is checkable
by its position on the page.

**The idle per-call delta — the treatment arm's latency minus the control's — must not exceed
p50 1.0 ms and p95 2.0 ms.**

Anchored on this project's own measurement of the closest comparable write rather than on a guess.
`research/m24-counter-write-cost.md` measured a four-row `UPDATE` inside `in_one_transaction`, on its
own connection, against an idle database on this machine: **p50 0.743 ms, p95 1.215 ms**, n=50. The
access log's write does *less* — one `INSERT` rather than a four-row `executemany` — on a connection
with `synchronous = NORMAL` and `wal_autocheckpoint = 0`, so it is a WAL append with no `fsync` and no
checkpoint where M24's was a synced commit. Exceeding M24's p50 by more than about a third, or its
p95 by more than about two thirds, would mean the write is not the thing it is designed to be. Rounded
to 1.0 and 2.0 ms.

**And under a writer interleaving short transactions, `memory_surface`'s p95 must stay inside
`push._DEADLINE_SECONDS` (2.0 s) in the treatment arm wherever the control's is.** That is the budget
the row is capable of breaking — M17's defect was exactly a cold-start sequence pushed past it — and
the conditional form matters: a control already outside the budget would say the load was too heavy,
not that the row was too expensive.

**A miss decides something.** It moves the write after `writer.drain()`, *inside* an activity bracket
widened to cover the drain — or idle self-stop could fire between the response and the row — or it
reopens the private connection's pragmas. The number is not written down for its own sake.

## Why the idle delta is the figure that matters

It is what **every push pays**, on every user message, whether or not anything else is contending.
The loaded arm answers a different question: whether the row can break the one latency budget in this
system that a user notices.

**Both arms run on the same machine at the same load, interleaved sample by sample rather than in
blocks**, because a figure from another day is not a comparison and a block per arm lets machine
drift land entirely on one of them.

**The loaded condition changed once and its figures are not comparable across that change.** The
background writer's `meta` upsert wrote a *constant*, which SQLite overwrites byte-identically without
dirtying the page — so it took the write lock and committed nothing, and the condition was lock
contention with no cache invalidation, which is not what another writer does to a store. Its value now
changes per transaction. Loaded figures from before that fix understate contention: the landed-row count
fell from 296–297 of 300 across those runs to **261 of 300** once it was real.

## Results, 2026-09-28

**`load1` 0.58 at the start and 0.52 at the end** — the idle condition the bar names. n=300 per arm per
condition, one machine, arms interleaved sample by sample. §"Against the bar" reads the verdict across
every run rather than this one.

| | p50 | p95 | max |
|---|---|---|---|
| **null arm**: unlogged against unlogged, effect zero by construction | **0.021** | **1.077** | 7.102 |
| **the row write alone**, idle (300 of 300 rows landed) | 0.249 | 0.353 | 0.444 |
| `memory_surface`, control, idle | 5.166 | 8.789 | 16.327 |
| `memory_surface`, treatment, idle | 6.146 | 10.303 | 23.601 |
| **paired delta per call**, idle | **1.049** | **2.996** | 14.115 |
| **the row write alone**, under the writer (297 of 300 landed) | 0.271 | 0.441 | 0.548 |
| `memory_surface`, control, under the writer | 4.980 | 8.054 | 20.432 |
| `memory_surface`, treatment, under the writer | 6.090 | 11.175 | 22.160 |
| **paired delta per call**, under the writer | 0.957 | 2.311 | 15.512 |

All figures in milliseconds. Standard deviation of the paired delta: **0.779 null, 1.250 treatment**.
**Every under-the-writer row here, and in the split below, predates the writer fix above**, so they are
the weaker contention condition; the idle rows are unaffected.

### Where the delta sits — a later run, `load1` 0.71, n=300

The run above says how much the row costs. It does not say *where*, and the remedy below reaches only
one of the two places — so the delta is split at the dispatch seam. `_run_handler` already computes the
handler's own elapsed time for the row's `duration_ms`; the harness captures it on **both** arms, the
control's copy existing nowhere else because the control writes no row.

**Both halves are paired per call, and the additive check is on means** (§"What this note got wrong").

| no background writer | p50 | p95 | mean |
|---|---|---|---|
| handler alone, control | 4.796 | 6.414 | 5.055 |
| handler alone, treatment | 5.057 | 7.032 | 5.358 |
| outside the handler, control | 0.053 | 0.082 | 0.057 |
| outside the handler, treatment | 0.563 | 0.866 | 0.591 |
| **paired handler delta** | **0.249** | 1.435 | **0.302** |
| **paired outside delta** | **0.508** | 0.786 | **0.534** |
| paired whole delta | 0.753 | 2.019 | 0.836 |

**The means add exactly, which is the only form of that check that holds**: 0.302 + 0.534 = 0.836
against a measured 0.836. Under the writer in the same run the split reads **0.416 inside and 0.668
outside**, adding to 1.083 against 1.083, with p50s of 0.387 and 0.630 against a whole of 1.023.

**"Outside the handler" is not only the row.** It also holds parse, envelope resolution, encoding and
the activity bracket — which is why it is read as an arm *difference*: the control pays all of that
too, and its own figure, 0.053 ms, is that floor.

### The handler-side cost is a page-cache reset: any committer, not this row

**A checkpoint cannot produce it.** `wal_autocheckpoint` is threshold-gated, so on the shared connection
it fires once per some hundreds of commits — a tail over a median near zero, where what is measured is a
shift *in* the median: 0.249 p50 against a 1.435 p95 in the table above. The shape rules it out with no
run needed.

**Two candidates act on every call.** A **page-cache reset**: a WAL-mode connection that begins a
transaction after another has committed sees a changed wal-index header and drops its **entire** cache,
re-reading every page *it* touches. So the cost is a function of the timed call's own footprint and is
**independent of how many frames the foreign commit wrote** — one frame changes the wal-index header
exactly as six do. A **deferred `fsync`**: the access log commits at `NORMAL`, and the next
`surface_call` commit at `FULL` syncs the WAL *file*, so the row's frames ride that sync — which would
only fire for an unsynced writer.

`_foreign_commit_probe` separates them on the axis the reset is *insensitive* to, with the access log
closed on both `memory_surface` arms and the only difference a third connection's commit landing
immediately before the timed call.

**It certifies itself, and the control is the mechanism's own counter.** `PRAGMA data_version` reads the
pager's `iDataVersion`, which `pager_reset` increments as it clears the cache — so an arm at 600 of 600 is
the reset *observed running*, not inferred, and an arm at 1 of 600 never fired it. That read is on the
shared connection, so it is what clears the cache; the timed call that follows begins with the cache
already empty and pays the re-read, which is the cost. The clear itself is microseconds. **In production
there is no such read and the handler's own `BEGIN` does the clearing** — same cost, one fewer statement,
so the probe times the re-read rather than an artifact of its own instrumentation.

| foreign-commit probe, n=300, `memory_surface` paired p50 | `data_version` moved | p50 |
|---|---|---|
| `meta`, value unchanged — outsider `NORMAL` | **1 of 600** | −0.047 |
| `meta`, value changing, one frame — outsider `NORMAL` | 600 of 600 | **0.140** |
| row-shaped `event` insert — outsider `NORMAL` | 600 of 600 | **0.156** |
| row-shaped `event` insert — outsider `FULL` | 600 of 600 | **0.197** |

**Six frames cost within 0.02 ms of one, where a per-frame cost would put them about 0.7 ms apart** —
eight standard errors away, and what a whole-cache reset predicts. The probe cannot see a per-frame
component below about 0.02 ms a frame, and the conclusion does not need it to. So the mechanism is the
reset, and the cost belongs to *any* connection committing before the next call rather than to anything
about this row.

**The arm that read as nothing had written nothing, and the positive control is what says so.** A `meta`
upsert whose value is a constant is a byte-identical overwrite: SQLite compares before it writes, the
page never dirties, and the commit never reaches the WAL — so `data_version` moved on **1 of 600** of
those commits, the first. That arm never fired the mechanism it was read as excluding.

**The deferred `fsync` is excluded by the `FULL` arm alone.** There nothing is deferred, and the cost is
0.197 anyway — so 0.197 is not a deferred sync. The `NORMAL` arm then adds nothing to it above the
probe's floor: it reads 0.04 ms *lower* than the synced arm, which is the wrong sign for a deferral and
inside the resolution either way. So the row's frames ride the next caller's sync at no measurable cost,
which is what this design's per-connection *"no `fsync`"* needs to also be true per call.

**The conditions the conclusion rests on are printed by the run, because this project sets neither.**
`ddl.PRAGMAS` sets no `synchronous`, so the shared connection's mode is the build's compile-time
default — **`FULL` (2) on SQLite 3.45.1 here**, without which the `FULL` arm above syncs nothing. And
the scratch filesystem decides whether a sync costs anything at all: **`/tmp` on ZFS**, not tmpfs.

**Three pragmas move between the sync-mode arms, not one.** `ACCESS_LOG_PRAGMAS` differs from
`ddl.PRAGMAS` in `busy_timeout` and `wal_autocheckpoint` as well, and the whole tuple is swapped. Only
one of the three can reach the surface half's median: `busy_timeout` never binds in a sequential probe,
and `wal_autocheckpoint` decides only whether a checkpoint runs untimed in the outsider or timed in the
shared connection, which is a tail. **The row-write halves are not that clean** — their levels differ
between arms by more than the same write should, and threefold in an earlier run that did not reproduce;
the arm order is never varied, which is the confound left open. Since no conclusion reads those levels,
they are not tabulated. **Their paired deltas do have one reader**: the private connection is reset by
every `surface_call` commit too, so *"after one"* against *"no foreign commit"* bounds that share of the
row's own await — at **0.039–0.105 ms paired p50** across the four arms, a fraction of the ~2× excess over
the isolated write below.

**What the probe bounds and what it does not.** The probe's own arms have a paired standard deviation
near 0.8 ms at n=300, so their median's standard error is about 0.06 ms and ~0.1 ms is this instrument's
floor, with nothing below it measured. (The A/B's treatment delta is noisier — sd 1.250, standard error
~0.09 — which is why §"Against the bar" quotes that figure instead; they are different distributions,
not two answers to one question.) The reset scales with the pages the timed call re-reads, and `_SEEDED_MEMORIES` is 40
against 252 live on `~/Trading/LeibaTrader`, so **the figure is a floor for production** rather than an
estimate of it. And the reset is confirmed as *a* per-call cost of the right order, **not** as the whole
of the handler-side half: its paired p50 in the table above is 0.140–0.197 against that half's 0.249 in
the split table. Both are idle paired p50s, which is the only comparison of the two that means anything.


### Against the bar: the p95 misses, the p50 straddles

**No single run settles this, so the verdict is read across them.** Each run whose output is on record,
newest last:

| `load1` | 0.58 | 1.20 | 0.71 | 1.59 | 0.32 | 1.29 |
|---|---|---|---|---|---|---|
| idle paired p50 | 1.049 | 1.059 | 0.753 | 1.062 | 1.053 | 1.099 |
| idle paired p95 | 2.996 | 3.001 | 2.019 | — | — | 3.064 |

**Five earlier runs are on record here as p50s only** — 0.760, 0.811, 0.891, 0.907 and 0.989, across
loads recorded only as a range topping out at 3.65. **Two p95 cells are empty because the record holds
pairwise p95s it cannot now attribute to a run**: the review trail carries four between 2.5 and 2.7, all
above the bar. A cell filled by inference would put a guessed figure in the column the verdict is read
from.

The p50s span 0.75–1.10 against a median standard error near 0.09 ms at n=300 — the treatment paired
delta's own spread, sd 1.250, rather than the probe's — and are not monotone in load: the lowest-load run
on record, 0.32, sits near the top. So **about 0.3 ms of run-to-run variation is unexplained and is not
load**, at roughly three standard errors.

**The p50 straddles its bar and the p95 does not.** The table falls on both sides of 1.0, so *whether a
run clears the p50* is a property of the run. The p95 is not like that: **2.0–3.1 in every run that
computed it pairwise, none under the 2.0 bar**. **That is the durable result** — the row sits at its p50
bar and above its p95 bar.

**The isolated write is a lower bound rather than the cost.** 300 back-to-back `record` calls on a hot
connection with no handler in between is the convenient condition rather than the one the budget was set
for (`CLAUDE.md` §"Measure before you assert"): **0.24–0.33 ms p50** there across runs, against a paired
outside-the-handler delta of **0.508–0.630 p50**, so about 2× — and the rest of the whole delta is the
handler-side cost above.

**The p95's own floor is part of it, and naming that is not excusing it.** With the effect zero by
construction the null arm reads **p95 0.888–1.181** across runs, so a large fraction of the 2.0 ms is
the estimator's spread before the row contributes anything, and the treatment's standard deviation is
the larger of the two — the row adds *variance* as well as a median, which is what a write
occasionally waiting on a lock looks like. **What that does not license is calling the p95 clause
unmeasurable**: at the isolated 0.3 ms a paired p95 would sit near 1.3 and clear the bar. It is the row
in situ that fails it.

**The isolated write does not separate the two conditions.** Its p50 has come out both ways across runs
— 0.249 idle against 0.271 loaded in one, 0.301 against 0.240 in the next — so the difference is inside
the run-to-run spread. The experiment reports how many attempts landed (297 of 300 under the writer)
because a mean over *attempts* that silently mixes refusals with writes is the figure that reporting
exists to prevent.

### The disposition: this is escalated, not accepted

**The bar names two remedies and one of them is already closed.** No per-connection pragma is left to
move: `synchronous = NORMAL` already skips the commit `fsync` under WAL, `wal_autocheckpoint = 0` means
this connection never checkpoints, and `journal_mode` is a property of the database rather than of a
connection. So the pragma route is exhausted rather than forgotten.

**The other remedy reaches the outside-the-handler half and not the other one, and the reason is
mechanistic and positional both.** Moving the write after `writer.drain()` takes the outside-the-handler
portion off what the *caller* waits for — the work still happens, after the bytes are on the wire. The
handler-side portion stays exactly where it is, and the mechanism says why directly: in either shape the
row still **commits** before the next call's `BEGIN`, so the cache invalidation that commit causes is
paid exactly as it is now. The positional reading holds as well, and needs no mechanism: the remedy
relocates work the split attributes to the *outside* of the handler, while the other half is what the
handler's own clock reads.

**"After `writer.drain()`" has two shapes and only one of them recovers that half.** *Awaited* in
`_handle_connection`'s loop before the next `readline`, the caller has its bytes and the row still
completes before anything else runs on that connection, so the drop rate is unchanged — a real client's
next request is seconds away. *Fired as a task*, the row overlaps the next handler's own write, and at
`busy_timeout = 0` it loses: the saving is then bought with a drop rate that climbs with call rate,
and the held-lock isolation test no longer describes the only contention the row meets. **The figure
below assumes the awaited shape.**

What the move costs either way is the seam's placement: `schema.md` §"`call` is an access log" puts the
row inside `_compute_response_line` with the line encoded first, and that placement is what the exit
table and the one-shared-write-then-return property are both argued from. It also needs the activity
bracket widened to cover the drain, or idle self-stop can fire between the response and the row.

So the number decided something, which is what a bar is for, and what it decided is **operator's
call**: accept ~0.75–1.10 ms per user message, or spend the restructuring to recover somewhat over half
of it. **The comparator is a conservative one and should be read as such**: `open_context` builds both
arms on `tests.fake_encoder.FakeEncoder`, so the 4.8–6.0 ms `memory_surface` here is its SQLite work
with no embedding, and the same ~1 ms is a *smaller* share of a real call. The delta itself does not
depend on the encoder.

**And the budget that could have been broken was not, on either arm.** The bar's second clause names a
writer *interleaving short transactions*, which the fixed writer alone reproduces faithfully — a writer
that commits no frame contends for the lock without invalidating anything — so the figure that answers
it is the one run at that condition: `memory_surface`'s treatment p95 **8.357 ms** against a control's
7.489, with 261 of 300 rows landing, against `push._DEADLINE_SECONDS` of **2,000 ms**. Two orders of
magnitude inside it, and the control inside it too, which is what the clause's conditional form required.
Runs at the weaker pre-fix condition read 9.8–11.2 ms and are not comparable to it. M17's defect was
exactly this budget being pushed past by added start-up work, so it is the one the row had to be checked
against, and it is not close.

## What this note got wrong

**What the bar itself got wrong is methodological rather than a threshold, and it cost two wrong
write-ups.** It named "an idle per-call delta at p50 and p95" without saying that a per-call delta is
only defined pairwise, so the first two runs were reported as a *difference of the two arms' own
quantiles* — not a per-call anything, since each arm's p95 is a different call and their difference is
the gap between two unrelated draws. That gave 1.670 ms and then 0.481 ms across runs whose paired
medians were 0.989 and 0.891, both of which §"Against the bar" lists among the five p50-only runs. The
third draft then corrected the
estimator but claimed the isolated write was "the quantity the bar's reasoning was about", which is a
reinterpretation after the result. **The bar was left exactly as written throughout**, because a bar
edited after seeing results is not a bar — and a p95 clause on a paired delta is the thing to write
differently next time, with the null arm's floor established first.

**Then the same estimator was reached for again one level down, which is the part worth carrying.** The
split's first version differenced each half's own p50s and called the near-agreement with the paired
whole *"the halves account for the whole"* — so knowing why an estimator is wrong did not stop it being
used the moment the question changed shape. Medians do not add; means do, and the script now prints that
line itself so the check is not the reader's to perform.

**The second failure is not about statistics: a null from a probe is an exclusion only once the probe is
shown to fire the mechanism.** This one had no positive control, so a null arm was read as *excluding* a
mechanism for two rounds — and the arm turned out to have committed no WAL frame at all, so it excluded
nothing. `PRAGMA data_version` either side of the foreign commit is that control, it costs two reads per
sample, and it would have said so the first time. **Every future null here owes one.**

