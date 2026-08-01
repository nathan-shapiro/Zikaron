# Prior art — `~/Memory` (read-only sibling)

> `~/Memory` is a **working implementation** of Zikaron's D3–D7 two-tier design, built for a different
> purpose. Only its *memory* mechanisms are of interest here; whatever serves its own domain is simply out
> of frame for Zikaron and is not catalogued below. **Strictly read-only — never write there.**

## What is built there

- **SQLite**, two tables. The structure that transfers: `journal(id, tags, text, session_id, created_at,
  consolidated)` + `memory(id, tags, gist, content, active, superseded_by, revision, created_at,
  updated_at)`. Zikaron collapses these into one table with a `tier` column — see `design/schema.md` for why.
- **FTS5** over both tables (BM25) + **sqlite-vec `vec0`** embeddings, `bge-small-en-v1.5` 384-d local via
  fastembed/ONNX, loaded behind an `Embedder` protocol so the model is swappable in one line.
- **Ranking** = `RRF(BM25_rank, vec_KNN_rank, k=60)` × **power-law recency**, then dedup, with a
  cohesive-memory-over-raw-journal-line tiebreak. Auto-surface k≈3 every turn; deliberate `RECALL` k 3–5 in
  full. Query = last message + current scratchpad text.
- **Model protocol** rather than tools: `REMEMBER: [tags] <observation>` appends a journal row,
  `RECALL: <keywords>` triggers a second pass. **No ids or handles are ever exposed to the model** —
  keywords are soft tags and `/sleep` numbers memories transiently.
- **Soft-retire, never delete** (`active=0`); `superseded_by` for revisions; `revision` as a drift watch.
  Adopted as Zikaron's D16.
- **`/sleep` consolidation:** one LLM pass which reuses the session's system+history prefix byte-identically
  so the **prompt cache** still hits; emits `NEW` / `REVISE <n>`; journal rows marked `consolidated=1`
  **only if a block came back**, else nudge ×3, never silent loss; `sleep_batch=40` oldest-first.
- **`merge_reframes`:** a *second*, later pass that does use code-side clustering — single-linkage
  transitive-closure union-find over a cosine graph at an independently calibrated `0.75`, keeping the
  longest-content row as survivor.
- **`ltm-revision-revamp.md`:** online recurrence-triggered revision — per-memory `surface_count`,
  `last_surface_seq`, `cooldown_seq`, `surface_weight`; a **DB-global** turn ordinal; fires at N=3 surfaces
  within W=5 with cooldown 10; one ephemeral self-query returning **REVISE / FORGET / KEEP / RECEDE**;
  `recede_factor` 0.4 with `recede_floor` 0.2 as an amnesia guard; plus a reconciling `/sleep` with
  `RETIRE <n>`.

## Where Zikaron's stated design diverged from what was built — all four resolved

1. **Handles.** `~/Memory` exposes *no* ids to the model. Zikaron exposes uuids deliberately, because D12's
   pull step needs a handle to fetch content and to target amend/retire.
2. **Who may amend.** `~/Memory`'s journal is append-only, amended only at `/sleep`. Zikaron (D6, D11) lets
   the primary agent amend and retire on the hot path, because that *is* the staleness-repair mechanism.
3. **Clustering** → **D29.** `~/Memory`'s code-side clustering was **"simplified" away** for one model call
   (BRAINSTORM 2026-06-07): dropped for scope, apparently never benchmarked against the alternative. It is
   *not* discredited in-house either — `merge_reframes` later shipped exactly that technique and works.
   D29 rebuilds it on retrieval rather than raw cosine.
4. **Consolidator identity** → **D29.** A fresh subagent. Prompt-cache prefix reuse is unavailable to us by
   construction: the consolidator has its own system prompt and its own four-verb tool set, so there is no
   shared prefix with the parent session to hit.

## Lessons carried across, with the scar that produced each

From the `merge_reframes` review trail — each of these cost that project a review finding, so they are
requirements in `design/consolidation.md` rather than advice:

- **Name the processing order and the linkage rule.** Leaving them implicit was a MAJOR.
- **Test the transitive chain case** (A~B, B~C, A≁C) explicitly.
- **Survivor rule: keep longest, not newest.** Theirs began as keep-newest and was wrong against real data —
  the substantive row was 136 characters while the two follow-ups were 71 and 88, so keep-newest would have
  discarded precisely the row worth keeping.

Elsewhere:

- **`REMEMBER` under-triggered on first live run** — the model funnelled durable facts, even improvised
  self-details, into its scratchpad and never called the verb, forcing a per-turn `LTM_NUDGE` to be added.
  This is the evidence behind D30's deliberate bias toward recording.
- **Never mark work done unless output came back.** The `consolidated=1`-only-if-a-block-returned rule is
  carried into D29, where per-group tool calls make it structural rather than a text-parsing retry.
- **Keep surfaced memories ephemeral**, place them late in the context, and exclude them from the
  summarizer input. kiro's equivalents appear to be `compaction.excludeMessages` and
  `compaction.excludeContextWindowPercent` — untested. **Partly answered 2026-08-01, and not in our favour on
  the placement half:** `userPromptSubmit` stdout arrives as a context entry framed *"I have gathered this
  context from valuable programmatic script hooks"*, positioned **before** the user message in the same turn.
  So placement is fixed by the harness and it is early, not late — the ephemerality and summarizer-exclusion
  halves of the lesson are the ones still actionable. The framing is worth noting on its own: the wrapper
  instructs the model to follow requests found in the injected text, which is the opposite of what
  `retrieval.md`'s push format asserts in its own untrusted-reference-data preamble.
- **No query may assume `active=0 ⇒ superseded_by NOT NULL`.** That exact assumption was a review BLOCKER
  there; it is invariant 5 in `design/schema.md`.
- **Same-dimension embedding model swaps corrupt `vec0` silently.** Hence D20's per-vector model id and
  forced reindex.

## Deliberately not ported

Only mechanisms that were genuine candidates for Zikaron and were rejected for a reason:

- **The recurrence-triggered online revision machinery** (`surface_count`, `last_surface_seq`,
  `cooldown_seq`, `surface_weight`). It costs an extra ephemeral LLM call per firing, which D2 forbids on
  the hot path, and its trigger is *salience* rather than *wrongness* — a memory can recur constantly while
  remaining perfectly true. Zikaron's `event` log records surfaces, so this stays reconstructible if we ever
  want it.
- **Power-law recency as a ranking multiplier.** Right for a store of events, wrong for tribal knowledge:
  "the build needs Java 17" is exactly as true a year later. Age does not predict truth here. Recency
  survives only as a journal-local tiebreak.
