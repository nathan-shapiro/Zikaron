# M35 — what the implementation was measured to do, against HEAD

`design/build-plan.md` §M35 asks for the probes re-run, a new probe phase, and four figures measured
once against a control on the same machine at the same load, with no bar. All of it was run on
2026-09-30, with the host busy (load average 6.5–7.8 throughout), in one sitting.

**The control is HEAD (`c66295f`), installed non-editable into a scratch virtualenv and run from a
directory outside the repository.** Both conditions are needed and the first attempt missed each in
turn: the project's editable install puts a meta-path finder ahead of `PYTHONPATH`, so a HEAD worktree
on `PYTHONPATH` still imports the working tree; and `python -m` puts the working directory first on
`sys.path`, so a spawned service run from the repository root imports the repository's package
whatever interpreter spawns it. A service log line only M35 writes (`stopping: reason=sigterm`) is
what showed both, and its absence is what confirms the control below.

## The store

`experiments/m34_gist_replay.py seed`, fresh, into a scratch directory: 284 journal rows from
`~/Trading/LeibaTrader`, snapshotted read-only with `Connection.backup()`. Each arm ran on its own
`backup()` copy. A plan over it outlasts the probe client's 10 s request timeout in every arm.

## The staleness probe (`spikes/m34_service_staleness_probe.py`)

    .venv/bin/python spikes/m34_service_staleness_probe.py <scratch-dir> <seeded-project-dir>

**Phase A — a plan running while a second client searches every 2 s.**

| arm | searches during the plan |
|---|---|
| HEAD | **5 of 8 failed**, `internal_error` — the nested `BEGIN` on the one shared connection |
| M35 | **0 of 8 failed** |

HEAD reproduces M34's own measurement (five of eight) on a store of the same size.

**Phase D, new — `next_group` with `apply_merge` or `apply_discard` against four concurrent readers,
two `search` and two `surface`, each on a connection of its own, for 20 s.** Counted from the
responses the probe received; the access log's count of the same phase beside it.

| arm | reads answered | reads refused `store_busy` | reads `internal_error` | consolidator disposals |
|---|---|---|---|---|
| HEAD | 8 | 892 | 2,810 | 1, then `index_failed` and the loop stopped |
| M35 | 779 | 0 | 0 | 176 |
| M35, retry disabled | 16 | 2,617 | 0 | 176 |

- **The retry is what carries the reads.** With it taken away, 99.4% of reads are refused at their
  upgrade while the consolidator writes continuously — each refused at once, which is why the refused
  reads outnumber the answered ones by so much in the same 20 s. That is the per-attempt figure the
  brief asks for: every read in the retry arm that met the writer needed its retry, and none needed a
  second.
- **The access log undercounts refusals, as predicted.** In the retry-disabled arm it holds 786
  `store_busy` rows for 2,617 refusals received: a read refused at a held lock attempts its `call` row
  while the lock is still held, on a connection with `busy_timeout` 0, and drops it. So a refusal
  rate read from the log understates the one the clients met, by a factor that moves with how long
  the writer holds its lock.
- HEAD's consolidator stopped after one serve: its discard met a read's transaction on the shared
  connection and failed `index_failed`, and its next `next_group` answered `store_busy`, which ends
  the probe's loop.

**Phases B and C** (a killed service, a frozen one) behave the same in every arm: the next call after
a kill respawns and answers; a call to a frozen service is `AmbiguousMutationError` at the client's
10 s, and calls after `SIGCONT` answer at once.

## The busy-snapshot probe (`spikes/m35_busy_snapshot_probe.py`)

    python3 spikes/m35_busy_snapshot_probe.py <scratch-dir>

Unchanged, re-run: a deferred `BEGIN` that reads before another connection's commit is refused
`SQLITE_BUSY_SNAPSHOT` after 0.001 s; `BEGIN IMMEDIATE` in the same place waits and commits. Its
fixture is now a test over every write verb, `tests/test_service_write_contention.py`, red under a
deferred writer for all twelve.

## The commit path, which sets `dispatch.DEADLINE_MARGIN_MS`

    .venv/bin/python experiments/m35_commit_path_margin.py <scratch-dir> 2000 <seeded-store-dir>

A real service, the hook's own client code, pushes sent one at a time; the service stamps
`time.time()` as its last deadline check passes, and the client stamps it as `recv` returns.

| pushes | median | p90 | p99 | p99.9 | max |
|---|---|---|---|---|---|
| 2,000 | 1.94 ms | 2.32 ms | 6.17 ms | 10.31 ms | 15.81 ms |

A first run of 400 gave median 1.90 ms and max 7.49 ms. **The margin is 20 ms**: above the largest
of the 2,000, rather than at a percentile of them, since a push lost to the race is one recorded as
shown that nobody saw and 20 ms is 1% of the hook's 2 s. Re-measure it if the host's disk or load
changes character.

## The two figures with no decision attached (`spikes/m35_warm_and_footprint.py`)

    python spikes/m35_warm_and_footprint.py <scratch-dir> <seeded-project-dir>   # from outside the repository

| | HEAD | M35 |
|---|---|---|
| warm `memory_search`, 50 sequential: median / p90 | 15.3 / 17.3 ms | 16.7 / 18.3 ms |
| service resident memory, before / after eight concurrent searches | 254 / 256 MB | 256 / 262 MB |
| open file descriptors, before / after | 18 / 26 | 16 / 30 |

The read's extra ~1.4 ms is the lease and the holder, at this load. The pool's footprint once full is
about 6 MB and four descriptors beyond HEAD's.

## Every guard, shown red

Each mutation re-executes one module's source with one change, loaded as a pytest plugin (or, for
the two that must reach a spawned service, as a `sitecustomize` on the child's path), and was run
against the tests named. Every one turned at least one of them red; the unmutated tree is green.

| mutation | red |
|---|---|
| writer opens deferred | `test_service_write_contention.py`, all 12 write verbs |
| nested-transaction check removed | `test_a_task_that_asks_again_for_a_transaction_it_holds_fails_at_once` |
| the closed mark never set | `test_a_writer_a_failed_rollback_closed_is_replaced_for_the_next_request` |
| reopen without the store's lock | `test_two_writes_into_the_gap_share_one_reopened_writer` |
| no closed check after taking the lock | `test_a_write_queued_when_the_writer_closed_answers_store_busy_and_ran_nothing` |
| no inode check on a later open | `test_a_connection_opened_onto_a_replaced_store_is_refused_by_its_family` |
| registry presence read removed | `test_a_store_without_the_registry_answers_as_an_empty_one_and_stays_without_it` |
| no read retry; a deferred retry | `test_a_read_retries_once_and_succeeds_when_the_hold_ends_inside_its_budget` |
| a returned lease wakes one waiter, not all (Python 3.12) | `test_a_notification_a_cancelled_waiter_consumed_still_reaches_the_next` |
| a cancelled return leaves the handle outside `close()` | `test_a_lease_whose_return_is_cut_short_is_closed_with_the_pool` |
| `BEGIN IMMEDIATE` tried once, not polled | `test_a_write_lock_freed_during_the_wait_is_taken`, the read-retry tests, and three more |
| the poll's longest pause raised to 400 ms | `test_a_write_lock_freed_during_the_wait_is_taken` |
| serving connections left at SQLite's own 5 s wait | `test_every_serving_connection_leaves_the_wait_to_the_primitive`, `test_the_wait_for_the_write_lock_ends_at_the_deadline`, and four more |
| two retries | `test_a_read_whose_hold_outlasts_its_budget_answers_store_busy_after_one_retry` |
| an unbounded wait for the writer's lock | `test_the_wait_for_the_writers_lock_ends_at_the_budget` |
| the lock wait timed only when `locked()` reports it held | `test_a_wait_that_begins_as_the_lock_is_released_still_ends_at_its_deadline` |
| both halves of the budget removed | `test_a_writers_whole_wait_is_one_budget_whichever_side_refuses_it` |
| `deadline_at_ms` converted through a float | both `beyond a float's range` cases |
| check point 1 removed | `test_a_deadline_already_past_answers_before_any_work` |
| check point 2 removed | `test_an_embed_that_outlasts_the_deadline_spends_no_read_pass` |
| check point 4 removed | `test_a_deadline_that_passes_inside_the_transaction_rolls_its_rows_back` |
| the margin ignored (the caller's deadline used whole) | `test_a_writers_hold_past_the_deadline_answers_deadline_passed_and_commits_nothing` |
| a caller-bounded retry answering `store_busy` | `test_a_writers_hold_past_the_deadline_answers_deadline_passed_and_commits_nothing` |
| the dispatcher's lateness mapping removed | `test_an_exhausted_pool_answers_deadline_passed_at_the_lease_wait_and_its_row_lands` |
| hook catches the timeout around the whole connect | `test_a_listener_that_never_answers_health_is_still_a_transport_failure` |
| hook has no `unanswered` catch | `test_a_push_sent_and_never_answered_is_logged_unanswered` |
| hook's `-32026` entry omitted | `test_every_rejection_kind_is_its_codes_own_wire_name`, and the `deadline_passed` hook test |
| the snapshot plan takes the write lock | `test_a_plan_holds_no_write_lock_while_it_computes` |
| fingerprint ignored | `test_a_journal_row_written_while_the_plan_computed_is_among_the_runs_members` |
| journal-only fingerprint | `test_an_anchor_retired_while_the_plan_computed_anchors_no_group` |
| `next_group`'s third step always replans | the own-run and the stranger's-run tests |
| `next_group` does not wait for the model | `test_next_group_takes_no_write_lock_while_the_model_loads` |
| completion callback not passed | `test_a_completed_build_has_its_one_row_before_the_lock_goes` |
| build-row latch removed | the build-row tests, on a second row |
| callback on `BaseException` | `test_a_build_cancelled_mid_scan_leaves_no_row_and_no_lock` |
| corpus lock acquired deferred | `test_the_second_of_two_simultaneous_acquisitions_is_refused_as_busy` |
| fast holder read removed | `test_a_build_arriving_during_the_winners_index_phase_is_refused_at_once` |
| idle poll logs no long request | `test_a_request_outliving_the_poll_is_logged_on_each_poll_until_it_ends` |
| spawned service without the dumps | both signal-dump integration tests |
| thread dump armed only after the store opens | `test_the_thread_dump_is_armed_before_the_store_opens` |
| store connections under `sqlite3`'s legacy transaction control | `test_a_statement_outside_a_transaction_opens_none` |
| spawned service without the signal stop line | both stop-line integration tests |

**Only the write-lock half of the budget survived alone at first**: removing it left every test
green, because the lock-wait deadline bounded the only scenario that exercised it. The two
half-budget tests were written for that, and the rows above are its kills.

## SQLite's own wait on macOS, and why the primitive polls instead

The first design set each serving transaction's `busy_timeout` to what was left of its budget and let
SQLite wait. Pull request #14's required macOS job (`gh run view 36725333239`) failed five timing tests,
every one where SQLite's busy handler refused a `BEGIN IMMEDIATE` behind a held lock. The waits ran
past their `busy_timeout`, not to it:

| test | SQLite's `busy_timeout` | refused after |
|---|---|---|
| the writer's half-spent deadline | ~250 ms | ~864 ms |
| a read's retry, budget 400 ms | ~400 ms | 1,359 ms |
| a push's retry, 300 ms before its margin | ~300 ms | 976 ms |
| the first of two queued writers, the one waiting in SQLite | ~500 ms | 1,174 ms |

The Linux jobs ran the same SQLite, 3.53.1, from the same uv-managed CPython 3.12.14, and every bound
held; the asyncio side of the same test on macOS, the wait for the connection's lock, landed at 509 ms
against 500. So the overrun is SQLite's sleep on that platform's build, and D36 makes that build the
recommended install. Which build option causes it was not established, and does not need to be:
the store's serving connections now run at `busy_timeout = 0`, and the primitive retries a refused
`BEGIN IMMEDIATE` itself, pausing 1 ms doubling to 25 ms, until the deadline. That bounds the wait to
within one attempt on every platform, and removes the pragma-restore machinery the pool needed. A
refused `BEGIN IMMEDIATE` leaves no transaction open, so the next attempt is not a nested one
(checked against 3.53.1 directly).

## On the real store, after the approved tree was live

`~/Trading/LeibaTrader`'s service runs `/home/nathan/Zikaron/.venv`, an editable install, so the
service started 2026-09-30 08:18 local — after the last source edit at 06:03 — runs the approved
tree. Checked without signalling first: `/proc/<pid>/status`'s `SigCgt` shows `SIGUSR1` and `SIGUSR2`
caught, which no pre-M35 build does. Then, with the operator's say-so, `kill -USR2` wrote
`dump: 0 request(s) in flight` and the five asyncio tasks' stacks into `service.log`, and `kill -USR1`
wrote every thread's stack as raw text — three `aiosqlite` worker threads, the writer, the access
log's and one leased read connection — and the service kept running after both.
