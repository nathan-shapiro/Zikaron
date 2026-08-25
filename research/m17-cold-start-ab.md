# M17 — the cold-start A/B, and the defect reproduced on demand

Measured 2026-08-25. Harness: `experiments/m17_cold_start_ab.py` (timings) and
`experiments/m17_hook_outcome.sh` (the outcome). Both re-runnable.

## Setup

12-core machine. Both arms use the same store — this repository's own `.zikaron`, 5 memories — and
the same query. "Cold" means a cold **process**, not a cold artifact cache: the production case is
a service that idled out and was respawned by start-if-absent on a machine where the model files
have been on disk for weeks. Each arm discards one warm-up run before measuring, so page-cache
misses on the model file are not charged to whichever arm happened to run first. Timings are from
the instant the spawn is issued.

The old arm is the working tree with the M17 changes stashed, verified each time by the absence of
`BackgroundLoadedEncoder` and the presence of the eager `FastEmbedEncoder.load` in
`ServiceContext.assemble`.

## Timings, idle machine (load1 0.55–1.10)

| arm | socket-ready | health ready | surface answered | inside the 1200 ms poll deadline |
|---|---|---|---|---|
| old | 805 ms (788–828) | 805 ms | 827 ms (809–849) | 3/3 |
| new | **242 ms** (242–243) | 243 ms | 809 ms (801–821) | 3/3 |

## Timings, under load (load1 7.0–8.9)

| arm | socket-ready | health ready | surface answered | inside the 1200 ms poll deadline |
|---|---|---|---|---|
| old | 1157 ms (1110–1420) | 1158 ms | 1215 ms (1141–1473) | **2/3** |
| new | **395 ms** (376–418) | 395 ms | 1348 ms (1128–1428) | 3/3 |

## The outcome, through the shipped hook, under load

`zikaron-hook` invoked exactly as the harness invokes it, against a service killed and its socket
unlinked before each run. A clean push is: exit 0, the injected block on stdout, and **no new line
in `hook.log`** — a `transport` line there is the silent loss this milestone exists to end.

| arm | load1 | clean pushes | stdout per run | `hook.log` |
|---|---|---|---|---|
| old | 8.89 | **0/5** | 241 B — the degrade relay | +1 `transport` line every run |
| new | 9.26 | **5/5** | 1513 B — the memory block | never created |

The new arm ran at *higher* load than the old arm, so the comparison is conservative against the
fix rather than flattering to it.

## What this establishes

**The defect is real and reproducible.** Old code under load produced exactly the production
failure recorded from `~/Trading/LeibaTrader`: a `transport` line in `hook.log` and the user's
message reaching the model with no memories attached. It reproduced 5 times out of 5.

**The fix removes it.** 5/5 clean pushes at higher load, with the full 1513-byte block delivered
every time.

**And the fix makes nothing faster, which is the point.** End-to-end time is essentially unchanged
— 827 ms → 809 ms idle, and under load the new arm's `surface` is *slower* (1348 ms vs 1215 ms),
because the model load that used to be paid before the bind is now paid inside the request. The
same work happens; only its position relative to the readiness signal changes. That was the
design's central claim and it is now measured rather than argued: what moved is which side of the
hook's deadline the wait falls on.

## Three caveats, stated because the numbers will outlive this note

**The defect is load-dependent, and an idle machine cannot demonstrate it.** At idle the old code
binds in 805 ms and wins the 1200 ms deadline 3/3 — an outcome test run at idle passes on *both*
arms and distinguishes nothing. The load here was synthetic (8 busy loops on 12 cores), which is
not the same mix as real contention; what it reproduces is the *condition*, not the exact
production workload.

**Small n.** Three timed runs per arm per condition, five outcome runs per arm. Enough to separate
805 from 242, not enough to characterise a distribution — note the old arm's 1110–1420 ms spread
under load against the new arm's 376–418 ms.

**The timing harness's `surface` calls returned 0 rows** (its query matched nothing in a 5-memory
store) while the hook test returned a full block. That does not affect the timings: the dense arm
embeds the query regardless, which is exactly what the ~566 ms gap between `health` and `surface`
in the new idle arm is made of.
