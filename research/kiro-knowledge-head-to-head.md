# Our retrieval against kiro's `knowledge`, on the queries agents actually send

**Run 2026-09-20.** The first measurement in this project that compares our retrieval stack against
a shipped competitor on identical corpus and identical queries. It exists because a day spent
trying to improve our retrieval produced nothing, which raised a question nobody had asked: **does
the stack beat a simple one at all?**

## Why this comparison and not a source reading

`research/amazon-q-knowledge-engine.md` and `-integration.md` trace the open predecessor,
`aws/amazon-q-developer-cli`. Per the operator, that codebase was built under a dramatic reduction
in force, largely by two new graduates, and the product was then deprecated in favour of kiro —
**operator-supplied and unverified here, but it fits the evidence**: the retrieval internals carry
defects no review would pass, while the surrounding platform choices (default-off with the tool
spec *removed from the schema*, a SHA256 model allowlist pinning `tokenizer.json`) show judgement
from somewhere else.

kiro itself is closed source and its documentation says little about implementation. So behaviour
was measured instead of read.

## Method

- **Corpus**: `cockroachdb/cockroach` `docs/RFCS` at commit `13cb3eb2`, the same tree both systems
  indexed. Ours: 188 markdown files → 2,720 chunks. kiro reports `Items: 248`, which matches the
  *file* count of the whole directory including non-markdown — so kiro carried more distractors.
- **Agent**: `kiro-cli 2.21.4`, a purpose-built agent on `claude-sonnet-5` with tools
  `knowledge, read, grep, glob`, instructed to search the knowledge base before reading anything.
  Definition preserved at `~/zk-kiro-probe/.kiro/agents/rfc-probe.json`.
- **Queries**: **53 queries that real agents actually issued**, extracted from the M26 trial
  transcripts' `tool_use` blocks — not questions, and not anything this project invented. See §"The
  variable that dominated everything".
- **Truth**: RFC citations from the trial's answers, every one mechanically validated (file exists,
  line range within the file): **57/57 valid, 0 invalid**. Reported against two gold sets — all
  citations, and control-arm-only citations, which came from grepping raw files and therefore
  favour neither index.
- **Comparison is file-level**, because kiro returns no line ranges. That is the finest common
  denominator, and it **understates** our result rather than flattering it.

## Result

| gold source | kiro `knowledge` | ours |
|---|---|---|
| all citations (n=53) | 31/53 = **0.585** | 38/53 = **0.717** |
| control-only, grep-derived (n=51) | 16/51 = **0.314** | 27/51 = **0.529** |

**Same direction under both, margin 13–21 points.** The bias ran opposite to the expected
direction: the chunking-independent gold *widens* our advantage rather than narrowing it.

**Not a cutoff artifact.** kiro returned a mean of 3.9 results against our 5, but our score is
**identical at top-3 and top-5** (38/53 either way), so the difference is not extra slots.

**The asymmetry is lopsided**: kiro missed 9 queries we found; we missed 2 it found.

### Where it wins, and why that is the expected place

kiro's misses cluster in two families:

- **All five deadlock queries.** It never surfaces `20171024_select_for_update.md`, the file
  carrying *"detect deadlocks by identifying cycles in a waits-for graph"*. Notably a query
  containing that phrase almost verbatim — `waits-for graph deadlock cycle detection` — returned
  `cluster_locks`, `transactional_schema_changes` and `mvcc_bulk_ops` instead.
- **Five of the multi-Raft queries.**

These are the cases where one arm alone is confidently wrong and fusion rescues it, which is what a
hybrid is for and what M25 independently measured (shipped beats lexical-only by **+0.0764**, CI
excluding zero).

### A second advantage that needs no score

**kiro's results carry no line ranges.** Asked a real question, its agent cited
`20160210_range_leases.md:3` and `20191108_closed_timestamps_v2.md:6:1-3` — chunk indices dressed
as line citations. Ours carry real ranges, which is the only reason the trial's citations were
mechanically checkable at all. A citation a reader can verify is worth more than one they cannot,
and this is the difference between 57/57 validated and nothing to validate.

## What this does not establish

- **One corpus**, of technical design prose, in English.
- **Gold is derived from agent citations** and is therefore incomplete: it rewards finding what
  someone already found, and cannot credit either system for surfacing better material nobody cited.
- **kiro's index mode (`Best` semantic vs `Fast` lexical) was not verified from disk.** The tool
  schema exposes no index-type parameter, `show` reports no type field, and the store directory is
  permission-gated. A behavioural discriminator was run and was **inconclusive**. Operator states
  `Best` is the default and this note proceeds on that.
- **kiro indexed ~60 more files** than we did, all non-markdown. That is a small unfairness in our
  favour, unquantified.
- The kiro agent's own answers were **substantively good** — its response on timestamp-cache
  availability correctly identified the lease-exclusivity argument and the closed-timestamp floor.
  This measures **retrieval**, not the quality of an agent wrapped around it.

## The variable that dominated everything

**Real agents do not send the user's question. They send short keyword queries**, 4–8 words, no
question syntax, and they reformulate:

| the user asked | the agent searched |
|---|---|
| "How does the CockroachDB approach not deadlock? Surely retrying could…" | `deadlock detection transaction locking` |
| "Timestamp cache is critical in providing the guarantee that…" | `timestamp cache availability lease transfer low water mark` |
| "CockroachDB routes MVCC garbage collection through Raft rather than…" | `MVCC garbage collection through Raft consistency` |

Extracted from `tool_use` blocks in the trial transcripts: **55 distinct queries across 10
questions**, from 2 to 16 per question.

**This was the largest single variable in every measurement made this day** — larger than any
chunking or ranking difference — and every earlier oracle in this project got it wrong in a
different way. `research/m26-chunking-levers.md` §11 carries the accounting.

**And the reformulation is healthy, not a defect.** An earlier reading of these numbers here called
"many queries per question" a product problem. The agents' own verdicts refute it: q05's agent said
*"The first search was wasted effort… The second search actually landed the useful document"*, and
q06's concluded, correctly, *"That question predates the RFC process; it's a founding decision, not
something anyone wrote an RFC to justify."* A low per-query hit rate with successful convergence is
what working search looks like. The claim is withdrawn.
