# experiments/embedder-precision

A throwaway-but-re-runnable benchmark that answers one question for Zikaron:

> **Is `bge-small-en-v1.5` the wrong embedder for tribal-knowledge memories, given that those
> memories are dense with precise tokens (identifiers, versioned type names, env vars, file paths,
> error-class names)? And if it is, is "something more capable" the right fix?**

Read this file first if you are picking the work up cold. The findings live in
`../../research/embedder-benchmark-results.md`; the round-1 self-critique in
`../../reviews/embedder-precision-eval-design.md`; the **independent review that drove rounds 2 and
3** in `../../reviews/embedder-benchmark-independent.md`.

**Three rounds exist.** Round 1 built the corpus, the sweep and the latency numbers. Round 2 rebuilt
the evaluation around an independent review's 18 findings: a blind query set, graded labels, a
preregistration, a factorial ablation, a held-out extractor test and a counterfactual identifier
instrument. Round 3 answered the 4 blocking findings the review's **second** round returned — two
estimand/analysis fixes, one tie-counting fix plus a causal test that came back negative, and one
relabelling. **Rounds 2 and 3 together are the current answer**; round-1 code and results are
retained unchanged for audit. Jump to "Round 2: what the independent review changed" and then
"Round 3" if you only want the current state.

## Why this exists

`research/embedding-models-technical-prose.md` established that **no published study measures
near-miss identifier discrimination** in text embedders (`WidgetV1` vs `WidgetV2`, `v2.3.1` vs
`v2.3.10`). The closest adjacent evidence is that sentence embedders are broadly blind to negation
(Nikiema et al. 2025, arXiv:2509.09714, 96.2% false-positive rate). So the question could not be
settled by citation and had to be measured on our own data. That is what this is.

Two competing positions were on trial:

- **User's hunch:** a small general-purpose prose embedder mis-serves identifier-dense text; we need
  a more capable model.
- **Counter-argument:** bi-encoder pooling destroys sub-token identity *by construction*, so scaling
  buys semantic nuance, not lexical precision. If true, the fix is lexical (BM25, an extracted
  identifier field) or joint-attention (a cross-encoder reranker), not capacity.

`6_rrf_bm25_large` is the decisive comparison for that: same family, same tokenizer, same prefix
convention, ~3× parameters. If it does not move the near-miss numbers, capacity is the wrong axis.

## Setup

```bash
cd experiments/embedder-precision
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install fastembed sqlite-vec
```

Nothing is installed into system Python. `numpy` arrives as a fastembed dependency.

Verify the substrate actually works before trusting anything built on it:

```bash
./.venv/bin/python -c "
import sqlite3, sqlite_vec
db=sqlite3.connect(':memory:'); db.execute('create virtual table t using fts5(x)')
db.enable_load_extension(True); sqlite_vec.load(db)
print('FTS5 ok, sqlite-vec', db.execute('select vec_version()').fetchone()[0])"
```

Model downloads total ~2.9 GB into `/tmp/fastembed_cache` (fastembed's default; **it is in `/tmp`,
so a reboot loses it and the next run re-downloads**). Prefetch them up front if you want the
download separated from the timing runs:

```bash
./.venv/bin/python _prefetch.py     # writes logs/prefetch.log
```

## Running it — round 1 (superseded, retained for audit)

These commands reproduce the round-1 results. They are **not** the current answer: `sweep.py` uses
one-gold labels, the self-authored query set, and `hnd` computed over a 50-candidate union. Use
`eval_v2.py` instead. See "The round-2 run order" below.

```bash
# 1. build the dataset artefact (deterministic; safe to re-run)
./.venv/bin/python build_dataset.py

# 2. is the eval accidentally trivial?
./.venv/bin/python leakage_audit.py
./.venv/bin/python leakage_audit.py --json > results/leakage_audit.json

# 3. the full sweep (all 9 configurations). Slow: rebuilds 4 dense indexes.
./.venv/bin/python sweep.py

# a single configuration, or a few (indexes are still built for all models)
./.venv/bin/python sweep.py --only 4p 6

# 4. the isolating diagnostic - the most important single result in the experiment
./.venv/bin/python twin_duel.py

# 5. latency, including cold whole-process start
./.venv/bin/python latency.py

# 6. the truncation question: does embedding gist-only beat gist+content?
./.venv/bin/python sweep.py --embed-mode gist_only
./.venv/bin/python sweep.py --embed-mode content_only
```

Expect the full sweep to take roughly 10–15 minutes on a 12-core CPU box, dominated by embedding
187 documents with bge-large (~4 min) and nomic (~2.5 min). `latency.py` takes a few minutes because
cold-start probes each spawn a fresh interpreter and reload a model.

## v2: an independently-authored query set

`reviews/embedder-benchmark-independent.md` finding 1 is a BLOCKER on everything above:
the same author wrote the memories *and* the queries, so query vocabulary was chosen while
holding the target memory text in mind. That inflates every number and cannot be fixed by care.

The cheap half of the fix is a fresh query set against the **existing** memory corpus, authored
by someone who has never read the memory prose. `stubs_v2.json` is the bridge — it carries only
what a real user would already have in hand:

```bash
./.venv/bin/python build_stubs_v2.py       # emit stubs_v2.json
./.venv/bin/python check_stub_leakage.py   # must print violations=0
./.venv/bin/python check_stub_leakage.py --json > results/stub_leakage_v2.json
```

Rules the stubs encode:

- **Identifier leakage is realistic; prose leakage is not.** `identifiers_involved` is meant to
  appear verbatim in the authored prompt (a user working on `WidgetV2` really types `WidgetV2`),
  and is restricted to *user-side* tokens. Answer-side identifiers the user could not know
  (`PLATFORM_OVERRIDE_ALLOW`, `TEMPLATE_CACHE_SALT`, `/var/run/secrets/...`) are excluded so the
  prompt cannot accidentally quote the punchline.
- **`situation` is <=15 words of circumstance, never content or resolution**, and is mechanically
  held to zero 3-word overlaps with any gist or content. It clears a 4-word span too; 2-word spans
  collide 118 times, which is just English and is why the threshold is 3.
- **Graded relevance, per review finding 11.** `relevant_memory_uuids` grades every bearing record
  `primary` / `also_useful` / `harmful_if_applied`. Three stubs now have **co-primaries** —
  `q-c2-10`, `q-c3-03` (`c2-cert-chain` ~ `c3-ssl-verify`) and `q-c3-06` (`c1-ver-2-3-1` ~
  `c3-symbol-lookup`) — because those pairs encode the same diagnosis and v1 called one of them a
  hard negative. Since D12 injects five gists, returning both is not a failure.
- **`confusable_uuids` is reserved for real traps** — records whose *application* misdirects.
  16 of the v1 hard-negative labels did not survive that bar.
- **Intent is explicit, per review finding 12.** 60 `current_action` / 4 `historical_intent`
  (`q-c4-06`..`q-c4-09`). Displacement on a historical-intent stub means the *newer* record
  outranked the legitimately-relevant older one, which is the opposite of a staleness failure and
  must not be pooled with the current-action rate.

### The authored prompts

`queries_blind.json` is the result: **192 prompts, three per stub**, written from `stubs_v2.json`
and this README alone. `dataset.json`, `dataset_src/`, `results/` and the results write-up were
never opened by the author, so no phrasing could be tuned against memory prose.

```bash
./.venv/bin/python build_queries_blind.py    # emit queries_blind.json; exit 1 on any check below
```

Three variants per stub exist so uncertainty can be estimated **over phrasings**, not only over
deterministic reruns. They are systematically differentiated by register and each row carries a
`variant_style` label, so the analysis can pool the three *or* split by register:

| `variant` | `variant_style` | mean words | shape |
|---|---|---|---|
| 1 | `terse` | 8.6 | a clause, lowercase, minimal ceremony, often missing context |
| 2 | `verbose` | 45.2 | multi-sentence, the surrounding story, what was already ruled out |
| 3 | `mid` | 13.0 | one sentence, entered from a different angle than variant 1 — a sanity check or "is X involved" rather than a task statement |

Splitting by register is worth doing on its own: real prompts look like variant 1, so a retriever
that only works on variant 2 is not usable.

`underspecified` is true on **39 of 192** rows that deliberately withhold a cue a careful author
would have supplied — the exact error string, or the one detail that distinguishes the case. v1
sampled only well-specified prompts; these sample the other tail. Notably `q-c3-02`, `q-c3-05` and
`q-c3-10` each have one variant that quotes **no** error text at all, which turns the
`error_string` category into a lexical-vs-dense contrast rather than a single condition.

`build_queries_blind.py` enforces, and fails on:

- exactly three variants per stub, numbered 1–3, none empty, no two prompts identical;
- **no paired twin identifier bleeding across** — no `v2.3.10` inside a `v2.3.1` prompt, no
  `--no-cache-dir` inside a `--no-cache` prompt, no `conftest.py` inside a `conf_test.py` prompt,
  and 22 such pairs in total. The reverse containment (`v2.3.10` contains `v2.3.1`) is inherent and
  is the trap itself;
- every stub carrying identifiers lands at least one of them somewhere;
- register word counts really are ordered `terse < mid < verbose`.

`identifier_coverage` in the output records, per stub, how many of the three variants contain each
identifier. It is **reported, not enforced**: 37 stubs have every identifier in all three variants,
9 omit one somewhere on purpose (the underspecified rows).

Two things are *not* mechanically checked and rest on the author's discipline: that no prompt names
a resolution, and that `q-c4-06`..`q-c4-09` ask about the past in all three variants rather than
about what to do now. A prose-leakage gate like `check_stub_leakage.py` cannot be run against these
without handing the checker both sides, and a 3-gram bar on 45-word prompts would fire on ordinary
English anyway.

## Round 2: what the independent review changed

`reviews/embedder-benchmark-independent.md` returned **NEEDS_CHANGES** on round 1 with 5 BLOCKERs,
11 MAJORs and 2 MINORs. Round 2 answers all 18. **If you are picking this up cold, read in this
order:** this README → `PREREGISTRATION.md` → `../../research/embedder-benchmark-results.md`
(the `## Response to independent review` section maps every finding to what changed).

Round-1 code and results are **retained unchanged** for audit. Round 2 lives in new files, and
`PREREGISTRATION.md` records sha256 hashes of the round-1 code so nobody has to trust that claim:

```bash
./.venv/bin/python verify_freeze.py     # exit 1 if any frozen artefact moved
```

### The round-2 run order

```bash
cd experiments/embedder-precision

# 0. always first - are the frozen artefacts still the ones the results describe?
./.venv/bin/python verify_freeze.py

# 1. the main evaluation: 18 configs x {blind, dev} x {depth 50, depth 187}
#    ~7 min cold (bge-large dominates), ~40 s once embcache/ is warm
./.venv/bin/python eval_v2.py
#    -> results/eval_v2.json  +  results/eval_v2_perquery.json

# 2. what-to-embed comparison on the blind set (dense arm embeds the gist alone)
./.venv/bin/python eval_v2.py --embed-mode gist_only --sets blind --depths 50 \
    --out results/eval_v2_gist_only.json

# 3. the counterfactual identifier instrument - replaces twin_duel.py
./.venv/bin/python twin_counterfactual.py       # ~4 min cold, seconds warm

# 4. the frozen extractor, held out (no models, instant)
./.venv/bin/python extractor_heldout.py

# 5. true write-side cost of the tokens column (no models, ~10 s)
./.venv/bin/python tokens_cost.py

# 6. reranker latency scaling - RUN THIS WITH NOTHING ELSE ON THE CPU
./.venv/bin/python rerank_scaling.py            # ~2 min

# 7. cross-check every figure the report quotes against the JSON. Do this LAST, and after any
#    rerun - it is the drift guard between report and artefacts.
./.venv/bin/python report_figures.py --assert      # 95 figures, exit 1 on mismatch

# smoke test the lexical factorial without loading any model (writes /tmp/smoke_perquery.json,
# so it cannot clobber the canonical per-query file):
./.venv/bin/python eval_v2.py --only L_ --depths 50 --out /tmp/smoke.json
```

`embcache/` caches every embedding by `sha256(model_name + "\0" + text)`, which is why reruns are
cheap. The model name is part of the key, so a same-dimension model swap **cannot** silently reuse
another model's vectors. Delete `embcache/` to force a true cold run.

### Round-2 files

| File | What it is |
|---|---|
| `PREREGISTRATION.md` | **Read before any result.** Decision thresholds, analysis plan, resampling unit, frozen hashes. Timestamped 2026-08-01T02:28:08Z, before any round-2 result was computed. Do not edit it. |
| `verify_freeze.py` | Re-checks the preregistered sha256 list. Exit 1 on mismatch. |
| `evalkit.py` | **Metric definitions are authoritative here.** Graded-relevance scoring, aggregation, breakdowns, paired cluster bootstrap over stubs, `set_gap_bootstrap` for the cross-query-set difference, phrasing spread. |
| `retrieval2.py` | Round-2 arms. Five FTS5 variants for the factorial, `extract_variant(dup=)` with a parity assertion against the frozen extractor, tie-counting RRF (`rrf_counted`, two separately-named tie quantities), explicit-tie-break RRF (`rrf_tiebreak`, round 3), `dbstat` byte accounting. Imports `retrieval.py`; never modifies it. |
| `embcache.py` | Model-keyed embedding cache. |
| `eval_v2.py` | The round-2 driver: 18 configs, 2 query sets, 2 depths, 15 declared contrasts, and the v1-dev/v2-blind `query_set_gap` table. |
| `twin_counterfactual.py` | Byte-identical-template identifier instrument with floor/ceiling controls, blocked on the twin set. |
| `extractor_heldout.py` | 60 held-out strings across 8 classes + 12 held-out near-miss pairs, with the grading rubric committed in the docstring. |
| `tokens_cost.py` | Index bytes, database growth, insert/amend p50/p95, extraction time. |
| `rerank_scaling.py` | Reranker latency across 5/10/25/50 candidates × gist-only/gist+content. |
| `report_figures.py` | **Drift guard.** Regenerates all 95 figures the report quotes and asserts they match. Run it after any rerun. |
| `index_v2.db`, `index_tie.db`, `embcache/` | Generated. Disposable. |

### The 18 round-2 configurations

Three families. Fixed for all: RRF `k=60`, seed 20260731/20260801, no threshold tuning.

| Family | Configs | Why |
|---|---|---|
| `L_*` (7) | `L_A_unicode61`, `L_B_tokchar`, `L_C_tok_w0`, `L_D_tok_w1`, `L_E_tok_w3`, `L_F_tok_w3_nodup`, `L_G_split` | **The factorial ablation of BLOCKER 5.** Lexical-only so fusion cannot confound the attribution. `A` = baseline tokenizer. `B` = tokenizer change **only**. `C/D/E` = tokens field at weight 0/1/3. `F` = `E` minus the duplicate whole-token emission. `G` = **a composite, isolating nothing**: two tables fused, so it adds the tokens index, a second arm, RRF normalisation and tie behaviour at once. FTS5 cannot give one table two tokenizers, so "custom tokenization confined to the extracted field" is **not testable here** and remains an open arm (review round-2 BLOCKER 4). |
| `D_*` (4) | `D_small_noprefix`, `D_small_prefix`, `D_large_prefix`, `D_nomic` | **MAJOR 8.** Round 1 tested large and nomic only behind RRF, so it compared pipelines. These compare embedders. |
| `H_*` (7) | `H_small_noprefix`, `H_small_prefix`, `H_tokchar_notok`, `H_tok_w3`, `H_tok_w3_nodup`, `H_large`, `H_nomic` | The deployable shapes. `H_small_prefix` is the incumbent baseline (round-1 config 4p). `H_tokchar_notok` is what `H_tok_w3` must be compared against, not `H_small_prefix`. |

`CONTRASTS` in `eval_v2.py` is the declared contrast list. Adding to it is fine; anything not on the
original list must be labelled **exploratory** in the report, per `PREREGISTRATION.md` section 7.

### Round-2 metrics

Authoritative definitions live in the `evalkit.py` docstring. `recall@5`/`hnd`/`hnd_top5` from
round 1 are superseded:

| Round 1 | Round 2 | Why |
|---|---|---|
| `recall@5` (one gold) | **`useful_hit@5`** — any `primary` in the top 5 | graded labels; 3 stubs have co-primaries |
| — | **`harmful_exposure@5`** — any `harmful_if_applied` in the top 5 | never netted against useful recall; they move independently |
| `hnd_top5` | **`harmful_disp@5`** — harmful in top 5 **and** above every primary | the primary displacement measure; top-5 is the injection budget |
| `hnd` ("full ranking") | **`harmful_disp_full`** at `--depths 187` | round-1 `hnd` was over a 50-candidate arm union, not the corpus |
| `precision@5` | dropped | ceiling ~0.21, no information beyond `useful_hit@5` |
| — | `relevant_recall@5` over `primary ∪ also_useful` | secondary; D12's five slots make a second useful memory a benefit |

**Uncertainty is a paired cluster bootstrap over the 64 stubs**, never over the 192 queries — three
variants of a stub are one information need. Every difference is reported with raw changed-query
counts. Phrasing uncertainty comes from the three registers, because model inference is
deterministic and a rerun estimates nothing.

### Round-2 gotchas (continuing the numbering from the round-1 list further down)

8.  **The per-query detail file used to be clobbered by any variant run** — a `--only L_` smoke
    test and a `--embed-mode gist_only` run both overwrote the canonical
    `results/eval_v2_perquery.json`. It is now named after `--out`, so
    `--out /tmp/smoke.json` writes `/tmp/smoke_perquery.json`. This bit twice.
9.  **A gist-only run rebuilds `index_v2.db` with gist-only vectors.** Re-run plain `eval_v2.py`
    afterwards to leave the database in the primary state. Cheap once `embcache/` is warm.
10. **At `--depths 187` a BM25-only arm still does not rank the whole corpus.** FTS5 returns only
    documents that share a term with the query — mean 158–160 of 187 here. So `harmful_disp_full`
    for `L_*` configs is displacement within the *matching* set. Do not call it full-corpus.
11. **`rrf()` produces exact score ties constantly.** With two unweighted arms, rank *i* in one arm
    ties with rank *i* in the other. 100 % of hybrid queries contain a tie; **12.5 % have at least
    one inside the top 5** (`H_small_prefix`; 15.6 % `H_large`, 11.5 % `H_nomic`, 7.8 % `H_tok_w3`,
    17.2 % `L_G_split`), broken by Python's stable sort, i.e. in favour of whichever arm was passed
    first (BM25). `retrieval2.rrf_counted` measures this. **Two distinct quantities, and round 2
    conflated them**: `frac_queries_with_any_tie_inside_top5` is a per-query boolean;
    `mean_tied_adjacent_pairs_in_top5_per_query` is a mean pair count. They coincide unless a query
    has two adjacent top-5 ties, which is why the bug went unnoticed for the headline configs and
    not for `H_nomic` and `L_G_split`. Any fusion tuning should add an explicit tie-breaker first —
    but see round-3 gotcha 16: ties are *not* why the hybrid absorbs bge-large's dense advantage.
12. **The counterfactual instrument's null is margin 0, not a 50 % win rate.** With byte-identical
    templates, a model blind to the identifier embeds both passages identically. If you find
    yourself writing "chance = 0.500", the construction has changed and the analysis is wrong.
    `identity` margin must print `+0.000000` or the harness is broken.
13. **`identifiers.py` is frozen.** The moment it is edited, `extractor_heldout.py` stops being a
    held-out test and its material must be re-authored. `verify_freeze.py` guards this.
14. **`retrieval2.extract_variant(dup=True)` must stay byte-identical to `identifiers.extract`.**
    `assert_extract_parity()` proves it on every index build; if it ever raises, the duplicate-
    emission factor is no longer isolated and the factorial is invalid.
15. **Insert p95 came out *lower* with the extra tokens work.** That is `fsync` dominating, not
    extraction making inserts faster. Use **amend** as the write-cost signal: it does strictly more
    work, and FTS5 has no in-place update so an amend is delete + reinsert.

### What round 2 still does not fix

Stated so a future session does not rediscover it as a surprise:

- **The memories are still synthetic and still 187.** Blind *queries* against synthetic *memories*
  is half the fix. Review finding 1 also asked for real memories from a real repository history.
- **The graded labels share an author with the memories.** Independent annotation is undone.
- **near_miss and error_string are still saturated** (0.976–1.000 for everything), so the aggregate
  is still a construction-weighted average. The unsaturated cells are paraphrase (10 stubs) and
  polarity (10).
- **`historical_intent` is 4 stubs / 12 prompts.** Enough to prove blanket supersession-suppression
  would be wrong; not enough for a rate.
- **The hook→MCP path is unmeasured.** Nothing here tests MCP lifecycle, IPC, concurrency or
  residency.
- **512-token truncation is deliberately left open**, declared unsettleable by this dataset in the
  preregistration before results were seen.
- **"Custom tokenization confined to an extracted field" was never tested.** `L_G_split` is a
  composite and cannot isolate it; FTS5 cannot give one table two tokenizers, so a clean test needs
  a different substrate (one `unicode61` table plus a pre-tokenized identifier column, say). Add
  that arm if the extractor is ever rewritten.
- **Capacity as a mechanism is untested, not refuted.** fastembed serves a *quantized* bge-small
  against an *unquantized* bge-large, so every large-vs-small number here — task and instrument
  alike — compares deployed artifacts. Settling capacity needs matched fp32 exports of one family.

## Round 3: what the review's second round changed

`reviews/embedder-benchmark-independent.md` **round 2** accepted 12 of the 18 round-1 findings as
resolved and 6 as partially resolved, and returned NEEDS_CHANGES on **4 analysis/wording defects**.
Round 3 fixes all four. **No recommendation changed.** Read `PREREGISTRATION-R3.md` before any
round-3 number — it was written before any of them existed, and `PREREGISTRATION.md` was *not*
edited.

| Round-2 finding | Fix | Where |
|---|---|---|
| 1a — the discrimination index displayed a **ratio of means** but bootstrapped the **mean of per-block ratios** for the model contrast, without saying so | both estimands are now computed, named and bootstrapped separately; RoM is primary because that is what `PREREGISTRATION.md` §5.5 literally declares | `twin_counterfactual.py` `rom_bootstrap` / `paired_rom_bootstrap` |
| 1b — causal "capacity does not fix it" language contradicted the report's own quantization threat | narrowed to "this deployed artifact did not materially improve the instrument"; capacity is recorded as **untested, not refuted** | report headline 3, §7, threat 5, implications |
| 2 — the dev−blind gap was called a real, bounded self-authorship inflation | renamed the **v1-development versus v2-blind query-set gap** everywhere, incl. the JSON key; kept as a sensitivity analysis; stub-clustered interval added | `eval_v2.py` `query_set_gap`, `evalkit.set_gap_bootstrap` |
| 3a — `ties_in_top5` counted tied *adjacent pairs* and was reported as a *fraction of queries* | per-fusion boolean added; both quantities reported under names that say which is which | `retrieval2.rrf_counted` / `tie_report` |
| 3b — tie prevalence was used causally with no sensitivity run | four tie-handling rules measured; ties are **not** the cause (max movement 0.0052); an arm-agreement mechanism is measured instead | `tie_sensitivity.py` |
| 4 — `L_G_split` was said to isolate "tokenization confined to the tokens field" | relabelled a **composite split-index RRF architecture comparison**; the un-isolable factor is now listed as untested | `eval_v2.py` `split_index_composite` |

### The round-3 run order

Round 3 does **not** require a full cold re-run. Everything is deterministic and `embcache/` is
keyed by model name, so the reruns reproduce every round-2 number bit-identically and change only
the tie block, the renamed keys and the added estimands. `PREREGISTRATION-R3.md` §R3.8 records the
round-2 result hashes and states in advance which files were allowed to change.

```bash
cd experiments/embedder-precision

./.venv/bin/python verify_freeze.py            # always first

# 1. both DI estimands (~30 s warm; ~4 min if embcache/ is cold)
./.venv/bin/python twin_counterfactual.py

# 2. main eval, for the tie-counting fix and the renamed keys (~40 s warm)
./.venv/bin/python eval_v2.py

# 3. EXPLORATORY: do insertion-order ties cause the hybrid to absorb the dense gain? (~30 s warm)
./.venv/bin/python tie_sensitivity.py

# 4. the drift guard, last
./.venv/bin/python report_figures.py --assert   # 95 figures
```

### Round-3 files

| File | What it is |
|---|---|
| `PREREGISTRATION-R3.md` | **Read before any round-3 result.** Pins the RoM estimand, fixes the tie-sensitivity decision rule in advance, declares the renames, and hashes the round-2 result files with the changes that were permitted. `PREREGISTRATION.md` is untouched. Has an **amendment log** at the bottom for the two values that moved unexpectedly — which is also why its mtime is later than the results, and it says so at the top. |
| `tie_sensitivity.py` | **EXPLORATORY.** Four tie-handling rules (`bm25_first`, `dense_first`, `tiebreak_dense`, `tiebreak_bm25`) × 4 hybrids on the blind set, plus the arm-agreement decomposition. Uses its own `index_tie.db`. |
| `results/tie_sensitivity.json` | Its output, including the mechanical evaluation of the predeclared decision rule and per-query ranks for the 9 dense-gain prompts. |

### Round-3 gotchas

16. **Insertion-order ties are a real defect that explains nothing here.** It is tempting to read
    "12.5 % of top-5 orderings are decided by arm order" as the reason bge-large's dense advantage
    vanishes in the hybrid. It is not: swapping arm order or adding an explicit tie-break moves the
    `large_vs_small_hybrid` contrast by **0.0052 — one query**. Do not re-derive the causal claim.
17. **What does explain it is arm agreement, and it is stark.** **960 of 960** fused top-5 slots
    across the 192 blind prompts are held by documents that *both* arms returned. Unweighted RRF over
    two arms cannot promote something only one arm likes. That is why "weight the arms / tune `k`" is
    the named follow-up — and why a negative fused result is not a verdict on the embedder.
18. **RoM and MBR are different numbers and neither is wrong.** The discrimination index as a *ratio
    of means* (primary, preregistered) sits ~0.02 below the *mean of per-block ratios* (secondary),
    and the RoM interval is wider because a ratio estimator propagates denominator uncertainty.
    Quote the estimand name every time. `report_figures.py` checks both so they cannot be swapped.
19. **The dev/blind gap is a set difference, not an authorship measurement.** The JSON key is
    `query_set_gap` and its `interpretation` field says so. If you find yourself writing
    "self-authorship inflation", the review already rejected that phrasing once.
20. **`tie_sensitivity.py` writes `index_tie.db`, not `index_v2.db`.** Deliberate: it must not leave
    the canonical index in a different state. Both are disposable and gitignored.
21. **`eval_v2.py` is safe to re-run and should reproduce every number exactly.** If a metric moves,
    something changed that should not have — check `verify_freeze.py` and `embcache/` before
    believing the new number.

## Files — round 1 (round-2 files are tabulated above)

| File | What it is |
|---|---|
| `dataset_src/cat1_near_miss.py` | Category 1 traps: 28 confusable memory pairs + 28 queries. Hand-authored. |
| `dataset_src/cat2345_traps.py` | Categories 2–5: paraphrase-only, exact-error-string, polarity/supersession, over-length. |
| `dataset_src/distractors_a.py` | 60 distractors, topically adjacent. |
| `dataset_src/distractors_b.py` | 63 distractors, *adversarially* adjacent — other version strings, other env vars, other dotted paths, other migration numbers, so no query's precise token is unique in the corpus. |
| `build_dataset.py` | Assembles the above into `dataset.json`. Validates that no distractor is ever gold and that every referenced key exists. |
| `dataset.json` | **The artefact.** 187 memories, 64 queries, auditable by eye. |
| `leakage_audit.py` | Jaccard + containment overlap, query vs gold and query vs hard negative, overall and per category. The honesty check. |
| `identifiers.py` | Regex identifier extraction for the `tokens` column (config 5). Run it directly for a self-test. |
| `retrieval.py` | Index building and the three arms: FTS5 BM25, sqlite-vec dense KNN, RRF fusion. |
| `sweep.py` | The driver. Metric definitions live in its docstring and are the authority. |
| `twin_duel.py` | **SUPERSEDED by `twin_counterfactual.py`** (review BLOCKER 3): it compared a bare identifier against two topically *different* documents, so topic, length, frequency and containment were all still available, and it treated 14 mirrored twin sets as 28 independent trials against a 0.500 "chance" baseline. Retained for audit. |
| `verify_truncation.py` | Confirms the over-length trap actually fires: counts bge-small WordPiece tokens per memory and locates the punchline relative to the 512 cap. |
| `latency.py` | Warm embed p50/p95, warm end-to-end, cold whole-process, on-disk footprint, reranker cost over 50 pairs. |
| `build_stubs_v2.py` | Builds `stubs_v2.json` from `dataset.json`. Holds the graded relevance table (keys, resolved to uuids at build time) and asserts every v1 gold is still `primary`. |
| `stubs_v2.json` | **Authoring spec for the v2 query set.** One stub per v1 query: trap category, intent, user-side identifiers, a <=15-word situation, graded relevant memories, real confusables. Carries uuids only — the authoring keys leak topic. |
| `check_stub_leakage.py` | Mechanical prose-leakage gate on `stubs_v2.json`: no `situation` may share a 3+ consecutive-word span with any memory gist or content. Exit 1 on violation. |
| `build_queries_blind.py` | Builds `queries_blind.json`. Holds the 192 hand-authored prompts and the structural checks (3 variants per stub, no twin-identifier bleed, register ordering). |
| `queries_blind.json` | **The v2 query set.** 192 prompts, 3 per stub, authored without reading the memories. Each row: `query_id`, `stub_id`, `variant`, `text`, plus `variant_style`, `underspecified`, and `trap_category` / `intent` denormalised from the stub. |
| `results/` | All output JSON. |
| `logs/` | Raw stdout from long runs, kept out of the report. |
| `index.db` | Generated SQLite index. Disposable; rebuilt by `sweep.py`. |

## Dataset structure

`dataset.json`:

```
{ schema_version, n_memories, n_queries,
  memories: [ { uuid, key, cat, gist, content } ],
  queries:  [ { qid, cat, text, gold[], gold_keys[], hard_neg[], hard_neg_keys[] } ] }
```

`uuid` is `uuid5(fixed-namespace, key)`, so ids are **stable across rebuilds** — a rebuild does not
invalidate a previously recorded result. `key` is the human-readable authoring handle; use it when
reading results. `cat` is one of `near_miss`, `paraphrase_only`, `error_string`, `polarity`,
`over_length`, `distractor`. Distractors are never gold, and `build_dataset.py` fails loudly if that
is ever violated.

Category counts: near_miss 28 / paraphrase_only 10 / error_string 10 / polarity 10 / over_length 6
queries, against 187 memories of which 123 are pure distractors.

## Configurations — round 1 (superseded by the 18 round-2 configs above)

Fixed for all of them: RRF `k=60`, fusion depth 50, seed 20260731. **No per-configuration threshold
tuning** — that would flatter whichever one was tuned.

| Name | What it is |
|---|---|
| `1_bm25` | BM25 alone over gist+content (FTS5, `unicode61`). |
| `2_small_noprefix` | bge-small dense alone, no prefix — the incumbent's *exact* current behaviour. |
| `3_small_prefix` | bge-small dense alone with BGE's documented query prefix. Isolates the prefix effect. |
| `4_rrf_small_noprefix` | RRF(BM25, bge-small no prefix) — incumbent as built in `~/Memory`. |
| `4p_rrf_small_prefix` | RRF(BM25, bge-small with prefix) — incumbent as BGE documents it. Baseline for 5–7. |
| `5_rrf_tokens_small` | RRF(BM25 over gist+content+**tokens** with the tokens column BM25-weighted 3.0, bge-small prefix). The zero-LLM lexical proposal, on trial. |
| `6_rrf_bm25_large` | RRF(BM25, **bge-large** prefix) — the scale-only control. |
| `7_rrf_bm25_nomic` | RRF(BM25, **nomic-embed-text-v1.5**) with `search_query:` / `search_document:` prefixes. Tokenizer + 8192 context change. |
| `8_best_plus_reranker` | Best RRF config above, + `bge-reranker-base` cross-encoder over the top 50. The first stage is chosen automatically and recorded in the results JSON. |

## Metrics — round 1 (superseded by `evalkit.py`)

Defined in the `sweep.py` docstring. **`evalkit.py` is now the authority**; see "Round-2 metrics"
above for the mapping. Kept here so round-1 results remain readable:

- **recall@5** — with exactly one gold per query this is also hit-rate@5. The primary number,
  because D12 injects exactly 5 memories.
- **precision@5** — **ceiling is 0.200** with one gold per query. Reported because the brief asked;
  carries no information beyond recall@5.
- **MRR@10** — mean reciprocal rank of the gold within the top 10.
- **hnd** — hard-negative displacement over the **full** ranking: fraction of queries with a hard
  negative where a hard negative outranks the gold. Measures ordering preference, unconfounded with
  recall.
- **hnd_top5** — stricter and operational: hard negative in the top 5 *and* above the gold. This is
  what the agent actually sees.

## Adding a model

1. Confirm fastembed carries it:
   `./.venv/bin/python -c "from fastembed import TextEmbedding; print([m['model'] for m in TextEmbedding.list_supported_models()])"`
2. Add an entry to `MODELS` in `retrieval.py`: `"tag": (hf_name, query_prefix, passage_prefix)`.
   Get the prefixes right — nomic needs `search_query:` / `search_document:`, BGE needs a query-side
   prefix only, and a wrong prefix silently costs quality rather than erroring.
3. Add the tag to `DENSE_TAGS` in `sweep.py`.
4. Add a branch to `rank_for()` and a row to `CONFIGS`.
5. Add the tag to `DENSE_TAGS` in `eval_v2.py`, `TAGS` in `twin_counterfactual.py`, `TAGS` and
   `HYBRIDS` in `tie_sensitivity.py`, and the loops in `latency.py` (and `twin_duel.py` if
   reproducing round 1).
6. Add `D_*` and `H_*` rows to `CONFIGS` and `DENSE_TAGS_FOR` in `eval_v2.py`, plus a branch in its
   `rank_for()`. Add the paired contrast to `CONTRASTS`.
7. Delete nothing from `embcache/` — it is keyed by model name, so a new model simply misses.

Dimension is probed at runtime, so a new dimension needs no schema edit — each model gets its own
`vec_<tag>` table, and `vectors_meta` records model id, dimension and embed mode per table. That is
FINDINGS Open-question-5 hygiene implemented rather than argued about: a same-dimension model swap
is otherwise a silent correctness failure.

## Adding a configuration

Add a `(name, description)` row to `CONFIGS` in `sweep.py` and a branch in `rank_for()` returning a
`[(rowid, score)]` list, best-first. Compose the existing arms — `R.bm25`, `R.dense`, `R.rrf` — and
do not add a tuning parameter without stating it in the report, per Attack 10 in the review.

## Gotchas hit while building this — round 1 (round-2 gotchas 8–15 are in the round-2 section above)

1. **Glueing punctuation out of identifiers manufactures new collisions.** The first identifier
   extractor stripped all punctuation, mapping both `conftest.py` and `conf_test.py` to
   `conftestpy` — creating a fresh collision on exactly the pair the `tokens` column exists to
   disambiguate. The fix is to keep the punctuation *and* build that FTS table with
   `tokenize="unicode61 tokenchars '_-./'"`. **`identifiers.py` and `TOKENIZE_TOK` in
   `retrieval.py` must stay in sync**, or the column silently stops matching and config 5 quietly
   degrades to plain BM25 without any error.
2. **fastembed serves a *quantized* bge-small but an unquantized bge-large.** The cache directories
   are `models--qdrant--bge-small-en-v1.5-onnx-q` versus `models--qdrant--bge-large-en-v1.5-onnx`.
   So `6_rrf_bm25_large` confounds parameter count with quantization, and the latency comparison
   gives small an unearned edge. Reported as a confound rather than fixed; fixing it means
   hand-exporting an fp32 bge-small.
3. **FTS5 needs its query escaped.** Raw user text containing `-`, `.` or `/` is interpreted as FTS
   syntax and raises. `retrieval._fts_query` rewrites free text into quoted OR-terms; the tokenchar
   set differs between the two FTS tables and must match how each was built.
4. **`bm25()` in SQLite returns a *negative* score**, more-negative being better. It is negated in
   `retrieval.bm25` so every arm is uniformly best-first. Forgetting this inverts the ranking and
   the eval still runs, just badly.
5. **fastembed's cache lives in `/tmp`.** Survives across runs but not a reboot.
6. **Embedding 187 documents is not fast on CPU**: ~25 s for bge-small, ~4 min for bge-large,
   ~2.5 min for nomic. Budget for it; it dominates the sweep.
7. **`precision@5` looked broken** at ~0.19 until it was clear the one-gold-per-query ceiling is
   0.200. Do not read it as a failure.

## Exact versions used

Recorded from the run that produced the checked-in results:

- Python 3.12.3, Linux, 12 CPU cores, SQLite library 3.45.1 (FTS5 compiled in)
- `fastembed` 0.8.0, `sqlite-vec` 0.1.9, `onnxruntime` 1.28.0, `numpy` 2.5.1,
  `tokenizers` 0.23.1, `huggingface-hub` 1.26.0
- Models, as resolved by fastembed 0.8.0 (note the `-q` on small):
  `qdrant/bge-small-en-v1.5-onnx-q` (384-d), `qdrant/bge-large-en-v1.5-onnx` (1024-d),
  `nomic-ai/nomic-embed-text-v1.5` (768-d), `BAAI/bge-reranker-base`
- `nomic-embed-text-v1.5` is served natively through fastembed's ONNX path. **No
  `sentence-transformers` fallback was needed**, contrary to the research note's open risk.

`latency.py` records the interpreter version and CPU count into `results/latency.json` so a future
run on different hardware is comparable.
