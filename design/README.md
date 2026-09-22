# design/

Design documents authored by **memory-researcher**. `FINDINGS.md` is the project's working memory and
indexes these rather than absorbing them.

**Read `overview.md` first** — it is the entry point: what Zikaron is, the system in one page, and the full
decision table with rationale. Everything else is a detailed spec it references.
*(No range is written here or in the row below. Both said `D1–D32` — stale by four decisions — while
`CLAUDE.md` and `FINDINGS.md` said `D1–D33`, stale by three. Nobody edits the sentence whose only job
is to track a count.)*

| Document | Covers |
|---|---|
| `overview.md` | **Start here.** Framing, scope line, non-goals, system shape, provenance, the decision table with rationale, and an index of these specs |
| `schema.md` | v0 SQLite tables, the store-coupled `meta` values, the config-key reference, indexes, the retrieval-eligibility predicate and the per-consumer filter table, the complete `meta` initialization and validation contract including the directed cosine primitive and the supported schema version, bounds, 20 invariants (21 withdrawn), per-kind event shapes, linked sessions, the six signals as queries, what is deliberately absent, migration posture |
| `architecture.md` | the components, RPC choice and rejected alternatives, request envelope in its resolved and bootstrap forms, the two-rung session-label ladder and the derived `label_source`, `health()` as the one unlabelled primitive, subagent-session push suppression, paths and store identity, filesystem security, start-if-absent, idle self-stop, the classified degraded chain, both tool surfaces, the consolidation state machine and serving loop, the two validation-precedence ladders and the error table, distribution artefacts — the two hook formats, the consolidator's model field, and the install contract |
| `retrieval.md` | the read path: push vs pull, eligibility and total order, fusion depth versus output budget, dense ranking algorithm, query construction on both arms for external and internal queries, hybrid fusion and its known defect, embedding and prefix, no reranker, the identifier weakness, supersession demotion and the precedence repair, push output format |
| `indexing.md` | chunking contract: token-exact preflight, boundaries, gist-prepending, `max` rollup, storage, and the implementation constraints — one transaction per mutation of indexed prose among them |
| `consolidation.md` | grouping mechanism and its cohesion rule, rejected alternatives, candidate construction, the provisional parameter seeds and what they are not, consolidator identity and model, never-lose guard |
| `write-policy.md` | the `agentSpawn` prompt text, its rationale, the secrets and poisoning boundary, the operator erasure procedure and its limits, the six instrumented signals, known gaps |
| `knowledge-index.md` | **The institutional-knowledge half** (D1 as amended). One SQLite file per corpus plus the registry in `memory.db`, discovery and filtering, chunking, both index arms, grouped cross-KB search and its bounds, the detached indexer, the seven MCP tools and the CLI, K1–K13 and its invariants |
| `harness.md` | the two supported harnesses as one table (D34): detection, session identity, triggers and output channels, injection budgets, subagent rules, D32's split, consolidation ownership, the consolidator's model, and the installer's two targets — the value/shape split and what each flag refuses |
| `distribution.md` | supported platforms (D35) and what rules each out, acquisition (D36) and why `uv` is install-time only, the version scheme and its artefact-shape rule, what CI asserts and the residual it cannot close |
| `prior-art.md` | `~/Memory` as built, the four divergences and how each resolved, lessons carried across, what was not ported |
| `build-plan.md` | **Per-milestone briefs**: scope, the normative sections each is built against, the invariants it must cover, its done-when list, and an explicit scope fence |
| `coding-standards.md` | **Binding.** Structure, the domain model, typing, the five test tiers, invariant tests, comment rules, dependency rules, bulk-edit rules, the check gate |
| `evaluation.md` | **Proposal, not normative.** The product claim decomposed into six links, three arms with the cheap one first, why resolve rate is probably the wrong dependent variable, what the benchmark literature returned, and the sample-size arithmetic |

Evidence lives elsewhere: measured results in `research/`, review rounds in `reviews/`, re-runnable
harnesses in `experiments/`. This corpus has been through sixteen independent review rounds —
`reviews/design-corpus-review.md`, where `grep -c '^## Round'` is the count that cannot go stale.
