# Review — `design/knowledge-index.md`

## Round 1 — 2026-09-14

**Summary judgment.** This is a strong, unusually well-evidenced design: the storage split, the
per-file transaction, the no-ATTACH decision, the empty-groups rule, and the tool-description
occasion design are all correctly reasoned from cited measurements, and the Amazon Q comparisons I
checked are supported line-for-line by both research notes. It is not shippable yet, for three
classes of reason: two decision citations say things the cited decisions do not say (one is a
quotation attributed to D10 that is actually D32's rationale); the git fast path and the schema's
"cascade" language are wrong in ways an implementer following the letter of the document would ship
as silent staleness and orphaned index rows; and the agent-facing `name` parameter is a path
traversal that can unlink `memory.db` — the one thing the brief says this design must not damage.

### Findings

1. **[BLOCKER] §8.2 and §6.2 both misattribute to D10 reasoning that lives elsewhere.**
   (a) §8.2: *"citing D10 — consolidation is user-invoked because 'exposing it to the primary agent
   would let it fire the one expensive path on a whim'"*. D10's rationale in `design/overview.md` §4
   is about the absence of a compaction hook ("Manual invocation is honest about that rather than
   guessing with a proxy"). The quoted clause is **D32's** rationale ("or the primary agent could
   fire the expensive path on a whim"), and it is not verbatim there either. The withdrawal argument
   survives intact — it just rebuts D32's concern, not D10's. Fix: attribute the quote to D32, quote
   it exactly, and drop "citing D10" or replace with "citing the D10/D32 pattern".
   (b) §6.2: *"A lock whose pid is not alive is stale and reclaimable — the same liveness-evidence
   reasoning D10 applies to the consolidation lease."* D10 says nothing about leases or liveness.
   The consolidation lease's liveness reasoning (FINDINGS open question 10) is the **opposite
   mechanism**: takeover is by explicit human reinvocation via `plan_groups`, precisely because a
   human act is "the only liveness evidence that exists" — not by a pid-aliveness probe. Fix: cite
   FINDINGS open question 10 / the M10 takeover design, and state that this design deliberately uses
   the *weaker* pid-aliveness test because an indexer, unlike a consolidator, is code with no
   judgment in flight and a spurious reclaim costs one rescan, not a worker's reasoning. That
   sentence is currently claiming sameness where there is a deliberate difference.

2. **[BLOCKER] "A blended cross-KB ranking is measured as uncomputable" is contradicted by the
   cited probe.** §2: *"§7.2 measures that such an ordering cannot be computed correctly"*; §13:
   *"§7.2 measures it as uncomputable rather than merely hard."* `research/cross-kb-ranking-probe.md`
   measures that pooling **BM25 scores** is wrong — and then, in its own "What follows" items 3–4,
   states that a blended ordering remains available (*"rank within each KB, then merge by rank,
   never by score … once a global lexical ordering exists by any defensible rule, fusion proceeds
   unchanged"*) and names the merge rule as *"a real open choice — Unmeasured; needs a decision."*
   Declining to blend is a defensible decision (rank-merge quality is unmeasured, and grouped
   presentation preserves the abstention signal), but the document claims the measurement settles
   what the measurement explicitly leaves open — this corpus's most persistent defect class, a
   sentence naming a quantity the instrument did not measure. Fix: in §2, §7.2 and §13, replace
   "uncomputable / cannot be computed correctly" with "score pooling is measured wrong; a rank-based
   blend is possible but of unmeasured quality, and is rejected because publishing an unmeasured
   global order would misrepresent the one thing the grouped form states honestly" — and record
   explicitly that this disposes of the probe's open item 4 (round-robin vs size-weighted) by
   declining to create a global lexical ordering at all.

3. **[BLOCKER] §4.3 divergence 2 attributes to D28 a rationale D28 does not state.** *"D28's
   reasoning explicitly rested on memories being short — measured at 162–879 tokens."* Both
   `design/overview.md` D28 and `design/indexing.md` §"FTS5 stays unchunked" give one reason: *"BM25
   already applies document-length normalization, so chunking the lexical side is redundant work
   against a mechanism that is already correct."* Shortness appears nowhere in either; 162–879
   tokens is FINDINGS open question 3's measurement, made months after D28. The honest form is
   stronger for this design anyway: D28's stated rationale ("BM25's normalization is already
   correct") holds at memory lengths and is exactly what breaks at 1 MiB — so divergence 2 is a case
   of D28's own premise failing out-of-range, not of a shortness assumption this document has to
   invent. Fix: quote D28's actual rationale and argue its range of validity, citing the 162–879
   figure as FINDINGS' measurement, not as D28's reasoning.

4. **[BLOCKER] `name` is unvalidated and is used to build a filesystem path — the agent can unlink
   `memory.db`.** §3.1 defines the KB file as `<project>/.zikaron/knowledge/<name>.db`; §8.4's
   `zikaron_knowledge_remove(name, confirm)` "unlinks after `confirm=true`". Nothing anywhere
   constrains `name`. `zikaron_knowledge_remove(name="../memory", confirm=True)` resolves to
   `<project>/.zikaron/memory.db`. The same hole lets `add` create databases outside `knowledge/`.
   Invariant 9 guards result `path`s but nothing guards KB names, and the review brief's own intent
   line — "must not damage the existing memory store" — is violated by a single tool call. Fix:
   specify a name grammar (e.g., `^[a-z0-9][a-z0-9-]{0,63}$`: single path component, no dot, no
   separator — excluding `.` also prevents `.db`-suffix games), reject at `add`/`remove`/`refresh`
   and at the CLI, and add an invariant: **"A KB name is a single path component matching the stated
   grammar; every knowledge database path is directly inside `knowledge/`."** Case-insensitive
   filesystems are a second reason to force lowercase: `Docs.db` and `docs.db` are one file on APFS
   and two KBs in the design.

5. **[BLOCKER] The git fast path (§5.2) is underspecified in ways that skip changed files
   silently, and §5.4's "avoided by construction" is false for it.** Three parts:
   (a) **The skip rule admits NULL = NULL.** "A file whose `git_blob_hash` matches
   `files.git_blob_hash` and which `status` does not report is unchanged; skip." Under
   `git_mode = all`, an untracked file has no `ls-files -s` entry (both hashes NULL), and
   `git status --porcelain` in its default `-unormal` mode reports untracked *directories* as one
   `?? dir/` line without enumerating files inside — so an edited untracked file inside an untracked
   directory satisfies the literal rule and is skipped as unchanged. Fix: state that the fast path
   applies **only** to paths present in `ls-files -s` with a non-NULL stored `git_blob_hash`;
   everything else is read and hashed. If `status` output is consulted for the dirty set, require
   `--porcelain -z -uall` (also solves `core.quotePath` mangling of non-ASCII paths, which matters
   because `path` is the join key).
   (b) **`git_mode = tracked` has no defined candidate set, and §4.1 contradicts §5.2 for
   tracked-but-ignored files.** §4.1's six-step pipeline never mentions the tracked restriction;
   §5.2 says `tracked` "inherits `.gitignore` for free". Git itself ignores `.gitignore` for tracked
   files, so a tracked file matching `.gitignore` is *in* the corpus by §5.2's ls-files reading and
   *out* by §4.1's step-3 walk filter. Two implementers will ship different corpora. Fix: define the
   candidate set per mode — `tracked`: exactly `ls-files -s` regular-file entries intersected with
   the walk's prune/symlink/size/text rules, with `.gitignore` **not** separately applied (matching
   git's own semantics); `all`: the §4.1 walk, with `.gitignore` applied and an explicit statement
   of whether it also excludes tracked files (recommend: it does not, same reason).
   (c) **The fast path inherits the clean-filter masking §5.4 claims to avoid.** `ls-files -s` blob
   hashes are hashes of clean-filtered content, and `git status` compares filtered content — so an
   on-disk change that a filter erases (the §5.4 CRLF example, ident, any custom clean filter) is
   invisible to both subprocesses, and the fast path skips a file whose indexed bytes changed,
   without ever consulting `content_hash`, "THE authority". The failure is the same one §5.4
   documents for `hash-object`, arriving through the front door. It is small in practice (eol-class
   changes), but *"This design does not call `hash-object` at all … so the trap is avoided by
   construction"* is prose the adjacent mechanism contradicts. Fix: narrow §5.4's claim to the
   in-process hash, and add to §5.2: "the fast path is correct up to clean filters: a change a
   filter erases is skipped; `git_mode = off` or a `full` refresh restores byte-exactness."

6. **[BLOCKER] §7.5's first staleness disjunct has no persisted representation and cannot be
   implemented from this document.** `stale: true` "when the last scan recorded the file as changed
   but its reindex has not completed" — but the schema (§3.2) has no pending flag, no dirty table,
   and §6.3's progress keys are counters. Nothing says the scan is two-phase or where "recorded as
   changed" lives, so the search path has nothing to read. Fix: either specify the record — e.g.,
   the indexer writes the changed-path list to a `pending` table (or a `meta` JSON value, with its
   size bound stated) in one transaction when the scan phase completes, deleting entries as each
   file commits, with search consulting it — or cut the disjunct and let the `stat` check carry
   §7.5 alone. If the pending set is added, invariant it: "a path in `pending` names a file whose
   `files` row (if any) predates the current scan."

7. **[BLOCKER] §8.3's signature comment contradicts the prose beside it.**
   `knowledge_bases: list[str] | None = None,   # enum-constrained; None = all` — followed
   immediately by *"deliberately **not** a schema enum"* and a whole subsection on why the enum was
   withdrawn. One implementer ships the enum the comment names and recreates the exact
   created-KB-unusable defect §8.3 exists to prevent. Fix: change the comment to
   `# free-form, validated at call time; None = all`. (This is the project's named failure mode —
   prose asserting what the adjacent artifact contradicts — inside a single code block.)

8. **[BLOCKER] "Chunks, FTS rows and vectors cascade" (§5.5) describes a mechanism SQLite does not
   provide.** An FK `ON DELETE CASCADE` from `chunks` to `files` deletes `chunks` rows only:
   `vec0` virtual tables take no foreign keys, and external-content FTS5 does not observe content-
   table deletes — an implementer trusting §5.5 ships orphaned vectors and a corrupt FTS index
   (violating invariant 3 silently, and external-content FTS over deleted rows returns garbage).
   §4.6 already states the correct mechanism — explicit delete of chunks, FTS rows and vectors in
   one transaction. The rename path has the same problem twice: `UPDATE files.path` with dependent
   `chunks` rows needs `ON UPDATE CASCADE` or ordered explicit updates, and `path` is an FTS-indexed
   column of an external-content table, so the FTS entries must be deleted and reinserted, not
   left. Fix: in §5.5, replace "cascade" with "are deleted in the same explicit per-file transaction
   as §4.6"; in §3.2 either add `ON UPDATE CASCADE` or drop the FK to a plain indexed column and
   state that invariants 1/3 are maintained by the per-file transaction plus an invariant test; add
   one sentence to §5.5 on FTS resync for renames. Also note `PRAGMA foreign_keys` is per-connection
   if the FK stays.

9. **[BLOCKER] The tool surface contradicts invariant 10 twice.** (a) §8.3: an unknown KB name
   "returns an error that lists the valid names" — a whole-call error; invariant 10: "Every KB named
   in the request appears in the response, including as an empty or errored group." For a request
   naming one bad KB among three, these prescribe different behaviours. Recommend the per-group
   form: the unknown name appears as `error: unknown_knowledge_base` with the valid names and
   descriptions in that group's error payload, and the other groups answer — it composes with
   partial failure (§11) and keeps one code path. (b) §8.7: on overflow "the lowest-ranked groups
   are dropped **whole**", which removes KBs that invariant 10 says must appear. Recommend keeping a
   stub group (`results` omitted or `dropped: true`) rather than a name in a side list, or reword
   invariant 10 to "…appears in the response as a group or in `truncated_knowledge_bases`". As
   written, two implementers diverge on normative behaviour in both places.

10. **[IMPROVEMENT] §7.2's group ordering is blind to lexical-only hits, and that blind spot lands
    exactly on the code-knowledge case the document's own open question flags.** Ordering groups by
    best dense cosine buries a KB whose top result is a pure lexical hit (exact identifier, error
    string) — and §14.2 already records that identifier discrimination is the dense arm's measured
    weakness (0.194–0.233) and that AWS steers large codebases to the lexical arm. So for the
    operator's own "code knowledge" corpus, the group-order signal is weakest precisely when the
    answer is most likely lexical. The caveat text ("an agent reading only the first group may miss
    a better result in the third") is honest but generic. Fix: name this specific failure shape in
    §7.2 and in open question 2, and note the candidate alternative to sweep alongside arm
    weighting: order groups by best *fused* contribution (rank-based, cross-KB-safe by the same
    argument as RRF) rather than best cosine.

11. **[IMPROVEMENT] §8's surface leaves several behaviours two-readable.** Specify: what `score` in
    the §8.3 result JSON *is* (best-chunk cosine? fused RRF value? they differ by an order of
    magnitude and RRF values are ~0.03 — 0.83 reads as cosine, while "results within a group by
    fused rank" reads as RRF); `refresh(name=None)` semantics (all KBs, presumably — say so, and
    whether locks are checked per KB); `add` with an existing name (error, not upsert — say which);
    `remove` while an indexer holds the lock (refuse with `already_indexing`, or cancel-then-unlink
    — and note the `-wal`/`-shm` siblings must be unlinked with the `.db`); `limit_per_kb > 20`
    (clamp or error); and the reclaim rule when the lock row's `hostname` differs from the current
    host (pid-aliveness is meaningless cross-host — state "never auto-reclaimed" or drop `hostname`
    from the row).

12. **[IMPROVEMENT] Skip accounting is incomplete against §4.1's own principle.** "Skips are
    counted and reported, by reason" — but §8.5's buckets (`binary`, `over_size_cap`,
    `excluded_by_glob`, `gitignored`, `decode_error`) have no bucket for pruned directories,
    unfollowed symlinks, the extension deny-list (§4.2), or a candidate that cannot be read
    (deleted mid-scan; sparse-checkout skip-worktree under `tracked`). A whole subtree pruned by the
    dot-rule is exactly "a file silently omitted" — §4.1's stated defect. Fix: add `pruned_directory`
    (count of directories, stated as such), `symlink`, `denied_extension`, `unreadable`. Also state
    explicitly that `include_globs` cannot rescue a pruned directory (`.github/`, `.notes/`, a docs
    tree named `build/`) — deny-by-default makes that surprising enough to say out loud, and it is a
    real limitation for documentation corpora, where `.github/` is a common home for run books.

13. **[IMPROVEMENT] Journal mode is unstated, and search-during-build depends on it.** §4.6/§6.3
    promise a search serving committed state while the indexer writes; with SQLite's default
    rollback journal, readers contend with the writer, and with WAL the promise holds cleanly. This
    project has a measured history here (spike 3's `busy_timeout`; the `cp memory.db` WAL lesson).
    Fix: state WAL explicitly per KB database, note the `-wal`/`-shm` siblings in the "one SQLite
    file" claim of §3.1 (true at rest, three files while open — deletion and any future backup
    guidance must handle all three), and state that the service's knowledge queries obey the same
    off-event-loop rule `architecture.md` makes normative for the memory path, since a blended
    event loop is the one way this feature *could* damage memory-serving latency.

14. **[IMPROVEMENT] Three load-bearing numbers have no recorded provenance.** (a) The §5.1 timing
    table and §5.2's "16 ms" are careful measurements ("2,046 files / 13.2 MB, warm cache") with no
    named harness — the cross-KB probe's spikes are in `spikes/` and cited; the hash table cites
    nothing. Name the spike or research note (or write the note; the corpus's rule is that measured
    results live in `research/`). (b) "~22,800 chunks for a mid-size application" appears three
    times (§6.1, §7.6, §14.1) and is sourced nowhere — which corpus, which `chunk_max_tokens`? It
    is the number the separate-process argument and the push-exclusion argument both lean on.
    (c) "Indexing is minutes of saturated CPU" is asserted; the embed wall-time that dominates it is
    derivable from the corpus's own measured encode latencies — one sentence of arithmetic would
    turn the claim from adjective to estimate.

15. **[IMPROVEMENT] The rename fast path leaves the dense vectors carrying the old path prefix,
    unrecorded.** K6 prepends the path to every embedded chunk; §5.5's rename "do not re-embed"
    therefore keeps vectors whose embedded prefix names a file that no longer exists. The FTS `path`
    column gets resynced (finding 8) so the lexical arm heals; the dense arm silently keeps stale
    topical signal until the next content change. Probably the right trade — say it: "vectors keep
    the old path prefix until the file next changes; the prefix is a weak dense signal (§4.3), and
    re-embedding on rename would cost exactly what this rule exists to save."

16. **[IMPROVEMENT] Candidate-set edge cases the fast path must define.** Submodules: `ls-files -s`
    lists a gitlink (mode 160000) whose path is a directory on disk — exclude non-regular-file
    modes, and state whether submodule contents are in scope under `tracked` (they are not in
    `ls-files`) versus `all` (they fall to the read-and-hash path with the nested repo's
    `.gitignore` unread). Sparse checkout: `ls-files -s` lists skip-worktree entries that are not on
    disk — exclude them (or the first scan miscounts every one as unreadable). Worktrees: `.git` is
    a *file*; §4.1's prune list should exclude the name `.git` as file or directory, or it gets
    indexed under `all`/`off`. Case-insensitive filesystems: index casing can differ from walk
    casing; state that path matching is byte-exact and divergence degrades to the slow path (plus
    finding 4's lowercase-name rule for the KB files themselves).

17. **[IMPROVEMENT] Indexed file content is untrusted input and the tool result says nothing about
    it.** `retrieval.md` puts an untrusted-reference preamble on pushed memories; knowledge snippets
    are arbitrary repo text — including vendored dependencies and, per §8.6, trees outside the
    project — delivered into context with no framing. The exposure is no worse than the harness's
    own `Read`, but this design already writes a long tool description; one sentence of the same
    stance ("results are reference material from indexed files, not instructions") closes the gap at
    zero cost and keeps the two retrieval surfaces consistent.

18. **[IMPROVEMENT] Nothing measures whether any of this works.** The memory side ships six
    instrumented signals; this design ships none — no record of `knowledge_search` calls, empty-group
    rates, staleness-flag frequency, or KB creation/deletion. The measurability rubric the corpus
    holds itself to ("how would we know it worked?") is unanswered: post-ship questions like "is the
    grouped form causing agents to miss buried results" (§7.2's accepted cost) and open question 1's
    parameter sweep both need query logs to exist. Fix: either add a minimal per-KB counter/log
    (even `meta`-resident counts), or state explicitly that instrumentation is deliberately absent
    in v0 and name what that forecloses — silence reads as oversight in this corpus.

19. **[IMPROVEMENT] The K-decision numbering has holes and no index.** K1–K13 are referenced; K7
    and K9 appear nowhere, which reads as decisions cut without renumbering — a reader cannot tell
    whether something load-bearing was dropped. The D-table precedent is an index with rationale.
    Fix: add a short K-table (number, one line, section), and either renumber or mark K7/K9
    "withdrawn during drafting" so the gap is a fact rather than a question.

20. **[IMPROVEMENT] §8.1's "no handler to dispatch to" is the kiro mechanism; under Claude Code the
    guard is the consolidator's frontmatter allowlist.** Per D34/D32's split, Claude Code registers
    MCP servers session-wide and gates subagent tool access mechanically via frontmatter `tools:`.
    The consolidator-mode *server* has no knowledge handlers, but the consolidator *agent* is kept
    from the primary server's knowledge tools by its allowlist, not by handler absence. The property
    survives on both harnesses; the stated mechanism is one harness's. One sentence, plus deferring
    the harness-coupled detail to `design/harness.md`, which is normative for exactly this.

21. **[IMPROVEMENT] `knowledge_scan_on_session_start` has no named actor.** No component in this
    design observes "session start": the service is started lazily, the hook must stay thin
    (D22-adjacent), and §6.2's "spawned … by the service on a scheduled scan" is the only mention of
    scheduling, undefined. Name the mechanism (the natural candidate is the `agentSpawn` warm
    helper, already a detached best-effort process) or mark the key reserved-and-inert in v0.

22. **[NITPICK] §4.5: "a working 32-wide batch path" overstates the cited note.** The engine
    teardown's §1 shows the batch path carries the unmasked-mean-pooling bug, making embeddings
    depend on batch composition — the path exists and is *wrong when exercised* ("It is also,
    incidentally, the only reason the … bug does not corrupt the stored vectors"). "an unexercised
    32-wide batch path" is the supported wording.

23. **[NITPICK] Small precision fixes.** §4.2: "its first 8 KiB contains no NUL byte, and it
    decodes as UTF-8" — say the *whole file* must decode (a file whose tail is invalid UTF-8 must be
    a `decode_error` skip), and state the `.gitattributes` precedence direction (exclusion only; a
    `text` attribute does not force-index what the sniff rejects). §5.1: state whether
    `content_hash` covers raw bytes or post-BOM-strip text (rename matching needs one answer).
    §6.3: "with counts (§8.4)" should point at §8.5. §7.1: the ATTACH limit of 10 is SQLite's
    compile-time default (`SQLITE_MAX_ATTACHED`, raisable to 125), so "hard" should read "hard in
    any stock build" — the conclusion stands regardless. §8.5: `status` should echo `include`/
    `exclude`/`git_mode` from `meta` — the Amazon Q note's own "record the patterns so refresh can
    reuse them" lesson, half-applied if the agent cannot see them. §8.4: "all three return the same
    status shape" is odd for `remove`, whose KB no longer exists — presumably a final snapshot plus
    `removed: true`; say which.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-14

**Summary judgment.** All 23 round-1 findings are genuinely fixed — I verified each against the
current text, the D32 quote is now verbatim against `design/overview.md`, and the new evidence
(`research/knowledge-index-hash-timings.md`, spike-results §D31's 5.45 ms, the cross-KB probe's open
item 4) supports every sentence that cites it, including §6.1's arithmetic (22,800 × 5.45 ms ≈ 124 s,
checked). The walk-first rewrite of §5.2 and the §5.6 table are the strongest additions. But the
in-place editing did what the brief predicted: four places where a fix landed in one section while a
neighbouring section still asserts the pre-fix world — two of them exactly the "prose contradicting
the mechanism beside it" class this corpus keeps convicting itself of.

### Findings

1. **[BLOCKER] §4.1 step 3 contradicts §5.2's candidate table on `.gitignore`, in both modes.**
   Step 3: *"`.gitignore`, when the root is inside a git repository and `git_mode` is not `off`"* —
   so it applies under `tracked`. §5.2's table, for `tracked`: *"`.gitignore` is **not** separately
   applied … A tracked-but-ignored file is therefore **in** the corpus."* An implementer following
   §4.1 filters the walk by `.gitignore` before the ls-files intersection and ships that file **out**
   — the exact two-implementers divergence §5.2 says it exists to remove. And under `all`, the table
   says *"A **tracked** file that matches `.gitignore` is still **in**, same reasoning"*, but step 3
   states no tracked-file exception, so the walk as specified excludes it. Fix step 3 to carry the
   whole rule: applies only when `git_mode = all`, and only to paths **not** listed in
   `git ls-files` (git's own semantics: ignore rules never affect tracked files); under `tracked` the
   ls-files intersection does this work; under `off` git is not consulted.

2. **[BLOCKER] `git_mode = tracked` and `all` are undefined when the root is not inside a git work
   tree — and `tracked` is the default on a use case §8.6 endorses.** §8.4's
   `git_mode: str = "tracked"` plus §8.6's *"indexing a docs tree … outside the project is a
   legitimate use"*: `add` on a non-repo directory makes §5.2's candidate set *"the §4.1 walk
   intersected with regular-file entries of `git ls-files -s`"* — an intersection with a failed
   subprocess. Three implementations follow the letter plausibly: error at `add`, silently empty
   corpus (the §4.1 "file silently omitted" defect, corpus-wide), or degrade to the walk. §5.3
   ("Without git") covers change detection but never defines the candidate set. Fix: state it —
   e.g., outside a git work tree (or with no `git` on `PATH`), `tracked` and `all` degrade to the
   `off` walk, `status` reports the effective mode (`git_mode_inactive` or similar), and `add`'s
   return says so. Refusing `tracked` at `add` for non-repo roots is the alternative; either is
   fine, unstated is not.

3. **[BLOCKER] Invariant 12's second clause is false under §6.4's own crash story, and enforcing it
   destroys the signal `pending` exists to provide.** Invariant 12: *"`pending` is empty whenever
   `indexing` is false."* Kill the indexer mid-build (the scenario §6.4 designs for): the lock pid is
   dead, so `indexing` is false, and `pending` still holds every not-yet-reindexed path. That state
   is not a defect — it is the *only* thing keeping §7.5's disjunct 1 honest between the crash and
   the next scan, since those files were noticed changed and never reindexed. An implementer making
   the invariant test pass must sweep `pending` on some startup path, which deletes exactly that
   information. Three-part fix: (a) reword the clause to what is true — `pending` is emptied by scan
   *completion*; rows surviving a crash are deliberate and are served as `stale: true` until the
   next scan; (b) state in §7.5 or §3.2 that phase 1 **replaces** the table's contents rather than
   appending (a file reverted between scans must lose its stale row); (c) one sentence in §6.4
   acknowledging `pending` survives a crash and why that is correct — §6.4's "there is no separate
   checkpoint; the `files` table *is* the progress record" currently reads as if `pending` did not
   exist.

4. **[BLOCKER] §12's counters make the service a second writer to the KB database, and §3.3 still
   says there is exactly one.** §3.3: *"here there is exactly one writer — the indexer"* — the
   stated ground for dropping D26's apparatus. §12 puts `searches`, `searches_empty`,
   `results_returned`, `results_stale` in each KB's `meta`, incremented by the service on the
   **search path**. Two consequences, neither stated: the one-writer claim is now false as written
   (the D26 argument survives — counters are not agent-authored records — but the sentence needs
   narrowing to "one writer of indexed content"); and a counter `UPDATE` is a write transaction on
   the latency path §6.1 exists to protect, contending with the indexer's WAL writer lock during
   exactly the builds §6.3 promises search availability through. Fix: amend §3.3, and state in §12
   that counter writes are **best-effort and never block a search** — skipped outright on
   `SQLITE_BUSY` rather than waiting out a `busy_timeout`, an acceptable loss for a counter and not
   for a query.

5. **[IMPROVEMENT] §3.3's "read-only from the agent's perspective (§8.5)" is a leftover from the
   withdrawn K9.** Under the CLI-only draft that sentence was literally true; §8.2 now gives the
   agent create, delete, and reindex, so "read-only" is false in the sense a reader will take it —
   the agent can destroy any KB with one confirmed call. The claim the section actually needs is
   narrower and still true: the agent never *authors or edits indexed content* — no amend verb, no
   record ownership; management verbs operate on whole corpora. Reword to that, and fix the pointer,
   which should be §8.2 (management surface), not §8.5 (`status`).

6. **[IMPROVEMENT] Open-question cross-references collide between two namespaces, and one is stale
   after the §16 insertion.** §7.2: *"Open question 2 records that identifier discrimination is the
   dense arm's measured weakness (0.194–0.233)…"* — that content lives in **§16 item 3** (or
   FINDINGS open question 8); this document's own open question 2 is the group-ordering blind spot,
   which cites §7.2 right back. The reference was written against the pre-insertion numbering and
   never moved. Meanwhile §16 item 1's "Open question 2 already records that unweighted RRF
   discards…" and item 3's "Open question 8 measures…" both mean **FINDINGS'** list without saying
   so, in a section that has its own numbered list. Fix: qualify every instance — "FINDINGS open
   question 8" / "open question 3 (§16)" — the same discipline the document already applies in §4.3
   ("FINDINGS open question 3 measures…").

7. **[IMPROVEMENT] §6.2's "or by the service on a scheduled scan" names a mechanism v0 does not
   have.** §10 makes `knowledge_scan_on_session_start` reserved-and-inert precisely because no
   scheduler exists, and no other scheduling is specified anywhere — yet §6.2 still lists a
   scheduled scan as one of the two spawn paths, resurrecting the exact undefined actor round-1
   finding 21 removed. The actual second spawn path is the service handling `add`/`refresh` (§8.4).
   Fix: "spawned by the CLI (§9) or by the service handling `add`/`refresh` (§8.4)".

8. **[IMPROVEMENT] §5.6 asserts §4.1 does something §4.1 does not say.** Linked-worktree row:
   *"§4.1's prune rule matches the *name* `.git` whether it is a file or a directory"* — but §4.1
   step 1 is *"Directory pruning, evaluated at the directory node"*, which never sees a `.git`
   **file**, and no other §4.1 step excludes it (only dot-*directories* are excluded; dot-files are
   admitted — §4.3's own `.env.example` example depends on that). One clause in §4.1 step 1 fixes
   it: "the name `.git` is additionally excluded when it is a file (linked worktrees, §5.6)".

9. **[NITPICK] §5.2's `tracked` row calls mode `120000` a "regular-file entry".** It is a symlink;
   §4.1 step 2 excludes symlinks, so the intersection removes it anyway and listing it is
   dead-but-misleading. Drop `120000`, or annotate "(symlinks; excluded by §4.1 step 2 regardless)".

10. **[NITPICK] Three pointer/coverage slips.** §4.1 "Skips are counted and reported (§8.4)" — the
    breakdown is defined in §8.5 (same slip round-1 finding 23 fixed at §6.3). §2's "rejected as
    unmeasured (§7.2)" — the rejection reasoning and the probe-open-item disposal live in §15; cite
    both. §3.1's rejection list (`add`, `remove`, `refresh`, CLI) omits the name-taking readers —
    invariant 11's path rule covers them, but one clause saying `search`/`status` match requested
    names against the directory scan by string equality, never by constructing a path, closes the
    reading where an implementer builds `knowledge/<name>.db` from an unvalidated name to probe it
    (note `memory.db` *has* a `meta` table, so `status(name="../memory")` under that reading answers
    rather than errors).

11. **[NITPICK] §8.3's `score` definition has three loose threads.** "The chunk's best-chunk cosine
    similarity" is garbled — per-result, it is simply that chunk's cosine ("best-chunk" is §7.3's
    per-file-cap vocabulary). "in `[0, 1]`" is not a property of cosine (range [−1, 1]); say
    "nonnegative in practice for this encoder" or drop the range. And a chunk reached only by the
    lexical arm has no cosine in hand from retrieval — it needs an explicit `chunks_vec` lookup;
    one clause saying so also covers §7.2's "best dense cosine in the group" for a group whose hits
    are all lexical.

12. **[NITPICK] §7.5 disjunct 2 is silent on a failed `stat`.** A file deleted since the last scan:
    `stat` returns ENOENT, which is neither "size differing" nor a `pending` row. It is the
    strongest staleness evidence available; state that a failed `stat` sets `stale: true`.

13. **[NITPICK] `meta` key naming drifts between sections.** §6.3 writes `started_at` where §3.2
    lists `last_scan_started_at`; §6.3's progress keys (`files_seen`, `files_indexed`,
    `files_skipped`, `bytes_indexed`) are absent from §3.2's key listing; §6.2's lock tuple
    `(pid, started_at, hostname)` versus §3.2's `lock_pid, lock_host, lock_started_at`. One
    authoritative key list in §3.2, and the prose naming keys exactly.

14. **[NITPICK] §10 names the warm helper by kiro's trigger.** "the detached warm helper the
    `agentSpawn` hook already spawns" — under Claude Code the trigger is `SessionStart`, and
    `design/harness.md` is normative for exactly this vocabulary (§8.1 already got this treatment).
    Say "the session-start warm helper (trigger name per `design/harness.md`)".

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-14

**Summary judgment.** The four round-2 blockers are genuinely fixed where they landed — §4.1 step 3
now agrees with §5.2 in both modes, the degradation rule is stated and its three-corpora ambiguity is
gone, `pending`'s crash survival is coherent across §3.2/§6.4/§7.5, and the writer claim is narrowed
consistently across §3.3/§6.1/§12, with §12's best-effort rule and §8.3's `chunks_vec` lookup both
holding up against the cost arguments they touch. But the predicted class recurred: one flat
normative contradiction (§4.2 consults git under a mode §5.2 says never consults git), one invariant
that is false under an ordinary non-crash run of the document's own mechanisms, and — a process
finding — round 2 had **14** findings while the transmittal says "all 11 accepted and applied";
findings 12–14 are unapplied in the text, which is the audits-enumerate-phrasings failure FINDINGS'
M18 entry names.

### Findings

1. **[BLOCKER] §4.2 consults git in a mode §5.2 says never consults git.** §4.2: *"Inside a git
   repository, `.gitattributes` `binary`/`-text` markings **exclude** a file the sniff would have
   admitted"* — unconditional on mode. §5.2's `off` row: *"the §4.1 walk. Git is not consulted at
   all"* — categorical. Text detection is §4.1 step 6, which incorporates §4.2, so under `off` (and
   under the new effective-`off` degradation, where `git` may not even be on `PATH`) step 6 both
   must and must not invoke `git check-attr`. Two implementers ship different corpora for
   attribute-marked files — the exact shape round-2 finding 1 had, one section over. Fix: condition
   the attributes check on effective `git_mode ≠ off`, and add one clause to §4.2: "when the
   effective mode is `off` (§5.2), attributes are not read and the sniff alone governs" — which
   also keeps the degradation rule honest when `git` is absent from `PATH`.

2. **[BLOCKER] Invariant 12's "emptied by scan completion" is false under an ordinary, non-crash
   run, because only the §4.6 reindex transaction is ever told to delete a `pending` row.** §7.5:
   rows are deleted "inside that file's own §4.6 transaction". But phase 2 has three other
   outcomes for a path phase 1 put in `pending`, and none of them touches the table as specified:
   (a) the file is **deleted** between phases — §5.5's deletion transaction lists `files` row,
   chunks, FTS rows and vectors, not `pending`; (b) the file is **renamed** — §5.5's rename updates
   `files.path` and `chunks.path` with no reindex commit; (c) the file is **unreadable** at reindex
   (an `unreadable` skip per §8.5). In all three the scan completes with `pending` non-empty, so
   the invariant test coding-standards requires goes red on any active worktree — or an implementer
   makes it pass with an end-of-scan sweep, recreating exactly the naive-reading hazard §6.4 just
   closed for the crash case. Fix, three parts: state that the §5.5 deletion and rename
   transactions also delete the path's `pending` row (both old and new path for a rename); reword
   invariant 12's second clause with the one honest exception — "except paths whose reindex could
   not commit (e.g. unreadable), which correctly remain and are served `stale: true`"; and while
   in there, fix the vocabulary drift the two-phase design introduced — §3.2's comment uses "the
   scan phase" for phase 1 while §7.5 and invariant 12 use "scan" for the whole two-phase
   operation. Name the phases once (walk phase / index phase) and use those names in all three
   places.

3. **[IMPROVEMENT] §8.5's field list was not updated for two things other sections say `status`
   reports.** (a) §5.2: *"`status` reports `git_mode_effective` alongside the configured value"* —
   §8.5's "Returns per KB:" enumeration has `git_mode` only. (b) §12: the four counters are "held
   in each KB's `meta` (§3.2) and reported by `status`" — none appears in §8.5. The omission
   propagates: §8.4 defines `add`/`refresh` returns as "the same status shape as §8.5", so an
   implementer building from §8.5 ships `add` returns that cannot "say so" about degradation as
   §5.2 requires. Fix: add `git_mode_effective` and the four §12 counters to §8.5's list, and say
   where `git_mode_effective` comes from — recommend recorded to `meta` at scan start (e.g.
   `last_scan_git_mode_effective`), since the value that explains the *indexed* corpus is the one
   the last scan used, not whatever the environment happens to be at `status` time.

4. **[IMPROVEMENT] §4.1 step 6's position in the walk order silently destroys §5.2's fast path if
   implemented literally.** §4.2 requires *whole-file* UTF-8 decode; §4.1 presents text detection
   as filter step 6 of discovery. Applied at walk time, that reads every byte of every candidate
   on every scan, which reduces the 4.3 ms git fast path to the 33–75 ms read-everything path the
   §5.1 table exists to beat — the design's headline economy undone by its own filter ordering.
   The fix is one sentence in §4.1: steps 1–5 evaluate during the walk; step 6 evaluates only when
   a file is read for (re)indexing, so a candidate the §5.2 skip rule clears is never re-sniffed
   (its prior admission stands, correctly, since its bytes are unchanged).

5. **[IMPROVEMENT] Round 2 had 14 findings; the transmittal says "all 11 round-2 findings were
   accepted and applied", and findings 12–14 are indeed unapplied in the text.** Verified against
   the artifact: (12) §7.5 disjunct 2 still says only "a live `stat` shows `size` differing" — a
   failed `stat` (ENOENT, the strongest staleness evidence there is) still maps to no disjunct;
   (13) §6.3 still writes `started_at` against §3.2's `last_scan_started_at`, the progress keys
   (`files_seen`, `files_indexed`, `files_skipped`, `bytes_indexed`) and the §8.5 skip-reason
   counts are still absent from §3.2's key list, and §6.2's lock tuple `(pid, started_at,
   hostname)` still disagrees with §3.2's `lock_pid, lock_host, lock_started_at`; (14) §10 still
   names the warm helper by kiro's `agentSpawn` trigger where `design/harness.md` is normative.
   All three remain worth applying — 13 most, since §3.2 presents itself as the schema while three
   other sections write or report keys it does not list. And record the count slip itself: an
   audit that verified "the 11 findings" against a round that contained 14 is the
   enumerate-the-phrasings-not-the-claim failure this corpus already convicted itself of in M18.

6. **[NITPICK] Two bare "open question 1" references survive the namespace sweep disposition 6
   declared complete ("zero bare ones remain, verified by grep").** §7.2: "It belongs in open
   question 1's sweep alongside arm weighting"; §12: "open question 1's parameter sweep needs real
   query volume". Both mean §16 item 1, but the collision is real, not theoretical: FINDINGS open
   question 2 is *also* an RRF sweep involving arm weighting, and FINDINGS open question 1 is
   something else entirely. The grep evidently matched the cross-namespace phrasings round 2
   quoted, not the claim. Fix: "open question 1 (§16)" in both places, the exact form round-2
   finding 6 prescribed for internal references.

7. **[NITPICK] The tool description contradicts §8.3's `score` paragraph on cross-corpus
   comparability.** Description: "relevance is not directly comparable between corpora"; §8.3,
   thirty lines later: cosine "is the quantity that is meaningful across groups (§7.2), which is
   exactly what a reader comparing two groups will try to do." Both are right about different
   quantities (within-group fused rank vs the `score` field); the description's blanket sentence
   erases the distinction the design paid for. One clause: "group *order* and within-group rank
   are not comparable across corpora; the `score` field is."

8. **[NITPICK] §5.1's "it costs nothing extra — the read has already happened" is no longer quite
   true under §7.5's two-phase scan.** Phase 1 must read and hash every candidate the git fast
   path does not clear (all of them, under `off`) *before* any chunking read happens, so the
   change-detection hash is its own read and a changed file is read twice (hash, then chunk). The
   claim stays true of the *stored* hash only. One sentence in §5.1 or §7.5 fixes it, and should
   also state which read produces the stored value when a file changes between phases — phase 2's,
   which "the bytes actually indexed" already implies but an implementer should not have to infer.

9. **[NITPICK] The degradation rule covers "not inside a work tree" and "no `git` on `PATH`" but
   not "git present and failing".** The common modern case is `safe.directory` / dubious-ownership
   refusal in containers and CI: `rev-parse` fails, `ls-files` fails, on a directory that *is* a
   work tree. As written, an implementer can read that as an `add` error, an empty intersection,
   or the degradation — the same three-corpora fork finding 2 of round 2 closed for the other two
   cases. One clause in §5.2's degradation paragraph: any failed git invocation during a scan
   degrades that scan to effective `off`, reported the same way.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-14

**Summary judgment.** All 12 round-3 items (the 9 plus the recovered 12–14) are genuinely applied — I
verified each against the current text, the walk-phase/index-phase vocabulary is consistent across
§3.2/§5.1/§6.4/§7.5/invariant 12 with no surviving "Phase 1"/"scan phase" outside quoted-draft text,
and the namespace sweep is now actually complete. Two problems remain, both created by the round-3
fixes' own interactions rather than left over from before: moving step 6 to index time (R3-4) created
two index-phase outcomes (`binary`, `decode_error`) that the `pending` disposal list (R3-2) does not
cover — invariant 12 goes red on the first scan of any corpus containing an image — and the same
mechanics mean the fast path structurally cannot clear a file it never indexed, so every binary file
is fully read and hashed on every scan in every mode, against a design whose headline is a 4.3 ms
scan.

### Findings

1. **[BLOCKER] The index phase has two skip outcomes the `pending` disposal machinery does not
   dispose of, and invariant 12 goes red on the first scan of any real corpus.** Step 6 now runs at
   index time (§4.1), so `binary` and `decode_error` are **index-phase** outcomes — and new paths do
   enter `pending` (§5.5's rename clause deletes "the new path's" row precisely because they would
   otherwise sit there forever). Trace a fresh KB over a repo containing one PNG that steps 1–5
   admit (the extension deny-list has no image, font, PDF or archive entries): the walk phase reads,
   hashes, and `pending`s it; the index phase reads it, fails the NUL sniff, counts
   `skipped_binary` — and no transaction deletes its `pending` row, because §7.5 and §3.2's comment
   enumerate reindex/deletion/rename only, and invariant 12's exceptions are crash survivors and
   `unreadable` skips, a strict reading of "disposal could not complete" that a completed
   judged-not-text determination does not satisfy. The invariant test coding-standards requires
   fails at scan completion — or an implementer adds a sweep, recreating the hazard §6.4 closed.
   Three parts, plus a boundary case:
   (a) **Never-indexed path failing step 6**: the skip-counting transaction deletes the `pending`
   row (nothing is served for a path with no chunks, so nothing is lost).
   (b) **Previously-indexed path failing step 6** (a file *became* binary or undecodable): treat as
   a §5.5 **deletion** — files row, chunks, FTS rows, vectors and `pending` row in one transaction,
   plus the skip count — by §5.6's own sparse-checkout reasoning: the indexed text no longer
   corresponds to anything indexable, and serving it forever behind a stale flag is worse than
   removing it.
   (c) Update all three enumerations together — §3.2's `pending` comment, §7.5's disposal sentence,
   and invariant 12 (whose exception list then stays exactly crash + `unreadable`).
   And the walk-time twin, currently unspecified anywhere: **a previously-indexed file that stops
   qualifying at steps 1–5** — grows past the size cap, or the cap is lowered in config. §5.5's
   deletion trigger is "a path in `files` that the walk no longer *finds*", and a found-but-filtered
   file satisfies it under one reading and not the other; one implementer deletes the rows, the
   other serves the old chunks indefinitely (with only disjunct 2's size check as a partial
   backstop). One sentence in §5.5 resolving "finds" to "admits as a candidate" (recommended — it
   makes the corpus definition uniform with §5.6's sparse rule) closes it.

2. **[IMPROVEMENT] The fast path can never clear a file that was never indexed, so every binary
   file is read in full and hashed on every scan, in every mode — unstated, and it undercuts the
   economics §5.2 headlines.** The skip rule requires a stored **non-NULL `files.git_blob_hash`**,
   and `files` holds one row per *indexed* file (§3.2), so a tracked PNG under the 1 MiB cap is
   read and hashed by the walk phase on every scan forever (then read again at index phase to be
   sniffed, under the current text). §4.1's "a candidate that the §5.2 skip rule clears is never
   re-sniffed" is literally true and vacuous for exactly these files — they are never cleared. On a
   repo with substantial binary assets (image fixtures, wheels, PDFs) the 4.3 ms scan is 4.3 ms
   plus a full read of every binary byte, twice, per scan; §5.1's table was measured on ~13 MB
   text corpora and does not cover this. Three fixes in increasing strength, at least the first
   two worth taking: (i) restate §4.1's timing rule as "step 6 evaluates on the **first read of
   the file's bytes in a scan** — the walk phase's hash read where one happens, else the index
   phase's chunking read", which halves the cost, keeps the fast-path property intact, and
   shrinks finding 1(a)'s surface (a walk-time sniff failure never enters `pending` at all);
   (ii) extend the §4.2 deny-list with the common binary extensions (`.png .jpg .jpeg .gif .ico
   .pdf .woff .woff2 .ttf .zip .gz .whl .so .db` etc.) so most never reach a read — walk-time,
   free; (iii) if the residual cost ever matters, a remembered-skip memo (path, hash, reason)
   that the skip rule may clear against — a schema change, name it in §16 rather than building
   it. At minimum, state the cost in §5.2 the way §5.3 states the no-git cost; an unbudgeted
   majority path is the exact thing this corpus calls an incomplete design.

3. **[IMPROVEMENT] §4.6 enumerates the reindex transaction's contents and omits the `pending`
   delete that two other sections assign to that same transaction.** §4.6: "delete its chunks,
   FTS rows and vectors, insert the new ones, update its `files` row — is one transaction";
   §3.2's comment and §7.5 both say the reindex transaction deletes the path's `pending` row.
   §4.6 is the section an implementer codes the transaction from, and it predates `pending` —
   the fix-landed-in-one-section-while-the-neighbour-asserts-the-pre-fix-world class, once more.
   Add the clause to §4.6's enumeration.

4. **[IMPROVEMENT] The CLI's per-KB `--max-file-bytes` (§9) is persisted nowhere, has no MCP
   twin, and is invisible to the authoritative `meta` list.** §8.2 claims "every operation has
   CLI parity", but `zikaron_knowledge_add` (§8.4) takes no such parameter; and §10 names
   `chunk_max_tokens`/`rrf_k`/`fusion_depth` as the keys seeded per KB into `meta` while the size
   cap is not among them and §3.2's list has no key for it — so a later `refresh` re-walks under
   the *global* `knowledge_max_file_bytes`, silently changing the corpus the flag defined
   (finding 1's stops-qualifying case, triggered by the design's own mechanics). Either drop the
   flag or do it properly: a `max_file_bytes` meta key seeded at creation (§10's existing
   pattern), the parameter added to §8.4's `add`, and the key added to §3.2. Worth recording:
   the transmittal's 10/10 key check verified every key *named as a key* and could not see this
   one, because it wears a flag's spelling — the claim ("per-KB configuration must persist"),
   not the phrasing, is the thing to audit.

5. **[IMPROVEMENT] §8.5 ties the skip breakdown to "when indexing", but its own stated purpose
   is post-scan.** "and — when indexing — `files_seen`/`files_indexed`, plus `skipped` broken
   down by reason" — yet the section's rationale for the breakdown is "a caller that did not
   create the KB cannot otherwise tell why a file is missing", a question asked overwhelmingly
   *after* a scan completes, and the nine counters persist in `meta` regardless. As written, a
   completed scan's `status` omits exactly the numbers §8.5 spends two paragraphs arguing must
   be surfaced. Fix: always report the last completed scan's breakdown; `files_seen`/
   `files_indexed` are the only fields that are meaningfully "during indexing only" (and even
   those could carry the final values).

6. **[NITPICK] The degradation rule reads as scan-scoped, but git invocations now span both
   phases, and a mid-scan failure has no stated semantics.** `ls-files`/`status` run at walk
   start; §4.2's attributes check runs per file at index time. A `check-attr` failure after
   half the corpus is indexed under effective `tracked` leaves "the effective mode for that
   scan is `off`" retroactively ambiguous. Cheapest closure: batch `check-attr --stdin -z` once
   over the admitted candidate list at walk-phase end, so every git invocation is walk-phase
   and the effective mode is fixed before the index phase begins — one sentence in §4.2 or
   §5.2.

7. **[NITPICK] Two naming drifts inside the newly-authoritative-list regime.** §8.5 reports
   `pruned_directory` (singular) against §3.2's `pruned_directories`, and describes
   `include`/`exclude` as "echoed from `meta`" whose keys are `include_globs`/`exclude_globs`.
   §3.2's own rule is "prose elsewhere must name these keys exactly". Either align the names or
   add one sentence stating the response-field ↔ meta-key mapping (strip `skipped_`, etc.) so
   the drift is a rule rather than an accident.

8. **[NITPICK] §5.2 says `add` reports the degradation in its return, but the value is recorded
   by the detached indexer at walk start — after `add` has returned.** §8.4's `add` "returns
   immediately"; `last_scan_git_mode_effective` does not exist yet at that moment. Say that
   `add` runs its own cheap probe (`rev-parse`, ~ms, synchronous) for its return value, with the
   indexer's walk-start record remaining the authoritative one — or soften §5.2's claim to
   "`status` reports it once the first scan starts".

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-09-14

**Summary judgment.** Seven of the eight round-4 fixes are genuinely and coherently applied — the
"admits as a candidate" resolution, the first-read-in-a-scan rule, the `max_file_bytes` persistence
(verified at all six sites: §3.2, §4.1 step 5, §8.4 signature and prose, §8.5, §9, §10), the batched
`check-attr`, and the naming-rule fix all hold up under the interaction checks the brief asked for.
One did not land completely: the transmittal says "all three enumerations updated together and now
state **four** disposals", and invariant 12 — explicitly one of the three in round-4 finding 1(c) —
still enumerates **three**, with a closing sentence that turns the omission into an active
prohibition of the disposal §5.5 now mandates. That is the count-slip/audit-the-phrasing failure
recurring inside the very fix that was recording it, and it is one line to repair. Everything else
this round is second-order: the walk-end attribute batch needs its ordering pinned, and §8.5's
always-report sentence names a data source the schema cannot supply mid-build.

### Findings

1. **[BLOCKER] Invariant 12 still lists three disposals against §3.2's and §7.5's four, and its
   closing sentence prohibits the fourth.** Invariant 12: *"`pending` is emptied by the index phase
   disposing of every path — by reindex, deletion, or rename (§5.5, §7.5)"* — no text-detection
   skip, while §3.2's `pending` comment and §7.5 both enumerate four and §7.5 adds "a fifth outcome
   would be a defect". Worse than an omission: invariant 12 ends *"An implementation that empties
   `pending` on any other occasion destroys the signal the table exists to carry"*, so the
   skip-recording transaction §5.5 requires to delete the `pending` row is, by the invariant's own
   letter, a signal-destroying occasion — the invariant test coding-standards requires would be
   written to *forbid* the behaviour two other sections mandate. Fix: "…by reindex, deletion,
   rename, or a recorded text-detection skip (§5.5, §7.5)…". And record the process fact: the
   round-4 transmittal claimed all three enumerations were updated together, and the claim was true
   of two. This is the enumerate-the-phrasings failure (M18; round-3 finding 5) recurring inside
   the fix for the finding that named it — the audit needed was "grep every statement of `pending`
   disposal", not "check the sections the finding quoted".

2. **[IMPROVEMENT] The walk-end `check-attr` batch is coherent with the first-read rule only under
   three readings the text does not state.** (a) **Order against the `pending` replacement.** Both
   happen "at walk-phase end" (§4.2, §7.5) with no stated order. Run the batch first and
   attribute-excluded paths never enter `pending` (clean — the same removes-a-disposal-case shape
   as §4.1's walk-phase-sniff property); run it after and a de-facto fifth disposal case exists,
   which §7.5 just declared a defect. One sentence: the batch runs *before* `pending` is replaced,
   so an attribute-excluded path is never a pending path. (b) **Coverage of fast-path-cleared
   candidates.** "Over the admitted candidate list" is the right reading, but the consequence is
   worth its sentence: when `.gitattributes` changes to mark an *unchanged* file binary, the §5.2
   skip rule still clears that file (its own blob is unchanged; only the attribute file changed),
   so the batch is the **only** mechanism that can ever discover the exclusion — a batch run only
   over files being read this scan misses it forever. State that cleared candidates are included,
   and that a previously-indexed file the batch excludes is §5.5's became-binary **deletion**,
   discovered by the walk phase. (c) **The skip bucket.** None of §8.5's nine reasons names an
   attribute exclusion; presumably `skipped_binary`, but §3.2's authoritative-list regime makes
   "presumably" a defect in one of the two places. Say which. Finally, narrow §4.1's *"its prior
   admission stands, correctly, because its bytes are unchanged"*: true of the sniff, false of
   step 6's attribute half, whose input (`.gitattributes`) can change while the file's bytes do
   not — and which the batch correctly re-evaluates every scan. The sentence claims a stability
   the adjacent mechanism deliberately does not provide.

3. **[IMPROVEMENT] §8.5's "reported always, from the last completed scan" names a data source the
   schema cannot supply during a build, and `files_indexed` sits in both the always and the
   indexing-only lists.** §6.3 writes progress — including the skip counters — to the *same single
   set* of `meta` keys after each file transaction, so during a scan those keys hold the running
   scan's partials; no stored copy of "the last completed scan" exists to report from (the
   no-persisted-representation shape of round-1 finding 6, much smaller). §6.3's own rationale
   *wants* live values ("this corpus is 40% indexed"). Fix the sentence to what the mechanism
   provides: reported always; while `indexing` is true the values are the running scan's progress,
   otherwise they are the last completed scan's totals. And resolve the internal duplication:
   `files_indexed` is in the "Returns per KB" list *and* in "`files_seen` and `files_indexed` are
   reported additionally while `indexing` is true" — drop it from the additional-fields sentence
   (leaving `files_seen`), or state the dual meaning explicitly.

4. **[NITPICK] The rename trigger still reads "a path the walk no longer *finds*"** (§5.5, first
   line) — the exact predicate the deletion rule two paragraphs later deliberately resolved to
   "no longer admits as a candidate". No corpus divergence follows (either reading yields the
   same final corpus; they differ only in whether a filtered-but-present twin donates its chunks
   or forces a re-embed), but the resolution paragraph's stated point was uniformity of the
   corpus definition. Align the predicate, and note rename matching evaluates before deletion —
   which "that no rename claimed" already implies.

5. **[NITPICK] A walk-end `check-attr` failure degrades a scan whose candidate set was already
   computed under `tracked`.** §5.2's categorical rule ("any git invocation during a scan fails →
   effective mode for that scan is `off`") now collides with §4.2's claim that batching fixes the
   mode "before the index phase begins": a `check-attr` failure at walk-phase end flips the mode
   *after* the ls-files intersection has shaped the candidate list. One sentence choosing: either
   the walk phase re-runs under effective `off` (a walk is milliseconds), or the narrower rule —
   a `check-attr` failure alone means "attributes unavailable; candidates stand; the sniff
   governs" — with the categorical rule scoped to the enumeration-affecting invocations
   (`ls-files`, `status`).

6. **[NITPICK] §5.1's "must read and hash every candidate the §5.2 fast path does not clear"
   overstates for never-indexed candidates.** A candidate with no `files` row is changed by
   definition — there is no stored hash to compare against — so it needs no walk-phase read at
   all, and §5.5's never-indexed skip case already assumes exactly that ("this case arises only
   when the index phase is the first read" is the *ordinary* path for a new binary file, not an
   exception). One clause in §5.1 ("every candidate *with a `files` row* that the fast path does
   not clear") aligns the two-read account with the mechanics §5.5 describes — and incidentally
   corrects §5.2's cost paragraph's "read in full **and hashed** on every scan": a never-indexed
   binary is read (often only as far as the first NUL) and never hashed.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-09-14

**Summary judgment.** All six round-5 fixes are genuinely applied, and the recurrence check the
transmittal asked for comes back clean on its own terms: the three disposal enumerations (§3.2
comment line 154, §7.5 line 783, invariant 12 line 1192) now agree at four, and a grep over every
`pending`/disposal statement in the file confirms **there is no fourth enumeration** — every other
mention is a per-transaction clause (§4.6 line 375, §5.5 lines 577/583/597), a never-enters
statement (lines 253/306/598), or the crash section, all consistent with the four. What remains is
two letter-level residues of the same fixes, both one-to-three-sentence repairs: invariant 12's
closing allowlist still omits the one legitimate non-disposal occasion its own previous sentence
names, and the enumeration-affecting/filtering split — the brief's question 3 — does leave exactly
one git touchpoint unclassified, because §4.1 step 3 never says how `.gitignore` is evaluated.

**Verification detail for the four checks requested.** (1) Disposal enumerations: confirmed three,
confirmed agreeing, confirmed no fourth (see above). (2) `check-attr` versus its neighbours:
consistent — the batch-before-replacement ordering (§4.2) composes with §7.5's walk-phase sequence
(§7.5's "walks and compares, then replaces" omits the batch as a named step, but §4.2 pins the
order explicitly and cites §7.5, so no contradiction); the coverage rule composes with §4.1's
narrowed stability claim (the sniff/attribute split at lines 244–248 is exactly right); and the
previously-indexed exclusion routes cleanly to §5.5's became-binary deletion, which needs no
`pending` row to delete ("together with its `pending` row" is satisfied vacuously; §5.5's
"disposed of by whichever phase discovers it" covers the walk-phase discovery). (3) The split:
`rev-parse`, `ls-files`, `status`, `check-attr` are all classified; the gap is finding 2.
(4) §8.5's partials/totals rule: consistent with §6.3 (same keys, written per file transaction),
with §8.4's same-shape rule (a scan spawned by `add`/`refresh` reports partials under
`indexing: true`, which is what a polling caller wants), and with §12 (the four counters are
cumulative service-side values, not scan-scoped, so the rule correctly does not touch them) —
except in the crash window, finding 3.

### Findings

1. **[IMPROVEMENT] Invariant 12's closing allowlist omits the walk-phase wholesale replacement,
   so its letter forbids the mechanism §7.5 mandates and its own previous sentence relies on.**
   Line 1196: *"An implementation that empties `pending` on **any occasion other than those four
   disposals** destroys the signal"* — but the walk phase **replaces `pending` wholesale** (§7.5
   line 780), and the invariant's own preceding sentence depends on that replacement to clear the
   two exception classes ("until the next walk phase replaces the table"). On a no-change scan the
   replacement literally empties the table, on an occasion that is not one of the four disposals.
   An invariant test written from the closing sentence's letter — "rows are deleted only by the
   four disposal transactions" — goes red on every scan that drops a reverted file's row, which is
   an ordinary run. This is the residue of the round-5 fix: the enumeration was corrected, the
   allowlist one sentence later was not. One clause: "…on any occasion other than those four
   disposals **or the walk phase's wholesale replacement (§7.5)** destroys…". Tagged improvement
   rather than blocker only because, unlike round 5's case, the legitimate occasion is named
   inside the same invariant two sentences earlier, so a test author has the correction in view.

2. **[IMPROVEMENT] §4.1 step 3 never states how `.gitignore` is evaluated, and the implied git
   invocation is the one the enumeration-affecting/filtering split leaves unclassified.** This is
   the direct answer to the transmittal's question 3. Under `all`, step 3 (lines 222–227) requires
   gitignore evaluation for every walked path not in `ls-files` — but the mechanism is unstated.
   The natural implementation is a batched `git check-ignore --stdin -z`: a git invocation that is
   in neither §5.2's enumeration-affecting list (line 464: `rev-parse`, `ls-files`, `status` —
   punctuated as a definition, not examples) nor the `check-attr` exemption paragraph. By the
   stated distinction it *determines the corpus* (it decides candidacy under `all`, during the
   walk, before the candidate set is final), so its failure should degrade the scan — but an
   implementer cannot get that from the text, and the alternative reading (treat it like
   `check-attr`: "ignore rules unavailable, candidates stand") *widens* the corpus with gitignored
   files, which is a different corpus. The other implementation — parsing `.gitignore` in-process —
   avoids the classification question at the price of reimplementing semantics this document
   elsewhere refuses to leave implicit (nested `.gitignore` files, negation re-inclusion,
   `$GIT_DIR/info/exclude`, `core.excludesFile`), in a document whose own §5.2 makes "Parsing
   `git status` is a correctness surface, not a detail" a bolded rule. Fix: state the mechanism.
   Recommend the batched `check-ignore` with it added to the enumeration-affecting list (its
   failure degrades the scan to effective `off`, under which `.gitignore` is not applied — which
   is self-consistent and reported); if in-process is chosen instead, name which gitignore sources
   are honoured and which are not, the way §5.6 states the nested-submodule limitation.

3. **[NITPICK] §8.5's "otherwise they are the last completed scan's totals" is false in the §6.4
   crash window.** After the crash §6.4 designs for, the lock pid is dead, `indexing` reads false,
   and the single set of `meta` keys holds the dead scan's **partials** — there is no completed
   scan to report totals from, which is the same no-such-source shape round 5's finding 3 fixed
   for the mid-build case. The discriminating data already exists: `last_scan_completed_at`
   predating `last_scan_started_at`. One clause: "…otherwise the last scan's values — its totals
   if it completed, its partials if it crashed (§6.4), distinguishable by `last_scan_completed_at`
   predating `last_scan_started_at`."

4. **[NITPICK] §5.2's "that read stops at the first NUL byte rather than running to completion"
   (line ~504) is categorical where the mechanism is not.** The sniff checks the first 8 KiB for
   NUL and then requires a whole-file decode (§4.2), so a binary whose sniffed prefix is NUL-free
   and which fails only on UTF-8 decode is read in full (or to the first invalid sequence).
   Round 5's suggested wording carried the hedge ("often only as far as the first NUL"); the
   applied text dropped it. Restore the hedge or state both cases in one clause.

5. **[NITPICK] §5.2's candidate-set table: the `tracked` row spans two source lines (452–453),
   which breaks the markdown table.** A table row must be one physical line; as written, renderers
   truncate the row at "excluded by §4.1" and emit the continuation as stray body text — in the
   normative candidate-set definition. Rejoin the row onto one line.

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-09-14

**Summary judgment.** All five round-6 fixes are genuinely applied, and every recurrence and
coherence check the transmittal asked for comes back clean: the `check-ignore` addition is
consistent with the per-mode table, the `check-attr` ordering, and the submodule limitation; the
invariant-12 allowlist is complete against every disposal and replacement the document states; and
§8.5's crash-window clause composes with §11 and §6.2 for every same-host state. One operation the
allowlist check surfaces was left two-resolvable — `refresh full=true`'s entire mechanics are the
three words "discards and rebuilds" — and one plain reading of those words is the document's own
§4.6 cautionary example. That is the only finding above nitpick level, and it is a paragraph to fix.

**Verification detail for the requested checks.**
(1) *Round-6 fixes:* all five confirmed against the current text — invariant 12's allowlist now
names the wholesale replacement with the why-sentence (lines 1210–1214); §4.1 step 3 specifies the
batched `check-ignore --stdin -z`, rejects in-process parsing by §5.2's own rule, and classifies the
invocation as enumeration-affecting (lines 228–235, 469–473); §8.5's partials/totals rule carries
the crash case with the timestamp discriminator (lines 1040–1047); the NUL hedge is restored and
made specific (lines 512–515); the `tracked` row is one physical line and no table row anywhere in
the file spans source lines.
(2) *The closed git-invocation list:* verified by grep over the whole document — `rev-parse`,
`ls-files`, `status`, `check-ignore`, `check-attr` are the only invocations the design makes;
`hash-object` appears only as the explicitly-not-called trap (§5.4). The "exhaustive" claim at §5.2
holds.
(3) *`check-ignore` coherence:* with the per-mode table — invoked only under `all`; under `tracked`
and `off` it never runs, and an invocation never made cannot fail, so the scan-scoped degradation
rule is vacuously consistent there; under `all` its failure degrades to effective `off`, which also
disables the fast path (§5.3's read-everything), conservative and derivable in one way. With §4.2 —
both batches are walk-phase (`check-ignore` at candidacy, `check-attr` at walk-end before the
`pending` replacement), candidacy precedes the walk-phase hashing by construction since §5.1 defines
hashing over *candidates*, and §4.2's "keeps every git invocation inside the walk phase" stays true
with the addition. With §5.6 — git's own `check-ignore`, run from the outer repository, does not
consult a nested repository's `.gitignore`, so the submodule row's stated limitation survives the
mechanism change intact; it is now git's documented behaviour rather than a parser's omission, which
is strictly better.
(4) *Invariant-12 completeness:* grep over every `pending` mention finds exactly the four disposal
transactions (§4.6 reindex; §5.5 deletion, rename-both-paths, never-indexed skip), the wholesale
replacement (§7.5), and three never-enters statements (§4.1, §4.2, §5.5) — all allowlisted or
non-removing. The one operation whose effect on `pending` is stated nowhere is `full=true`'s
"discard": finding 1.
(5) *§8.5 crash window vs §11 and §6.2:* composes for same-host — §6.4 pins `indexing` false on a
dead pid, §11's reclaim row is the next scan, the timestamps discriminate, and surviving `pending`
rows serve `stale: true` through the window. The cross-host lock leaves `indexing` uncomputable and
uncomputed: finding 2. (The first-scan-crashed edge — no `last_scan_completed_at` key exists yet —
resolves one way only, missing-key-as-predating, and is not worth a sentence.)

### Findings

1. **[IMPROVEMENT] `refresh full=true` is specified in three words — "discards and rebuilds" — and
   one of its two plain readings is the document's own cautionary example.** §8.4 (line ~1015) and
   §9 say nothing else about the mechanics. Reading (a), discard-then-rebuild: drop the derived
   state (or the file) and reindex from scratch — which is, letter for letter, the defect §4.6
   convicts Amazon Q of (*"with the corpus unavailable throughout and no rollback if the rebuild
   fails"*), plus an emptying of `pending` on an occasion invariant 12's allowlist does not name,
   plus destruction of §12's cumulative counters, which the counters' own "answers: is this used at
   all" purpose cannot survive. Reading (b), treat-everything-as-changed: an ordinary scan with the
   §5.2 fast path and the stored-hash comparison bypassed, every admitted candidate reindexed
   through §4.6's per-file transactions, disposals and the walk-phase replacement proceeding as in
   any scan — which preserves per-file search availability, §6.4 crash-resume, the counters, and
   invariant 12 unmodified. The two readings converge on the same final corpus, which is why six
   rounds of corpus-definition checks never caught it; they diverge on availability during the
   minutes of rebuild, on what survives in `meta`, and on whether the invariant-12 test passes
   during a full refresh. One constraint prevents simply decreeing (b): the repair path §11 assigns
   to `reindex_required` (embed model/dim changed) *cannot* be incremental — `chunks_vec`'s
   dimension is fixed at `CREATE` time, so new-dim vectors cannot be inserted per file into an
   old-dim table, and recreating `chunks_vec` empty while chunks/FTS rows persist violates
   invariant 3 mid-rebuild. Fix: define the mechanics in §8.4 — recommend (b) as the ordinary
   behaviour, stated with the clause "meta identity, configuration and counters persist; search
   serves each file's old committed state until its transaction replaces it"; and one stated
   exception for the model-change repair, where the derived tables (`chunks`, `chunks_fts`,
   `chunks_vec` at the new dimension) and `files` rows are dropped together in one transaction
   before the scan — availability being moot there because §11 already has the KB refusing to
   serve. If (a) is chosen instead, invariant 12 and §12 need the corresponding exceptions stated,
   and §4.6's Amazon Q paragraph needs a sentence distinguishing the two cases.

2. **[NITPICK] `indexing`'s value under a cross-host lock is uncomputable and unstated, and §8.5's
   partials/totals rule keys off it.** §6.4 defines the same-host dead-pid case ("`indexing` reads
   false"); §6.2 says a cross-host lock is never auto-reclaimed and is reported for a human. But
   nothing says what `indexing` *reads* while a cross-host lock is held: one implementer ships
   `true` (lock present, liveness unrefutable), another ships `false` (pid probe is the only test
   in the text) — and under `false`, a live foreign indexer's running partials present as a crashed
   scan's, timestamps agreeing. One clause in §6.2 or §8.5: a cross-host lock reports
   `indexing: true` plus the lock's age, since liveness cannot be refuted — which also composes
   with §11's reclaim row being same-host-only.

VERDICT: NEEDS_CHANGES

## Round 8 — 2026-09-14

**Summary judgment.** Both round-7 fixes are genuinely applied and correctly reasoned — the
`full=true` paragraphs (§8.4 lines 1027–1048) are exactly the ordinary-scan reading with the
withdrawal recorded, §9 is aligned, and §6.2's cross-host rule composes cleanly with §8.5, §11 and
§8.4's `already_indexing`. The commissioned checks come back clean on every count but one: the
`reindex_required` exception is consistent with invariant 3 and **inconsistent with invariant 7**,
because the document never states when `meta.embed_model`/`embed_dim` are rewritten — and the two
candidate moments contradict different normative sentences, with observably different serving
behaviour during a repair. That is squarely the transmittal's own bar ("an implementer able to
resolve something two ways"), so I am saying so plainly rather than approving past it; it is a
two-clause fix, and findings 2–4 alone would not have withheld approval.

**Verification detail for the commissioned checks.**
- *`full=true` vs invariant 12:* consistent. The full scan's walk-phase replacement (every admitted
  candidate, since all are treated as changed) is the allowlisted wholesale replacement; the four
  disposals then drain it; end state empty. No fifth occasion appears.
- *vs §12's counters:* consistent — persistence is stated in the paragraph itself, and the
  withdrawal names the counter destruction as one of the rejected reading's three defects.
- *vs §6.4 crash-resume:* mechanically consistent; but the *full-ness* of a crashed full refresh
  does not resume, and nothing says so — finding 2.
- *vs §11's `reindex_required` row and invariant 3:* the one-transaction drop keeps invariant 3
  true at every commit boundary — vacuous after the drop, joint per-file inserts during the
  rebuild — and the dimension-fixed-at-CREATE reasoning is right (and DDL on the vec table inside a
  transaction is fine on any SQLite ≥ 3.7.11). Invariant 7 is the gap — finding 1.
- *vs §8.5:* consistent — during a full refresh `indexing: true` selects the running partials,
  afterwards totals; the skip counters recount correctly because every candidate is re-read.
- *Cross-host `indexing: true` vs §8.5:* composes — `true` selects the partials reading, which is
  what the single set of keys holds whether the foreign scan is live or dead, and §6.2 now states
  that uncertainty out loud. *Vs §11:* the reclaim row is same-host by §6.2's never-auto-reclaimed
  rule; the lock-held row covers the cross-host state. *Vs §8.4:* `refresh` reports
  `already_indexing` and `remove` refuses — mechanically consistent, but for a **stale** cross-host
  lock the composition is a permanent refusal with no named exit — finding 4. `lock_host` naming
  confirmed against §3.2.

### Findings

1. **[BLOCKER] The `reindex_required` repair never states when `meta.embed_model`/`embed_dim` flip
   to the configured values, and the two candidate moments fork observable behaviour — one violates
   invariant 7 for the duration of every repair, the other falsifies §8.4's and §11's own
   sentences.** §8.4's exception (lines 1042–1048) enumerates the drop transaction's contents —
   `chunks`, `chunks_fts`, `chunks_vec` recreated at the new dimension, `files` rows — and never
   mentions the `meta` identity keys; §11's refusal trigger is "embed model/dim in `meta` ≠
   configured", the only one defined. So: **flip at drop time**, and the refusal clears the moment
   the drop commits — the KB *serves* during the rebuild (empty groups growing to full), directly
   contradicting §8.4's "§11 already has the KB refusing to serve until the reindex completes" and
   turning §7.4's "no matches is a real answer" into misinformation for the window. **Flip at
   completion**, and §8.4/§11 stay literally true — but every vector inserted during the rebuild
   was produced by the configured model at the new dimension while `meta` still names the old one,
   so invariant 7's letter ("match **every** vector in `chunks_vec`", line 1229) is false
   throughout, in both fields. The document cannot shrug at that: §8.4's own exception paragraph
   justifies the one-transaction drop precisely by refusing to "violate invariant 3 for the
   duration", so mid-rebuild invariant truth is this document's *stated* standard, applied in the
   same breath. An implementer resolves the collision either by weakening the invariant-7 test
   coding-standards mandates or by flipping at drop and shipping the serving behaviour §8.4 says
   does not happen. Fix (recommended): **flip at completion, stated in §8.4** — "the repair scan's
   completing transaction rewrites `meta.embed_model`/`embed_dim`; until then §11's mismatch keeps
   the KB refusing to serve" — plus one exception clause in invariant 7: "except during a §8.4
   `reindex_required` repair, where `meta` keeps the old identity — and the KB refuses to serve —
   until the completing transaction rewrites it." Flip-at-completion is the right pick on its own
   merits, not only textual economy: a crash mid-repair leaves `meta` old, so the KB *keeps
   refusing*, and the next scan — every `files` row gone, every candidate changed-by-definition —
   completes the repair as an ordinary scan with no extra state, and no mismatched vector or
   misleading empty group is ever served. If flip-at-drop is chosen instead, §8.4's availability
   sentence and §11's row both need rewording to partial-serving-under-`indexing: true`.

2. **[IMPROVEMENT] A crashed `full` refresh silently abandons its remainder, and §6.4's "resumes
   rather than restarts" does not extend to it — unstated.** After a crash mid-full-refresh, the
   un-reindexed remainder's hashes still match their unchanged bytes, so the reclaiming scan finds
   nothing to do: the full refresh's *intent* — §5.2's clean-filter byte-exactness restoration, a
   changed `chunk_max_tokens`, healing — is silently unfulfilled for whatever fraction was not
   reached, and nothing can ever detect it. The surviving `pending` rows do flag the remainder
   `stale: true`, but only until the next walk-phase replacement erases them (finding no byte
   changes), which converts an honestly-flagged window into a silently mixed corpus — the exact
   silent-staleness class this document convicts Amazon Q of. Note the asymmetry that confirms the
   mechanism: the `reindex_required` variant is immune by construction, because the upfront drop of
   `files` rows makes any later scan complete the repair naturally. Fix: one honest sentence in
   §8.4's `full` paragraph (or §6.4): a full refresh interrupted by a crash does not resume as
   full — the remainder rejoins ordinary change detection, and the refresh must be re-invoked. The
   mechanical alternative — the walk-phase replacement unioning surviving `pending` rows in as
   forced-changed — would make resume real but breaks §7.5's reverted-file property ("replaces
   rather than appends"); if ever wanted, it belongs in §16 as a named deferral, not built silently.

3. **[NITPICK] During a full refresh every not-yet-reindexed result carries `stale: true`, and the
   tool description's gloss is systematically false for that window.** Under `full=true` the
   replacement puts the entire corpus in `pending` by decree rather than discovery, so §7.5's
   disjunct 1 flags every result for the minutes of rebuild — while §8.3's description says
   `stale: true` "describes a file that has changed since it was indexed", which is untrue of files
   whose bytes are identical. Conservative and transient, but this document's habit is to state
   such consequences ("stated because they are invisible otherwise"). One clause in §8.4's `full`
   paragraph: during a full refresh every not-yet-reindexed result reports `stale: true`; the
   accurate frame is the description's gloss on `false` ("no evidence of change"), not a claim the
   file changed.

4. **[NITPICK] A stale cross-host lock composes into a KB nothing can manage, and "for a human to
   clear" names no procedure.** Under the (correct) conservative rule, `refresh` reports
   `already_indexing` forever, `remove` refuses under the same lock (§8.4 lines 1019–1021),
   auto-reclaim is same-host-only (§6.2), and no surface provides a clearing verb — §9 has no
   `unlock`, and no SQL is documented. This is ordinary rather than exotic: an indexer run inside a
   devcontainer records the container's hostname into `lock_host`, so one crash there leaves a lock
   the host session can never clear through any tool this design ships. One sentence in §6.2
   naming the procedure — delete the three `lock_*` keys with `sqlite3`, or a `refresh
   --force-unlock` that refuses when the lock is same-host-live — either is fine; unstated is not,
   since the design itself assigns the human the task.

VERDICT: NEEDS_CHANGES

## Round 9 — 2026-09-14

**Summary judgment.** All four round-8 fixes are genuinely applied — counted (4 of 4) and verified
in place — and the commissioned checks pass on every surface but two. One of the two is exactly the
cascade the transmittal predicted, though it comes from round 8's own fix rather than from the
`--force-unlock` addition: the `reindex_required` repair now has flip-at-completion semantics bound
to "the repair scan's completing transaction" while **nothing says which scans are repair scans**,
and the two available readings fork observable recovery behaviour — under one of them, §8.4's own
crash-self-correction sentence is false and a crashed repair leaves a KB refusing to serve forever
behind a fully rebuilt corpus. That is one to two sentences to fix, but it is squarely inside the
bar the transmittal set ("changes behaviour or leaves an implementer able to resolve it two ways"),
so I am withholding on it alone; findings 2 and 3 would have been approval-with-observations.

**Verification detail for the commissioned checks.**
- *Fix 1 (flip timing):* applied in the recommended form — §8.4 lines ~1088–1099 carry the
  completing-transaction rule, both halves of the reasoning (serving-empty-groups-as-misinformation;
  crash-self-correction), and invariant 7 (lines ~1285–1288) carries the exception verbatim plus the
  stated-rather-than-weakened sentence. Composes with §11's mismatch row: during the rebuild `meta`
  names the old identity ≠ configured, so the refusal stands with no new trigger needed. The residue
  is finding 1.
- *Fix 2 (crashed full refresh):* applied at §8.4 lines ~1058–1069 with the mechanism (remainder's
  hashes still match), the honest-window-to-silently-mixed-corpus consequence, and the
  `reindex_required` immunity asymmetry; §16 item 8 carries the union-surviving-`pending`
  alternative with the §7.5 replaces-rather-than-appends property it would break. Consistent on all
  sides.
- *Fix 3 (`stale: true` during full refresh):* applied at lines ~1051–1056, framed off the
  description's gloss on `false` as recommended.
- *Fix 4 (stale cross-host lock):* applied at §6.2 lines ~687–696 — the three-key delete, the
  same-host-live refusal, the devcontainer motivating case — and §9's synopsis (line ~1193) and
  prose (~1202–1205) agree with it and with §8.2's exception paragraph.
- *`--force-unlock` against §8.2 / §8.4 / §6.2 / §11 / §9:* the one-directional-parity paragraph
  (§8.2 ~857–860) is internally coherent and names the same single exception §9 names; `remove`'s
  and `refresh`'s `already_indexing` refusals compose with the exit (the permanent-refusal loop
  round 8 flagged now terminates at the CLI); §11's lock-held row is unaffected. Two seams found,
  neither a cascade of the kind rounds 3–5 produced: §8.2 and §9 characterize the parity claim's
  *scope* differently, with `search` falling in the gap (finding 2), and §11's reclaim row still
  lacks §6.2's same-host restriction (finding 3 — pre-existing wording, surfaced by this check
  rather than created by the fix).
- *§16 renumbering:* verified by grep — every internal reference is of the form "open question 1
  (§16)" or an unnumbered "named in §16"; no numeric §16-item reference exists anywhere in the
  document, so inserting item 8 broke nothing.

### Findings

1. **[BLOCKER] The `reindex_required` repair has no named trigger, and the two available readings
   fork observable recovery behaviour — §8.4's own crash-recovery and immunity sentences are true
   under exactly one of them.** Round 8's fix bound the `meta` rewrite to "the repair scan's
   completing transaction" (§8.4 ~1088) without ever saying *which invocations are repair scans*.
   The exception paragraph (~1080–1086) sits inside the `full=true` discussion, framed as an
   exception to `full=true`'s mechanics — which reads as: the repair is a mode of `refresh
   full=true` (reading A). But the crash paragraph (~1096–1099) says "the next **scan** — every
   `files` row already gone, so every candidate changed by definition — finishes the repair as an
   ordinary scan with no extra state", and its parenthetical only does any work if that next scan
   is an *ordinary* refresh relying on changed-by-definition (reading B); the immunity sentence
   (~1064–1066, "makes **any later scan** complete the repair naturally") asserts B a second time.
   Trace reading A through the crash §8.4 calls self-correcting: the next plain `refresh` rebuilds
   the entire corpus — no `files` rows, so every candidate is changed; the configured encoder's
   vectors insert cleanly into the already-recreated new-dimension table — but **nothing rewrites
   `meta`**, because the rewrite belongs exclusively to the repair scan, so the KB refuses to serve
   *forever* behind a fully consistent corpus, until someone reinvokes `full=true`, which, being
   the repair variant, drops the just-rebuilt corpus and rebuilds it a second time. Reading A is
   also odd on the no-crash path: a plain `refresh` on a mismatched KB runs ordinary change
   detection, finds nothing changed, and no-ops "successfully" while `reindex_required` persists,
   with nothing telling the caller that `full=true` is the exit. Under reading B both sentences
   are literally true and any scan heals the KB. Two implementers ship those two behaviours; the
   document asserts B's consequences while its structure suggests A — prose contradicting the
   mechanism beside it, this corpus's named class. Fix, one to two sentences beside the
   flip-at-completion paragraph, in the direction the text already believes: "**A scan that begins
   while `meta.embed_model`/`embed_dim` differ from the configured values is the repair variant,
   however invoked** — plain `refresh`, `full=true`, or `refresh(None)` reaching that KB. The
   upfront drop happens (vacuously when the derived tables are already gone), the scan embeds with
   the configured model, and its completing transaction rewrites the keys. The drop from a plain
   `refresh` costs nothing observable, because §11 has the KB refusing to serve throughout the
   mismatch; `add` cannot encounter the state, since a fresh KB is seeded from config (§10)." If
   reading A is chosen instead, the crash paragraph, the immunity sentence and §11's
   `reindex_required` row all need rewording, and the redundant second rebuild needs stating as a
   cost — B is strictly simpler. For the audit trail: round 8's own recommended wording ("completes
   the repair as an ordinary scan with no extra state") is where the ambiguity entered; the fix
   applied it faithfully. The cascade is the recommendation's, not the application's.

2. **[IMPROVEMENT] §8.2 and §9 characterize the parity claim's scope differently, and under
   §8.2's letter the claim is false — `search` has no CLI form.** §8.2 (~855): "Every **agent**
   operation has CLI parity (§9)", directly above a table whose operations include `search` and
   `poll status`; §9 (~1204): "§8.2's parity claim is stated over the **management verbs**". §9's
   command list — `list`, `add`, `remove`, `refresh`, `status` — contains no `search`, so under
   §8.2's wording an implementer either ships a CLI search the design never specifies or reads the
   sentence as aspirational. §9's characterization is plainly the intended one: §8.2's own opening
   enumerates "create, delete, reindex, poll". Fix in §8.2: "Every agent **management** operation
   (create, delete, reindex, poll) has CLI parity (§9); `search` is deliberately MCP-only — the CLI
   is a management surface, not a retrieval one" — or add a CLI `search`, but say which. This is
   the seam the transmittal asked me to check; it is the only one the narrowing left, and only a
   convenience surface forks on it, so it does not withhold approval on its own.

3. **[IMPROVEMENT] §11's reclaim row states the pid-liveness reclaim without §6.2's same-host
   restriction, and its letter licenses the auto-reclaim §6.2 forbids.** Row: "indexer died
   holding the lock → next scan reclaims after a liveness check on the pid" — no host qualifier,
   while §6.2 rules a cross-host lock "**never auto-reclaimed** — pid liveness is meaningless
   across hosts". A local probe of a foreign pid can collide with an unrelated live process, or —
   worse — find the number dead and reclaim a lock whose foreign holder is alive: two indexers on
   one KB over a shared filesystem, the state invariant 8 exists to forbid. The table is a
   synopsis, but this document's own §3.2 regime treats a synopsis contradicting the normative
   prose as a defect in one of the two places. One clause in the row: "…after a liveness check on
   the pid (**same host only, §6.2**; a cross-host lock is never auto-reclaimed — it reports
   `indexing: true` with the lock's age, and the exit is `refresh --force-unlock`)". Pre-existing
   wording surfaced by the commissioned check, not a cascade of the round-8 fixes; does not
   withhold approval on its own.

VERDICT: NEEDS_CHANGES

## Round 10 — 2026-09-14

**Summary judgment.** All three round-9 fixes are genuinely applied — counted (3 of 3) and verified
in place — and the state-based repair trigger is single-valued at every point that matters: an
implementer building from §8.4's rule ("however it was invoked … a property of the store's state,
not of the verb") ships exactly one recovery behaviour, and every touchpoint the transmittal named
composes with it. What remains is residue, not mechanics: two sentences in §8.4's own rationale
block still narrate the reading-B recovery that round 9 refuted — the transmittal's claim that the
crash-self-correction and immunity sentences "should now both be literally true" is **not met**,
because both restate the withdrawn mechanism — but the normative rule two paragraphs above them is
categorical, so no implementer resolves the mechanics two ways. Per the transmittal's stated bar,
these are non-withholding observations with exact wording supplied, and the document ships.

**Verification of the three round-9 fixes.**
- *Fix 1 (state-based trigger):* applied at §8.4 (~1091–1097) in the recommended reading-B wording,
  strengthened by "The repair is a property of the store's state, not of the verb." All four
  commissioned clauses present: the three invocation routes, the vacuous-drop parenthetical, the
  no-observable-cost clause, and the `add`-cannot-meet-it clause. The rejected reading is recorded
  (~1103–1110) with all three of its forks — refusing-forever, the second rebuild, and the
  successful no-op with `reindex_required` persisting.
- *Fix 2 (§8.2 parity scope):* applied (~855–858) — "management operation — create, delete,
  reindex, poll", `search` stated MCP-only with the management-surface reason. §8.2's narrowed
  claim, its one-directional-exception paragraph (`--force-unlock`), and §9's "stated over the
  management verbs" (~1223–1225) now all say the same thing; the §8.2 table remains the MCP
  surface, not the parity claim, so `search`/`status` appearing there contradicts nothing.
- *Fix 3 (§11 reclaim row):* applied (~1260) — "same host only (§6.2)", the never-auto-reclaimed
  rule, `indexing: true` with the lock's age, and the `--force-unlock` exit, all matching §6.2's
  normative prose.

**Composition of the state-based trigger, per the commissioned list.**
- *§11's `reindex_required` row:* composes — the refusal is keyed on the same state that defines
  the repair variant, so it stands through the rebuild (and through a crash gap) with no new
  trigger, and clears exactly when the completing transaction rewrites the keys. Under the state
  rule any `refresh` is the exit, so the row not naming one is now harmless where under reading A
  it was the no-op trap.
- *Invariant 7's exception:* composes, and the state rule is what makes it composable — "during a
  §8.4 `reindex_required` repair … until the completing transaction rewrites it" reads naturally
  as the whole mismatch duration, which correctly includes the §6.4 crash gap (where new-identity
  vectors sit in `chunks_vec` while `meta` names the old identity and the KB refuses). A
  duration-of-the-process reading would go red in that gap; the state definition forecloses it.
- *§10's seeding:* the *mechanism* composes (`add` seeds from config, so a fresh KB can never
  begin mismatched) but the citation dangles — finding 2.
- *§8.5 during a repair:* composes — lock held → `indexing: true` → running partials; after a
  crash the timestamp discriminator applies unchanged; `files_indexed` climbing from zero after
  the drop is consistent with §8.5's one-field-one-meaning rule. §11's refusal is the search
  path's; `status` answering is what makes `reindex_required` visible at all — finding 3 records
  the field-list gap.
- *§8.4's crash-self-correction and immunity sentences:* the guarantees are true; the sentences
  are not — finding 1.

### Findings

1. **[IMPROVEMENT — non-withholding] §8.4's crash paragraph and immunity sentence both restate the
   reading-B mechanism round 9 refuted, and neither is literally true under the state rule as
   applied.** Three clauses, all in rationale prose beside a categorical rule, so no mechanics
   fork — but this is the corpus's named class (a corrected passage restating the withdrawn lemma
   beside the correction), and the transmittal's "should now both be literally true" is the claim
   to audit, not the phrasing. (a) Crash paragraph (~1116–1119): *"the next scan — every `files`
   row already gone, so every candidate changed by definition — finishes the repair as an ordinary
   scan with no extra state."* False twice for a crash at 40%: the done fraction's `files` rows
   **exist** at scan start (§4.6 inserted them per file), and the next scan is **not** an ordinary
   scan — by the state rule's own letter it *is* the repair variant, and its unconditional upfront
   drop is what removes those rows. (b) Immunity sentence (~1067–1069): *"immune by construction,
   because its upfront drop of every `files` row makes any later scan complete the repair
   naturally"* — attributes the immunity to exactly the mechanism round 9's reading-A trace proved
   insufficient (drop without the state trigger = rebuilt corpus behind a KB refusing forever,
   because nothing rewrites `meta`). The operative cause is the state: `meta` still mismatched, so
   any later scan begins as the repair variant. (c) The "(vacuously if the derived tables are
   already gone)" condition cannot arise — the drop transaction itself recreates the tables, so a
   crash-recovery re-drop is always non-vacuous, and it **discards the crashed run's correct
   partial work**: recovery redoes the corpus rather than resuming the remainder. That is the one
   real cost the state rule introduces, currently unstated, and it scopes the adjacent "costs
   nothing observable" clause — true of served state (the KB refuses throughout either way), not
   of wall time. Suggested wording, replacing (a): *"the next scan — beginning under the mismatch —
   is itself the repair variant, however invoked: its upfront drop removes the crashed run's
   partial work (a redo of the corpus, not a resume — the cost of having no repair checkpoint,
   accepted for the same no-extra-state reason as §6.4), and its completing transaction rewrites
   the keys, having never served a mismatched vector or a misleading empty group."* Replacing (b):
   *"immune by construction: `meta` still names the old identity, so any later scan begins under
   the mismatch and is the repair variant (§8.4), which completes the repair whole."* And drop or
   correct the vacuous-drop parenthetical. For the audit trail: clause (c)'s impossible condition
   entered in round 9's own recommended wording, faithfully applied — the cascade is again the
   recommendation's, not the application's.

2. **[IMPROVEMENT — non-withholding] §8.4's "a fresh KB seeds both keys from config (§10)" cites
   §10 for a fact §10 never states.** §10's seeding sentence names `chunk_max_tokens`, `rrf_k`,
   `fusion_depth` and `max_file_bytes` only; no sentence anywhere states that `embed_model`/
   `embed_dim` are written to `meta` at creation, though §3.2 lists the keys and the `add`-cannot-
   meet-the-state clause rests on it. One sentence in §10: *"`embed_model` and `embed_dim` are
   likewise recorded at creation from the configured encoder identity — but unlike the four tuning
   keys, a later config change is not silently absorbed per-KB: divergence puts the KB into §11's
   `reindex_required`."* The contrast is worth stating because §10's stated purpose for per-KB
   seeding ("changing a global default does not silently invalidate an existing index") is
   deliberately inverted for these two keys.

3. **[NITPICK] §8.5's field list has no slot for the degraded-state reports §11 assigns to
   `status`.** §11 says `status` reports `root_missing`, `reindex_required`, and (per §6.2) a
   cross-host lock's age — none appears in §8.5's "Returns per KB" enumeration, which §8.4 also
   makes the shape of `add`/`refresh` returns. No fork (§11 is unambiguous that they are
   reported), but the list presents itself as the response schema. One field (`state: ok |
   reindex_required | root_missing`, plus the lock-age note) or one sentence deferring to §11's
   rows closes it.

If the researcher folds finding 1's redo-not-resume cost anywhere, §16 item 8 is the natural home
alongside the crashed-full-refresh deferral, since the two are the same trade one level apart.

VERDICT: APPROVED

## Round 11 — 2026-09-14

**Summary judgment.** The seven operator-directed changes land coherently at most of their
touchpoints: the registry's naming/traversal/rename story is sound and consistently told, the
snippet property survives every section that touches it, the `list` projection claim is true as
stated, and the state machinery composes correctly with §6.2's cross-host lock and §8.5's
partials rule at every point I traced but two. But the predicted class recurred at three seams,
each squarely over the brief's bar: `add`'s own paragraph states two opposite orderings and two
other sections assert consequences only the rejected ordering produces; the three-disposal regime
left two "four disposals" behind — the third recurrence of this exact count-slip in this
document's history; and the new `files_remaining` null rule mandates a distinction the schema
gives the serving process no way to draw.

**Verification detail for the commissioned checks.**
- *The projection claim (change 3):* **true.** `list`'s five fields (`name`, `description`,
  `state`, `files_indexed`, `files_remaining`) are a strict subset of `status`'s (§8.5 line 1320:
  "Returns per KB everything `list` returns … plus the diagnostic fields"), each defined once —
  the enum, the precedence, the `null` rule and `files_indexed`'s one-meaning rule are stated in
  §8.5 and referenced, never restated. The absent-DB case (`files_indexed: 0` with no file to
  read) is specified in §11 line 1474. The rejected "avoids opening KB files" mechanism is
  correctly absent from §8.5 ("Both calls open every knowledge-base database") — but it survives
  in §3.1a (finding 7a).
- *The snippet property (change 7):* **not contradicted anywhere.** Traced through §3.2's
  `chunks.text` comment (verbatim, no prefix), §4.3 (prefix at embed time only, FTS path as its
  own column), invariant 16 (whole-line prefix, `start_line`/`end_line` describe the snippet),
  §8.7 (overflow drops groups whole, never trims snippets), and the §8.3 tool description. The
  truncation rule preserves the property (fewer whole lines, `end_line` reduced); the single
  over-long-line exception is stated in both §8.3 and invariant 16. Two byte-level
  under-definitions remain, neither a contradiction (finding 11).
- *Rename-detection removal (change 6):* vocabulary is cleanly gone from §5.2 (`R` entries read
  as deletion + candidate), §5.5, §8.4 ("rename in this document means only this"), and §15
  (costed rejection; arithmetic checks out — 200/1,000/5,000 files × ~3 chunks × 5.45 ms = 3.3 s /
  16 s / 82 s). The three disposal *enumerations* (§3.2 lines 206–211, §7.5 lines 863–865,
  invariant 12 line 1537) all say three. The transmittal's check verified the enumerations; the
  *count references* were not swept, and two say four (finding 2).
- *Registry interactions (change 1):* deletion ordering, orphan semantics, lower-casing,
  `rename`, invariant 14 and the §15 rejections all agree with each other. The `add` ordering
  does not agree with itself (finding 1), and two rationale sentences still assert the
  pre-change-5 world (finding 7b).
- *State/`files_remaining` interactions (change 4):* §6.2's cross-host `state: "indexing"` rule,
  §8.5's no-separate-boolean rule, the precedence chain, and the missing-file → `indexing`
  transition mid-repair (once the file exists with current-config `meta`, neither
  `reindex_required` cause holds, so partial results during the rebuild correctly report
  `indexing`) all compose. §11's reclaim row uses the removed boolean vocabulary (finding 4); the
  null rule has no persisted representation (finding 3); and the enum cannot express one §11
  condition the new machinery must now present (finding 5).
- *Narration sweep (change 2):* two survivors of the chronological class remain (finding 10).
  The K-index is gapless and every K marker resolves to its stated section; the seven tools agree
  across §2/§8.2/§8.3/§8.4/§8.5; the CLI's six commands include `rename` and exclude `search`.

### Findings

1. **[BLOCKER] `add`'s paragraph states two opposite orderings, and two other sections assert
   consequences only the rejected one produces.** §8.4 line 1121: *"`add` generates the KB's id,
   inserts the registry row, creates `knowledge/<id>.db`, writes its `meta`, spawns the indexer,
   and returns"* — registry row **second**. The next sentence (1122–1124): *"the registry row is
   written **last**, after the database exists, so an interrupted `add` leaves an unreferenced
   file rather than a name resolving to nothing"* — registry row **last**. These are not one rule
   sloppily phrased: each ordering has other sections betting on it. Registry-**last** is asserted
   by §3.1a (orphans are "the residue of an interrupted `add`/`remove`"), §11's orphan row
   (line 1475), and invariant 15. Registry-**first** is what §11's absent-DB row requires —
   *"Absence is the ordinary state of a KB whose `add` was interrupted"* (line 1474) — and §8.4's
   no-database-file bullet repeats it (lines 1208–1210: *"the ordinary path for a KB whose `add`
   was interrupted"*): under registry-last, an interrupted `add` can **never** produce
   row-without-file — it produces file-without-row, the orphan. Two implementers ship different
   crash residues (orphan vs dangling name), and whichever ships, two normative sections are
   false. Worth noting before picking: **change 5 moved the calculus.** A dangling name is now a
   self-healing empty KB (*"recoverable without operator involvement"*, §11), while an orphan
   leaks disk indefinitely with deletion an open question (§16 item 10) and a retried `add` mints
   a fresh id, so the orphan is permanent. Registry-first for `add` therefore composes better with
   the machinery this revision built — and it does *not* break the `remove` ordering, which
   change 5 actually strengthens (see finding 7b). But either ordering is shippable; the document
   must say exactly one, in the enumeration, the bold sentence, §11's absent-row rationale, and
   §8.4's bullet together. If registry-last is kept, the absent-DB state's named causes reduce to
   "file deleted out from under the registry" and the two "interrupted `add`" clauses must go.

2. **[BLOCKER] Two "four disposals" survive against three enumerations that say three — the
   third recurrence of this exact count-slip, in the same invariant as rounds 5 and 6.**
   Invariant 12's closing allowlist (line 1542): *"any occasion other than those four disposals
   or the walk phase's wholesale replacement"* — while the same invariant's own enumeration five
   lines up (1537) lists three (reindex, deletion, recorded text-detection skip), and §7.5
   (line 865) says *"a fourth outcome would be a defect"*. And §8.4's `full=true` paragraph
   (line 1155): *"the walk-phase `pending` replacement, the four disposals and every invariant
   proceed exactly as in any other scan."* Not merely cosmetic: a test author reading "those four
   disposals" hunts for the fourth, and the nearest candidate in view is the invariant's own
   `unreadable`-skip exception — reading *that* as the fourth disposal makes it a row-deleting
   occasion, which contradicts the exception's own "correctly remain". Fix: "four" → "three" in
   both places. Process note, since this file is the running record of it: the transmittal's
   audit — "disposal enumerations all say three" — verified the *enumerations*, and the slip
   lives in the *count references*; the claim to audit was "every statement of the disposal
   count", which is the enumerate-the-claim-not-the-phrasing lesson recurring inside its third
   fix.

3. **[BLOCKER] `files_remaining`'s null-during-walk rule mandates a distinction the schema gives
   the serving process no way to draw.** §8.5 (lines 1289–1293): `null`, not `0`, while the walk
   phase is still running, and *"the distinction is load-bearing"* — but the service (a separate
   process; under a cross-host lock, a separate *machine*, where §6.2 makes exactly this report
   mandatory) must compute it from the KB database, and nothing persisted marks walk-phase
   completion. During a running scan's walk phase, `pending` still holds the *previous* scan's
   contents — usually empty — so `COUNT(pending)` reports a stale count, and the one candidate
   discriminator in the schema, `pending.noticed_at` against `last_scan_started_at`, fails on
   exactly the empty table: post-replacement-with-no-changes (`0`, "nothing left") and
   not-yet-replaced (`null`, "not yet counted") are byte-identical database states. This is
   round-1 finding 6's no-persisted-representation class recurring on the field that fix
   introduced. Fix is one key plus one rule: the walk phase's wholesale-replacement transaction
   also writes `last_walk_completed_at` (added to §3.2's authoritative list, per its own regime);
   `files_remaining` is `COUNT(pending)` iff the lock is held **and**
   `last_walk_completed_at ≥ last_scan_started_at`, else `null`. The crash case already resolves
   ("`null` also means 'no scan running'"); only the running-scan window is unspecified.

4. **[IMPROVEMENT — non-withholding] §11's reclaim row reports a field §8.5 says does not
   exist.** Line 1479: a cross-host lock *"reports `indexing: true` with the lock's age"* — the
   separate `indexing` boolean this revision removed. §8.5 is categorical (*"There is no separate
   `indexing` boolean"*, line 1332) and §6.2 states the correct form (*"`status` reports
   `state: "indexing"`, plus the lock's age"*), so the mechanics do not truly fork, but the
   removed vocabulary standing in a normative table row is the recreate-the-parallel-field
   invitation §8.5 exists to forbid. Fix the row: *"it reports `state: "indexing"` with the
   lock's age"*.

5. **[IMPROVEMENT — non-withholding] The `state` enum cannot express §11's unreadable-database
   condition, and "every group carries the same `state`" cannot hold for error groups.** §11's
   first row (line 1473) specifies the *search* presentation (an `error` group) for a KB whose
   file is present but unreadable — but `list` and `status` must present that KB too (the
   registry says it exists), and the enum (`ok | indexing | reindex_required | root_missing`)
   has no value for it: one implementer ships `reindex_required` (false — `refresh` against a
   corrupt file does not obviously rebuild it), another invents an undocumented state. Related:
   §8.3 line 1032, *"**Every group** carries the same `state` and `files_remaining` as `list`"*,
   is unsatisfiable for the unknown-name error group (no KB exists to have a state) and for the
   unreadable-DB error group (the state's inputs are unreadable). Fix together: add an `error`
   (or `unreadable`) state above `root_missing` in the precedence, name it in §11's first row for
   `list`/`status`, and scope §8.3's sentence to non-error groups (stating whether §8.7's stub
   groups carry it — they can, and it is useful there).

6. **[IMPROVEMENT — non-withholding] Invariant 11's first sentence is categorically false
   against §8.6's own text.** Invariant 11: *"**No caller-supplied string is ever interpolated
   into a filesystem path.**"* §8.6: `add`'s `path` *"is the only caller-supplied string with any
   path semantics at all"* — a caller-supplied string that becomes `root_path`, is walked, and
   prefixes every result-derived absolute path. The invariant's second sentence shows the
   intended scope (knowledge database paths); the first sentence universalises it into a claim
   the design's own surface refutes, and an invariant test written from the letter has no honest
   implementation. Fix: *"No caller-supplied string is ever interpolated into a path under
   `.zikaron/`; the corpus root (§8.6) is the one caller-supplied path in the system, and it is
   validated, never combined with a name."*

7. **[IMPROVEMENT — non-withholding] Two §3.1a rationale sentences still assert pre-revision
   worlds.** (a) Line 139, the registry's benefits list: *"**Listing is one indexed query**
   rather than opening every KB file and reading its `meta`"* — §8.5 says the opposite of the
   shipped `list` (*"Both calls open every knowledge-base database"*; *"The split is about
   response size, not about data access"*), and the transmittal records that this exact
   mechanism claim was withdrawn under operator pushback. What the registry actually buys here
   is narrower and true: name→id resolution and `search`'s call-time name validation (§8.3) read
   the registry alone, touching no KB file. Reword to that. (b) Lines 144–147, the `remove`
   ordering's rationale: a dangling registry row *"would be a KB that appears to exist and
   cannot be opened"* — under change 5 that state is defined as an **empty KB that serves empty
   groups and rebuilds on `refresh`** (§11, invariant 15), so "cannot be opened" is now false.
   The true post-change-5 hazard is worse and argues the same ordering *harder*: a dangling name
   after an interrupted `remove` would silently **resurrect** as an empty KB on the next
   `refresh`/`refresh(None)`, rebuilding the corpus the caller had just asked to destroy. State
   that instead.

8. **[IMPROVEMENT — non-withholding] Search over a `root_missing` KB is two-readable.** §11
   retains the index (*"the index is retained, not deleted"*), the precedence rule ranks
   `root_missing` first, and groups now carry `state` — but nothing says whether a search names
   that KB serves the retained chunks (every result's `stat` fails → all `stale: true`,
   disjunct 2) or answers an empty group with `state: "root_missing"`. Two implementers ship
   different result sets. The design's own §5.6 reasoning (*"a result pointing at a file the
   agent cannot `Read` is worse than no result"*) argues the empty group, with the retained index
   ready for the root's return; either way, say which, and add `root_missing` to the tool
   description's state gloss, which currently explains `reindex_required` and `indexing` only.

9. **[NITPICK] §8.2's two enumerations omit `rename`.** Lines 902 and 904 both read "create,
   delete, reindex, poll" while the table five lines down, §8.4, §9 and §2 all carry `rename` —
   the enumeration predates the verb this revision added. Both parity claims should include it
   (`rename` has CLI parity, so the claim stays true once stated).

10. **[NITPICK] Two chronological-narration survivors of the change-2 sweep.** §5.5
    (lines 665–667): *"Both were unhandled when text detection moved to read time, which left
    `pending` non-empty at scan completion…"* — drafting history; restate forward
    ("Both must be stated: text detection runs at read time (§4.1), so without them `pending`
    would be non-empty at scan completion for any corpus containing an image"). §16 item 9:
    *"the same machinery `pending` needed four review rounds to get right"* — review-process
    chronology; "the same class of disposal machinery `pending` shows is hard to specify
    correctly" carries the warning without the trace.

11. **[NITPICK] Two byte-level under-definitions around the snippet property, neither a
    contradiction.** (a) `knowledge_snippet_max_chars` never names its unit — and this corpus's
    own measured lesson (FINDINGS current-state item 5; the M14/M16 gist-bound history) is that
    "characters" is precisely the ambiguous word; one clause in §10 or §8.7 naming code points
    (or UTF-16 units, but say which) closes it. Behaviour barely forks — the 24,000-byte response
    cap is enforced by group-dropping regardless — but where the mid-line cut lands differs.
    (b) "Byte-identical to lines `start_line`–`end_line`" leaves the final line terminator
    two-readable (and the no-trailing-newline last line); one sentence — the snippet includes
    each line's terminator except any absent from the file itself — makes the round-trip test
    writable.

12. **[NITPICK] §8.5's field list omits `last_scan_started_at`, which its own partials/totals
    discriminator needs caller-side.** Lines 1341–1345 tell the caller crashed partials are
    *"distinguishable by `last_scan_completed_at` predating `last_scan_started_at`"*, but the
    "Returns per KB" enumeration carries only `last_scan_completed_at` — the discriminator's
    other operand is not in the response. Add it to the list.

VERDICT: NEEDS_CHANGES

## Round 12 — 2026-09-14

**Summary judgment.** All 12 round-11 findings are genuinely applied — counted (12 of 12) and
verified in place — and the three propagation clusters the transmittal flagged come back clean at
every mechanics-bearing site: the registry-first ordering is stated once in §8.4 and asserted
consistently by §2, §3.1a, both §11 rows, §8.4's repair bullet and invariant 15, with both reverse
orderings costed correctly; a grep over every statement of the disposal *count* (not only the
enumerations) finds three everywhere, the sole "fourth" being §7.5's correct "a fourth outcome would
be a defect"; and the `last_walk_completed_at` rule is written once, keyed in §3.2, and resolves
one-valued in every window I traced — running walk, post-walk index phase, crash (dead pid → lock
not held → `null`), cross-host lock, and first-scan missing key. Nothing an implementer builds from
this text forks. What remains is letter-level residue at four sites, none of it mechanics, plus one
transmittal-versus-text discrepancy worth recording for the audit trail.

**Verification detail.**
- *Cluster 1 (ordering):* §8.4's enumeration ("inserts and commits the registry row, then creates")
  and its same-ordering paragraph agree; §3.1a's rationale now argues resurrection for the `remove`
  reversal and the withdrawn "listing is one indexed query" claim survives only in its corrected,
  explicitly-not-about-`list` form (line 140); §11's orphan row attributes orphans to interrupted
  `remove` only; §11's absent-DB row and §8.4's no-file repair bullet both require registry-first
  and now get it. The permanent-orphan and silent-resurrection costings are both mechanically
  correct (retried `add` mints a fresh uuid4; a dangling name is §11's empty KB, which
  `refresh`/`refresh(None)` rebuilds).
- *Cluster 2 (`error`):* present in the enum table with a correct `refresh`-does-not-repair
  distinction, first in the precedence, in §11's unreadable row for all three surfaces, in §8.3's
  scoped carries-state sentence with the `unknown_knowledge_base` exception and the stub statement,
  and in §8.5's list description gloss. Invariant 10's four-form enumeration covers errored and
  stub groups. `files_remaining` for an unreadable KB resolves one way (`lock is held` cannot be
  established → `null`).
- *Cluster 3 (`last_walk_completed_at`):* in §3.2's scan-outcome list; write moment stated in §8.5
  ("the walk phase's wholesale-replacement transaction therefore also writes") and consistent with
  §7.5's transaction description, which it extends without contradiction; §6.3 contains nothing
  asserting the pre-fix world; the corrected rationale ("`pending` still holds the *previous*
  scan's contents") now matches §7.5's replacement semantics. The reclaimed-scan case
  (old timestamp < new `last_scan_started_at` → `null`) and §8.5's own list-description gloss
  ("started and has not yet finished working out what changed") both agree with the rule.
- *Remaining items:* 2, 4, 6, 7, 9, 10, 11, 12 all verified in place as transmitted; invariant 11's
  narrowed form is consistent with §8.6's "only caller-supplied string with any path semantics";
  the snippet unit names Unicode code points with the mid-line-cut scope correctly bounded; the
  terminator rule makes invariant 16's round-trip test writable.

### Findings

1. **[IMPROVEMENT — non-withholding] §8.3's search description still glosses only two of the four
   states a search group can now carry, and round-11 finding 8's gloss fix landed in the other
   tool's description.** The search description (§8.3): *"unless its `state` says otherwise:
   `reindex_required` means it is not built yet, and `indexing` means the answer is partial while a
   scan finishes"* — exactly the two-state gloss round-11 finding 8 described as the defect. The
   fix's gloss half landed in §8.5's *list* description, which now covers all five states — but the
   agent that meets an empty group with `state: "root_missing"` or `"error"` is reading the search
   response, and nothing guarantees it ever called `list`. No mechanics fork (the state table and
   §11 are categorical; the descriptions ship verbatim as written), but the claim behind the
   finding — the reading agent can interpret the state it is looking at — is met only on the
   surface the finding did not name. One clause in §8.3's description: *"…while a scan finishes;
   `root_missing` and `error` mean the corpus cannot answer at all — its directory is gone, or its
   index is unreadable."* For the audit trail: this is the audit-the-phrasing shape again — the
   transmittal's "added to the tool description's gloss" is true of *a* tool description, and the
   round-11 text pointed at the other one.

2. **[NITPICK] §8.7's stub enumeration omits the two fields §8.3 says stubs carry.** §8.7:
   *"a stub group carrying `dropped: true` with the KB's name and description"*; §8.3: *"§8.7's
   `dropped: true` stubs do carry both [`state` and `files_remaining`], where they remain useful."*
   No fork — §8.3 is categorical and §8.7 states no "only" — but two field lists for one response
   object is the defect-in-one-of-two-places shape §3.2's regime names. Add `state` and
   `files_remaining` to §8.7's sentence.

3. **[NITPICK] §8.5's "What `list` omits" enumeration lacks `last_scan_started_at`** — the field
   round-11 fix 12 added to the Returns list. The omits list still ends "…and
   `last_scan_completed_at`", asserting the pre-fix response shape. No fork (`list`'s five fields
   are defined positively), but it is cluster 3's predicted neighbour, one word to fix.

4. **[NITPICK] §16 item 10's deciding question still includes `add`.** *"how often an interrupted
   `add`/`remove` actually happens"* — under the settled registry-first ordering an interrupted
   `add` cannot create an orphan (§11's orphan row says exactly this), so the orphan-sweep question
   turns on interrupted `remove` alone. Drop "`add`/"; the item's own first sentence ("after a
   botched `remove`") already has it right.

5. **[NITPICK] §8.4's stated ordering rule promises more than its own `remove` bullet delivers,
   and §3.1a echoes the overreach.** §8.4: *"an interrupted operation should leave the state the
   system can recover from by itself"* — true of the `add` bullet, contradicted two lines later by
   the orphan that *"leaks disk until someone clears it"*; §3.1a's *"makes every interrupted case
   recoverable"* is the same claim. The rule the bullets actually apply is: prefer the self-healing
   state where one exists, and the lesser harm where none does. One clause in each place; the
   mechanics and the ordering decision are untouched.

VERDICT: APPROVED
