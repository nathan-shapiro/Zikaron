"""The knowledge-base management methods: their wire shapes, and what they refuse.

What is checked here is the boundary — raw parameters in, the wire object out, and a refusal that
arrives as a code a caller can branch on rather than as an internal error. The lifecycle behind it
is tested against `zikaron.core.knowledge`'s own modules, where it does not have to travel through
a dispatch table first.

**No build actually runs.** `add` and `refresh` spawn a detached indexer, which is a real process
doing a minute of real work; every test here replaces that spawn and asserts what was asked for
instead. The spawn's own behaviour has its own suite.
"""

import os
from pathlib import Path

import pytest

from tests.fake_encoder import FakeEncoder
from tests.knowledge_fixtures import (
    DEAD_PID,
    build_settings,
    corpus_root,
    write_meta,
    write_tree,
)
from tests.service_fixtures import envelope, open_context
from zikaron.core.clock import timestamp
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.knowledge import lifecycle, lock, meta, registry, reporting
from zikaron.core.knowledge import paths as knowledge_paths
from zikaron.core.knowledge.errors import (
    CorpusRootMissingError,
    InvalidNameError,
    UnknownKnowledgeBaseError,
)
from zikaron.knowledge.indexer import detach
from zikaron.service import dispatch_knowledge, paths
from zikaron.service.context import ServiceContext

#: Every corpus a spawn was asked for, in order, as `(name, project, full)`.
type Spawns = list[tuple[str, Path, bool]]


@pytest.fixture(autouse=True)
def spawns(monkeypatch: pytest.MonkeyPatch) -> Spawns:
    """Replace the detached spawn with a record of what it was asked to start.

    **Autouse, because no test in this file wants a real one.** A real spawn starts a real indexer
    against a real corpus — a minute of work, and a second process writing the very database these
    assertions then read; a test that merely forgot to ask for this fixture would get that silently.
    What the dispatch layer owes is *that a build was asked for, for the right corpus, in the right
    project*, and that is what this records. Tests that check the record take it as an argument;
    the rest are covered without naming it.
    """
    recorded: Spawns = []

    def fake_spawn(name: str, *, project: Path, full: bool = False) -> list[str]:
        recorded.append((name, project, full))
        return ["python", "-m", "zikaron.knowledge.indexer", "--", name]

    monkeypatch.setattr(detach, "spawn", fake_spawn)
    return recorded


async def _add(
    ctx: ServiceContext, tmp_path: Path, name: str = "docs", **extra: object
) -> dict[str, object]:
    params: dict[str, object] = {
        "name": name,
        "path": str(corpus_root(tmp_path, name)),
        "description": f"the {name} corpus",
        **extra,
    }
    result = await dispatch_knowledge.knowledge_add(ctx.store.connection, ctx, envelope(), params)
    payload = result.as_json()
    assert isinstance(payload, dict)
    return payload


async def _call(ctx: ServiceContext, method: str, params: dict[str, object]) -> dict[str, object]:
    handler = dispatch_knowledge.KNOWLEDGE_METHODS[method]
    result = await handler(ctx.store.connection, ctx, envelope(), params)
    payload = result.as_json()
    assert isinstance(payload, dict)
    return payload


def _only(payload: dict[str, object]) -> dict[str, object]:
    bases = payload["knowledge_bases"]
    assert isinstance(bases, list)
    (one,) = bases
    assert isinstance(one, dict)
    return one


async def _database_of(ctx: ServiceContext, name: str) -> Path:
    """One corpus's own database file, resolved the way the product resolves it.

    Through the registry rather than by globbing the directory: the filename is a generated id, so
    a glob answers for whichever corpus happens to be there and is wrong the moment a test has
    two.
    """
    registered = await registry.require(ctx.store.connection, name)
    return knowledge_paths.knowledge_db_path(ctx.store_directory, registered.id)


class TestAdd:
    async def test_it_registers_the_corpus_and_starts_a_build(
        self, tmp_path: Path, spawns: Spawns
    ) -> None:
        async with open_context(tmp_path) as ctx:
            payload = await _add(ctx, tmp_path)

            entry = _only(payload)
            assert entry["name"] == "docs"
            assert entry["description"] == "the docs corpus"
            assert entry["outcome"] == "started"
            assert entry["state"] == "reindex_required", (
                "nothing is stored until the first build completes, which is the truth"
            )
            assert spawns == [("docs", paths.scope_of(ctx.store_directory), False)]

    async def test_the_project_a_build_is_started_in_is_the_store_s_own(
        self, tmp_path: Path, spawns: Spawns
    ) -> None:
        """The child takes a project and resolves a store from it, so passing the wrong one would
        build a different store's corpus — silently, since both would succeed."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            (_name, project, _full) = spawns[0]
            assert project / ".zikaron" == ctx.store_directory

    async def test_it_reports_the_git_probe_it_just_ran(self, tmp_path: Path) -> None:
        """A caller asking for `tracked` outside a work tree gets `off`, and learning that at
        creation is the whole reason `add` probes at all."""
        async with open_context(tmp_path) as ctx:
            payload = await _add(ctx, tmp_path, git_mode="tracked")
            assert payload["requested_git_mode"] == "tracked"
            assert payload["effective_git_mode"] == "off"

    async def test_the_per_corpus_effective_mode_is_the_last_build_s_and_is_not_the_probe(
        self, tmp_path: Path
    ) -> None:
        """Two fields, two subjects: the probe describes configuration as accepted, and the
        per-corpus one describes what a completed build actually used — `null` until there is
        one."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            entry = _only(await _call(ctx, "knowledge_status", {"knowledge_base": "docs"}))
            assert entry["git_mode_effective"] is None

    async def test_settings_reach_the_corpus_s_own_meta(self, tmp_path: Path) -> None:
        """A setting accepted and not persisted would be silently undone by the next build."""
        async with open_context(tmp_path) as ctx:
            await _add(
                ctx,
                tmp_path,
                include=["*.md"],
                exclude=["draft/*"],
                git_mode="off",
                max_file_bytes=4096,
            )
            entry = _only(await _call(ctx, "knowledge_status", {"knowledge_base": "docs"}))
            assert entry["include"] == ["*.md"]
            assert entry["exclude"] == ["draft/*"]
            assert entry["git_mode"] == "off"
            assert entry["max_file_bytes"] == 4096

    async def test_absent_globs_mean_no_patterns_rather_than_a_rejection(
        self, tmp_path: Path
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            entry = _only(await _call(ctx, "knowledge_status", {"knowledge_base": "docs"}))
            assert entry["include"] == []
            assert entry["exclude"] == []

    async def test_a_taken_name_is_refused_rather_than_reconfigured(self, tmp_path: Path) -> None:
        """Silently reconfiguring a corpus underneath whoever created it is worse than a failed
        call."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            with pytest.raises(ZikaronError) as raised:
                await _add(ctx, tmp_path)
            assert raised.value.code is ErrorCode.KNOWLEDGE_BASE_EXISTS
            assert raised.value.data["name"] == "docs"

    async def test_a_taken_name_is_reported_as_the_registry_stores_it(self, tmp_path: Path) -> None:
        """The normalized spelling, because that is what `list` reports and what a caller has to
        supply to reach the same corpus again."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            with pytest.raises(ZikaronError) as raised:
                await _add(ctx, tmp_path, name="DOCS")
            assert raised.value.data["name"] == "docs"

    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            pytest.param({"name": "   "}, "name", id="blank name"),
            pytest.param({"path": "/definitely/not/here"}, "path", id="absent root"),
            pytest.param({"git_mode": "sometimes"}, "git_mode", id="unknown git mode"),
        ],
    )
    async def test_a_value_it_cannot_accept_is_a_bounds_rejection(
        self, tmp_path: Path, spawns: Spawns, overrides: dict[str, object], field: str
    ) -> None:
        """Rejections of a parameter value rather than statements about a corpus, so they carry the
        code whose payload names the field to try again with."""
        async with open_context(tmp_path) as ctx:
            params: dict[str, object] = {
                "name": "docs",
                "path": str(corpus_root(tmp_path)),
                "description": "a corpus",
                **overrides,
            }
            with pytest.raises(ZikaronError) as raised:
                await dispatch_knowledge.knowledge_add(
                    ctx.store.connection, ctx, envelope(), params
                )
            assert raised.value.code is ErrorCode.BOUNDS
            assert raised.value.data["field"] == field
            assert spawns == [], "nothing is built for a request that was refused"

    async def test_an_absent_root_carries_the_path_rather_than_a_sentence(
        self, tmp_path: Path
    ) -> None:
        """`actual` is the refused path **as resolved**, so a client can show where the request
        actually landed. Built from the exception's own field rather than from its message, since
        a message is prose about the refusal and gets reworded — after which a field claiming to
        hold a path holds a paragraph."""
        async with open_context(tmp_path) as ctx:
            absent = tmp_path / "no-such-tree"
            with pytest.raises(ZikaronError) as raised:
                await _add(ctx, tmp_path, path=str(absent), name="gone")
            assert raised.value.code is ErrorCode.BOUNDS
            assert raised.value.data["field"] == "path"
            assert raised.value.data["actual"] == str(absent)

    async def test_an_absent_relative_root_is_reported_where_it_resolved_to(
        self, tmp_path: Path
    ) -> None:
        """The case that tells *as resolved* apart from *as supplied*: an absolute fixture cannot,
        since the two strings are equal. A caller that sent `nope` needs to be shown the directory
        that was actually looked for, which is the project's — not its own word back."""
        async with open_context(tmp_path) as ctx:
            with pytest.raises(ZikaronError) as raised:
                await _add(ctx, tmp_path, path="nope", name="gone")
            assert raised.value.code is ErrorCode.BOUNDS
            assert raised.value.data["actual"] == str(tmp_path / "nope")

    async def test_a_tilde_naming_no_known_user_is_a_bounds_rejection(self, tmp_path: Path) -> None:
        """The other side of passing `~` through untouched: it reaches expansion, and expansion can
        fail. A caller that typed a path must be told its path was refused, not handed an internal
        error — which is what an exception with no wire code becomes by the time it reaches a
        model."""
        async with open_context(tmp_path) as ctx:
            with pytest.raises(ZikaronError) as raised:
                await _add(ctx, tmp_path, path="~no-such-user-zikaron/docs", name="gone")
            assert raised.value.code is ErrorCode.BOUNDS
            assert raised.value.data["field"] == "path"

    async def test_a_home_relative_root_is_expanded_rather_than_joined(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A leading `~` names the home directory, so joining it to the project first would look
        for `<project>/~/...` — which expands to nothing, since expansion only applies at the
        front of a path."""
        home = tmp_path / "home"
        corpus = home / "notes"
        corpus.mkdir(parents=True)
        (corpus / "a.md").write_text("a line\n", encoding="utf-8")
        monkeypatch.setenv("HOME", str(home))
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path, path="~/notes")
            entry = _only(await _call(ctx, "knowledge_status", {"knowledge_base": "docs"}))
            assert entry["root_path"] == str(corpus)

    async def test_a_size_cap_outside_the_declared_range_is_a_bounds_rejection(
        self, tmp_path: Path, spawns: Spawns
    ) -> None:
        """A number the caller typed, refused in the caller's own terms. It used to surface as a
        configuration complaint, which sends a caller looking in a file for a typo that is in its
        request; `limit` now carries the same range phrasing the stored-value path uses, so the
        two cannot come to describe one range differently."""
        bounds, expected = meta.bounds_for(meta.MAX_FILE_BYTES_KEY)
        below = bounds.minimum - 1
        async with open_context(tmp_path) as ctx:
            with pytest.raises(ZikaronError) as raised:
                await _add(ctx, tmp_path, max_file_bytes=below)
            assert raised.value.code is ErrorCode.BOUNDS
            assert raised.value.data["field"] == meta.MAX_FILE_BYTES_KEY
            assert raised.value.data["limit"] == expected
            assert raised.value.data["actual"] == below
            assert spawns == []

    async def test_a_relative_path_resolves_against_the_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not against the service's working directory, which is inherited from whichever client
        spawned it and which nothing an agent can see reports. Resolving there would index some
        unrelated tree, store the result as an absolute path that looks deliberate, and answer
        searches from it.

        A **decoy** of the same name sits in that working directory, so the wrong resolution
        succeeds rather than failing on a missing path — which is the whole shape of the defect.
        Without it this passes against a service whose cwd merely happens to hold nothing."""
        expected = corpus_root(tmp_path, "docs")
        elsewhere = tmp_path / "elsewhere"
        (elsewhere / "docs").mkdir(parents=True)
        (elsewhere / "docs" / "decoy.md").write_text("not the corpus\n", encoding="utf-8")
        monkeypatch.chdir(elsewhere)
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path, path="docs")
            entry = _only(await _call(ctx, "knowledge_status", {"knowledge_base": "docs"}))
            assert entry["root_path"] == str(expected)


class TestList:
    async def test_an_empty_store_lists_nothing(self, tmp_path: Path) -> None:
        """Both keys present and empty, rather than absent: a caller reads their contents."""
        async with open_context(tmp_path) as ctx:
            assert await _call(ctx, "knowledge_list", {}) == {
                "knowledge_bases": [],
                "orphans": [],
            }

    async def test_it_carries_the_choosing_fields_and_not_the_diagnostic_ones(
        self, tmp_path: Path
    ) -> None:
        """`list` is `status` projected down: same names, same vocabulary, fewer of them."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            entry = _only(await _call(ctx, "knowledge_list", {}))
            assert set(entry) == {
                "name",
                "description",
                "state",
                "files_indexed",
                "files_remaining",
            }


class TestStatus:
    async def test_it_carries_the_diagnostic_half(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            entry = _only(await _call(ctx, "knowledge_status", {"knowledge_base": "docs"}))
            assert entry["root_path"] == str(corpus_root(tmp_path))
            assert entry["chunks"] == 0
            assert entry["lock"] is None
            assert entry["last_scan_completed_at"] is None

    async def test_the_skip_breakdown_names_every_reason(self, tmp_path: Path) -> None:
        """Reported by the name a response uses rather than by the `meta` key that holds it, and
        all nine every time — a reason missing from the breakdown is a count nothing adds up."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            entry = _only(await _call(ctx, "knowledge_status", {"knowledge_base": "docs"}))
            skipped = entry["skipped"]
            assert isinstance(skipped, dict)
            assert set(skipped) == {
                "binary",
                "denied_extension",
                "over_size_cap",
                "excluded_by_glob",
                "gitignored",
                "decode_error",
                "symlink",
                "unreadable",
                "pruned_directories",
            }

    async def test_the_four_search_counters_are_reported(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            entry = _only(await _call(ctx, "knowledge_status", {"knowledge_base": "docs"}))
            assert entry["searches"] == 0
            assert entry["searches_empty"] == 0
            assert entry["results_returned"] == 0
            assert entry["results_stale"] == 0

    async def test_naming_no_corpus_reports_every_one_and_the_orphans(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path, name="docs")
            await _add(ctx, tmp_path, name="runbooks")
            payload = await _call(ctx, "knowledge_status", {})
            bases = payload["knowledge_bases"]
            assert isinstance(bases, list)
            assert len(bases) == 2
            assert payload["orphans"] == []

    async def test_naming_one_corpus_reports_no_orphans(self, tmp_path: Path) -> None:
        """An orphan belongs to no knowledge base, so attaching one to a report about a named
        corpus would be attaching it arbitrarily. The key is present either way."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            (ctx.store_directory / "knowledge" / "not-a-registered-corpus.db").write_bytes(b"x")
            payload = await _call(ctx, "knowledge_status", {"knowledge_base": "docs"})
            assert payload["orphans"] == []

            whole = await _call(ctx, "knowledge_status", {})
            orphans = whole["orphans"]
            assert isinstance(orphans, list)
            assert len(orphans) == 1
            assert set(orphans[0]) == {"path", "name", "size_bytes"}

    async def test_an_unknown_name_is_its_own_code(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_status", {"knowledge_base": "absent"})
            assert raised.value.code is ErrorCode.KNOWLEDGE_BASE_UNKNOWN
            assert raised.value.data["name"] == "absent"

    async def test_a_held_lock_is_reported_with_who_holds_it(self, tmp_path: Path) -> None:
        """`state` alone cannot explain a lock that outlived the build that wrote it, which is the
        whole reason the holder is reported at all."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            await write_meta(
                await _database_of(ctx, "docs"),
                lock_pid=str(os.getpid()),
                lock_host=lock.this_host(),
                lock_started_at=timestamp(),
            )
            held = _only(await _call(ctx, "knowledge_status", {"knowledge_base": "docs"}))["lock"]
            assert isinstance(held, dict)
            assert held["pid"] == os.getpid()
            assert held["host"] == lock.this_host()
            assert held["live"] is True
            assert isinstance(held["age_seconds"], float)

    async def test_a_corpus_whose_database_will_not_open_reports_no_diagnostics(
        self, tmp_path: Path
    ) -> None:
        """Absent rather than zeroed: a zero no stored value backs is a confident answer to a
        question nothing could answer."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            (await _database_of(ctx, "docs")).write_bytes(b"this is not a SQLite database")
            entry = _only(await _call(ctx, "knowledge_status", {"knowledge_base": "docs"}))
            assert entry["state"] == "error"
            assert set(entry) == {
                "name",
                "description",
                "state",
                "files_indexed",
                "files_remaining",
            }

    async def test_a_blank_knowledge_base_names_the_parameter_that_was_sent(
        self, tmp_path: Path
    ) -> None:
        """This verb's name parameter is called `knowledge_base`, so that is what a caller has to
        resend. Reporting `name` would name a field the caller never sent."""
        async with open_context(tmp_path) as ctx:
            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_status", {"knowledge_base": "   "})
            assert raised.value.code is ErrorCode.BOUNDS
            assert raised.value.data["field"] == "knowledge_base"
            assert raised.value.data["actual"] == "   "

    async def test_a_refusal_with_no_wire_code_reaches_the_caller_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other half of leaving an unmapped class alone: it has to travel out of the handler
        as itself, so the service's own internal-error path reports it as the defect it is. Forced
        rather than waited for, because no reachable path raises one here — which is the point.
        """

        async def _raises(*_args: object, **_kwargs: object) -> object:
            raise CorpusRootMissingError("the indexed directory is gone, and no code for it")

        monkeypatch.setattr(reporting, "status", _raises)
        async with open_context(tmp_path) as ctx:
            with pytest.raises(CorpusRootMissingError):
                await _call(ctx, "knowledge_status", {"knowledge_base": "docs"})


class TestRename:
    async def test_it_answers_under_the_new_name(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            payload = await _call(
                ctx, "knowledge_rename", {"name": "docs", "new_name": "Design Records"}
            )
            assert _only(payload)["name"] == "design records"

    async def test_it_starts_no_build(self, tmp_path: Path, spawns: Spawns) -> None:
        """A registry update touching no file, so there is nothing to reindex and no `outcome` to
        report."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            spawns.clear()
            payload = await _call(ctx, "knowledge_rename", {"name": "docs", "new_name": "other"})
            assert spawns == []
            assert "outcome" not in _only(payload)

    async def test_a_blank_new_name_names_new_name_and_carries_it(self, tmp_path: Path) -> None:
        """Two parameters of this call are names, so *a name was blank* does not say which to
        resend — and reporting the one that was accepted invites a caller to change it and get the
        identical refusal back."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_rename", {"name": "docs", "new_name": "   "})
            assert raised.value.code is ErrorCode.BOUNDS
            assert raised.value.data["field"] == "new_name"
            assert raised.value.data["actual"] == "   "

    async def test_a_blank_current_name_names_that_one_instead(self, tmp_path: Path) -> None:
        """The other side of the same call, so the field is decided by which value was refused
        rather than by which verb was called."""
        async with open_context(tmp_path) as ctx:
            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_rename", {"name": " ", "new_name": "other"})
            assert raised.value.code is ErrorCode.BOUNDS
            assert raised.value.data["field"] == "name"
            assert raised.value.data["actual"] == " "

    async def test_both_names_blank_reports_the_one_that_was_validated_first(
        self, tmp_path: Path
    ) -> None:
        """Two identical blanks carry no evidence of which was meant, so the tie is broken by
        order — and the order that matters is the one the rename validates in, which is the current
        name before the new one. A caller resending on this answer fixes the value that actually
        stopped the call."""
        async with open_context(tmp_path) as ctx:
            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_rename", {"name": " ", "new_name": " "})
            assert raised.value.code is ErrorCode.BOUNDS
            assert raised.value.data["field"] == "name"
            assert raised.value.data["actual"] == " "

    async def test_a_taken_new_name_names_the_new_one(self, tmp_path: Path) -> None:
        """The payload names the corpus that already exists, not the one the caller was working
        from — which is the difference between a message a caller can act on and one it cannot."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path, name="docs")
            await _add(ctx, tmp_path, name="runbooks")
            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_rename", {"name": "docs", "new_name": "RUNBOOKS"})
            assert raised.value.code is ErrorCode.KNOWLEDGE_BASE_EXISTS
            assert raised.value.data["name"] == "runbooks"

    async def test_an_unknown_name_is_unknown(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_rename", {"name": "absent", "new_name": "other"})
            assert raised.value.code is ErrorCode.KNOWLEDGE_BASE_UNKNOWN


class TestRemove:
    async def test_without_confirm_it_refuses_and_says_what_would_go(self, tmp_path: Path) -> None:
        """Against a corpus that has actually been **built**, which is the only way the numbers
        mean anything. **Found by mutation**: an unbuilt corpus holds nothing, so a version
        reporting a constant zero — the same value as *there is nothing here to lose* — passed
        every assertion, and "says what would be destroyed" was a sentence with no measurement
        behind it."""
        async with open_context(tmp_path) as ctx:
            root = write_tree(tmp_path / "docs", {"a.md": b"the protobuf step fails silently\n"})
            await _call(
                ctx,
                "knowledge_add",
                {"name": "docs", "path": str(root), "description": "what was decided"},
            )
            await lifecycle.refresh(
                ctx.store_directory,
                ctx.store.connection,
                ctx.config,
                name="docs",
                build=build_settings(ctx.config, encoder=FakeEncoder()),
            )

            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_remove", {"name": "docs", "confirm": False})
            assert raised.value.code is ErrorCode.KNOWLEDGE_CONFIRM_REQUIRED
            assert raised.value.data["name"] == "docs"
            assert raised.value.data["files_indexed"] == 1
            chunks = raised.value.data["chunks"]
            assert isinstance(chunks, int)
            assert chunks >= 1

    async def test_omitting_confirm_entirely_is_the_same_refusal(self, tmp_path: Path) -> None:
        """The case the tool's own signature cannot produce and a direct RPC caller can, which is
        why the default is what decides it. **Found by mutation**: every other test here passes
        `confirm` explicitly, so flipping the default to `True` destroyed the corpus and every one
        of them still passed. The nearest comparable product ships the mirror image of this — a
        `confirm` field its published schema omits, so the guard exists and cannot be satisfied —
        and an omitted field that silently destroys is the worse half of the same mistake."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_remove", {"name": "docs"})
            assert raised.value.code is ErrorCode.KNOWLEDGE_CONFIRM_REQUIRED
            assert _only(await _call(ctx, "knowledge_list", {}))["name"] == "docs"

    async def test_an_unconfirmed_removal_destroys_nothing(self, tmp_path: Path) -> None:
        """Both halves of *nothing*: the registry still names the corpus, and its database is
        still on disk. Checking only the registry would pass against a removal that unlinked the
        file and failed before deleting the row, which is the worse of the two orders to be
        interrupted in."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            database = await _database_of(ctx, "docs")
            with pytest.raises(ZikaronError):
                await _call(ctx, "knowledge_remove", {"name": "docs", "confirm": False})
            assert _only(await _call(ctx, "knowledge_list", {}))["name"] == "docs"
            assert database.is_file()

    async def test_a_corpus_that_will_not_open_previews_an_unknown_amount(
        self, tmp_path: Path
    ) -> None:
        """`null`, never `0`. A present database refused for a permission or a schema reason may
        hold a fully built corpus, so `0` would be a confident number no stored value backs — on
        the one verb nothing undoes. `state` rides along to say that `files_indexed: 0` is a
        statement about availability rather than about content."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            (await _database_of(ctx, "docs")).write_bytes(b"this is not a SQLite database")
            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_remove", {"name": "docs", "confirm": False})
            assert raised.value.code is ErrorCode.KNOWLEDGE_CONFIRM_REQUIRED
            assert raised.value.data["chunks"] is None
            assert raised.value.data["state"] == "error"
            assert raised.value.data["files_indexed"] == 0

    async def test_a_corpus_with_no_database_previews_nothing_to_lose(self, tmp_path: Path) -> None:
        """The other half of the same distinction: an absent database holds nothing, and `0` is
        true of it rather than a guess. Told apart from the unreadable case by the state, since
        both are corpora with no diagnostic half to read a count out of."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            (await _database_of(ctx, "docs")).unlink()
            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_remove", {"name": "docs", "confirm": False})
            assert raised.value.code is ErrorCode.KNOWLEDGE_CONFIRM_REQUIRED
            assert raised.value.data["chunks"] == 0
            assert raised.value.data["state"] == "reindex_required"

    async def test_an_unknown_name_is_unknown_rather_than_needing_confirmation(
        self, tmp_path: Path
    ) -> None:
        """So a typo is never met with a prompt to confirm it — which would invite a caller to
        confirm a destruction of something that does not exist and learn nothing."""
        async with open_context(tmp_path) as ctx:
            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_remove", {"name": "absent", "confirm": False})
            assert raised.value.code is ErrorCode.KNOWLEDGE_BASE_UNKNOWN

    async def test_with_confirm_it_destroys_the_corpus_and_reports_what_went(
        self, tmp_path: Path
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            payload = await _call(ctx, "knowledge_remove", {"name": "docs", "confirm": True})
            assert payload["removed"] is True
            assert _only(payload)["name"] == "docs"
            unlinked = payload["files_unlinked"]
            assert isinstance(unlinked, list)
            assert unlinked
            assert (await _call(ctx, "knowledge_list", {}))["knowledge_bases"] == []

    async def test_the_final_snapshot_carries_the_diagnostic_half(self, tmp_path: Path) -> None:
        """It is the last chance to see what was destroyed: the corpus no longer exists to poll."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            payload = await _call(ctx, "knowledge_remove", {"name": "docs", "confirm": True})
            assert "root_path" in _only(payload)

    async def test_a_foreign_lock_refuses_the_removal_too(self, tmp_path: Path) -> None:
        """Nothing here can show a process on another machine has stopped, and the reading that
        assumes it has is the one that unlinks a database out from under a live writer."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            await write_meta(
                await _database_of(ctx, "docs"),
                lock_pid=str(DEAD_PID),
                lock_host="another-machine",
                lock_started_at=timestamp(),
            )
            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_remove", {"name": "docs", "confirm": True})
            assert raised.value.code is ErrorCode.KNOWLEDGE_BASE_BUSY

    async def test_a_live_build_refuses_the_removal(self, tmp_path: Path) -> None:
        """Refusing to unlink a database a writer may hold is recoverable; unlinking one it does
        hold is not.

        `holder` describes **who holds the lock** — a pid and a host a reader can go and look at —
        rather than restating the refusal or advising a retry. A payload field carrying a sentence
        is one a client can only print, and the point of naming the holder separately from the
        message is that it can be acted on."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            await write_meta(
                await _database_of(ctx, "docs"),
                lock_pid=str(os.getpid()),
                lock_host=lock.this_host(),
                lock_started_at=timestamp(),
            )
            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_remove", {"name": "docs", "confirm": True})
            assert raised.value.code is ErrorCode.KNOWLEDGE_BASE_BUSY
            assert raised.value.data["name"] == "docs"
            holder = raised.value.data["holder"]
            assert isinstance(holder, str)
            assert str(os.getpid()) in holder
            assert lock.this_host() in holder
            assert "retry" not in holder, "a value field is not the place for advice"
            assert "docs" not in holder, "the corpus is already named by its own field"


class TestRefresh:
    async def test_a_named_corpus_starts_one_build(self, tmp_path: Path, spawns: Spawns) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            spawns.clear()
            payload = await _call(ctx, "knowledge_refresh", {"name": "docs"})
            assert _only(payload)["outcome"] == "started"
            assert spawns == [("docs", paths.scope_of(ctx.store_directory), False)]

    async def test_full_is_carried_through_to_the_build(
        self, tmp_path: Path, spawns: Spawns
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            spawns.clear()
            await _call(ctx, "knowledge_refresh", {"name": "docs", "full": True})
            assert spawns == [("docs", paths.scope_of(ctx.store_directory), True)]

    async def test_no_name_reaches_every_corpus(self, tmp_path: Path, spawns: Spawns) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path, name="docs")
            await _add(ctx, tmp_path, name="runbooks")
            spawns.clear()
            payload = await _call(ctx, "knowledge_refresh", {})
            bases = payload["knowledge_bases"]
            assert isinstance(bases, list)
            assert {str(one["outcome"]) for one in bases} == {"started"}
            assert {name for name, _project, _full in spawns} == {"docs", "runbooks"}

    async def test_no_name_over_an_empty_store_is_an_empty_answer(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            assert await _call(ctx, "knowledge_refresh", {}) == {"knowledge_bases": []}

    async def test_a_live_build_is_reported_rather_than_raised(
        self, tmp_path: Path, spawns: Spawns
    ) -> None:
        """A refresh that met a running build got what it asked for: the corpus is being built.
        Raising here would make a loop of refreshes a loop of failures."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            await write_meta(
                await _database_of(ctx, "docs"),
                lock_pid=str(os.getpid()),
                lock_host=lock.this_host(),
                lock_started_at=timestamp(),
            )
            spawns.clear()
            payload = await _call(ctx, "knowledge_refresh", {"name": "docs"})
            assert _only(payload)["outcome"] == "already_indexing"
            assert spawns == [], "nothing was queued and nothing started"

    async def test_a_foreign_lock_is_already_indexing_too(
        self, tmp_path: Path, spawns: Spawns
    ) -> None:
        """A dead pid on *another* machine is not a dead build: this host cannot probe it, and
        treating the unprovable as stopped is what lets two indexers write one database."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            await write_meta(
                await _database_of(ctx, "docs"),
                lock_pid=str(DEAD_PID),
                lock_host="another-machine",
                lock_started_at=timestamp(),
            )
            spawns.clear()
            payload = await _call(ctx, "knowledge_refresh", {"name": "docs"})
            assert _only(payload)["outcome"] == "already_indexing"
            assert spawns == []

    async def test_a_dead_build_s_lock_does_not_stop_the_next_one(
        self, tmp_path: Path, spawns: Spawns
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            await write_meta(
                await _database_of(ctx, "docs"),
                lock_pid=str(DEAD_PID),
                lock_host=lock.this_host(),
                lock_started_at=timestamp(),
            )
            spawns.clear()
            payload = await _call(ctx, "knowledge_refresh", {"name": "docs"})
            assert _only(payload)["outcome"] == "started"

    async def test_a_corpus_with_no_database_reports_no_database(
        self, tmp_path: Path, spawns: Spawns
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            (await _database_of(ctx, "docs")).unlink()
            spawns.clear()
            payload = await _call(ctx, "knowledge_refresh", {"name": "docs"})
            assert _only(payload)["outcome"] == "no_database"
            assert spawns == []

    async def test_one_stopped_corpus_does_not_stop_the_others(
        self, tmp_path: Path, spawns: Spawns
    ) -> None:
        """The reason a sweep reports rather than raises: failing it for one corpus's sake would
        deny the rest a build they could have had."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path, name="docs")
            await _add(ctx, tmp_path, name="runbooks")
            (await _database_of(ctx, "docs")).unlink()
            spawns.clear()
            payload = await _call(ctx, "knowledge_refresh", {})
            bases = payload["knowledge_bases"]
            assert isinstance(bases, list)
            outcomes = {str(one["name"]): str(one["outcome"]) for one in bases}
            assert outcomes == {"docs": "no_database", "runbooks": "started"}
            assert [name for name, _project, _full in spawns] == ["runbooks"]

    async def test_an_unknown_name_fails_the_call(self, tmp_path: Path, spawns: Spawns) -> None:
        """With one name given there is nothing else in the answer, so the refusal is the whole
        answer and is an error rather than a success carrying only a refusal."""
        async with open_context(tmp_path) as ctx:
            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_refresh", {"name": "absent"})
            assert raised.value.code is ErrorCode.KNOWLEDGE_BASE_UNKNOWN
            assert spawns == []

    async def test_a_malformed_full_is_refused_before_the_store_is_consulted(
        self, tmp_path: Path, spawns: Spawns
    ) -> None:
        """Named with a corpus that does not exist, so a handler that read `full` after the sweep
        would answer *unknown knowledge base* and hide this until the caller fixed the name. A
        rejection of a parameter value is decided without consulting stored state, so it cannot be
        ordered behind a question about the store."""
        async with open_context(tmp_path) as ctx:
            with pytest.raises(ZikaronError) as raised:
                await _call(ctx, "knowledge_refresh", {"name": "absent", "full": "yes"})
            assert raised.value.code is ErrorCode.BOUNDS
            assert raised.value.data["field"] == "full"
            assert spawns == []


class TestTheWholeLifecycleThroughTheTools:
    """The six verbs as one path: create a corpus, fill it, search it, rename it
    and destroy it, without any step reaching for the command line.

    The build is the one step done in-process rather than through the spawn, because the spawn is
    a detached child and what it does is checked where it lives. What this asserts is that the
    corpus the tool created is one an ordinary build can fill and an ordinary search can answer
    from — which is the join the six verbs exist to make.
    """

    async def test_it(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            root = write_tree(tmp_path / "docs", {"a.md": b"the protobuf step fails silently\n"})
            created = await _call(
                ctx,
                "knowledge_add",
                {"name": "Design Docs", "path": str(root), "description": "what was decided"},
            )
            assert _only(created)["outcome"] == "started"

            await lifecycle.refresh(
                ctx.store_directory,
                ctx.store.connection,
                ctx.config,
                name="design docs",
                build=build_settings(ctx.config, encoder=FakeEncoder()),
            )
            assert _only(await _call(ctx, "knowledge_list", {}))["state"] == "ok"

            found = await _call(ctx, "knowledge_search", {"query": "protobuf"})
            groups = found["groups"]
            assert isinstance(groups, list)
            assert groups[0]["results"], "the corpus the tool created answers a search"

            renamed = await _call(
                ctx, "knowledge_rename", {"name": "design docs", "new_name": "records"}
            )
            assert _only(renamed)["name"] == "records"

            destroyed = await _call(ctx, "knowledge_remove", {"name": "records", "confirm": True})
            assert destroyed["removed"] is True
            assert (await _call(ctx, "knowledge_list", {}))["knowledge_bases"] == []

    async def test_a_search_advances_the_corpus_s_own_counters(self, tmp_path: Path) -> None:
        """The four §12 counters, through the path that actually raises them rather than through
        the function that writes them: a search that never reached the write would leave every
        one of these at zero and look identical to a corpus nobody asked."""
        async with open_context(tmp_path) as ctx:
            root = write_tree(tmp_path / "docs", {"a.md": b"the protobuf step fails silently\n"})
            await _call(
                ctx,
                "knowledge_add",
                {"name": "docs", "path": str(root), "description": "what was decided"},
            )
            await lifecycle.refresh(
                ctx.store_directory,
                ctx.store.connection,
                ctx.config,
                name="docs",
                build=build_settings(ctx.config, encoder=FakeEncoder()),
            )

            await _call(ctx, "knowledge_search", {"query": "protobuf"})
            entry = _only(await _call(ctx, "knowledge_status", {"knowledge_base": "docs"}))
            assert entry["searches"] == 1
            returned = entry["results_returned"]
            assert isinstance(returned, int)
            assert returned >= 1
            assert entry["searches_empty"] == 0

    async def test_a_corpus_that_cannot_serve_raises_no_counters(self, tmp_path: Path) -> None:
        """What keeps `searches_empty` an abstention rate rather than a mixture: an unbuilt corpus
        answers with an empty group without a query ever running against it, and counting that as
        a search that found nothing would bury the signal the counter exists for."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            await _call(ctx, "knowledge_search", {"query": "anything"})
            entry = _only(await _call(ctx, "knowledge_status", {"knowledge_base": "docs"}))
            assert entry["searches"] == 0
            assert entry["searches_empty"] == 0


class TestTranslatingARefusal:
    """The three branches of the translation that the six handlers cannot reach between them, and
    which exist for what a later edit might do rather than for what today's code does.

    Everything a handler *can* reach is tested through the handler, where reachability is part of
    what is being asserted."""

    def test_a_refused_name_this_call_never_sent_is_left_alone(self) -> None:
        """Every verb refuses only names it was handed, so a refusal naming something else means
        `core` rejected a value this layer does not know it asked for. That is a defect, and the
        rule for a defect is the same here as anywhere in this module: propagate it. Naming one of
        the parameters the call *did* send would hand a caller a refusal it would act on — it would
        resend a field that was never the problem."""
        assert (
            dispatch_knowledge._as_bounds(
                InvalidNameError("blank", value="  "), supplied={"name": "docs"}
            )
            is None
        )

    def test_a_refusal_with_no_wire_code_is_left_alone(self) -> None:
        """Answering an unmapped class with a nearby code would turn a defect into something a
        caller acts on. `None` means *propagate it*, and the handlers then let it reach the
        service's own internal-error path, where a bug belongs."""
        assert (
            dispatch_knowledge._translated(
                CorpusRootMissingError("the indexed directory is gone"),
                name="docs",
                taken="docs",
                supplied={"name": "docs"},
            )
            is None
        )

    def test_a_name_that_cannot_be_normalized_is_carried_as_it_was_written(self) -> None:
        """An error payload must not fail over the value it is reporting. No handler can reach this
        today — a blank name is refused as `bounds` long before any code that names a corpus — but
        the alternative to the fallback is a translation that raises inside an `except`, replacing
        a clean refusal with an internal error."""
        translated = dispatch_knowledge._translated(
            UnknownKnowledgeBaseError("nothing there"),
            name="   ",
            taken="   ",
            supplied={"name": "   "},
        )
        assert translated is not None
        assert translated.code is ErrorCode.KNOWLEDGE_BASE_UNKNOWN
        assert translated.data["name"] == "   "


class TestTheMethodTable:
    def test_it_names_every_knowledge_method_the_design_states(self) -> None:
        """One table, and the names are the wire contract: a handler registered under a name no
        client sends is a method that answers `METHOD_NOT_FOUND` in production and passes every
        test that calls the Python function directly.

        `knowledge_unlock` is here and is deliberately not an MCP tool — clearing a build lock is
        the operator judgement `lifecycle.unlock` describes — so this set is larger than the tool
        surface, which `zikaron.mcp.tool_names` declares and `test_mcp_server.py` asserts.
        """
        assert set(dispatch_knowledge.KNOWLEDGE_METHODS) == {
            "knowledge_search",
            "knowledge_list",
            "knowledge_status",
            "knowledge_add",
            "knowledge_remove",
            "knowledge_rename",
            "knowledge_refresh",
            "knowledge_unlock",
        }


class TestUnlock:
    """`knowledge_unlock` — the one management method with no MCP tool behind it."""

    async def test_it_clears_a_foreign_lock_and_names_who_held_it(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            await write_meta(
                await _database_of(ctx, "docs"),
                lock_pid=str(DEAD_PID),
                lock_host="another-machine",
                lock_started_at=timestamp(),
            )
            payload = await _call(ctx, "knowledge_unlock", {"knowledge_base": "docs"})

            cleared = payload["cleared"]
            assert isinstance(cleared, dict)
            assert cleared["pid"] == DEAD_PID
            assert cleared["host"] == "another-machine"
            assert set(cleared) == {"pid", "host", "started_at"}, (
                "no rendered sentence on the wire: a caller rebuilds the holder and renders it "
                "through `describe`, so one wording exists rather than one per surface"
            )

    async def test_no_lock_recorded_is_reported_rather_than_refused(self, tmp_path: Path) -> None:
        """Nothing to clear is the state the caller wanted, reached without this call acting."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            assert await _call(ctx, "knowledge_unlock", {"knowledge_base": "docs"}) == {
                "cleared": None
            }

    async def test_an_unknown_corpus_is_refused_by_the_name_the_caller_sent(
        self, tmp_path: Path
    ) -> None:
        async with open_context(tmp_path) as ctx:
            with pytest.raises(ZikaronError) as excinfo:
                await _call(ctx, "knowledge_unlock", {"knowledge_base": "absent"})
            assert excinfo.value.code is ErrorCode.KNOWLEDGE_BASE_UNKNOWN
            assert excinfo.value.data["name"] == "absent"

    async def test_a_corpus_whose_database_is_gone_is_dangling_not_internal_error(
        self, tmp_path: Path
    ) -> None:
        """The condition this method alone can reach, and the reason it has a code at all.

        `knowledge_refresh` meets the same corpus through `builds.plan`, which reports it as the
        `no_database` outcome rather than raising — so without a code here it would have been the
        one reachable refusal answering `internal_error`.
        """
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            (await _database_of(ctx, "docs")).unlink()
            with pytest.raises(ZikaronError) as excinfo:
                await _call(ctx, "knowledge_unlock", {"knowledge_base": "docs"})
            assert excinfo.value.code is ErrorCode.KNOWLEDGE_BASE_DANGLING
            assert excinfo.value.data["name"] == "docs"

    async def test_a_blank_name_is_refused_as_bounds_naming_the_parameter_sent(
        self, tmp_path: Path
    ) -> None:
        async with open_context(tmp_path) as ctx:
            with pytest.raises(ZikaronError) as excinfo:
                await _call(ctx, "knowledge_unlock", {"knowledge_base": "  "})
            assert excinfo.value.code is ErrorCode.BOUNDS
            assert excinfo.value.data["field"] == "knowledge_base"


class TestTheForegroundCommand:
    """The argv a build result carries is the spawn's own, never a second construction."""

    async def test_add_reports_the_argv_the_spawn_returned(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            entry = _only(await _add(ctx, tmp_path))
            assert entry["foreground_command"] == detach.spawn(
                "docs", project=paths.scope_of(ctx.store_directory)
            )

    async def test_add_reports_the_database_it_created(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            payload = await _add(ctx, tmp_path)
            assert payload["database_path"] == str(await _database_of(ctx, "docs"))

    async def test_refresh_reports_no_database_path(self, tmp_path: Path) -> None:
        """A refresh creates none, and a key present with a stale value is worse than an absent
        one."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            assert "database_path" not in await _call(ctx, "knowledge_refresh", {})

    async def test_a_corpus_no_build_started_for_carries_no_command(self, tmp_path: Path) -> None:
        """`foreground_command` describes a build that was started. An obstacle means none was, so
        offering a command to reproduce it would be offering one that reproduces nothing."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            await write_meta(
                await _database_of(ctx, "docs"),
                lock_pid=str(os.getpid()),
                lock_host=lock.this_host(),
                lock_started_at=timestamp(),
            )
            entry = _only(await _call(ctx, "knowledge_refresh", {"name": "docs"}))
            assert entry["outcome"] == "already_indexing"
            assert entry["foreground_command"] is None


class TestListCarriesOrphans:
    async def test_an_index_file_no_corpus_refers_to_is_reported(self, tmp_path: Path) -> None:
        """Without this, a caller reading an empty `knowledge_bases` in a directory holding index
        files concludes there is nothing there."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            database = await _database_of(ctx, "docs")
            await registry.delete(ctx.store.connection, name="docs")
            await ctx.store.connection.commit()

            orphans = (await _call(ctx, "knowledge_list", {}))["orphans"]
            assert isinstance(orphans, list)
            assert [Path(str(one["path"])).name for one in orphans] == [database.name]
