"""D15's write-time dedup: `zikaron.core.write.dedup.offer`.

Default tier, unmarked: a real store on `tmp_path` with a deterministic `FakeEncoder`
(`coding-standards.md` §4). `Harness` (`tests/retrieval_fixtures.py`) writes every row through the
real indexed path, so a dedup search here runs against real chunks and real vectors, not a
stand-in.
"""

import unittest.mock
from pathlib import Path

import pytest

from tests.retrieval_fixtures import Harness, ctx, harness, query_vector_for
from zikaron.core.events import EventKind
from zikaron.core.retrieval.eligibility import Consumer, Scope
from zikaron.core.retrieval.query import internal_query
from zikaron.core.retrieval.retrieve import retrieve
from zikaron.core.retrieval.similarity import exact_directed_cosines
from zikaron.core.write.dedup import DedupPolicy, offer

_GIST_A = "protobuf codegen fails silently on staging"
_CONTENT_A = "the proto compiler version drifts from the one pinned in requirements.txt"
_GIST_B = "protobuf codegen fails silently on staging too"
_CONTENT_B = "the proto compiler version drifts from the one pinned in requirements.txt as well"
_GIST_UNRELATED = "the release build needs Java 17, not 21"
_CONTENT_UNRELATED = "Gradle's toolchain resolution picks the newest installed JDK"


async def _uuids_by_gist(harness: Harness) -> dict[str, str]:
    rows = await harness.store.connection.execute_fetchall("SELECT uuid, gist FROM memory")
    return {str(gist): str(uuid) for uuid, gist in rows}


async def _pool_best_distance_for(
    h: Harness, *, new_row_uuid: str, target_uuid: str
) -> float | None:
    """The fused pool's own `best_distance` for `target_uuid`, exactly as `dedup.offer` would see
    it before its exact-cosine fix — used only to prove the regression test's own precondition:
    that the dense arm's `fusion_depth`-cut fused rows genuinely exclude `target_uuid`, so the
    behaviour under test is reached through the lexical arm alone rather than by accident."""
    settings = h.read_call().settings
    query = await internal_query(
        h.store.connection, memory_uuid=new_row_uuid, max_terms=settings.fts_query_max_terms
    )
    retrieved = await retrieve(
        h.store.connection,
        query=query,
        scope=Scope(Consumer.DEDUP, exclude_uuid=new_row_uuid),
        settings=settings,
    )
    for ranked in retrieved.pool:
        if ranked.row.uuid == target_uuid:
            return ranked.best_distance
    raise AssertionError(f"{target_uuid} was not in the fused pool at all")


async def test_a_lone_write_offers_nothing(tmp_path: Path) -> None:
    """No candidates exist yet, so the search finds none — an empty tuple, not an error."""
    async with harness(tmp_path) as h:
        uuid = await h.write(gist=_GIST_A, content=_CONTENT_A)
        offered = await offer(
            h.store.connection,
            created_uuid=uuid,
            ctx=ctx(),
            settings=h.read_call().settings,
            policy=DedupPolicy(dedup_threshold=0.80, dedup_max=3),
        )
        assert offered == ()


async def test_a_near_identical_row_is_offered_back(tmp_path: Path) -> None:
    """Two rows built from near-identical prose: the second's dedup search finds the first."""
    async with harness(tmp_path) as h:
        first = await h.write(gist=_GIST_A, content=_CONTENT_A)
        second = await h.write(gist=_GIST_B, content=_CONTENT_B)
        offered = await offer(
            h.store.connection,
            created_uuid=second,
            ctx=ctx(),
            settings=h.read_call().settings,
            policy=DedupPolicy(dedup_threshold=0.0, dedup_max=3),
        )
        assert [candidate.uuid for candidate in offered] == [first]
        assert offered[0].rank == 1
        assert offered[0].gist == _GIST_A


async def test_dedup_max_zero_returns_nothing_and_runs_no_search(tmp_path: Path) -> None:
    """`dedup_max = 0` is a legal config value (`schema.md` §Bounds: 0-20) and means the search
    itself never runs — checked by asserting `internal_query` is never called, not only that no
    event was written or nothing was returned: an implementation could run the search, discard
    every result and still pass a weaker check, which would incur the search's latency and its
    failure modes on a call the config asked to skip entirely."""
    async with harness(tmp_path) as h:
        await h.write(gist=_GIST_A, content=_CONTENT_A)
        await h.clear_events()
        second = await h.write(gist=_GIST_B, content=_CONTENT_B)
        before = await h.events()
        with unittest.mock.patch(
            "zikaron.core.write.dedup.internal_query",
            side_effect=AssertionError("dedup_max=0 must not run the search at all"),
        ):
            offered = await offer(
                h.store.connection,
                created_uuid=second,
                ctx=ctx(),
                settings=h.read_call().settings,
                policy=DedupPolicy(dedup_threshold=0.0, dedup_max=0),
            )
        assert offered == ()
        after = await h.events()
        assert after == before


async def test_a_row_below_threshold_is_not_offered(tmp_path: Path) -> None:
    """An unrelated row scores low on the directed cosine and never clears the floor."""
    async with harness(tmp_path) as h:
        await h.write(gist=_GIST_UNRELATED, content=_CONTENT_UNRELATED)
        second = await h.write(gist=_GIST_B, content=_CONTENT_B)
        offered = await offer(
            h.store.connection,
            created_uuid=second,
            ctx=ctx(),
            settings=h.read_call().settings,
            policy=DedupPolicy(dedup_threshold=0.999, dedup_max=3),
        )
        assert offered == ()


async def test_dedup_excludes_the_row_just_created(tmp_path: Path) -> None:
    """A row is its own nearest neighbour; `Consumer.DEDUP`'s `excludes_self` keeps it off its own
    offer list even at a threshold of 0."""
    async with harness(tmp_path) as h:
        uuid = await h.write(gist=_GIST_A, content=_CONTENT_A)
        offered = await offer(
            h.store.connection,
            created_uuid=uuid,
            ctx=ctx(),
            settings=h.read_call().settings,
            policy=DedupPolicy(dedup_threshold=0.0, dedup_max=20),
        )
        assert uuid not in {candidate.uuid for candidate in offered}


async def test_dedup_excludes_inactive_rows(tmp_path: Path) -> None:
    """A retired or superseded candidate is never offered: the offered resolution is `amend`,
    which `inactive_row` rejects, so it would be an offer the agent cannot take.
    `eligibility.CONSUMER_FILTERS[DEDUP]` restricts the search to `active = 1`."""
    async with harness(tmp_path) as h:
        retired = await h.write(gist=_GIST_A, content=_CONTENT_A)
        await h.retire(retired)
        second = await h.write(gist=_GIST_B, content=_CONTENT_B)
        offered = await offer(
            h.store.connection,
            created_uuid=second,
            ctx=ctx(),
            settings=h.read_call().settings,
            policy=DedupPolicy(dedup_threshold=0.0, dedup_max=20),
        )
        assert retired not in {candidate.uuid for candidate in offered}


async def test_dedup_max_caps_the_returned_count(tmp_path: Path) -> None:
    """Three near-identical rows exist; `dedup_max = 1` still returns the whole pool's best one."""
    async with harness(tmp_path) as h:
        variants = [
            (_GIST_A, _CONTENT_A),
            (_GIST_B, _CONTENT_B),
            ("protobuf codegen fails silently on staging still", _CONTENT_A + " still"),
        ]
        uuids = [await h.write(gist=gist, content=content) for gist, content in variants]
        newest = await h.write(gist="protobuf codegen fails silently again", content=_CONTENT_A)
        offered = await offer(
            h.store.connection,
            created_uuid=newest,
            ctx=ctx(),
            settings=h.read_call().settings,
            policy=DedupPolicy(dedup_threshold=0.0, dedup_max=1),
        )
        assert len(offered) == 1
        assert offered[0].uuid in uuids
        assert offered[0].rank == 1


async def test_a_lexical_only_pooled_row_is_still_scored_by_its_exact_directed_cosine(
    tmp_path: Path,
) -> None:
    """The regression case for the exact-cosine fix: a candidate the dense arm's `fusion_depth`
    cut excludes from its **fused** rows (its stored vector is pushed far from the query, and two
    distractors outrank it) but which the lexical arm still finds through a shared exact term must
    still be offered once its *true* `s(new row -> candidate)` clears the floor — `schema.md`
    defines that quantity over a candidate's chunks with no dependence on `fusion_depth` or on
    which arm happened to surface the row."""
    async with harness(tmp_path, overrides="[retrieval]\nfusion_depth = 1\n") as h:
        candidate = await h.write(gist="a shared_marker_term memory", content=_CONTENT_A)

        # Push the candidate's stored chunk vector maximally far from anything the dense arm
        # will search with, while its FTS postings — built from the same gist/content the row
        # still holds — are untouched, so the lexical arm still finds it on the shared term.
        rows = await h.store.connection.execute_fetchall(
            "SELECT chunk_id FROM memory_chunk WHERE memory_uuid = ? AND part_index = 0",
            (candidate,),
        )
        (chunk_id,) = next(iter(rows))
        far_vector = query_vector_for("as far from this as any vector can be", "unrelated noise")
        await h.store.connection.execute("DELETE FROM memory_vec WHERE rowid = ?", (chunk_id,))
        await h.store.connection.execute(
            "INSERT INTO memory_vec (rowid, embedding) VALUES (?, ?)", (chunk_id, far_vector)
        )
        await h.store.connection.commit()

        # Two distractors the dense arm ranks ahead of `candidate` at `fusion_depth = 1`: with the
        # candidate's own vector pushed far, any two other rows outrank it, which is what pushes
        # it out of the dense arm's **fused** rows even though the arm's overfetch loop, on a
        # small store, still scores every row while probing. The lexical arm still returns
        # `candidate` on the shared term regardless of dense rank.
        await h.write(gist="an unrelated distractor row one", content=_CONTENT_UNRELATED)
        await h.write(gist="an unrelated distractor row two", content=_CONTENT_UNRELATED + " two")

        new_row = await h.write(gist="a shared_marker_term note", content=_CONTENT_B)
        outcome_pool_has_no_dense_score_for_candidate = await _pool_best_distance_for(
            h, new_row_uuid=new_row, target_uuid=candidate
        )
        assert outcome_pool_has_no_dense_score_for_candidate is None

        # `FakeEncoder`'s hash-seeded vectors carry no semantic relationship between texts, so the
        # actual directed cosine between two arbitrary rows can legitimately be negative — a
        # threshold of `-1.0` (below any real cosine) isolates "is the candidate offered at all",
        # which is what this test is about, from "does it clear 0.80", which it is not.
        offered = await offer(
            h.store.connection,
            created_uuid=new_row,
            ctx=ctx(),
            settings=h.read_call().settings,
            policy=DedupPolicy(dedup_threshold=-1.0, dedup_max=3),
        )
        assert candidate in {near_duplicate.uuid for near_duplicate in offered}


async def test_exact_directed_cosine_reads_the_minimum_across_all_of_a_candidates_chunks(
    tmp_path: Path,
) -> None:
    """`schema.md`'s `s(X -> Y)` is the best cosine against **any** chunk of Y, not only Y's
    first — the actual property round 2's finding asked to be pinned independently of the
    lexical-only pool shape. A two-chunk candidate has its first chunk's vector pushed far and its
    second set exactly to the query vector, so the true minimum distance is 0 (cosine 1.0) and is
    reachable only by a computation that reads chunk 1 as well as chunk 0. `_exact_directed_
    cosines` is exercised directly, independent of `offer`'s dense-arm-exclusion machinery, which
    the sibling regression test above already covers for the pool-membership half of the fix."""
    overrides = "[indexing]\nchunk_max_tokens = 64\n"
    async with harness(tmp_path, overrides=overrides) as h:
        # `FakeEncoder` counts whitespace-delimited tokens: 60 distinct words per paragraph stays
        # under the 64-token budget alone, and the gist-plus-separator assembly pushes the
        # combined text over it, forcing exactly two chunks.
        first_paragraph = " ".join(f"far{i}" for i in range(60))
        second_paragraph = " ".join(f"near{i}" for i in range(60))
        candidate = await h.write(
            gist="a memory", content=f"{first_paragraph}\n\n{second_paragraph}"
        )
        rows = await h.store.connection.execute_fetchall(
            "SELECT chunk_id, part_index FROM memory_chunk WHERE memory_uuid = ? "
            "ORDER BY part_index",
            (candidate,),
        )
        chunk_ids = [(int(chunk_id), int(part)) for chunk_id, part in rows]
        assert [part for _chunk_id, part in chunk_ids] == [0, 1], (
            "fixture assumption: candidate must land in exactly two chunks for this test to mean "
            "anything about best-of-all-chunks scoring"
        )
        (chunk_zero_id, _), (chunk_one_id, _) = chunk_ids

        query_vector = query_vector_for("the query", "text")
        far_vector = query_vector_for("as far from this as any vector can be", "unrelated noise")
        for chunk_id, vector in ((chunk_zero_id, far_vector), (chunk_one_id, query_vector)):
            await h.store.connection.execute("DELETE FROM memory_vec WHERE rowid = ?", (chunk_id,))
            await h.store.connection.execute(
                "INSERT INTO memory_vec (rowid, embedding) VALUES (?, ?)", (chunk_id, vector)
            )
        await h.store.connection.commit()

        cosines = await exact_directed_cosines(
            h.store.connection, [candidate], query_vector=query_vector
        )
        assert cosines[candidate] == pytest.approx(1.0, abs=1e-4)


async def _vec_read_count_for_n_lexical_only_candidates(h: Harness, n: int) -> tuple[int, int]:
    """Run `offer` against `n` candidates whose stored vectors are pushed far from the query, and
    return `(lexical_only_count, vec_reads)` — how many of them the dense arm's fused rows
    genuinely excluded, and how many statements touching `memory_vec` `offer` took overall. Both
    are measured rather than assumed, because whether a fixed-size distractor set actually excludes
    every far-pushed candidate at a given `fusion_depth` depends on details of the fused pool this
    helper does not control precisely enough to state as a guarantee."""
    far_vector = query_vector_for("as far from this as any vector can be", "unrelated noise")
    for index in range(n):
        candidate = await h.write(gist=f"a shared_marker_term memory {index}", content=_CONTENT_A)
        rows = await h.store.connection.execute_fetchall(
            "SELECT chunk_id FROM memory_chunk WHERE memory_uuid = ? AND part_index = 0",
            (candidate,),
        )
        (chunk_id,) = next(iter(rows))
        await h.store.connection.execute("DELETE FROM memory_vec WHERE rowid = ?", (chunk_id,))
        await h.store.connection.execute(
            "INSERT INTO memory_vec (rowid, embedding) VALUES (?, ?)", (chunk_id, far_vector)
        )
        await h.store.connection.commit()
    # `2n` distractors with genuinely distinct vectors, comfortably more than `n`, so the dense
    # arm's own fused rows are filled well before any far-pushed candidate could rank among them.
    for index in range(2 * n):
        await h.write(
            gist=f"an unrelated distractor row {index}", content=f"{_CONTENT_UNRELATED} {index}"
        )
    new_row = await h.write(gist="a shared_marker_term note", content=_CONTENT_B)

    settings = h.read_call().settings
    query = await internal_query(
        h.store.connection, memory_uuid=new_row, max_terms=settings.fts_query_max_terms
    )
    retrieved = await retrieve(
        h.store.connection,
        query=query,
        scope=Scope(Consumer.DEDUP, exclude_uuid=new_row),
        settings=settings,
    )
    lexical_only_count = sum(1 for ranked in retrieved.pool if ranked.best_distance is None)

    real_fetchall = h.store.connection.execute_fetchall
    vec_reads = 0

    async def _counting_fetchall(sql: str, *args: object, **kwargs: object) -> object:
        nonlocal vec_reads
        if "memory_vec" in sql:
            vec_reads += 1
        return await real_fetchall(sql, *args, **kwargs)

    with unittest.mock.patch.object(
        h.store.connection, "execute_fetchall", side_effect=_counting_fetchall
    ):
        await offer(
            h.store.connection,
            created_uuid=new_row,
            ctx=ctx(),
            settings=settings,
            policy=DedupPolicy(dedup_threshold=-1.0, dedup_max=20),
        )
    return lexical_only_count, vec_reads


async def test_lexical_only_candidate_scoring_cost_does_not_grow_with_candidate_count(
    tmp_path: Path,
) -> None:
    """The round-2 cost fix, proved as scale-invariance rather than as one fixed magic number: the
    number of statements touching `memory_vec` must be the **same** whether the fused pool holds
    3 lexical-only candidates or 6 of them — never one further statement per additional candidate,
    which a one-read-per-candidate regression would show as growing linearly with the count."""
    three_dir = tmp_path / "three"
    six_dir = tmp_path / "six"
    three_dir.mkdir()
    six_dir.mkdir()
    async with harness(three_dir, overrides="[retrieval]\nfusion_depth = 3\n") as three:
        lexical_only_three, reads_for_three = await _vec_read_count_for_n_lexical_only_candidates(
            three, 3
        )
    async with harness(six_dir, overrides="[retrieval]\nfusion_depth = 6\n") as six:
        lexical_only_six, reads_for_six = await _vec_read_count_for_n_lexical_only_candidates(
            six, 6
        )
    assert lexical_only_three > 0, "fixture assumption: some candidates must be lexical-only"
    assert lexical_only_six > lexical_only_three, (
        "fixture assumption: the six-candidate run must have strictly more lexical-only "
        "candidates than the three-candidate run, or the two runs prove nothing about scaling"
    )
    assert reads_for_six == reads_for_three


async def test_dedup_offered_events_are_filed_under_the_candidate_not_the_new_row(
    tmp_path: Path,
) -> None:
    """`DedupOfferedDetail`'s own docstring: the matured-outcome signal joins on the record an agent
    might amend, which is the candidate — so the event's `memory_uuid` is the candidate's, and
    `detail.created_uuid` is what names the new row."""
    async with harness(tmp_path) as h:
        first = await h.write(gist=_GIST_A, content=_CONTENT_A)
        await h.clear_events()
        second = await h.write(gist=_GIST_B, content=_CONTENT_B)
        await h.clear_events()
        await offer(
            h.store.connection,
            created_uuid=second,
            ctx=ctx(),
            settings=h.read_call().settings,
            policy=DedupPolicy(dedup_threshold=0.0, dedup_max=3),
        )
        await h.store.connection.commit()
        events = await h.events()
        assert len(events) == 1
        kind, memory_uuid, detail = events[0]
        assert kind == EventKind.DEDUP_OFFERED.value
        assert memory_uuid == first
        assert detail["created_uuid"] == second
        assert detail["rank"] == 1
        assert set(detail) == {"created_uuid", "cosine", "rank"}


async def test_dedup_offer_ordering_is_deterministic(tmp_path: Path) -> None:
    """The same store and the same new row's search produce byte-identical candidates twice
    (`coding-standards.md` §4: determinism is asserted, not assumed)."""
    async with harness(tmp_path) as h:
        await h.write(gist=_GIST_A, content=_CONTENT_A)
        await h.write(gist=_GIST_UNRELATED, content=_CONTENT_UNRELATED)
        second = await h.write(gist=_GIST_B, content=_CONTENT_B)
        settings = h.read_call().settings
        policy = DedupPolicy(dedup_threshold=0.0, dedup_max=20)
        first_run = await offer(
            h.store.connection, created_uuid=second, ctx=ctx(), settings=settings, policy=policy
        )
        await h.store.connection.commit()
        second_run = await offer(
            h.store.connection, created_uuid=second, ctx=ctx(), settings=settings, policy=policy
        )
        assert first_run == second_run
