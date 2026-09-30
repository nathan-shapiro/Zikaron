"""Instrumentation for `m35_commit_path_margin.py`: stamp the service's last deadline check.

On `PYTHONPATH`, with `ZIKARON_MARGIN_STAMPS` naming a file, the spawned service appends one
`time.time()` line each time a `surface` renders its block — which it does immediately after the
check before `COMMIT` passes, inside the transaction. The service inherits both from the harness's
environment. Nothing else about the service changes.
"""

import os
import time

_STAMPS = os.environ.get("ZIKARON_MARGIN_STAMPS")

if _STAMPS:
    from zikaron.core.retrieval import block

    _render = block.render

    def _stamped_render(*args, **kwargs):  # type: ignore[no-untyped-def]
        with open(_STAMPS, "a", encoding="utf-8") as stamps:
            stamps.write(f"{time.time():.6f}\n")
        return _render(*args, **kwargs)

    block.render = _stamped_render
