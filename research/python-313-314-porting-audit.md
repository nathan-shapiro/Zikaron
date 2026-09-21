# Python 3.12 → 3.13/3.14 porting audit: changed defaults, semantics and return values

## Brief

Zikaron is pinned `requires-python = "==3.12.*"`. We are considering widening to `>=3.12`. The
2,865-test suite run on 3.13 and 3.14 produced one loud failure (`asyncio.Server._active_count`
replaced by `_clients`) and one **silent** one the suite passed straight through:
`loop.create_unix_server()` gained a `cleanup_socket` parameter defaulting to `True` in 3.13, so an
`asyncio` Unix-domain server now unlinks its own socket file on `close()` where 3.12 left it in
place — and Zikaron's socket-lifecycle invariants (start-if-absent, vet-and-unlink) were written
assuming the 3.12 behaviour. This note hunts for **more of that shape**: changed defaults, changed
behaviour, changed semantics of *existing* APIs — not removals (the suite finds those) and not new
features alone. Scope is the stdlib modules Zikaron actually imports, in the priority order given in
the brief, with `asyncio` and `sqlite3` covered in depth.

## Method

Read CPython's official "What's New in Python 3.13/3.14" pages
([3.13](https://docs.python.org/3/whatsnew/3.13.html),
[3.14](https://docs.python.org/3/whatsnew/3.14.html)) in full; then fetched the per-module reference
docs for `asyncio` (event loop, streams, tasks) and `sqlite3` directly, since What's New is known to
omit function-level "Changed in version" notes that only live on the reference page (this is exactly
how the `cleanup_socket` default was missed the first time — it *is* in What's New 3.13, in one
sentence, with no callout that the default is `True`). Cross-checked the CPython issue tracker for
the `Server` shutdown redesign. Checked SQLite's own release log (`sqlite.org/changes.html`,
individual release-log pages) for the delta between the two measured bundled-library versions,
3.45.1 (Ubuntu system Python 3.12.3) and 3.53.1 (uv-managed 3.13/3.14), against `fts5.html`'s stated
version requirements. Searched targeted queries for `socket`, `subprocess`, `signal` and
free-threading; did not do an exhaustive per-function sweep of every module in the "lower risk" tail
of the brief's list (see §5).

---

## 1. Table of behaviour changes, ranked by how likely each is to pass a test suite silently

"Silent" here means: no exception is raised, no warning fires by default (or the warning is easy to
miss/filter), and ordinary unit or integration tests exercising the *documented* contract of the API
would not notice — only an assertion about a side effect (a file on disk, a log line, a timing
window) would catch it. Ranked highest-risk-of-silence first.

| # | Module | API | What changed | Ver | Kind | Source |
|---|---|---|---|---|---|---|
| 1 | `asyncio` | `loop.create_unix_server()` / `asyncio.start_unix_server()` | New `cleanup_socket` parameter, **default `True`**: the Unix socket file is now unlinked automatically when the server closes, unless the socket path was replaced after the server was created. 3.12 left the file in place on close. | 3.13 | Changed default | [Event loop docs, `create_unix_server`](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.create_unix_server); [Streams docs, `start_unix_server`](https://docs.python.org/3/library/asyncio-stream.html#asyncio.start_unix_server); [What's New 3.13](https://docs.python.org/3/whatsnew/3.13.html) (gh-111246) |
| 2 | `sqlite3` | `Connection.row_factory` / `Cursor.row_factory` / `Connection.text_factory` | Deleting the `row_factory` or `text_factory` attribute (`del conn.row_factory`) is **no longer allowed** — previously this silently reset to a default; behaviour is a point release, not the `.0`. | 3.13.14 | Changed semantics (was silently accepted before) | [`sqlite3` docs, `Connection.row_factory`](https://docs.python.org/3.13/library/sqlite3.html#sqlite3.Connection.row_factory) |
| 3 | `sqlite3` | `Cursor.arraysize`, `Cursor.fetchmany(size=...)` | Negative `size` values used to be accepted (with SQLite/DB-API-dependent behaviour); now rejected by raising `ValueError`. Any code path passing a negative or derived-negative size silently worked before and now raises. | 3.13.8 | Changed error type / changed semantics | [`sqlite3` docs, `Cursor.arraysize`](https://docs.python.org/3.13/library/sqlite3.html#sqlite3.Cursor.arraysize) |
| 4 | `asyncio` | `Server.wait_closed()` | Previously returned **immediately** if the server was already closed, even with active connections. Now waits until the server is closed **and all active connections have finished**. Code that called `close()` then `wait_closed()` expecting an instant return (e.g. in a shutdown-timeout budget) will now block until clients drain. | 3.12 (not 3.13/3.14, but adjacent and easy to misattribute — see note below) | Changed semantics | [Event loop docs, `Server.wait_closed`](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.Server.wait_closed) |
| 5 | `asyncio` | `Server` internals: `_active_count` → `_clients` | Undocumented, private attribute rename/restructuring as part of the `close_clients()`/`abort_clients()` redesign (gh-113538). **This is exactly the class of change a "Changed in version" sweep cannot catch, because it is a private API and appears in no reference-page callout** — it is only visible by reading `Lib/asyncio/base_events.py`/`selector_events.py` source or by a test that reaches into the private attribute (as Zikaron's evidently does, per the brief). Confirmed as the source of Zikaron's own loud 3.13 failure. | 3.13 | Changed internal attribute (undocumented) | [gh-113538, "Cannot cleanly shut down an asyncio based server"](https://github.com/python/cpython/issues/113538); [Event loop docs, `Server.close_clients`/`abort_clients`](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.Server.close_clients) — **inference**: the rename itself is not stated verbatim in any doc page found; treat the exact old→new name as reported by Zikaron's own failing test, not as independently confirmed here |
| 6 | `sqlite3` | `sqlite3.connect()` and 7 other functions/methods | Positional use of `timeout`, `detect_types`, `isolation_level`, `check_same_thread`, `factory`, `cached_statements`, `uri` (on `connect()`), and similar positional/keyword patterns on `create_function()`, `create_aggregate()`, `set_authorizer()`, `set_progress_handler()`, `set_trace_callback()` is **deprecated**, not yet broken. Emits `DeprecationWarning`, which is silenced by default in many test runners and CI configs. Becomes a hard `TypeError` in 3.15 — not this port, but worth flagging now since the warning itself is easy to miss. | 3.13 | Changed default (deprecation, future breakage) | [`sqlite3` docs, `connect()`](https://docs.python.org/3.13/library/sqlite3.html#sqlite3.connect) |
| 7 | `sqlite3` | `Cursor.execute()` / `executemany()` | If named placeholders are used and `parameters` is a sequence (not a `dict`), this emitted only a `DeprecationWarning` through 3.13; **starting 3.14 it raises `ProgrammingError`.** A latent bug (wrong placeholder/parameter shape) that previously ran with a warning will now hard-fail on 3.14. | 3.14 | Changed error type | [`sqlite3` docs, `Cursor.execute`](https://docs.python.org/3.13/library/sqlite3.html#sqlite3.Cursor.execute) (deprecation notice states the 3.14 behaviour) |
| 8 | `sqlite3` | `sqlite3.version` / `sqlite3.version_info` | Deprecated since 3.12, **removed in 3.14.** Any code, tooling, or third-party dependency reading `sqlite3.version` (the pysqlite wrapper version, easily confused with `sqlite3.sqlite_version`) breaks with `AttributeError` at import/attribute-access time, not at a call site a test necessarily exercises. | 3.14 | Removal (listed here despite the "no removals" instruction because it is a **name collision trap**, not a feature loss — `sqlite3.version` is commonly confused with `sqlite3.sqlite_version`, which is unaffected) | [gh issue noting the break](https://github.com/o3de/o3de/issues/19644); [`sqlite3` docs deprecation note](https://docs.python.org/3.13/library/sqlite3.html) |
| 9 | `asyncio` | `TaskGroup` / `Task.uncancel()` | `uncancel()` "changed to rescind pending cancellation requests upon reaching zero" — a subtle change to how nested cancellation and `cancelling()` counts interact when a task group and an external canceller collide. Code relying on the exact old count semantics for retry/backoff logic could silently compute a different cancellation count. | 3.13 | Changed semantics | [Coroutines and tasks docs, `Task.uncancel`](https://docs.python.org/3/library/asyncio-task.html#asyncio.Task.uncancel); [What's New 3.13](https://docs.python.org/3/whatsnew/3.13.html) |
| 10 | `asyncio` (policy layer) | `asyncio.get_event_loop_policy().get_event_loop()` | In 3.14, calling this with no running/set loop now **raises `RuntimeError`** instead of emitting a `DeprecationWarning` and creating a new loop. Only matters if Zikaron (or a dependency, e.g. a test fixture library) ever calls the bare `get_event_loop()` rather than `asyncio.run()`/`Runner`. **Inference**: risk is low if all of Zikaron's own async entry points go through `asyncio.run()`, but worth a grep since this fails at a different call site than the one that used the loop. | 3.14 | Changed error type | [`asyncio` policy docs](https://docs.python.org/3.14/library/asyncio-policy.html); confirmed via multiple 3.14 changelog/issue threads (see §"asyncio deep dive") |
| 11 | `asyncio` | `DatagramTransport.sendto()` | Now sends a zero-length datagram if called with an empty `bytes` object (previously a no-op); flow control accounting also changed to include the datagram header. Not used by Zikaron's Unix-socket transport as far as this audit can tell, but flagged since it is exactly a "changed semantics of an existing call" case. | 3.13 | Changed semantics | [What's New 3.13](https://docs.python.org/3/whatsnew/3.13.html) (gh-115199) |
| 12 | `sqlite3` | `Connection` (any) | A `ResourceWarning` is now emitted if a `Connection` is not explicitly `close()`d before garbage collection. Warnings-as-errors CI configs would newly fail; default CI would not notice. | 3.13 | Changed default (new warning) | [`sqlite3` docs, `Connection`](https://docs.python.org/3.13/library/sqlite3.html#sqlite3.Connection) |

**A note on item 4** (`Server.wait_closed()`): this actually landed in **3.12**, which Zikaron is
already on — it is listed because it sits directly adjacent to the 3.13 `close_clients()`/
`abort_clients()` work and it would be easy to misattribute the whole shutdown-semantics change to
3.13 when auditing by memory rather than by version tag. Kept in the table as a caution against that
exact mistake, not as a 3.13/3.14 finding.

---

## 2. `asyncio` deep dive

### Unix-domain server and socket handling
- **`cleanup_socket` (3.13, default `True`)** — covered above, table row 1. Full signature as of
  3.14: `loop.create_unix_server(protocol_factory, path=None, *, sock=None, backlog=100, ssl=None,
  ssl_handshake_timeout=None, ssl_shutdown_timeout=None, start_serving=True, cleanup_socket=True)`.
  Doc text: *"If cleanup_socket is true then the Unix socket will automatically be removed from the
  filesystem when the server is closed, unless the socket has been replaced after the server has
  been created."* [Event loop docs](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.create_unix_server).
  The identical parameter, same default, exists on `asyncio.start_unix_server()`
  ([Streams docs](https://docs.python.org/3/library/asyncio-stream.html#asyncio.start_unix_server)).
  **This is exactly Zikaron's already-found trap.** Passing `cleanup_socket=False` explicitly
  restores the 3.12 behaviour and is the mechanical fix, independent of whatever invariant-level fix
  is chosen.
- No other Unix-socket-specific change (e.g. to `sock_connect`, `open_unix_connection`) was found in
  the 3.13 or 3.14 What's New pages or in the streams/event-loop reference docs' "Changed in version"
  notes.

### `Server` object: internals and public surface
- **Public additions, 3.13**: `Server.close_clients()` — *"Close all existing incoming client
  connections. Calls close() on all associated transports."* — and `Server.abort_clients()` —
  the same but calling `abort()` instead, for immediate closure without waiting for pending
  operations. Both docs carry the same caution: *"close() should be called before close_clients()
  [or abort_clients()] when closing the server to avoid races with new clients connecting."*
  [Event loop docs, `Server`](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.Server.close_clients).
  These are pure additions (new methods), not silent — they do not change existing behaviour unless
  called.
- **`sockets` attribute**: no 3.13/3.14 change found; still a list of `asyncio.trsock.TransportSocket`
  copies (that copy-not-reference behaviour dates to 3.7).
- **`Server._active_count` → `_clients`**: private, undocumented, confirmed only by Zikaron's own
  failing test per the brief. This class of change — an internal attribute renamed as an
  implementation detail of a *documented* feature addition (`close_clients()`/`abort_clients()`,
  gh-113538) — is structurally the hardest to find by reading official docs, because private names
  are deliberately excluded from them. **If Zikaron's test suite reaches into `Server._active_count`
  or similar underscored attributes anywhere else, treat every one of those reaches as a landmine for
  this and future minor versions**; that is a maintenance property of testing on private state, not
  specific to 3.13.
- **`wait_closed()`**: see table row 4 — a 3.12 change (already in scope for Zikaron today), but
  worth re-verifying no invariant assumes the old "returns immediately if already closed" behaviour.

### Streams: `StreamReader`/`StreamWriter`
- **`StreamReader.readuntil()`** (3.13): the `separator` parameter may now be a `tuple` of separators,
  stopping at whichever is encountered first. Purely additive — old single-separator calls are
  unaffected. [Streams docs](https://docs.python.org/3/library/asyncio-stream.html#asyncio.StreamReader.readuntil).
- **`limit` parameter**: default remains `65536` (64 KiB) across `start_server`, `start_unix_server`,
  `open_connection`, `open_unix_connection`; no version-tagged change found to this default or to how
  it is enforced.
- No "Changed in version 3.13/3.14" notes were found for `StreamWriter.wait_closed()`,
  `StreamWriter.is_closing()`, `drain()`, `write()`, or `StreamReader.read()`/`readline()`/
  `readexactly()`.

### Cancellation and timeouts
- **`Task.uncancel()`** (3.13): *"Changed to rescind pending cancellation requests upon reaching
  zero."* [Coroutines and tasks docs](https://docs.python.org/3/library/asyncio-task.html#asyncio.Task.uncancel).
- **`TaskGroup`** (3.13): *"Improved handling of simultaneous internal and external cancellations and
  correct preservation of cancellation counts."* Also: *"Close the given coroutine if the task group
  is not active"* when `create_task()` is called on an inactive group (prevents an
  un-awaited-coroutine `RuntimeWarning`, but changes what happens to that coroutine — it is now
  silently closed rather than left dangling). [What's New 3.13](https://docs.python.org/3/whatsnew/3.13.html) (gh-115957, gh-116720).
- **`create_task()` family, `**kwargs`** (3.13, refined in 3.14): `asyncio.create_task()`,
  `loop.create_task()`, `TaskGroup.create_task()` now accept arbitrary `**kwargs` forwarded to the
  `Task` constructor or a custom task factory. Note the **3.13.3 regression**: an accidental
  backwards-incompatible change to how `name`/`context` were special-cased broke some custom task
  factories; this was reverted for 3.13.4+ compatibility, and in 3.14 `name` and `context` are no
  longer special-cased at all — *"the name should now be set using the name keyword argument of the
  factory, and context may be None."* If Zikaron (or a dependency) supplies a custom task factory,
  re-check it against 3.13.0–3.13.2, 3.13.3, 3.13.4+, and 3.14 separately — this one moved twice
  within the 3.13 series. [What's New 3.13](https://docs.python.org/3/whatsnew/3.13.html) (gh-128307);
  [What's New 3.14](https://docs.python.org/3/whatsnew/3.14.html).
- **`asyncio.wait_for`, `asyncio.wait`, `asyncio.timeout`/`timeout_at`, `asyncio.shield`,
  `asyncio.to_thread`, `Task.cancel`, `Task.cancelling`, `asyncio.gather`**: no "Changed in version
  3.13" or "3.14" notes found on any of these in the reference docs as of this audit. (`wait_for`'s
  most recent behaviour change, being implemented via `asyncio.timeout()` so a coroutine is no longer
  wrapped in a `Task` when `timeout` is positive, is a **3.12** change — already in scope today, but
  worth re-confirming no code compensates for the pre-3.12 wrapping behaviour.)

### Event-loop shutdown, `asyncio.run()`, signal handlers
- No "Changed in version 3.13" or "3.14" note was found for `asyncio.run()`'s own cleanup sequence
  (cancelling remaining tasks, shutting down async generators, closing the loop) or for
  `loop.add_signal_handler()`. This audit did **not** find evidence of a behaviour change here, but
  also did not find an authoritative "nothing changed" statement — see §5.
- **Event loop policy deprecation (3.14)**: `asyncio.get_event_loop_policy()`, `set_event_loop_policy()`,
  `DefaultEventLoopPolicy`, `WindowsSelectorEventLoopPolicy`, `WindowsProactorEventLoopPolicy` are all
  deprecated in 3.14 for removal in 3.16, and **`get_event_loop()`'s fallback behaviour hardens**: it
  now raises `RuntimeError` rather than emitting a `DeprecationWarning` and creating a loop, when
  there is no current loop. [`asyncio` policy docs, 3.14](https://docs.python.org/3.14/library/asyncio-policy.html).
  **Inference**: if Zikaron's service entry point uses `asyncio.run()` throughout (as the design docs'
  description of a single Unix-socket JSON-RPC service suggests), this is low risk; it would only bite
  a helper, a test fixture, or a third-party dependency that calls the bare accessor outside a running
  loop. Worth a grep for `get_event_loop(` with no immediately-preceding `asyncio.run(` context.

### Free-threading (3.14)
- **First-class free-threaded support**: *"asyncio now has first-class support for free-threaded
  builds, which enables parallel execution of multiple event loops across different threads, scaling
  linearly with the number of threads."* Previously asyncio relied on the GIL/global state and was
  not thread-safe under a no-GIL build. [`asyncio` and free-threaded Python, 3.14 docs](https://docs.python.org/3/library/asyncio-threading.html).
- Free-threading itself remains an **opt-in build** (`--disable-gil` / the `t` interpreter tag) in
  3.13 and 3.14, not the default CPython build; a standard `python3.14` from most distros or from
  `uv python install 3.14` will have the GIL. **Inference**: unless Zikaron's tooling specifically
  targets a free-threaded interpreter, this whole area is not exercised by the port under
  consideration — flagged for completeness per the brief's request, not as a live risk.
- No "default event loop policy" change specific to free-threading (beyond the general 3.14 policy
  deprecation above) was found.

---

## 3. `sqlite3` deep dive

### (a) The `sqlite3` Python module itself

Minimum SQLite version to **build** the module: **3.15.2 or newer**
([`sqlite3` docs](https://docs.python.org/3.13/library/sqlite3.html)) — unchanged in 3.13/3.14 as far
as this audit found; this is a build-time floor, not a behavioural change.

Full "Changed in version 3.12/3.13/3.14" sweep of the reference page (fetched directly, not inferred
from What's New):

- **3.12**: `Connection.autocommit` parameter/attribute added — a real behavioural fork point.
  Its default is `LEGACY_TRANSACTION_CONTROL` (pre-3.12 implicit-transaction behaviour), so existing
  3.12 code is unaffected by default, but this is the mechanism through which PEP 249-compliant
  autocommit semantics become available; not a 3.13/3.14 change but the ground truth for anyone
  reasoning about transaction behaviour going forward.
- **3.13**: positional-argument deprecation across `connect()` (`timeout`, `detect_types`,
  `isolation_level`, `check_same_thread`, `factory`, `cached_statements`, `uri`), plus
  `create_function()`, `create_aggregate()`, `set_authorizer()`, `set_progress_handler()`,
  `set_trace_callback()` — deprecation only, becomes an error in 3.15 (out of scope for this port,
  but the `DeprecationWarning`s will start appearing in test output on 3.13+).
- **3.13**: `ResourceWarning` on an unclosed `Connection` at GC time (table row 12).
- **3.13.8**: `Cursor.arraysize` / `fetchmany(size=...)` reject negative values with `ValueError`
  (table row 3).
- **3.13.14**: deleting `row_factory` or `text_factory` is disallowed (table row 2).
- **3.13**: `Connection.iterdump()` gained a `filter=` keyword-only parameter (purely additive).
- **3.14**: `sqlite3.version`/`version_info` **removed** (table row 8).
- **3.14**: named-placeholder/sequence-parameters mismatch in `execute()`/`executemany()` escalates
  from `DeprecationWarning` to `ProgrammingError` (table row 7).
- **3.14** (patch-level bug fixes, not behaviour changes to rely on or plan around): a crash fix for
  deleting/mis-setting `Connection.autocommit` to an out-of-range integer, and a fix so
  `Cursor.arraysize` assignment that overflows leaves the attribute unchanged rather than corrupting
  it to `0`.
- No "Changed in version" note was found for `enable_load_extension()`/`load_extension()` beyond the
  3.10 auditing-event addition and the 3.12 `entrypoint` parameter on `load_extension()` — i.e.
  **no 3.13/3.14 change to the extension-loading API surface** was found. Zikaron's use of
  `enable_load_extension`/`load_extension` (for `sqlite-vec`) appears unaffected on this axis.
- No "Changed in version" note was found for WAL-mode handling, `busy_timeout`, transaction
  isolation-level semantics (beyond the 3.12 `autocommit` addition), or row-factory *behaviour*
  (as opposed to the deletion restriction above) in 3.13/3.14.

### (b) The bundled SQLite *library* version: 3.45.1 → 3.53.1

This is the axis the brief calls out as measured — Ubuntu's system Python 3.12.3 links SQLite
3.45.1; uv-managed 3.13/3.14 (which vendor their own SQLite build) link 3.53.1. That is roughly
**two years and dozens of point releases** of SQLite C-library changes, entirely independent of the
Python `sqlite3` module version — this axis exists *even if Zikaron never changed Python version at
all*, purely from changing how the interpreter is obtained (Ubuntu package vs. uv-managed build).
That framing matters: **this risk is not really "Python 3.13/3.14" risk, it is "interpreter
provenance" risk**, and widening `requires-python` makes it *newly visible* rather than *newly true*.

What changed in SQLite itself between 3.45.0 (2024-01-15) and 3.53.x (2026), relevant to FTS5, WAL,
or `busy_timeout`, per [`sqlite.org/changes.html`](https://sqlite.org/changes.html) and individual
release-log pages:

- **FTS5 `tokendata` option** (3.45.0): lets a tokenizer attach extra data to each token; additive,
  changes nothing about existing tables that don't opt in.
- **FTS5 secure-delete option** (3.42.0, so already present at 3.45.1 — listed for context): removes
  forensic traces on delete. Sharp compatibility note from the FTS5 docs: *"Once one or more table
  rows have been updated or deleted with this option set, the FTS5 table may no longer be read or
  written by any version of FTS5 earlier than 3.42.0."* This is a **one-way ratchet** — if any FTS5
  table Zikaron ships or has ever touched with a 3.53.1-linked SQLite gets a secure-delete write, it
  becomes unreadable by the 3.45.1-linked build. **Inference**: relevant only if secure-delete is
  ever enabled (it is not the default); flagging because it is exactly the kind of one-directional
  compatibility trap a "just widen the version pin" decision should know about.
- **Contentless-delete FTS5 tables** (3.43.0): a new table variety; additive.
- **`fts5_tokenizer_v2` API and `locale=1` option** for locale-aware custom tokenizers (3.47.0):
  additive, and only matters if Zikaron writes a custom FTS5 tokenizer (unconfirmed either way in
  this audit — see §5).
- **FTS5 tables droppable even with an unregistered custom tokenizer** (3.47.0): a robustness fix,
  not a behaviour change to existing well-behaved usage.
- **`sqlite3_setlk_timeout()`** (3.50.0): a *new*, separate timeout interface for blocking locks,
  distinct from `busy_timeout`/`PRAGMA busy_timeout`. Not a change to `busy_timeout`'s existing
  behaviour, but a sibling mechanism Zikaron isn't using today and doesn't need to.
  [Release log](https://sqlite.org/releaselog/current.html).
- **WAL-reset corruption bug fix** (3.53.0, 2026-04-09): *"Fix the WAL-reset database corruption
  bug."* Exact text is a one-line changelog entry with no further detail surfaced by this audit —
  **this reads as a bug *fix*, i.e. 3.45.1's WAL handling is presumptively the buggier one**, which
  argues *for* the newer bundled library rather than against it, but the specific trigger conditions
  for the bug were not found and should be treated as **unconfirmed** rather than assumed harmless
  either direction.
- **No behavioural change to `busy_timeout` itself** (the `PRAGMA busy_timeout` / `sqlite3_busy_timeout()`
  mechanism Zikaron's `busy_timeout` handling presumably relies on for the Unix-socket-served
  concurrent-writer case) was found in the 3.45→3.53 changelog. The general caveats found (it is
  per-connection and resets on every new connection; it does not apply to a `DEFERRED` transaction's
  read-to-write lock upgrade, which fails with `SQLITE_BUSY` immediately regardless of the timeout)
  are **long-standing SQLite behaviour, not something that changed in this window** — sourced from
  general SQLite documentation and community write-ups
  ([`sqlite3_busy_timeout()` docs](https://www.sqlite.org/c3ref/busy_timeout.html)) rather than a
  version-tagged changelog entry, so treat the "long-standing" framing as this audit's own synthesis,
  not a quoted claim.
- **No FTS5 query-syntax or reserved-word change** was found across this window. Reserved words in
  FTS5 MATCH syntax remain `AND`, `OR`, `NOT`, `NEAR` (case-sensitive), per the current `fts5.html`;
  no changelog entry proposing to add or change reserved words in 3.45–3.53 was found. Treat as
  **stable**, not merely "unconfirmed" — the current doc text and the absence of any changelog hit
  agree.
- **Default ranking function** (`bm25()`, `k1=1.2`, `b=0.75`): no changelog entry found altering these
  constants or the default `rank` column behaviour across 3.45–3.53.

**Minimum SQLite version for FTS5 itself**: FTS5 has shipped in the SQLite amalgamation since
**3.9.0 (2015-10-14)**, per [`fts5.html`](https://sqlite.org/fts5.html) — both 3.45.1 and 3.53.1 are
far above this floor, so FTS5's mere *presence* is not in question on either interpreter; what
matters is the feature-specific floors above (secure-delete's 3.42.0 one-way compatibility line being
the one with real bite for a system already at 3.45.1+).

---

## 4. The "Changed in version 3.13/3.14" sweep — what was checked and what was not

**Checked by fetching the actual reference doc page and reading its per-function "Changed in
version" notes** (not just What's New): `asyncio` event-loop docs (`asyncio-eventloop.html`),
`asyncio` streams docs (`asyncio-stream.html`), `asyncio` tasks/coroutines docs (`asyncio-task.html`),
and the full `sqlite3` reference page (`docs.python.org/3.13/library/sqlite3.html`).

**Checked only via targeted search, not a full per-function doc-page read**: `socket` (found: new
`SO_BINDTOIFINDEX` on Linux in 3.13, restoration of `socket.CAN_RAW_ERR_FILTER` in 3.13.4 — both
additive, no behaviour-change hits found), `subprocess` (found: a `STARTUPINFO.dwFlags`
Windows-only addition in 3.13, and an internal lazy-import-of-`locale`/`signal` optimization that
was introduced and then **reverted** within the 3.13 series after it broke `__del__` finalizers
calling `terminate()`/`kill()`/`send_signal()` — worth knowing only in that it shows the
subprocess-teardown path was actively unstable across 3.13 point releases, not that anything is
wrong at 3.13.14+ or 3.14), `signal` (found: no version-tagged behaviour change to SIGINT/default
handler semantics between 3.12, 3.13 and 3.14 in the doc text checked).

**Not checked via a per-function doc-page sweep at all** (relied only on the What's New pages, which
are known to be incomplete for this purpose, or on nothing): `pathlib`, `os`, `threading`, `logging`,
`json`, `tempfile`, `contextlib`, `dataclasses`, `typing`, `enum`, `uuid`, `time`, `re`, `stat`,
`errno`, `argparse`, `shlex`, `datetime`, `urllib`, `shutil`, `itertools`, `hashlib`, `weakref`,
`importlib`, `sysconfig`, `tomllib`. The 3.14 What's New fetch (§ background research above) surfaced
no behaviour-changing item for any of these beyond purely additive features (new methods, new
constants, new CLI flags) — nothing in that pass read as a changed default or changed return type for
this group — but that pass was a page-level extraction, not the per-function "Changed in version"
sweep the brief asks for, and **should not be read as "these modules are clear."** This is the
single largest gap in this audit; see §5.

---

## 5. What could NOT be determined

- **The `Server._active_count` → `_clients` rename**: could not find an authoritative source (CPython
  commit, PR diff, or doc note) stating the old and new attribute names explicitly. This audit relies
  on Zikaron's own already-observed test failure for that fact; treat the *mechanism* (part of the
  gh-113538 `close_clients()`/`abort_clients()` redesign) as confirmed, but the exact old→new name
  mapping as **reported by Zikaron, not independently re-verified here**.
- **A full per-function "Changed in version" sweep of the 27 lower-priority stdlib modules** listed in
  §4's last paragraph was not performed — only a page-level What's New pass. Given `pathlib` (gained
  `copy()`/`move()`/`info` in 3.14 — additive) and `datetime`/`enum`/`dataclasses` are the modules
  most likely to hide a changed default among that set based on their history in earlier Python
  versions, they would be the next place to spend audit time if this port proceeds.
- **Whether Zikaron ever calls `asyncio.get_event_loop()` outside a running loop**, which would newly
  raise `RuntimeError` on 3.14 rather than warn-and-create. Not checked against Zikaron's own source
  in this audit (out of scope — this note covers only public stdlib behaviour, not Zikaron's call
  sites); a grep is a five-minute follow-up.
- **Whether Zikaron writes a custom FTS5 tokenizer or enables `secure-delete`.** If either is true,
  the `fts5_tokenizer_v2`/`locale=1` addition (3.47.0) and the secure-delete one-way compatibility
  line (3.42.0+, already true even at 3.45.1) both become directly relevant; this audit does not know
  Zikaron's schema/indexing code well enough to say either way and did not read `design/schema.md` or
  `design/indexing.md` as part of this task (scope was the stdlib porting question only).
  `zikaron/knowledge-index.md`'s indexing scheme was not consulted.
- **Exact trigger conditions for the 3.53.0 "WAL-reset database corruption bug" fix.** The changelog
  entry is a single line; no CPython/SQLite forum thread describing the failure mode was located in
  the time budget for this audit. Whether it could have silently affected Zikaron's WAL usage on
  3.45.1 is genuinely unknown — flagged, not resolved.
- **Whether `busy_timeout` has any version-tagged behaviour change** across 3.45→3.53 — no changelog
  hit was found, which this note reports as "stable," but a changelog silence is weaker evidence than
  a positive confirming statement; SQLite's changelog granularity varies release to release and a
  small behavioural tweak folded into a larger release entry could have been missed by keyword search.
- **`multiprocessing`/`concurrent.futures` default start-method change** (`fork` → `forkserver` on
  non-macOS Unix, 3.14) was found but is out of the brief's module list (Zikaron does not appear to
  import `multiprocessing` per the priority list given) — noted here only so it is not silently
  dropped if that assumption is wrong.

---

## Sources

1. [What's New In Python 3.13](https://docs.python.org/3/whatsnew/3.13.html) — CPython official docs
2. [What's New In Python 3.14](https://docs.python.org/3/whatsnew/3.14.html) — CPython official docs
3. [Event loop — asyncio, current docs](https://docs.python.org/3/library/asyncio-eventloop.html) — `create_unix_server`, `Server` class, `close_clients`/`abort_clients`/`wait_closed`
4. [Streams — asyncio, current docs](https://docs.python.org/3/library/asyncio-stream.html) — `start_unix_server`, `StreamReader.readuntil`
5. [Coroutines and tasks — asyncio, current docs](https://docs.python.org/3/library/asyncio-task.html) — `TaskGroup`, `Task.uncancel`, `create_task` kwargs
6. [Policies — asyncio, 3.14 docs](https://docs.python.org/3.14/library/asyncio-policy.html) — event loop policy deprecation, `get_event_loop()` `RuntimeError`
7. [asyncio and free-threaded Python — 3.14 docs](https://docs.python.org/3/library/asyncio-threading.html)
8. [sqlite3 — DB-API 2.0 interface, 3.13 docs](https://docs.python.org/3.13/library/sqlite3.html) — full "Changed in version 3.12/3.13" sweep, minimum SQLite build version
9. [gh-113538, "Cannot cleanly shut down an asyncio based server"](https://github.com/python/cpython/issues/113538) — origin of `close_clients()`/`abort_clients()`, context for the `_active_count`/`_clients` internal change
10. [gh-111246 reference via typeshed PR #15792](https://github.com/python/typeshed/pull/15792) — `cleanup_socket` parameter typing, corroborating default `True`
11. [o3de/o3de issue #19644](https://github.com/o3de/o3de/issues/19644) — real-world breakage example from `sqlite3.version` removal in 3.14
12. [SQLite Release History](https://www.sqlite.org/changes.html) — top-level changelog index
13. [SQLite Release 3.53.1](https://sqlite.org/releaselog/3_53_1.html) and [3.53.0/current release log](https://sqlite.org/releaselog/current.html) — WAL-reset bug fix, `sqlite3_setlk_timeout()`
14. [SQLite FTS5 Extension documentation](https://sqlite.org/fts5.html) — minimum version (3.9.0), secure-delete compatibility note, reserved words, default `bm25()` ranking
15. [SQLite `sqlite3_busy_timeout()` C API docs](https://www.sqlite.org/c3ref/busy_timeout.html) — long-standing (not version-specific) `busy_timeout` semantics
