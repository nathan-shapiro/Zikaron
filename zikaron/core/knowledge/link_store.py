"""The link each indexed file declares, as `files` records it and as its stored chunks say it.

`knowledge-index.md` §7.7 ("What is read is persisted") and §7.7.1 are normative. A row's four link
columns record what one version of the file declared, beside the `content_hash` of that version, and
are trusted only while the two hashes agree. Where they do not, the link is read again from the
row's stored chunks, whose concatenation in `part_index` order is the file's decoded text exactly —
so the build, the migration and a search all read one text with one reader.

A corpus at schema 1 has none of these columns, so what names one runs only where the corpus's
`KnowledgeMeta.stores_links` says it may; `declared_by` is told which it holds, and at schema 1
reads every link from the stored chunks.
"""

from collections.abc import Iterable, Mapping, Sequence

import aiosqlite

from zikaron.core.knowledge import links

_FIRST_CHUNK_OF_EVERY_ROW = (
    "SELECT f.path, f.content_hash, c.text FROM files AS f "
    "LEFT JOIN chunks AS c ON c.path = f.path AND c.part_index = 0"
)


async def stored_prefix(db: aiosqlite.Connection, path: str) -> str:
    """As much of `path`'s stored text, joined in `part_index` order, as `links.read_link` reads.

    One character past `LINK_PREFIX_CHARS` is enough: the reader looks no further, and the extra
    character is what tells it the text goes on.
    """
    collected: list[str] = []
    size = 0
    async with db.execute(
        "SELECT text FROM chunks WHERE path = ? ORDER BY part_index", (path,)
    ) as cursor:
        async for (text,) in cursor:
            collected.append(str(text))
            size += len(collected[-1])
            if size > links.LINK_PREFIX_CHARS:
                break
    return "".join(collected)


async def _declared(
    db: aiosqlite.Connection, path: str, first_chunk: object
) -> links.DeclaredLink | None:
    """What `path` declares, given its first stored chunk — reading further chunks only for a text
    that opens a block and is not already long enough to decide."""
    text = "" if first_chunk is None else str(first_chunk)
    if text.startswith("---") and len(text) <= links.LINK_PREFIX_CHARS:
        text = await stored_prefix(db, path)
    return links.read_link(text)


async def _records(
    db: aiosqlite.Connection, rows: Iterable[Sequence[object]]
) -> list[tuple[str, links.LinkRecord]]:
    found: list[tuple[str, links.LinkRecord]] = []
    for path, content_hash, first_chunk in rows:
        declared = await _declared(db, str(path), first_chunk)
        found.append((str(path), links.LinkRecord(read_from=str(content_hash), declared=declared)))
    return found


async def records_of_every_row(db: aiosqlite.Connection) -> list[tuple[str, links.LinkRecord]]:
    """What every `files` row's stored chunks declare, each beside the row's own `content_hash`.

    One statement reads every file's first chunk, which settles the common case — a file that
    does not open with a `---` line declares nothing.
    """
    return await _records(db, await db.execute_fetchall(_FIRST_CHUNK_OF_EVERY_ROW))


async def write_records(
    db: aiosqlite.Connection, records: Iterable[tuple[str, links.LinkRecord]]
) -> None:
    """Set the link columns of each named row. Inside the caller's transaction."""
    await db.executemany(
        "UPDATE files SET link_read_from = ?, link_declared = ?, source_path = ?, source_blob = ? "
        "WHERE path = ?",
        [(*record.columns(), path) for path, record in records],
    )


async def paths_with_inexact_records(db: aiosqlite.Connection) -> list[str]:
    """Every row whose link record was read from bytes other than the ones it now records, or was
    never read — what a build of the previous schema left behind it."""
    rows = await db.execute_fetchall(
        "SELECT path FROM files WHERE link_read_from IS NULL "
        "OR link_read_from != content_hash ORDER BY path"
    )
    return [str(path) for (path,) in rows]


async def make_exact(db: aiosqlite.Connection, path: str) -> None:
    """Read `path`'s link again from its stored chunks and record it against its `content_hash`.

    Inside the caller's transaction, which also holds the read, so the record is of the bytes the
    row names when it commits.
    """
    rows = await db.execute_fetchall(
        "SELECT f.path, f.content_hash, c.text FROM files AS f "
        "LEFT JOIN chunks AS c ON c.path = f.path AND c.part_index = 0 WHERE f.path = ?",
        (path,),
    )
    await write_records(db, await _records(db, rows))


async def declared_by(
    db: aiosqlite.Connection, paths: Sequence[str], *, stores_links: bool
) -> Mapping[str, links.DeclaredLink | None]:
    """What each of `paths`' indexed bytes declare — from the row's record where it was read from
    those bytes, and from the stored chunks otherwise (invariant 17)."""
    if not paths:
        return {}
    recorded: dict[str, links.DeclaredLink | None] = {}
    if stores_links:
        placeholders = ", ".join("?" for _ in paths)
        rows = await db.execute_fetchall(
            "SELECT path, content_hash, link_read_from, link_declared, source_path, source_blob "  # noqa: S608 — placeholders only; every path is a bound parameter.
            f"FROM files WHERE path IN ({placeholders})",
            tuple(paths),
        )
        for path, content_hash, read_from, declared, source_path, source_blob in rows:
            if read_from is not None and read_from == content_hash:
                recorded[str(path)] = links.declared_from_columns(
                    declared, source_path, source_blob
                )
    for path in paths:
        if path not in recorded:
            recorded[path] = links.read_link(await stored_prefix(db, path))
    return recorded


async def count_linked(db: aiosqlite.Connection) -> int:
    """How many files the corpus holds whose recorded bytes declare a link."""
    rows = await db.execute_fetchall("SELECT count(*) FROM files WHERE link_declared = 1")
    ((found,),) = list(rows)
    return int(found)
