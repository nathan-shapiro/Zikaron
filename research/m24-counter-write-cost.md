# What the four search counters cost a search

**Measured 2026-09-16**, on a machine that was **not idle** — the same qualifier every other timing
in this corpus carries, and stated because it was checked rather than copied from a template.
Harness, re-runnable in one command: `experiments/m24_counter_write_cost.py`.

A search of one corpus now ends in a write transaction — four `UPDATE`s in that corpus's `meta` —
where it used to end in nothing. That is a write on the latency path §6.1 exists to protect, so its
size is a number rather than an intuition.

| condition | p50 | min | max | n |
|---|---|---|---|---|
| idle database | 0.743 ms | 0.626 | 1.215 | 50 |
| writer lock held by another connection | 0.331 ms | 0.275 | 0.617 | 50 |

## What the two rows mean

**The idle row is the ordinary case**, and it is what a search pays per corpus it actually served.

**The held row is the case the timeout is dropped to zero for**, and it is *faster* than the idle
one, which is the result worth stating: refusing the lock costs less than taking it, so the
contention path is not a tax on the happy path but a shortcut off it. Without the dropped timeout
the same row would read **5,000 ms** — measured, by mutation, in
`tests/test_knowledge_counters.py`.

## Against what it has to be weighed

Both figures this project already holds for the same path:

- a knowledge search: **16–17 ms**, including the query embedding (`FINDINGS.md`, M22)
- opening one corpus: **p50 1.32 ms** (same)

So the counter write is **roughly 4–5% of one search against one corpus**, and rather less than the
open that precedes it. Across five corpora it adds something under 4 ms to a call already costing
80-odd. That is the cost §12 accepts in exchange for being able to answer *is this corpus used at
all* later.

## What this does not measure

**The write is per corpus served, not per call**, so a search naming ten corpora pays it ten times
— the table above is the unit, not the total. And nothing here measures the *contended* case
against a real indexer: the holder in this harness takes the lock and sits still, where a build
takes and releases it per file (§4.6). A real build therefore offers windows in which the counter
write succeeds, which can only make the observed cost fall between the two rows rather than exceed
either.
