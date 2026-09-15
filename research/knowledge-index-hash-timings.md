# Change-detection cost, measured on two corpora

**Date:** 2026-09-14. **Harness:** `spikes/spike_hash_timings.py`, re-runnable inside any git
repository. **Consumer:** `design/knowledge-index.md` §5.1–§5.2.

Warm cache, best of 3–5 runs. Two corpora, deliberately different in shape.

| approach | `amazon-q-developer-cli`<br>2,046 files / 13.2 MB | Zikaron<br>369 files / 12.7 MB |
|---|---|---|
| `git ls-files -s` (precomputed, **no file reads**) | **4.3 ms** | **2.5 ms** |
| `git status --porcelain` | 12.2 ms | 5.5 ms |
| `sha1sum`, batched via `xargs` | **71.2 ms** | 34.6 ms |
| python `hashlib.sha1` | 75.5 ms | **32.6 ms** |
| `git hash-object --stdin-paths --no-filters` | 91.7 ms | 58.4 ms |
| python `hashlib.sha256` | 97.5 ms | 47.1 ms |
| `git hash-object --stdin-paths` (filters on) | 112.1 ms | 61.0 ms |

## What replicates, and what does not

**Robust across both corpora, by a wide margin:** git's precomputed hashes cost roughly **an order of
magnitude less than any approach that reads files** — 4.3 ms versus 71 ms, and 2.5 ms versus 33 ms.
This is the measurement the design's fast path rests on, and it is not close.

**Does not replicate: `sha1sum` versus in-process Python.** The ordering *reverses* between the two
corpora — `sha1sum` is 6% faster on one and 6% slower on the other. The two corpora carry near-identical
total bytes (13.2 MB vs 12.7 MB) and differ 5.5× in file count, which is the plausible cause: per-file
overhead dominates for many small files, per-byte throughput for fewer large ones.

**Consequence for the design, and it is the useful one:** an earlier draft of §5.1 asserted that
`sha1sum` is faster than hashing in process. **That claim is withdrawn** — it held on the corpus it was
measured against and inverted on the next one tried. Since the design hashes **in process, from bytes
already in memory for chunking**, the comparison was never load-bearing; it is recorded here so nobody
re-opens it on the strength of one corpus.

**Also note `git hash-object` is slower than both**, in either direction, on both corpora — git's
advantage is entirely in *not re-reading*, never in its hashing being faster. With clean filters on it
is the slowest option measured **and** incorrect for this purpose (`design/knowledge-index.md` §5.4).

## Caveats

- **Warm cache throughout.** Cold, every row that reads files becomes I/O-bound and the differences
  among them compress; the git-precomputed rows do not read files and are unaffected.
- **One machine**, no `sha_ni` CPU flag present, so hardware SHA acceleration is not in play; a host
  with it would shift every hashing row and not the git rows.
- `git status` timing depends on index freshness — a cold index (first run after checkout) is slower
  than these figures.
