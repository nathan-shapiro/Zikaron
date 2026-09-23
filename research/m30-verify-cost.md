# M30 — what per-start artefact verification costs, and the hook budget it breaks

**Measured 2026-09-23**, Linux, 12 cores. **This machine did not reach M17's idle baseline
(`load1 0.55–1.10`) at any point**: ambient load sat at 5.3–9.2 with nothing of this session's own
running, so every figure here is at elevated load and the idle cell is unmeasured.

## What was asked

M30 makes `FastEmbedEncoder.load` verify the pinned artefact's five files against their SHA256 on
every start. The question is not what that walk costs in isolation — it is how much of the push
hook's `_DEADLINE_SECONDS = 2.0` it leaves, since a `surface` that outlives the budget degrades:
no memories injected, one `transport` line in `hook.log`, and a relay instruction the model reads
out to the user. That is the defect M17 exists to prevent.

## The walk in isolation, warm, unloaded process

188.5 / 182.7 / 192.4 ms for the five files, `model_optimized.onnx` essentially all of it.

```
.venv/bin/python -c "import time;from zikaron.core.indexing import acquisition as a,model_pin as p,model_cache as c;pin=p.pin_for('BAAI/bge-small-en-v1.5');d=c.snapshot_dir(c.resolved_model_cache_dir(),repo_id=pin.repo_id,revision=pin.revision);t=time.perf_counter();a.verify(pin,d);print(round((time.perf_counter()-t)*1000,1),'ms')"
```

**This figure is misleading on its own and is recorded so nobody re-derives only it.** The walk is
CPU-bound, so it does not cost 185 ms on a machine that is busy — which is the condition the hook
budget was sized against.

## End to end, at `load1 5.75`

`experiments/m17_cold_start_ab.py`, 7 runs after a discarded warm-up.

| from spawn | median | range |
|---|---|---|
| socket | 419 ms | 408–440 |
| health | 420 ms | 410–441 |
| surface | 1481 ms | 1460–1495 |

`health` inside 1200 ms 7/7; `surface` inside 2000 ms 7/7.

**`load1 5.75` bounds nothing.** It sits between M17's two cells — idle `0.55–1.10` and loaded
`7.0–8.9` — and M17's own loaded arm answered `surface` at up to 1428 ms *before* this walk existed.
Reading 1481 ms as an upper bound, as an earlier draft of `design/distribution.md` did, is falsified
by `research/m17-cold-start-ab.md`'s second table.

## End to end, at M17's load cell

Load generated with ten busy loops on twelve cores, `load1` read from `/proc/loadavg`.

At `load1 7.35`, `experiments/m17_hook_outcome.sh 5` — the **shipped hook**, not the timing harness:

```
  run 1: exit=0 stdout=241B hook.log+=1  FAIL
  run 2: exit=0 stdout=1855B hook.log+=0  ok
  run 3: exit=0 stdout=241B hook.log+=1  FAIL
  run 4: exit=0 stdout=241B hook.log+=1  FAIL
  run 5: exit=0 stdout=241B hook.log+=1  FAIL
clean pushes: 1/5
```

241 B of stdout is the degrade relay; 1855 B is the memory block. M17's post-fix arm was **5/5 clean
at `load1 9.26`**.

## The A/B that attributes it

Four arms, alternating, one load source throughout. The control is a `sitecustomize.py` on
`PYTHONPATH` that empties `model_pin.PINNED_ARTIFACTS`, so `pin_for` returns `None` — the branch M30
added for an unpinned model. **It is not the pre-M30 tree**, and the difference is deliberate: M30's
`cache_dir` argument stays in place, so the control is fastembed's own acquisition into Zikaron's
durable directory. That isolates verification, which is the question, rather than mixing in the
cache-location change. No product code was modified for the measurement.

`load1` at each arm's start: 8.01, 9.75, 11.77, 12.25. **It rose monotonically, so each control ran
at heavier load than the arm before it and the deltas below are conservative** — the same direction
`m17-cold-start-ab.md` records for its own arms.

| arm | verification | socket | surface median | surface range | inside 2000 ms |
|---|---|---|---|---|---|
| A1 | **on** | 582 ms | **2076 ms** | 1984–2160 | **1/5** |
| B1 | off | 560 ms | 1745 ms | 1648–1782 | 5/5 |
| A2 | **on** | 611 ms | **2181 ms** | 2075–2409 | **0/5** |
| B2 | off | 567 ms | 1785 ms | 1662–1914 | 5/5 |

**Delta: +331 ms (A1−B1), +396 ms (A2−B2).** `socket` spans 560–611 ms and `health` 560–611 ms across
all four arms — a spread of ~50 ms with no ordering by arm, against a `surface` delta six times that
— which places the cost in the acquisition path rather than anywhere else in startup.

**The delta exceeds the isolated walk by 150–210 ms, and the excess is the hash under contention.**
The other candidate was the warm `snapshot_download(local_files_only=True)` call, and the fix rules
it out: the fixed tree still makes that call and lands at or below the no-pin arm (below), so it
costs nothing measurable here. What is left is that hashing 64 MB competes with ten busy loops.

## What it establishes

**Per-start verification as built breaks the guarantee M17 bought.** At M17's own load cell the
pre-M30 arm is comfortably inside the hook budget and the M30 arm is outside it, 0–1 runs in 5.
The isolated 185 ms figure understates the cost by a factor of about two under load, which is why
it should never have been the number a design decision rested on.

## The fix, and its control

Verification moved to the paths where bytes arrive from the network; a warm start does five `stat`
calls. Re-measured at the same load cell:

| tree | `surface` median | range | inside 2000 ms |
|---|---|---|---|
| fixed | **1677 ms** | 1637–1786 | **7/7** (`load1 9.35`) |

Through the shipped hook, the fixed tree first gave **4/5** at `load1 7.66`. **That one failure was
variance, not the fix**, which a control settled rather than an argument: run back to back at higher
load still,

| arm | clean pushes | `load1` |
|---|---|---|
| pre-M30 (no pin, via the shim) | **5/5** | 10.86 |
| fixed tree | **5/5** | 11.88 |

1677 ms also sits at or below the no-pin arm's 1745–1785 ms, so the cost is removed rather than
reduced. **Do not read the parity as "the pin costs nothing"** — it costs 331–396 ms whenever it
runs; the fixed tree simply does not run it on a warm start.

## A snapshot proved wrong is discarded, before the re-fetch as well as after

Presence is all a warm start checks, so any instant at which all five pointers resolve to bytes
already proved wrong is an instant another process can load them. **There are two such windows.**
The first — a snapshot left behind by a failed acquisition — was found by a test failing. The
second, and much the longer, was found in review and confirmed against the installed library:
`snapshot_download` creates a pointer only `if not os.path.exists(pointer_path)`, so under
`force_download` every existing pointer stays aimed at the old blob for the whole 64 MB download.
A process killed there leaves the wrong bytes complete and trusted.

`acquisition._discard` therefore runs **before** the forced re-fetch as well as after a failure.
That also fixes a second consequence of the same line: when the server's etag differs from the
on-disk blob's, the download lands at a new blob, the surviving pointer is never re-aimed, and the
re-fetch cannot succeed at all.

## Re-deriving this

```
for i in $(seq 1 10); do (while :; do :; done) & done   # then wait for load1 >= 7
bash experiments/m17_hook_outcome.sh 5
.venv/bin/python experiments/m17_cold_start_ab.py <label> 7
PYTHONPATH=<shim dir> .venv/bin/python experiments/m17_cold_start_ab.py <label>-nopin 7
kill %1 %2 %3 %4 %5 %6 %7 %8 %9 %10
```

**`experiments/m17_cold_start_ab.py` had rotted and was repaired to take these measurements.** It
sent RPC method `surface`, which D1's amendment renamed `memory_surface` when every method gained a
subsystem prefix; it had not been run since, and answered `method not found`. `experiments/` is
ruff-excluded and outside the gate, so nothing reported the decay.
