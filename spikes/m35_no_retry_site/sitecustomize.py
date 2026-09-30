"""Control arm for `m34_service_staleness_probe.py`'s phase D: a service whose reads never retry.

On `PYTHONPATH`, with `ZIKARON_PROBE_NO_RETRY=1`, the spawned service's `search` and `surface`
make their first attempt only, answering `store_busy` where the retry would have waited. The
spawned service inherits both from the probe's environment.
"""

import os

if os.environ.get("ZIKARON_PROBE_NO_RETRY") == "1":
    from zikaron.core.retrieval import reads
    from zikaron.core.store import transactions

    async def _first_attempt_only(db, work, *, verb, deadline):  # type: ignore[no-untyped-def]
        return await transactions.in_one_transaction(
            db, work, failure=reads._retry_failure_map(verb, deadline), deadline=deadline
        )

    reads._read_with_one_retry = _first_attempt_only
