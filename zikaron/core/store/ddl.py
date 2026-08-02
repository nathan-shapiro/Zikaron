"""The schema, as data: every `CREATE` statement `schema.md` §Tables specifies.

One statement per table or index, in creation order, so a schema change touches this module and
nothing that executes it. Foreign keys point forward in this list — `memory_chunk` before
`memory`, for instance, would fail — so the order here **is** the order the store must execute
them in, and `applier` functions elsewhere must not parallelize or reorder it.

Every literal here is a transcription of `schema.md`'s own DDL block; a test reads that block at
test time and compares, so drift between the design and this module fails a test rather than
surfacing as a table that silently does not match its own specification.
"""

from typing import Final

#: The three pragmas `schema.md`'s DDL block opens with, applied to every connection this store
#: opens — creation and every later open alike, since a connection that skipped them would not
#: see concurrent readers correctly or retry under contention as the design requires.
PRAGMAS: Final[tuple[str, ...]] = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA foreign_keys = ON",
)

_MEMORY: Final = """
CREATE TABLE memory (
  rowid          INTEGER PRIMARY KEY,
  uuid           TEXT    NOT NULL UNIQUE,
  tier           TEXT    NOT NULL DEFAULT 'journal'
                         CHECK (tier IN ('journal', 'long_term')),
  gist           TEXT    NOT NULL,
  content        TEXT    NOT NULL,
  active         INTEGER NOT NULL DEFAULT 1    CHECK (active IN (0, 1)),
  superseded_by  TEXT             REFERENCES memory(uuid) ON DELETE RESTRICT,
  version        INTEGER NOT NULL DEFAULT 1    CHECK (version >= 1),
  created_at     TEXT    NOT NULL,
  updated_at     TEXT    NOT NULL,
  session_id     TEXT,
  token_count    INTEGER NOT NULL DEFAULT 0,

  CHECK (length(trim(gist))    > 0),
  CHECK (length(trim(content)) > 0),
  CHECK (superseded_by IS NULL OR superseded_by <> uuid),
  CHECK (superseded_by IS NULL OR active = 0)
)
"""

_MEMORY_INDEXES: Final[tuple[str, ...]] = (
    "CREATE INDEX idx_memory_unconsolidated ON memory(tier, active, created_at)",
    "CREATE INDEX idx_memory_eligible ON memory(active, superseded_by)",
    "CREATE INDEX idx_memory_superseded ON memory(superseded_by)",
    "CREATE INDEX idx_memory_session ON memory(session_id)",
)

_MEMORY_FTS: Final = """
CREATE VIRTUAL TABLE memory_fts USING fts5 (
  gist, content,
  content      = 'memory',
  content_rowid= 'rowid',
  tokenize     = 'unicode61'
)
"""

_MEMORY_CHUNK: Final = """
CREATE TABLE memory_chunk (
  chunk_id     INTEGER PRIMARY KEY,
  memory_uuid  TEXT    NOT NULL REFERENCES memory(uuid) ON DELETE CASCADE,
  part_index   INTEGER NOT NULL,
  token_count  INTEGER NOT NULL,
  truncated    INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)),
  embed_model  TEXT    NOT NULL,
  embed_dim    INTEGER NOT NULL,
  UNIQUE (memory_uuid, part_index)
)
"""

_MEMORY_CHUNK_INDEX: Final = "CREATE INDEX idx_chunk_memory ON memory_chunk(memory_uuid)"

_EVENT: Final = """
CREATE TABLE event (
  id          INTEGER PRIMARY KEY,
  at          TEXT NOT NULL,
  session_id  TEXT,
  client_kind TEXT NOT NULL CHECK (client_kind IN ('hook', 'mcp', 'consolidator')),
  op_id       TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN (
                'surface_call', 'surface', 'search', 'fetch', 'remember', 'amend', 'retire',
                'merge', 'promote', 'discard', 'dedup_offered', 'version_conflict',
                'no_receipt', 'group_served', 'consolidate_run'
              )),
  memory_uuid TEXT,
  detail      TEXT
)
"""

_EVENT_INDEXES: Final[tuple[str, ...]] = (
    "CREATE INDEX idx_event_kind_at ON event(kind, at)",
    "CREATE INDEX idx_event_session ON event(session_id)",
    "CREATE INDEX idx_event_session_kind ON event(session_id, client_kind)",
    "CREATE INDEX idx_event_op ON event(op_id)",
    "CREATE INDEX idx_event_uuid_at ON event(memory_uuid, at)",
)

_READ_RECEIPT: Final = """
CREATE TABLE read_receipt (
  session_id   TEXT    NOT NULL,
  client_kind  TEXT    NOT NULL,
  memory_uuid  TEXT    NOT NULL REFERENCES memory(uuid) ON DELETE CASCADE,
  version      INTEGER NOT NULL,
  at           TEXT    NOT NULL,
  source       TEXT    NOT NULL CHECK (source IN ('fetch', 'group', 'conflict', 'own_write')),
  PRIMARY KEY (session_id, client_kind, memory_uuid, version)
) WITHOUT ROWID
"""

_CONSOLIDATION_RUN: Final = """
CREATE TABLE consolidation_run (
  run_id      TEXT PRIMARY KEY,
  session_id  TEXT    NOT NULL,
  pid         INTEGER NOT NULL,
  started_at  TEXT NOT NULL,
  expires_at  TEXT NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('active', 'complete', 'expired', 'abandoned',
                                               'taken_over'))
)
"""

_CONSOLIDATION_GROUP: Final = """
CREATE TABLE consolidation_group (
  group_id    TEXT PRIMARY KEY,
  run_id      TEXT NOT NULL REFERENCES consolidation_run(run_id) ON DELETE CASCADE,
  anchor_uuid TEXT             REFERENCES memory(uuid) ON DELETE RESTRICT,
  order_key   TEXT NOT NULL,
  shard_index INTEGER NOT NULL DEFAULT 1,
  shard_count INTEGER NOT NULL DEFAULT 1,
  status      TEXT NOT NULL CHECK (status IN ('pending', 'served', 'complete', 'deferred')),
  serve_count INTEGER NOT NULL DEFAULT 0,
  served_at   TEXT,
  CHECK (shard_count >= 1),
  CHECK (shard_index BETWEEN 1 AND shard_count),
  CHECK (serve_count >= 0)
)
"""

_CONSOLIDATION_GROUP_INDEX: Final = (
    "CREATE INDEX idx_group_run_order "
    "ON consolidation_group(run_id, status, order_key, shard_index)"
)

_CONSOLIDATION_GROUP_MEMBER: Final = """
CREATE TABLE consolidation_group_member (
  group_id     TEXT    NOT NULL REFERENCES consolidation_group(group_id) ON DELETE CASCADE,
  memory_uuid  TEXT    NOT NULL REFERENCES memory(uuid) ON DELETE RESTRICT,
  version_seen INTEGER NOT NULL,
  version_served INTEGER,
  disposition  TEXT             CHECK (disposition IN
                 ('merged', 'promoted', 'discarded', 'vacated')),
  disposed_at  TEXT,
  PRIMARY KEY (group_id, memory_uuid)
) WITHOUT ROWID
"""

_CONSOLIDATION_GROUP_MEMBER_INDEX: Final = (
    "CREATE INDEX idx_group_member_open ON consolidation_group_member(group_id, disposition)"
)

_CONSOLIDATION_GROUP_CANDIDATE: Final = """
CREATE TABLE consolidation_group_candidate (
  group_id       TEXT    NOT NULL REFERENCES consolidation_group(group_id) ON DELETE CASCADE,
  memory_uuid    TEXT    NOT NULL REFERENCES memory(uuid) ON DELETE RESTRICT,
  role           TEXT    NOT NULL CHECK (role IN ('anchor', 'candidate')),
  version_served INTEGER NOT NULL,
  rank           INTEGER NOT NULL,
  PRIMARY KEY (group_id, memory_uuid)
) WITHOUT ROWID
"""

_META: Final = "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"

#: Every statement that creates something with **no** dependency on the validated `embed_dim`,
#: in the exact order `schema.md`'s DDL block presents them — which is also a valid dependency
#: order, since every `REFERENCES` in this list names a table created earlier in it.
FIXED_STATEMENTS: Final[tuple[str, ...]] = (
    _MEMORY,
    *_MEMORY_INDEXES,
    _MEMORY_FTS,
    _MEMORY_CHUNK,
    _MEMORY_CHUNK_INDEX,
    _EVENT,
    *_EVENT_INDEXES,
    _READ_RECEIPT,
    _CONSOLIDATION_RUN,
    _CONSOLIDATION_GROUP,
    _CONSOLIDATION_GROUP_INDEX,
    _CONSOLIDATION_GROUP_MEMBER,
    _CONSOLIDATION_GROUP_MEMBER_INDEX,
    _CONSOLIDATION_GROUP_CANDIDATE,
    _META,
)


def memory_vec_statement(embed_dim: int) -> str:
    """The one DDL statement `vec0` fixes a width into, at the validated effective `embed_dim`.

    `schema.md` §"Creating the dense index" requires this width to be validated — and the
    embedder that will fill the column checked against it — before this statement ever runs,
    which is why it is a function rather than a member of `FIXED_STATEMENTS`: nothing may call it
    with an unvalidated value.

    Args:
        embed_dim: the effective config's `embed_dim`, already checked to be `>= 1` and to equal
            the width the configured embedder actually reports.
    """
    if embed_dim < 1:
        raise ValueError(f"embed_dim must be >= 1, got {embed_dim}")
    return f"CREATE VIRTUAL TABLE memory_vec USING vec0 (embedding float[{embed_dim}])"
