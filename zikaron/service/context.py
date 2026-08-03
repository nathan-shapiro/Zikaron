"""`ServiceContext`: the one store handle's worth of assembled state, built once at startup.

`architecture.md` §"Read once, at service startup": both config layers are read when the service
starts and never re-read, because `surface_call.detail` records `fusion_depth` and D30's signals
are computed over those event rows, so a config change mid-run would let two events of one run
disagree about the parameters that produced them. This module is where that "once" actually
happens: every `*Settings`/`*Context` value the rest of `core` needs is built here, from the one
`EffectiveConfig` this process resolves, and handed to every RPC handler unchanged for the life of
the process.

**What this module is not.** It holds no socket and dispatches no method — `server.py` and
`dispatch.py` own those. This is purely "what does the service need open and resolved before it
can answer anything", plus the two facts `dispatch.py`'s idle-tracking needs to update on every
request: `last_activity` and `in_flight`.
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.consolidation.context import ConsolidationSettings
from zikaron.core.indexing.encoder import Encoder, FastEmbedEncoder
from zikaron.core.indexing.writes import IndexingContext
from zikaron.core.retrieval.retrieve import RetrievalSettings
from zikaron.core.store.store import Store


@dataclass(slots=True)
class ActivityTracker:
    """The two mutable facts idle self-stop needs: when the store was last touched, and by how
    many requests right now.

    A separate small type rather than two loose attributes on `ServiceContext`, so `lifecycle.py`
    can be handed exactly this and nothing else — it has no business seeing the store or the
    encoder, only whether it may stop.
    """

    last_activity: float
    in_flight: int = 0

    def begin_request(self) -> None:
        """Mark one request as started: increments `in_flight` and refreshes the activity clock."""
        self.in_flight += 1
        self.last_activity = time.monotonic()

    def end_request(self) -> None:
        """Mark one request as finished: decrements `in_flight` and refreshes the activity clock.

        Refreshed on completion as well as on start — `architecture.md`: "`last_activity` is
        refreshed when each request completes" — so a long-running call keeps the deadline from
        the moment it actually finishes, not from the moment it began.
        """
        self.in_flight -= 1
        self.last_activity = time.monotonic()

    def idle_for(self) -> float:
        """Seconds since the store was last touched by a completed or in-flight request."""
        return time.monotonic() - self.last_activity

    def may_stop(self, *, idle_timeout: float) -> bool:
        """Whether idle self-stop may exit right now: idle past the timeout, and nothing in flight.

        Both conditions in one place, so `lifecycle.py`'s poll loop states the *rule* by calling
        this rather than restating the two-part test itself.
        """
        return self.in_flight == 0 and self.idle_for() > idle_timeout


@dataclass(frozen=True, slots=True)
class ServiceContext:
    """Everything the RPC handlers need, assembled once from one store and one effective config.

    Construct directly for a test that needs a `FakeEncoder`'s determinism and speed, or through
    `assemble` for the real process entry point — both build the identical shape, and `encoder` is
    typed as the `Encoder` protocol rather than `FastEmbedEncoder` specifically for exactly that
    reason: every handler in `dispatch.py`/`dispatch_consolidation.py` only ever calls it through
    `ReadCall`/`IndexingContext`, both of which already take the protocol.
    """

    store: Store
    config: EffectiveConfig
    encoder: Encoder
    index: IndexingContext
    retrieval: RetrievalSettings
    consolidation: ConsolidationSettings
    supersession_max_depth: int
    activity: ActivityTracker

    @property
    def store_id(self) -> str:
        """This store's identity, for `health()`'s handshake."""
        return self.store.meta.store_id

    @property
    def store_path(self) -> Path:
        """This store's `memory.db` path, for `health()`'s handshake."""
        return self.store.path

    @classmethod
    async def assemble(cls, store_directory: Path, config: EffectiveConfig) -> Self:
        """Open the store — creating it first if this is the very first time — and build every
        downstream setting from it, in the required order.

        **The service creates the store on its own first startup, rather than requiring some
        separate bootstrap step to have run first.** Nothing else in the distribution creates
        `memory.db` (`Store.create` had no production caller before this): a fresh `.zikaron`
        directory with no store in it is the ordinary state of a project that has never run
        Zikaron, not a misconfiguration, and a design that required an operator or an installer to
        create the store before the service could ever start would mean the system can never reach
        its own working state from an empty directory unassisted. `store_directory / "memory.db"`
        existing is the signal this function uses to decide which of `Store.open`/`Store.create`
        to call — checked directly rather than by attempting `open` and catching its "no such
        store" failure, since that failure's `bad_config` code is shared with several genuinely
        different causes (`Store.open`'s own docstring: a missing required `meta` key, a
        `schema_version` this build does not support) that must not be silently treated as "create
        one," only the specific absence of the database file itself.

        The encoder loads **before** either store call now, rather than after `Store.open` as in
        the open-only path this replaced: `Store.create` needs it (`embedder.dim`/`.model_name`
        checked against the effective config before any table exists — `schema.md` §"Creating the
        dense index"), and `Store.open` never depended on load order in the first place, so loading
        it first costs the open path nothing while it is what makes the create path possible at
        all. Loading is still the expensive step (hundreds of milliseconds cold) and still happens
        exactly once here rather than being re-derived per request.

        Every step after the encoder loads runs inside a `try` that closes whichever of the store
        or the encoder already succeeded on any later failure: `coding-standards.md` §6's binding
        rule ("a `Store` is held with `async with`, or closed in a `finally`") is a rule about
        process exit, not tidiness — `aiosqlite`'s worker thread is non-daemon, so a store this
        function opened or created and then abandoned on a later failure would keep the whole
        interpreter alive after `main.run()` has already logged the failure and is trying to exit.
        `FastEmbedEncoder.load` failing, or the encoder loading but the store call after it
        failing, are not hypotheticals: this function's own `Raises` section already names both.

        Raises:
            ZikaronError: whatever `Store.open`/`Store.create` or `FastEmbedEncoder.load` raise —
                `REINDEXING`, `BAD_CONFIG`, or `SCHEMA_INCOMPATIBLE` for an existing store;
                `BAD_CONFIG` naming `embedding.embed_dim`/`embedding.embed_model` for a first-time
                create whose configured embedder disagrees with itself; or `BAD_CONFIG` naming
                `embedding.embed_model` if the configured model exposes no usable tokenizer. Any
                store this function itself opened or created is closed before either propagates,
                and it is the **original** failure that propagates even if closing the store
                itself also fails — a caller diagnosing why startup failed is owed the
                construction error, not a close error that only exists because construction had
                already failed.
        """
        encoder = FastEmbedEncoder.load(config.get_str("embed_model"))
        store = await cls._open_or_create(store_directory, config, encoder)
        try:
            index = IndexingContext.for_store(store, config, encoder)
            return cls(
                store=store,
                config=config,
                encoder=encoder,
                index=index,
                retrieval=RetrievalSettings.from_config(config),
                consolidation=ConsolidationSettings.from_config(config),
                supersession_max_depth=config.get_int("supersession_max_depth"),
                activity=ActivityTracker(last_activity=time.monotonic()),
            )
        except BaseException:
            try:
                await store.close()
            except BaseException:
                # The construction failure is what a caller needs to diagnose; a close failure
                # on top of it is a second, secondary fact worth recording but not worth letting
                # displace the first. The bare `raise` below re-raises the construction failure
                # specifically — confirmed directly, since Python's "currently handled exception"
                # reverts to the outer one once this inner `except` block finishes without
                # itself re-raising.
                logging.getLogger("zikaron.service").exception(
                    "failed to close the store while handling an earlier startup failure"
                )
            raise

    @staticmethod
    async def _open_or_create(
        store_directory: Path, config: EffectiveConfig, encoder: FastEmbedEncoder
    ) -> Store:
        """`Store.open` if `memory.db` already exists there, else `Store.create` it first.

        The existence check is the database file itself, not `store_directory` — a `.zikaron`
        directory can exist (created by an earlier, unrelated failure, or by nothing more than
        `mkdir -p` in a deploy script) with no `memory.db` inside it, and that is exactly the state
        this function's create branch exists to leave behind correctly rather than to special-case
        away.
        """
        if (store_directory / "memory.db").exists():
            return await Store.open(store_directory, config)
        return await Store.create(store_directory, config, encoder)

    async def close(self) -> None:
        """Close the underlying store connection. Safe to call once."""
        await self.store.close()
