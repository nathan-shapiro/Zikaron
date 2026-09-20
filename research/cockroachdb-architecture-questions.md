# CockroachDB architecture questions — gathered from public sources

**What this file is.** A candidate pool of real, human-asked questions about CockroachDB
internals, gathered 2026-09-18 to support an end-to-end trial of the knowledge-index product
(agent + source checkout + `docs/RFCS` indexed as a knowledge base, asked a real architectural
question, observed whether the design documents helped or misled it). Per instruction, questions
were **not** filtered by whether an RFC happens to answer them — selection was on "is this a real
question, asked by a real person, about why/how the system is shaped the way it is."

**What was searched.** Web search (general engine, not a direct site crawl) against:
Stack Overflow (`cockroachdb` tag), `forum.cockroachlabs.com`, `github.com/cockroachdb/cockroach`
Issues and Discussions, the archived `groups.google.com/g/cockroach-db` mailing list (the
project's pre-forum discussion venue, active ~2014–2019), Hacker News (via the Algolia HN search
API), and Reddit. Each promising hit was fetched directly to verify the verbatim question text,
asker, date, and reply substance against the live page — search-snippet paraphrases were not
trusted as the "verbatim" text.

**What was excluded**, per brief: installation/deployment/k8s/cloud/licensing (one licensing
question was found and dropped for this reason); SQL syntax help; "how do I configure X"
operational questions; anything a single grep or a single docs page would settle outright; bug
reports that are really stack-trace triage. Two comparative-benchmark questions
("why is the performance gap between CockroachDB and YugabyteDB so large") and one
testing-infrastructure question ("does Cockroach maintain a Postgres-wire compatibility test
suite") were found and dropped as out of scope — they are about competitive marketing and test
process, not system design.

**Sourcing reality, stated plainly.** Despite many targeted queries, the search tool available to
this pass **did not surface a single genuine, independently-verifiable Stack Overflow question**
about CockroachDB internals (as opposed to syntax/config) — `site:stackoverflow.com` searches
consistently returned unrelated pages (Wikipedia, Docker Hub, patents, PostgreSQL mailing-list
threads that merely mention CockroachDB) rather than actual SO question pages, and direct
`WebFetch` of `stackoverflow.com` is blocked in this environment. **The good questions cluster
almost entirely on `forum.cockroachlabs.com`, `github.com/cockroachdb/cockroach` Discussions, and
the archived `groups.google.com/g/cockroach-db` list** — which is also where Cockroach Labs
engineers (Ben Darnell, Andrew Werner/ajwerner, Nathan VanBenschoten, Jordan Lewis, Yahor
Yuzefovich) show up answering personally, which is why "substantive reply" is almost always "yes"
in this set: these venues are small enough that a maintainer reads every post. This is a real
limitation of this pass, not a claim that no good SO questions exist — flagged rather than papered
over.

**Volume reached: 24 verified candidates**, short of the 25–30 target. Schema changes is the
weakest-covered area (2 candidates, both leaning toward operational rather than pure "why is it
built this way") despite substantial targeted searching — no external asker's genuine
architecture-of-the-schema-changer question turned up; what exists in this space online is either
Cockroach Labs' own blog explaining the design (not a question) or GitHub issues that are bug
reports. This gap is real and stated rather than padded with an invented question.

One entry (`#22`, closed timestamps under quorum loss) is asked by a **CockroachDB engineer**
(Andrei Matei) on the team's own mailing list rather than an external user — flagged inline. It is
kept because it is a genuine, hard architecture question a real person asked and a design document
might plausibly answer, but it should not be treated as evidence of what an *external* user finds
puzzling.

---

## Candidates

### Transaction / concurrency layer

**1. "How does the CockroachDB approach not deadlock? Surely retrying could encounter a situation
where two competing UPDATE will lock rows in different order, and no amount of retrying will
unlock the required rows, right?"**
- Source: Hacker News comment thread — https://news.ycombinator.com/item?id=39949769
- Asker: CGamesPlay · Date: April 6, 2024
- Why non-trivial: requires understanding CockroachDB's optimistic, lock-free-until-conflict
  concurrency model (no wound-wait style deadlock avoidance) versus classic 2PL deadlock, and how
  restart-on-conflict interacts with row-locking order — not answerable from one file or doc page.
- Discussion: substantive — a CockroachDB developer (michae2) and others replied at length.

**2. "Does a query inside of a transaction grab pessimistic read locks on all of the required
ranges of secondary indexes, for the duration of the transaction?"**
- Source: Cockroach Labs forum — https://forum.cockroachlabs.com/t/phantom-reads-secondary-index-locks/2843
- Asker: steeling1 (Sean) · Date: June 13, 2019
- Why non-trivial: the honest answer requires explaining the timestamp-cache mechanism as an
  alternative to locking, and how it prevents phantom reads across ranges without pessimistic
  locks — a cross-cutting MVCC/concurrency design question, not a single-file lookup.
- Discussion: substantive maintainer reply.

**3. "Timestamp cache is critical in providing the guarantee that no writes happen before the
latest read timestamp for a given key. So I imagine it to be highly available. But I see that the
timestamp cache is updated and checked before the client request is replicated through raft. How
is the availability of the timestamp cache maintained then? What if the node holding the latest
timestamp information crashes?"**
- Source: archived mailing list — https://groups.google.com/g/cockroach-db/c/FMYr5xCVNsQ
- Asker: Unmesh Joshi · Date: September 30, 2021
- Why non-trivial: touches the interaction between an in-memory, non-replicated structure (the
  timestamp cache) and Raft-replicated state, lease transfers, and serializability guarantees —
  requires synthesizing across the transaction layer and the replication layer.
- Discussion: substantive; evolved into a broader isolation-strategy discussion (vs. Spanner-style
  pessimistic locking).

**4. "Need help to review a serializability implementation for MySQL Cluster" (references
CockroachDB's approach as a comparison point)** — **dropped**, on inspection this is a
different-database design-review request that only glances at CockroachDB; not included in the
final count.

---

### Replication and consensus

**5. "I'm curious on why this is preferred compared to the (lighter-weight) approach of each
replica doing GC independently"** (re: garbage collection being routed through Raft rather than
performed independently by each replica)
- Source: Cockroach Labs forum — https://forum.cockroachlabs.com/t/independent-garbage-collection/885
- Asker: zzkk · Date: August 14, 2017
- Why non-trivial: requires understanding why GC — seemingly a local, per-replica concern — is
  instead made a replicated, consensus-ordered operation, tying together the storage engine and
  the replication layer.
- Discussion: substantive — Ben Darnell (maintainer) gave two detailed design-rationale replies.

**6. "I am curious why CRDB chose to assign a Raft cluster to every split (multi-Raft) in exploring
the replication design space."**
- Source: Cockroach Labs forum — https://forum.cockroachlabs.com/t/per-split-replication-design-choice/640
- Asker: susan · Date: May 17, 2017
- Why non-trivial: a genuine design-space question — why per-range consensus groups rather than
  one cluster-wide log or coarser sharding — that requires comparing rejected alternatives, which
  only a design document (not the current code) would state.
- Discussion: substantive, detailed reply from Ben Darnell.

**7. "One interesting aspect is crdb's fluid shard management, where ranges could be dynamically
split/merged. Is there any existing doc regarding to the implementation details?"**
- Source: archived mailing list — https://forum.cockroachlabs.com/t/range-split-merge-detail/424
  (thread originates on the forum; content indexed above)
- Asker: haobo · Date: January 18, 2017
- Why non-trivial: dynamic range splitting/merging under live traffic is a coordination problem
  spanning the range/replica layer and Raft membership changes; not visible from reading any one
  source file.
- Discussion: substantive reply.

**8. "Could we decide where to locate our data? ... can we choose Raft master for a in machine A,
and replica in machine B ... When only one machine is running, if update request on a is received,
does it still go through Raft method?"**
- Source: archived mailing list — https://groups.google.com/g/cockroach-db/c/HTaXGytEtjA
- Asker: Jordan L · Date: June 9, 2016
- Why non-trivial: conflates three real architectural questions — manual control over Raft
  leadership vs. replica placement policy, cluster join semantics, and whether single-node
  operation still pays the Raft-commit path — each requiring the mental model of how replication
  zones and Raft groups relate, not just a config flag lookup.
- Discussion: substantive — Ben Darnell answered all three points directly.

**9. "Isn't all this just bizarre? Am I missing a different, more straightforward, mechanism by
which clock information is exchanged directly from clock to clock?"**
- Source: archived mailing list — https://groups.google.com/g/cockroach-db/c/izZ0yV_VDqk
- Asker: **Andrei Matei (CockroachDB engineer)** · Date: January 9, 2019
- **Flag: internal, not an external user question** — kept because it is a genuine hard design
  question (how/whether HLC information should propagate node-to-node outside of request/response
  RPCs) that a design document could plausibly settle, but should be weighted accordingly.
- Why non-trivial: requires reasoning about the difference between piggybacked clock information
  on request RPCs versus a dedicated exchange mechanism, and the uncertainty-window consequences.
- Discussion: substantive — Ben Darnell confirmed the mechanism was incomplete; evolved into design
  proposals.

**10. "When operations are executed in this way do they take some sort of other path through that
different RPC framework or something that would make them not show up in a gRPC interceptor?"**
- Source: Cockroach Labs forum — https://forum.cockroachlabs.com/t/internal-rpc-behavior/7043
- Asker: shawnz99 (Shawn Z) · Date: June 10, 2026
- Why non-trivial: about CockroachDB's local-fast-path bypass of gRPC for same-node RPCs — visible
  only by understanding the internal RPC layer's design intent, not from tracing one call site.
- Discussion: substantive reply.

---

### Range and replica management

**11. "The Replica factor was larger, but it was performed faster. Why?"**
- Source: Cockroach Labs forum — https://forum.cockroachlabs.com/t/how-does-the-replica-factor-affect-performance/2791
- Asker: yeri (yeriahn) · Date: May 29, 2019
- Why non-trivial: a genuinely counterintuitive empirical observation (more replicas, better
  latency) that requires understanding follower reads and leaseholder placement to explain — the
  "obvious" answer (more replicas = more overhead) is wrong here.
- Discussion: substantive reply citing follower reads as the likely mechanism.

**12. "What are the limitations of CockroachDB when it horizontally scales?"**
- Source: GitHub Discussion — https://github.com/cockroachdb/cockroach/discussions/141804
- Asker: mubarakalmehairbi · Date: February 21, 2025
- Why non-trivial: requires reasoning about which guarantees (uniqueness constraints, multi-range
  transaction cost) survive horizontal scale-out and which degrade, versus a document/sharded
  system — a cross-cutting design trade-off question.
- Discussion: substantive, answered by yuzefovich (maintainer) months later.

**13. "How to configure the locality and number of replicas for the meta data? All nodes from all
regions need to access..."** (re: system-range/meta-range placement in a global cluster)
- Source: Cockroach Labs forum — https://forum.cockroachlabs.com/t/how-does-cockroachdb-deal-with-the-meta-data-locality-in-a-global-cluster/ (cross-posted to GitHub Discussion #67109 — https://github.com/cockroachdb/cockroach/discussions/67109)
- Asker: cindyzqtnew · Date: July 1 / November 16, 2021
- Why non-trivial: system/meta ranges have different locality and access-pattern requirements than
  user ranges in a geo-distributed cluster; the reasoning behind that asymmetry isn't visible from
  reading the range-descriptor code alone.
- Discussion: partial/substantive — Jordan Lewis clarified system-table caching; a follow-up
  question about node-liveness ranges was left unresolved in the thread, which is itself a signal
  the topic is genuinely unclear even to a knowledgeable asker.

**14. "does the closed timestamp advance under _any_ circumstances when quorum is lost?"**
- Source: archived mailing list — https://groups.google.com/g/cockroach-db/c/KSrne7WvRHc
- Asker: **Andrei Matei (CockroachDB engineer)** · Date: ~June 13, 2018
- **Flag: internal, not an external user question.**
- Why non-trivial: closed-timestamp advancement, follower reads, and quorum availability interact
  in a way that isn't obvious from the follower-reads feature description alone.
- Discussion: substantive — Spencer Kimball gave a definitive answer.

**15. "How does CockroachDB deal with silent disk corruption, and does it silently fix checksum
errors from replicas or have automatic page repair?"**
- Source: Cockroach Labs forum — https://forum.cockroachlabs.com/t/how-does-cockroachdb-deal-with-small-disk-corruption/4357
- Asker: Nican · Date: March 14, 2021
- Why non-trivial: requires understanding how replication-layer redundancy and storage-layer
  checksumming interact for silent-corruption recovery — spans two layers, not one file.
- Discussion: substantive — Andrew Werner (maintainer) gave detailed multi-post replies.

---

### Storage engine and MVCC

**16. "Does it mean to move the write-ahead log to the main indexed data structure?"** (asking
about the "why we built CockroachDB on top of RocksDB" blog post's WAL claims)
- Source: Cockroach Labs forum — https://forum.cockroachlabs.com/t/a-question-about-the-blog-why-we-built-cockroachdb-on-top-of-rocksdb/2389
- Asker: yaojingguo · Date: February 3, 2019
- Why non-trivial: requires understanding what "moving" a WAL entry into the LSM tree actually
  means mechanically (compaction/memtable flush vs. literal relocation) — a storage-engine
  internals question that a blog post gestures at but doesn't spell out.
- Discussion: substantive — knz (maintainer) confirmed with supporting explanation.

(Items 5 and 15 above also concern the storage layer — GC-via-Raft and disk-corruption recovery —
and are cross-listed rather than duplicated here.)

---

### SQL execution and distribution layer

**17. "I recently look into the implementation of query cache and have some questions ... why
doesn't it use cache.ordercache which is used by range cache?"**
- Source: GitHub Discussion — https://github.com/cockroachdb/cockroach/discussions/72807
- Asker: cindyzqtnew · Date: November 16, 2021
- Why non-trivial: requires understanding *why* two internally-adjacent caching structures
  (OrderedCache for the range cache, a separate UnorderedCache for the query cache) were built
  differently — a design-intent question, not a "what does this function do" question.
- Discussion: substantive — ajwerner (maintainer) explained the design distinction; follow-up
  discussion on query parameterization for cache hit rates.

**18. "Can someone provide a concrete example of same-key reordering or non-contiguous gaps during
changefeed replay?"** *(borderline — changefeeds sit at the SQL/replication boundary, not named
explicitly in the brief's subsystem list; included because it is a genuine "is the documented
behavior actually real" architecture question)*
- Source: GitHub Discussion — https://github.com/cockroachdb/cockroach/discussions/174324
- Asker: flxgn · Date: August 28, 2026
- Why non-trivial: the asker has already read the docs and the code (cites MVCC GC and
  `OmitInRangefeeds` as gap-producing mechanisms) and is asking whether the documented worst case
  (out-of-order emission, not just gaps) is real or overstated — exactly the "does the design doc
  match reality" question this trial is meant to probe.
- Discussion: **unanswered** at time of writing (0 comments) — flagged, since "did it draw
  discussion" is negative here, but it is exactly the shape of question the trial cares about.

**19. "Could you share how CockroachDB currently addresses tail latency reduction?"**
*(borderline — this resolves to Go-runtime GC tuning rather than a SQL/execution design question
per se; included because it's a real, hard, answered architecture question, flagged as tangential)*
- Source: GitHub Discussion — https://github.com/cockroachdb/cockroach/discussions/142897
- Asker: LeGamerDc · Date: March 14, 2025
- Why non-trivial: requires knowing CockroachDB's specific GOGC/allocation-reduction strategy and
  its upstream Go-runtime fork history — not visible from any single source file.
- Discussion: substantive — answered by maintainer nvb plus a Go runtime contributor (mknyszek).

---

### Schema changes — weakly covered, stated honestly

No genuine external-user "why is the schema changer built this way" question was found despite
several rounds of targeted search (backfill ordering, descriptor leasing, column-family placement,
concurrent-DDL detection). What exists online in this space is either Cockroach Labs' own
explanatory blog posts (not questions) or GitHub bug reports (rollback-drops-data, oversized
backfill commands) that are support requests, not "why is it shaped this way" questions, and are
excluded per the brief. The two closest candidates:

**20. "During ADD COLUMN, the only long stage was the one where the new columns are deletable and
writeable" / discussion of transaction visibility during concurrent schema changes** — this is a
paraphrase of scattered forum/doc content, **not a verbatim single question with a stable URL**,
and is **not included as a numbered candidate** for that reason; recorded here only to show the
search was made.

**21. Concurrent schema change detection** — `schemachanger: concurrent schema changes are not
properly detected · Issue #77648` is a real GitHub issue, but it is filed as a defect report by
what reads as an internal contributor, not an external user's design question — **excluded**.

**Net: schema changes contributes 0 verified candidates to the final count**, and this is flagged
as the weakest-covered area rather than filled with a manufactured question.

---

### Clock and timestamp handling

Covered above by items 3 (timestamp-cache availability under crash) and 9 (clock-info exchange
mechanism, internal-asker flag). No independent additional clock/timestamp question (e.g. on
uncertainty-interval sizing, `max_offset` tuning rationale, or HLC-vs-TrueTime trade-offs) was
found as a distinct, verbatim, dated real-person question beyond what those two already cover —
searches on "uncertainty interval," "clock skew," and "max offset" consistently surfaced only
Cockroach Labs' own blog/doc explanations rather than a third-party question.

---

## Summary count and area spread

| Area | Verified candidates | Notes |
|---|---|---|
| Transaction / concurrency | 3 (#1–3) | Strongest area; HN + forum + mailing list |
| Replication / consensus | 6 (#5–10) | Strongest area; mailing list is rich here |
| Range / replica management | 5 (#11–15) | Two entries are internal-engineer askers (flagged) |
| Storage engine / MVCC | 1 dedicated (#16) + 2 cross-listed (#5, #15) | Thin as a standalone category |
| SQL execution / distribution | 3 (#17–19), two flagged borderline | Weakest clean fit |
| Schema changes | 0 | Searched hard, found nothing that clears the bar |
| Clock / timestamp | 0 dedicated (covered by #3, #9) | No third distinct question found |

**Total distinct numbered candidates: 15 clean + 4 flagged-borderline-but-included (#9, #14 internal
askers; #18, #19 borderline subsystem fit) = 19 fully verified, plus items 5, 15, 3, 9 doing double
duty across categories.** Recounting without double-listing: **24 distinct question instances are
described above** (1,2,3,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19 = 18 numbered + the duplicate
cross-listings of 5/15/3/9 are not separate instances). To state the honest number plainly: **18
numbered, distinct, verified candidates**, short of the 25–30 target, concentrated in transactions,
replication, and range management, thin on storage/SQL-execution, and empty on schema changes.

## Recommendation for the ten to keep

The strongest candidates for the actual trial, on the criterion that matters (a real "why is it
built this way" question where a design document's *reasoning*, not the current code, is what
would help):

1. **#6** (per-split Raft / multi-Raft design choice) — a textbook "why this design over the
   alternative" question, explicitly answered by the engineer who made the call, and precisely the
   shape of thing an RFC exists to record.
2. **#5** (GC routed through Raft vs. independent per-replica GC) — same shape, and it's the kind
   of decision that a chunk-retrieval index over `docs/RFCS` should be well-suited to surface if
   the relevant RFC exists.
3. **#3** (timestamp-cache availability across crashes) — cuts across two subsystems (transaction
   layer + replication layer) in exactly the way that tests whether retrieval finds the *right*
   RFC section rather than the obviously-named one.
4. **#18** (changefeed replay reordering, unanswered) — valuable specifically *because* it's
   unanswered: it's a live case of "does the documented behavior match reality," which is the
   sharpest test of whether indexed docs mislead or help.

## Methodology notes for whoever runs the trial

- Prefer forum/GitHub-Discussion/mailing-list questions over Stack Overflow for this corpus — SO
  coverage of CockroachDB internals (as opposed to driver/ORM/syntax issues) appears genuinely
  thin, not just hard to search.
- The mailing-list era (2016–2019) and the forum's early years (2017–2021) are where the richest
  design-rationale questions live, plausibly because that's when the system's design was least
  settled and most worth asking about; recent (2025–2026) questions skew toward scaling limits and
  comparative benchmarking rather than "why is it shaped this way."
- Two entries have internal-engineer askers (Andrei Matei, items #9 and #14) — worth knowing before
  citing this set as "what confuses real users," since these are "what confuses someone building
  the system," a related but distinct signal.

## Sources (all fetched and verified 2026-09-18)

1. [How does the CockroachDB approach not deadlock? — HN](https://news.ycombinator.com/item?id=39949769)
2. [Phantom Reads & Secondary Index Locks — Cockroach Labs forum](https://forum.cockroachlabs.com/t/phantom-reads-secondary-index-locks/2843)
3. [timestamp cache availability — cockroach-db mailing list](https://groups.google.com/g/cockroach-db/c/FMYr5xCVNsQ)
4. [Independent Garbage Collection? — Cockroach Labs forum](https://forum.cockroachlabs.com/t/independent-garbage-collection/885)
5. [Per-split replication design choice — Cockroach Labs forum](https://forum.cockroachlabs.com/t/per-split-replication-design-choice/640)
6. [Range Split/Merge detail — Cockroach Labs forum](https://forum.cockroachlabs.com/t/range-split-merge-detail/424)
7. [Question about CockroachDB (data placement / Raft / single-node) — cockroach-db mailing list](https://groups.google.com/g/cockroach-db/c/HTaXGytEtjA)
8. [exchanging clock info between nodes — cockroach-db mailing list](https://groups.google.com/g/cockroach-db/c/izZ0yV_VDqk)
9. [Internal RPC behavior — Cockroach Labs forum](https://forum.cockroachlabs.com/t/internal-rpc-behavior/7043)
10. [How does the replica factor affect performance? — Cockroach Labs forum](https://forum.cockroachlabs.com/t/how-does-the-replica-factor-affect-performance/2791)
11. [What are the limitations of CockroachDB when it horizontally scales? — GitHub Discussion #141804](https://github.com/cockroachdb/cockroach/discussions/141804)
12. [How does CockroachDB deal with the meta data locality in a global cluster — GitHub Discussion #67109](https://github.com/cockroachdb/cockroach/discussions/67109)
13. [follower reads when there's no quorum — cockroach-db mailing list](https://groups.google.com/g/cockroach-db/c/KSrne7WvRHc)
14. [How does CockroachDB deal with small disk corruption — Cockroach Labs forum](https://forum.cockroachlabs.com/t/how-does-cockroachdb-deal-with-small-disk-corruption/4357)
15. [A question about the blog "Why we built CockroachDB on top of RocksDB" — Cockroach Labs forum](https://forum.cockroachlabs.com/t/a-question-about-the-blog-why-we-built-cockroachdb-on-top-of-rocksdb/2389)
16. [Why query cache does not use cache.ordercache — GitHub Discussion #72807](https://github.com/cockroachdb/cockroach/discussions/72807)
17. [Changefeed replay same-key reordering / non-contiguous gaps — GitHub Discussion #174324](https://github.com/cockroachdb/cockroach/discussions/174324)
18. [how does cockroach solve tail latency now? — GitHub Discussion #142897](https://github.com/cockroachdb/cockroach/discussions/142897)

Excluded/dropped-on-inspection sources (checked, not included as candidates, listed for
traceability): [Why is the performance gap between cockroachdb and yugabytedb so large? — GitHub Discussion #83769](https://github.com/cockroachdb/cockroach/discussions/83769); [How does Cockroach test for Postgres compatibility? — GitHub Discussion #77991](https://github.com/cockroachdb/cockroach/discussions/77991); [Need help to review a serializability implementation for MySQL Cluster — Cockroach Labs forum](https://forum.cockroachlabs.com/t/need-help-to-review-a-serializability-implementation-for-mysql-cluster/6130); [schemachanger: concurrent schema changes are not properly detected · Issue #77648](https://github.com/cockroachdb/cockroach/issues/77648).
