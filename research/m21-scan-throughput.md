# What a build costs, and the two deferred questions it settles — measured

**Date:** 2026-09-15. **Harness:** `experiments/m21_scan_throughput.py`, re-runnable
(`.venv/bin/python experiments/m21_scan_throughput.py <repository> off|tracked|all`).
**Consumers:** `design/knowledge-index.md` §6.1, §16 items 9 and 11; `design/build-plan.md` §M21.
**Environment:** Linux, ext4, git 2.43.0, warm page cache. ~~an otherwise idle machine~~ —
**withdrawn, and it was never checked.** The machine was under other load throughout, and is
expected to stay under load for days, so **every wall-clock figure below is an upper bound on what
an idle machine would show.** Read shortly afterwards: **load average 6.6 across 12 cores**. The
harness now records the load average and the core count into its own output, so the next run states
this condition as data rather than leaving it to a write-up to assert. See §"Not measured" for
which conclusions that touches and which it cannot.

## The question

M21's brief asks for three numbers that cannot be taken later without re-walking a real repository:
what a build costs, how much of a corpus is binary with an unrecognised name, and how much of one
sits under a `.gitignore`d directory the fixed prune list does not already name. The second and third
are the deciding measurements for two questions the design deliberately deferred.

Two corpora, the same pair the change-detection timings used, so the two notes compare directly.
One build per process, because peak RSS is a *process* high-water mark and several builds in one
process would report the largest of them against every one.

## 1. What a build costs

**No embedding happens in this milestone, so these are the floor**: walk, git, read, hash, and one
transaction per file.

| corpus | mode | cold build | rebuild, nothing changed | peak RSS | files | bytes |
|---|---|---|---|---|---|---|
| Zikaron | `off` | 0.571 s | 0.072 s | 37.3 MiB | 448 | 9.1 MB |
| Zikaron | `tracked` | 0.548 s | **0.049 s** | 36.8 MiB | 402 | 8.9 MB |
| Zikaron | `all` | 0.592 s | 0.064 s | 37.3 MiB | 427 | 9.1 MB |
| `amazon-q-developer-cli` | `off` | 2.553 s | 0.231 s | 39.5 MiB | 2,033 | 11.9 MB |
| `amazon-q-developer-cli` | `tracked` | 2.554 s | **0.147 s** | 40.2 MiB | 2,033 | 11.9 MB |
| `amazon-q-developer-cli` | `all` | 2.903 s | 0.253 s | 40.4 MiB | 2,033 | 11.9 MB |

**Against §6.1's model, which is the comparison the brief asks for.** That section estimates ~124 s
of *embedding alone* for a mid-size application (22,800 chunks at a measured 5.45 ms each). The
largest corpus here is 2,034 files and 11.9 MB, roughly a **quarter** of the 5,000-file, 40 MB
corpus that estimate assumes, and **its slowest cold build across the three modes is 2.903 s**
(`all`; `off` and `tracked` are both 2.55 s). Scaled linearly by bytes that is **~9.8 s** for the
modelled corpus — **under a tenth of the embed component, and under a tenth of the whole.**

**Quoted from the slowest mode deliberately, and an earlier revision of this paragraph did not.**
It said "2.6 s", which is the `tracked` column presented as though it were a corpus-wide maximum,
three lines below a table containing 2.903 s. Every statement of a bound in this note and in the
documents citing it is therefore the **worst** row, because a bound taken from the convenient
column is not a bound at all.

**So the separate-process argument is not about this milestone's work, and the measurement says so
rather than assuming it.** Everything M21 does is cheap; K8's case rests entirely on what M22 adds.
A build that stayed in the service today would be a sub-second job, and one that stays there after
chunking and embedding land would be a multi-minute one.

**Peak RSS is flat in corpus size** — 37 MiB against 40 MiB for 4.5× the file count — and is
dominated by the interpreter plus SQLite rather than by anything the scan holds. The scan does keep
its whole candidate list and its whole `files` table in memory, so this is a claim about these
sizes rather than about all sizes; at 2,034 files those structures are noise.

**The rebuild number is the one a user meets most often**, and it is where consulting git earns its
keep: 0.147 s against 0.231 s on the larger corpus, and 0.049 s against 0.072 s on the smaller. The
fast path is doing what it was built to do — a third to a half off an already-fast path — but note
that neither of these is the case the design's order-of-magnitude figures describe, because a warm
page cache makes the reads it avoids cheap too.

## 2. §16 item 9 — binary files with an unrecognised name: a rounding error

The deciding criterion is item 9's own: *"how much of a real corpus is binary-with-unknown-extension
after the §4.2 deny-list. If it is a rounding error, this never gets built."*

| corpus | walked | denied by name | **binary, unrecognised name** | fraction |
|---|---|---|---|---|
| Zikaron | 457 | 1 | **1** | 0.22% |
| `amazon-q-developer-cli` | 2,034 | 1 | **0** | 0.00% |

**One file in 2,491.** It is `.coverage` — a SQLite database with no extension at all, which the
deny-list cannot name because it has nothing to match. And it is `.gitignore`d, so it reaches the
sniff only under `git_mode = off`; under either git mode it never gets there.

**Verdict: the remembered-skip memo should not be built.** The cost it exists to remove is one file
read per scan on one of two corpora, in one of three modes. Weigh that against a second table with
its own staleness and its own disposal rules — the class of machinery `pending` shows is hard to
specify correctly — and the trade is not close.

**The threat to this conclusion, stated because it is real.** Neither corpus carries substantial
binary assets: no image directory, no vendored wheels, no checked-in fonts. A repository that did
would be the case the memo is for — *except* that the §4.2 deny-list names exactly those extensions,
which is why the residual measured here is a file with no extension rather than a PNG. The number
to re-take is the one above, against a corpus with a large `assets/` tree, before this is treated as
settled for every shape of repository.

## 3. §16 item 11 — ignored directories the prune list misses: 4.8% and 0%

The deciding number is *"how much of a real repository sits under a `.gitignore`d directory that
step 1's fixed list does not already name"* — because such a tree is descended in full and every
file under it is walked, statted and then discarded one at a time, where testing the directory node
would prune the subtree.

| corpus | walked files | directories tested | ignored, un-pruned | files under one | fraction |
|---|---|---|---|---|---|
| Zikaron | 457 | 35 | **3** | **22** | **4.81%** |
| `amazon-q-developer-cli` | 2,034 | 194 | **0** | **0** | **0.00%** |

Zikaron's three are `zikaron.egg-info` (6 files), `experiments/embedder-precision/logs` (13) and
`experiments/embedder-precision/embcache` (3).

**Why the larger corpus scores zero, which is the more useful half of the result.** Its
`.gitignore` names `node_modules/`, `target/`, `build/` and `coverage/` — and the first three are
on §4.1's fixed prune list already. **The fixed list is not an approximation of what repositories
ignore; on this corpus it is a superset of the ignored directories that would have mattered.** That
is what the deny-by-default design predicts, and it is the first time it has been checked.

**Verdict: do not prune directories with `check-ignore` during the walk.** At the worse of the two
measurements it would save walking 22 files of 457, on a cold build of 0.57 s — on the order of
**25 ms**, and less on the corpus where the question is most likely to be asked, because there it
saves nothing at all. Against that: a per-directory call during descent, or a batched pre-pass that
cannot be batched against paths the walk has not found yet, and a second place where a
`check-ignore` failure has to be classified.

**The threat, again stated.** Zikaron's 4.8% comes from two directories under `experiments/`, which
is a research tree rather than a build tree — an artifact of this repository's own habits, not a
general property. A repository whose ignored output lands somewhere the fixed list does not name
(`out/`, `_build/`, `vendor/`) would score higher, and the fixed list is the cheaper place to fix
that: adding a name costs a string comparison, where directory-level `check-ignore` costs a
subprocess protocol.

## What changes in the design

1. **§16 item 9 — closed, negative.** The remembered-skip memo is not built, on the measurement it
   named, with the asset-heavy-repository threat recorded against it.
2. **§16 item 11 — closed, negative.** Directory-level `check-ignore` pruning is not adopted; §4.1's
   fixed prune list stays the mechanism, and growing that list is the cheaper answer if a corpus
   ever makes the fraction matter.
3. **§6.1 gains a measured floor.** Its ~124 s figure is an embed-only estimate, and everything
   around the embedding is now known to be single-digit seconds at this scale — which is what makes
   the estimate the whole of the argument rather than a part of it.

## Not measured, and named as such

**An idle machine, and this one is owed a re-run.** Every timing above was taken while the machine
was doing other work, so each is an **upper bound** on an idle machine's. Which conclusions that
touches divides cleanly, and the division is the useful part:

- **§2 and §3 are untouched.** Both are *counts and fractions* — 1 file in 2,491, 4.81% and 0.00%
  — and neither depends on how long anything took. The two §16 items they close stay closed. §3's
  verdict quotes a ~25 ms saving, but what drives it is the fraction of files, and an inflated
  build time makes that saving look *larger* rather than smaller.
- **§1 is the part to re-take**, and the contamination's direction is known: a true idle build is
  faster than these, so "everything around the embedding is cheap" is the conservative reading
  rather than the flattering one. What it is **not** is a like-for-like ratio — the ~124 s it is
  compared against derives from a 5.45 ms-per-text figure measured under other conditions
  entirely — so the comparison should be re-made once both sides can be taken on one idle machine.

**When to re-take it: after the chunker and the embedder land**, because that is the first moment
the whole build can be timed rather than its floor, and the number §6.1 actually wants is the whole
build. Re-running is one command per corpus and mode.

**A cold page cache.** Every figure above is warm, which is the ordinary case for a repository
somebody is working in and the wrong case for a first build after a reboot. The rebuild numbers in
particular would move.

**A corpus at the scale §6.1 models.** Both corpora are around a quarter of it by bytes, and the
scaling above is linear-by-bytes, which the walk's per-file overhead makes optimistic for a corpus
of many small files — the same per-file-versus-per-byte effect that made the change-detection
timings fail to replicate between these two corpora.

**Anything about a machine other than this one.** Single runs, not best-of-n; the cold builds differ
by less between modes than two runs of one mode plausibly would.
