"""`zikaron.hook.warm_helper`: the `agentSpawn` hook's detached process, unit-tier pieces.

`architecture.md` §"Warming" is normative. This file covers `_configure_warmup_log` in
isolation; `test_hook_warm_helper_integration.py` covers `run()` end to end against a real
spawned `zikaron.service.main`.
"""

import logging
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from zikaron.hook.warm_helper import _configure_warmup_log


@pytest.fixture
def clean_warm_helper_logger() -> Iterator[logging.Logger]:
    """`logging.getLogger` returns the identical object for a given name across every call in one
    process, so a handler `_configure_warmup_log` attaches in one test would otherwise still be
    attached — alongside whatever pytest's own log-capture plugin attaches globally — when a
    later test calls it again. This fixture hands back the logger with every handler *this test
    itself* adds removed again afterward, so each test observes only what its own call attached.
    """
    logger = logging.getLogger("zikaron.hook.warm_helper")
    before = list(logger.handlers)
    yield logger
    for handler in list(logger.handlers):
        if handler not in before:
            handler.close()
            logger.removeHandler(handler)


def test_configure_warmup_log_writes_only_to_its_own_path(
    tmp_path: Path,
    clean_warm_helper_logger: logging.Logger,  # noqa: ARG001 — required for its teardown only.
) -> None:
    log_path = tmp_path / "warmup.log"
    logger = _configure_warmup_log(log_path)
    logger.info("a warm-up line")
    for handler in logger.handlers:
        handler.flush()
    assert log_path.exists()
    assert "a warm-up line" in log_path.read_text(encoding="utf-8")
    assert logger.propagate is False


def test_configure_warmup_log_attaches_a_file_handler_on_the_given_path(
    tmp_path: Path, clean_warm_helper_logger: logging.Logger
) -> None:
    log_path = tmp_path / "warmup.log"
    before = set(clean_warm_helper_logger.handlers)
    logger = _configure_warmup_log(log_path)
    added = [h for h in logger.handlers if h not in before]
    assert len(added) == 1
    handler = added[0]
    assert isinstance(handler, logging.FileHandler)
    assert Path(handler.baseFilename) == log_path


def test_configure_warmup_log_does_not_propagate_to_the_root_logger(
    tmp_path: Path,
    clean_warm_helper_logger: logging.Logger,  # noqa: ARG001 — required for its teardown only.
) -> None:
    logger = _configure_warmup_log(tmp_path / "warmup.log")
    assert logger.propagate is False


def test_configure_warmup_log_creates_the_file_at_mode_0600(
    tmp_path: Path,
    clean_warm_helper_logger: logging.Logger,  # noqa: ARG001 — required for its teardown only.
) -> None:
    log_path = tmp_path / "warmup.log"
    _configure_warmup_log(log_path)
    mode = stat.S_IMODE(log_path.stat().st_mode)
    assert mode == 0o600


def test_configure_warmup_log_tightens_an_existing_wider_file(
    tmp_path: Path,
    clean_warm_helper_logger: logging.Logger,  # noqa: ARG001 — required for its teardown only.
) -> None:
    log_path = tmp_path / "warmup.log"
    log_path.touch()
    log_path.chmod(0o644)
    _configure_warmup_log(log_path)
    mode = stat.S_IMODE(log_path.stat().st_mode)
    assert mode == 0o600


def test_configure_warmup_log_leaves_a_file_already_at_mode_0600_untouched(
    tmp_path: Path,
    clean_warm_helper_logger: logging.Logger,  # noqa: ARG001 — required for its teardown only.
) -> None:
    """The converse of the tightening test above: a file already at exactly `0600` before this
    call must take the *other* branch of the mode check (skip the `chmod`) rather than always
    taking the tightening path — `path.touch()`'s own default mode is governed by the process
    umask, not `0600`, so this has to set the mode explicitly first to construct the "already
    correct" case rather than assume a fresh touch produces it.
    """
    log_path = tmp_path / "warmup.log"
    log_path.touch()
    log_path.chmod(0o600)
    _configure_warmup_log(log_path)
    mode = stat.S_IMODE(log_path.stat().st_mode)
    assert mode == 0o600
