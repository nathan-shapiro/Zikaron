# The `SIGUSR1` thread dump crashed the service it was dumping

**Decision this supports:** replacing `faulthandler.register(SIGUSR1, all_threads=True)` with a
Python-level `signal.signal` handler that calls `faulthandler.dump_traceback` on the main thread
(`zikaron/service/diagnostics.py`; `design/architecture.md` §"What a service that stops answering
writes" is normative).

## What was seen

PR #19's `macos / 3.12` job failed
`test_sigusr1_dumps_every_threads_stack_and_leaves_the_service_running`: the dump reached
`service.log`, then the service exited with return code `-11` (`SIGSEGV`). The PR's commit at the
time, `7a19ed2`, changed no code under `zikaron/`.

## Cause

`faulthandler.register`'s handler runs in whichever thread the kernel delivers the signal to and,
with `all_threads=True`, walks every thread's frame chain **without the GIL**. A thread running
Python meanwhile pushes and frees frames under the walk. On the open path the service loads its
model on a thread of its own, and the dumps taken right after the socket accepts show that thread
inside `import fastembed`, so a dump sent then reads frames mid-change.

## Measurement

`experiments/sigusr1_dump_stress.py`, Linux, Python 3.12, on a host under sustained unrelated load.
Each run spawns the service as a client does and signals it as soon as the socket accepts; each
signal after the first waits for the previous dump to land. *Before* is commit `7a19ed2` in a
separate worktree run from that worktree's directory, so the spawned service imports that tree.

A dump is counted by its `Current thread` header. A run stops signalling once its service has died,
so the count is runs × signals only where nothing died.

| Handler | Signals per run | Runs that died | Return code | Dumps counted |
|---|---|---|---|---|
| `faulthandler.register` | 5 | 55 of 60 | `-11` | 89 |
| `faulthandler.register` | 1 | 19 of 60 | `-11` | 41 |
| Python-level handler | 5 | 0 of 60 | — | 300 |
| Python-level handler | 1 | 0 of 60 | — | 60 |

```bash
.venv/bin/python experiments/sigusr1_dump_stress.py 60 5
.venv/bin/python experiments/sigusr1_dump_stress.py 60 1
```

**Why the single-signal test was usually green despite 19 of 60 here — an inference, not measured.**
It asserted the process alive as soon as the first thread's header appeared, and a crash partway
through the walk comes after that header, so the assertion could run in between. The test now
sends five dumps, each after the previous one has landed. Against the old handler that test failed
4 of 5 runs; against the new one, 5 of 5 passed.

## The design that was tried first and does not work

A dedicated thread that `sigwait`s for `SIGUSR1`, with the signal blocked in the main thread before
the handler goes on, would dump without depending on the main thread. Measured by the same procedure
before the harness was committed: 60 of 60 runs at five signals died with `-10`, `SIGUSR1`'s default
disposition. Importing `numpy` starts eleven native threads before `run()` is entered (a process
goes from 1 thread to 12 on `import numpy`), they have the signal
unblocked, and a process-directed signal goes to a thread that does not block it. Making it work
would mean blocking the signal before any import in `zikaron.service.main`, and every child the
service spawns — the knowledge indexer, `git` — would inherit it blocked.

## What the replacement gives up

The Python-level handler runs when the main thread next executes Python. A loop blocked in Python
code or in a wait a signal interrupts is dumped at once; a loop stuck inside a single C call that no
signal interrupts is dumped only when that call returns. The service's SQLite calls and embeddings run
on worker threads, which the dump shows either way.
