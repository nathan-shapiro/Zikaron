"""`service.log` setup: stdlib `logging`, one file per process, `0600`.

`coding-standards.md` §6: `zikaron-service` is off any latency-critical path once warm, so the
~15 ms `import logging` cost that rules it out of the hook is irrelevant here. `architecture.md`
§Paths: `service.log` is this process's own file, never shared with `warmup.log` or `hook.log`,
because `logging.FileHandler` has no cross-process append locking.
"""

import logging
import stat
from pathlib import Path
from typing import Final

from zikaron.core.config.resolution import EffectiveConfig

_FILE_MODE: Final = 0o600


def configure_service_log(log_path: Path) -> None:
    """Attach a file handler at `log_path`, creating it at `0600` and tightening it if it exists
    wider than that.

    Idempotent-enough for the process's own lifetime: called once, at startup, before anything
    that might log — the resolved-config line this module's other function writes is the first
    thing `main.py` puts through it.
    """
    log_path.touch(exist_ok=True)
    current_mode = stat.S_IMODE(log_path.stat().st_mode)
    if current_mode != _FILE_MODE:
        log_path.chmod(_FILE_MODE)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s pid=%(process)d %(levelname)s %(message)s"))
    logger = logging.getLogger("zikaron.service")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)


def log_resolved_config(config: EffectiveConfig) -> None:
    """One line per configuration key, naming the layer its winning value came from.

    `architecture.md` §"Configuration": "the resolved config is written to `service.log` at
    startup, with the layer each non-default value came from" — with three layers, this is the
    one place "why does this project behave differently" is answered without a two-file hunt.
    """
    logger = logging.getLogger("zikaron.service")
    for name, value in sorted(config.provenance.items()):
        source = str(value) if value is not None else "<default>"
        logger.info("config %s = %r (from %s)", name, config.get(name), source)


def log_self_stop(*, reason: str, store_dir: Path, idle_seconds: float) -> None:
    """The one record a *clean* exit writes, and the reason it exists.

    Before this, every exit path but one was silent: `lifecycle.idle_self_stop` unlinked the
    socket, shut the server down and returned without logging, so the only line any exit ever
    produced was `main.py`'s forced-exit `exception()`. That inverted the log's contract —
    silence meant a clean stop and a line meant a failed one — and made "did this service stop or
    is it wedged?" answerable only with `ps`. Observed directly: four stores on one machine, one
    live service, and four `service.log` files whose last entry was the startup config dump, with
    no way to tell an idle stop from a crash or a kill.

    `reason` distinguishes the two conditions `idle_self_stop` polls, because they carry different
    diagnoses: `idle` is routine, while `store_replaced` means the file this process had open is
    no longer the one at its path — someone moved, deleted or restored the store underneath a
    running service, which is worth seeing in a log rather than inferring from a restart.
    """
    logger = logging.getLogger("zikaron.service")
    logger.info(
        "stopping: reason=%s store=%s idle_for=%.1fs",
        reason,
        store_dir,
        idle_seconds,
    )
