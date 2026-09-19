# Public repositories with substantial in-repo design/decision prose

## Brief

Find public GitHub repositories that keep substantial design/architecture/decision prose (ADR/RFC-shaped: a
decision, its rationale, rejected alternatives) **in the same repository as the code**, suitable as a corpus
to dogfood Zikaron's knowledge index against — index the design tree, then have a coding agent answer
"why is it built this way / what was rejected / what breaks if I change this" against real code in the same
repo. API-reference-shaped documentation is explicitly the wrong shape, since an agent can get that from the
code. Six specific recollections were to be verified or refuted, and a short list of separate-repo
alternatives (rust-lang/rfcs, python/peps, etc.) was wanted as a weaker fallback.

## Method

For each candidate: fetched the GitHub REST `contents` API for the candidate path (file counts, names),
fetched the repo metadata endpoint (language, size, license, last push, stars), and fetched raw file content
for one or two representative documents per repo to check document shape (section headings, presence of an
"Alternatives"/"Rationale" section) rather than trusting directory names alone. Queries used, roughly:
`api.github.com/repos/<owner>/<repo>/contents/<path>`, `api.github.com/repos/<owner>/<repo>`, and raw content
fetches of specific files. One general web search was used to locate rust-analyzer's historical
`architecture.md` once the live path 404'd, to confirm removal rather than a fetch-tool error.

All six of the operator's named candidates were checked directly rather than assumed.

## Verify-or-refute: the six named candidates

- **`cockroachdb/cockroach` — `docs/RFCS/` — CONFIRMED, but frozen.** 192 files, `.md`, named
  `YYYYMMDD_feature_description.md` from 2015-07-20 through 2023-01-18. The directory's own README states
  plainly: *"This review process is deprecated. Existing docs are left for archival purposes."* New design
  review has moved to an internal Atlassian wiki, so nothing has landed here since ~January 2023 and nothing
  will. Document shape is genuinely ADR/RFC: `20171220_encryption_at_rest.md` runs Summary → Motivation →
  Related resources → Out of scope → Security analysis → Guide-level explanation → Reference-level
  explanation → Drawbacks → **Rationale and Alternatives** → Future improvements, ~85 KB of prose in that one
  file alone including a discussion of single- vs two-level key structures and why each was or was not
  chosen.
- **`MaterializeInc/materialize` — `doc/developer/design/` — CONFIRMED, cooling but not dead.** 124 files
  (including `00000000_template.md`), same `YYYYMMDD_slug.md` convention, 2020-05-20 through at least
  2024-06-10 (`20240610_unified_compute_introspection.md`). No 2025/2026 entries found in the listing, so
  this reads as slowed rather than frozen — no README statement of deprecation the way Cockroach's has.
  Shape is explicitly ADR-like by house template: Summary, Jargon, Goals, Non-goals, API/design body,
  **Alternatives**, Open questions. `20220330_persist.md` (the persistence-layer redesign) runs ~57 KB and
  its Alternatives section names a specific rejected design ("store the state in Blob instead of Consensus")
  with the concrete tradeoff argued out.
- **`tikv/tikv` and `pingcap/tidb` — REFUTED for TiKV, CONFIRMED for TiDB, and they are not parallel.**
  `tikv/tikv`'s in-repo `doc/` holds only `deploy.md`, `http.md`, and `maintenance-guides/` — no
  `docs/design`, no `rfc/`. TiKV's RFCs live in a **separate** repository, `tikv/rfcs` (Apache-2.0, `text/`
  directory, ~40+ files up to `0119-enhance-slow-score-store-scheduler.md`) — so TiKV is a rust-lang/rfcs-
  shaped fallback candidate, not an in-repo one; it does not meet the brief's primary criterion.
  `pingcap/tidb`'s `docs/design/` is real and **still being added to**: 127 files, `YYYY-MM-DD-slug.md`,
  spanning 2018-07-01 through **2025-11-05** (`2025-11-05-active-active.md`), Apache-2.0 licensed, governed
  by a stated process ("substantial changes... put through a design process... consensus among the TiDB
  community") with a `TEMPLATE.md`. `2020-06-24-placement-rules-in-sql.md` runs ~95 KB: Introduction,
  Motivation or Background, Detailed Design, Implementation, Examples, Impacts & Risks, **Investigation &
  Alternatives** (naming CockroachDB and Yugabyte's approaches and why they were not copied), Unresolved
  Questions, Changelog.
- **`rust-lang/rust-analyzer` — `docs/dev/` — REFUTED, cleanly.** The path 404s today. The repo's root
  `docs/` now contains only `docs/book/`, which is the **user-facing mdBook** (`configuration.md`,
  `installation.md`, `other_editors.md`, `troubleshooting.md`, `vs_code.md`, plus a 48 KB
  auto-generated `configuration_generated.md`) — exactly the API-reference shape the brief rules out, not
  design rationale. A web search confirms `docs/dev/architecture.md` existed historically (findable at old
  commit hashes) but is absent from current `master`. No `ARCHITECTURE.md` at the repo root either. Repo is
  Apache-2.0/MIT dual-licensed, actively pushed to daily, but has **no current in-repo design-decision
  corpus** to index. Drop this candidate.
- **`etcd-io/etcd` — `Documentation/` — REFUTED as a decision corpus.** `Documentation/` holds
  `contributor-guide/` (18 files — `branch_management.md`, `release.md`, `modules.md`,
  `triage_issues.md`, etc.: **process and workflow documentation**, not design rationale), `dev-guide/`
  (an `apispec/` subdirectory — API reference), and `etcd-internals/`, which on inspection contains only a
  `diagrams/` subdirectory — no prose files sit directly under it in the current tree. There is no
  ADR/RFC-shaped decision corpus here now; what remains is contributor process docs and API reference, both
  the wrong shape for this brief.
- **`ceph/ceph` — `doc/dev/` — CONFIRMED, but mixed-shape and it's a heavy clone.** 101 items (94 files, 7
  subdirectories: `osd_internals/`, `mds_internals/`, `crimson/`, `dashboard/`, `developer_guide/`,
  `cephadm/`, `ceph-volume/`). Titles are a genuine mix: some are architecture/design prose
  (`bluestore.rst`, `crush-msr.rst`, `deduplication.rst`, `erasure-coded-pool.rst`, `peering.rst`,
  `pool-migration-design.rst`), and a large fraction is process/reference (`release-process.rst`,
  `testing.rst`, `perf_counters.rst`, `logging.rst`). Docs are **CC-BY-SA-3.0** (code is LGPL-2.1/2.1-or-
  later, mixed with several other licenses per `COPYING`) — usable, but not a clean single license and
  attribution-bearing. The repository itself is ~1 GB (979 MB reported size), C++, which is a real clone-
  tractability cost the brief specifically flags as a problem.

## Ranked recommendation

**Top recommendation: `pingcap/tidb`, `docs/design/`.**
- 127 files, Apache-2.0 (unambiguous, permissive, no license-shape caveat unlike Cockroach/Materialize),
  still actively added to through November 2025 (not frozen, not merely cooling).
- Confirmed ADR/RFC shape with a house template and an explicit "Investigation & Alternatives" section that
  names competitor designs and argues why they were rejected — exactly the "why built this way / what was
  rejected" content the brief wants, and not reconstructable from the code.
- Repository is Go, ~768 MB reported size — large but this project's own build already deals with a similar
  order of magnitude (Ceph, Cockroach); TiDB is smaller than either and does not require the special-purpose
  submodule/vendoring handling a C++ monorepo like Ceph does.
- Real risk: TiDB is a large, actively-changing codebase, so a comprehension question about "what breaks if
  I change this" is answerable but the surface area to choose a task from is large — a strength for realism,
  a cost for scoping the eval task.

**Strong second: `cockroachdb/cockroach`, `docs/RFCS/`.**
- Largest corpus by file count (192) and by measured per-document size (single files run tens of KB; total
  corpus is almost certainly several MB of prose), longest historical range (2015–2023), and the cleanest
  demonstrated ADR shape (Summary/Motivation/Rationale-and-Alternatives/Drawbacks is closer to a textbook RFC
  than TiDB's own template).
- Two real costs: the tree is **frozen** (nothing added since Jan 2023, so it cannot exercise "is this still
  relevant" staleness questions the way an actively-growing tree can), and the **repository's own license is
  not permissive** — root `LICENSE` is the proprietary "CockroachDB Software License" (a BSL-style license
  with usage restrictions), not Apache/MIT. That does not block reading and indexing the repo for internal
  research use, but it disqualifies redistributing a fork or corpus built from it, and is worth flagging
  explicitly since the brief asked about license.
- Repo size (~2.6 GB reported) is the largest of the group; a shallow/partial clone would be advisable.

**Third: `MaterializeInc/materialize`, `doc/developer/design/`.**
- 124 files, explicit house ADR template including an "Alternatives" section with real engineering tradeoffs
  argued out (the persist design doc is a good example). More recent than Cockroach's (last entry mid-2024
  vs. Cockroach's Jan-2023), Rust codebase, ~385 MB — the most tractable clone of the top three.
  Same license caveat as Cockroach: root `LICENSE` is Business Source License 1.1 (converts to Apache 2.0
  automatically four years after each release, not immediately), not currently OSI-permissive. Good
  secondary or comparison corpus; would not lead with it given the license caveat and its docs being one
  rung smaller than TiDB's/Cockroach's.

**Weaker, not recommended as primary: `ceph/ceph`.** Real ADR-shaped content exists but is diluted with
process/reference docs in the same directory (would need filtering, which cuts against measuring the raw
retrieval task), the license is a genuine multi-license mix rather than one clean grant, and the ~1 GB clone
is the heaviest of the group for no corresponding corpus-size advantage.

**Refuted, drop from consideration:**
- `rust-lang/rust-analyzer` — no in-repo design corpus exists today; `docs/dev/` is gone, `docs/book/` is
  user-facing reference.
- `etcd-io/etcd` — `Documentation/` is contributor-process and API-reference material; no ADR/RFC tree.
- `tikv/tikv` — no in-repo design docs; TiKV's RFCs are a **separate** repository (`tikv/rfcs`), making TiKV
  itself structurally identical to the rust-lang/rfcs pattern, not the in-repo pattern the brief wants.

## Separate-repo fallback list (weaker fit, per the brief's own framing)

Not independently re-verified in this pass beyond what was already surfaced incidentally:
- `rust-lang/rfcs` (named in the brief as the reference shape for this category).
- `tikv/rfcs` — Apache-2.0, ~40+ files under `text/`, same template-driven RFC process as TiKV's own
  contribution guidelines describe, confirmed to exist as a going concern (open PRs/issues visible) but not
  timestamp-verified for 2025/2026 activity in this pass.
- `python/peps`, `kubernetes/enhancements`, `reactjs/rfcs` — named in the brief, not independently checked
  here; listed only because the brief asked for them to be named as fallback options, not because this pass
  verified their current state. **Treat as unverified** until checked the same way the primary list was.

## Evidence quality and caveats

- File counts and directory listings came from the GitHub REST `contents` API via WebFetch, which is
  reliable for names/counts but does not return aggregate byte totals for a directory in one call; per-file
  sizes were sampled by fetching a small number of representative raw files per repo rather than summing
  every file, so the "total corpus size" figures in this note are **order-of-magnitude estimates from
  samples**, not an exact sum. If an exact total matters before committing to a corpus, it is cheap to get
  properly: `git clone --depth 1 --filter=blob:none --sparse` the target path and run `du`/`wc -c` directly,
  or walk the `git trees` API recursively and sum `size` fields — neither was done here because a sample
  was sufficient to answer "is there enough text" at the confidence this pass needed.
- Repo metadata (size, license, stars, last push) came from the `api.github.com/repos/<owner>/<repo>`
  endpoint, read via WebFetch summaries rather than raw JSON — treat exact byte/star counts as approximate
  to the nearest reported figure rather than exact to the digit, though license identifiers and directory
  existence/non-existence are binary facts and are trustworthy at face value.
- The Cockroach and Materialize license findings (proprietary / BSL, not currently permissive) came from
  fetching the repos' root `LICENSE` files directly — this is a fact worth double-checking before any
  decision that involves redistributing indexed content rather than reading it internally for research.
- The rust-analyzer refutation is corroborated two ways (live 404 on the API path, and a web search
  surfacing the historical file only at old commit hashes), which is stronger evidence than either check
  alone.

## Sources

1. [cockroachdb/cockroach — docs/RFCS](https://github.com/cockroachdb/cockroach/tree/master/docs/RFCS)
2. [cockroachdb/cockroach — 20171220_encryption_at_rest.md](https://raw.githubusercontent.com/cockroachdb/cockroach/master/docs/RFCS/20171220_encryption_at_rest.md)
3. [cockroachdb/cockroach — repo](https://github.com/cockroachdb/cockroach)
4. [cockroachdb/cockroach — LICENSE](https://raw.githubusercontent.com/cockroachdb/cockroach/master/LICENSE)
5. [MaterializeInc/materialize — doc/developer/design](https://github.com/MaterializeInc/materialize/tree/main/doc/developer/design)
6. [MaterializeInc/materialize — 20220330_persist.md](https://raw.githubusercontent.com/MaterializeInc/materialize/main/doc/developer/design/20220330_persist.md)
7. [MaterializeInc/materialize — repo](https://github.com/MaterializeInc/materialize)
8. [MaterializeInc/materialize — LICENSE](https://raw.githubusercontent.com/MaterializeInc/materialize/main/LICENSE)
9. [pingcap/tidb — docs/design](https://github.com/pingcap/tidb/tree/master/docs/design)
10. [pingcap/tidb — 2020-06-24-placement-rules-in-sql.md](https://raw.githubusercontent.com/pingcap/tidb/master/docs/design/2020-06-24-placement-rules-in-sql.md)
11. [pingcap/tidb — repo](https://github.com/pingcap/tidb)
12. [tikv/tikv — repo top level](https://github.com/tikv/tikv)
13. [tikv/rfcs](https://github.com/tikv/rfcs)
14. [tikv/rfcs — text/](https://github.com/tikv/rfcs/tree/master/text)
15. [rust-lang/rust-analyzer — repo top level](https://github.com/rust-lang/rust-analyzer)
16. [rust-lang/rust-analyzer — docs/book/src](https://github.com/rust-lang/rust-analyzer/tree/master/docs/book/src)
17. [rust-lang/rust-analyzer — historical architecture.md (old commit)](https://github.com/rust-lang/rust-analyzer/blob/d7c99931d05e3723d878bea5dc26766791fa4e69/docs/dev/architecture.md)
18. [etcd-io/etcd — Documentation](https://github.com/etcd-io/etcd/tree/main/Documentation)
19. [etcd-io/etcd — contributor-guide](https://github.com/etcd-io/etcd/tree/main/Documentation/contributor-guide)
20. [etcd-io/etcd — repo](https://github.com/etcd-io/etcd)
21. [ceph/ceph — doc/dev](https://github.com/ceph/ceph/tree/main/doc/dev)
22. [ceph/ceph — repo](https://github.com/ceph/ceph)
23. [ceph/ceph — COPYING](https://raw.githubusercontent.com/ceph/ceph/main/COPYING)
