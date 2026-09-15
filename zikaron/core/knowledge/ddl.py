"""One knowledge base's schema, as data: every statement `knowledge-index.md` specifies for one.

One statement per table or index, in creation order. Order is load-bearing even though this
schema declares no foreign key at all: `chunks_fts` is external-content against `chunks`, and the
index follows the table it indexes.

Every literal here is a transcription of that document's own DDL block; a test reads the block at
test time and compares, so drift between the design and this module fails a test rather than
surfacing as a table that silently does not match its own specification.
"""

from typing import Final

#: The pragmas every connection to a knowledge base is opened with — two of the memory store's
#: three. WAL is required rather than incidental: a search has to serve committed state *while*
#: the indexer writes, and under the default rollback journal a reader contends with the writer
#: instead. `busy_timeout` is what makes that reader wait rather than fail. `foreign_keys` is
#: deliberately absent, because this schema declares no foreign key at all — switching it on would
#: promise a cascade that does not exist here, and an implementer trusting it would ship orphaned
#: vectors and a corrupt full-text index.
#:
#: **This tuple is passed to the opener rather than being one it knows about**, and a test reads
#: the setting back off a live connection — not merely comparing this tuple to the design, which a
#: separate test also does. Both are needed, and knowing why is the point: a correct tuple applied
#: to nothing is what the first version of this module shipped, and the document-comparison test
#: passed the whole time, because comparing two texts cannot see whether either reaches the running
#: system.
PRAGMAS: Final[tuple[str, ...]] = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA busy_timeout = 5000",
)

_FILES: Final = """
CREATE TABLE files (
  path            TEXT    PRIMARY KEY,
  size            INTEGER NOT NULL,
  content_hash    TEXT    NOT NULL,
  git_blob_hash   TEXT,
  chunk_count     INTEGER NOT NULL,
  indexed_at      TEXT    NOT NULL,

  CHECK (length(path) > 0),
  CHECK (size >= 0),
  CHECK (chunk_count >= 0)
)
"""

_PENDING: Final = """
CREATE TABLE pending (
  path       TEXT PRIMARY KEY,
  noticed_at TEXT NOT NULL,

  CHECK (length(path) > 0)
)
"""

_CHUNKS: Final = """
CREATE TABLE chunks (
  id          INTEGER PRIMARY KEY,
  path        TEXT    NOT NULL,
  part_index  INTEGER NOT NULL,
  start_line  INTEGER NOT NULL,
  end_line    INTEGER NOT NULL,
  text        TEXT    NOT NULL,
  UNIQUE (path, part_index),

  CHECK (part_index >= 0),
  CHECK (start_line >= 1),
  CHECK (start_line <= end_line)
)
"""

_CHUNKS_INDEX: Final = "CREATE INDEX chunks_path ON chunks(path)"

_CHUNKS_FTS: Final = """
CREATE VIRTUAL TABLE chunks_fts USING fts5 (
  text, path,
  content      = 'chunks',
  content_rowid= 'id',
  tokenize     = 'unicode61'
)
"""

_META: Final = "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"

#: Every statement that creates something with **no** dependency on the configured `embed_dim`,
#: in the design's own order.
FIXED_STATEMENTS: Final[tuple[str, ...]] = (
    _FILES,
    _PENDING,
    _CHUNKS,
    _CHUNKS_INDEX,
    _CHUNKS_FTS,
    _META,
)


def chunks_vec_statement(embed_dim: int) -> str:
    """The one DDL statement `vec0` fixes a width into, at the configured `embed_dim`.

    A function rather than a member of `FIXED_STATEMENTS` for the same reason the memory store's
    equivalent is: `vec0` fixes a column's width forever at `CREATE` time, so nothing may call
    this with a width that has not been checked.

    Unlike the memory store, the width here is checked against **configuration alone** and never
    against a loaded model — which is what lets a knowledge base be created with no `fastembed`
    import and no model load on the caller's critical path. The consequence is stated rather than
    hidden: a configured `embed_dim` that disagrees with what the configured model actually emits
    produces a knowledge base whose first embedding write fails, where the memory store would have
    refused at creation. The encoder-mismatch repair is what recovers it.

    Args:
        embed_dim: the effective config's `embed_dim`, already checked to be `>= 1`.
    """
    if embed_dim < 1:
        raise ValueError(f"embed_dim must be >= 1, got {embed_dim}")
    return (
        "CREATE VIRTUAL TABLE chunks_vec USING vec0 (\n"
        "  chunk_id  INTEGER PRIMARY KEY,\n"
        f"  embedding float[{embed_dim}]\n"
        ")"
    )
