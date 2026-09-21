"""`zikaron.service.log` — the one startup line whose whole value is being parseable later.

`log_runtime_versions` exists to answer "what was this service actually running on?" weeks after the
fact, from a log file and nothing else. That makes its *content* the feature, not merely the call: a
line that fires but omits one of the two values is as useless as no line, and coverage cannot tell
the difference.
"""

import logging
from pathlib import Path

from zikaron.service import log


def test_the_startup_line_names_both_the_python_and_the_sqlite(tmp_path: Path) -> None:
    log_path = tmp_path / "service.log"
    logger = logging.getLogger("zikaron.service")
    log.configure_service_log(log_path)
    try:
        log.log_runtime_versions()
    finally:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)

    written = log_path.read_text(encoding="utf-8")
    assert "runtime python=" in written
    assert "sqlite=" in written
    # Both values dotted and non-empty, rather than merely present as labels: an empty or `None`
    # value would satisfy a substring check while answering nothing.
    versions = written.rsplit("runtime ", 1)[1].split()
    reported = dict(pair.split("=", 1) for pair in versions)
    assert reported["python"].count(".") >= 1
    assert reported["sqlite"].count(".") >= 1
