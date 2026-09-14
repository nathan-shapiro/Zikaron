"""`zikaron.mcp.spill` — writing a result too large to return, to a file a reader can address.

Every bound here is denominated in **UTF-8 bytes**, and the tests are written in that unit rather
than in characters, because the unit is the design: a token spans at least one byte, so bytes bound
tokens for any content, while a character count bounds nothing without a content-dependent ratio.
A test that asserted character lengths would pass while the property it exists to check quietly
depended on the payload being ASCII.
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from inspect import signature
from pathlib import Path

import pytest

from zikaron.mcp import server, spill
from zikaron.mcp.connection import ServiceConnection
from zikaron.mcp.consolidator import register_consolidator_tools
from zikaron.mcp.primary import register_primary_tools
from zikaron.mcp.spill import PayloadLineTooLongError, SpillPolicy


def _a_dead_pid() -> int:
    """A pid that is provably not running, by reaping a process and taking its number.

    Not a large literal: `kernel.pid_max` is 4,194,304 on 64-bit systemd machines, so a long-uptime
    host wraps past any number chosen to look unreachable, and the sweep's own liveness check then
    answers true — a red gate for a reason unrelated to the change under test. Linux allocates pids
    cyclically, so a just-reaped one is not reissued next.
    """
    probe = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(probe.stdout)


def _policy(tmp_path: Path, *, enabled: bool = True, threshold: int = 500) -> SpillPolicy:
    return SpillPolicy(
        enabled=enabled,
        threshold_bytes=threshold,
        directory=tmp_path / "runtime",
        store_key="abc123",
    )


def _group(*, entries: int = 1, content: str = "x" * 400) -> dict[str, object]:
    return {
        "group_id": "g1",
        "journal_entries": [
            {"uuid": f"u{n}", "gist": "a gist", "content": content} for n in range(entries)
        ],
    }


def test_a_payload_that_fits_is_returned_unchanged(tmp_path: Path) -> None:
    """Identity, not merely equality: the spill path must not be reached at all for a small
    result, so the object a handler returns is the one the service sent."""
    small = {"done": True}
    assert spill.apply(small, policy=_policy(tmp_path), tool="next_group") is small
    assert not (tmp_path / "runtime").exists()


def test_spilling_is_off_where_the_harness_cannot_read_a_file(tmp_path: Path) -> None:
    """The kiro case. A harness whose consolidator has no file-reading tool must be handed the
    payload inline however large it is — a path it cannot open is the same stall this exists to
    end, reached by a different route."""
    big = _group(entries=20)
    assert spill.apply(big, policy=_policy(tmp_path, enabled=False), tool="next_group") is big
    assert not (tmp_path / "runtime").exists()


def test_an_over_threshold_payload_becomes_a_pointer_to_a_file_holding_it(tmp_path: Path) -> None:
    pointer = spill.apply(_group(entries=20), policy=_policy(tmp_path), tool="next_group")

    assert isinstance(pointer, dict)
    assert pointer["spilled"] is True
    written = Path(str(pointer["path"]))
    assert written.is_file()
    assert written.parent == tmp_path / "runtime"


def test_the_pointer_cannot_be_mistaken_for_a_served_group(tmp_path: Path) -> None:
    """A consolidator that skimmed the pointer must not find the key it looks for in a group.
    Asserted because "unmistakable" is otherwise prose with nothing behind it — and the failure it
    guards is a merge decided from a filename."""
    pointer = spill.apply(_group(entries=20), policy=_policy(tmp_path), tool="next_group")

    assert isinstance(pointer, dict)
    assert "journal_entries" not in pointer
    assert "anchor" not in pointer


def test_the_file_round_trips_to_exactly_the_payload_that_would_have_been_returned(
    tmp_path: Path,
) -> None:
    """The property recovery means: what the reader parses back is what the inline path would have
    given it. Compared as parsed objects rather than as text, so the formatting this module chose
    for readability cannot be mistaken for part of the contract."""
    payload = _group(entries=20)
    pointer = spill.apply(payload, policy=_policy(tmp_path), tool="next_group")

    assert isinstance(pointer, dict)
    written = Path(str(pointer["path"])).read_text(encoding="utf-8")
    assert json.loads(written) == payload


def test_no_line_in_the_file_exceeds_the_addressable_maximum(tmp_path: Path) -> None:
    """The invariant the whole design rests on: a line is the smallest unit a reader can fetch, so
    a line over the cap has an unreachable tail. Asserted on the longest line in bytes — a line
    *count* would pass against a file of one enormous line, which is exactly the shape the harness
    writes and this module exists to avoid."""
    payload = _group(entries=40, content="y" * 2_000)
    pointer = spill.apply(payload, policy=_policy(tmp_path), tool="next_group")

    assert isinstance(pointer, dict)
    written = Path(str(pointer["path"])).read_text(encoding="utf-8")
    longest = max(len(line.encode("utf-8")) for line in written.splitlines())
    assert longest <= spill.SPILL_MAX_LINE_BYTES
    assert written.count("\n") > 40, "the document must be paginable, not one long line"


def test_a_value_too_long_to_address_is_refused_rather_than_written(tmp_path: Path) -> None:
    """The one shape that cannot be recovered, so it must not be produced. Refusing strands
    nothing: the group stays undecided and is served again, where a file with an unreadable tail
    would be decided from in part and merged."""
    payload = _group(content="z" * (spill.SPILL_MAX_LINE_BYTES + 1))

    with pytest.raises(PayloadLineTooLongError) as raised:
        spill.apply(payload, policy=_policy(tmp_path), tool="next_group")

    assert raised.value.uuid == "u0"
    assert raised.value.line_bytes > spill.SPILL_MAX_LINE_BYTES
    assert "u0" in str(raised.value)
    assert not list((tmp_path / "runtime").glob("*.json")), "nothing may be left behind"


def test_the_bound_is_bytes_so_multibyte_prose_is_measured_as_it_is_written(
    tmp_path: Path,
) -> None:
    """A CJK character is one code point and three UTF-8 bytes. A character-denominated bound
    would admit three times as much of it as the reader can address, which is the silent-loss case
    this unit exists to rule out."""
    payload = _group(content="漢" * (spill.SPILL_MAX_LINE_BYTES // 3))

    with pytest.raises(PayloadLineTooLongError):
        spill.apply(payload, policy=_policy(tmp_path), tool="next_group")


def test_multibyte_prose_within_the_bound_is_written_and_stays_readable(tmp_path: Path) -> None:
    """The other half of the same choice: bytes must not be so conservative that ordinary
    non-Latin prose is refused, and the file must hold it as itself rather than as escapes — a
    consolidator reading `\\u6f22` is reading something it cannot judge."""
    payload = _group(content="漢字" * 200)
    pointer = spill.apply(payload, policy=_policy(tmp_path), tool="next_group")

    assert isinstance(pointer, dict)
    written = Path(str(pointer["path"])).read_text(encoding="utf-8")
    assert "漢字" in written
    assert json.loads(written) == payload


def test_the_file_is_private_to_this_user(tmp_path: Path) -> None:
    """It holds record prose verbatim, outside the store and outside the log rules."""
    pointer = spill.apply(_group(entries=20), policy=_policy(tmp_path), tool="next_group")

    assert isinstance(pointer, dict)
    assert Path(str(pointer["path"])).stat().st_mode & 0o777 == 0o600


def test_two_spills_never_share_a_filename(tmp_path: Path) -> None:
    """A re-serve of the same group must not overwrite a file a reader is partway through."""
    policy = _policy(tmp_path)
    first = spill.apply(_group(entries=20), policy=policy, tool="next_group")
    second = spill.apply(_group(entries=20), policy=policy, tool="next_group")

    assert isinstance(first, dict)
    assert isinstance(second, dict)
    assert first["path"] != second["path"]


def test_the_primary_client_has_no_way_to_obtain_a_spill_policy() -> None:
    """Spilling is a property of the consolidator mode, asserted structurally rather than by
    reading the code: `register_primary_tools` takes no policy, so a primary process cannot spill
    however `build_server` is edited. Without this, an implementation that moved the check to the
    shared result seam would satisfy every other invariant here while handing a primary agent a
    pointer nothing has ever explained to it."""
    assert "spill_policy" in signature(register_consolidator_tools).parameters
    assert "spill_policy" not in signature(register_primary_tools).parameters


class TestTheWiringThatProducesAPolicy:
    """`server._spill_policy` turns harness data into the gate. Tested directly because every
    other test here builds a `SpillPolicy` by hand — which leaves the wiring itself uncovered, and
    a wiring mistake is the one that matters: `enabled=True` under kiro hands a consolidator with
    no file-reading tool a path it cannot open, which is the original stall rebuilt."""

    @pytest.fixture(autouse=True)
    def _an_empty_system_config_layer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Point the system config layer at an empty directory for every test here.

        `_spill_policy` resolves the real two-layer configuration, whose upper layer is
        `${XDG_CONFIG_HOME:-~/.config}/zikaron/config.toml` — a supported, documented layer an
        operator may well write. Without this the class would read whatever is on the developer's
        machine, so a `spill_threshold` set there would turn these tests red with no code change,
        and an out-of-bounds key anywhere in that file would break all of them. The default suite
        is hermetic on purpose; this keeps it that way.
        """
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    def test_kiro_gets_no_spilling(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CLAUDECODE", raising=False)
        policy = server._spill_policy(ServiceConnection(tmp_path))
        assert policy.enabled is False

    def test_claude_code_gets_spilling(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDECODE", "1")
        policy = server._spill_policy(ServiceConnection(tmp_path))
        assert policy.enabled is True

    def test_the_threshold_is_the_shipped_default(self, tmp_path: Path) -> None:
        assert server._spill_policy(ServiceConnection(tmp_path)).threshold_bytes == 27_000

    def test_an_operator_override_reaches_the_client(self, tmp_path: Path) -> None:
        """The test above cannot tell `config.get_int("spill_threshold")` from a hard-coded
        27,000, because the shipped default *is* 27,000 — so it would stay green while the
        operator's knob was silently severed. This one is the assertion that distinguishes them,
        and it is the reason the key exists: the threshold's whole claim to being future-proof is
        that a moved harness cap is a config edit rather than a release."""
        store_dir = tmp_path / ".zikaron"
        store_dir.mkdir()
        (store_dir / "config.toml").write_text(
            "[consolidation]\nspill_threshold = 30000\n", encoding="utf-8"
        )

        assert server._spill_policy(ServiceConnection(tmp_path)).threshold_bytes == 30_000

    def test_the_file_goes_to_the_runtime_directory_not_the_project(self, tmp_path: Path) -> None:
        """The spill holds record prose verbatim. Writing it into the project tree would put it
        somewhere a repository can capture it, which is what the runtime directory exists to
        avoid."""
        connection = ServiceConnection(tmp_path)
        policy = server._spill_policy(connection)

        assert policy.directory == connection.location.runtime_dir
        assert tmp_path not in policy.directory.parents
        assert policy.directory != connection.location.store_dir

    def test_the_store_key_is_the_one_the_socket_is_named_for(self, tmp_path: Path) -> None:
        """So `<key>-*.json` finds exactly one store's spill files in a directory shared by every
        store this user has — which is what the erasure procedure instructs an operator to do."""
        connection = ServiceConnection(tmp_path)
        policy = server._spill_policy(connection)

        # Equality rather than `startswith`: `startswith("")` is unconditionally true, so a
        # prefix check would pass against an empty or truncated key — which is exactly the value
        # that would make the erasure procedure's glob match every store's files instead of one's.
        assert connection.location.sock_path.name == f"{policy.store_key}.sock"


def test_a_process_that_exits_cleanly_takes_its_spill_files_with_it(tmp_path: Path) -> None:
    """The `atexit` path, which is real but is **not** the mechanism this design relies on.

    Measured: a real consolidation left four spill files behind, because the harness terminates its
    MCP server rather than letting it exit, and a terminated process runs no `atexit` handler. This
    test covers the case where one *does* exit normally; `sweep_stale` and `release_finished` cover
    the case that actually happens. Kept distinct so nobody reads a green test here as proof that
    cleanup works in production — that reading is exactly the mistake this file's history records.

    Driven through a real subprocess because the behaviour under test *is* interpreter exit:
    calling the handler directly would leave the registration uncovered, and the registration is
    the part a refactor drops."""
    runtime = tmp_path / "runtime"
    script = f"""
import sys
sys.path.insert(0, {str(Path.cwd())!r})
from pathlib import Path
from zikaron.mcp.spill import SpillPolicy, apply

policy = SpillPolicy(
    enabled=True, threshold_bytes=100, directory=Path({str(runtime)!r}), store_key="k"
)
pointer = apply({{"journal_entries": [{{"uuid": "u", "content": "x" * 500}}]}},
                policy=policy, tool="next_group")
assert Path(pointer["path"]).is_file(), "the spill must exist while the process lives"
print(pointer["path"])
"""
    finished = subprocess.run(  # noqa: S603 — this interpreter, on a script built here.
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    written = Path(finished.stdout.strip())

    assert written.name.startswith("k-next_group-"), "the store key must lead the filename"
    assert not written.exists(), "the file must not outlive the process that wrote it"


class TestTheCleanupThatDoesNotDependOnExiting:
    """Two mechanisms, because the one that reads most naturally does not work here.

    A harness terminates its MCP server when a session ends, so `atexit` never runs in production —
    measured, after a real consolidation left four spill files in tmpfs. What works instead is
    releasing at a known-safe point during the run, and sweeping at the *next* process's start,
    which needs nothing from the dead one.
    """

    @pytest.fixture(autouse=True)
    def _an_isolated_written_list(self) -> Iterator[None]:
        """`spill._written` is module state shared by every test in the session.

        Without this, a release here unlinks whatever an earlier test happened to leave in it — the
        tests pass today and are order-coupled forever, and one of them is vacuous for the same
        reason: a file that was never appended is one `release_finished` would leave alone whether
        or not it honoured the policy.
        """
        held = list(spill._written)
        spill._written.clear()
        yield
        spill._written[:] = held

    def test_releasing_removes_what_was_written_before_it(self, tmp_path: Path) -> None:
        policy = _policy(tmp_path)
        first = spill.apply(_group(entries=20), policy=policy, tool="next_group")
        second = spill.apply(_group(entries=20), policy=policy, tool="apply_merge")
        assert isinstance(first, dict)
        assert isinstance(second, dict)

        spill.release_finished(policy)

        assert not Path(str(first["path"])).exists()
        assert not Path(str(second["path"])).exists(), (
            "a conflict response's own file belongs to the group being released with it"
        )

    def test_releasing_does_not_touch_a_file_written_after_it(self, tmp_path: Path) -> None:
        """The boundary is the release, not the process: the next group's payload must survive it,
        or asking for a group would destroy the group you were handed."""
        policy = _policy(tmp_path)
        spill.release_finished(policy)
        current = spill.apply(_group(entries=20), policy=policy, tool="next_group")

        assert isinstance(current, dict)
        assert Path(str(current["path"])).is_file()

    def test_the_sweep_removes_a_dead_processs_files(self, tmp_path: Path) -> None:
        """The case `atexit` cannot reach, and the only one that happens in production."""
        policy = _policy(tmp_path)
        policy.directory.mkdir(parents=True, exist_ok=True)
        dead = policy.directory / f"{policy.store_key}-next_group-{_a_dead_pid()}-abc.json"
        dead.write_text("{}", encoding="utf-8")

        spill.sweep_stale(policy)

        assert not dead.exists()

    def test_the_sweep_leaves_a_live_processs_files_alone(self, tmp_path: Path) -> None:
        """It may belong to a concurrent consolidator on this store, and it may be being read right
        now. Deleting it would reintroduce the failure the whole milestone exists to remove."""
        policy = _policy(tmp_path)
        policy.directory.mkdir(parents=True, exist_ok=True)
        live = policy.directory / f"{policy.store_key}-next_group-{os.getpid()}-abc.json"
        live.write_text("{}", encoding="utf-8")

        spill.sweep_stale(policy)

        assert live.is_file()

    def test_the_sweep_leaves_another_stores_files_alone(self, tmp_path: Path) -> None:
        """The runtime directory is shared by every store this user has."""
        policy = _policy(tmp_path)
        policy.directory.mkdir(parents=True, exist_ok=True)
        other = policy.directory / "someotherstorehash-next_group-999999-abc.json"
        other.write_text("{}", encoding="utf-8")

        spill.sweep_stale(policy)

        assert other.is_file()

    def test_the_sweep_leaves_a_name_it_cannot_parse_alone(self, tmp_path: Path) -> None:
        """This function decides what to delete, so an unreadable name is left rather than guessed
        at — the failure mode of guessing is deleting somebody else's file."""
        policy = _policy(tmp_path)
        policy.directory.mkdir(parents=True, exist_ok=True)
        odd = policy.directory / f"{policy.store_key}-notapid.json"
        odd.write_text("{}", encoding="utf-8")

        spill.sweep_stale(policy)

        assert odd.is_file()

    def test_neither_mechanism_touches_anything_where_spilling_is_off(self, tmp_path: Path) -> None:
        """Under a harness that cannot read files nothing is ever written, so nothing is ever
        removed — the invariant that kiro's behaviour is unchanged in both directions."""
        policy = _policy(tmp_path, enabled=False)
        policy.directory.mkdir(parents=True, exist_ok=True)
        stranger = policy.directory / f"{policy.store_key}-next_group-{_a_dead_pid()}-abc.json"
        stranger.write_text("{}", encoding="utf-8")
        # Appended so the release half is not vacuous: a file absent from `_written` would be left
        # alone whether or not `release_finished` honoured the policy, so the assertion below would
        # pass against a version that ignored it.
        spill._written.append(stranger)

        spill.sweep_stale(policy)
        spill.release_finished(policy)

        assert stranger.is_file()
