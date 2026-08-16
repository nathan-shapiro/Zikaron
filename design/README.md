# design/

Design documents authored by **memory-researcher**. `FINDINGS.md` is the project's working memory and
indexes these rather than absorbing them.

**Read `overview.md` first** — it is the entry point: what Zikaron is, the system in one page, and the full
D1–D32 decision table with rationale. Everything else is a detailed spec it references.

| Document | Covers |
|---|---|
| `overview.md` | **Start here.** Framing, scope line, non-goals, system shape, provenance, the D1–D32 table with rationale, and an index of these specs |
| `schema.md` | v0 SQLite tables, the store-coupled `meta` values, the config-key reference, indexes, the retrieval-eligibility predicate and the per-consumer filter table, the complete `meta` initialization and validation contract including the directed cosine primitive and the supported schema version, bounds, 20 invariants (21 withdrawn), per-kind event shapes, linked sessions, the six signals as queries, what is deliberately absent, migration posture |
| `architecture.md` | four components, RPC choice and rejected alternatives, request envelope in its resolved and bootstrap forms, the two-rung session-label ladder and the derived `label_source`, `health()` as the one unlabelled primitive, subagent-session push suppression, paths and store identity, filesystem security, start-if-absent, idle self-stop, the classified degraded chain, both tool surfaces, the consolidation state machine and serving loop, the two validation-precedence ladders and the error table, distribution artefacts — the two hook formats, the consolidator's model field, and the install contract |
| `retrieval.md` | the read path: push vs pull, eligibility and total order, fusion depth versus output budget, dense ranking algorithm, query construction on both arms for external and internal queries, hybrid fusion and its known defect, embedding and prefix, no reranker, the identifier weakness, supersession demotion and the precedence repair, push output format |
| `indexing.md` | chunking contract: token-exact preflight, boundaries, gist-prepending, `max` rollup, storage, atomicity |
| `consolidation.md` | grouping mechanism and its cohesion rule, rejected alternatives, candidate construction, the provisional parameter seeds and what they are not, consolidator identity and model, never-lose guard |
| `write-policy.md` | the `agentSpawn` prompt text, its rationale, the secrets and poisoning boundary, the operator erasure procedure and its limits, the six instrumented signals, known gaps |
| `harness.md` | the two supported harnesses as one table (D34): detection, session identity, triggers and output channels, injection budgets, subagent rules, D32's split, consolidation ownership, the consolidator's model |
| `prior-art.md` | `~/Memory` as built, the four divergences and how each resolved, lessons carried across, what was not ported |

Evidence lives elsewhere: measured results in `research/`, review rounds in `reviews/`, re-runnable
harnesses in `experiments/`. This corpus has been through twelve independent review rounds —
`reviews/design-corpus-review.md`.
