"""The hook client: push injection and policy delivery, on a hard interpreter-startup budget.

Stdlib only, and not even all of stdlib, for every module in this package **except
`warm_helper.py`** — its own module docstring states why it is the one deliberate exception,
mirroring the identical carve-out `coding-standards.md` §6 already documents for
`zikaron-service`'s own logging: a module that runs as a *separate, detached process image*, off
the `agentSpawn`/`userPromptSubmit` critical path entirely, pays its own import cost in a process
nothing is waiting on. Every other module here — `main.py`, `push.py`, `spawn_warm.py`,
`connect.py`, `rpc.py`, `envelope.py`, `failure.py`, `write_policy.py` — must not import `logging`,
whose import cost alone is comparable to the whole budget the service architecture exists to
protect (`design/coding-standards.md` §6: ~15 ms, measured, in the same range as the rest of this
package's stdlib-thinness argument), and none of them do.
"""
