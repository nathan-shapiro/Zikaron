# FINDINGS — Zikaron

> **Working memory for this project**, maintained by the **memory-researcher** agent. It loads every
> session, so it stays lean: the decision index, where the work stands, and what is still open.
>
> **The design lives in `design/overview.md`** — what we are building, the shape of the system, and the
> full D1–D33 decision table *with rationale*. §"Settled decisions" below is a one-line index only. Read
> `design/overview.md` before revisiting any decision, and never re-litigate one from the index alone.
>
> **The finished record lives in `FINDINGS-archive.md`** — build history, the milestone plan, the
> dogfooding evidence, the references, and §"The knowledge index as built" (M19–M24). Read on demand,
> not every session. It was split out when this
> file reached ~49k tokens and stopped being the lean hub this header claims it is; keeping it lean is
> an ongoing job, not a one-off. When a section here stops being live, move it there rather than
> letting it accumulate.
>
> **That last sentence has now been proven twice, and the second time is the instructive one.** By
> 2026-09-18 this file had reached **~83–89k tokens — well past the ~49k that forced the first
> split** — while carrying a sentence that said it was at ~29k. Nothing noticed for five milestones,
> because the line tracking the size was only ever read by someone working on something else.
> *That figure read "~60k" until a real `/context` reading put this corpus's bytes-per-token at
> **2.7–2.9, not the 4.0 being estimated**; the measurement is in `FINDINGS-archive.md`'s M25 block
> under §"Track C". **Even after that pass this file was ~44–47k tokens — still at the split
> threshold, not under it**, and by 2026-09-20 it had climbed to ~70k again.* Take the reading
> rather than the estimate: `/context` against a known byte total, which is free.
>
> **2026-09-20, three passes in one day: 199,091 → 115,166 bytes, ~70k → ~41k tokens.** Finished
> milestones, then **open questions marked closed or resolved years of milestones ago and still
> carried in full**, then **priority items whose own text says they are done**. That second and
> third category is the lesson: **the archiving rule was written about milestones, and milestones
> were never what made this file large.** Anything that stops being live needs a home, whatever
> section it sits in.
> **And the measurement that drove it was wrong the first time it was taken** — withdrawn-in-place
> text was reported as 39% of the file and is **5%**, because whole *paragraphs containing* a
> strikethrough were counted rather than the struck text itself, in a file whose paragraphs often
> carry no internal blank lines. **What the corrected measurement shows is that there is no culprit
> left**: the largest single entry is 5% and the top fourteen are 36%. The file is **uniformly
> verbose** — roughly 250 entries averaging 500 bytes, each carrying its measurement, its method and
> the lesson it taught. Trimming further means shortening entries, not moving them, and that spends
> the evidential value the withdraw-in-place rule exists to protect.
> **A milestone's block stops being live the moment it is APPROVED; move it then, not when the file
> gets uncomfortable.** The trigger cannot be "when someone notices", because the measurement above
> is what noticing looks like and it took five milestones to arrive.

## Settled decisions — index
One line each. **Rationale, measurements and rejected alternatives are in `design/overview.md` §4.**

| # | Decision |
|---|---|
| D1 | Tribal knowledge only; ~~codebase KB is a separate system~~ — **amended 2026-09-15: that separate system is now Zikaron's own** (`design/knowledge-index.md`). What `remember` accepts is unchanged |
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
| D17 | Scope key = the harness's own project directory where it names one, else the cwd (**amended 2026-08-18**) |
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

### Phase: **M0–M24 built and reviewed. M25 is measurement-complete. M26 is CLOSED and ships
nothing — neither the reranker nor any chunking change. The product is unchanged and that is the
result, not a stall.**

**If you are a fresh session, this is the whole of what you need to know to resume.**

**M26 CLOSED 2026-09-20, ships nothing, and the day's work is worth reading before proposing any
retrieval change.** Four things were measured and three are negative:

1. **The reranker is the wrong build.** §M26's brief claims its target is *"a ranking failure
   inside a document retrieval already found"*. On this corpus that class is 17–23% of queries
   where the answering chunk **was never a candidate at all** — reranking reorders what the arms
   returned and cannot admit what they did not. Its real ceiling is the **16.6%** sitting at ranks
   6–20. Feasibility itself is fine (it does rerank, ~57 ms/pair, bounded by a 4,096-character
   slice); the *justification* is not.
2. **Section-first chunking looked like it doubled quality and made it worse.** 0.267 → 0.593 on
   heading queries; **0.698 → 0.566 on the queries agents actually send.** Overturned the same day.
3. **Query shape was the dominant variable in every measurement**, larger than any chunking or
   ranking difference, and three self-authored oracles were each wrong differently — one of them
   **inverting** the answer rather than merely mis-scaling it.
4. **The one positive: our retrieval stack beats kiro's shipped `knowledge` tool** on the same
   corpus and the same real queries — 0.717 against 0.585, and 0.529 against 0.314 under
   chunking-independent gold. It earns its complexity against the obvious alternative; it just does
   not respond to the levers tried here.

**The standing rule this produced, and it binds the next retrieval milestone:** *before choosing a
query set, go read what the system's real callers actually send.* The recorded `tool_use` blocks
in the M26 trial transcripts are the instrument; they existed the whole time and nobody opened them.

**What is uncommitted**: this file, plus `research/` notes (`m26-chunking-levers.md`,
`kiro-knowledge-head-to-head.md`, `chunking-for-retrieval.md`, `m26-rerank-preregistration.md`,
`cockroachdb-architecture-questions.md`, `trial-corpus-candidates.md`), four `experiments/m26_*.py`
harnesses and three `spikes/spike_*cross_encoder*`/`spike_real_chunk_lengths.py`. **No product,
test or design file changed**; `design/knowledge-index.md` §4.3 is untouched. The gist-as-abstract
fix is committed (`89a1e00`) and is unrelated.

**`design/build-plan.md` §M26 still carries two things that are now known false** and should be
rewritten or struck if the milestone is ever reopened: the `≤250 ms at p50 for a five-corpus
search` bar, which was invented with no measurement behind it (commit `a8cdd87`, whose own subject
is *"a bar fixed on the wrong quantity"*), and the claim that a cross-encoder is *"the standard fix
for exactly that shape"*.

**The design worked out 2026-09-20 and never written down until now — none of it reviewed, and
`design/knowledge-index.md` is normative and does not yet mention any of it:**

1. **Service-owned, loaded lazily once**, a handle on `ServiceContext`; first use loads under an
   `asyncio.Lock` in `asyncio.to_thread`. **Not eager**: the hook spawns a service on every session
   and most sessions never search knowledge, so an eager load puts an 80–150 MB model into every
   service process — and M17 fought hard for that cold start. Lazy also means the default-off path
   loads nothing, structurally. A test must show the load function runs exactly once across N
   searches; a per-search load is disqualifying.
2. **One config key, `retrieval.knowledge_rerank_model`, string, default `""` = off**, read from
   `EffectiveConfig` at search time and **not** seeded into per-KB `meta`. §10's own criterion is
   *does it describe how the index was built?* — a reranker changes no stored byte. M25 recorded
   `rrf_k`/`fusion_depth` being in the seeded group by an argument that does not apply to them; do
   not repeat it. Empty-disables is `embed_prefix_query`'s existing idiom, not a new one.
3. **Rerank the top N of the fused pool, before the per-file cap**, so the cap acts on the final
   order. `search_one` already loads `_stored_chunks` for the whole pool before `_capped`, so the
   stage costs **zero extra queries**. Pool smaller than N reranks what exists. **N = `4 ×
   limit_per_kb` = 20**, a module constant rather than a second key, and it is now justified by the
   headroom measurement below rather than by the latency figure this line used to cite: N=20
   captures 70% of what N=50 would at 40% of its cost.
4. ~~**`Result.score` stays a cosine and group order stays best-cosine.** §7.2/K3/K4 settle cross-KB
   ordering and M19 spike C measured it; this milestone's oracle is within-KB and cannot speak to
   it.~~ **— the second half is withdrawn on operator challenge 2026-09-20, and the challenge
   found something real.** Cross-corpus ordering is the ranking §7.2 *itself* calls *"approximate"*,
   accepting in writing that *"an agent reading only the first group may miss a better result in
   the third"*. **A cross-encoder score is cross-corpus comparable for exactly the reason cosine is
   — a function of a query and one passage, nothing corpus-relative — and it is a far stronger
   function.** BM25 can never cross that boundary. And once each corpus's candidates are rescored
   for the within-corpus ordering, the group key costs **no additional inference**: it is a
   different line, not a second model. So the group key is now a *measured* question with its own
   arm and its own bar. **`Result.score` does stay a cosine** — a new field costs bytes against the
   24,000 cap. Cosine is the incumbent on evidence (M19 spike C: 0.74 against fused's 0.57), so a
   tie leaves it in place. Observable consequence still needing its own test: changing which chunks
   survive can change a group's max cosine and so group order.
5. **Degraded mode**: a missing or unloadable model, or a scoring failure, logs once to
   `service.log` and returns today's ranking. Never fails the search. §11 is the pattern and gains
   a row.
6. ~~**What text the reranker sees — `text` alone vs `path + "\n" + text` — is measured, not
   assumed.**~~ **— superseded 2026-09-20: that framing would have shipped a silent truncation on
   either arm of the choice.** `chunks.text` is unbounded (max 1,072 tokens measured against a 450
   budget), so the question is not which string but **what bounds it**. Answer: `path + "\n" +
   text`, **sliced to 4,096 characters before tokenization** — a cost guard, since tokenizing an
   8 MiB line costs 10 s and the slice makes it 3.4 ms at any input size — after which the model's
   own tokenizer cuts at its 512-token window on a token boundary, truncating the longer member of
   the pair, which is always the document. The path is already what the dense arm embeds, so this
   is the existing convention rather than a new one.
7. **Query-time only: no schema change, no new stored column, no reindex** — operator constraint
   2026-09-20, and it is sharper than anything above. It must work against every knowledge base
   already on disk. It also forecloses the tempting optimisation of precomputing a rerank-ready
   body per chunk, which would force a rebuild of every corpus to turn a ranking tweak on.

~~**The feasibility question that can still kill it, and it is unanswered.** The brief's bar is
**≤250 ms added at p50 for a five-corpus search** — 50 ms per corpus. If a cross-encoder can only
score ~10 pairs in that budget, this is D23's *"reranking 5 candidates is operationally pointless"*
again.~~ **— ANSWERED 2026-09-20, and the bar is withdrawn rather than met.**

**The 250 ms bar was invented.** I wrote it into `design/build-plan.md` §M26 in commit `a8cdd87`
with no measurement behind it — in the same commit whose subject is *"a bar fixed on the wrong
quantity"*. Operator challenge, and it is correct: a single model turn costs minutes, a pull-path
tool call is one the agent chose to make and is blocked on the way it is blocked on a grep, and
nothing is watching a spinner. **Milliseconds are the wrong unit.** What replaces it is
**boundedness** — work per search must not grow without limit in the number of corpora named or in
the size of a chunk — plus cost reported with the machine's load beside it. `design/build-plan.md`
§M26's done-when item 2 needs rewriting; the other two stand.

**Measured** (`spikes/spike_cross_encoder_latency.py`, `spike_cross_encoder_budget.py`,
`spike_real_chunk_lengths.py`):
- **It reranks.** Only **2 of the pool's top 5** survive into the reranker's top 5, on both
  candidate models independently. That was the operator's stated kill condition and it is cleared.
- **~57 ms per (query, 450-token) pair**, flat across pool sizes 10/25/50, so cost is linear in
  candidates and in tokens shown. `jinaai/jina-reranker-v1-tiny-en` is within noise of
  `Xenova/ms-marco-MiniLM-L-6-v2`; model choice buys nothing. Threads: `2` costs 112 ms/pair and
  `4` costs 71.5 against 57 at auto, so pinning is a 25–100% tax rather than free.
- **The first instrument was invalid and the second is why we know.** Sequential runs on a machine
  carrying a moving 4.3-core `java` load put one configuration at **1,229 ms** and the identical
  configuration at **1,647 ms**. Configurations are now **interleaved** — one timed call each per
  round — so contention lands across the grid, and the **minimum** is reported beside the median.
  Operator caught this; every figure in the first table was withdrawn.
- **`chunks.text` is not bounded by `chunk_max_tokens`** — max **1,072** tokens against a 450
  budget, because a single line longer than the budget is stored whole and only its head embedded
  (6 of 2,700 chunks). Feeding that to a cross-encoder truncates silently, and tokenizing an
  8 MiB line costs **10 s**. **Slicing to 4,096 characters first makes it 3.4 ms regardless of
  input size**, after which the model's own tokenizer cuts at 512 on a token boundary, truncating
  the longer member of the pair, which is always the document.
- **The 512-token window has less headroom than it looks.** Real chunk p50 is 408 tokens and the
  embedded form maxes at 473 — but that bound was proved for a sequence holding *only* prefix and
  text. A cross-encoder adds the query: at 9 words nothing overflows, at 36 words 6 of 2,700 do.

**The gate that actually decided the within-corpus half, run 2026-09-20**
(`experiments/m26_headroom.py`, output in the session scratchpad). **Operator's challenge: reranking
results from one corpus sounds like a tautology — why not rank them correctly to begin with?** The
answer is that the first stage is *constrained to be precomputable* (a chunk's vector is built at
index time, so query and passage are never in one forward pass) and a cross-encoder is not — but
that only pays if fusion is **recall-good and precision-poor**, which was unmeasured. It is:

| family | hit@1 | hit@5 | hit@10 | hit@20 | hit@50 | ever in pool |
|---|---|---|---|---|---|---|
| `heading` | 0.200 | 0.387 | 0.473 | **0.553** | 0.633 | 0.687 |
| `masked-100` | 0.193 | 0.433 | 0.660 | **0.833** | 0.940 | 0.973 |
| `masked-50` | 0.480 | 0.713 | 0.860 | **0.987** | 1.000 | 1.000 |
| `verbatim` | 0.687 | 0.873 | 0.967 | **1.000** | 1.000 | 1.000 |

**The pattern holds in every family, including the least heading-like**, so the conclusion does not
rest on the oracle the operator rejected. On `heading` the median rank when found is **4** while the
mean is **13.7** and p90 is **44** — a long tail sitting just outside what a caller sees.
**Headroom at N=20 over today's post-cap hit@5: `heading` +0.187, `masked-100` +0.400, `verbatim`
+0.133.** N=20 captures **70% of what N=50 would at 40% of the cost**, which is what justifies it.
**And 31.3% of `heading` queries never retrieve truth at any depth** — a *retrieval* failure no
reranker can touch, outside M26's fence. It is close to the withdrawn "33% right file not
retrieved" and is **not** a reproduction of it: this counts a chunk absent from a 400-deep pool,
that counted a file absent from a post-cap top five.

**No rebuild was needed** — `~/zk-m26-cockroach/cockroach/.zikaron` already holds the corpus at
commit `13cb3eb2`: 2,700 chunks, 188 files, shipped defaults, `*.md` only, so cleaner than M25's
build, which indexed 20 `.puml`/`.svg` chunks.

**THE RERANKER IS SUSPENDED, 2026-09-20, on a measurement that says it is the wrong build — and
the operator got there first.** His challenge, after the headroom table: *"we should try better
chunking or other approaches. It seems we're chasing something you happened to find convenient
because it seems like making the progress, while it is not."* He is right, and the diagnosis that
followed (`experiments/m26_miss_diagnosis.py`) shows the brief's central claim is false on this
corpus.

**Where retrieval actually fails**, `heading`, n=150, shipped configuration:

| outcome | top 5 | top 20 | top 400 |
|---|---|---|---|
| answer found | 0.387 | 0.553 | 0.687 |
| **right file found, the answering section never returned** | 0.227 | 0.187 | **0.173** |
| right file never returned at all | 0.380 | 0.240 | 0.113 |
| an adjacent chunk of the right section | 0.007 | 0.020 | 0.027 |

**§M26's brief says the reranker's target is *"a ranking failure inside a document retrieval
already found, and a cross-encoder is the standard fix for exactly that shape."* That is wrong
here.** When the right file is found and the answering section is not, **the answering chunk is
not in the pool at all** — the file is represented there by a *different* chunk of itself. A
reranker reorders what the arms returned; it cannot pull in what they did not. So that entire
class, 17–23% by depth, is **unreachable by reranking at any N**. What reranking can actually
reach is the band where the answer sits at ranks 6–20: **16.6%**.

**And the pointer to what *would* work.** Where a chunk of the right file reached the top 20
without the answer, the two are **within 1–2 chunks in 16 of 31 cases**. The answer is adjacent to
something already retrieved. That is a question about where the cuts fall, not about how the
candidates are sorted.

~~**Eight levers compared, and section-first cutting wins decisively.**~~ **— OVERTURNED the same
day by testing the queries agents actually send. Nothing from M26 ships. The table below is
measured correctly and answers the wrong question; it is kept because the reversal is the finding.**

**The reversal.** Real agents do not send the user's question and do not send headings. They send
short keyword queries and reformulate — **55 distinct queries over 10 questions, 2 to 16 each**,
extracted from the M26 trial transcripts' own `tool_use` blocks, which this project had already
copied out of the harness's pruning window for a different purpose and never read:

| the user asked | the agent searched |
|---|---|
| "How does the CockroachDB approach not deadlock? Surely retrying could…" | `deadlock detection transaction locking` |
| "Timestamp cache is critical in providing the guarantee that…" | `timestamp cache availability lease transfer low water mark` |

Scored on those, against trial citations **mechanically validated 57/57** (real file, real line
range):

| arm | all gold (n=53) | control-only gold (n=51) |
|---|---|---|
| **baseline (shipped)** | **0.698** | **0.412** |
| section | 0.566 | 0.353 |
| section_overlap_crumb | 0.547 | 0.333 |

**The shipped chunker wins under both.** Bias was real — the margin narrows 13 → 6 points under
chunking-independent gold — and the ordering does not change. **q03 drops 2/3 → 0/3** under
section-first: its answer is one bullet under a `# Future work` heading, and cutting at every
heading isolates it into a small chunk stripped of context. **Section-first helps broad conceptual
queries find a topical section and hurts specific queries whose answer is one line inside a short
one** — exactly the split `research/chunking-for-retrieval.md` reported (structure-aware wins for
finding the *document*, reverses for finding the *passage*), collected that morning and
underweighted because a self-authored oracle disagreed.

**The transferable rule, which is worth more than the result.** Query shape was the **dominant
variable in every measurement made this day**, larger than any chunking or ranking difference.
Three oracles were used and each was wrong differently: chunk-id + headings (not comparable across
differently-cut indexes, and heading-shaped); line-range + headings (comparable, still
heading-shaped — **inverted the answer**); line-range + verbatim questions (real questions, wrong
*form*). Only the recorded agent queries matched reality. **Before choosing a query set, go read
what the system's real callers actually send** — not the user's words, not a plausible paraphrase,
not a mechanically-derived family. Every one of those oracles was defensible in advance and three
of four were wrong. The operator challenged the heading oracle in M25 and twice more this day
before it was tested.

**A second correction, also operator-prompted.** An earlier revision here called "agents issue many
queries per question" a product problem. The agents' own verdicts refute it — q05: *"The first
search was wasted effort… The second search actually landed the useful document"*; q06 concluded
correctly that the corpus holds no founding design rationale. **A low per-query hit rate with
successful convergence is what working search looks like.** Withdrawn.

Original table and reasoning, superseded — n=150 per family, `heading` the target and `verbatim` the
guard:

| arm | chunks | heading | verbatim | chars |
|---|---|---|---|---|
| baseline (shipped) | 2,720 | 0.267 | 0.640 | 5,702 |
| `no_overlap` *(control)* | 2,440 | 0.253 | 0.527 | 5,784 |
| overlap | 3,129 | 0.320 | 0.827 | 5,784 |
| breadcrumb | 2,440 | 0.320 | 0.527 | 5,785 |
| section | 4,007 | 0.553 | 0.773 | 4,056 |
| section+overlap | 4,273 | 0.567 | **0.847** | 4,220 |
| **section+overlap+breadcrumb** | 4,273 | **0.593** | 0.827 | 4,174 |
| neighbours | 2,720 | 0.540 | 0.933 | **22,584** |

**Target 0.267 → 0.593, guard 0.640 → 0.827, and 27% *fewer* characters delivered.** Costs are
+57% chunks and 366 s → 481 s to build, neither of which a caller experiences. **`neighbours` is
disqualified by cost**: 22,584 characters against the 24,000-byte response cap, so it would sit at
the ceiling dropping groups.

**Three things the run established that argument would not have.**
**(a) The control earned its place.** The variants pack *lines* where the product packs
*paragraphs*, so `overlap` against `baseline` confounded the overlap with the packing unit — and
line-greedy is itself *worse* than paragraph-greedy. Overlap's real effect is **+0.067/+0.300
against its own control**, not the +0.053 it appeared to gain.
**(b) The breadcrumb is free and its mechanism is visible.** No extra chunks, 4 s of build. Its
`heading` *any*-coverage gain, **0.793 → 0.853**, means it reaches sections never touched before —
chunks whose prose never names their subject now carry it — rather than covering the same sections
more fully. **The top two arms differ by less than the n=150 standard error of ≈0.04**, so they are
not separated by these numbers.
**(c) Stitching is a no-op, which corrects an objection of mine.** Merging same-file results whose
ranges touch changes **no hit rate and at most ~1% of delivered characters**, because the per-file
cap admits two chunks per file and a file's two best chunks are rarely adjacent. **So the cost I
raised against overlap — duplicate lines, a wasted cap slot — is much smaller than I claimed**, not
because stitching fixes it but because it seldom arises. Operator proposed stitching; the idea was
sound and the situation it addresses is rare.

**Residual floor whatever wins: 11.3%** never retrieve the right file at any depth — query
construction, untouched by chunking or reranking, and the next thing to measure.

~~**The product change is ~30 lines**, because `chunking.py` is already shaped for it~~ — **true,
and not being made.** Recorded only so nobody re-derives it: `_Unit` gains `starts_section`,
`_paragraph_units` sets it from a boundary detector defaulting to `False`, `_pack` flushes before
such a unit, `_Packer.flush` retains tail units for overlap. The default path would be provably
unchanged and no migration would be needed. **`design/knowledge-index.md` §4.3 is untouched**, and
its *"no gap and no overlap"* sentence stands.

~~**Owed before §4.3 changes**: re-run the winning arms against the 18 real human questions.~~ —
**done, and it measured the instrument rather than the product.** The verbatim questions were the
wrong *form* too; the recorded agent queries settled it. See the reversal above.

**THE ONE POSITIVE RESULT OF THE DAY, and it came from asking whether any of this is worth it.**
Failing all day to improve retrieval raised a question nobody had asked: **does our stack beat a
simple one at all?** Measured against **kiro's shipped `knowledge` tool**, same corpus, same 53
real agent queries, file-level (kiro returns no line ranges):

| gold source | kiro | ours |
|---|---|---|
| all citations (n=53) | 0.585 | **0.717** |
| control-only, grep-derived (n=51) | 0.314 | **0.529** |

**Same direction under both; the chunking-independent gold *widens* our margin rather than
narrowing it.** Not a cutoff artifact — ours is identical at top-3 and top-5, where kiro returned a
mean of 3.9 results. Asymmetry is lopsided: **kiro missed 9 queries we found, we missed 2 it
found**, and its misses cluster on all five deadlock queries (it never surfaces
`select_for_update.md`, even for a query containing that file's key phrase almost verbatim) and
five multi-Raft queries. **Those are the cases where one arm is confidently wrong and fusion
rescues it** — what a hybrid is for, and what M25 measured independently (+0.0764 over
lexical-only, CI excluding zero).
**A second advantage needing no score: kiro's results carry no line ranges.** Its agent cited
`range_leases.md:3` and `closed_timestamps_v2.md:6:1-3` — chunk indices dressed as citations. Ours
carry real ranges, which is the only reason the trial's citations were checkable at all.
Full method, the kiro agent definition, and five stated caveats — including that **kiro's
`Best`/`Fast` index mode was never verified from disk** — are in
`research/kiro-knowledge-head-to-head.md`. **So the retrieval stack earns its complexity against
the obvious alternative; what it does not do is respond to the levers tried here.**

**The oracle had to change, and this is the transferable part.** Every earlier measurement scored
*is the truth chunk id in the top five*, which **cannot compare two indexes that cut the corpus
differently** — their chunk ids describe different things. Truth is now a **line range**: the body
of the section a heading names, read from the file rather than from any index, with the heading
line itself excluded since it contains the query verbatim. A hit is **≥50% of those lines reaching
the caller**. Identical across all four arms, independent of chunking, and closer to what a caller
needs than any chunk identity. **Delivered characters are reported beside the hit rate**, because
neighbour widening buys coverage with bytes and a comparison that ignored size would recommend it
every time.

**A process failure worth more than the result, caught by the operator twice in one session.**
First: *"why don't you want assistant to lookup online how people generally chunk their texts…
I don't think this problem is novel."* I had written two chunking variants from first principles
with `memory-assistant` sitting unused, against a standing instruction that **all** literature and
prior-art search is delegated to it. Chunking for retrieval is a heavily-studied problem and I
treated it as a blank page. Brief dispatched; target `research/chunking-for-retrieval.md`.
Second, earlier: I invented the `≤250 ms` bar, then spent a third of the session defending it.
**The common shape is optimising inside a frame instead of checking the frame** — I challenged
this milestone's bar and its oracle and never once asked whether a reranker was the right thing to
build, which is the question that actually mattered.

~~**And the honest framing for the note**: the 28% band that originally motivated this is
**unreproducible** (below), so the reranker is not justified by it. It is being built because a
cross-encoder is a standard, dependency-free precision lever on a pull path D23 leaves explicitly
open.~~ **— still true about the 28%, and overtaken: "standard precision lever" was doing the work
of a justification and it is not one.** Whatever is built has to be preregistered against a
quantity that survives — M25's lesson is that preregistration protects the threshold and not the
quantity — and, added here, **against a failure the mechanism can actually reach.**

**What survives for the reranker if it is resumed**: the design in items 1–7 above, the
feasibility measurements, and `research/m26-rerank-preregistration.md`, which is written but
unreviewed. Its within-corpus half is now on weak ground; **its cross-corpus half is not**, since
group ordering by best cosine is §7.2's own stated approximation and a cross-encoder score is
cross-corpus comparable. That half is untouched by this diagnosis.

~~**M26 attacks the 28% with a cross-encoder reranker on the pull path**, which D23 leaves
explicitly open and which needs no new dependency (`fastembed 0.8.0` ships `TextCrossEncoder`).
The 33% is a different problem — embedder or query construction — and is fenced out.~~

| ~~outcome, shipped config, post-cap top 5~~ | ~~share~~ |
|---|---|
| right section returned | 39% |
| **right file, wrong section** | 28% |
| right file not retrieved at all | 33% |

**— withdrawn in place, on two counts, and the second is the one that matters.**

**(a) Two of those three numbers cannot be reproduced.** Only the 39% exists in the committed run
(`experiments/results/m25_fusion_sweep.json`, `hit5_capped_heading = 0.3867`). The 28/33 split
appears in this file and in the §M26 brief and **nowhere else**; the JSON is chunk-level
throughout and carries no file-level breakdown, and the sweep store it would be recomputed from
was a scratchpad that is gone. A whole milestone was briefed on an unreproducible split — this
corpus's own *name the quantity* rule, committed in the document that justifies the next build.

**(b) The instrument does not measure the task.** M25's queries are section **headings** lifted
out of the corpus — `"Range leases"`, 2–3 word noun-phrase labels the corpus chose for itself.
The only real knowledge-base queries in this corpus, from the LeibaTrader dogfooding, are
`"does a trailing stop or any underwater stop improve results"` and `"does abandoning an
underwater position or any stop level pay"` — 9–11 word **decision questions** in the agent's own
vocabulary, the second a reformulation of the first. Those are different tasks. So *"39% is bad"*,
the sentence that creates M26, is not established, and the bar is wrong in the same direction:
heading queries hand the lexical arm 0.5950 term overlap with their own answer, where a
cross-encoder earns its keep precisely when query and passage share no words. ~~The heading oracle
therefore **understates** what reranking buys as surely as it misstates the need for it.~~
**M25's own note said this** — *"a real agent asking 'how do I configure the retry budget' is not
doing known-item retrieval"* — and the next brief drew a product conclusion from it anyway.

**The struck sentence is refuted, 2026-09-20, and the correction is stronger than the claim.**
"Understates" assumes the oracle points the right way and merely mis-scales. **It does not: on the
chunking comparison it inverted the answer outright** — section-first cutting scored 0.267 → 0.593
on heading queries and **lost** to the shipped chunker, 0.566 against 0.698, on the queries agents
actually issue. A heading-shaped query favours an index cut at headings; nothing about that is a
scaling error. **A self-authored oracle can be wrong in direction, not only in magnitude**, and the
only fix that worked was reading what real callers send — recorded all along in the trial
transcripts' `tool_use` blocks. Also corrected by the same measurement: those two LeibaTrader
queries are cited above as "the only real knowledge-base queries in this corpus", which was true
when written and is no longer — **53 real agent queries are now on record**, and their form is not
the decision-question form this entry assumed either. Detail:
`research/m26-chunking-levers.md` §§10–11.

**M26 is replaced by an end-to-end trial, and D14's condition is what licenses it**: task-benefit
evaluation was stoved *"until an implementation exists"*, and one now does. Design settled with
the operator 2026-09-18:

- **Subject.** A `cockroachdb/cockroach` clone at HEAD (`~/zk-m26-cockroach/cockroach`), Zikaron
  installed for real, `docs/RFCS` indexed. A **top-level** `claude -p --agent` session on sonnet,
  never a subagent — M16 measured that a subagent gets no MCP registration of its own.
- **Steering, honest and in the repo's own `CLAUDE.md`**: these are design documents, they may be
  behind the code, use them for the *why* and verify the *what* against the source. That artefact
  is itself under test — inventing it is currently the user's job (§16 item 6).
- **Control, run separately: index versus `grep`, not index versus nothing.** The control keeps
  the RFC files on disk and the same steering minus the corpus paragraph. D1's scope test asks
  *could you learn this by reading the code*; the analogue here is *could you get there by
  grepping `docs/RFCS`*, and if yes at similar cost the index is not earning its keep. It also
  preserves grader blinding, which stripping the RFCs would destroy — only one arm could cite them.
- **Questions.** Ten real architectural questions about CockroachDB internals, gathered from Stack
  Overflow and the like (`research/cockroachdb-architecture-questions.md`), **not** selected by
  whether an RFC answers them, which would rig the trial.
- **Two turns per session**, because asking for the verdict inside the answer contaminates both:
  turn 1 the question, answer plus citations to RFC paths and source file:line; turn 2, separately,
  *did the design documents help you, mislead you, or neither — be blunt*.
- **Correctness and cost are co-primary and are never reported apart.** Cheap-and-wrong is the
  outcome that matters most and is invisible if only cost is measured. Cost is denominated as
  **new context ingested** (`input_tokens + cache_creation_input_tokens`), with `total_cost_usd`
  and wall clock beside it — cache reads are nearly free and would otherwise price "more turns" as
  "more waste". `claude -p --output-format json` carries all of it plus `session_id`.
  **`usage` and `modelUsage` are different quantities** — measured 10 against 909 input tokens on
  one run — so establish which is which before quoting either.
- **Correctness is graded by a separate opus session per answer**, no knowledge base, codebase
  access, given only the question and the answer — not the arm, not the transcript, not the
  self-report. Per claim: supported / contradicted / unverifiable, each with the grader's own
  `file:line`, and a distinct flag for *true of the design document, not of the current code*.
  **Unverifiable must not collapse into wrong** — this project rejected LoCoMo for excluding
  abstention from its grading. Every verdict carries a citation so a non-expert can spot-check
  three rather than read twenty.
- **The shared blind spot stays on the record**: subject and grader are one model family on one
  codebase, so a misconception they share is invisible. This is the `memory-reviewer` independence
  loss again, with a shared corpus on top.
- **The row the trial exists to produce**: agent says *helped*, grader says *contradicted*. That is
  misled-and-did-not-notice, which no self-report can catch alone and no ranking metric can see.

**Run 1 is done — 10 questions × 2 arms × 3 repeats, artefacts in `~/zk-m26-cockroach/` — and it
has two results, one of them about the trial rather than about the product.**

**(a) On cost the arms are indistinguishable, and the within-cell noise is the reason.** New
context ingested, median of per-question medians: **KB 24,452 against control 26,002**, a 6%
difference, with per-question ratios running **0.40 to 2.39 in both directions**. Totals $4.38
against $4.76. **An n=1 pilot on the same question had shown the index 2.3× cheaper and that was
sampling noise**: q01's three KB runs are 20,357 / 17,951 / 9,340 and its control runs 47,785 /
26,576 / 16,877. The widest single cell is q02's control arm at **3,240 to 32,558 — 10× on one
question in one arm** — and one q16 control run ingested **2** new-context tokens, answering
from the model's own memory with no tool call at all. **Three repeats is the minimum that makes
this visible and is not enough to measure a small effect through it.**

**(b) The corpus is contaminated for this design, and that is the finding worth keeping.** The
agent already knows the CockroachDB tree at file-name granularity, so the control never pays for
the exploration the index exists to save. Measured from the transcripts: in **12 of 30** control
runs the *first* tool call greps a specific subsystem path with no prior listing —
`pkg/kv/kvserver/closedts`, `pkg/config/zonepb` (all three runs), `pkg/kv/kvserver/replica_tscache.`
— and one run opens by naming a specific RFC **filename**, `docs/RFCS/20180603_follower_read…`,
before searching anything. It is not the instruction file: CockroachDB's own `CLAUDE.md` names
only `pkg/util/log`, `pkg/sql` and `pkg/clusterversion`, and carries no directory map.
**This is `FINDINGS` open question 9's django/django threat, walked into with the note already in
the corpus** — *"the most pretrained-on repo in the set, where an external store of its
conventions is least likely to add anything"*. The corpus was inherited from §M25's brief, where
it was only a retrieval target and the choice was sound; it stops being sound the moment a
model's own recall is the control arm.
**Scope the damage rather than writing the run off**: contamination bites hardest on **cost**,
because an agent that need not explore cannot be saved the exploration. It bites far less on
**rationale**, which is what an RFC holds and which is much less memorised than file layout — the
control grepped `docs/RFCS` in 12 of 30 runs and mostly discarded what it found, while the KB arm
pulled `20171024_select_for_update.md:75-87` and used it. So the correctness half is still worth
grading; the cost half is not evidence about the product.
**Run 2 goes to a repository the model does not already know**, and the instruction file is
stripped to generic content plus the knowledge paragraph first, so the arms differ in one thing.

**Whether a reranker is the right build is downstream of this and is not currently decided.**
**Do not open another measurement milestone before something ships.** M25's own accounting is
that rounds 1–2 of its review earned their cost and rounds 3–4 bought hygiene; the milestone
produced four artefacts, a closed open question and **zero product change**. That was the right
outcome for a sweep and is the wrong pattern to repeat — and this trial avoids it only if its
output is a decision about what to build, not another table.

M25's own block **moved to `FINDINGS-archive.md` 2026-09-20**, into §"M25, and the last three
pre-knowledge-index milestones". The three design questions its dogfooding opened are **still
unresolved and are not closed by that move**: **intra-document supersession** (withdraw-in-place
documentation is adversarial to chunk retrieval, and this repository writes that way), the
`git_mode` default, and who owns scan scheduling.
*This header previously read "every milestone in `design/build-plan.md` is landed… the next work is
not a milestone", which was true when M18 was the last one and was never revised as the knowledge
index added M19–M25 beneath it. Corrected rather than withdrawn in place: it is stale **state**, not
a refuted finding, and this file's own header says state gets edited. Worth one line anyway, because
it is this corpus's two-sites lesson in its purest form — a summary at the top of a document
contradicted by 1,500 lines of the document, surviving six milestones because nobody edits the part
they are not working in.*
The pre-knowledge-index milestones, in brief. M18 landed 2026-09-14, APPROVED after 24 rounds, as
"M18: the result that did not fit, and the path that did"; every question its done-when asked is
answered by measurement.
M17 landed 2026-08-25, APPROVED after seven rounds
— four on the brief and three on the code — and its A/B is `research/m17-cold-start-ab.md`. M16
landed 2026-08-16, APPROVED after five rounds; its dogfooding evidence is
`research/claude-code-dogfood-checkpoint.md`. M15 (the installer adapter) landed 2026-08-16,
APPROVED after six rounds; what it built and what its rounds taught is in `FINDINGS-archive.md`
§"M15 as built" — history, not a starting point.

**`design/harness.md` is normative for every harness-coupled fact.** Read it before touching the
hook, the MCP client or the installer, and do not re-derive one from an older section of
`architecture.md`.

**What is true of the product right now, which M15 changed.** Both thin clients *and* the installer
speak both harnesses. `python -m zikaron.install --project .` writes either harness's artefacts, runs
from a plain shell with no harness process, and refuses when the harness's own binary is absent.
**But nothing is installed into this repository yet** — that is a choice, not a gap. Until someone
runs it, the memory tools and the push hook are **not live in this session**. M16 chose a throwaway
over installing here (its reasoning is in `FINDINGS-archive.md` §"M25, and the last three
pre-knowledge-index milestones", under the M16 item); installing into this repo remains available,
and unexercised, as:

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
(`reviews/m14-harness-seam-review.md`).
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
a small store from a seeding experiment. ~~`~/Memory` is the **primary real-work store**~~ — **that
is stale, corrected 2026-09-20**: `~/Trading/LeibaTrader` held **252 memories and 116 planned
groups** on 2026-09-13 (`research/consolidation-payload-sizes.md`, measured read-only), against
`~/Memory`'s 31 long-term records and 26 journal entries at last count. **LeibaTrader is the primary
real-work store** — it is where every production report since M17 has come from, and it is where
this change's owed baseline is read.
`~/Memory` had one consolidation run completed (all 31 promoted in place,
zero merges) and remains the corpus a consolidation A/B would run against. It is otherwise
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

### The gist was being read as the finding — a production report, and the fix

**Reported 2026-09-20 by an agent using Zikaron for real work in `~/Trading/LeibaTrader`, in its
own words**: because only gists surface and a gist is condensed, it *"takes the gist as a truthful
fact even if content of the memory is more nuanced"*, and treats that as *"a license to not think
critically"* — answering with a claim derived from the gist alone, sometimes inaccurate, which the
operator describes as reading *arrogant and ignorant*.

**The two records it named**, both of which it says it had never fetched — its own account, relayed
by the operator in conversation with no transcript copied, and not checked against the store's
`surface`/`fetch` rows:

| uuid | gist |
|---|---|
| `247ec4ee` | "Recurring failure here: asserting analytical claims without measuring them, then defending the frame" |
| `97250485` | "This store is selection-biased toward failures — treat a uniformly negative retrieval as a property of the sample, and NEVER as a reason not to try something" |

**Both are conclusion-shaped and both are about the reading agent's own behaviour**, which is the
class where a gist-only read misleads hardest: an agent has no independent check on a verdict about
itself, and such a record reshapes a posture rather than being "stated as fact" in any step the
agent can observe itself taking. That is also the class this fix is weakest for, and
`design/retrieval.md` §"Push output format" says so beside the fix rather than after it.

**The corpus already held the mechanism and had only fixed the write half.**
`design/write-policy.md` §1 records the 2026-08-03 incident in the same terms — *"every memory has
a gist/content boundary, the gist is the half that gets injected, and a qualifier on the far side
of that boundary is a qualifier that will be recalled without its claim… The content cannot rescue
a gist that has already been believed."* The rule added then was write-side (*"if a claim expires,
the gist has to say so"*). Nobody did the read side for the seven weeks between that rule and this one.
**And that incident caps what the read side can buy**: the agent there *did* fetch, read the
qualifier, and kept the gist's framing anyway.

**Shipped 2026-09-20 across three surfaces** — the injected block, `zikaron_memory_search`'s
description, and the write policy's recall paragraph — plus the untrusted-reference frame on
`zikaron_memory_search` and `zikaron_memory_fetch`, the latter the surface this fix sends more
reads to. The recall paragraph had been
asserting the opposite (*"The records themselves are not suspect — the choice of which five you
were shown is"*). Each of the three names a gist as an abstract of a longer record and ties the
fetch to a **detectable occasion** — *before you state one as fact, or act on one* — rather than
to a resemblance judgement, which is the trigger shape the write policy already had to abandon
once. Review trail: `reviews/gist-abstract-read-path-review.md`.

**Owed — stated in `design/retrieval.md` §"Push output format", tracked here**: the pre-change
share of surfaced uuids fetched before their session's next write, **over LeibaTrader**, the store
the direction will be read in (single-harness from its first day, so the 2026-08-16 baseline reset
cannot bite: its `service.log` begins 2026-08-18, after M15 gave Claude Code an installer, and M17's
08-19 diagnosis already reads it under `SessionStart`), **over the sessions whose last event has `at`
before
`2026-09-20T05:00:00+00:00`** — 2026-09-20 00:00 on the store's machine (`America/Chicago`, UTC−5
under CDT; it would be 06:00Z under CST), written as the UTC instant because `event.at` is UTC
(`core/clock.py`). A bare `at < '2026-09-20'` on that last event cuts five hours **early**, dropping
any session that ended in the evening of 09-19 local from the pre-change side; it cannot admit
anything post-change.
**Midnight is safe because the fix's first edit to any shipped file came after it**: `block.py` at
`2026-09-20T07:35:13.666Z` = 02:35:13 local, `primary.py` 54 seconds later, and `write_policy.py`
within the hour (this session's transcript, `cc39b148-fca0-447f-b75b-5e011621d1dd.jsonl` lines 1672
and 1717). Nothing that **ended** before local midnight could have carried new text on any surface,
so the bound is conservative by at least 2 h 35 min. (A session that *started* before midnight and
ran on could carry it after the restart — which is why such sessions are straddlers, excluded whole
by the rule below.) **Neither bound is ever a bare date**, and **both
sides are sets of sessions rather than dates**. The block is rendered in the service,
so it reached that store at the first *service* start after the edit — on the 30-minute idle default
a session running through the edit keeps the old block until its next idle gap — while the policy
and the search description reach a session at *its* own start, and no event records which text a
push or a session carried.
**That restart has happened and its instant is checked, so this is a number rather than a
procedure**: `~/Trading/LeibaTrader/.zikaron/service.log` records the first start after the
block's last write (`block.py`, 03:01:57 local — `write_policy.py` and `primary.py` were last
written later, at 03:32:22, a one-line rewrap of both policy copies, and 03:43:47, a byte-identical
restore after a mutation run whose last *content* change was earlier; **all three precede this
start**, which is what the rule below needs) at
**2026-09-20 04:40:06.416 local = `2026-09-20T09:40:06.416+00:00`**,
pid 2401132, launched from `/home/nathan/Zikaron/.venv` as every LeibaTrader client is — its
`.mcp.json` names that venv's `zikaron-mcp` for both servers and `.claude/settings.local.json` its
`zikaron-hook` on all three triggers — so any start-if-absent from that project resolves `block.py`
to this working tree. **Count as post-change every session whose first event has `at` at or after that instant, and
as pre-change every session whose last event has `at` before the pre-change bound.** Every other
session — one that began between the two bounds, or one with events on both sides of either —
belongs to neither side, **whole**: a session is never split between sides, because the unit below
is a pair whose window runs to its session's end. The cost is **every session on neither side** —
any with an event between the two bounds, and any whose events sit on both sides of the gap with
none inside it, which is the shape of an overnight session resumed after 04:40 — **plausibly at
least one**, since the log shows the store active between them (a
start at 01:09:29 local, and a last request near 04:04:36 by subtraction from `idle_for=1804.1s` at
the 04:34:40 stop), though it records neither which request nor whether that request wrote an
`event` row at all — and its size is one query, reported beside the share. The 09-19 log's overnight
restarts show the habit is not a one-off, though that night lies wholly inside the pre-change side.
*(`service.log` appends across restarts and stamps in **local** time — it logs both
the startup config dump and the idle stop — so any later re-derivation converts the same way.)*
"Before" and "after" between rows are `event.id` order, which is authoritative
because two rows can share an `at`.

**Unit, stated so no decision is left in it**: distinct `(session_id, memory_uuid)` pairs among
`surface` rows whose `session_id` is **harness-labelled** — a `zk-`-prefixed label is one the
service minted for a single client process, which a hook cannot share with an MCP client, so such a
row is a one-push "session" that can never hold its own `fetch` and would score unfetched by
construction; those are reported by count and left out. The unit is pairs rather than `surface`
rows, which are one per push and would count a re-surfacing of an already-fetched record as
unfetched. A pair counts as fetched if a `fetch` row for that uuid and
session falls after the pair's first `surface` row and before that session's first `remember`,
`amend` or `retire` after it, or the session's end. **Pairs whose session later amends or retires
the uuid are counted separately**: D26 requires a receipt for those, so the write path forces the
fetch whatever the agent read it for, and pre-change they are plausibly most of the numerator. That
bucket is taken first, whatever the fetch's timing, and left out of the share — the direction is
read from pairs fetched in-window over all pairs not in it, with the bucket's size reported beside
it. Without that precedence a session that surfaces `X`, writes `Y`, fetches `X` and amends `X`
would score the pair unfetched, the window having closed at the unrelated write. A
`fetch` preceding the first `surface` does not count — that is a pull-path read, and this
instruction is about the lines the block printed.

**`~/Memory` can add a second, informational number only if the operator supplies its harness
cutover.** This corpus does not record whether that store ever moved harness, and its events
cannot say: `event` carries `client_kind` and deliberately no harness field, and both harnesses'
session ids are uuid4. Its rows through 2026-08-14 are kiro-era in any case, with a large,
unmeasured share of its reads from a different model family (open question 1), and this file's
08-16 decision says not to compare across that boundary.

That LeibaTrader share is the change's only signal, the same join under a different projection
would settle whether the two records above were really never fetched, and **no baseline has been
taken**.

**`97250485` is a second, unfixed defect and it is on the write side.** *"…and NEVER as a reason
not to try something"* is an order, and the policy's own rule is **"Write observations, not
orders"**, whose stated reason is that *"a memory phrased as a command will be obeyed by someone
with less context than you have"*. The policy's §1 already records that prohibition failing to
catch an imperative once; this is the second instance, in production. Not fixed here.

### Live work: an indexed-knowledge tool, and D1's premise failing under the port

**Opened 2026-09-14 on operator direction.** D1 reads *"Zikaron is not a codebase knowledge base — a
separate system handles code structure, symbols and repo maps."* **That premise was true under
kiro-cli, which ships a built-in `knowledge` tool, and it is false under Claude Code, which has no
equivalent.** D1 outsourced a responsibility to a system that stopped existing when the harness
changed, and nothing in the migration noticed: M13–M16 checked that *our* harness-coupled facts moved
correctly and never asked whether a decision's *external dependency* survived. Operator's framing,
which is the authoritative one here: the scope line was set while targeting kiro, he has since
switched to Claude Code, and the missing knowledge tool is a real gap in daily use.

**Refined the same day, before the source traces landed — the mapping above is too simple, and the
premise failure is *broader* than stated.** `research/kiro-knowledge-tool.md` finds that kiro ships
**two** relevant built-ins: `knowledge` (a *generic text/document* semantic index — file and directory
paths, broad text-ish extension list, generic chunking, no AST or symbol awareness) and a separate
`code` tool ("symbol search, LSP integration, and pattern-based code search and rewriting").
**D1's wording — "code structure, symbols and repo maps" — matches `code`, not `knowledge`.** So the
sentence above, which credited D1's premise to the knowledge tool, is withdrawn as written: *both*
capabilities are absent under Claude Code, the one D1 actually leaned on is the one nobody has
proposed rebuilding, and what the operator is asking for is the *other* one. Flagged by the doc pass
as needing source verification before D1 is formally revised; the two traces in flight cover it.

**So "should Zikaron index code?" is a live question rather than a settled one.** What is *not* yet
decided is whether the answer is to widen D1, to build a sibling system that shares Zikaron's
substrate (SQLite + sqlite-vec + fastembed are already here), or something else. Do not treat this
entry as a decision — it records that the ground moved.

**The general lesson, worth more than this instance:** a decision that delegates to an external
system carries a dependency, and a dependency can disappear without contradicting the decision's own
text. D1 still *reads* true. Nothing in `check.sh`, the review loop or the harness seam can see this
class of failure, because the decision is internally consistent and only its environment changed.
Worth a sweep of the other decisions for outsourced premises — D8's "no global tier" and D23's
"open for the pull path" are the obvious candidates to check.

**First evidence in, and it is not flattering to the thing we are copying.** Per
`research/kiro-knowledge-tool.md`: kiro's `knowledge` uses **`all-minilm-l6-v2`** for its semantic
mode and offers **Fast (lexical) or Best (semantic) as an either/or choice per entry, not a fused
hybrid** — so on both counts our shipped retrieval stack is arguably ahead of it, since D5/D20 give
us RRF over both arms simultaneously with a stronger embedder. And **it has no staleness story at
all**: updates are manual (`/knowledge update`), there is no watch mode, and the documentation never
engages with what happens to results after files move underneath the index. That is the single
sharpest contrast with this project, which has an entire decision (D11) about exactly that failure.
**Do not copy this design wholesale**; the thing worth taking from it is the agent-facing surface and
the file-selection rules, not the retrieval architecture.

**"Arguably ahead" was measured on 2026-09-20 and is now *ahead*, which is the first time this
claim rested on anything.** Head-to-head on one corpus and 53 real agent queries: **ours 0.717
against kiro's 0.585**, and **0.529 against 0.314** under chunking-independent gold.
`research/kiro-knowledge-head-to-head.md`. It was asserted from architecture for six weeks before
anyone tested it.

**But the wider dismissal of Amazon Q was wrong, and the correction matters more than the win.**
This corpus recorded their tool as amateurish on an architectural scoreboard **this project
invented** — hybrid beats either/or, agent-triggered beats human-triggered, a staleness story beats
none — and never checked whether that scoreboard predicted usefulness. On 2026-09-20 it did not:
a day of work established that two proposed improvements to our own retrieval are worthless and one
is actively harmful. Three specific reversals.
**(a) "The human is the trigger" was filed as a weakness.** Their documentation tells the *user* to
say "using your knowledge tools, find…". But the measured bottleneck is **query formulation**, and
putting a human at exactly that step answers the hardest problem here rather than failing to
automate it.
**(b) "Fast or Best, an either/or" was filed as behind us.** M25 measured that exact-phrase and
conceptual queries want **opposite arm weights** and no constant serves both. Letting a user choose
per corpus is crude and addresses a real problem we have not solved.
**(c) AWS steering large codebases to the lexical arm** was filed as corroboration of our
identifier finding. It is also a shipped workaround for something we keep measuring and not fixing.
**The defects still stand, because they are wrong on any scoreboard**: `chunk_size: 512` counting
whitespace words against a 512-*token* model with no truncation; `avgdl` 5.0 at build and 100.0 at
load so rankings change after a restart; BM25 scores and cosine *distances* sharing one `f32` with
both sorts ascending; `contexts.json` written with `fs::write` and read with `unwrap_or_default()`;
the one test that measured retrieval commented out.

**Provenance on the two Amazon Q source traces, operator-supplied 2026-09-20 and unverified here.**
That codebase was built under a dramatic reduction in force, largely by two new graduates, and the
product was then deprecated in favour of kiro. **It fits the evidence** — the retrieval internals
carry defects no review would pass, while the surrounding platform choices (default-off with the
tool spec *removed from the schema*; a SHA256 model allowlist pinning `tokenizer.json`) show
judgement from somewhere else. **Consequence for how those notes are read**:
`research/amazon-q-knowledge-engine.md` and `research/amazon-q-knowledge-integration.md` are
evidence about **one rushed implementation of a deprecated product**, not about the design space,
which bounds anything drawn from them — particularly "their result shape is worse than the obvious
design" and the four schema/implementation contradictions, now unsurprising rather than
informative. **kiro is closed source and its documentation says little about implementation**, so
the live comparison is behavioural, not a source reading.

**The two source traces moved to `FINDINGS-archive.md` 2026-09-20**, into §"Closed priority items
and the Amazon Q source traces" — that arc closed when the head-to-head replaced reading their code
with measuring kiro's behaviour. **Three things from them are still live and are kept here.**
**(a) The one genuinely portable idea, still unbuilt**: a **SHA256 model allowlist**, one pinned
hash per file, verified before use, the file deleted on mismatch so the next run re-downloads — and
it pins `tokenizer.json` too, which is what makes tokenizer-dependent bounds *provable*. ~20 lines
in Python, and it closes a hole D19/D20 leave open.
**(b) The gating shape worth copying**: default off, and when off the tool spec is *removed from the
schema* rather than refusing at call time — the same structural "provably cannot reach" property
D32 gives the consolidator split.
**(c) A real alternative to D8/D17 never examined here**: storage partitioned by **agent identity**
rather than by working directory. Notes: `research/amazon-q-knowledge-engine.md`,
`research/amazon-q-knowledge-integration.md`, `research/kiro-knowledge-tool.md`.

**The design is written and APPROVED after twelve review rounds: `design/knowledge-index.md`**
(16 sections, K1–K13 decision index, 16 invariants, and **13 §16 items of which three are closed** —
item 2 by M19 spike C, items 9 and 11 by M21's throughput measurement — leaving 10 open. The count
grew with the milestones that raised the questions, so **re-count it rather than quoting this line**:
it was 11-of-which-1 when M19 landed and both halves moved without the total appearing to. **The
line count that used to sit here is deliberately gone**, being a confident-looking number that every
ordinary edit falsifies, which is this file's own M13-hash lesson in miniature; it was already wrong
by 25 lines one review round after it was written.)
Trail: `reviews/knowledge-index-review.md`. It **does** now have milestone briefs —
`design/build-plan.md` §§M19–M25 — of which **M19 through M24 have all landed**, their blocks moved
to `FINDINGS-archive.md` §"The knowledge index as built" on 2026-09-18, leaving **M25** live below.
*This line previously read "of which M19 has landed (below)", and both halves went stale: five more
milestones landed after it, and the block it pointed at has left this file.*

**It is normative, on operator sign-off 2026-09-15** — taken at M20, the first milestone to write
product code against it, rather than at M19, which was a spike that wrote none. `CLAUDE.md`'s design
table carries its row. The split of authority, stated because two documents now describe one file:
`design/schema.md` owns `memory.db`'s tables **including the knowledge-base registry**, and
`design/overview.md` owns every memory-store decision; `knowledge-index.md` owns everything else about
the index. **D1 was amended in the same sign-off**, withdraw-style, in `design/overview.md` §4 and in
the index above: the separate system D1 delegated to is now Zikaron's own, and what `remember` accepts
is unchanged.

**Rounds 11–12 reviewed a substantial operator-directed revision *after* the round-10 approval**, and
the revision is the current design: the knowledge-base registry moved into **`memory.db`** (so KB files
are `knowledge/<uuid4>.db`, names are free-form and lower-cased, and path traversal is impossible by
construction rather than by a validated grammar); all chronological narration was stripped on the
operator's instruction that **a design document states what we are doing, with rejected alternatives at
the end** — historical traces make it unusable over time, and the review trail already holds the
history; `zikaron_knowledge_list` was added as `status` projected down; `state` gained `indexing` and
`error` plus a `files_remaining` count; a missing database file became an **empty knowledge base**
rather than an error; **file-rename detection was removed** as measured over-engineering; and
`snippet` was finally defined — the document had used the word six times without saying what it was.
~~**`design/schema.md` is deliberately untouched**; it gains its section when the schema change is
made.~~ **— that was true of rounds 11–12 and was overtaken by M20**, which made the change: the
section is §"The knowledge-base registry", and it is the contract the code is compared against.

**What the ten rounds are evidence of, since the count is extreme even by this project's standards.**
Findings ran **23 → 14 → 9 → 8 → 6 → 5 → 2 → 4 → 3 → 3**, and the sequence is not monotonic because
**four rounds' blockers were cascades from the immediately preceding round's own fix** (3→4, 4→5,
7→8, 8→9). Twice the reviewer identified *its own* prior recommendation as where the ambiguity
entered. The mechanism is worth knowing before anyone plans a review budget: in a document this
interconnected, a fix is an edit to a system, and the defect rate of fixes is not obviously lower
than the defect rate of the original prose.
**Two classes dominated, and neither is catchable by `check.sh`.** (a) **Neighbour contradiction** —
a fix landing in one section while an adjacent one keeps asserting the pre-fix world; round 2 was
four blockers of this shape alone. (b) **Enumeration drift** — a claim stated in three places, two
updated. The guard that works is mechanical: **grep for every statement of the claim and reconcile a
count**, not re-read the sections a reviewer quoted. Full write-up, with all four instances of the
day: `FINDINGS-archive.md` §"Dogfooding notes".
**The most valuable single finding was a security hole**, not a design flaw: nothing constrained a
knowledge-base name, and `<name>` is interpolated into a path that `remove` unlinks — so
`zikaron_knowledge_remove(name="../memory", confirm=True)` resolved to `.zikaron/memory.db`. **An
agent could have destroyed the memory store with one tool call.** Found in round 1; now a validated
grammar plus invariants 11 and 14.

**The evaluation work of the same day is PARKED, not abandoned**, on operator direction — the
benchmark question was sidelined in favour of this. Its state is complete and resumable:
`design/evaluation.md` (proposal), three research notes, and open question 9 rewritten. Nothing is
half-edited.

**M25's block has moved** to `FINDINGS-archive.md` §"M25, and the last three pre-knowledge-index
milestones" (2026-09-20), being measurement-complete. Its artefacts: `research/m25-fusion-sweep.md`,
`research/m25-fusion-sweep-preregistration.md`, `experiments/m25_fusion_sweep.py`,
`experiments/m25_build_sweep_corpus.py`, `experiments/m25_verify_note_figures.py`, and
`experiments/results/m25_fusion_sweep.json`. **Three design questions it opened are still owed and
are not closed by the move**: intra-document supersession (withdraw-in-place documentation is
adversarial to chunk retrieval, and this repository writes that way), the `git_mode` default, and
who owns scan scheduling. **And its central instrument is now known to invert rather than merely
understate** — see the M26 entry above and `research/m26-chunking-levers.md` §§10–11.

**What to do next, in priority order.**

*Archive pass — **both parts done**. Part 1, 2026-09-18: M19–M24 to `FINDINGS-archive.md`
§"The knowledge index as built", 1,442 lines, 240,104 → 120,995 bytes. Part 2, 2026-09-20: **M25
and the three items numbered `0.` (M18, M17, M16), with M17's superseded cold-start diagnosis
paragraphs travelling with it**, to §"M25, and the last three pre-knowledge-index milestones",
**199,091 → ~140,600 bytes (≈70k → ≈50k tokens)**. Both moved byte-for-byte with a reading note at
the destination rather than re-pointed sentence by sentence, because the archive's header says to
append rather than rewrite.*

*Three things part 2 had to respect, recorded because they still bind anyone touching items 1–6
below.* **The `0.` numbering was deliberate** — removing those three renumbers none of items 1–6,
which matters because **these items are cited by number from outside this file, where a silent
renumber is undetectable**. Counted rather than recalled: **items 3, 4 and 5 plus a lettered item
(b)** are cited from `design/knowledge-index.md` §10, `research/amazon-q-knowledge-integration.md`,
`research/claude-code-install-artefact-contract.md`, `reviews/m14-harness-seam-review.md` and
`reviews/knowledge-index-review.md`. **`design/build-plan.md` §M17's two references now point
across files**, into the archive; the pointer *between* the M17 item and its superseded paragraphs
stays internal, which is why they moved together despite not being contiguous here. And the resume
block's *"see its item below"* pointed at the M16 item and has been re-pointed.

**The standing lesson this pass exists to carry, which cost five milestones to learn.** The
sentence tracking this file's size said **~29k tokens** while the file was at **~83–89k** — it was
plausibly true when written at M20, the file more than doubled through M21–M25, and nobody edited
the one sentence whose entire job was to track that quantity. It was caught only because an
unrelated pass happened to measure it. **Take the reading rather than the estimate**: `/context`
against a known byte total is free, and the two eyeball methods used here disagreed by 20% while
both were wrong in the same direction (the real ratio is ~2.7–2.9 B/token, not 4.0).
1. **The next consolidation, on a journal grown by real work.** That is when open question 12's *positive*
   merge criterion gets designed and tested. The prompt currently has reasons to split and none to merge,
   deliberately, on operator decision — do not revert it on the strength of the 11-merges-to-0 result.
2. **DONE in M16 — the recall instrument was read.** **0.83 searches per user turn**, memory-naive
   agent, zero operator nudges, and **0 of 3** searches against a non-empty store came back empty.
   **The pre-migration numbers are a different-harness baseline and are not to be compared against,
   in either direction.** The mechanism half of open question 1 is untouched: every search happened
   at task-framing time, so the mid-task moment where no injectable hook fires is still the real
   work. Full entry: `FINDINGS-archive.md` §"Closed priority items and the Amazon Q source traces".
3. **DONE in M14 — `gist` is bounded, by characters rather than bytes.** `GIST_MAX_CHARACTERS =
   1024`, a fixed constant in `core/indexing/chunking.py`, counted in **UTF-16 code units** and
   reported against field `gist.characters`. **The live arithmetic**, restated after the
   2026-09-20 preamble change: framing for five demoted rows is **1,309 units**, a five-row block is
   **6,429 units (64% of 10,000)** and **19,287 bytes (29% of 65,536)**, the per-gist ceiling is
   **1,738**, and admitting prose at `gist_max_tokens` 256 would put the same block at **92%** of
   budget. **Those figures live in six places** — here, `schema.md` §Bounds, `architecture.md`'s
   margin claim, the comment on the constant itself, `hook/limits.py` and `harness.md` §"Injection
   budgets" — and preamble prose moves every one of them. Full entry, including the trade at the top
   of the token range: `FINDINGS-archive.md` §"Closed priority items and the Amazon Q source traces".
4. **FIXED in M15 — the installer now detects *same install, older version*.** Staleness became a
   **content comparison**, which subsumes the old interpreter check and extends it to every shipped
   file; kiro's skill could previously never be refreshed at all, its staleness predicate being the
   constant `False`. **It is a trade**: content is the only evidence available, so a hand-edited
   artefact is backed up and reverted rather than kept. `architecture.md` §"The install contract"
   carries the argument and the two remedies deliberately not built.
5. **`BudgetUnit.CHARACTERS` is now known to be the ambiguous word, and the D34 table cannot say
   otherwise.** M16 measured the Claude Code injection budget in **UTF-16 code units**, which is
   exactly the distinction "characters" fails to make — and `exceeds_injection_budget` already
   implements it. But `tests/test_harness_table.py::test_injection_budget_value_and_unit` parses that
   table cell for **one number and one unit word**, and the string "UTF-16" carries a digit, so
   naming the measured unit there turns the row unparseable and the test red. Found by doing it.
   The precise unit lives in `harness.md` §"Injection budgets" instead. The honest fix — rename the
   enum and teach the parser a unit containing a digit — is small, is a code change rather than a
   documentation one, and was deliberately not made inside a checkpoint milestone.
6. **FIXED 2026-09-16 — a load-dependent intermittent, fixed in the product rather than the test.**
   `main.run` now installs the `SIGTERM`/`SIGINT` handlers **before** the bind, so a socket file's
   existence implies a process that will clean it up on those signals; any death it does not handle
   still leaves one, which is what start-if-absent's vet-and-unlink exists for. Pinned
   deterministically by a test **verified failing against the old ordering** before being trusted.
   **The live consequence, which is what keeps this item here at all**: timing nondeterminism moves
   the **coverage number itself** — three consecutive `./check.sh` runs over a tree whose only diffs
   were comments measured **97.64%, 96.85%, 97.64%**, all passing. `fail_under` is **95%** against a
   measured 96.85–98.07% spread, so **the margin absorbing that flap is under two points**, and
   **pinning this race does not license raising the floor**, because nothing attributes the flap to
   it — no cross-run per-file diff was ever taken. **What is still not fixed**: the process-level
   window from `exec` to handler installation, where `SIGTERM` is fatal by default. Full entry,
   including the second instance measured 2026-08-18 and its two wrong diagnoses:
   `FINDINGS-archive.md` §"Closed priority items and the Amazon Q source traces".

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

**The self-review loop has a single point of failure, and it was observed failing.** During M17
the reviewer became unavailable: four consecutive spawns died on server-side 500s, including a
deliberate probe that read no files and wrote two lines, which rules out prompt size and points at
the model. `py-runner` (haiku) was working normally throughout, so this was not the harness. Two
things follow. **The loop stops entirely when one model is down** — memory-reviewer is the only
independent critic in the crew, so there is no degraded mode, only a halt; the fallback is to wait,
to land at the last completed round and resume later from the review file, or to self-verify and
*say so in the review file*, which is much weaker evidence and must never be recorded as a review.
**And the file-based protocol earned its keep**: every failure wrote nothing, so the trail ends
cleanly at the last completed round with no partial round to reconcile. A reviewer that streamed
findings back conversationally would have left half a review and no way to tell which half.

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
   falls below 32% — a figure from before 2026-09-20, when both read paths began asking for a fetch
   before a result is used, so it has to be re-read after that date before it serves as a
   threshold. **The push-path baseline §"The gist was being read as the finding" owes is a
   different quantity — surfaced uuids, not searches — and cannot stand in for it.** And the burst
   structure flattening toward one search per proposal.
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
   of one written lesson and comfortably below a merged record. *The superseded original — "the real
   length distribution of memories is unknown" — is in `FINDINGS-archive.md` §"Open questions that
   closed".*
4. **CLOSED — hook→service transport.** Resolved 2026-08-01 by M0 spike 3: RPC latency, `busy_timeout`
   under two real writers, start-if-absent under a race, and the connect-as-server-exits recovery all
   measured (`research/spike-results.md` §"Spike 3"). What remained was integration-test material for
   M9 rather than a design question. **One live residue**: hook stdout arrives *early*, before the user
   message, which contradicts `~/Memory`'s "place surfaced memories late" lesson and we cannot choose;
   and the harness's own framing instructs the model to follow requests found in injected text,
   against `retrieval.md`'s untrusted-reference preamble. Full entry: `FINDINGS-archive.md`
   §"Open questions that closed".
10. **CLOSED — consolidation-lease takeover.** Caller specified, both premises measured 2026-08-02
   (`research/kiro-mcp-lifecycle-probe.md`): kiro runs one MCP server per agent instance, and the
   handshake is eager, which is why the bridge calls `plan_groups` lazily before the first forwarded
   `next_group`. **One narrow item stays open**: whether kiro ever restarts a client mid-subagent for
   its own reasons, which would supply a fresh takeover guard with no human invocation behind it —
   three instances showed no such restart, and nothing depends on it being false, since a spurious
   takeover costs one worker's in-flight reasoning and never a journal row. Full entry:
   `FINDINGS-archive.md` §"Open questions that closed".
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
11. **CLOSED — nothing bounds a gist's length in bytes.** Closed in M14 by a **character** bound
   rather than the byte bound the question proposed — `GIST_MAX_CHARACTERS = 1024`, counted in
   **UTF-16 code units**, which bounds bytes for both harnesses at once. M16 then *measured* the unit
   itself by astral bisection, refuting both the byte and code-point readings. The diagnosis was
   right and only the unit was wrong. Full entry, including the original text and the invented
   four-bytes-per-token factor that an earlier test used to assert the opposite: `FINDINGS-archive.md`
   §"Open questions that closed". The live arithmetic is in the priority items above.
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
9. **Evaluation** (deferred by D14). **Researched 2026-09-14, three briefs; the plan is
   `design/evaluation.md` (proposal, not yet normative).** Notes:
   `research/memory-benchmark-landscape.md`, `research/coding-agent-experience-benchmarks.md`,
   `research/agentic-eval-methodology.md`.
   **The list below was 8-for-10 and two names are now withdrawn.** Verified real: LoCoMo
   (arXiv:2402.17753), LongMemEval (2410.10813), BEAM (2510.27246), HaluMem (2511.03506),
   PersonaMem, LifeBench (2603.03781), EvoMemBench (2605.18421), MemoryAgentBench (2507.05257).
   **`LongMemCode` and `AFTER` could not be found under those names** and are treated as
   confabulated; `LongMemEval-V2` is unconfirmed as a distinct benchmark. Two confabulated names
   sat in an always-loaded file for six weeks — the cost of carrying an unverified brainstorm list
   without the word "unverified" attached to each item rather than to the set.
   **No surveyed benchmark scores an end-task coding outcome**, which corroborates D14 rather than
   offering a way around it.
   **Four findings that change the shape of the work.** (a) **LoCoMo cannot score abstention** —
   its official grading excludes the 446-question adversarial category (22.5% of the set) and its
   prompt instructs models against answering "not specified"; since Zikaron's empty retrieval must
   not score as failure, the harness is unusable for us independent of domain. (b) **Every
   published comparison in this space is vendor self-report**, and the numbers have not settled:
   Zep's claimed 84% on LoCoMo was corrected to **58.44%** after Mem0 disputed the denominator.
   Never quote one without that provenance. (c) **CTIM-Rover (2505.23422) is a published negative
   result for approximately this system** — repo-scoped episodic memory on AutoCodeRover dropped
   SWE-bench Verified resolution **42% → 31%** on 45 issues. The stored material was episodic
   traces of past repairs, i.e. **code-structure knowledge, which D1 excludes**, so it reads as
   evidence *for* the scope line and makes "replicate it, then test whether D1 flips its sign" the
   sharpest experiment available. (d) **Power and construct sensitivity are in opposition.**
   django/django is **231 of SWE-bench Verified's 500 instances**, the only repo with a long enough
   within-repo sequence for a ~10 pp paired binary detection — and the most pretrained-on repo in
   the set, where an external store of its conventions is least likely to add anything.
   Contamination *suppressing* a memory effect has **no published treatment at all**.
   **Unverified inference of mine, recorded as such:** AgentKB's +4.0 pp (24.3→28.3) sits inside the
   2.2–6.0 pp single-run spread measured for agent scaffolds, so the cleanest on-topic positive may
   not be distinguishable from noise. Neither paper makes this claim; check whether AgentKB
   averaged seeds before repeating it.
   Original text, superseded: *"Grok named LoCoMo, LongMemEval(-V2), BEAM, HaluMem, LongMemCode,
   PersonaMem, LifeBench, AFTER, EvoMemBench; several may be misremembered, and all are
   conversational or codebase-QA proxies rather than tribal-knowledge tests."*
   The benchmark set is the seed but its residual
   threats are the work: 187 synthetic memories is 1–2 orders below real scale, relevance labels were
   authored by the same agent that wrote the corpus, and query-set independence is attested rather than
   mechanically provable. Real memories from a real repository with independent annotators is the fix.
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
13. **RESOLVED and shipped 2026-08-16 — two write-policy scope rules disagreed.** *Could you learn it
   by reading the code?* admitted a general-but-hard-won fact; *not worth recording: facts about a
   language or tool in general* excluded it, and the highest-volume category sat in the conflict. The
   fix is that **a general fact enters as the decision it forced here**, never as an encyclopedia
   entry — evaluable by inspection, since "what did this fact make me do here?" is a question about
   the past. **Unmeasured, and named as such**: whether it changes what agents actually write; the M16
   write corpus is n=4. Rejected on the way: recasting the test as "will this bite someone again
   here?", a *prediction*, which is the shape the 2026-08-14 occasions change already replaced once.
   Full entry: `FINDINGS-archive.md` §"Open questions that closed".
15. **RESOLVED and shipped 2026-08-16 — records cross-referenced each other by gist prose.** The
   defect was never prose-instead-of-uuid; it was **quoting a mutable field verbatim as though it
   were an identifier**. The policy now says to point at a record **by its subject**, since a gist is
   rewritten whenever its record is corrected. A uuid was proposed and **refuted by the operator**:
   opaque to a human in a store meant to be auditable, unfindable semantically when it fails, and a
   hallucinated uuid is undetectable where a hallucinated description is obviously wrong. A
   subject-shaped reference also survives consolidation — the actor most likely to rewrite a gist —
   by construction. Full entry: `FINDINGS-archive.md` §"Open questions that closed".
