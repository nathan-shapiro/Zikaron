# v0 schema

> Written 2026-08-01. Reconciles D1–D32. Companion to `design/architecture.md` (process model, RPC, MCP
> surface), `design/indexing.md` (chunking contract) and `design/consolidation.md`.
> Verified locally: stdlib `sqlite3` 3.45.1 on Python 3.12.3 has **FTS5 compiled in** and
> `enable_load_extension` available for `sqlite-vec`.

## The main structural decision: one table, not two

`~/Memory` uses separate `journal` and `memory` tables. Zikaron uses **one `memory` table with a `tier`
column**, because in Zikaron the two tiers have become identical in every respect that would justify
separate tables:

| | `~/Memory` | Zikaron |
|---|---|---|
| shape | journal has `text` only; memory has `gist`+`content` | **both** carry `gist`+`content` — D6 has the agent author a gist on every write, and D12 injects gists, so a journal entry without one could never be surfaced |
| amendable | journal append-only | **both** — D11's repair loop and D26's version apply to journal rows too |
| retrieved | `journal(consolidated=0) ∪ memory(active=1)` | **both**, D15, in one ranking |
| chunked | n/a | **both**, D28 |

Two tables would mean two FTS5 indexes, two `vec0` tables, and a union-plus-merge on every read for no
gain. One table means one index, one query, one code path.

**Consequence: "consolidated" is not a flag.** A journal row is unprocessed iff
`tier='journal' AND active=1`. Consolidation either flips `tier` to `long_term` in place, or retires the row
with `superseded_by` pointing at the record it merged into, or retires it outright as discarded. If the
consolidator returns nothing for a row, none of those happen and the row is picked up next run — D29's
never-lose guard expressed structurally instead of with a separate boolean.

`consolidation_group_member.disposition` is a **plan-tracking** column, not a second source of truth: it
records what a run did so a group's completeness can be checked (invariant 16) and so `remaining_uuids` can
be computed. The authoritative answer to "is this row consolidated" remains the `memory` row itself, which
is why a run that ends without completing — `expired`, `abandoned` or `taken_over` — loses nothing — and why a member that left the journal between plan and
serve can simply be marked `'vacated'` without anyone having to reconcile two truths.

## Tables

```sql
PRAGMA journal_mode = WAL;          -- concurrent readers: service + hook degraded path + a 2nd session
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────────────────────
-- memory: both tiers (D3, D4)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE memory (
  rowid          INTEGER PRIMARY KEY,          -- FTS5 external-content linkage
  uuid           TEXT    NOT NULL UNIQUE,      -- D4; the handle exposed to the agent
  tier           TEXT    NOT NULL DEFAULT 'journal'
                         CHECK (tier IN ('journal', 'long_term')),
  gist           TEXT    NOT NULL,             -- D4, D13: relevance triage
  content        TEXT    NOT NULL,             -- D4: stored untruncated, always
  active         INTEGER NOT NULL DEFAULT 1    CHECK (active IN (0, 1)),   -- D16 soft retire
  superseded_by  TEXT             REFERENCES memory(uuid) ON DELETE RESTRICT,  -- D25
  version        INTEGER NOT NULL DEFAULT 1    CHECK (version >= 1),      -- D26
  created_at     TEXT    NOT NULL,             -- D27, UTC ISO-8601
  updated_at     TEXT    NOT NULL,             -- D27
  session_id     TEXT,                         -- D27: consolidation grouping, audit
  token_count    INTEGER NOT NULL DEFAULT 0,   -- current size of THIS row; per-write sizes live in `event`

  -- Declarative guards. The graph rules a CHECK cannot express (acyclicity,
  -- target state) are code invariants below.
  CHECK (length(trim(gist))    > 0),                              -- no empty prose (indexing.md §preflight)
  CHECK (length(trim(content)) > 0),
  CHECK (superseded_by IS NULL OR superseded_by <> uuid),          -- no self-edge
  CHECK (superseded_by IS NULL OR active = 0)                      -- superseded ⇒ retired (D25/D16)
);

CREATE INDEX idx_memory_unconsolidated ON memory(tier, active, created_at);  -- D29 oldest-first scan
CREATE INDEX idx_memory_eligible       ON memory(active, superseded_by);     -- the retrieval predicate below
CREATE INDEX idx_memory_superseded     ON memory(superseded_by);             -- D25 correction lookup
CREATE INDEX idx_memory_session        ON memory(session_id);                -- D30 writes-per-session

-- ─────────────────────────────────────────────────────────────────────────────
-- Lexical index: UNCHUNKED over the whole record (D28)
-- Plain unicode61 tokenizer — D24 measured that custom `tokenchars` COSTS
-- -0.052 useful-recall on its own, so the default is the evidence-backed choice.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE VIRTUAL TABLE memory_fts USING fts5 (
  gist, content,
  content      = 'memory',
  content_rowid= 'rowid',
  tokenize     = 'unicode61'
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Dense index: CHUNKED (D28). One row per chunk.
-- Split into a normal table + a bare vec0 table rather than relying on vec0
-- metadata columns, whose syntax varies across sqlite-vec versions. The vec0
-- rowid is the chunk_id, so the join is free.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE memory_chunk (
  chunk_id     INTEGER PRIMARY KEY,
  memory_uuid  TEXT    NOT NULL REFERENCES memory(uuid) ON DELETE CASCADE,
  part_index   INTEGER NOT NULL,
  token_count  INTEGER NOT NULL,
  truncated    INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)),  -- D28 canary
  embed_model  TEXT    NOT NULL,          -- D20 reindex guard
  embed_dim    INTEGER NOT NULL,          -- D20: guards the fixed-dim vec0 contract
  UNIQUE (memory_uuid, part_index)
);

CREATE INDEX idx_chunk_memory ON memory_chunk(memory_uuid);

-- TEMPLATE, not a literal: <embed_dim> is substituted with the VALIDATED EFFECTIVE
-- embed_dim at creation. 384 is only the v0 default (bge-small, D20). vec0 fixes a
-- column's width at CREATE time, so this is the one DDL that cannot be written as a
-- constant while embed_dim is configurable -- see "Creating the dense index" below.
CREATE VIRTUAL TABLE memory_vec USING vec0 (embedding float[<embed_dim>]);
-- INVARIANT: memory_vec.rowid == memory_chunk.chunk_id

-- ─────────────────────────────────────────────────────────────────────────────
-- event: append-only log backing D30's six instrumented signals
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE event (
  id          INTEGER PRIMARY KEY,
  at          TEXT NOT NULL,
  session_id  TEXT,
  client_kind TEXT NOT NULL CHECK (client_kind IN ('hook', 'mcp', 'consolidator')),
                                    -- from the request envelope. Makes cross-client session linkage
                                    -- OBSERVABLE: pushes come from 'hook', writes from 'mcp'.
                                    -- No 'service' value: every v0 event is emitted inside a client
                                    -- call, which is also why invariant 18 can hold.
                                    -- NO label_source column. It is DERIVED from session_id --
                                    -- `session_id LIKE 'zk-%'` is 'minted', anything else is
                                    -- 'harness' -- so storing it would be a second source of truth
                                    -- for a pure function (architecture.md §"`label_source` is
                                    -- derived, not stored").
  op_id       TEXT NOT NULL,        -- one RPC = one op_id; correlates the events of a single call
  kind        TEXT NOT NULL CHECK (kind IN (
                'surface_call',     -- push path fired; EXISTS EVEN AT ZERO RESULTS
                'surface',          -- one per memory the push path returned (D12)
                'search',           -- pull path
                'fetch',
                'remember',
                'amend',
                'retire',
                'merge',            -- consolidator: rewrote a long-term record
                'promote',          -- consolidator: created or flipped a long-term record
                'discard',          -- consolidator: retired journal rows as noise
                'dedup_offered',    -- D15 handed back a near-duplicate
                'version_conflict', -- D26 rejected a write
                'no_receipt',       -- D26 rejected a write for want of a read receipt
                'group_served',     -- one per row a consolidation serve actually delivered
                'consolidate_run'
              )),
  memory_uuid TEXT,
  detail      TEXT                  -- JSON; per-kind shape fixed below, never free-form
);

CREATE INDEX idx_event_kind_at ON event(kind, at);
CREATE INDEX idx_event_session ON event(session_id);
CREATE INDEX idx_event_session_kind ON event(session_id, client_kind);  -- linked-session coverage
CREATE INDEX idx_event_op      ON event(op_id);
CREATE INDEX idx_event_uuid_at ON event(memory_uuid, at);   -- locates the rows about one uuid for the
                                    -- "surface then amend" signal; that signal GROUPS by
                                    -- (session_id, memory_uuid) and ORDERS by event.id, since `at` collides

-- ─────────────────────────────────────────────────────────────────────────────
-- read_receipt: what makes D26's read-before-write mechanical rather than trusted
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE read_receipt (
  session_id   TEXT    NOT NULL,
  client_kind  TEXT    NOT NULL,    -- REQUIRED in the key: since 2026-08-01 every client of one
                                    -- kiro session shares one session_id (a subagent's MCP client
                                    -- reads the PARENT's KIRO_SESSION_ID), so without this column a
                                    -- receipt minted by next_group's serve would license the PRIMARY
                                    -- agent to amend that row without ever fetching it. Lost-update
                                    -- protection never depended on it (the version must still match)
                                    -- but D6's read-before-amend would have decayed from "this agent
                                    -- read it" to "some client of this session did".
  memory_uuid  TEXT    NOT NULL REFERENCES memory(uuid) ON DELETE CASCADE,
  version      INTEGER NOT NULL,
  at           TEXT    NOT NULL,
  source       TEXT    NOT NULL CHECK (source IN (
                 'fetch',           -- zikaron_fetch delivered full content
                 'group',           -- zikaron_next_group delivered full content
                 'conflict',        -- a rejected write returned the current full record
                 'own_write'        -- the caller authored this exact prose (remember/amend/merge/promote)
               )),
  PRIMARY KEY (session_id, client_kind, memory_uuid, version)
) WITHOUT ROWID;

-- ─────────────────────────────────────────────────────────────────────────────
-- Consolidation runs and groups: persisted so a group_id survives a restart and
-- cannot be handed to two consolidators (architecture.md §Consolidation lifecycle)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE consolidation_run (
  run_id      TEXT PRIMARY KEY,
  session_id  TEXT    NOT NULL,     -- with pid, the OWNER PAIR. NOT NULL since 2026-08-01: every
  pid         INTEGER NOT NULL,     -- client of one kiro session shares a session_id, so session
                                    -- alone no longer identifies a worker, and a NULL in either
                                    -- column would silently collapse ownership back to session-only.
                                    -- architecture.md rejects a missing envelope `pid` with `bounds`.
  started_at  TEXT NOT NULL,
  expires_at  TEXT NOT NULL,        -- lease; refreshed by every successful call in the run
  status      TEXT NOT NULL CHECK (status IN ('active', 'complete', 'expired', 'abandoned',
                                               'taken_over'))
);

CREATE TABLE consolidation_group (
  group_id    TEXT PRIMARY KEY,
  run_id      TEXT NOT NULL REFERENCES consolidation_run(run_id) ON DELETE CASCADE,
  anchor_uuid TEXT             REFERENCES memory(uuid) ON DELETE RESTRICT,  -- NULL for orphan groups
  order_key   TEXT NOT NULL,        -- 'earliest_created_at|min_uuid' of the PRE-SHARD cohesive subgroup,
                                    -- so every shard of one subgroup carries the SAME order_key and
                                    -- `shard_index` is the load-bearing tiebreak between them
  shard_index INTEGER NOT NULL DEFAULT 1,   -- 1-based position of this shard within its subgroup
  shard_count INTEGER NOT NULL DEFAULT 1,   -- total shards the subgroup was split into; 1 when unsplit
  status      TEXT NOT NULL CHECK (status IN ('pending', 'served', 'complete', 'deferred')),
  serve_count INTEGER NOT NULL DEFAULT 0,   -- deliveries of this group in this run, INCLUDING the first;
                                            -- `pending → served` sets 1. Deferred once it reaches
                                            -- `max_group_serves` (invariant 17)
  served_at   TEXT,
  CHECK (shard_count >= 1),
  CHECK (shard_index BETWEEN 1 AND shard_count),
  CHECK (serve_count >= 0)
);

CREATE INDEX idx_group_run_order ON consolidation_group(run_id, status, order_key, shard_index);

-- SHARD IDENTITY IS PERSISTED, NOT RECOMPUTED, and both halves of it are. `consolidation.md` step 4
-- requires the payload to carry `shard: {index, of}` and `architecture.md` §`zikaron_next_group` exposes
-- it, so `of` has to survive a service restart like everything else the lifecycle promises to recover
-- from state. Storing only `shard_index` would have left `of` derivable in exactly one way — replanning
-- the cohesive subgroup from the current store — which is illegal twice over: membership is frozen at
-- plan time (invariant 16's premise), and the store has moved since, because D29 processes groups
-- oldest-first with earlier groups mutating it. Both fields are written at plan time and returned
-- verbatim on every serve. Indices are **1-based**, so an unsplit group is `{index: 1, of: 1}` rather
-- than a third convention meaning "not sharded"; invariant 19 states the completeness condition.

CREATE TABLE consolidation_group_member (
  group_id     TEXT    NOT NULL REFERENCES consolidation_group(group_id) ON DELETE CASCADE,
  memory_uuid  TEXT    NOT NULL REFERENCES memory(uuid) ON DELETE RESTRICT,
  version_seen INTEGER NOT NULL,    -- version at PLAN time. Change detection only — NOT the version
                                    -- the payload carries; see `version_served`.
  version_served INTEGER,           -- version whose prose was actually delivered on the most recent serve
                                    -- that delivered this row, and the version its receipt was minted at.
                                    -- This is the `expected_version` the payload carries. NULL IFF the row
                                    -- has never been delivered (see §"The `event` log, per kind").
  disposition  TEXT             CHECK (disposition IN ('merged', 'promoted', 'discarded', 'vacated')),
  disposed_at  TEXT,
  PRIMARY KEY (group_id, memory_uuid)
) WITHOUT ROWID;
-- MEMBERS ARE JOURNAL ROWS ONLY. The anchor and the candidates are long-term records the group is
-- shown *against*; they are never dispositioned, so they are not members. That is why invariant 16
-- can define completeness as "no member left undispositioned" without stranding an anchor.
-- 'vacated' means the row left the journal by another path between plan and serve (a primary agent
-- retired it, or promoted it) — it is not delivered, it blocks nothing, and nothing was lost. It
-- COUNTS AS DISPOSITIONED, so vacating the last open member closes the group inside the serve
-- transaction itself (invariants 16-17); it does not leave the group waiting for a write verb that
-- has nothing left to write.

CREATE INDEX idx_group_member_open ON consolidation_group_member(group_id, disposition);

-- The exact set a `merge` is authorized to target, persisted at serve time so authorization survives
-- a service restart and does not depend on recomputation. Rewritten on each (re-)serve, in the same
-- transaction as the serve. `group_served` events are instrumentation; THIS is the authority.
CREATE TABLE consolidation_group_candidate (
  group_id       TEXT    NOT NULL REFERENCES consolidation_group(group_id) ON DELETE CASCADE,
  memory_uuid    TEXT    NOT NULL REFERENCES memory(uuid) ON DELETE RESTRICT,
  role           TEXT    NOT NULL CHECK (role IN ('anchor', 'candidate')),
  version_served INTEGER NOT NULL,  -- version whose prose was delivered; the receipt's version
  rank           INTEGER NOT NULL,  -- 0 for the anchor; 1..N for candidates, in retrieval order
  PRIMARY KEY (group_id, memory_uuid)
) WITHOUT ROWID;

-- ─────────────────────────────────────────────────────────────────────────────
-- meta: store-level configuration and the reindex guard
-- Every key, its type, range, v0 default and validation rule is in
-- §"`meta` -- the store-coupled values, and the initialization contract" below.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

### Creating the dense index — the one width-bound DDL

`embed_dim` is a config key (§"Configuration keys") **and** a `meta` row, and `vec0` fixes a column's width at
`CREATE` time. Those two facts together mean the `memory_vec` DDL above is a **template**, and three things must
happen in one transaction at store creation, in this order:

1. Resolve the effective config and validate `embed_dim` (integer, ≥1).
2. **Load the embedder named by the effective `embed_model` and check the width it actually emits equals that
   `embed_dim`.** A mismatch is `−32023 bad_config` naming both values, *before* any table exists. Without this
   check a typo produces a store whose every write fails at insert time with a dimension error that points at
   the wrong culprit — the file says 768, the model emits 384, and nothing has said which is wrong.
3. Create `memory_vec` at that width and write `embed_model` / `embed_dim` into `meta`.

**On a later open**, `meta.embed_dim` is authoritative and is compared against both the `vec0` column width and
the config's value; any disagreement is invariant 11's forced reindex, not a silent continue.

**A dimension-changing reindex is not an in-place migration.** It must **drop and recreate** `memory_vec` at the
requested width — `vec0` cannot widen a column — and only then re-embed every chunk and update `meta.embed_dim`.
That whole sequence runs inside invariant 3's unavailable window, with the `reindexing` sentinel set, because
between the drop and the last insert the dense index does not describe the store. This is the sharpest
difference between the two hard keys: a changed `embed_model` at the same width can in principle re-embed into
the existing table, while a changed `embed_dim` cannot.

**v0 scope, stated plainly:** the only value exercised by any measurement is **384**. The key is honoured rather
than pinned so that D20's deferred question — whether a more capable embedder helps, `FINDINGS.md` open
question 8 — is a config edit plus a reindex rather than a schema change. Any other width is untested.

## The knowledge-base registry

`memory.db` carries one table that is **not** part of the memory store and is **not** created by store
creation. It is the registry the knowledge index keys its corpora on; `design/knowledge-index.md` §3.1a is
normative for what it means, and this section is the contract for its shape and its creation.

```sql
CREATE TABLE IF NOT EXISTS knowledge_bases (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL,
  created_at  TEXT NOT NULL,

  CHECK (length(trim(name)) > 0),
  CHECK (name = lower(name))
)
```

`id` is a server-generated uuid4 and names the KB's own database file at `.zikaron/knowledge/<id>.db`. `name`
is free-form and lower-cased on write with Python's `str.lower()`; the `UNIQUE` constraint on a `TEXT` column
compares under the default `BINARY` collation, which is the plain string equality invariant 14 states. Both
are constraints rather than caller discipline, because the alternative is a rule enforced by every call site
and by none of them.

**The `lower(name)` `CHECK` is a partial backstop and is documented as one, because SQLite's `lower()` is
ASCII-only** (measured). Two consequences, and only the second is a limit:

- **It never rejects a correctly normalised name.** SQLite's `lower()` maps `A`–`Z` and nothing else, and a
  string that has been through Python's `str.lower()` contains no `A`–`Z`, so `name = lower(name)` holds for
  every value the write path can produce. That is a proof rather than a sample, which is what makes the
  constraint safe to impose on free-form text including non-ASCII.
- **It catches an un-normalised name only when one contains an ASCII capital.** A writer that skipped the
  normalisation and inserted `ΣΟΦΙΑ` satisfies the `CHECK`, because SQLite leaves every one of those
  characters alone. The constraint is therefore a cheap guard against the common mistake, not an enforcement
  of invariant 14 — that rests on the write path, which is where the test for it lives.

### Additive tables and the version gate

**`meta.schema_version` is not bumped for this table, and the rule that licenses it is stated here so the
next such change is decided by a rule rather than by convenience.**

> **The version gates compatibility, not content.** It is bumped when a binary at the old version would read
> the store **wrongly** — a changed table, a changed index an invariant rests on, a changed meaning of an
> existing key, or a new invariant an old binary would violate by writing. It is **not** bumped for a table
> that no older code path reads or writes and that no existing invariant mentions: every read and write an
> older binary performs over such a store is exactly as correct as it was before.

`knowledge_bases` is the first change of that kind. Bumping would make every older build refuse the store
outright with `−32024 schema_incompatible` — the correct answer for a schema it cannot read, and the wrong
one for a schema it can — and would force the supported-range-plus-migration contract §"Migration posture"
defers, for a change that needs none of its machinery.

**What the rule obliges in exchange is a single idempotent creation site.** A store created before this
table existed must still open and serve memory, so the table is created **on first use by the knowledge
registry**, with the `CREATE TABLE IF NOT EXISTS` above, for every store alike. It is deliberately absent
from §Tables' DDL block and from store creation: a second, eager creation path for fresh stores would buy
nothing — the idempotent one is needed regardless — and would give two copies of one statement room to
disagree. It is also what makes "a store predating this table opens and answers normally" true by
construction rather than by test, since the memory store's own open path is not touched at all.

**Measured, because the ensure runs on every registry open and the memory path's latency is what the
knowledge index's out-of-process indexer exists to protect:** `CREATE TABLE IF NOT EXISTS` against a table
that **already exists** takes no write lock — it succeeds while another connection holds the writer lock —
while the same statement against an absent table does take it and blocks. The steady-state cost is a schema
read, and contention is possible only on the one occasion the table is genuinely created.

**This table is outside every invariant in §"Invariants the code must hold".** Those are stated over the
memory store, and none of them mentions it; the knowledge index states its own (`knowledge-index.md` §13,
invariants 11, 14 and 15 covering this table). Said explicitly because an invariant list that silently
acquired a table would be the enumeration drift this corpus keeps convicting itself of.

## `meta` — the store-coupled values, and the initialization contract

**`meta` holds only what is coupled to the bytes already stored.** Operator preferences live in TOML — two
layers, resolved per store — and are specified in `architecture.md` §"Configuration" with their keys listed
in §"Configuration keys" below. The dividing rule, and it is the whole rule: **a value belongs in `meta` if
changing it would invalidate or fragment data already written.** Everything else expresses intent and is a
file key.

This split was made after the corpus review, when the user asked why configuration was in the database at
all. It was a genuine conflation: no config file existed anywhere in the design, so `meta` had absorbed every
setting by default rather than by decision. Nineteen of its twenty-four keys moved out outright. Of the five that remain, `schema_version` and
`store_id` are not configurable at all, while **`embed_model`, `embed_dim` and `chunk_max_tokens` are
dual-homed** — the file states intent and seeds them at creation, `meta` records what the existing index
was built with. The transient `reindexing` sentinel was never configuration.

Every key below is written at store creation from the **effective config** (`architecture.md`
§"Configuration"), so a fresh store is fully described and nothing reads a missing key. Values are stored
as text and parsed to the stated type. All five are **required** on open.

**Validation happens twice**, and both are required: on **store creation** (write the defaults) and on
**every store open** (parse and range-check every required key). A required key that is missing,
unparseable, or out of range on open is a **fatal store error**, not a fall-back-to-default — silently
substituting a default is how two deployments end up ranking differently while both look healthy. The
service refuses to serve, returns `−32023 bad_config` naming the key, and logs it.

**A configuration error is not something the degraded path can route around.** An earlier draft had the
degraded hook path re-validate the same keys a `bad_config` had just declared unusable, so it could attempt a
fallback read anyway — which meant re-deriving values the rule above forbids substituting a default for, or
ranking differently while looking healthy, which is the exact failure this rule exists to prevent. The hook no
longer attempts this at all: on `bad_config` it logs the exact detail to `hook.log` and exits 0 with a
model-facing relay instruction on stdout, uniformly with every other failure (`architecture.md` §"Degraded
modes"). There is no validation for the degraded path to perform, because there is no read for that
validation to protect.

**Unknown keys are tolerated; a newer `schema_version` is not.** An unknown key on a *supported* version is
left alone and logged once, so a newer writer's extra settings do not brick the store. That is deliberately
**not** a forward-compatibility claim, and reading it as one was a defect: an unknown key says nothing about
whether the tables, indexes, invariants, or the meaning of the *existing* keys changed under a newer writer.
v0 therefore supports **exactly `schema_version = 1`**. A value `> 1` is refused with a stable
`−32024 schema_incompatible` naming what was found and what is supported; a value `< 1` or unparseable is
`bad_config` by the range rule. Compatibility is asserted by the version, never inferred from key tolerance.

| Key | Type | Range | v0 default | Notes |
|---|---|---|---|---|
| `schema_version` | int | **exactly `1`** in v0 | `1` | `> 1` ⇒ `−32024 schema_incompatible`, not `bad_config`; migration posture below |
| `store_id` | uuid string | 36 chars, uuid4 | **minted at creation** | not user-configurable; `health()` returns it (`architecture.md` §"Store identity") |
| `embed_model` | string | non-empty | from the effective config at creation (`BAAI/bge-small-en-v1.5`) | **dual-homed with the config file, hard.** Seeded here at creation; authoritative thereafter, so a file that disagrees is *requesting* a change and the answer is invariant 11's forced reindex, never a silent switch |
| `embed_dim` | int | ≥1 | from the effective config at creation (`384`) | **dual-homed with the config file, hard.** Must equal the `vec0` column width, which is fixed at creation — so unlike `embed_model` a disagreement here cannot be reindexed in place at all |
| `chunk_max_tokens` | int | 64–8192 | from the effective config at creation (`450`) | **the dual key.** Records the budget the *existing* chunks were cut at. The config file governs **new** writes; a mismatch is **soft** — logged, store simply heterogeneous, never a refusal, because old chunks are valid vectors of valid text. Contrast the hard `embed_model` case (invariant 11) |

**`reindexing` is a sentinel, not configuration, and is deliberately not in the table above.** It is a
transient key inserted when invariant 3's unavailable window opens and **deleted** when it closes; its value
is the ISO-8601 instant the window opened. Its **absence is the normal state**, so it is *exempt from
required-key validation* — an open that finds it absent proceeds, and an open that finds it **present**
concludes the previous process died mid-reindex and must finish or restart the reindex before serving
(`−32022 reindexing` until then). Listing it as a required key with default "absent" was a straight
contradiction of the paragraph above it; this is the correction. **Only the service checks it, and that is
sufficient:** the service is the only reader of the store, and a `reindexing` result from it produces the
same response from the hook as every other failure — one line to `hook.log` plus a model-facing relay on
stdout, never a read (`architecture.md` §"Degraded modes"). An earlier draft had the hook itself check this
sentinel before running a fallback query of its own; there is no fallback query left to guard.

**One setting deliberately does not live in `meta`: the consolidator's model.** D29 requires it to be a
config value, and the store is the wrong home for it — the store does not spawn the subagent, D10's skill
does, and the harness reads the model from the agent config. It is located, typed and defaulted in
`architecture.md` §"Distribution artefacts" instead. Named here so a reader looking for "the model setting"
in the config contract is not left concluding it does not exist.

**The three cosine cutoffs share one primitive, and it is directional.** Define, for an ordered pair of
memories:

> **`s(X → Y)`** = the *best* (maximum) cosine between **X's first chunk** embedding and **any chunk of Y**.

- This is the same rollup the dense arm already performs (`retrieval.md` §"The dense arm, precisely"), read in
  cosine rather than distance. X is the **querying** memory; Y is the **candidate**.
- **`s` is not symmetric, and every cutoff must therefore say which direction it takes.** X contributes one
  vector (its first chunk) while Y contributes its best of many, so on a pair where one memory is chunked and
  the other is not, `s(A → B) ≠ s(B → A)` in general. Writing a cutoff as `cos(A, B)` left that undefined and
  would change graph edges — and therefore groups — between two conforming implementations.

| Cutoff | Directed quantity thresholded | Why that direction |
|---|---|---|

`min` rather than `max` or a mean, for the same reason the edge test already demands mutual top-K: an edge
should require agreement from both endpoints, and the conservative direction is the safe one here because
`consolidation.md` step 2 argues explicitly that over-splitting costs one extra call while under-splitting
manufactures a false record. The **cohesion pass consumes this same edge relation** and computes no score of
its own, so the definition applies there unchanged.

The rest of the arithmetic is shared by all three:

- `vec0` returns an **L2 distance** `d` over vectors normalized at write time, so
  `cos = 1 − d²/2` and `cos ≥ t` is implemented as `d ≤ sqrt(2(1 − t))`. At `t = 0.65` that is
  `d ≤ 0.8367`; at `t = 0.80`, `d ≤ 0.6325`. Stated as a formula so nobody thresholds the wrong quantity.
- Boundary semantics are **inclusive**: `cos ≥ cutoff` passes. Uniformly, for all three.
- Cutoffs are *not* thresholds on the fused RRF score, and that is deliberate. An RRF score is a function of
  ranks, so "one arm ranked it first, the other missed it" (`1/61 = 0.0164`) scores *below* "both arms ranked
  it fiftieth" (`2/110 = 0.0182`). That makes a fused score a poor similarity proxy — the same arm-agreement
  effect `retrieval.md` documents as the known fusion defect. So the hybrid decides *which* record is the
  candidate and the cosine floor decides *whether* it is close enough.

**What the three cosine seeds are worth: they are provisional heuristics, not measurements.**
`design/consolidation.md` §"Where the three cosine seeds come from" gives the reasoning
behind `anchor_cutoff` / `orphan_edge_cutoff` / `dedup_threshold` and states plainly that **no persisted
measurement backs their values.** A probe run during round-2 remediation is deliberately *not* quoted as
evidence: it scored whole-record vectors rather than the `s(X → Y)` quantity defined above, so it did not
measure this estimand, and it was never persisted. Every one of the three is a **config-file** key precisely so that
replacing a seed with a number is a measurement rather than a code change.

**Nothing measured locates any pair population on the `s` axis, in either direction.** Stated here as well as
in `consolidation.md` because a schema reader picking a threshold is exactly who would otherwise assume
someone had checked: the approved instrument
(`research/embedder-benchmark-results.md` §7) measured **query→passage** cosines — its probe is a bare
identifier token or the carrier sentence "Tell me about X." — not the similarity between two stored memories.
So its absolute cosine levels say nothing about where a duplicate pair or a version-twin pair sits relative to
`0.80`, and no duplicate population was measured at all. What the instrument *does* establish is about the
**signal**, not the threshold: with topic held constant, a near-miss identifier buys only about a fifth
(discrimination index **0.194–0.233**) of the separation the same model gets from a plainly distinct token. A
value moved on the strength of a level from that report would be moved on a misread.

## Configuration keys

**Twenty-three file keys: nineteen that moved out of `meta` outright, three dual-homed ones**
(`embed_model`, `embed_dim`, `chunk_max_tokens`) that also persist in `meta` as the record of what the
existing index was actually built with, and one belonging to the knowledge index rather than to the
memory store (`knowledge_max_file_bytes`), which is why it carries that prefix inside a shared section.
Resolved from the two TOML layers per `architecture.md` §"Configuration". Ranges and defaults are unchanged
from when the nineteen lived in `meta`; only their home moved. The dual-homed three are the reason the file can be said to express *intent* while `meta` records
*what was done* — without a file key there would be no way to state the intent at all, and the
hard-mismatch path `architecture.md` documents would be unreachable.

**Key names are deliberately identical to the old `meta` names, including where that reads redundantly inside
a section** — `[dedup] dedup_threshold` rather than `[dedup] threshold`. These keys are referenced by
name across six documents, and renaming them would mean updating dozens of cross-references for cosmetics,
which is exactly the drift class the review kept catching. The TOML is a new *home*, not a new vocabulary.

Sections exist for readability only. Nothing nests deeper, and per `architecture.md` a section in the override
**amends** rather than replaces.

```toml
[embedding]
# Read at STORE CREATION to seed meta, and compared against meta on every later open.
# Editing either on an existing store does not switch embedder silently: it is the HARD
# mismatch of architecture.md "What the file may not change" -> forced reindex.
embed_model = "BAAI/bge-small-en-v1.5"
embed_dim   = 384
# query-side only -- documents receive no prefix under BGE's asymmetric convention,
# so changing this degrades retrieval quality but invalidates no stored vector.
embed_prefix_query = "Represent this sentence for searching relevant passages: "

[indexing]
chunk_max_tokens = 450       # also recorded in meta; see the dual-key note above
gist_max_tokens  = 64
# the knowledge index's per-file cap, seeded into each knowledge base's own meta
knowledge_max_file_bytes = 1048576

[retrieval]
chunk_overfetch        = 8
fusion_depth           = 50
rrf_k                  = 60
supersession_penalty   = 0.5
retired_penalty        = 0.5
supersession_max_depth = 32
fts_query_max_terms    = 64

[dedup]
dedup_threshold = 0.80
dedup_max       = 3

[consolidation]
mutual_k           = 5
orphan_edge_cutoff = 0.65
anchor_cutoff      = 0.65
group_max          = 12
max_group_serves   = 3
run_lease          = 1800
spill_threshold    = 27000

[service]
idle_timeout = 1800

[signals]
signal_horizon_days = 30
```

| Section | Key | Type | Range | Default | Notes |
|---|---|---|---|---|---|
| `embedding` | `embed_model` | string | non-empty | `BAAI/bge-small-en-v1.5` | **dual-homed, hard.** Seeds `meta` at store creation, so it is how a *new* store picks an embedder; on an existing store `meta` is authoritative and a disagreement is invariant 11's forced reindex, never a silent switch |
| `embedding` | `embed_dim` | int | ≥1 | `384` | **dual-homed, hard.** Must equal the `vec0` column width; same creation-and-compare rule as `embed_model`, and a cross-dimension disagreement cannot be reindexed in place because `vec0` fixes its width at creation |
| `embedding` | `embed_prefix_query` | string | — | the BGE literal, **including its trailing space** | quoted verbatim from the model card via `research/embedding-models-technical-prose.md`; it is the exact string the benchmark measured, given as a literal because a paraphrase is a different measured pipeline. Empty string disables it. Query-side only, so it is a preference — but a footgun one: changing it invalidates the applicability of every figure in `retrieval.md` |
| `indexing` | `chunk_max_tokens` | int | 64–8192 | `450` | governs **new** writes; `meta` records what existing chunks were cut at. `indexing.md` preflight |
| `indexing` | `gist_max_tokens` | int | 8–256 | `64` | the one bound that can **reject** an agent's write. Lowering it below an existing gist's length does not revalidate stored rows, but that row's next `amend` will fail until the gist is shortened |
| `indexing` | `knowledge_max_file_bytes` | bytes int | 1–67108864 | `1048576` | the knowledge index's per-file size cap (`knowledge-index.md` §10), seeded into each knowledge base's own `meta` as `max_file_bytes` at creation. Over-cap files are skipped and counted, never truncated. Its **maximum** bounds the peak memory one file costs, since text detection decodes a candidate whole; its `StoreCoupling` is `none` because nothing about it is recorded in `memory.db` — the per-KB seeding is that document's concern, not this one's |
| `retrieval` | `chunk_overfetch` | int | 1–64 | `8` | KNN multiplier, `retrieval.md` |
| `retrieval` | `fusion_depth` | int | 1–500 | `50` | **per-arm** depth before fusion — the most memories one arm can contribute. 50 is the depth every quality figure in `retrieval.md` was measured at. Each arm probes `fusion_depth + 1` and discards the surplus; that row is a termination diagnostic only (invariant 20), never fused. Distinct from the output `limit` |
| `retrieval` | `rrf_k` | int | ≥1 | `60` | inherited from `~/Memory`, unchanged through the benchmark |
| `retrieval` | `supersession_penalty` | float | (0, 1] | `0.5` | multiplier on a superseded row's fused score |
| `retrieval` | `retired_penalty` | float | (0, 1] | `0.5` | multiplier on an outright-retired row's fused score, reachable only under `include_retired` |
| `retrieval` | `supersession_max_depth` | int | 1–1024 | `32` | chain-walk cap; hitting it is an error |
| `retrieval` | `fts_query_max_terms` | int | 1–512 | `64` | cap on quoted terms per lexical query (§Bounds, `retrieval.md` §"Query construction") |
| `dedup` | `dedup_threshold` | float | [0, 1] | `0.80` | floor on `s(new row → candidate)` for D15's advisory near-duplicate list |
| `dedup` | `dedup_max` | int | 0–20 | `3` | how many near-duplicates `remember` hands back |
| `consolidation` | `mutual_k` | int | 2–50 | `5` | orphan-clustering top-K, both directions |
| `consolidation` | `orphan_edge_cutoff` | float | [0, 1] | `0.65` | floor on `min(s(A→B), s(B→A))` for an orphan edge, **and** required alongside mutual-K |
| `consolidation` | `anchor_cutoff` | float | [0, 1] | `0.65` | floor on `s(entry → record)` for anchoring a journal row to a long-term record |
| `consolidation` | `group_max` | int | 2–64 | `12` | shard size for an oversized cohesive group |
| `consolidation` | `max_group_serves` | int | 1–16 | `3` | maximum **deliveries** of one group per run, counting the first; a group that has had this many is `deferred` for the rest of the run (invariant 17) |
| `consolidation` | `run_lease` | seconds int | 60–86400 | `1800` | consolidation run lease |
| `consolidation` | `spill_threshold` | bytes int | 4096–1048576 | `27000` | the serialized size above which a consolidator tool result is written to a file and replaced by a pointer, where the harness can read one. A **proof, not a margin**: a token spans at least one byte, so 27,000 bytes is at most 27,000 tokens, under the ≈29,923 the harness was observed to deliver (`research/claude-code-mcp-result-truncation.md`) |
| `service` | `idle_timeout` | seconds int | 60–86400 | `1800` | service idle self-stop |
| `signals` | `signal_horizon_days` | int | 1–3650 | `30` | after this many days an unresolved joined pair in D30's two cross-event signals counts as **unresolved by definition** — see §"`signal_horizon_days`". A *reporting* parameter; it is not a retention rule and deletes nothing |

**The three cosine cutoffs remain provisional seeds, not measurements** — that was round 3's correction and
moving them to a file does not change it. What is not provisional is that `orphan_edge_cutoff` must exist,
which is combinatorial rather than empirical (`consolidation.md`). Their direction is defined in
`consolidation.md`; only `orphan_edge_cutoff` is symmetrized, being the one undirected relation of the three.

Being file keys now makes `fusion_depth` and `rrf_k` in particular a **config sweep** rather than a schema
write, which is what `FINDINGS.md` open question 2 needs.

## The `event` log, per kind


`detail` is JSON with a **fixed shape per kind**. Untyped detail was the reason three of D30's six
signals were not reproducible. Every event carries `op_id`; one RPC call emits one `op_id`'s worth of
events, **inside the same transaction as the mutation it describes** (invariant 10), so no signal can
observe a write that did not commit. Every event also carries `client_kind` straight from the request envelope,
which is what makes cross-client session linkage checkable rather than assumed (§"Linked sessions" below). It
does **not** carry `label_source`: that is a pure function of `session_id` (`^zk-` ⇒ `minted`, else `harness`),
computed by whoever wants it — `architecture.md` §"`label_source` is derived, not stored".

| `kind` | Cardinality | `memory_uuid` | `detail` |
|---|---|---|---|
| `surface_call` | **exactly one per `surface` call, always — including when nothing was returned** | NULL | `{prompt_chars, limit, fusion_depth, dense_depth_reached, dense_stop_reason, lexical_depth_reached, lexical_stop_reason, query_tokens, query_truncated, lexical_skipped, n_returned, n_demoted}` |
| `surface` | one row per surfaced memory — five rows for a five-gist push, sharing the `surface_call`'s `op_id`; **zero rows when nothing was eligible** | the surfaced uuid | `{rank, fused_score, demoted, demotion:'superseded'\|'retired'\|null}` |
| `search` | one per call | NULL | `{query_chars, limit, fusion_depth, dense_depth_reached, dense_stop_reason, lexical_depth_reached, lexical_stop_reason, query_tokens, query_truncated, lexical_skipped, include_retired, n_returned, uuids:[...]}` |
| `fetch` | one per requested uuid | that uuid | `{version, found}` |
| `remember` | one per call | the new uuid | `{version, token_count, gist_tokens, n_chunks, truncated}` |
| `amend` | one per call | the amended uuid | `{from_version, to_version, token_count, gist_tokens, n_chunks, truncated}` |
| `retire` | one per call | the retired uuid | `{from_version, to_version, superseded_by}` |
| `merge` | **one row per row the call mutated** — one for the target, one per absorbed member, sharing one `op_id` | that uuid | `{group_id, run_id, role:'target'\|'absorbed', from_version, to_version, n_absorbed, token_count, gist_tokens, n_chunks, truncated}` — the size fields are present on the `target` row and null on `absorbed` rows |
| `promote` | **one row per row the call mutated**, and the two forms differ — see the cardinality rule below | that uuid | `{group_id, run_id, role:'created'\|'flipped'\|'absorbed', form:'in_place'\|'new_row', from_version, to_version, n_absorbed, token_count, gist_tokens, n_chunks, truncated}` — size fields on the `created`/`flipped` row only |
| `discard` | **one row per discarded member** | that uuid | `{group_id, run_id, reason, from_version, to_version, n_absorbed}` — `reason` is the verb's argument, stored **here** and nowhere else (D16 leaves the row's own prose untouched) |
| `dedup_offered` | one row per offered near-duplicate, all sharing the `op_id` of the `remember` that triggered them | the *offered* (pre-existing) uuid | `{created_uuid, cosine, rank}` |
| `version_conflict` | **one row per conflicting uuid** in the rejected call | the contested uuid | `{verb, expected_version, actual_version}` |
| `no_receipt` | **one row per uuid lacking a receipt** in the rejected call | the contested uuid | `{verb, version_presented}` |
| `group_served` | **one row per row whose prose this serve actually delivered** — one per member of the **served set** (`architecture.md` §"Serving": the group's members with `disposition IS NULL` after re-validation), one per candidate, and one for the anchor when an anchor was delivered. A serve-time-vacated member emits **none**; a vacated anchor emits none; a member dispositioned by an earlier call is not in the served set and so emits none on a re-serve | that uuid | `{group_id, run_id, role:'member'\|'candidate'\|'anchor', version_served, serve_count}` — `version_served` is **NOT NULL**, because the event exists only for a row that was delivered at that version; `serve_count` is the group's delivery count **including this delivery**, so the first delivery emits `1` (invariant 17) |
| `consolidate_run` | one per run transition | NULL | `{run_id, phase:'planned'\|'complete'\|'expired'\|'abandoned'\|'taken_over', n_groups, n_members, n_deferred}` |

**`promote`'s two forms have two different cardinalities, stated because one physical row can hold two
roles.** In the `new_row` form the created record and the absorbed members are different rows, so the call
emits **one `created` event plus one `absorbed` event per absorbed member**. In the `in_place` form the sole
absorbed member *is* the row that gets flipped, and a singular `role` cannot say both — so that call emits
**exactly one event, `role:'flipped'`, `form:'in_place'`, `n_absorbed: 1`, and no `absorbed` event for that
uuid.** One mutated row, one event. Every query that counts affected rows or per-write sizes therefore counts
an in-place promotion once, and the `created`/`flipped` roles remain the complete set of authored-prose rows.

**`consolidate_run`'s three counts describe the run the transition is about, at the moment of the
transition** — not the run being created, where those differ. `plan_groups` closing a stale run emits that
run's `expired`/`abandoned`/`taken_over` event with *its* totals and then the new run's `planned` event
with the new
ones, so two events of one `op_id` legitimately carry different numbers. `n_groups` and `n_members` are the
run's own `consolidation_group` and `consolidation_group_member` row counts, which are fixed at plan time and
therefore identical on every later phase of that run; `n_deferred` is the count of its groups currently
`status='deferred'`, which is 0 on `planned` and is the only one of the three that can move. Stated because
"the counts" invites a reader to compute them over whichever run the *call* is about, and a `plan_groups`
that closes one run and opens another is about two.

**Each arm reports the depth it reached *and why it stopped*, because the depth alone does not say.**
`retrieval.md` claims both arms report the depth they actually reached; carrying only the *configured*
`fusion_depth` made a short or exhausted arm invisible, which is the opposite of the claim. So
`dense_depth_reached` and `lexical_depth_reached` are the count of **distinct eligible memories the arm
produced** — counted after the eligibility join and the consumer filter, **before the arm's cut**, and capped
at the arm's probe target of `fusion_depth + 1`. The range is therefore `0 … fusion_depth + 1`, and the arm's
actual contribution to fusion is `min(depth_reached, fusion_depth)`.

**Termination is recorded, never inferred — and the record is a measured surplus, not an equality test.** Two
earlier drafts failed here in the same way. The first said `depth_reached < fusion_depth` was *exactly* index
exhaustion and `== fusion_depth` meant the bound cut the arm; neither implication holds, because the dense
overfetch loop also stops after `4` doublings with the index unexhausted
(`retrieval.md` §"The dense arm's overfetch loop, and the three ways it can stop"), which produces a short depth
with eligible memories still outside the probe. The second replaced the inference with an explicit enum but
left the arm's stop test at `≥ fusion_depth`, which put a store holding *exactly* `fusion_depth` eligible
memories into `'depth_reached'` — a value defined as "the bound cut the arm and more may exist", when in fact
nothing was cut and nothing more exists. Round 6 removed the equality case instead of relabelling it: each arm
probes for **one more distinct eligible memory than it keeps**, so a cut is observed rather than assumed.

| Field | Values | Meaning |
|---|---|---|
| `dense_stop_reason` | `'depth_reached'` | the arm produced `fusion_depth + 1` distinct eligible memories; the surplus row **proves** the bound cut at least one memory, so more exists. Holds whether or not the probe covered the index |
| | `'index_exhausted'` | no surplus was found **and** the probe covered the whole chunk index (`n ≥` the chunk count, read in the probe's own transaction) — `depth_reached` is the true eligible total, nothing was cut, and **equality with `fusion_depth` lands here** |
| | `'probe_cap_hit'` | no surplus was found **and** the index was not covered — completeness is **unknown**; eligible memories may remain unprobed. Not an error, and the one value that means "tune something" |
| `lexical_stop_reason` | `'depth_reached'` \| `'index_exhausted'` | same two meanings. The arm is one `LIMIT fusion_depth + 1` statement over an ordered cursor, so returning the limit is a proven cut and returning fewer is a proven end-of-cursor — **equality included**. It has no probe cap, so `'probe_cap_hit'` is unreachable there |

The reasons are evaluated **surplus first, then coverage**, so exactly one applies. Coverage is consulted only
when there is no surplus, which is what keeps `'depth_reached'` from ever meaning "the arm happened to stop at
its budget". `n_returned` and the two depths keep their meanings; the reason is what "the arm exhausted early"
is read off, and `probe_cap_hit` is what a retrieval-parameter sweep watches, since it is the only signal that
`chunk_overfetch` or the cap is too small for the store's real length distribution — the distribution
`FINDINGS.md` open question 3 says we have not measured.

Null has one defined meaning per field, on both the depth and the reason: `lexical_depth_reached` and
`lexical_stop_reason` are **null iff `lexical_skipped`** (zero surviving terms, so the arm never ran), and the
two dense fields are null iff the dense arm never ran — which on the service path is unreachable in v0, so
that null is reserved rather than live. The hook's degraded path emits no events at all on any failure,
because it never reaches the service — there is no request for the service to log, mint a receipt for, or
count (§"Honest limit on the session denominator").

**Which `detail` fields may be null, in one place.** Nullability is stated above in three different forms —
inline in `surface`'s value set, as a clause on the `merge` and `promote` rows, and as the paragraph on the two
arms — and the `retire` case is stated only in §"D30's six signals, as queries". That is how a signal comes to
be written against a field whose null case was specified somewhere its author did not read. The table below
introduces **no new rule**: it is exactly the nulls this document already states, gathered so they can be read
and checked in one place. A field absent from it is one this document says nothing about, which is **not** the
same as one that cannot be null — the answer for such a field is a design question, not an inference.

| `kind` | `detail` fields that may be null | Why |
|---|---|---|
| `surface_call` | `dense_depth_reached`, `dense_stop_reason`, `lexical_depth_reached`, `lexical_stop_reason` | an arm that never ran reports neither a depth nor a reason. The lexical pair is null **iff** `lexical_skipped`; the dense pair is reserved rather than live, being unreachable on the service path in v0 |
| `surface` | `demotion` | the row was not demoted, so there is no demotion to name |
| `search` | `dense_depth_reached`, `dense_stop_reason`, `lexical_depth_reached`, `lexical_stop_reason` | the same two conditions as `surface_call` |
| `retire` | `superseded_by` | an outright retirement names no replacement, and the retire-count signal splits on exactly this null |
| `merge` | `token_count`, `gist_tokens`, `n_chunks`, `truncated` | the size fields describe authored prose, and only the `target` row authored any |
| `promote` | `token_count`, `gist_tokens`, `n_chunks`, `truncated` | as `merge`, except that the authoring row is the `created` or `flipped` one |

`group_served.version_served` is the one detail field this document declares **NOT NULL** outright, and it is
absent from the table above for that reason rather than by omission.

**Serve-time vacating is recorded in state, deliberately not in the event log.** A member found no longer
`tier='journal' AND active=1` inside the serve transaction is not delivered, so it emits no `group_served` —
and that is what lets `version_served` in the event detail be non-null and mean what it says. The vacating is
not thereby lost: it is written to `consolidation_group_member.disposition = 'vacated'` with `disposed_at`,
which is durable, authoritative and queryable, and none of D30's six signals counts it. Two states are
distinguishable there, and the distinction is load-bearing for anyone reading the table:

- `version_served IS NULL AND disposition='vacated'` — **never delivered.** It vacated on the serve that would
  have delivered it.
- `version_served IS NOT NULL AND disposition='vacated'` — **delivered on an earlier serve, vacated on a later
  one.** `version_served` is the version whose prose was delivered on the most recent serve that delivered it,
  and it keeps that value.

So `consolidation_group_member.version_served` is NULL **iff** the member has never been delivered, and there
is exactly one `group_served` event per (serve, delivered row) pair.

### Linked sessions — what makes a cross-client signal computable

> **Harness delta (D34).** The "by construction under kiro" guarantee below holds identically under Claude
> Code, reading `CLAUDE_CODE_SESSION_ID` instead — measured in both hook processes **and the MCP server**
> (`research/claude-code-harness-probe.md` §1) — so the expectation stays ~1.0 and a shortfall keeps its
> one-line diagnosis. **One case is invisible to this instrument and is not to be claimed otherwise:** a
> non-Claude-Code process tree — a kiro session, for instance — launched inside a Claude Code session
> inherits `CLAUDECODE` and a *stale* `CLAUDE_CODE_SESSION_ID`, while the reverse direction is measured
> **safe** (probe §1). Both clients then read the same stale value, they **agree**, coverage reads ~1.0, and that session's events are
> silently attributed to the outer session. Agreement-by-construction is exactly what hides it. The hook's
> payload-versus-environment tripwire in `design/harness.md` is the only evidence available.


Two of D30's six signals join events emitted by **different clients** under one session: a push comes from
`zikaron-hook`, while `remember`/`amend` come from `zikaron-mcp`. That join only works if both clients
resolved the *same* session label. As of 2026-08-01 they do, **by construction under kiro** — both read
`KIRO_SESSION_ID` out of their own environment and it is the same string in every process kiro spawns
(`architecture.md` §"Both clients resolve the same label"). The join is no longer resting on a derivation.

Linkage stays **observable rather than assumed**, because "by construction under kiro" is a conditional and the
condition is exactly what an env-less harness breaks:

- A session is **linked** iff at least one event with `client_kind='hook'` and at least one event with
  `client_kind='mcp'` share its `session_id`.
- **Link coverage** = linked sessions ÷ sessions with any `client_kind='hook'` event. It is reported alongside
  the two cross-client signals, every time.
- **The expectation is now ~1.0, and that changes how a low value reads.** Under the old three-rung ladder a
  shortfall meant *a derivation failed or lost a race* — an expected, tolerated, hard-to-diagnose event. Now a
  shortfall means **`KIRO_SESSION_ID` was absent from some client's environment**, so both clients fell to
  minting and minted *different* labels. That is a one-line diagnosis with a one-line check, and it is the only
  remaining way to be unlinked.
- `label_source` still says which happened — `harness` vs `minted`, derived from the label's prefix rather than
  read from a column — so a `minted`-heavy population is visible immediately. Two rungs, two values; the third
  value (`ancestry`) is gone with the rung.
- The two cross-client signals are computed **over linked sessions only**. An unlinked writing session would
  otherwise be counted as a zero-write hook session — inflating exactly the under-writing rate D30 exists to
  measure, and in the direction that would confirm its prior. That is the worst available failure, which is
  why coverage is reported rather than assumed even now that it should be trivially satisfied.
**Why `surface_call` exists as a separate kind from `surface`.** `surface` is one row per *result*, which is
what gives the "surface then amend" signal a per-memory row to key on at all — the rows for one uuid are located
by `idx_event_uuid_at`, then grouped by `(session_id, memory_uuid)` and ordered by `event.id`
(§"D30's six signals, as queries"). But a push that
returned nothing — empty store, or nothing eligible — then emits no row at all, and a session that never
wrote and never surfaced anything would be invisible to the zero-write-session signal. `surface_call` is the
call, `surface` is the results, and the two share an `op_id`.

**Honest limit on the session denominator.** `surface_call` counts *sessions the service saw*, not sessions
that existed. A session whose every push failed contributes no events at all, because the hook never reaches
the service on a failure and so never emits the `surface_call` the service would have logged
(`architecture.md` §"Degraded modes"). This holds uniformly across every failure kind — transport,
`bad_config`, `reindexing`, contention, identity — since the hook's response to all of them is now identical:
one line to its own `hook.log` plus a model-facing relay on stdout, never a read. So the zero-write rate is
conditional on the service having been reachable **and healthy**. That is a stated limitation, not a fixed one
— making the hook write would mean giving it a writable store handle, which is a worse trade.

**Subagent sessions are absent from both sides, and that is why they create no artifact.** The hook prints
nothing and calls nothing in a subagent session (`architecture.md` §"Subagent sessions"), so a subagent
contributes no `surface_call` and never enters the denominator. An MCP client *inside* a subagent sends the
**top-level** label, so any write it makes lands on the parent session's row — where the work was actually
requested. The denominator and the numerator therefore move together, which is the property rounds 9–11 kept
finding missing elsewhere: the alternative, suppressing the hook while letting subagent writes carry a subagent
label, would have manufactured both a zero-write hook session *and* a write with no session, in the same run.

`dedup_offered` correlates to its `remember` two ways — the shared `op_id`, and `detail.created_uuid`.
Ordering within one `op_id` is `event.id`, which is monotonic under SQLite's single-writer rule; across
concurrent calls only `at` and `id` order events, and `id` is authoritative because `at` can collide.

**Rejected calls emit events too**, which is not a contradiction of the error table's all-or-nothing rule.
See `architecture.md` §"Errors" — a rejected call performs no **domain** mutation, and may still atomically
commit its audit events and, for a version conflict, the receipt for the record it returned. Without that,
`version_conflict` and `no_receipt` would be unobservable and D26's one-round-trip retry would be
impossible.

### D30's six signals, as queries

Each signal is stated as an explicit numerator and denominator so two implementations report the same number.

| Signal | Numerator | Denominator |
|---|---|---|
| **writes per session; zero-write sessions** | per `session_id`: `count(kind='remember')` and `count(kind='amend')`, reported separately **and** summed | `count(DISTINCT session_id)` over **linked** sessions (§"Linked sessions") — every session the service saw *through both clients*, whether or not it wrote. A linked session with a `surface_call` and no `remember`/`amend` is a zero-write session. Reported **with link coverage**; unlinked sessions are excluded rather than counted as zero-write, because an unlinked writing session would otherwise be miscounted as one. Two limits, both stated: "sessions the service saw" is the population, and only linked ones are countable. |
| **dedup offered → resolved?** | `dedup_offered(op_id=O, memory_uuid=X, detail.created_uuid=N)`, then classify: both bounded by `event.id > offer.id` **and** `event.at ≤ offer.at + signal_horizon_days`, let `A` = such an `amend` on `X` exists and `R` = such a `retire` of `N` with `detail.superseded_by = X` exists. **`A ∧ R` closes early as *fully resolved*** — it cannot be improved on, so waiting adds nothing. **Every other offer stays *pending* until `now >` the deadline**, which is what makes a classification permanent: an amend-only offer must not be published as a failure while an in-deadline `retire` could still complete it. At maturity all four combinations are named, so the states are exhaustive and mutually exclusive: `A ∧ ¬R` = **amended-but-duplicate-left-live**; `¬A ∧ R` = **duplicate-discarded-without-amend** (the agent deferred to the existing memory and threw its own new row away without folding the lesson in — a distinct behaviour, not a degenerate case); `¬A ∧ ¬R` = **ignored**. Five reported numbers: those four plus `pending`, with the rate taken over the four matured classes only (§"`signal_horizon_days`"). The unit is the `dedup_offered` **row** on both sides — one offer, one classification | `count(kind='dedup_offered')`. Single-client (all three kinds come from `mcp`), so linkage does not apply. |
| **amend after surface (does D11 fire?)** | `count(DISTINCT (session_id, memory_uuid))` over the **denominator's** pairs that also have an `amend` row on that uuid in that `session_id` whose `event.id` is strictly greater than the pair's **earliest** `surface` row **and** whose `at` is at or before that surface's `at + signal_horizon_days` — `event.id` order is what "followed by" means, the deadline is what makes the classification permanent, and pairs still inside their deadline with no `amend` are **pending** and excluded from the rate rather than counted as unrepaired | `count(DISTINCT (session_id, memory_uuid))` over `kind='surface'` rows **within linked sessions** — one *opportunity* per (session that was shown the memory, memory shown), in a session whose writes are attributable. Cross-client, so it carries the same coverage caveat. |
| **retire count** | `count(kind='retire')`, split by whether `detail.superseded_by` is null; consolidator retirements are **excluded** here and counted under `merge`/`discard`, because "the agent chose to retire" and "consolidation absorbed a row" are different behaviours | `count(kind='remember')` over the same window, so the ratio reads as retire-per-write. Single-client. |
| **write size distribution** | `detail.token_count` over **all** `remember`, `amend`, and the `target`/`created`/`flipped` rows of `merge`/`promote` — the per-write history. An in-place promotion contributes exactly one row (`role:'flipped'`), per the cardinality rule above | n/a (a distribution, not a rate). `memory.token_count` is only the current size of the current row and answers a different question: store composition now. |
| **version-conflict rate** | `count(DISTINCT op_id)` over `kind='version_conflict'`, and separately over `kind='no_receipt'` — **calls, not rows**, because the denominator counts calls; never summed, because a missing receipt means "wrote without reading" while a conflict means "read something stale" | **observable receipt-gated mutation calls** — the five verbs that name a **pre-existing row at a version**: `amend`, `retire`, `merge`, `promote`, `discard`. `count(DISTINCT op_id)` over `kind IN ('amend','retire','merge','promote','discard')` — the calls that committed — **plus** `count(DISTINCT op_id)` over `version_conflict` **plus** the same over `no_receipt`. **`remember` is excluded by construction, not by oversight**: it creates a row, so it presents no version and holds no receipt, and can never appear in either numerator. The three terms are disjoint, so each rate is a true fraction; not every *attempted* mutation is in it, and not every *mutation* is in it. All three points are stated below. Consolidator writes are in scope, which is what D30 requires. |

Two counting rules that the multi-row kinds make necessary, stated once: a **rate over calls** deduplicates
by `op_id`; a **count of affected rows** does not. Every query above says which it uses — and a rate must use
the **same unit on both sides**. Round 10 caught the version-conflict rate mixing them: `version_conflict` and
`no_receipt` commit **one row per offending uuid**, so a bare `count(kind=…)` numerator over a call-level
denominator let a single three-row conflicting `merge` report 3 / 1 and the "rate" exceed 100%. Both sides are
now calls. The row-level count remains available and is a **different quantity** — contested rows, not a rate —
and rows ÷ conflicted calls reads as "how many rows a conflicting call typically contests".

**A rate over pairs deduplicates by the pair, and round 11 caught the amend-after-surface signal with no unit
at all.** Its numerator was a *condition* — `surface(X)` then `amend(X)` in one session — with no aggregation,
against a denominator of distinct memories, so three readings were all defensible: qualifying `amend` calls,
distinct memories, or distinct session-memory opportunities. They disagree, and the first can exceed 100% — one
memory surfaced and amended in two linked sessions gives 2 over a denominator of 1. The unit is now the
**`(session_id, memory_uuid)` pair** on both sides. That is the unit the question is about: D11's opportunity is
*this session was shown this memory and could repair it*, so the same memory surfaced in two sessions is two
chances, a memory surfaced five times in one session is one, and two amends in one session are one — the signal
asks *whether* the loop fires, not how often. "Followed by" is **`event.id` order**, for the reason already
given above: `at` can collide across concurrent calls while `id` is monotonic under SQLite's single-writer rule.
`idx_event_uuid_at` is still the access path for "rows about this uuid"; the comparison is on `id`.

**Honest limit: this is D11's `amend` arm, not all repair.** A surfaced memory the agent repaired by `retire`
instead — legitimate under D11 and D16 — is counted by the retire signal and not here, so the rate is a floor on
repair rather than a measure of it. D30 names the six signals separately for exactly that reason; the pairing is
left to the reader of both.

**Why each rate is a true fraction.** The three denominator terms are mutually exclusive. A call is rejected at
the **first** rung holding any offender, and the version rung precedes the receipt rung in both ladders
(invariant 9, `architecture.md` §"Validation precedence"), so no call emits both kinds; and a rejected call
commits no mutation, so no call is both committed and rejected. A retry is a separate call with its own
`op_id`, which is the intent: each attempt counts once, and a conflict followed by a successful retry
contributes one to the numerator and two to the denominator.

**Honest limit: the denominator is every observable *receipt-gated* mutation call — not every attempted
mutation, and not every mutation.** Two exclusions, for two different reasons. (a) Only `version_conflict` and
`no_receipt` write an event when a call is rejected (`architecture.md` §"What a rejected
call does and does not change"), so mutation calls rejected as `bounds`, `not_found`, `inactive_row`,
`bad_supersession`, `not_in_group`, `bad_merge_target`, `group_unknown`, `group_complete`, `group_deferred`,
`group_expired`, `store_busy`, `index_failed` or `bad_config` are counted **nowhere** and are invisible to this
signal. So it measures concurrency among calls that got far enough to be audited — which is the population
D26's one-round-trip retry contract is actually about — and it does *not* measure malformed or unauthorized
write attempts. A one-per-call attempt event would make those countable and was rejected: it would put a store
write on the cheapest rejection path (`bounds`, decided before any state is read), it could not commit inside
the transaction it describes when there is no mutation, so invariant 10 would need an exception, and it still
could not record `store_busy` — the one rejection where the store is by definition unwritable.

(b) **`remember` is a committed, observable, logically-mutating call (invariant 2) and is deliberately not in
this denominator**, which round 11 caught the prose promising. It is excluded because it is not *receipt-gated*:
it names no pre-existing row, so neither ladder's version rung nor receipt rung applies to it
(`architecture.md` §"Validation precedence"), and it therefore cannot appear in either numerator. Admitting a
term that is structurally incapable of reaching the numerator would not measure contention better — it would
divide contention by **write volume**, which D30's *first* signal measures on purpose. A prompt change that made
agents write more would then appear to reduce contention while concurrency was unchanged: wrong in the direction
of our own prior, the failure the linked-session caveat already exists to prevent. The estimand is *of the calls
that had to present a version and a receipt, how many held a stale one* — the five verbs, named in full wherever
the population is named.

### Retention: `event` is not pruned

**Nothing in `event` is deleted on a schedule.** Measured: a full `surface_call` row costs **454 bytes**
including both indexes, so at ~1,000 events/day — a heavy single project at ~200 user messages — the table
grows about **200 MB/year** live (166 MB `VACUUM`ed, plus 20–30% for WAL and free pages). A normal project is
under 20 MB/year. The store is per-directory (D8, D17), gitignored (D19), and **no hot path reads `event`**,
so a large table costs disk and slows only the signal queries in §"D30's six signals, as queries".

Age-pruning was considered and **rejected on two grounds**, the first of which is not about size at all:

1. **It would manufacture the conclusion D30 already expects.** Two of the six signals join across sessions
   (`dedup_offered → amend`, and `surface → amend` on a `(session_id, memory_uuid)` pair). Age-pruning cuts
   those pairs asymmetrically at the boundary, and the specific worst case is that pruning a session's
   `remember` rows while its `surface_call` survives makes that session read as a **zero-write session** —
   inflating the under-writing rate in exactly the direction `~/Memory`'s evidence predisposes us to believe.
   The artifact would be indistinguishable from the finding.
2. **`event.detail` is the input to the open fusion-tuning question**, not disposable diagnostics. The RRF `k`,
   arm-weighting and `fusion_depth` pass (`FINDINGS.md` open question 2, the largest known quality lever)
   needs historical distributions of `dense_stop_reason`, `lexical_stop_reason`, `probe_cap_hit` and
   `depth_reached`. Nulling `detail` past a horizon would destroy precisely the evidence that pass requires.

Not pruning also removes machinery rather than adding it: no schedule, no background job, no invariant to
police it, and `read_receipt` no longer needs an age-pruning exemption — it was only ever special because
age-pruning was assumed. `read_receipt` remains bounded **logically**, by invariant 9: a version bump deletes
every receipt for that uuid except the writer's own.

**The manual escape hatch, if disk ever does matter.** Documented as **SQL, not a tool and not a CLI** — the
same posture as the erasure procedure, since it is rare, operator-driven and dangerous to automate. It deletes
**whole sessions only**: every `event` row whose `session_id` has no activity at or after the cutoff, plus
sessionless rows older than it. Whole sessions are the unit because that is what makes a manual prune
structurally incapable of producing the zero-write artifact above. It names only `event`, so `read_receipt` is
untouched — required, since invariant 9 bounds it logically. Statements and caveats:
`design/write-policy.md` §"Pruning the event log, if it is ever necessary".

### `signal_horizon_days` — why the horizon is not a retention rule

Two signals ask an open-ended question — *was this `dedup_offered` ever followed by an `amend`?* — which has
no closing condition. Without a horizon the **same historical window reports a different rate depending on
when the query is run**, because a late `amend` retroactively resolves an old offer. That is a defect in the
estimand, not in retention, and it exists whether or not a single row is ever deleted.

`signal_horizon_days` (default **30**, range 1–3650) closes it, and the closing rule has to be a **deadline
measured from the earlier event**, not a test applied at query time. An earlier draft said "an unresolved pair
whose earlier event is older than the horizon counts as unresolved", which does not close anything: a day-31
`amend` stops that pair being *still* unresolved and so retroactively changes its classification — the exact
drift the key exists to prevent.

The rule, stated as the queries must implement it. For a joined pair whose earlier event `E` occurred at
`E.at`, define `deadline = E.at + signal_horizon_days`:

| State of `E` | Condition | Counted as |
|---|---|---|
| **resolved** | a qualifying follow-up exists with `event.id > E.id` **and** `event.at ≤ deadline` | resolved, permanently |
| **matured-unresolved** | `now > deadline` and no such follow-up | unresolved, permanently |
| **pending** | `now ≤ deadline` and no such follow-up | **neither** — excluded from the rate |

Three properties follow, and they are the point:

- **A follow-up after the deadline never changes a classification.** `event.at ≤ deadline` is part of the
  numerator condition, not a filter on when the query runs, so a matured pair's answer is fixed for good.
- **Pending pairs are excluded rather than counted as failures**, because counting them as *ignored* would
  make every rate depend on how recently the store was written to — a fresh offer would look like an ignored
  one. Each query therefore reports its matured classes **plus** `pending`, with the rate taken over the matured
  classes only: three numbers for amend-after-surface (amended, not-amended, pending) and **five** for
  dedup, whose four matured outcomes are enumerated in the query table — `A ∧ R` may close early, and
  every other offer stays pending until maturity precisely so no answer is published twice.
- **Both bounds are needed.** `event.id` order is what "followed by" means (`at` collides); `event.at ≤
  deadline` is what makes the classification final. Neither alone suffices.

For the dedup signal, *fully resolved* requires **both** the `amend` on the offered row and the `retire` of the
created duplicate, so **both** must fall inside the deadline; an `amend` inside it and a `retire` after it is
`amended-but-duplicate-left-live`, permanently. Both queries report the horizon alongside the rate so two runs
are comparable, and a run must state the horizon it used — the same numbers under two horizons are two
different estimands.

One honest imprecision. The two signals have different natural timescales: `surface → amend` is D11's repair
loop and normally fires within one session in minutes, while `dedup_offered → amend` can legitimately span
weeks. A single horizon is therefore set by the longer of the two and is generous for the shorter one, which
biases `surface → amend` toward *undercounting* repairs — the conservative direction. Splitting it into two
keys is a one-line change if the measured distributions ever justify it.

## Retrieval eligibility — one predicate, three row states

D25 says supersession **demotes rather than hides**. That is only true if the default query predicate lets
superseded rows through, so the predicate is defined once, here, and every read path uses it as its **base** —
push, pull, dedup, consolidation anchors, and orphan edges. Three of those five then add a filter on top; the
complete list is §"Consumer filters" below, and a path may not add one that is not in it. There are exactly
three row states:

| State | Rows | Default retrieval | `include_retired=true` |
|---|---|---|---|
| **live** | `active = 1` | eligible, no penalty | eligible |
| **superseded** | `active = 0 AND superseded_by IS NOT NULL` | **eligible, demoted** (D25) | eligible, demoted |
| **retired outright** | `active = 0 AND superseded_by IS NULL` | excluded | eligible, demoted |

An outright-retired row is demoted rather than ranked normally even when it was explicitly asked for,
because `include_retired` widens *what may appear*, not *what is currently true* — the agent asked to see
history, not to have it compete on equal terms with the present. **Both demoted states have a named
penalty**: `supersession_penalty` for superseded rows, `retired_penalty` for outright-retired ones, both
defaulting to 0.5. They are separate **config keys** with equal defaults, and the reason is honesty rather than
symmetry: nothing measured distinguishes the two cases, so they start equal and can diverge once something
does. The two states are mutually exclusive (`superseded_by` is either NULL or not), so the penalties can
never compound.

```sql
-- ELIGIBLE(include_retired):
--   include_retired = 0:  active = 1 OR superseded_by IS NOT NULL
--   include_retired = 1:  (all rows)
```

Two consequences worth stating because the old `active = 1` filter got them both wrong:

- **The push path needs no new argument.** Superseded rows are eligible by default, so they can reach the
  injected five, which is what D25's measurement requires. `include_retired` widens the predicate only to
  rows nobody replaced — the deliberate archaeology case — and stays on `search` alone.
- **"Retired" and "superseded" are not the same exclusion.** Invariant 5 already forbids assuming
  `active=0 ⇒ superseded_by NOT NULL`; this predicate is where that stops being advice.

The demotion itself — the two penalties, and the rule that a replacement always outranks the record it
replaced — is specified in `design/retrieval.md` §"Supersession: eligible, demoted, and labelled", because it
is a ranking rule rather than a storage rule.

### Consumer filters — the base predicate, plus exactly one named filter per read path
An earlier draft claimed the predicate had **one** documented narrowing. That was wrong, and it was wrong in
the dangerous direction: two consumers were being handed rows they could not legally act on. Dedup offered
inactive rows whose stated resolution (`amend`) rejects inactive rows, and orphan adjacency let superseded
journal rows consume top-K ranks even though group members are by definition *unconsolidated* journal rows.

So the contract is: **`ELIGIBLE` is the base for every read path, and each path adds at most one filter,
named here and nowhere else.** A filter that is not in this table does not exist.

| Consumer | Filter on top of `ELIGIBLE` | Why this filter |
|---|---|---|
| push (`surface`) | none | D25: superseded rows must be able to reach the injected five |
| pull (`search`) | none; `include_retired` widens the base | deliberate archaeology is the agent's call |
| `fetch` | not a predicate path at all — lookup by uuid, any state | a uuid is a handle; refusing to resolve it would strand an agent holding a `superseded_by` |
| **dedup candidates (D15)** | **`active = 1`**, and exclude the row just created | the offered resolution is "`amend` the older row", and `amend` rejects `active=0` (`−32003 inactive_row`). Handing back a row the agent is forbidden to amend is an offer it cannot take. A superseded row's replacement is active and will surface in its place if it is genuinely close |
| **consolidation anchor + candidates** | **`tier='long_term' AND active = 1`** | every long-term row shown is a row `merge` may be asked to *rewrite*, and rewriting a historical row is incoherent — `superseded_by` is immutable once set (invariant 6), so a retired row given fresh prose is neither current nor historical |
| **orphan adjacency (D29 step 2)** | **`tier='journal' AND active = 1`**, and exclude the querying row itself | this is exactly the definition of an unconsolidated journal row, i.e. of a group *member*. A superseded journal row cannot become a member, so letting it hold a top-`mutual_k` rank displaces a row that could |

Each filter is restated at its own site — `design/consolidation.md` steps 1 and 2,
`design/architecture.md` `zikaron_remember` — because an undocumented divergence between read paths is
exactly the defect a shared predicate exists to prevent, and because the round-1 review found precisely that
defect. Note what the three filters have in common: each one is the *legality* condition of the action the
rows are being retrieved *for*. Retrieval for reading has no filter; retrieval for mutation is filtered to
what may be mutated.

## Bounds

Enforced at the tool/RPC boundary, so a rejection is an immediate, actionable error rather than silent
truncation. `design/architecture.md` §"Errors" carries the codes.

| Bound | Value | Why |
|---|---|---|
| `gist` | ≤ **64 tokens** (`gist_max_tokens`), non-empty | D13 wants triage-length prose, and `indexing.md`'s preflight must fit gist + separator + content + special tokens under the embedder's 512. Over-budget **rejects**; the agent still holds the text and can shorten it in the same turn. |
| `gist.characters` | ≤ **1024** code units, a fixed constant | Tokens bound neither characters nor bytes — the deployed WordPiece tokenizer maps an unbroken 4,000-character run to a single `[UNK]` — so the token bound above cannot make the injected block's size provable, and without a second bound the block can overrun any harness's injection budget. `harness.md` §"Injection budgets" carries the derivation; the number is chosen so a five-row block is **6,087 units, 61%** of the smallest budget any supported harness states, and at UTF-8's 3-bytes-per-UTF-16-unit ceiling **18,261 bytes, 28%** of the largest byte-denominated one. **The unit is UTF-16 code units, not code points**, matching the injection budget's own conservative count — the two halves of one argument must measure the same thing, or five astral-heavy gists satisfy the bound and overrun the budget it exists to prove. **Fixed, not configurable**: an output cap cannot be proven against a limit an operator can raise. **The trade it makes, stated because it is observable**: measured at 3.89–6.55 characters per token across prose styles, this binds above ~156 tokens of plain English, so it is *not* reachable at the default `gist_max_tokens` of 64 (worst case 363 characters) but *is* the binding constraint in the top of that key's 8–256 range. Admitting prose at the 256-token ceiling would need ≥1584, putting the five-row block at 89% of budget — a loud rejection naming the character count is the better failure than a block that fits by luck. |
| `content` | non-empty, **no upper limit** | D4 stores content untruncated. Length is handled by chunking, never by refusal. |
| `limit` on `search`/`surface` | 1–50, default 5 | The **output** budget: how many memories come back. It does *not* set retrieval depth. |
| `uuids` on `fetch` | 1–50 per call | The **bound** is all-or-nothing — a call naming 0 or >50 uuids is rejected whole and returns nothing. The **contents** are not: a well-formed call answers partially, returning every known record and reporting unknown uuids in `missing`, because a dead handle is something the agent needs told rather than a reason to fail the batch (`architecture.md` §`zikaron_fetch`). All-or-nothing in the error table means *mutating* batches. |
| `absorb` on consolidator verbs | 1 row minimum, ≤ the group's member count | An empty list cannot complete a group, and a verb may never touch a row outside the group it was handed. |
| FTS5 query terms | ≤ `fts_query_max_terms` (**64**) quoted terms, deduplicated, longest-first | Bounds worst-case lexical cost on a pathological prompt or a long memory. A "term" is one maximal run of Unicode alphanumerics, quoted as an FTS5 string literal and handed to FTS5's **own** tokenizer — see `retrieval.md` §"Query construction". The tie-break for "longest-first" is `(−length, first occurrence)`, so the cap is deterministic |
| Internal lexical query | the querying memory's `gist + content`, through the same constructor and the same 64-term cap | An internal query (dedup, anchor, orphan edge) has no user text; its lexical side is the memory itself. The cap keeps the longest tokens, which for technical prose is where the identifiers are — `retrieval.md` §"Two kinds of query" |
| Dense query tokens | ≤ `512 − specials − prefix` under the deployed tokenizer | The query side of `indexing.md`'s preflight. Over-budget queries are head-truncated and the truncation is **recorded**, never silent — `retrieval.md` §"Query construction". |

## Invariants the code must hold

1. **`memory_vec.rowid == memory_chunk.chunk_id`.** The only link between a vector and its memory.
2. **Every logical mutation is exactly one SQLite transaction**, covering: the `memory` row(s), the
   `version` bump, explicit `memory_fts` maintenance, `memory_chunk` + `memory_vec` maintenance, any
   `read_receipt` change, and its `event` rows. This holds for `remember`, `amend`, `retire`, `merge`,
   `promote` (both forms) and `discard` — not just `amend`. A service killed mid-write must leave either
   the old state or the new one, never prose with a stale dense index. **Deletion order inside the
   transaction is vectors first, then chunks**: `memory_vec` is a virtual table with no foreign key, so
   deleting chunks first would orphan vectors if the statement sequence were interrupted.
3. **Reindex is build-and-swap or unavailable.** A full reindex (D20's forced case) either builds into
   shadow tables and swaps in one transaction, or marks the store `reindexing` in `meta` and fails reads
   with a defined error until it completes. A `vec0` dimension change **requires** the second form, since
   `vec0` tables cannot be altered — the table is dropped and recreated, and no read may see the gap.

   **"No read" has no exception to state, because the hook is never a reader.** An earlier draft had the
   degraded hook path read the store directly on any RPC failure, which put a second, unsupervised reader
   outside this invariant's own enforcement — the service could correctly refuse a read with `−32022
   reindexing` while the one path that bypasses the service read straight through the window this invariant
   declares unavailable. The hook no longer reads the store under any circumstance, on any failure, so this
   invariant's "no read may see the gap" is enforced entirely at the one place reads happen: the service
   itself. Full mechanism: `architecture.md` §"Degraded modes".
4. **Retire never deletes** (D16): `active=0` only. FTS5 and `vec0` rows stay, which is what keeps
   superseded rows retrievable under the eligibility predicate above and keeps outright-retired rows
   recoverable.
5. **Retire vs. superseded are distinct.** Retired-with-no-replacement is `active=0, superseded_by IS NULL`.
   Superseded is `active=0, superseded_by = <uuid>`. No query may assume `active=0 ⇒ superseded_by NOT NULL`
   — that exact assumption was a review BLOCKER in `~/Memory`.
6. **The supersession graph is a rooted converging forest, checked on write.** Precisely: **out-degree ≤ 1,
   in-degree unbounded, acyclic.** Each connected component is an in-tree whose root is the one row with
   `superseded_by IS NULL`, and whose other nodes are everything it replaced, transitively. A **chain** is only
   the special case where every in-degree happens to be 1. Convergence is deliberate and common:
   `zikaron_merge` absorbing rows `A` and `B` into `C` writes `A→C` *and* `B→C`, so two rows share one
   replacement. Calling this "a forest of chains" was wrong, and it is what produced the impossible ranking
   rule the corpus review caught — see `retrieval.md` §"Supersession". Table CHECKs cover no-self-edge and
   `superseded_by IS NOT NULL ⇒ active = 0`.

   **A root is live or terminal, and both are legal.** A `active=1` root is the current record. A root that is
   `active=0 AND superseded_by IS NULL` is a **terminal component**: the whole lineage has been declared no
   longer true with nothing replacing it. That state is reachable by an ordinary legal write — `A→B` exists and
   the agent then calls `zikaron_retire(B)` with no replacement — so the schema must define it rather than
   forbid it. Forbidding it was considered and **rejected**: it would force an agent to either leave a
   known-false row active or invent a replacement it does not have, and "this whole lineage is dead" is a
   thing tribal knowledge genuinely needs to be able to say. Invariant 7 defines what retrieval and `fetch`
   do with it.

   **Write-time preconditions, not preserved properties.** The three rules below are checked in the same
   transaction as the edge write. Two of them are permanent (a self-edge and a cycle can never appear later);
   the target-state rule is **a precondition only**, and the distinction is now explicit because conflating
   the two is what round 3 caught:
   - **Target exists and is not, *at the moment the edge is created*, retired-outright.** A replacement may be
     live, or may itself be superseded (that is how `A→B→C` arises); it may not already be
     `active=0 AND superseded_by IS NULL`. The reason is about the claim being made, not about the end state:
     `retire(A, superseded_by=B)` asserts "B replaces A", and if B is already known to be untrue that
     assertion is false at the instant it is made. B becoming untrue *later* is new information rather than a
     false claim, so the same shape is legal when it arises that way. Nothing re-checks this rule afterwards,
     and nothing should.
   - **No cycles**, permanently. Before writing `A→B`, walk `B`'s chain; if it reaches `A`, reject. The walk is
     capped at `supersession_max_depth` (default 32) and a walk that hits the cap is itself an error, so a
     corrupt store cannot hang a query. Acyclicity is preserved by every later write, because edges are
     immutable and each new edge is checked against the graph as it then stands.
   - **One outbound edge, immutable once set.** `superseded_by` is written once, by the `retire`/`merge` that
     creates it. Re-pointing it is not a supported operation; a correction of a correction adds a link to the
     chain instead. This is what makes the acyclicity check sufficient rather than merely hopeful.
   - **Any tier may supersede any tier.** A journal row can supersede a long-term record and vice versa —
     consolidation does exactly this.

   Acceptance tests: `A→B→C` traversal; two concurrent attempts to close a cycle; and **`A→B` followed by an
   outright `retire(B)`**, which must succeed and produce a terminal component rather than an error or a
   corrupted graph.
7. **Supersession semantics: immediate edge for storage, resolved root for display.** `superseded_by` is
   always the *immediate* replacement. Retrieval demotes on the immediate edge and does not chase the graph
   for ranking. `fetch` additionally returns **`superseded_by_latest`** — the component root, reached by
   walking `superseded_by` to a row with `superseded_by IS NULL`, capped as above — **and
   `superseded_by_latest_state`**, that root's own state (`live` | `retired`). The state field is not
   decoration: under the terminal-component case above, the root a chain resolves to may itself be retired
   outright, and an agent told only "replaced by `5d81…`" would fetch a row that is also no longer true. The
   walk is unambiguous because out-degree is ≤ 1, which is the property that makes "latest" well defined even
   though in-degree is not bounded. So an agent handed `A` in an `A→B→C` chain is told about `C` rather than
   being made to fetch twice, and two rows absorbed into one record both resolve to that record.

   **Eligibility deliberately does not consult the root's state**, and the cost is stated rather than hidden:
   a superseded row whose lineage ends in a terminal root is still eligible-and-demoted by default, so a dead
   lineage can still surface. Resolving root state per candidate would mean a graph walk per row in the fused
   pool, against invariant 7's own "does not chase the graph for ranking" rule and against the latency budget
   D22 sets. The chosen trade is: cheap ranking on the immediate edge, full truth on `fetch`.

   Demotion is by state, **not** by graph depth: a twice-superseded row is demoted exactly as much as a
   once-superseded one, because nothing measured says depth predicts harm.
8. **Version is monotonic and bumped on every mutation** (D26), including a `tier` flip and a
   `superseded_by` write, since both are writes another actor could race.
9. **A write requires a read receipt for every row it mutates** (D26, and see D26's corrected rationale in
   `overview.md`). `amend`, `retire`, `merge`, `promote` and `discard` each require a
   `read_receipt(session_id, client_kind, uuid, version)` matching the version they present, for **every**
   affected uuid.
   Receipts are minted by `fetch`, by `next_group` (which delivers full content), by a conflict payload
   (which returns the current full record — this is what keeps D26's "re-decide in one round trip" promise
   true), and by a successful write (`own_write`: the caller authored that exact prose). On a version bump
   of uuid `U`, every receipt for `U` is deleted except the one minted for the writer at the new version —
   which bounds the table and makes a stale receipt unusable rather than merely wrong.
   **Minting is idempotent**: it is an upsert on `(session_id, client_kind, memory_uuid, version)` that refreshes `at` and
   `source`. Required, not cosmetic — a re-served consolidation group delivers the same rows at the same
   versions to the same session, and a plain insert would violate the primary key.
   **The receipt is scoped to `(session, client kind)`, never to a process**, and the `client_kind` half of
   that was added on 2026-08-01 to close a hole the shared label opened. Every client of one kiro session now
   shares one `session_id` — a subagent's MCP client reads the *parent's* `KIRO_SESSION_ID`
   (`architecture.md` §"What the shared label affects") — so on the old `(session_id, …)` key a receipt minted
   by `next_group`'s serve would have satisfied this invariant for the **primary agent** on that row, letting it
   amend a memory it never fetched. Lost-update protection never depended on the receipt (the version must
   still match), but D6's read-before-amend would have decayed from *this agent read it* to *some client of
   this session did*. With `client_kind` in the key it does not: the consolidator mints and spends
   `kind='consolidator'` receipts, `fetch` and `amend` both run as `kind='mcp'`, so each verb still consumes
   only receipts its own class of client earned. **Process-level scoping remains deliberately absent** — two
   MCP clients of one session do share receipts, which is the same latitude the design has always granted a
   session and is why the scope is named here rather than left to be inferred.
   **The version check runs before the receipt check.** That ordering is load-bearing, not incidental: the
   two rules interlock, because a version bump revokes receipts, so checking receipts first would turn every
   ordinary lost-update race into `no_read_receipt` and destroy the one-round-trip retry the same invariant
   promises.
   **For the four consolidator verbs, group authorization runs before *all* of that.** A conflict payload
   returns a full record and mints a receipt, so if version came first a consolidator could name any uuid it
   liked with a deliberately wrong version and be handed that row's prose — turning `merge` into the `fetch`
   D32 withheld on purpose. Authorization against `consolidation_group_member` and
   `consolidation_group_candidate` therefore precedes existence, version and receipt, and its error payloads
   name uuids only, never state or prose. The full precedence ladder for every mutating verb, primary and
   consolidator, is `architecture.md` §"Validation precedence".
10. **Events commit with their mutation** (see §"The `event` log, per kind"). No event outside the
    transaction it describes. A **rejected** call commits no domain mutation but does commit its audit
    events and, for a version conflict, the receipt for the record it returned — enumerated in
    `architecture.md` §"Errors".
11. **`embed_model` / `embed_dim` are checked against `meta` on open.** A mismatch means a full reindex, not
    a best-effort continue — D20 established that same-dimension model swaps corrupt `vec0` silently with no
    schema protection.
12. **Every active memory has at least one chunk.** Enforced by the non-empty `content` CHECK plus
    `indexing.md`'s preflight. A memory with zero vectors would be invisible to the dense arm while looking
    perfectly healthy.
13. **FTS5 is unchunked; `vec0` is chunked.** Easy to break by reflex; D28 explains why the asymmetry is
    correct (BM25 already length-normalizes).
14. **`uuid` is the only handle ever exposed *to the primary agent*.** `rowid`, `chunk_id` and `event.id`
    are internal to every client. `group_id` and `run_id` are exposed to the **consolidator** only, and
    naming `run_id` internal here without that carve-out contradicted `architecture.md`
    §`zikaron_next_group`, whose payload has stated `{group_id, run_id, …}` since the lifecycle was written.
    The carve-out is safe because neither id is a *handle*: `group_id` is the only one any verb accepts, and
    **no verb accepts `run_id` at all** — it is a correlation id, so that a consolidator's own log line, and
    the `merge`/`promote`/`discard`/`group_served`/`consolidate_run` events it caused, can be joined to the
    run that produced them. It reaches no row of `memory` and authorizes nothing.
15. **One *effectively-active* consolidation run per store at a time** — `status='active' AND
    expires_at ≥ now`. A stored `'active'` row past its lease constrains nobody, including its owner
    (invariant 17). Enforced by that predicate rather than by `status` alone; the lifecycle, including
    same-owner lease recovery and crash takeover, is in `architecture.md` §"Consolidation lifecycle".
16. **A group completes only when every member is dispositioned — and a group whose members are all
    dispositioned is never left open.** `consolidation_group.status='complete'` requires zero rows in
    `consolidation_group_member` with `disposition IS NULL` for that group. `'vacated'` counts as
    dispositioned — the row left the journal by another path, so the group has nothing left to decide about it.

    The converse is the half an earlier draft omitted, and omitting it left a group permanently uncloseable.
    Stated as a closure property that holds **at every transaction boundary**:

    > **No committed group is `pending` or `served` with zero undispositioned members.**

    Two producers can reach zero, so completion has two producers rather than one: the **write verb** that
    dispositions the last member, and the **serve transaction**, when serve-time vacating dispositions the last
    one (`architecture.md` §"What serving re-validates"). Before the closure rule, a group all of whose members
    vacated at serve — or whose last surviving member vacated on a re-serve — left zero undispositioned rows
    with no write verb having run: no transition applied, so the group stayed `served`, was re-served empty
    until `serve_count` hit `max_group_serves`, and became `deferred`. That contradicted this invariant's own
    completion condition, burned the re-serve budget on an empty group, and delayed `{done: true}`. Invariant
    17 carries the transitions.

17. **The group and run state machines are closed, and every transition has exactly one named cause.**
    "One producer per transition" was the earlier phrasing and it was too strong: `→ complete` has two causes.
    The contract is that the enumeration below is **exhaustive** and each row names its cause, so no
    implementation invents a transition and no reachable state is left without an exit.

    **Group:**

    | From → to | Cause | Notes |
    |---|---|---|
    | `pending → served` | a `next_group` that delivers it | **sets `serve_count = 1`.** The counter counts *deliveries*, and the first delivery is one — see the counting rule below |
    | `pending → complete` | the **serve transaction**, when serve-time vacating dispositions *every* member | the group is never delivered and never counts as served: re-validation runs *before* the serve is committed, so `serve_count` stays 0 and no `group_served` event is emitted. `next_group` continues to the next group rather than returning an empty one |
    | `served → served` | a re-serve, incrementing `serve_count` | |
    | `served → complete` | (a) the write verb that dispositions the last member, **or** (b) the serve transaction, when re-serve-time vacating dispositions the last remaining member | both in the same transaction as the disposition, per invariant 16. In case (b) `serve_count` is **not** incremented, for the same reason as `pending → complete` |
    | `served → deferred` | a `next_group` whose re-validation left ≥1 undispositioned member **and** which finds `serve_count` already **equal to** `max_group_serves` | the two tests are ordered: completion beats deferral, so a group whose last member just vacated closes `complete` even at the cap rather than being deferred with nothing left to do (`architecture.md` §"Serving") |

    **The counted quantity is fixed here, because two readings were reachable and they differ in observable
    behaviour.** `serve_count` is **the number of times this group's prose was delivered in this run,
    including the first delivery** — not the number of re-serves. So at the default `max_group_serves = 3` a
    group is delivered at most **three** times per run: the first delivery sets 1, two re-serves take it to 3,
    and the next `next_group` that reaches it defers it. The alternative reading — initial delivery leaves 0,
    each re-serve increments, defer at 3 — would allow **four** deliveries from the same configuration, which
    is why the column comment, the `meta` note, the parameter's description in `consolidation.md`, the
    `group_served` payload and this table all had to be made to say one thing. A delivery that does not happen
    does not count: both `→ complete`-by-vacating rows leave the counter alone because nothing was delivered.

    No other transition exists; in particular a group never returns to `pending`, and `deferred` is terminal
    for the run. `deferred` groups leave their members undispositioned, so the next run plans them again and
    D29's never-lose guard is untouched.

    **Run:**

    | From → to | Cause |
    |---|---|
    | — → `active` | `plan_groups` |
    | `active → complete` | whichever transaction first observes that no group of the run is `pending` or `served` — either the write verb that completed the last group, or the `next_group` that finds nothing servable left |
    | `active → expired` | `plan_groups`, closing a pre-existing `active` run whose `expires_at < now` |
    | `active → abandoned` | `plan_groups`, closing a pre-existing `active` run whose lease has **not** passed, called by that run's **own** `(session_id, pid)` owner |
    | `active → taken_over` | `plan_groups`, closing a pre-existing `active` run whose lease has **not** passed, called by a **different** owner |

    `expired`, `abandoned` and `taken_over` are therefore the *same* producer discriminated by two tests, which
    removes an earlier ambiguity: `plan_groups` closes any `active` run, the lease decides whether the status is
    `expired`, and ownership decides which of the other two it is. The third value exists because a takeover is
    a **supported operation** rather than a fault (`architecture.md` §"Consolidation lifecycle": no evidence
    inside the store distinguishes a dead consolidator from a slow one, so a human reinvoking the consolidation
    skill is the evidence), and folding it into `abandoned` would make the two indistinguishable in the
    one case that matters — a user retrying in one kiro session produces the same `session_id` and only a
    different pid.

    **How a model relates to this transition, stated precisely, because the loose version is wrong.** A human
    invoking the skill supplies a fresh consolidator client, and that client — not the model — calls explicit
    `plan_groups` when the model first requests a serve, at most once successfully per process. So a model
    confined to the configured tool surface cannot *request* this transition: `plan_groups` is in neither tool
    set, and `next_group`, which is in one, refuses a foreign unexpired run with `{busy: true}`. It can
    nonetheless *reach* the transition indirectly, since asking for a serve is what causes the client's own
    call. Saying "no model can reach this transition" would therefore be false — what holds is that none can
    ask for it.
    Every transition is written as a guarded update (`... WHERE status='active'`) so it is idempotent under a
    retry.

    **Expiry is a derived condition on the read side and a stored status only at plan time**, and that split
    is load-bearing rather than tidy-minded. An earlier draft had "any call that finds its own lease passed"
    also perform the transition, which contradicted the rule that a **rejected** call writes nothing but its
    audit events (`architecture.md` §"What a rejected call does and does not change") — a `group_expired`
    rejection would have had to mutate `consolidation_run.status`. So: every reader treats
    `status='active' AND expires_at < now` as **effectively expired**; the stored status catches up when some
    session next calls `plan_groups`. The observable consequence is that a store can hold an `active` row whose
    lease has passed. That is not drift: it is a lazily-collected tombstone, every reader already computes the
    same answer from `expires_at`, and the alternative was a write on a rejection path.

    **An effectively-expired run is treated as absent by `next_group`, for every caller including its owner.**
    This is the second half of the derived-expiry rule and leaving it out stranded the owner. Because
    `next_group` replans only when the caller has no active run, an owner whose own lease lapsed would find its
    own run, be served a group from it, and be rejected `group_expired` — forever, since `plan_groups` is a
    service RPC and **not** one of D32's four consolidator tools, so the owner had no reachable way to replan.
    The rule is therefore uniform: `next_group` looks for a run that is `active` **and** unexpired; finding
    none — no run at all, or only a lapsed `active` row, whoever owns it — it calls `plan_groups` implicitly,
    which closes the lapsed row `expired` and creates a fresh run owned by the caller. Only an `active` **and
    unexpired** run belonging to a **different `(session_id, pid)` owner** yields
    `{busy: true, holder_session, holder_pid, expires_at}`. The **pair, never the session alone**: since
    2026-08-01 every client of one kiro session shares a `session_id` and two consolidators of that session
    also share `client_kind='consolidator'`, so a session-only predicate here would silently reintroduce the
    session-only implementation that `architecture.md`'s lifecycle, validation ladder, error table and RPC
    surface all reject. Crash recovery and same-owner
    lease recovery are then one code path, and neither needs an operator. Lifecycle detail:
    `architecture.md` §"Consolidation lifecycle".
18. **`session_id` is never NULL for a live request** — meaning the **normalized** envelope, the one every
    method, `event` write and receipt mint sees. A client may send `session_id: null` in the bootstrap form; the
    service mints `zk-<uuid4>` and normalizes the envelope to it before rung 1 of either validation ladder
    (`architecture.md` §"The request envelope" and §"Validation precedence"). So `read_receipt.session_id` can
    be `NOT NULL` and `fetch` can keep its unconditional promise to mint a receipt. One method carries **no
    envelope at all** and so falls outside this rather than violating it: `health()`, the unlabelled primitive
    (`architecture.md` §"Service RPC surface"); it emits no event and mints no receipt. The bootstrap null
    is a **wire state, never a stored one** — no table and no event can hold it. The `memory.session_id`
    and `event.session_id` columns stay nullable only to leave room for a future import that genuinely has
    no session; nothing in v0 writes NULL there.
19. **Shard identity is persisted, complete, and consistent within a subgroup.** The shards of one cohesive
    subgroup are the rows of a run sharing an `order_key`, and for any such set:

    > every row has the same `shard_count = N`; the multiset of `shard_index` values is exactly
    > `{1, …, N}`; and `N` equals the number of rows in the set.

    `order_key` identifies the subgroup because it is the pre-shard subgroup's `earliest_created_at|min_uuid`
    and cohesive subgroups are disjoint member sets, so two subgroups in one run cannot share a minimum uuid.
    The per-row `CHECK`s catch a malformed row; this invariant is the set-level condition the planner must
    hold, and it is what makes `shard: {index, of}` reconstructible from state alone after a restart. The
    count is asserted rather than *used* as the source of `of` — a `deferred` or `complete` sibling still
    counts, so the two must agree; if they ever disagree the planner is at fault, and the persisted
    `shard_count` is the value served.

    Group status is deliberately **not** part of this: shards are dispositioned independently, so one shard
    may be `complete` while its siblings are `pending`.

20. **Arm termination is self-evidencing: the reason is derivable from the recorded depth.** On every `search`
    and `surface_call` event, for each arm `A ∈ {dense, lexical}`, `A_depth_reached` is NULL iff
    `A_stop_reason` is NULL, and when both are non-NULL:

    > `0 ≤ A_depth_reached ≤ fusion_depth + 1`; and
    > `A_stop_reason = 'depth_reached'` **iff** `A_depth_reached = fusion_depth + 1`; and
    > `A_stop_reason ∈ {'index_exhausted', 'probe_cap_hit'}` **iff** `A_depth_reached ≤ fusion_depth`; and
    > `lexical_stop_reason ≠ 'probe_cap_hit'`.

    This is what the probe target of `fusion_depth + 1` buys (`retrieval.md` §"The dense arm's overfetch loop,
    and the three ways it can stop"): no event can claim a cut it did not make, and an analysis reading the log
    never has to trust the writer's classification against the count printed beside it. The **only** distinction
    the depth cannot settle is `index_exhausted` versus `probe_cap_hit` — both carry `depth_reached ≤
    fusion_depth` and differ on probe coverage, which is not an event field. That is deliberate: coverage is a
    property of a transaction that has ended, so the arm records the conclusion it drew rather than the
    evidence, and the two values exist precisely because that conclusion is not recoverable later. The
    `fusion_depth` the comparison is against is on the same event row, so the check holds across a **config**
    change.

21. *(withdrawn 2026-08-01.)* This was **label provenance is recorded where it is resolved, and every use agrees
    with that record** — a join between `event.label_source` and a `session_client` row. Both sides are gone:
    the measurement that collapsed the label ladder to two rungs made `label_source` a **pure function of
    `session_id`** (`^zk-` ⇒ `minted`, else `harness`), so there is nothing to record and nothing for two copies
    to disagree about. The number is retired rather than reused, so that every `invariant N` reference written
    across the corpus in twelve review rounds keeps pointing at what it pointed at. **v0 holds invariants 1–20.**
    Rationale: `architecture.md` §"`label_source` is derived, not stored".

## File permissions
The store is durable, unencrypted, plain-text knowledge about a project. `.zikaron/` is mode **0700** and
`memory.db`, its `-wal` and `-shm`, and each of `service.log`, `warmup.log` and `hook.log` are mode **0600**,
created with an explicit umask rather than inherited. `design/architecture.md` §"Filesystem security" carries
the full rule, including the socket and the `/tmp` fallback, because those live outside the store directory.

**Erasing a row is not a `DELETE FROM memory`.** `memory_fts` is an external-content FTS5 table, so deleting
the content row leaves its terms searchable; `memory_vec` has no foreign key, so deleting chunks first
orphans vectors; and `consolidation_group_member`/`_candidate` hold `ON DELETE RESTRICT` references that will
refuse the delete outright. There is no agent-facing hard delete by design (D16), but an operator who must
erase a leaked secret needs the exact transaction — it is in `design/write-policy.md` §"Inspection,
deletion", together with the WAL/log residue that survives it.

## Deliberately absent

- `commit_sha`, `file_paths`, `originating_command`, `cwd` — rejected in D27, with reasons.
- A `tokens` column and a custom `tokenchars` tokenizer — rejected in D24 by its own factorial ablation.
- `surface_count` / `last_surface_seq` / `cooldown_seq` / `surface_weight` — `~/Memory`'s
  recurrence-triggered online revision. Not ported: it costs an extra LLM call per firing, which D2
  forbids on the hot path, and its trigger is salience rather than wrongness. The `event` log records
  surfaces, so this stays reconstructible if we ever want it.
- Power-law recency as a ranking multiplier — rejected in the D27 discussion. Age does not predict truth
  for tribal knowledge the way it does for episodic memory. Recency survives only as a journal-local
  tiebreak.
- A **`session_client` table** and an **`event.label_source` column** — both existed from round 7 to
  2026-08-01, and both are deleted rather than deferred. They were the durable record of *which rung of the
  label ladder* produced a session label, needed only because a `/proc`-ancestry rung produced labels
  byte-identical to harness-supplied ones. Measurement removed that rung (`architecture.md` §"Both clients
  resolve the same label"), leaving two rungs the reserved `zk-` namespace already separates, so
  `label_source` became a pure function of `session_id` and a stored copy became a second source of truth.
  Invariant 21 went with them. Nothing is reconstructible-if-wanted here and nothing needs to be: the
  function is total.

## Migration posture
`meta.schema_version` starts at 1, and **v0 supports exactly that one value**. v0 has no migrations to write
yet, and the store is empty, which is precisely why D28's chunked `vec0` shape is being adopted now rather
than later.

What that means operationally, because "no migrations yet" is not the same as "any version opens":

| Found on open | v0 does | Why |
|---|---|---|
| `1` | opens | the only version whose tables and invariants this binary knows |
| `> 1` | refuses, `−32024 schema_incompatible` `{found, supported: 1}` | a newer writer may have changed tables, indexes, invariants or the meaning of an existing key. Opening it and ignoring the unknown keys would be reading an unknown schema as if it were this one |
| `< 1`, non-integer, missing | refuses, `−32023 bad_config` | ordinary required-key range failure |

The first version that needs to open more than one schema gets an explicit **supported range plus a migration
or capability contract**, written then. Until it exists, the version is a hard gate rather than a hint, and
unknown-key tolerance (above) is scoped to supported versions only — it buys nothing across a version bump
and must not be mistaken for doing so.

**"No migrations yet" does not mean "no tables may be added", and §"The knowledge-base registry" carries the
rule that separates the two.** A table no older code path reads or writes leaves every older read and write
exactly as correct as it was, so it is created idempotently at first use and the version does not move —
which is why this section is still accurate with `knowledge_bases` in the file. What would move the version
is a change an old binary would read *wrongly*, and that is the change this section is waiting for.
