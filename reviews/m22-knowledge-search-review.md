# M22 — chunking, both index arms, and search — review

Artifacts: the M22 implementation per the brief — `zikaron/core/knowledge/{chunking,writes,lexical,vectors,search,arms,groups,scan,state,lifecycle}.py`, `zikaron/service/{dispatch_knowledge,params,context,server}.py`, `zikaron/mcp/{primary,tool_names,errors}.py`, `zikaron/core/indexing/{encoder,vectors,chunking}.py`, `zikaron/core/config/keys.py`, the named test files, and the design/prose deltas (`design/knowledge-index.md`, `design/schema.md`, `design/architecture.md`, `design/build-plan.md` §M22, `check.sh`, `pyproject.toml`, `FINDINGS.md` §M22).

## Round 1 — 2026-09-15

**Summary judgment.** This is strong work: the per-file transaction reads the FTS values before deleting and orders postings → vectors → chunks correctly; the chunker's partition and byte-identity properties are real and property-tested; the reported `score` is a genuine cosine (corpus normalized at write, query renormalized in `unit_query`, and the one mutation that survived was closed with a test that proves exactly this); invariant oracles are shown failing on planted violations; and the mask-aware-pooling premise is guarded against the real artifact across three batch widths. The one thing I would not ship as-is is the response byte cap: it is bypassable by the shape of the request (duplicate names, unknown names carrying the whole registry, never droppable), which reintroduces the M18 silent-truncation failure the cap exists to prevent. Beyond that, the findings are the corpus's dominant class — prose asserting something narrower or stronger than the adjacent code.

### Findings

1. **[BLOCKER] The response byte cap is bypassable by request shape, and the overflow fails exactly the way M18 documents — silently, at the harness.** Two mechanisms, both in `zikaron/core/knowledge/groups.py`:
   (a) **Duplicate names are not deduplicated.** `_requested` (groups.py:306–333) appends one entry to `found` per occurrence, so `knowledge_bases=["docs"]*50` runs fifty full searches of one corpus (fifty dense probes, fifty lexical probes, fifty snippet assemblies) and puts fifty identical groups in the response.
   (b) **Every unknown name carries the entire registry, and unknown groups can never be dropped.** `UnknownGroup.payload()` (groups.py:146–151) embeds `known_knowledge_bases` — every registered name *and description* — per unknown name, and `_fit_to_cap` skips anything that is not a `Group` (groups.py:217: `if not isinstance(group, Group) or not group.results: continue`). A request naming K unknown corpora therefore produces K × (registry size) bytes that nothing can reduce. With twenty KBs at ordinary description lengths that is ~1.5 KB per unknown name; thirty bad names clears 24,000 bytes on the unknown groups alone.
   Downstream nothing bounds it: `mcp/connection.py::_read_response` (line 559) reads until newline with no limit, and FastMCP serializes whatever dict it is handed — so the oversized result reaches the harness, which M18 measured truncating tool results silently. A truncated JSON response also silently violates invariant 10, since groups vanish mid-document with nothing set.
   **Suggested edits, all small:** in `_requested`, dedupe order-preserving — first occurrence wins — for both `found` and `unknown` (a `dict.fromkeys` pass over `names` before the loop); and bound the unknown payload — either emit the known list once per response (a top-level field the stubs point at), or cap it (names only, or first N with a count), or make `UnknownGroup` participate in `_fit_to_cap` by shedding `known_knowledge_bases` under pressure. Add a test: a request with duplicated and many-unknown names stays under the cap and searches each real corpus once.

2. **[IMPROVEMENT] The design and FINDINGS assert an unqualified byte cap that the code deliberately floors — one of them is a bug, per the build plan's own standing note.** `design/knowledge-index.md` §8.7 (line 1897): *"The whole response is capped at 24,000 bytes"*, with no exception stated. The code has a stated floor: `_fit_to_cap`'s docstring (groups.py:207–209, "once every group's results are gone there is nothing further this can drop, and a response of nothing but stubs is returned as it is") and `tests/test_knowledge_groups.py::test_no_named_corpus_is_removed_even_when_stubs_alone_exceed_the_cap` pin a response that exceeds the cap. `FINDINGS.md` (line ~807) says *"the response stays under 24,000 bytes by dropping whole groups into stubs"* — false at the floor, in the always-loaded file. The floor is the right choice (invariant 10 beats the cap), so the fix is prose: add the floor sentence to §8.7 (presence of every named corpus outranks the cap; once every group is a stub the response ships as it is), and qualify the FINDINGS sentence. Note that fixing finding 1 shrinks the floor but does not remove it — descriptions are unbounded — so the sentence is needed either way.

3. **[IMPROVEMENT] The mid-line snippet cut fires whenever the chunk's *first* line exceeds the cap, but every statement of the exception says "a single line longer than the cap".** `cut_to_snippet` (search.py:177–207): the `fitting == 0` branch (line 205–206) returns `text[:max_chars]` whenever the first line alone exceeds `max_chars`, regardless of how many more lines the chunk holds — reachable at defaults, since a ~1,300-character line is roughly 325 tokens and leaves budget for further lines in a 450-token chunk. In that case the snippet is a mid-line prefix of the first line, `end_line` names it, and the chunk's *remaining lines* are silently outside the snippet with only `truncated: true` to say so. The behaviour is the only sensible one; the prose is narrower than the branch, in four places: `cut_to_snippet`'s own docstring ("a **single line** longer than the cap"), `design/knowledge-index.md` §8.3's parenthetical (line 1476–1479, "a **single line** longer than the cap is cut mid-line"), invariant 16's last sentence (line 2085–2086), and FINDINGS §M22's second decision bullet. Reword to "when the first line alone exceeds the cap, the cut is mid-line inside it; any further lines of the chunk are outside the snippet, flagged by `truncated`". This is the corpus's named dominant defect class — worth the grep across all four sites, not just the ones cited.

4. **[IMPROVEMENT] A per-file chunk/embed failure aborts the whole build, and the adjacent prose reads as a per-file skip.** `scan._record_indexed`'s docstring (scan.py:316–317: "a file that cannot be chunked or embedded leaves the index exactly as it was, with its pending row still naming it") and the module docstring (lines 23–26) describe the *file's* state and never say the *scan* dies with it: a `ZikaronError` from `plan_file_chunks` or `embed_chunks` propagates out of `_dispose` → `_index_phase` → `run`, so `_complete` never writes, every remaining pending file is never disposed, and the error surfaces only to whoever invoked the build. For `IndexStage.EMBED`/`ASSEMBLY` an abort is right — those are systemic. For `IndexStage.BUDGET` it is a **deterministic, permanent** trap: a corpus-relative path over ~509 tokens (~2,000 characters, legal on Linux) makes *every* refresh die at the same file, the corpus can never complete a scan, and no skip reason, state, or status field explains why — the operator's only remedy is an exclude glob they have no pointer toward. Minimum fix: state the abort semantics in both docstrings. Better: record the BUDGET case in `knowledge-index.md` §16 as an open item, or treat it as a kept-row non-disposal like `unreadable` (invariant 12's "paths whose disposal could not complete" wording already accommodates it) while EMBED/ASSEMBLY keep aborting.

5. **[IMPROVEMENT] `register_primary_tools`'s docstring undercounts what it registers and its enumeration omits the new tool.** `zikaron/mcp/primary.py:55` — "Decorate all five primary-agent tools onto `mcp`" — the function decorates **six**, and the closing sentence (lines 59–61) enumerates "`search`/`fetch`/`remember`/`amend`/`retire` are never registered as tools in that process" without `zikaron_knowledge_search`, which the consolidator equally must not reach (the test `test_a_consolidator_config_provably_cannot_reach_any_reading_tool` covers it; the prose beside the code did not move). `tool_names.py` and `architecture.md` handled the count correctly — this is the one site that drifted. Fix both sentences.

6. **[IMPROVEMENT] `cosine_from_distance`'s docstring is now false about one of its two consumers.** `zikaron/core/retrieval/arms.py:171–172`: "An external query's vector is not renormalized, and no external query is thresholded." As of this milestone `knowledge.arms.unit_query` renormalizes an external query *precisely so this function's output is a true cosine* — that is the whole argument of unit_query's docstring, and the mutation that survived until a test forced it. Scope the sentence to the memory store's read path ("the memory store's external query is not renormalized…"), or state both consumers.

7. **[NITPICK] `response_bytes`'s docstring claims an encoding identity nobody measured.** groups.py:189–195: "Compact and without ASCII escaping, because that is what the transport sends." Neither hop sends those bytes: the service RPC hop (`service/rpc.py:144`, `json.dumps` defaults) ASCII-escapes and adds the same separators, and FastMCP's default serializer (`pydantic_core.to_json`, `.venv/.../fastmcp/tools/base.py:89–92`) is compact *without* the `", "`/`": "` spaces `json.dumps`'s default includes — so the measurement is a modest over-estimate of the harness-facing text, which is the conservative direction, but "is what the transport sends" overstates it. Reword to "an upper bound on the compact encoding FastMCP delivers". Optional, cheap, and in this project's spirit: one measurement near the cap of what the harness-facing tool result actually carries (including whether FastMCP adds `structured_content` alongside the text block for this tool's `object` return, which would ride the same wire).

8. **[NITPICK] The `knowledge_snippet_max_chars` ceiling comment equates code points with bytes — the exact unit slippage the key's own note warns about.** `zikaron/core/config/keys.py:298–301` and `design/schema.md:583`, both: "the ceiling is the whole response's byte cap, past which one snippet could not be delivered even on its own" — 24,000 *code points* is up to 96,000 *bytes*, and a snippet well under the ceiling in code points (e.g., ~8,000 CJK code points) is already undeliverable. The bound is fine; the justification conflates the units. Reword in both places (e.g., "the ceiling reuses the response cap's number as an order-of-magnitude sanity bound; near it any snippet is undeliverable in bytes regardless").

**Checked and clean, for the record:** the FTS5 `'delete'` path reads `chunks.path`/`chunks.text` before any delete and the `_clear` ordering (postings → vectors → chunks) matches §4.6; the integrity oracle uses argument 1 and is shown failing in both directions; the chunker's partition/byte-identity/budget postconditions hold, with hypothesis coverage and a recount that makes the packer's sum assumption non-load-bearing; `emit_head_of` can only run against an empty pending buffer, so chunk order is safe; every named corpus appears in the response across populated/empty/unknown/error/root_missing/dropped, tested end to end; the build-path encoder is a real `FastEmbedEncoder`, so `_require_matching_encoder`'s dim check is measured rather than vacuous; invariant 13 is pinned against the real artifact at three batch widths; the consolidator mode structurally cannot name the search tool, tested from both directions; the two formerly-vacuous tests (per-file cap, lexical-only cosine) now force their conditions and assert they arose; and `CLAUDE.md`'s check-gate paragraph moved with `check.sh`'s 600 s timeout.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-15

**Summary judgment.** Every round-1 fix landed as described, and I verified each against the code rather than the brief: the dedup of resolved names, the once-per-response registry listing with a defensible shed order, the floor stated in §8.7 and qualified in FINDINGS, the prefix-shortening replacement for the `BUDGET` trap (correct, including the postcondition recount against the plan's own prefix), the four mid-line-cut rewordings plus the new multi-line unit test, and all the smaller prose fixes (`register_primary_tools`, `cosine_from_distance`, `keys.py`/`schema.md` units). The check-gate test is real and self-verifying, and `CLAUDE.md` moved with it. **The one thing I cannot approve is the centrepiece of this round: the `_WIRE_COPIES = 2` change rests on a claim — "a response counted once at 24,000 bytes arrives as ~48,000, past the threshold" — that the corpus's own M18 measurement contradicts**, and it silently halves the deliverable answer while the prose in three places asserts a guard the test does not implement. The remaining findings are the corpus's named class: docstrings and design sentences the round-1 fixes left asserting the pre-fix world.

**On the recorded disagreement (round-1 finding 3, fourth site): I accept the correction.** FINDINGS §M22's second decision bullet (lines 786–792) is the *chunker's* embedded-head rule — "a single line longer than the chunk budget is stored whole and embedded from its head" — and `emit_head_of` is indeed reached only for a single line that does not fit an empty chunk, so "single line" is correct there. My round-1 citation was wrong; the real fourth site was the round-trip test docstring, which is now fixed (`tests/test_knowledge_search.py:149–153`). Withdrawn.

### Findings

1. **[BLOCKER] The ×2 wire charge is justified by a claim the corpus's own cited measurement refutes, and it halves the response budget for a safety gain the evidence does not support.** The brief asked for exactly this check, so here it is in full.
   The duplication itself is real and worth having measured: FastMCP delivers an object-returning tool's result as a text block *and* structured content, both on the wire. **But the threshold the cap exists to stay under was measured in single-counted payload size, through the same duplicating transport.** `research/claude-code-mcp-result-truncation.md`'s table: a **44,000-character payload was delivered intact** and 50,012 spilled — and that probe was "a `FastMCP` server whose one tool returns a payload of a requested size", whose spill file holds `{"result": "…"}`, i.e. FastMCP's own output-schema wrapping, so its deliveries carried both copies too. A threshold bracket established on dual-copy deliveries and denominated in single-counted characters *already includes* the duplication. You cannot multiply your own count by 2 without re-denominating the measured threshold by the same 2 — under the single-counted denomination the bracket is ~29,923–34,011 tokens and 24,000 single-counted bytes was always provably under it; under a both-copies denomination the same measurement re-reads as ~59,846–68,022 tokens and 48,000 wire bytes is *still* under it. Under **either** consistent accounting, the pre-fix behaviour (24,000 counted once) was safe, and the sentence in `design/knowledge-index.md` §8.7 (lines 1940–1943, "arrives as roughly 48,000 — past the threshold this number exists to stay under, failing exactly the way the threshold's own measurement says it fails") plus `FINDINGS.md` §M22 (lines 903–905, "past the very threshold the cap exists to stay under") are **contradicted by the 44,000-delivered row of the measurement they cite**.
   The cost is concrete: the effective payload budget is now ~12,000 bytes. One group at defaults (5 results × 1,200-char snippets ≈ 6,900 B of payload) charges ~13,800 "wire" bytes, so **two fully-populated groups now trigger group-dropping** (~27,600 > 24,000) where the pre-fix accounting delivered both — and M18's table says the harness would have delivered both comfortably.
   There is one reading under which ×2 *would* be right: if the probe's deliveries had carried only one copy (no structured content) while this tool carries two, and the harness gates on the combined total. But note that reading **breaks M18 instead** — the consolidator's tools also return objects (`consolidator.py`), `spill.py:121` counts once, and `spill_threshold = 27,000` single-counted would then sit *above* a ~22,000 dual-copy delivered floor, falsifying `schema.md` line 592's "a proof, not a margin". The two milestones' accountings cannot both be right, and one small measurement decides which: re-run one ~44,000-character probe with a tool that verifiably emits structured content (or open `/tmp/zk-mcptrunc/mcpprobe.py` if it survived and confirm its return annotation).
   **Suggested resolution:** take the measurement, then pick one denomination and state it everywhere. If it confirms the probe carried both copies (which the spill file's `{"result": …}` already indicates), revert `_WIRE_COPIES` to 1 (or equivalently set `RESPONSE_MAX_BYTES` to 48,000 wire bytes), keep the duplication fact recorded in §8.7 as a *denominators-must-match* caution rather than a correction, and rewrite the §8.7 and FINDINGS sentences so they no longer assert an overflow the M18 table refutes. If it instead shows the harness gates on the combined total, the M22 code is already right — but then M18's `spill_threshold` and `schema.md` line 592's proof claim must be reopened in the same change, because the corpus cannot carry both.

2. **[IMPROVEMENT] Three sites claim the wire test catches "a transport that stops duplicating"; the test cannot, and it can also pass vacuously.** `test_the_knowledge_response_cap_counts_every_copy_the_transport_carries` asserts only `on_the_wire <= response_bytes(payload)` — an upper bound. A transport that stops duplicating *halves* `on_the_wire` and the test passes; a delivery with no text blocks and `structured_content is None` yields `on_the_wire == 0` and the test passes. The test's own docstring is the honest version ("a transport that **adds a third representation**, or an accounting that goes back to charging once, fails here") — but `groups.py:200–202` (`_WIRE_COPIES` comment), `design/knowledge-index.md` §8.7 lines 1944–1946, and `FINDINGS.md` §M22 lines 906–908 all say "stops duplicating … fails there". Fix by strengthening the test rather than weakening three sentences: assert `delivered.structured_content is not None` and that the text-block sum is nonzero (that pins the duplication itself, and also removes the vacuous-pass path). This finding survives whichever way finding 1 resolves — if `_WIRE_COPIES` reverts to 1, the test and all three sentences get rewritten in the same pass.

3. **[IMPROVEMENT] Unknown names are deduplicated on the *raw* string, not after normalisation — the code contradicts both its own docstring and the design.** `groups.py::_requested` line 369 and 373: the miss is recorded with `unknown.setdefault(name, None)` — the caller's raw spelling — so `knowledge_bases=["DCOS", "dcos"]` produces **two** `UnknownGroup`s. The docstring three lines above (lines 354–356, "**Both halves** are deduplicated after normalisation") and `design/knowledge-index.md` §8.3 lines 1347–1349 ("and so is a repeated unknown name: both are deduplicated after that normalisation") say otherwise. The existing test (`test_one_unknown_name_repeated_is_reported_once`) uses byte-identical names, so it cannot see this. No cap exposure remains (an unknown group is ~60 bytes and the registry no longer rides on it), so this is prose-vs-code — but it is the exact claim the round-1 fix added. Fix the code to match the prose: in the `base is None` branch, `unknown.setdefault(normalized, None)` (the `InvalidNameError` branch keeps the raw string, having no normalized form), which also matches how the found half reports the registry's spelling rather than the caller's; add a case-variant unknown test. Or, if echoing the caller's spelling is preferred, say so in both places instead.

4. **[IMPROVEMENT] `KnowledgeSearchResult`'s two docstrings still state the two-field response the round-1 fix outgrew.** `zikaron/service/dispatch_knowledge.py:32` ("success shape: `{groups, groups_dropped}`") and `:46` ("`-> {groups, groups_dropped}`") — the payload now has three keys, and `tests/test_service_dispatch_knowledge.py:50` asserts exactly `{"groups", "groups_dropped", "known_knowledge_bases"}` one directory away. A neighbour contradiction created by the round-1 fix. Add `known_knowledge_bases` to both docstrings.

5. **[IMPROVEMENT] §8.3 asserts "the response reports the effective value" of a clamped `limit_per_kb`, and nothing reports it.** `design/knowledge-index.md` line 1367–1368. `SearchResponse.payload()` carries `groups`/`groups_dropped`/`known_knowledge_bases` only, no group field carries the applied limit, and a corpus-wide grep for the claim finds no reporting site. The tool description and the code agree on "clamped rather than refused" and say nothing about reporting. Delete the clause (the caller can count `results`), or add the field — but the sentence and the shipped shape must stop disagreeing.

6. **[NITPICK] `scan.py` is back over the module guideline it was split for.** 502 lines against `coding-standards.md` line 34's "roughly 400"; M21 split this exact file at 560. The clean seam is the index-phase disposal block (`_record_skip`/`_record_indexed`/`_dispose`/`_index_phase`, lines ~283–409), which already communicates through `_Disposals`. Optional now, but the trend line says M23 will force it anyway.

**Checked and clean this round:** `_fit_to_cap`'s shed order and its argument (announced loss before silent loss; the terminal listing-shed is stated in a comment and confined to the all-stubs degenerate case — defensible, and the design says the same); duplicate resolved names deduped order-preserving with two tests, and the query embedding provably skipped when only unknown names are asked; `known_knowledge_bases` populated only when a name went unmatched, absent on clean requests, and invariant 10 untouched by it (the listing is response-level, every named corpus still appears in `groups`); the tool description and §8.3 both carry the field and the shipped text names no unregistered tool (pinned by `test_zikaron_knowledge_search_names_no_tool_this_build_does_not_have`); prefix-shortening is correct end to end (`spare` floor, `token_head` at `spare − 1`, budget from the *shortened* prefix, `embedded_texts()` takes no argument, and the postcondition recounts against `plan.prefix`), with the remaining `BUDGET` raise genuinely model-only; the scan module and `_record_indexed` docstrings now state the abort and its systemic rationale accurately; `search.py` and `arms.py` re-read for correctness — dense tie-break in Python with the measured `vec0` constraint, 1-based ranks, lexical bm25 tie-break on rowid, `_capped` before the output limit, `_missing_cosines` through the extension's own arithmetic, the no-vector chunk omitted rather than scored, stale as pending ∪ size-disagreement with failed `stat` as strongest evidence; `test_check_gate.py` derives packages from the tree, proves its discovery non-empty, and pins `fail_under` to the standards sentence; and the p50 1.32 ms open measurement is quoted with its conditions.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-15

**Summary judgment.** The round-2 blocker was resolved the right way, and I verified the resolution rather than the report of it: `_WIRE_COPIES` is gone, `response_bytes` counts once with a denomination argument that is correct and now *measured* (I read the surviving probe at `/tmp/zk-mcptrunc/mcpprobe.py` — both tools are annotated `-> str`, and `emit(4)` returns exactly 4,000 characters, consistent with the reported 4,000 text + 4,013 structured bytes, the 13 being `{"result":"…"}`'s wrapper); the exact-encoding test at `tests/test_knowledge_groups.py:219–227` pins the single-counted accounting against re-doubling, and the re-aimed wire test pins the duplication and can no longer pass vacuously on the text side. §8.7's rewrite argues denomination rather than overflow and is consistent with M18's note, `architecture.md` and `build-plan.md` §M18 — the two milestones' accountings now agree, so `spill_threshold`'s proof claim needed no reopening. The `scan.py`/`disposal.py` split is clean: the two module docstrings agree about which phase owns what, `_record_indexed`'s abort semantics match `scan.py`'s module-level statement, imports moved (`lifecycle.py:55`, `indexer/main.py:73–82`, both test modules), and no code site references the old home. **What remains is the residue the brief asked me to hunt: the ×2 era left its unit word and — almost certainly — its doubled numbers in FINDINGS' own measurement paragraph, whose conclusion M25 is told to treat as a measurement.**

### Findings

1. **[BLOCKER] FINDINGS still denominates the cap in "wire bytes", and the three-corpora measurement it hands M25 is in the withdrawn ×2 accounting — its conclusion likely reverses under the shipped code.** Two sites, both in the always-loaded file, both contradicting §8.7's own denomination sentence ("24,000 counted bytes put roughly 48,000 on the wire", `design/knowledge-index.md:1947`):
   (a) `FINDINGS.md:808` — "the response is held under 24,000 **wire bytes** by dropping whole groups into stubs". Post-revert the cap is 24,000 *single-counted payload* bytes and the wire carries roughly double; calling it wire bytes re-asserts the withdrawn denomination. Suggested edit: "held under a 24,000-byte cap counted once on the payload (the wire carries both copies, roughly twice that — `knowledge-index.md` §8.7)".
   (b) `FINDINGS.md:875–881` — "at the shipped defaults, three corpora trip the response cap. Two corpora of real prose came to **20,872 wire bytes** of the 24,000 budget and dropped nothing; a third took it to **20,436 with the lowest-ranked corpus's results dropped whole** … So `groups_dropped` is an ordinary occurrence rather than a rare one … M25 now has the measurement rather than an intuition." The paragraph never states which accounting produced those numbers, and the arithmetic says it was the doubled one: at the shipped defaults a result serializes to ≈1,400–1,500 bytes even with its snippet at the full 1,200-code-point cap (snippet ≈1,250–1,350 B escaped, fields and keys ≈130–150 B), so **two fully-populated five-result groups cannot exceed ≈15 KB single-counted** — 20,872 is unreachable except as a ×2-era `response_bytes` output (≈10.4 KB of payload, charged twice). It is also the only reading on which "dropped nothing" was true while `_WIRE_COPIES = 2` was in force. Under the shipped single-counting, the same three corpora measure ≈15.7 KB — comfortably under 24,000, **nothing drops**, and dropping starts around four to five fully-populated groups. So the paragraph's headline claim and the "ordinary occurrence rather than a rare one" conclusion are artifacts of the accounting this round reverted, being handed to M25 as a measurement. Suggested resolution: re-run the two- and three-corpus searches through the shipped `response_bytes`, restate the numbers with their denomination named ("single-counted payload bytes"), and rewrite the conclusion to whatever the rerun shows — if it lands where the arithmetic points, the withdraw-in-place rule applies to the "three corpora trip the cap" sentence, since M25 would otherwise tune `limit_per_kb` against a threshold crossing that does not exist.

2. **[IMPROVEMENT] The deciding denomination measurement lives only in FINDINGS' M22 block and §8.7 — the research note both caps cite carries none of it, and the probe that anchors it is in tmpfs.** `research/claude-code-mcp-result-truncation.md` is the cited threshold evidence for M18's `spill_threshold` *and* M22's `RESPONSE_MAX_BYTES`, and both now rest on a fact about that note's own table — that its 44,000-delivered/50,012-spilled bracket is a dual-copy observation denominated in single counts — which the note itself never states; its "Not measured here" section doesn't mention it either. The next reader who does what round 2 did (go read what the cited threshold was measured on) finds nothing about denomination, and `/tmp/zk-mcptrunc/mcpprobe.py` — the only surviving proof of the probe's `-> str` shape — will not survive a reboot, the same trap FINDINGS already records for the `/tmp` store snapshots. Suggested edit: append a dated subsection to the research note ("Denomination of this table's counts, established 2026-09-15"): the probe's tools return plain strings (`-> str`, verified against the surviving file); FastMCP wraps a string return as structured content exactly as an object return (`{"result": …}`, which is why the spill file holds that shape); re-running the probe's shape through an in-memory client, `emit(4 KB)` delivered 4,000 text bytes and 4,013 structured bytes; therefore every character count in the table above is single-counted payload size through a transport that delivered both copies, and any bound compared against this bracket must count the same way. FINDINGS' M22 block is due for the archive; the note is where this fact has to survive.

3. **[NITPICK] The wire test's final assertion cannot fail for any value.** `tests/test_mcp_wire_contracts.py:228`: `json.dumps(delivered.structured_content, separators=(",", ":")) != ""` — `json.dumps` never returns an empty string for any input (`None` serializes to `"null"`, `{}` to `"{}"`), so the line is a tautology in a codebase whose review trail keeps convicting vacuous assertions. The `is not None` on line 227 already pins presence. Either delete line 228, or replace it with an assertion that the structured copy is *the payload again* rather than a stub — e.g. `assert len(json.dumps(delivered.structured_content, ensure_ascii=False).encode("utf-8")) >= as_text` (the second copy carries at least the payload, wrapper included), which can actually fail if a future transport ships an empty or summarized structured form.

4. **[NITPICK] FINDINGS still carries the snippet-ceiling unit conflation that round 1 had corrected in `keys.py` and `schema.md`.** `FINDINGS.md:797–800`: "above the 24,000-byte response cap a snippet could not be delivered even alone" — the key's ceiling is 24,000 *code points* (up to 96,000 bytes), and `keys.py:298–301` now says exactly that the two units differ and the number is a sanity bound rather than a derivation. The always-loaded file kept the pre-fix justification. Align the clause with `keys.py`'s corrected wording ("the ceiling reuses the response cap's number as a sanity bound; near it any snippet is undeliverable in bytes regardless").

5. **[NITPICK] Two small inventory drifts from the split, both in FINDINGS.** Line 827: "done, as `scan.BuildSettings`" — the class is defined in `disposal.py` and reaches `scan`'s namespace only via `scan.py:69`'s own import; every real consumer (`lifecycle.py:55`, `indexer/main.py:73`) imports it from `disposal`. Say `disposal.BuildSettings`. Line 992's inventory of `disposal.py` omits `write_counters`, which the module exports and `dispose` calls — the same list one bullet up in the round-3 brief included it.

6. **[NITPICK] The shipped description carries one clause the design's quote lacks, outside the one licensed substitution.** `zikaron/mcp/primary.py:116` ends the unknown-name sentence "…every corpus that does exist, **so you can pick the one you meant**"; the block quote at `design/knowledge-index.md:1395–1396` ends at "does exist." §"Until `zikaron_knowledge_list` exists" (lines 1409–1414) licenses exactly one shipped-vs-quote difference — the list-tool sentence's replacement — so by that section's own logic any other delta is drift. Add the tail clause to the quote (it is good text), or trim it from the shipped string; either way the byte-level rule for future drift checks is restored.

**Checked and clean this round:** the revert itself (`groups.py:196–214` counts once; the exact-encoding test pins compact-with-default-separators single counting, so a return to ×2 charging fails a test, and the wire test fails if the transport stops duplicating — §8.7's "a test pins both halves" is true across the pair); §8.7's rewritten paragraph asserts no overflow and its "roughly 48,000 on the wire" is labelled extrapolation from a measured duplication; no sentence outside `reviews/` still asserts the old overflow conclusion or the "stops duplicating … fails there" claim (grepped `_WIRE_COPIES`, `48,000`, `stops duplicating`, `counts every copy` — only FINDINGS' deliberate withdraw-in-place narrative at lines 913–934, which states the error and its refutation correctly); M18's `spill_threshold`, `schema.md`'s proof sentence, `architecture.md:1050–1051` and `build-plan.md:1192–1205` are coherent with the single-count denomination and needed no reopening; unknown names dedupe on the normalized spelling with the blank-name branch keeping the raw string and the docstring saying so (`groups.py:354–380`), pinned by the parametrized case-variant test asserting the reported spelling is the registry's; `KnowledgeSearchResult`'s both docstrings name all three fields and match the payload test one directory away; §8.3's clamp-reporting clause is withdrawn in place with its reasoning (`knowledge-index.md:1367–1373`); the split left no docstring in either module describing the other's job — `scan.py`'s module docstring names `disposal.py` as the index phase's home, both state the same three-disposals-plus-one-non-disposal contract and the same abort-on-systemic-failure semantics, `Disposals`' "five parameters" matches its five fields, and `BuildSettings`' rationale (the two values `meta` deliberately does not record) is correct in its new home; and the shipped tool description names only fields and states the response carries (`known_knowledge_bases` at the response level, `groups_dropped` as whole-corpora loss distinct from `truncated`).

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-15

**Summary judgment.** Every round-3 fix landed and I verified each against the artifact rather than the brief: both "wire bytes" sites are gone and the withdraw-in-place quotes the old numbers with their accounting named; the re-measurement is sound — `experiments/m22_response_cap.py` measures `groups.response_bytes` off the same payload object the cap is applied to, records its conditions including the denomination, and the restated table's arithmetic reconciles at every point I checked (differences 6,127/6,884 B → "6.1–6.9 KB", 24,000 − 19,764 = 4,236, stub growth ~110–160 B in rows 4–5); the denomination fact now lives in the research note both caps cite, anchored by an in-repo probe whose four byte counts are exactly what compact-versus-default-spacing wrapping predicts; the wire test's tautology was replaced by the strong form (structured copy pinned as *equality* with the payload under `{"result": …}`); and the drift guard is well built — `parse_block_quote` fails closed on zero and two matches, the exemption is index-anchored *and* pinned from the other side, so an inserted paragraph turns both tests red rather than silently shifting the exemption. No behaviour defect remains. What is left is scope-and-wording residue of the corpus's dominant class — including one instance where the restated paragraph inherited a missing qualifier from my own round-3 wording, which is the failure mode FINDINGS' M20 round-3 entry names.

### Findings

1. **[IMPROVEMENT] The restated cap paragraph swaps one unscoped universal for two, and its own conditions sentence contradicts the second.** `FINDINGS.md:911–913`: *"a store of three or fewer corpora never sees it, and one of four or more sees it on any search that names them all."* Three lines below, the conditions sentence says *"a corpus of short lines would serve smaller results and cross later"* — which directly falsifies "one of four or more sees it on **any** search that names them all" (four short-fragment groups can total well under 24,000). And the "never" half is falsified in the direction the conditions sentence does not cover: the snippet cap is 1,200 **code points** while `response_bytes` counts UTF-8 bytes of the JSON encoding, so multi-byte or escape-heavy text runs 2–4 bytes per code point (backslash-heavy ≈2,400 B/snippet, CJK ≈3,600, astral ≈4,800) — a group of five is then 12–25 KB and the cap trips at **two corpora, or even one**. Both claims are facts about this text presented as facts about store size. Related, same paragraph: line 894's *"at the shipped defaults a result cannot serialize to enough bytes for two groups to reach 20,872"* has the same missing qualifier — and it inherited it from **my round-3 arithmetic**, which was about this repository's mostly-ASCII prose; installing a reviewer's wording without re-scoping it is the exact mechanism FINDINGS' M20 round-3 entry documents. Suggested edits: scope the never/any sentence to the measured corpora and state that the crossing moves in *both* directions ("on corpora like these, three fit and four did not; short fragments cross later, multi-byte or escape-heavy text crosses earlier — as low as one or two corpora"); extend the conditions sentence with the crosses-earlier direction; add "on text like this repository's" to line 894. **`build-plan.md` §M25 (lines 1770–1776) is correctly scoped and needs no change** — the always-loaded file is the only site over-claiming.

2. **[IMPROVEMENT] The research note's new section says "the table above", and the table above is the wrong table.** `research/claude-code-mcp-result-truncation.md:137–140`: the heading "Denomination of **this table's** counts" and the opening "Every character count in **the table above** is the size of the payload the tool returned" sit directly beneath the long-lines table (lines 104–109) — whose counts are file **line lengths measured through `Read`**, a channel that delivers once and has no structured content. The claim is about §"What was measured"'s table, 120 lines up. A reader who resolves "above" to the nearest table — or lands on the section by grep, which is how this note is used — reads a false statement about `Read` measurements in the note both payload bounds cite. Fix is one phrase in each place: name the section ("Every character count in §'What was measured' …"), which also keeps the `Read`-derived token accounting (104,179 chars / 70,848 tokens) correctly outside the claim's scope.

3. **[IMPROVEMENT] §8.3 says the registry listing is "present only when some name went unmatched"; the payload always carries the key, and the design's own example 80 lines later shows it.** `design/knowledge-index.md:1363` versus `SearchResponse.payload()` (`groups.py:171–176`), which serializes `known_knowledge_bases` unconditionally — `[]` when nothing went unmatched, as proven by the exact-encoding test's literal (`tests/test_knowledge_groups.py:223–228`) and by the design's own result example (`"known_knowledge_bases": []` … "because every name resolved", lines 1445–1449). The code's docstring has the accurate word — "**populated** only when some name went unmatched" (`groups.py:162`). Second site, same claim: §8.7:1964 argues the listing sheds last because "its **absence** is also what a request with no bad names looks like" — the shed form is `[]`, not absence, and the argument survives intact with "emptiness". A client implementer keying on field *presence* — which is what §8.3's sentence licenses — would build a signal the shipped shape never emits. Fix both words in the design; nothing in the code needs to move.

4. **[NITPICK] "Roughly double what the shipped code measures" invites a reconciliation the paragraph does not supply.** `FINDINGS.md:891–893`: halving the withdrawn 20,872 gives 10,436, and the new table's same-two-trees row reads 12,880 — a 23% residual a careful reader will trip on, whose actual cause (the trees have grown between the two sessions, and the original query is not certainly the harness's) the paragraph never states. Reword to "roughly double the single-counted size of the same responses" and add one clause noting the re-run is over the trees as they stand now, so the halved originals and the new rows are not expected to match.

5. **[NITPICK] Three small hygiene items in `spikes/spike_mcp_result_denomination.py`.** (a) Line 28: `KIBIBYTE = 1000` — a kibibyte is 1,024 bytes; this constant holds an SI kilobyte, and the corpus has twice convicted the ambiguous unit word. Rename `KILOBYTE`. (b) Lines 56–65: `delivered_twice` computes `as_text > 0 and len(encoded) > 0`, and `json.dumps(None)` is `"null"` (4 bytes), so the field prints `true` even when `structured_content is None` — a diagnostic field named for a fact its computation cannot falsify on one side; require `structured is not None`. (c) Placement: `CLAUDE.md`'s evidence taxonomy assigns re-runnable harnesses to `experiments/` and throwaway probes to `spikes/`, and this file is kept "precisely so this fact does not depend on a probe directory under `/tmp`" — i.e., it is a durable, re-runnable anchor, and FINDINGS:967 even introduces it with the taxonomy's own word ("Re-runnable as…"). Move it to `experiments/` and update the two references (research note line 148, FINDINGS line 967).

6. **[NITPICK] The exempted paragraph is the only one with no mechanical guard on its content, and a normative §8.3 claim leans on it.** `design/knowledge-index.md:1369–1370`: "the cap is stated in the tool's own description, where a caller reads it before choosing a number" — the clamp sentence lives only in the substitution paragraph (`primary.py:103–104`), which both drift tests deliberately skip, so a future edit could drop it (or the omit-names instruction §"Until…" licenses) with nothing going red, quietly falsifying the withdrawn-clause paragraph's own justification. Add a required-phrase test on `shipped[_LICENSED_SUBSTITUTION]` — "Omit `knowledge_bases` to search every corpus" and "clamped rather than refused" — in the same style as the occasions test above it.

7. **[NITPICK] `parse_block_quote` is the one parser in `design_tables.py` that reads through fences.** `_structural_headings`, `parse_tables`, `parse_toml` and `parse_fenced_code` all mask fenced content; `parse_block_quote` (lines 423–450) does not. The silent path exists because this corpus keeps withdrawn text around by policy: if the prose quote were ever removed while a fenced historical copy opening with the same words sat in §8, the exactly-one rule would be satisfied by the fenced copy and the guard would compare the shipped description against an archive. Four lines — skip while `in_fence`, same as the siblings — closes it for good.

**Checked and clean this round:** the post-revert state is untouched (`RESPONSE_MAX_BYTES = 24_000`, `response_bytes` counts once with the denomination argument, the exact-encoding test still pins compact single counting); the harness measures the right object in the right unit and its conditions block records load, CPU count, denomination, git mode, limits and query — and its `git_mode = off` choice is argued, not defaulted; the spike's four byte counts are internally consistent to the byte (`-> str` 4,000/4,014, `-> object` 4,014/4,027 — compact text copy, default-spaced re-serialization of the `{"result": …}` wrapper), the note's "rows are not comparable to each other" caveat is right, and its "wire carried roughly double" matches 44,000 + 44,013; the wire test's equality assertion goes through a serialization round trip so tuple-versus-list cannot false-positive it; the drift guard's exemption cannot quietly widen (companion test pins that `designed[1]` still names the list tool and still differs) and cannot quietly shift (an inserted paragraph breaks the length assertion and the companion's content pin together); the shipped substitution paragraph carries both the omit-names instruction and the clamp sentence today; `parse_block_quote`'s five unit tests cover the bare-marker, end-of-section, zero-match and two-match cases; §M25 carries the corrected crossing with the do-not-tune warning; FINDINGS' round-3 nitpick fixes are all in place (the snippet-ceiling clause withdrawn-in-place at lines 795–804, `disposal.BuildSettings` with the re-export note, `write_counters` in the inventory, the loop-state tally updated); and the corpus grep for the crossing claim in its other phrasings ("three corpora", "third corpus", "20,872", "trip the cap") finds only the deliberate withdraw-in-place sites and correctly restated ones.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-09-15

**Summary judgment.** All seven round-4 fixes landed as described and I verified each against the
artifact: the cap paragraph is scoped in both directions and reconciles internally, the research
note's denomination section names §"What was measured" in its heading and opening line and scopes
the `Read`-measured table out, the probe moved with its rename and its `delivered_twice` guard, the
required-phrase test pins both load-bearing sentences *inside* the substitution paragraph rather
than anywhere in the description, and `parse_block_quote` masks fences with both directions tested.
The deep pass the brief asked for — chunker, both arms, per-file transaction, disposal — found the
shipped behaviour sound, with one exception worth fixing before this ships: the chunker's
assembly-stage recount measures a string the embedder never receives, and the test named for that
recount cannot tell the difference. The rest is one-word residue of round 4's own fixes, the
cascade class this trail keeps predicting.

### Findings

1. **[IMPROVEMENT] The chunker's assembly recount never counts the string the embedder actually
   receives, and both prose statements of the property say it does.**
   `zikaron/core/knowledge/chunking.py:366`: `_assert_plan_is_within_its_budgets` checks
   `assembled_tokens(plan.prefix, chunk.embedded_body)`, which counts `f"{prefix}{body}"` — no
   separator — while `embedded_texts()` (line 116 → line 79) emits
   `f"{prefix}{PREFIX_SEPARATOR}{body}"`. So the exact sequence handed to `encoder.embed` is
   counted **nowhere**: the budget derivation charges the separator as the constant
   `SEPARATOR_TOKENS = 1` over parts counted separately, and the recount measures a
   concatenation with the separator deleted. The module docstring (chunking.py:14–17, "counted on
   the assembled sequence — prefix, separator, body and special tokens") and §4.3
   (`design/knowledge-index.md:546–547`, "enforced against the **assembled** sequence — prefix +
   separator + text + special tokens") both describe a check the code does not perform.
   **Not a live overflow on the deployed artifact** — the deployed pre-tokenizer splits at the
   newline (stated as measured in the packer's own comment), so real-sequence fit is provable
   today with the charged separator token as slack. But the `SEPARATOR_TOKENS` comment
   (`core/indexing/chunking.py:32–36`) explicitly argues the assembled-sequence assertion is the
   bug-catcher for "a future model whose separator does tokenize" — and for exactly that model,
   the assertion is measuring the wrong string. D20 keeps the model a config key, so that model
   arrives via an ordinary rebuild, and the failure it would admit is the silent model-side
   truncation this module exists to prevent.
   **The test named for this cannot discriminate.**
   `tests/test_knowledge_chunking.py:301–318`: `_PrefixFusingEncoder` fires when the counted text
   contains `PREFIX_SEPARATOR` *anywhere* and starts with `_PATH` — and the body `"alpha beta\n"`
   carries its own trailing newline, so the fake fires on the no-separator concatenation exactly
   as it would on the true emitted string. The current implementation and the correct one both
   pass it.
   **Suggested fix, one argument plus one trigger:** change the recount to
   `assembled_tokens(f"{plan.prefix}{PREFIX_SEPARATOR}", chunk.embedded_body, encoder=encoder)`
   (or equivalently `encoder.count_tokens(chunk.embedded_text(plan.prefix)) +
   encoder.n_special_tokens`), which counts byte-for-byte the string `embedded_texts()` emits;
   and sharpen the fake's trigger to `text.startswith(f"{_PATH}{PREFIX_SEPARATOR}")`, which fails
   on the current implementation and passes on the fixed one — the mutation-grade discriminator
   this project already practices. **Name the neighbours in the same edit** so this does not
   become round 6's cascade: `encoder.py:136–137` ("the file path the knowledge index prepends to
   a chunk" — still true under the first form, worth a clause saying the separator rides with the
   prefix argument), and re-read chunking.py:14–17 and §4.3:546–547 afterwards, both of which
   become literally true under the fix.

2. **[NITPICK] `_fit_to_cap`'s docstring still argues the listing shed with the word round 4's
   design fix disavowed.** `zikaron/core/knowledge/groups.py:227–230`: "it is already **absent**
   whenever every name resolved, so its **absence** carries no information" — §8.7:1965 now says
   "the shed form is an empty list", §8.3:1365–1366 says "the field itself is always present,
   empty in that case rather than absent", and the payload serializes the key unconditionally.
   This is the third statement of the claim round 4's finding 3 corrected, missed because its
   phrasing differs — the corpus's own grep-over-every-phrasing lesson. One word, twice: "it is
   already **empty** whenever every name resolved, so its **emptiness** carries no information."

3. **[NITPICK] FINDINGS cites the research note's denomination section by its pre-rename
   heading, twice.** `FINDINGS.md:979` and `:1077` both say §"Denomination of this table's
   counts"; the heading round 4's finding-2 fix produced is
   `## Denomination of §"What was measured"'s counts, established 2026-09-15`
   (`research/claude-code-mcp-result-truncation.md:137`). Both are live pointers, not quotes, and
   a reader grepping the note for the cited heading finds nothing — the rename fixed the section
   and left its two citations pointing at a title that no longer exists. Update both.

4. **[NITPICK] The cap paragraph's bold lede is the crossing claim without the scope its own body
   added.** `FINDINGS.md:885`: "Superseded by measurement: three corpora do *not* trip the
   response cap — the fourth does." Read as a store-size fact — which is how a skimming reader of
   an always-loaded file takes a bold lede — it is the withdrawn "one of four or more sees it"
   half in compressed form, and line 924 ("no store size at which dropping is impossible, and
   none at which it is guaranteed") contradicts that reading nineteen lines later. The body is
   correctly scoped ("On corpora like these", line 914); the lede is not. Suggested: "…: on these
   trees, three corpora do not trip the response cap — the fourth does."

**Checked and clean this round:** every round-4 fix, against the artifact — the never/any sentence
withdrawn in place with the mechanism named and the conditions sentence carrying both directions
(FINDINGS:918–927), line 894's "on text like this repository's" qualifier, §M25 still correctly
scoped (`build-plan.md:1770–1776`); the multi-byte arithmetic reads as derivation rather than
measurement (per-point byte costs of JSON-escaped UTF-8 are encoding facts, correctly stated at 2/3/4
B per point); the withdrawn-in-place paragraph is coherent read cold — original, cause, non-reconciliation warning
with the 10,436-vs-12,880 gap explained, table, scoped conclusion — and its internal arithmetic
reconciles (6,127/6,884 differences → "6.1–6.9 KB", 24,000 − 19,764 = 4,236); §8.3 says
*populated* with the always-present clause and its own example shows `[]`, §8.7's shed argument
says "empty list", and the third site FINDINGS:993 is corrected; the note's denomination section
scopes the `Read`-measured long-lines table out explicitly and its two-row table is internally
consistent with the wrapper-spacing explanation; `experiments/mcp_result_denomination.py` has
`KILOBYTE`, requires `structured is not None` in `delivered_twice`, and no reference to the old
spike path or unit name survives anywhere; the required-phrase test asserts inside
`_paragraphs(description)[_LICENSED_SUBSTITUTION]` specifically, and both phrases are in the
shipped paragraph today; `parse_block_quote` masks fences like its four siblings with both
directions tested (live-beside-fenced returns the live quote; two fenced copies raise on zero) —
one degenerate shape noted for the record, not raised: an *empty* fence directly between two quote
runs would merge them, which no real design document contains, and fences are provably balanced
within any section because `_structural_headings` refuses unterminated fences at document level;
`CLAUDE.md`'s never-commit rule explicitly disarms the "lands as one commit" bullet, contradicts
nothing else in the file, and agrees with FINDINGS' "not committed, operator instruction" notes;
and the deep pass over the milestone's less-reviewed code found no behaviour defect beyond finding
1 — `split_lines`/packer partition and `emit_head_of`'s empty-pending precondition, `writes.py`'s
read-before-delete and postings → vectors → chunks order with the count equality checked rather
than trusted, `disposal.py`'s three-disposals-plus-one with counters written inside each disposing
transaction and the unreadable case flushed alone, `lexical.py`'s positional `'delete'` traveling
as a `Document`, the width check living in `normalize` exactly as `embed_chunks`'s Raises claims,
`arms.py`'s Python-side dense tie-break and rowid lexical tie-break, `search.py`'s per-file cap
before the output limit, missing-cosine backfill through the extension's own arithmetic, failed
`stat` as staleness, and no-vector chunks omitted rather than scored, and `groups.py`'s shed order
with the floor; the `knowledge_bases: []` edge ("asked for none, answered with none") is
deliberate, documented at the params layer, and pinned by
`test_an_empty_name_list_asks_for_nothing_and_is_given_nothing`.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-09-15

**Summary judgment.** The milestone's code is done: the chunker recount now measures byte-for-byte
the string `embedded_texts()` emits, the sharpened fake genuinely discriminates, the fence-boundary
fix is correct with both masking directions and the joining case pinned, and a fresh pass over the
two files no prior round's checked-clean list had walked (`state.py`, `vectors.py`) plus a full
re-read of `groups.py` found no behaviour defect. The brief's three self-verified conclusions all
hold under independent re-derivation, and the PROCESS FAILURE entry's classification and cascade
claims are accurate against the round texts above. What remains is exactly one instance of the
class the new process documents exist to name — the corrected count survives uncorrected in the
*other* process document, the always-loaded binding one — plus two small accuracy items in the
FINDINGS narration.

### Findings

1. **[IMPROVEMENT] `CLAUDE.md`'s new bullet still carries the withdrawn "18", presented as
   measured, while FINDINGS' own correction says the 18 was never counted — the two process
   documents disagree about the one number the classification rests on.** `CLAUDE.md:97`:
   *"**Measured on M22** — roughly 14 of rounds 3–5's 18 findings were self-findable"*.
   `FINDINGS.md:1041,1045–1047`: *"**14 of 17 did** (round 3: 6 of 6; round 4: 5 of 7; round 5:
   3 of 4)"*, followed by a withdraw-in-place naming *"roughly 14 of 18"* as *"the
   confident-looking number this file has a standing rule about"* — and 17 is the correct total
   (rounds 3–5 above tally 6 + 7 + 4). So the binding, always-loaded instruction file asserts, with
   the word "Measured" in front of it, the exact figure its companion document withdraws as
   never-counted, inside the bullet whose own text mandates grepping every changed claim in all of
   its phrasings. **And per this round's brief, I am required to say this explicitly: the brief
   reports these two numbers as "corrected in place" — they were corrected in FINDINGS only. The
   correction was applied as a site fix, not a claim sweep, inside the entry that defines the
   difference. That is direct evidence the sweep as executed still runs over the file that was
   being edited rather than over the claim.** Fix: `CLAUDE.md:97` → "14 of rounds 3–5's 17
   findings" (exact, so "roughly" can go too), then grep `14 of` / `of 18` / `self-findable`
   across the corpus for any third site.

2. **[NITPICK] FINDINGS' spawn line and this round's brief disagree about the gate count by one
   test.** `FINDINGS.md:1090`: *"Round 6 was spawned against a green gate: `./check.sh` exits 0,
   2542 passed, 98%."* The brief that spawned this round says **2543 passed, 98.02%**, and the
   difference is exactly the one test the brief says was added after the killed round-6 brief was
   written (the empty-fence joining test, which exists —
   `tests/test_design_tables.py::test_a_fence_between_two_quotes_does_not_join_them`). One of the
   two numbers describes the killed spawn rather than this one. Reconcile FINDINGS:1090 against
   the actual final run — a confident-looking count in the always-loaded file is this file's own
   M13-hash lesson at one-test scale.

3. **[NITPICK] The round-6 briefing block's account of *why* the denomination citations drifted
   contradicts the file's own cascade narrative twenty lines up.** `FINDINGS.md:1114–1118`: the
   round-4 heading *"cannot be cited without nesting quotes, **and that is what made the citations
   drift in the first place**"*. It is not: the two citations at the then-`FINDINGS.md:979`/`:1077`
   quoted the *pre-round-4* heading ("Denomination of this table's counts"), i.e. round 4 renamed
   the section and the citations were never updated — which is precisely how `FINDINGS.md:1062–1063`
   itself files the defect ("round 5's stale citations … from round 4's" fixes), and how round 5
   finding 3 above records it. The nesting-quotes fact is a good argument for the *new* heading
   being citable; as a cause of the drift it retroactively converts a missed sweep into a
   structural inevitability, in the entry stream whose whole subject is accurate defect causes.
   Reword: "…which also made it awkward to cite; the drift itself was round 4's rename landing
   without its citations, the cascade class named above."

**Checked and clean this round, answering the brief's four questions in order.**
*(1) The milestone.* `chunking.py:370–376` recounts
`assembled_tokens(f"{plan.prefix}{PREFIX_SEPARATOR}", chunk.embedded_body)`, and
`f"{prefix}{sep}" + body` concatenated inside `assembled_tokens` (encoder.py:142) is character-for-
character `FileChunk.embedded_text`'s `f"{path}{sep}{body}"` — the counted string is the emitted
string, closing round 5's finding as specified. The sharpened trigger
(`test_knowledge_chunking.py:320`, `startswith(f"{_PATH}{PREFIX_SEPARATOR}")`) cannot fire on the
pre-fix concatenation, since `_PATH` is directly followed by the body there, so the test now fails
on the old code and passes on the new — a true discriminator, and its docstring records why the old
trigger was not. Derivation and recount reconcile: `spare = max − specials − SEPARATOR_TOKENS`,
the shortened-prefix path leaves `budget ≥ 1` (`token_head` to `spare − 1`, lines 336–338), the
head-only path satisfies both recount bounds, and on the deployed artifact (`PREFIX_SEPARATOR =
"\n"`, zero tokens under WordPiece pre-tokenization) the charged separator token is slack exactly
as the `SEPARATOR_TOKENS` comment argues, so no live corpus aborts. On a future separator-
tokenizing model a mismatch now fails loud at `ASSEMBLY` rather than truncating silently, which is
the property the module claims. `parse_block_quote` (design_tables.py:423–464) masks fences, ends
an open run at a fence boundary, and handles the quote-marker-inside-a-fence and
fence-marker-inside-a-quote cases correctly; all three mutation claims in the brief are
mechanically consistent with the tests as written (deleting masking turns the live-beside-fenced
test into a two-match error; restoring the `continue` splices the joining test's two runs into one
and zeroes its second lookup). Fresh reads: `groups.py` end to end (dedup on normalized spelling
with the blank-name branch keeping the raw string; `known_knowledge_bases` built once, carried only
when something went unmatched, shed last; the stub floor; `_serve`'s catch split — open failures
*and* `ZikaronError` become the corpus's `error`, serve-time `ZikaronError` deliberately propagates
as our own bug rather than masking as corpus state — defensible and consistent with the module
docstring); `state.py` (PRECEDENCE tuple and `resolve`'s branch order agree; the three
`reindex_required` causes match M20's decision; `never_built` reads the persisted key, not an
emptiness test); `vectors.py` (batch loop preserves `part_index` order, count mismatch and embedder
failure both become `INDEX_FAILED` at `embed`, per-id `vec0` deletes with the no-`rowid` fact
stated and measured). Nothing else in the milestone remains unread.
*(2) The process documents.* The 14-of-17 classification is defensible against the actual round
texts: the per-round totals are right (6/7/4 from the tallies at FINDINGS:1027–1033, matching the
round headers above), the three findings credited with independent-reviewer value are the right
three, and the marginal case (round 3 finding 2, the evidence-placement judgment) is classed
self-findable, which errs in the self-critical direction rather than the flattering one. The
cascade claim is true as stated: round 2's findings 1–4 arose from round-1-era changes, round 3's
blocker from round 2's revert, round 4's findings 1–2 from round 3's rewrite, round 5's nitpicks
2–4 from round 4's fixes — four rounds of five, and the parenthetical withdrawing the borrowed
"four of the last nine" figure is accurate. The one inaccuracy found in either document is finding
1 above.
*(3) The recount and neighbours.* The conclusion holds, re-derived rather than taken: the fixed
recount is at least as strict as the old one on the deployed artifact (the newline join is a
pre-tokenizer boundary, so the new count equals the parts' sum where the old concatenation could
fuse and undercount) and is the correct string on any artifact; `encoder.py:136–140` now states
the separator-rides-with-prefix rule; the module docstring's "prefix, separator, body and special
tokens" and §4.3's assembled-sequence sentence (`knowledge-index.md:546–547`) are both literally
true of the code. The class audit's conclusion also holds independently: `retrieval/query.py:236`
and `:275` count the exact string line 277 embeds (`f"{prefix}{kept}"`, no separator exists in that
sequence), and `consolidation/candidates.py:86`'s loop feeds `external_query`, which recounts the
assembled string itself — so the knowledge chunker was indeed the only caller whose emitted string
carried a join the count omitted. `_PrefixFusingEncoder` appears at its definition and one test
only.
*(4) Residue.* The `_fit_to_cap` docstring says empty/emptiness (groups.py:228); the research
note's renamed section heading (`claude-code-mcp-result-truncation.md:137`) is quotable without
nested quotes, scopes the `Read`-measured table out, and all three FINDINGS citations
(:980, :1116, :1166) match it; the cap paragraph's lede carries "on these trees" (FINDINGS:885).

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-09-15

**Summary judgment.** All three round-6 fixes landed exactly as the brief describes, and — the
brief's own question 3, answered against the artifact — **none of them cascaded**. That is the
first round in this trail where the preceding round's fixes produced no new defect (rounds 2–6
each did), and the difference is visible in how the fixes were executed: the count fix arrived
with its corpus sweep already run and its results reported, the gate fix as a withdraw-in-place
with the cause of the staleness named, and the heading fix — a *second rename*, the exact
operation that caused the original drift — with all three citations moved in the same pass and
nothing left pointing at either prior title. The milestone's code was done at round 6 and nothing
has touched it since; the one thing this round found predates round 6 and is a two-word fix.

### Findings

1. **[NITPICK] FINDINGS states round 1's tally as "seven improvements" in two places; the trail
   one file away tags 1 blocker, 5 improvements, 2 nitpicks.** `FINDINGS.md:964` ("Round 1 of the
   review found one blocker and seven improvements") and `FINDINGS.md:1025–1026` ("**Round 1
   NEEDS_CHANGES** (1 blocker, 7 improvements)") — the second sits in the loop-state list whose
   every other entry gives the exact three-way tag tally, so it reads as one and is wrong: round 1
   above is findings 1 [BLOCKER], 2–6 [IMPROVEMENT], 7–8 [NITPICK]. The total (8) is right; the
   two nitpicks were absorbed into "improvements". **This is not a round-6 cascade** — the claim
   dates from the round-2-era narration and survived because round 6's tally verification covered
   rounds 3–5 (whose 6/7/4 the classification rests on) and never round 1's, and I did not check
   it in five rounds either. Nothing downstream computes from it: the 14-of-17 classification
   starts at round 3, so the PROCESS FAILURE accounting is untouched. Fix both sites to
   "(1 blocker, 5 improvements, 2 nitpicks)" / "one blocker, five improvements and two nitpicks".
   Trivial, and I would ship without it — raised because the operator's standing instruction is
   that every nitpick gets addressed, and because a tally in the loop-state list's own format is
   exactly the confident-looking count this file keeps convicting.

**Checked and clean this round, answering the brief's three questions in order.**
*(1–2) The three fixes, each against the artifact rather than the brief.* `CLAUDE.md:97` reads
"**Counted on M22** — 14 of rounds 3–5's 17 findings were self-findable" — exact, "roughly" and
"Measured" both gone — and lines 101–105 record the bullet's own failure with the site-fix
mechanism named and the closing sentence the brief quotes; it agrees with `FINDINGS.md:1048`
("14 of 17 did", 6+7+4) and with the withdraw-in-place at :1052, and the corpus sweep the brief
reports reproduces under my own grep (`14 of` / `of 18` / `of 17` / `self-findable` /
`17 findings` / `18 findings` over all markdown: the two intended sites, this trail, and only
unrelated hits — the embedder documents' "14 of 14" and "18 findings", kiro's "one of 18 built-in
tools"). `FINDINGS.md:1097–1101` reads 2543/98.02%, names the withdrawn 2542/98% as the killed
spawn's gate with the extra test identified, and no third gate figure exists in any non-review
markdown (grepped `2531|2542|2543|98.02`). `FINDINGS.md:1125–1131` now attributes the citation
drift to round 4's rename landing without its citations — the cascade class — with the
nesting-quotes fact demoted to "which also made it awkward to cite" and its own earlier
misattribution withdrawn in place; :1054 and :1061–1062 file the defect the same way, so the
three sites agree.
*(3) Cascade check on the fixes themselves, the trail's most reliable pattern.* The heading
re-rename is contained: `research/claude-code-mcp-result-truncation.md:137` reads "Denomination
of the delivery-threshold counts", all three FINDINGS citations (:980, :1127, :1179) match it
byte-for-byte, neither prior title survives anywhere outside this trail, the section's internal
references (§"What was measured" at :139 and :177) resolve to the heading at :13, the other
heading `build-plan.md:1280` cites (§"The cap in tokens, derived") is untouched at :57, and
`experiments/mcp_result_denomination.py` cites no section heading at all. The count fix's two
documents tell one story (site fix in FINDINGS, survivor found by review, recorded in both — 
`FINDINGS.md:1039–1042` and `CLAUDE.md:101–105` agree on every particular). The gate fix
introduced no new number anywhere else. And the no-gate-re-run claim is sound, verified from the
other side: nothing in `tests/` or `zikaron/` references `CLAUDE.md` or `FINDINGS.md` (the only
grep hits in `zikaron/` are harness identifiers), so no test parses either edited file and round
6's green gate still describes this tree. The loop-state tallies for rounds 2–6 each reconcile
against the round headers above; round 1's is finding 1.

**On the loop itself, since the brief asked for the fact rather than the finding:** rounds 2–6
each contained a cascade of the preceding round's own fixes; round 7 contains none. One round is
n=1, but the mechanism difference is observable in the brief itself — this is the first round
whose brief reported sweep *results* instead of asking the reviewer to run the sweeps, which is
precisely the PROCESS FAILURE entry's "verify it first and tell the reviewer what you found" rule
being executed rather than narrated.

The milestone is done. Round 6 established the code; this round establishes that the process
documents carrying its lessons are accurate and mutually consistent. Finding 1 is trivial, does
not touch a normative document, and should be fixed without another round being spawned.

VERDICT: APPROVED
