"""`zikaron.hook.instruction_markers`: one empty file per agent whose instruction may be unserved.

`design/harness.md` §"Agent teams" is normative. The property the push rests on is that claiming
is unlinking, so a parallel tool batch's hooks claim one marker exactly once between them.
"""

import os
import stat
import threading
import time
from pathlib import Path

import pytest

from zikaron.hook import instruction_markers as markers
from zikaron.service import paths

SESSION = "6ce78ba4-beb9-485f-b46d-fd39b8ed5073"
AGENT = "amate-1-d82c396dc9f48005"


@pytest.fixture
def store(tmp_path: Path) -> Path:
    directory = tmp_path / ".zikaron"
    directory.mkdir(mode=0o700)
    return directory


def _pending(store: Path) -> set[str]:
    directory = paths.instruction_pending_dir(store)
    return {entry.name for entry in directory.iterdir()} if directory.exists() else set()


class TestNames:
    def test_a_session_and_an_agent_inside_it(self) -> None:
        assert markers.name(SESSION, None) == SESSION
        assert markers.name(SESSION, AGENT) == f"{SESSION}.{AGENT}"

    @pytest.mark.parametrize(
        ("session_id", "agent_id"),
        [(None, None), (42, None), ("", None), ("../x", None), (SESSION, "a/b"), (SESSION, 7)],
    )
    def test_an_id_that_cannot_safely_name_a_file_names_nothing(
        self, session_id: object, agent_id: object
    ) -> None:
        assert markers.name(session_id, agent_id) is None


class TestMarking:
    def test_a_marker_is_an_empty_private_file_in_a_private_directory(self, store: Path) -> None:
        markers.mark(store, SESSION)
        directory = paths.instruction_pending_dir(store)
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        marker = directory / SESSION
        assert stat.S_IMODE(marker.stat().st_mode) == 0o600
        assert marker.read_bytes() == b""

    def test_nothing_is_marked_where_there_is_no_store(self, tmp_path: Path) -> None:
        markers.mark(tmp_path / ".zikaron", SESSION)
        assert not (tmp_path / ".zikaron").exists()

    def test_marking_again_refreshes_its_age(self, store: Path) -> None:
        markers.mark(store, SESSION)
        marker = paths.instruction_pending_dir(store) / SESSION
        os.utime(marker, (1.0, 1.0))
        markers.mark(store, SESSION)
        assert marker.stat().st_mtime > 1.0

    def test_a_symlinked_directory_is_not_written_through(
        self, store: Path, tmp_path: Path
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        paths.instruction_pending_dir(store).symlink_to(elsewhere)
        markers.mark(store, SESSION)
        assert list(elsewhere.iterdir()) == []


class TestClaiming:
    def test_a_marker_is_claimed_once(self, store: Path) -> None:
        markers.mark(store, SESSION)
        assert markers.claim(store, SESSION) is True
        assert markers.claim(store, SESSION) is False

    def test_claiming_one_agent_leaves_the_others(self, store: Path) -> None:
        for agent in ("a1", "a2"):
            markers.mark(store, f"{SESSION}.{agent}")
        assert markers.claim(store, f"{SESSION}.a1") is True
        assert _pending(store) == {f"{SESSION}.a2"}

    def test_racing_claims_succeed_exactly_once(self, store: Path) -> None:
        markers.mark(store, SESSION)
        barrier = threading.Barrier(8)
        won: list[bool] = []

        def race() -> None:
            barrier.wait()
            won.append(markers.claim(store, SESSION))

        threads = [threading.Thread(target=race) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(won) == [False] * 7 + [True]


class TestSweeping:
    def test_each_kind_of_marker_ages_out_at_its_own_limit(self, store: Path) -> None:
        now = time.time()
        ages = {
            f"{SESSION}.old": markers.PENDING_TTL_SECONDS + 1,
            f"{SESSION}.young": markers.PENDING_TTL_SECONDS - 60,
            "old-session": markers.PENDING_SESSION_TTL_SECONDS + 1,
            "waiting-session": markers.PENDING_TTL_SECONDS * 4,
        }
        for marker, age in ages.items():
            markers.mark(store, marker)
            os.utime(paths.instruction_pending_dir(store) / marker, (now - age, now - age))
        markers.sweep(store, now=now)
        assert _pending(store) == {f"{SESSION}.young", "waiting-session"}

    def test_no_directory_is_nothing_to_sweep(self, store: Path) -> None:
        markers.sweep(store, now=time.time())
        assert _pending(store) == set()
