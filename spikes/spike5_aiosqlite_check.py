"""
Verify aiosqlite works for every mechanism M0's spikes exercised, before
mandating it in the design. aiosqlite describes itself as "an asyncio
bridge to the standard sqlite3 module" — this checks that claim against
the three things Zikaron actually needs from a connection: loading the
sqlite-vec C extension, running vec0 KNN queries, and the FTS5
external-content amend/erasure sequence — all inside a real asyncio
event loop, plus a two-writer busy_timeout contention check analogous to
spike 3d/3e.
"""

import asyncio
import struct
import time

import aiosqlite
import sqlite_vec


def serialize(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


async def check_extension_loading_and_vec0() -> None:
    print("=== aiosqlite + sqlite-vec: extension loading, float[N] template, KNN ===")
    async with aiosqlite.connect(":memory:") as db:
        # aiosqlite.Connection wraps a real sqlite3.Connection that lives on
        # aiosqlite's OWN dedicated worker thread — stdlib sqlite3 connections
        # are hard-bound to their creating thread, so reaching into `db._conn`
        # from the calling coroutine's thread is illegal (confirmed: it raised
        # "SQLite objects created in a thread can only be used in that same
        # thread" on first attempt). aiosqlite exposes `load_extension` as
        # its own async method precisely so extension loading is dispatched
        # to the correct thread — sqlite_vec.load(conn) is just
        # `conn.load_extension(sqlite_vec.loadable_path())`, so the
        # equivalent through aiosqlite's sanctioned API is this:
        await db.enable_load_extension(True)
        try:
            await db.load_extension(sqlite_vec.loadable_path())
            print("await db.load_extension(sqlite_vec.loadable_path()): OK")
        except Exception as e:
            print(f"await db.load_extension(...) RAISED: {type(e).__name__}: {e}")
            raise
        await db.enable_load_extension(False)

        cursor = await db.execute("SELECT vec_version()")
        row = await cursor.fetchone()
        print(f"vec_version() via aiosqlite: {row}")

        await db.execute("CREATE VIRTUAL TABLE memory_vec USING vec0 (embedding float[8])")
        await db.execute(
            "CREATE TABLE memory_chunk (chunk_id INTEGER PRIMARY KEY, memory_uuid TEXT)"
        )
        rows = [
            (1, "uuid-a", [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]),
            (2, "uuid-b", [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        ]
        for chunk_id, uuid, vec in rows:
            await db.execute(
                "INSERT INTO memory_chunk (chunk_id, memory_uuid) VALUES (?, ?)", (chunk_id, uuid)
            )
            await db.execute(
                "INSERT INTO memory_vec (rowid, embedding) VALUES (?, ?)", (chunk_id, serialize(vec))
            )
        await db.commit()

        query_vec = [0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85]
        cursor = await db.execute(
            """
            SELECT mv.rowid, mc.memory_uuid, mv.distance
            FROM memory_vec mv JOIN memory_chunk mc ON mc.chunk_id = mv.rowid
            WHERE mv.embedding MATCH ? AND k = 2
            ORDER BY mv.distance
            """,
            (serialize(query_vec),),
        )
        knn_rows = await cursor.fetchall()
        print(f"KNN via aiosqlite: {knn_rows}")

        # Dimension mismatch — same check as spike 1, through aiosqlite
        try:
            await db.execute(
                "INSERT INTO memory_vec (rowid, embedding) VALUES (?, ?)",
                (99, serialize([0.1, 0.2, 0.3])),
            )
            await db.commit()
            print("UNEXPECTED: mismatched-dimension insert succeeded")
        except Exception as e:
            print(f"Dimension mismatch via aiosqlite RAISED: {type(e).__name__}: {e}")


async def check_fts5_amend_and_erasure() -> None:
    print("\n=== aiosqlite + FTS5 external-content: amend and erasure ===")
    async with aiosqlite.connect(":memory:") as db:
        await db.execute(
            "CREATE TABLE memory (rowid INTEGER PRIMARY KEY, uuid TEXT, gist TEXT, content TEXT)"
        )
        await db.execute(
            "CREATE VIRTUAL TABLE memory_fts USING fts5(gist, content, content='memory', content_rowid='rowid')"
        )
        await db.execute(
            "INSERT INTO memory (rowid, uuid, gist, content) VALUES (1, 'u1', 'g', 'the protobuf step fails on staging')"
        )
        await db.execute("INSERT INTO memory_fts (rowid, gist, content) VALUES (1, 'g', 'the protobuf step fails on staging')")
        await db.commit()

        async def search(term: str) -> list:
            quoted = '"' + term.replace('"', '""') + '"'
            cursor = await db.execute(
                "SELECT rowid, gist FROM memory_fts WHERE memory_fts MATCH ? ORDER BY rank", (quoted,)
            )
            return await cursor.fetchall()

        print(f"before amend, 'staging': {await search('staging')}")

        # amend sequence: delete FTS row, update content, insert new FTS row — one transaction
        await db.execute("DELETE FROM memory_fts WHERE rowid = 1")
        await db.execute(
            "UPDATE memory SET content = 'the protobuf step fails on prod-eu' WHERE rowid = 1"
        )
        await db.execute(
            "INSERT INTO memory_fts (rowid, gist, content) VALUES (1, 'g', 'the protobuf step fails on prod-eu')"
        )
        await db.commit()

        print(f"after amend, stale 'staging': {await search('staging')}")
        print(f"after amend, new 'prod-eu': {await search('prod-eu')}")

        # documented erasure sequence via aiosqlite
        cursor = await db.execute("SELECT gist, content FROM memory WHERE rowid = 1")
        cur_gist, cur_content = await cursor.fetchone()
        await db.execute(
            "INSERT INTO memory_fts (memory_fts, rowid, gist, content) VALUES ('delete', ?, ?, ?)",
            (1, cur_gist, cur_content),
        )
        await db.execute("DELETE FROM memory WHERE rowid = 1")
        await db.commit()
        print(f"after erasure, 'prod-eu': {await search('prod-eu')}")

        await db.execute("INSERT INTO memory_fts(memory_fts) VALUES('integrity-check')")
        print("integrity-check via aiosqlite: OK")


async def check_busy_timeout_two_writers() -> None:
    print("\n=== aiosqlite + busy_timeout: two concurrent writers ===")
    import os

    db_path = "/tmp/zikaron_aiosqlite_check.db"
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(db_path + suffix)
        except FileNotFoundError:
            pass

    async def setup() -> None:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("PRAGMA journal_mode = WAL")
            await db.execute("CREATE TABLE counter (id INTEGER PRIMARY KEY, n INTEGER)")
            await db.execute("INSERT INTO counter (id, n) VALUES (1, 0)")
            await db.commit()

    await setup()

    async def writer(label: str, hold_s: float) -> dict:
        async with aiosqlite.connect(db_path, timeout=5.0) as db:
            await db.execute("PRAGMA busy_timeout = 5000")
            t0 = time.monotonic()
            try:
                await db.execute("BEGIN IMMEDIATE")
                await asyncio.sleep(hold_s)  # aiosqlite's own connection is thread-backed,
                # so this yields the CALLER's event loop, not the worker thread the
                # connection's blocking calls run on — this is exactly the distinction
                # spike 3's self-inflicted deadlock was about, now checked against the
                # library rather than against hand-rolled asyncio.to_thread calls.
                await db.execute("UPDATE counter SET n = n + 1 WHERE id = 1")
                await db.commit()
                waited = time.monotonic() - t0
                cursor = await db.execute("SELECT n FROM counter WHERE id = 1")
                (n,) = await cursor.fetchone()
                return {"label": label, "ok": True, "n": n, "waited_s": round(waited, 4)}
            except Exception as e:
                return {"label": label, "ok": False, "error": str(e), "waited_s": round(time.monotonic() - t0, 4)}

    results = await asyncio.gather(writer("A", 0.5), writer("B", 0.5))
    for r in results:
        print(r)
    ns = [r["n"] for r in results if r["ok"]]
    print(f"Counter values: {ns} — incremented exactly twice, no lost update: {sorted(ns) == [1, 2]}")

    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(db_path + suffix)
        except FileNotFoundError:
            pass


async def main() -> None:
    print(f"aiosqlite version: {aiosqlite.__version__}\n")
    await check_extension_loading_and_vec0()
    await check_fts5_amend_and_erasure()
    await check_busy_timeout_two_writers()


if __name__ == "__main__":
    asyncio.run(main())
