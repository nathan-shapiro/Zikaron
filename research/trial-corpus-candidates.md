# Trial corpus candidates for the design-doc retrieval experiment

**Gathered:** 2026-09-19, by memory-assistant, on request from memory-researcher.
**What this file is:** candidate GitHub repositories for an experiment comparing a searchable
index over a project's design documents against plain grep, when a coding agent answers
architectural questions. Superseding candidate: `cockroachdb/cockroach`, which **failed** because
the model already knows the codebase's file layout from pretraining (12/30 control runs went
straight to a precise subsystem path with no exploration; one run named a design-doc filename
before searching).

**The four criteria, restated:** (1) large — source tree too big to load into context, rough floor
~100 MB or many thousands of files; (2) **not widely known** — this is the criterion that matters
most, given what sank the CockroachDB attempt; (3) a real design-doc tree embedded in the repo (RFCs,
ADRs, `docs/design`, developer/internals docs carrying rationale and rejected alternatives — not API
reference or user manuals); (4) source in a mainstream, verifiable language (Go, Rust, C, C++, Java,
Python, TypeScript).

## Method

Search strategy: rather than starting from "famous systems in domain X" (which is exactly the
selection bias that produced the CockroachDB failure), searched by mechanical property —
`docs/rfcs`, `docs/design`, "improvement proposal" directory structures — across databases, storage,
graph databases, streaming systems, and one compiler/language project, then verified each candidate
against GitHub's REST API (`api.github.com/repos/<owner>/<repo>`) for `stargazers_count`, `size`
(KB, includes the whole repo not just source), `language`, and `created_at`, and fetched the actual
`docs/rfcs` or `docs/design` directory listing (and in two cases one representative document) to
check the design-tree claim rather than trust a README's description of itself.

**Caveats on the method, stated up front.** `size` from the GitHub API is the whole repository
(including vendored/generated content, git history overhead counted differently than tree bytes,
and non-source assets), not a clean source-tree byte count — flagged per-candidate where it looks
inflated by vendoring. Star count and "how much has been written about it" are a proxy for what an
LLM's pretraining corpus likely emphasized, not a direct measurement of memorization — this is the
same class of uncertainty that produced the CockroachDB surprise, so treat lower-star candidates as
*more likely* to be safe, not as *proven* safe; a smoke test (does the agent's first action look
exploratory or does it name a precise path unprompted) is still worth running before committing to a
final pick, exactly as was done for CockroachDB.

Two directory checks were negative and are recorded so they are not re-tried: **NebulaGraph's**
`docs/rfcs/` (`vesoft-inc/nebula`) contains only `0000-template.md` at `HEAD` — an RFC numbered
`0001-ssl-transportation.md` exists at an old commit but is gone from the current tree, so despite
12.4k stars and real distributed-systems substance, it does not currently meet criterion 3.
**PolarDB-for-PostgreSQL's** in-repo docs are thin (a `README.postgres` and links out to a
separately-hosted docs site); its architecture material lives outside the repository, so it does not
meet "documentation embedded in the repository" as stated.

## Ranked candidates

### 1. GreptimeDB — `GreptimeTeam/greptimedb`

- **URL:** https://github.com/GreptimeTeam/greptimedb
- **Language:** Rust. **Age:** created 2022-04-11 (about 3.5 years old).
- **Size:** repo size 116 MB (API `size` field, KB→MB); 6,151+ commits. Well over the 100 MB floor.
- **Stars:** 6,683 (verified via API). Forks: 545.
- **Coverage:** an "Observability 2.0" database positioned as a Prometheus/Loki/Elasticsearch
  replacement; has real adoption and some conference/blog presence in the observability space, but
  no evidence of deep technical write-ups or tutorials at the density CockroachDB has. Read as
  **less-famous rather than obscure** — a working engineer in the observability space has probably
  heard of it; one outside it likely has not.
- **Design-doc tree:** `docs/rfcs/` — confirmed by direct directory fetch, **27 dated Markdown RFCs**
  from 2023-01 through 2026-09, plus 4 RFC subdirectories with supporting material. Titles include
  *"2023-03-08-region-fault-tolerance.md"*, *"2023-05-09-distributed-planner.md"*,
  *"2023-08-13-metadata-txn.md"*, *"2024-01-17-dataflow-framework.md"*,
  *"2025-08-16-async-index-build.md"*. **Content verified**, not assumed: fetched
  `2023-03-08-region-fault-tolerance.md` directly — it has a dedicated "Alternatives" section
  explicitly rejecting a "Neon Way" WAL-shipping approach and a "direct replication" approach with
  stated reasons, and argues for active-vs-passive failure detection from first principles. This is
  exactly the rationale-carrying material the experiment needs, not reference documentation.
- **Read:** genuinely the strongest match on criteria 2+3 jointly — enough real engineering
  substance to have accumulated 27 RFCs over 3.5 years, not enough public profile to be a household
  name outside its niche.

### 2. YDB — `ydb-platform/ydb`

- **URL:** https://github.com/ydb-platform/ydb
- **Language:** C++. **Age:** created 2022-02-07 (open-sourced by Yandex/YDB Platform).
- **Size:** repo size **2,636,878 KB ≈ 2.6 GB** — the largest candidate by a wide margin. Caveat:
  this figure almost certainly includes vendored third-party dependencies bundled in-tree (a known
  property of large C++ monorepos of this vintage), so the genuine "YDB's own source" fraction is
  smaller than 2.6 GB; not independently measured here. Even discounted heavily this clears the
  100 MB floor with room to spare.
- **Stars:** 4,775 (API-verified). Forks: 820.
- **Coverage:** built by Yandex (Russian search/cloud company); documentation and community presence
  skew Russian-language, with an English site (`ydb.tech`) that is comparatively thin on
  blog/conference coverage in English-language venues. Plausibly the **most genuinely obscure to an
  English-pretrained model** of the size-qualified candidates, precisely because its primary
  audience and discussion have historically been outside the English web.
  Newer to open source (2022) reinforces this.
- **Design-doc tree:** **not yet confirmed in-repo.** A directory fetch of the main repo's file
  listing turned up no obvious `docs/design` or `rfcs` folder in the top-level tree shown, and a
  separate `ydb-platform/ydb-docs` companion repo (404'd on the specific path tried) was not
  reachable in this pass. **This is the open item**: YDB clears criteria 1, 2, and 4 with room to
  spare, but criterion 3 needs a direct follow-up search of the actual repo tree (or the docs repo)
  before it can be recommended with confidence. Flagged as a near-miss/TBD rather than dropped,
  given how strong it is on the criterion that matters most.

### 3. CubeFS — `cubefs/cubefs`

- **URL:** https://github.com/cubefs/cubefs
- **Language:** Go. **Age:** created 2019-02-19 (CNCF-hosted since 2019, graduated Dec 2024).
- **Size:** repo size 176.8 MB. Comfortably over the floor.
- **Stars:** 5,660 (API-verified). Forks: 714.
- **Coverage:** CNCF-graduated, which raises its profile somewhat within the cloud-native/storage
  community (graduation itself is a mild negative signal for obscurity — it means a CNCF TOC vetted
  and publicized it), but it has nothing like CockroachDB's or even TiKV's general-audience
  footprint. Mostly discussed in Chinese-language venues (originated at JD.com); English coverage is
  thin. Read as **moderately obscure** — a real risk that CNCF-graduate status has put it on more
  training-data radars than the star count alone suggests, worth a smoke test before committing.
- **Design-doc tree:** `docs/source/design/` — confirmed, **9 documents**, one per major subsystem:
  `master.md`, `metanode.md`, `datanode.md`, `objectnode.md`, `blobstore.md`, `client.md`,
  `kernelclient.md`, `authnode.md`, `lcnode.md`. Content check on `master.md`: roughly 70% design
  rationale/trade-offs (e.g., why a utilization-based placement strategy was chosen and what
  overheads it avoids) and 30% reference-style specifics (exact step sizes, thresholds) — a mixed
  but real design document, weaker on "rejected alternatives" than GreptimeDB's RFCs but still
  substantively about *why*, not just *what*.

### 4. Curve — `opencurve/curve`

- **URL:** https://github.com/opencurve/curve
- **Language:** C++. **Age:** created 2020-07-01. CNCF sandbox project (NetEase-originated).
- **Size:** repo size 103 MB — right at the stated floor, the thinnest margin of any candidate that
  clears it.
- **Stars:** 2,389 (API-verified). Forks: 522.
- **Coverage:** CNCF sandbox (lower profile than CubeFS's graduated status), primarily Chinese-origin
  (NetEase) with a maintained English doc set. Genuinely obscure outside a narrow
  distributed-block-storage niche — no evidence of blog/conference presence found.
- **Design-doc tree:** `docs/en/` (mirrored from `docs/cn/`) — confirmed, **10 English documents**:
  `mds_en.md`, `chunkserver_design_en.md`, `client_en.md`, `snapshotcloneserver_en.md`, `nebd_en.md`,
  plus build/quality/monitoring/k8s-CSI docs. Content check on `mds_en.md`: substantively
  design-rationale material — explains a CopySet mechanism's three separate motivations (metadata
  footprint reduction, operational granularity, correlated-failure reliability) and discusses
  failure-domain isolation as a deliberate choice, not just describing the resulting API.
- **Caveat:** its 103 MB size is the least comfortable margin above the floor of any recommended
  candidate — worth confirming against an actual file count/byte count of the source tree (excluding
  `docs/`, `.git`, and build artifacts) before relying on "too big to load into context" holding in
  practice.

## Near-misses and notable failures (recorded so they are not re-investigated)

- **NebulaGraph** (`vesoft-inc/nebula`) — 12,396 stars, 123 MB, C++, created 2018. **Fails criterion
  3 as currently maintained**: its `docs/rfcs/` directory contains only a template at `HEAD`; a real
  RFC (`0001-ssl-transportation.md`) exists only in old history. Also borderline on criterion 2 at
  12.4k stars in a well-covered field (graph databases).
- **openGauss** (`opengauss-mirror/openGauss-server`) — 788 stars, 351 MB, C++, created 2020.
  Excellent on criteria 1 and 2 (very obscure outside China, huge Huawei-descended PostgreSQL fork),
  but **fails criterion 3 as checked**: its documentation lives in a separate `opengauss-mirror/docs`
  repository rather than embedded in the source repo, and what's public reads as system-overview/
  reference material (e.g. "System Architecture" pages) rather than RFC-style rationale with
  rejected alternatives. Worth a second look if the "embedded in the repository" requirement can
  flex to "documentation the project itself maintains, in a sibling repo."
- **TDengine** (`taosdata/TDengine`) — 25,127 stars, 1.28 GB, C, created 2019. **Fails criterion 2
  outright**: 25k stars and years of aggressive project marketing/comparison blog posts make this
  one of the more widely-covered time-series databases; included only as a size/language data point
  and explicitly not recommended.
- **RisingWave** (`risingwavelabs/risingwave`) — 9,333 stars, 237 MB, Rust, created 2022. Strong on
  size and has an in-repo `docs/` design-doc set, but at 9.3k stars and heavy VC-funded marketing
  presence in the streaming-database space, **borderline on criterion 2** — a near-miss rather than
  a recommendation.
- **Databend** (`databendlabs/databend`) — ~9.2k stars, Rust. Has `docs/rfcs`-style material but
  fails criterion 2 for the same reason as RisingWave (Snowflake-alternative marketing has produced
  real coverage); not further pursued.
- **Neon** (`neondatabase/neon`) — Rust/C, `docs/rfcs/` confirmed real and substantial (numbered RFCs
  e.g. `018-storage-messaging-2.md`), but Neon's profile has risen sharply since the Databricks
  acquisition announcement — **fails criterion 2** at this point; a strong candidate a year or two
  ago, not now.
- **PolarDB-for-PostgreSQL** (`alibaba/PolarDB-for-PostgreSQL`) — 3,203 stars, 839 MB (mostly
  inherited PostgreSQL bulk), C, created 2021. **Fails criterion 3**: no substantial in-repo design
  doc tree found; its architecture docs are hosted externally on a GitHub Pages site rather than
  embedded in the repository as prose files.
- **Apache Kvrocks** (`apache/kvrocks`) — 4,434 stars but only 13.8 MB repo size — **fails criterion
  1** outright, far too small.
- **Vald** (`vdaas/vald`) — 1,728 stars (good obscurity), but 94.9 MB repo size sits just under the
  100 MB floor — **borderline fails criterion 1**; did not check its design-doc tree given the size
  shortfall.
- **Carbon Language** (`carbon-language/carbon-lang`) — C++, 128 MB, extremely rich in-repo
  `docs/design/` material (this is close to the project's entire purpose). **Fails criterion 2
  badly**: 33,896 stars and Google's 2022 launch generated substantial press/HN/conference coverage;
  a model has very likely seen commentary about this repository's structure. Excluded despite being
  an otherwise near-perfect fit for criterion 3.
- **Apache IoTDB** (`apache/iotdb`) — 6,402 stars, 388 MB, Java, created 2018. Good on 1, 2, and 4,
  but **no in-repo RFC/design-doc directory was found** in this pass — its process (à la Kafka's
  KIPs) appears to live on a wiki/mailing list rather than in the repository. Not recommended without
  further checking; flagged as a possible re-check if the wiki-hosted proposals turn out to be
  mirrored into the repo somewhere not surfaced here.

## Honest read on the "large AND obscure" combination

It is not rare in the sense of nonexistent, but it **is** in tension with the fact that a project
needs enough real engineering maturity to have accumulated substantial design documentation, and
maturity tends to correlate with adoption, which tends to correlate with the exact public-profile
signals (stars, blog coverage) that break obscurity. The cleanest fits found here — GreptimeDB,
CubeFS, Curve — are all young-ish (2019–2022), CNCF-adjacent or China-market-first projects that
have had time to write real RFCs/design docs but have not yet crossed into the western-blogosphere
attention CockroachDB, TiKV, ClickHouse, RisingWave, Neon, or Carbon all have. The failure mode
worth naming: several strong-looking candidates (NebulaGraph, PolarDB, openGauss) turned out on
direct inspection to keep their real design rationale either out of the repository entirely or only
in project history — the RFC/design-tree README claims that surface in search results are not
reliable without fetching the actual current directory, which is exactly what this pass did
differently from a name-recognition-driven search.

## Sources

1. [GreptimeTeam/greptimedb](https://github.com/GreptimeTeam/greptimedb) — repo, RFC directory, and
   `2023-03-08-region-fault-tolerance.md` fetched directly.
2. [GreptimeDB RFC: region-fault-tolerance](https://github.com/GreptimeTeam/greptimedb/blob/main/docs/rfcs/2023-03-08-region-fault-tolerance.md)
3. [ydb-platform/ydb](https://github.com/ydb-platform/ydb)
4. [cubefs/cubefs](https://github.com/cubefs/cubefs) and `docs/source/design/master.md`
5. [opencurve/curve](https://github.com/opencurve/curve) and `docs/en/mds_en.md`
6. [vesoft-inc/nebula](https://github.com/vesoft-inc/nebula) — `docs/rfcs/` (template-only at HEAD)
7. [opengauss-mirror/openGauss-server](https://github.com/opengauss-mirror/openGauss-server)
8. [taosdata/TDengine](https://github.com/taosdata/TDengine)
9. [risingwavelabs/risingwave](https://github.com/risingwavelabs/risingwave)
10. [databendlabs/databend](https://github.com/databendlabs/databend)
11. [neondatabase/neon](https://github.com/neondatabase/neon) — `docs/rfcs/018-storage-messaging-2.md`
12. [alibaba/PolarDB-for-PostgreSQL](https://github.com/alibaba/PolarDB-for-PostgreSQL)
13. [apache/kvrocks](https://github.com/apache/kvrocks)
14. [vdaas/vald](https://github.com/vdaas/vald)
15. [carbon-language/carbon-lang](https://github.com/carbon-language/carbon-lang)
16. [apache/iotdb](https://github.com/apache/iotdb)
17. GitHub REST API (`api.github.com/repos/<owner>/<repo>`) — used for all star/size/language/
    created-at figures quoted above.
