"""One knowledge base's schema, as data: every statement `knowledge-index.md` specifies for one.

One statement per table or index, in creation order. Order is load-bearing even though this
schema declares no foreign key at all: `chunks_fts` is external-content against `chunks`, and the
index follows the table it indexes.

Every literal here is a transcription of that document's own DDL block; a test reads the block at
test time and compares, so drift between the design and this module fails a test rather than
surfacing as a table that silently does not match its own specification.
"""

import re
from typing import Final

#: How long a connection to a knowledge base waits for the writer lock before giving up. Named
#: rather than written into the pragma below alone, because one caller has to *lower* it for a
#: single statement and then put it back — and restoring a hand-written duplicate of this number is
#: how a connection comes to keep a timeout nobody chose.
BUSY_TIMEOUT_MS: Final = 5000

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
    f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}",
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

#: Everything a build *derives* from the files it read, as opposed to `files`, `pending` and
#: `meta`, which say what the corpus is and how far a build got. Named as a group because they are
#: dropped and created again as a group when a knowledge base has to be rebuilt at a new embedding
#: width, and one definition used by both paths is what keeps a rebuilt table identical to a
#: created one.
DERIVED_STATEMENTS: Final[tuple[str, ...]] = (_CHUNKS, _CHUNKS_INDEX, _CHUNKS_FTS)

#: Every statement that creates something with **no** dependency on the configured `embed_dim`,
#: in the design's own order.
FIXED_STATEMENTS: Final[tuple[str, ...]] = (
    _FILES,
    _PENDING,
    *DERIVED_STATEMENTS,
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


#: The width out of a `chunks_vec` declaration. It sits beside the statement that writes one so the
#: two cannot drift.
#:
#: **As tolerant as `vec0` itself, which is wider than what this module writes.** Measured: the
#: extension accepts `FLOAT[16]` and `float [16]` as readily as `float[16]`, and `sqlite_master`
#: stores whichever spelling was used, verbatim. A pattern matching only our own spelling would
#: therefore report a perfectly working table as unreadable — and what this is for is knowing what
#: the table will *accept*, which is the extension's question rather than this module's.
_DECLARED_WIDTH = re.compile(r"float\s*\[\s*(\d+)\s*\]", re.IGNORECASE)


def declared_vector_width(statement: str) -> int:
    """The width a stored `chunks_vec` declaration fixes, read back out of that declaration.

    **The only place this width can be read from, and it has to be readable.** `vec0` fixes the
    column at `CREATE` time and reports nothing about it afterwards — measured: `PRAGMA table_info`
    gives the column an empty type — so the declaration in `sqlite_master` is the sole record of
    what the table will actually accept. Without it, a corpus whose table was recreated at one width
    while its `meta` names another looks perfectly healthy until the first insert of a vector is
    rejected, one file at a time, in a process whose output nobody reads.

    Raises:
        ValueError: the declaration names no width. The statement is one this module wrote, so this
            means a database that is not the one it claims to be — which is why it is fatal here
            rather than absorbed into a default.
    """
    found = _DECLARED_WIDTH.search(statement)
    if found is None:
        raise ValueError(f"no vector width in the recorded declaration: {statement!r}")
    return int(found.group(1))


def rebuild_derived_statements(embed_dim: int) -> tuple[str, ...]:
    """Drop everything a build derived from this corpus's files, and create it again empty.

    The one operation that has to exist because `vec0` fixes a column's width at `CREATE` time: a
    vector of a new width cannot be inserted into a table declared for the old one, so an embedding
    model that changes under an existing index leaves nothing to migrate and the derived tables are
    made again at the new width.

    The creates are the same statements a fresh knowledge base is built from, so a rebuilt table
    cannot drift from a created one — which matters here more than usual, since the two would
    otherwise be compared only by a reader who happened to look at both.

    Dropping runs in the reverse of creation order, and the full-text table goes first for a
    reason: it is external-content over `chunks`, so it is the one that has an opinion about
    another table existing. Dropping `chunks` takes its index with it, which is why no statement
    names that index.

    Args:
        embed_dim: the width the recreated vector table is declared at — the one the encoder that
            is about to fill it actually emits.
    """
    return (
        "DROP TABLE chunks_fts",
        "DROP TABLE chunks_vec",
        "DROP TABLE chunks",
        *DERIVED_STATEMENTS,
        chunks_vec_statement(embed_dim),
    )
