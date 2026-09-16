"""Rebuilding a knowledge base whose vectors were made by a model it no longer uses.

Every other way a corpus goes out of date is repaired one file at a time, because a file's chunks,
postings and vectors move together in a transaction of their own. **An embedding model that changes
cannot be**: `vec0` fixes a column's width at `CREATE` time, so a vector of the new width has
nowhere to go, and recreating the vector table empty while the chunks and postings stayed would
leave a corpus whose three tables disagree for as long as the rebuild took.

So this is the one operation that drops derived state wholesale, and it is deliberately narrow:

- **It runs as one transaction**, statement by statement through an explicit `BEGIN`. A `DROP TABLE`
  issued with no transaction open runs in autocommit and no later rollback restores it, and
  `executescript` commits whatever is open before it starts — either of which would turn a failure
  mid-rebuild into a corpus with no chunks and no way back.
- **It happens before the scan, not after it.** A scan that dropped at the end would have spent
  minutes embedding into a table of the wrong width.
- **It drops whenever the recorded identity disagrees with either the encoder in hand or the width
  the table is declared at**, which is the question `rebuilt_identity` answers.
- **It records the identity that is about to fill the corpus, in the same transaction that empties
  it.** One statement empties the tables, declares the vector column's width, and names the encoder
  whose vectors will go into it — so `meta.embed_model` and `meta.embed_dim` describe what is
  *stored* at every instant, including the minutes a rebuild is running and including the state a
  killed rebuild leaves behind. That is what makes the rows a dead rebuild committed safe to keep:
  they were made by the encoder `meta` now names, so the scan that follows may treat them as
  current, and an interrupted rebuild resumes rather than starting over — where the encoder in hand
  is still that one. A reverted configuration makes the recorded identity a mismatch instead, and
  the next drop redoes the corpus whole, which is equally correct and for the same reason.
- **It also clears the completion instant**, in the same breath. The identity says *what* is in the
  tables; the instant says *whether a completed build's corpus is*, and the drop has just made that
  false. It is what keeps the corpus refusing to serve for the whole rebuild — the identity cannot
  do that job, since after the flip it agrees with the encoder — and it is unconditional, true
  after any drop whatever the rebuild was to.

**Writing the identity here rather than at the far end of the scan is a reversal of an earlier
choice, and the reason the earlier one was made no longer holds.** It was written at completion so
that a knowledge base under repair would not start serving the moment its old vectors were
destroyed. Clearing the completion instant now does that, and does it whatever `meta` says — so the
later moment bought nothing and cost correctness: it left a window in which the rows a killed
rebuild had already committed were labelled with the *previous* model, which a following scan would
then clear as current.

`pending` is untouched. It names what a walk found changed, the next walk replaces it wholesale, and
clearing it here would destroy the staleness signal a crashed rebuild leaves behind.
"""

from collections.abc import Mapping
from dataclasses import replace

import aiosqlite

from zikaron.core.indexing.encoder import Encoder
from zikaron.core.knowledge import database, ddl, files, meta
from zikaron.core.knowledge.meta import KnowledgeMeta
from zikaron.core.store.transactions import in_one_transaction, propagate


def rebuilt_identity(
    corpus: KnowledgeMeta, encoder: Encoder, *, stored_width: int
) -> KnowledgeMeta | None:
    """The identity this corpus has to be rebuilt at, or `None` when nothing is owed.

    Two disagreements ask for the same work, and they are asked about in this order because the
    answers differ when both hold: the table has to be declared at the width the encoder about to
    fill it emits, not at the one a record names.

    **The encoder in hand is not the one the recorded identity names.** Compared against the
    artifact actually loaded rather than against configuration, because what the recorded keys are
    for is saying which model produced the vectors in the table — and the vectors a build is about
    to write come from this encoder whatever a configuration file says. A corpus rebuilt for this
    reason records what filled it; if configuration disagrees with the model it names, the rebuilt
    corpus goes on reporting that it needs rebuilding, which is the truth.

    **The stored table is not the width the recorded identity names**, which nothing in this package
    can produce: the drop declares the table and writes the identity in one transaction, so the two
    move together on every path that moves either. It is here for a corpus whose `meta` and tables
    were separated by something else — a database file restored from a backup of another build, a
    row edited by hand — where without it every later build would write vectors of the recorded
    width into a table declared for another, one rejected insert per file in a process whose output
    nobody reads. The rebuild is back to the **recorded** identity, which is the one the corpus
    still claims.

    **What an interrupted rebuild leaves is not this function's to detect.** The drop already
    recorded the identity that was filling the corpus, so a dead rebuild leaves `meta` describing
    exactly what is stored; what says a build is owed is the completion instant the same drop
    cleared. Where the encoder in hand is still the one `meta` names, nothing here fires and the
    scan may treat the dead run's committed rows as current, because that model made them. Where
    configuration was reverted, the first question above fires on the abandoned identity — which is
    the right answer, since those same rows were made by the model being abandoned.

    Args:
        corpus: the recorded identity, from this knowledge base's own `meta`.
        encoder: the artifact this process loaded.
        stored_width: the width the vector table will actually accept, read from its declaration
            rather than from `meta` — the two disagreeing is the whole of the second case.

    Returns:
        The identity to rebuild at, or `None` if no rebuild is due.
    """
    if encoder.model_name != corpus.embed_model or encoder.dim != corpus.embed_dim:
        return replace(corpus, embed_model=encoder.model_name, embed_dim=encoder.dim)
    if stored_width != corpus.embed_dim:
        return corpus
    return None


def identity_rows(identity: KnowledgeMeta) -> Mapping[str, str]:
    """The `meta` rows that name what is in the vector table, as the drop's transaction writes
    them."""
    return {
        meta.EMBED_MODEL_KEY: identity.embed_model,
        meta.EMBED_DIM_KEY: str(identity.embed_dim),
    }


async def drop_derived(db: aiosqlite.Connection, *, identity: KnowledgeMeta) -> None:
    """Empty this knowledge base of everything a build derived, in one transaction.

    The chunks, their postings and their vectors are dropped and created again — the vector table at
    `identity.embed_dim` — and the `files` rows go with them, because a row claiming a hash and a
    chunk count for content that is no longer stored would clear the very file the rebuild has to
    read again.

    **`identity` is recorded here, so `meta` never describes vectors that are not the ones in the
    table.** The same statement empties the tables, declares the width and names the model, which
    makes the three agree at every instant a reader can observe — during the rebuild, and after one
    that was killed. The consequence that matters is about the *next* scan: the rows a killed
    rebuild committed were made by the encoder `meta` now names, so treating them as current is
    correct, and recovery is a resume rather than a redo. Recorded at the far end of the scan
    instead, those rows would carry the new model under a `meta` still naming the old one, and a
    following scan would clear them as current and complete over them.

    **The completion instant goes too, and it is what keeps the corpus refusing to serve.** That key
    means *a completed build's corpus is what is stored*, and this transaction has just destroyed
    the corpus it vouched for, so leaving it would be leaving a claim this very statement falsified.
    The identity cannot do that job — after the flip it agrees with the encoder, which is the point
    — so this is the whole of what holds the knowledge base out of service until a scan finishes.
    Removing the key is not a repair checkpoint: it adds no state, it records nothing about what is
    owed, and the scan's completing transaction writes it again.

    Args:
        db: the knowledge base's own connection, outside a transaction.
        identity: the model and width about to fill the corpus, recorded as the drop commits.
    """

    async def _work(connection: aiosqlite.Connection) -> None:
        for statement in ddl.rebuild_derived_statements(identity.embed_dim):
            await connection.execute(statement)
        await files.forget_all(connection)
        await database.write_meta(connection, identity_rows(identity))
        await database.clear_meta(connection, (meta.LAST_SCAN_COMPLETED_AT_KEY,))

    await in_one_transaction(db, _work, failure=propagate)
