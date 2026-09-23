"""The one artifact the write path needs: a tokenizer to count with and a model to embed with.

Both come from the *same* deployed artifact, which is `indexing.md`'s own requirement rather than
a convenience: "Counting uses the same `bge-small-en-v1.5` WordPiece tokenizer fastembed will use
at embed time, obtained from the same artifact." Anything else — a regex, a word count, another
model's vocabulary — makes the 512-token guarantee approximate, and an approximate guarantee is
worth nothing here because the failure it exists to prevent is silent truncation.

The protocol lives beside chunking rather than beside the store's own `Embedder` because the
chunking preflight is what defines this contract: a special-token count, a sequence cap and
character-level token boundaries are needed only by something that has to *cut text to fit*.
`retrieval.md`'s query-side preflight is specified as this same tokenizer applied to a prompt, so
the read path borrows this definition rather than owning a second one.
"""

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError
from zikaron.core.indexing import acquisition, model_cache, model_pin
from zikaron.core.store.embedder import Embedder

if TYPE_CHECKING:
    # Annotations only: `fastembed`'s import cost is the reason `load` imports it inside the
    # function body, so naming its types here must not undo that at runtime.
    from fastembed import TextEmbedding
    from tokenizers import Tokenizer


@runtime_checkable
class Encoder(Embedder, Protocol):
    """An embedding model, plus the tokenizer facts the chunking preflight budgets against.

    Extends the store's `Embedder` because a store's `vec0` width is fixed from the same model
    that will later fill it, so anything satisfying this protocol can also be handed to
    `Store.create` — one object, one artifact, one recorded `embed_model`/`embed_dim` pair.

    Every count here **excludes** special tokens, so a caller adds `n_special_tokens` itself and
    the cap arithmetic is visible where it is performed rather than hidden inside an accessor.
    """

    @property
    def n_special_tokens(self) -> int:
        """How many special tokens the model wraps a sequence in — `[CLS]`/`[SEP]` for BGE.

        A property of the artifact, so an implementation measures it rather than asserting 2.
        """
        ...

    @property
    def max_sequence_tokens(self) -> int:
        """The longest sequence, special tokens included, the model processes untruncated."""
        ...

    def count_tokens(self, text: str) -> int:
        """How many tokens `text` becomes, excluding special tokens.

        Must not truncate. A counter that saturates at `max_sequence_tokens` reports every
        over-length paragraph as sitting exactly at the cap, so the hard-split step that exists
        to catch those never fires and the canary never trips.
        """
        ...

    def token_char_spans(self, text: str) -> tuple[tuple[int, int], ...]:
        """One `(start, end)` character span per token of `text`, excluding special tokens.

        This is what lets a hard split land on a token boundary rather than mid-token: the caller
        slices `text` by these offsets. Spans are in token order and non-overlapping, and are
        offsets into `text` exactly as passed; characters between them are what the tokenizer
        discarded as whitespace.
        """
        ...

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Embed every text, in order, as one vector of `dim` floats each.

        Blocking, and a cold model load costs hundreds of milliseconds, so a caller running on an
        event loop is responsible for keeping this call off it.
        """
        ...


def _artifact_failure(model_name: str, expected: str) -> ZikaronError:
    """`bad_config` naming the configured model, for an artifact that cannot supply a fact.

    `source='file'` rather than `'meta'`: the culprit is which model the configuration asked for,
    not a value the store recorded, and `file` is what points an operator at the key to change.
    """
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.FILE,
        file="<embedding artifact>",
        key="embedding.embed_model",
        value=model_name,
        expected=expected,
    )


def index_identity_disagrees(
    *, reported_model: str, reported_dim: int, recorded_model: str, recorded_dim: int
) -> ZikaronError:
    """`bad_config` for an encoder whose identity disagrees with the index it would write into.

    One definition rather than one per checking site, because the *payload* is the contract: a
    caller diagnosing this is told what the encoder reports and what the store recorded, and the
    two checks that can raise it — eagerly at construction, and off-thread once a deferred load
    returns — are the same refusal discovered at different moments, not two different errors.

    `source='meta'`: the store's recorded identity is the authority being contradicted, and it is
    what a reader has to look at to understand the disagreement.
    """
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.META,
        key="embed_model/embed_dim",
        value=f"{reported_model}/{reported_dim}",
        expected=f"{recorded_model}/{recorded_dim} (what this store's existing index was built "
        "with — an encoder that disagrees would write vectors labelled with a model that did not "
        "produce them)",
    )


def assembled_tokens(prefix: str, text: str, *, encoder: Encoder) -> int:
    """How many tokens the model will actually see for `prefix + text`, special tokens included.

    Counted on the **concatenation**, never as the sum of the two pieces' counts. A tokenizer
    re-tokenizes across a join, so neither count bounds the other: with a prefix ending in
    whitespace the pre-tokenizer splits at the boundary and the two agree — but a prefix is
    free-form text, and one without a trailing boundary fuses with the following first token and can
    produce *more* pieces than the two counts predicted. Trusting the sum would then report a
    sequence as fitting while the model quietly dropped its tail, which is the single failure every
    budget in this codebase exists to prevent.

    Both prefixes this store uses go through here: the query instruction a read prepends to a
    prompt, and the file path the knowledge index prepends to a chunk. **A caller whose real
    sequence has a separator between the two passes it as part of `prefix`**, because the whole
    point of this function is that the counted string and the emitted string are the same string —
    a separator charged separately, or assumed, is a join this does not see.
    """
    return encoder.count_tokens(f"{prefix}{text}") + encoder.n_special_tokens


def token_head(text: str, *, tokens: int, encoder: Encoder) -> str:
    """The first `tokens` tokens of `text`, sliced on token boundaries.

    The one way this codebase shortens a sequence for the model: the cut lands between tokens and
    never inside one, because a fragment of a word embeds as a different word. Head rather than
    tail, in both places that need it — the head carries the topic and the earliest-named
    identifiers — and in both the lexical arm still sees the whole text, so what the head drops
    stays reachable by the other arm.

    The spans are counted against the count that decided a shortening was needed. A span list that
    is well-formed but *short* — ordered, in range, and covering only the first few tokens — would
    keep less text than intended while every later check still passed, so the disagreement is
    refused here rather than left to something that cannot see it.

    A text the tokenizer finds no token in has no head, and yields the empty string rather than an
    index error: it is the honest answer, and the sequence it goes on to build is the prefix alone.

    Raises:
        ZikaronError: `BAD_CONFIG` naming `embedding.embed_model` if the artifact's token count and
            token spans disagree, since the head kept would then not be the head that was counted.
    """
    spans = encoder.token_char_spans(text)
    if len(spans) != encoder.count_tokens(text):
        raise _artifact_failure(
            encoder.model_name,
            "a tokenizer whose token count and token spans agree — they disagree, so the head "
            "kept here would not be the head that was counted",
        )
    window = spans[:tokens]
    if not window:
        return ""
    return text[window[0][0] : window[-1][1]]


@dataclass(frozen=True, slots=True)
class ArtifactFacts:
    """Everything `FastEmbedEncoder` measures off the loaded artifact rather than assuming.

    One value type instead of four constructor parameters, because these four are a single fact —
    *what the model that was actually loaded turned out to be* — and they are always established
    together, in `load`, from the same object. D20 makes the model a config key, so none of them
    may be a literal transcribed from the model this code was written against.
    """

    model_name: str
    dim: int
    n_special_tokens: int
    max_sequence_tokens: int


class FastEmbedEncoder:
    """`Encoder` over a real `fastembed` model and a truncation-free copy of its own tokenizer.

    Construct with `load`, which is also where the `fastembed` import happens: importing this
    module has to stay free, because `zikaron-core` is imported by processes that never embed
    anything and the model import alone is a measurable share of a cold start.

    **Why the tokenizer is a copy.** fastembed configures its tokenizer with
    `truncation.max_length` at the model's cap, so counting through *that* instance returns the
    cap for any longer text — measured, and fatal to the preflight, since an over-length
    paragraph then looks like it sits exactly at the limit and is never hard-split. The copy is
    built from the deployed tokenizer's own serialized form, so it is the same vocabulary and the
    same normalization with only the truncation rule dropped, and the instance fastembed embeds
    with is left exactly as fastembed configured it.
    """

    __slots__ = ("_facts", "_model", "_tokenizer")

    def __init__(
        self, *, model: "TextEmbedding", tokenizer: "Tokenizer", facts: ArtifactFacts
    ) -> None:
        self._model = model
        self._tokenizer = tokenizer
        self._facts = facts

    @classmethod
    def load(cls, model_name: str) -> Self:
        """Load `model_name` through fastembed and derive every tokenizer fact from the artifact.

        Nothing here is a constant transcribed from a model card: the width comes from one real
        embedding, the special-token count from encoding one word twice, and the sequence cap
        from the deployed tokenizer's own truncation configuration. D20 keeps the model a config
        key, so each of those is a property of whichever artifact was actually loaded and not of
        the one this was written against.

        Raises:
            ZikaronError: `BAD_CONFIG` naming `embedding.embed_model` if the loaded model exposes
                no tokenizer, or if that tokenizer declares no maximum sequence length — either of
                which would leave the preflight budgeting against a number nobody supplied.
        """
        from fastembed import TextEmbedding  # noqa: PLC0415
        from tokenizers import Tokenizer  # noqa: PLC0415

        # Both arguments, not either: `OnnxTextEmbedding.__init__` runs
        # `define_cache_dir(cache_dir)` — which `mkdir`s — before the `download_model` call that
        # `specific_model_path` returns early from, so passing the specific path alone still
        # creates an empty `tempfile.gettempdir()/fastembed_cache` on every service start.
        cache_dir = model_cache.resolved_model_cache_dir()
        pin = model_pin.pin_for(model_name)
        specific_model_path = (
            None if pin is None else str(acquisition.artifact_directory(pin, cache_dir=cache_dir))
        )
        try:
            model = TextEmbedding(
                model_name=model_name,
                cache_dir=str(cache_dir),
                specific_model_path=specific_model_path,
            )
        except Exception as error:
            # **The cause has to be in the payload, because nothing else will carry it.**
            # `server.py` logs a traceback for a non-`ZikaronError` and returns only `data` for a
            # `ZikaronError`, and nothing in the package renders `__cause__`. Converting without
            # this text would report a broken `onnxruntime` as a config fault pointing at a
            # `doctor` that passes, with the real message on no channel.
            if pin is None:
                raise
            raise _artifact_failure(
                model_name,
                f"an artefact that loads from {specific_model_path} — constructing it raised "
                f"{type(error).__name__}: {error}; `zikaron doctor` checks its files against the "
                "pin this release carries",
            ) from error
        deployed = getattr(model.model, "tokenizer", None)
        if not isinstance(deployed, Tokenizer):
            raise _artifact_failure(model_name, "a model exposing its own tokenizers.Tokenizer")

        truncation = deployed.truncation
        if truncation is None or "max_length" not in truncation:
            raise _artifact_failure(
                model_name, "a tokenizer declaring max_length, the model's sequence cap"
            )
        max_sequence_tokens = int(truncation["max_length"])

        counting = Tokenizer.from_str(deployed.to_str())
        counting.no_truncation()

        probe = "probe"
        # Measured rather than asserted to be 2: `n_special` is a property of the artifact, and D20
        # keeps the artifact a config key. No lower bound is checked here because a wrong value in
        # either direction lands somewhere that already fails loudly — too many specials leaves no
        # room for content, which is `index_failed` at the `budget` stage, and too few makes an
        # assembled sequence overrun the cap, which is the `assembly` stage.
        n_special_tokens = len(counting.encode(probe).ids) - len(
            counting.encode(probe, add_special_tokens=False).ids
        )

        (vector,) = list(model.embed([probe]))
        return cls(
            model=model,
            tokenizer=counting,
            facts=ArtifactFacts(
                model_name=model_name,
                dim=len(vector),
                n_special_tokens=n_special_tokens,
                max_sequence_tokens=max_sequence_tokens,
            ),
        )

    @property
    def model_name(self) -> str:
        """The model identifier this encoder was loaded from."""
        return self._facts.model_name

    @property
    def dim(self) -> int:
        """The measured width of the vectors this encoder produces."""
        return self._facts.dim

    @property
    def n_special_tokens(self) -> int:
        """The measured number of special tokens the model wraps a sequence in."""
        return self._facts.n_special_tokens

    @property
    def max_sequence_tokens(self) -> int:
        """The cap read from the deployed tokenizer's own truncation configuration."""
        return self._facts.max_sequence_tokens

    def count_tokens(self, text: str) -> int:
        """How many tokens `text` becomes, excluding special tokens, without truncating."""
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def token_char_spans(self, text: str) -> tuple[tuple[int, int], ...]:
        """One character span per token of `text`, from the tokenizer's own offsets.

        The offsets are checked rather than trusted, on both properties a caller slicing by them
        depends on, because a violation of either produces text rather than an error:

        - **In range.** A tokenizer whose normalization rewrote the text would report offsets into
          the *rewritten* form, and slicing the original by those would cut in the wrong places.
        - **In order and non-overlapping.** A hard split takes a window of consecutive spans and
          slices from the first's start to the last's end, so spans that ran backwards or overlapped
          would silently reorder or duplicate the prose inside a chunk.
        """
        spans = tuple(
            (int(start), int(end))
            for start, end in self._tokenizer.encode(text, add_special_tokens=False).offsets
        )
        if any(start < 0 or end > len(text) or start > end for start, end in spans):
            raise _artifact_failure(
                self._facts.model_name, "a tokenizer reporting offsets into the text as passed"
            )
        if any(later[0] < earlier[1] for earlier, later in pairwise(spans)):
            raise _artifact_failure(
                self._facts.model_name,
                "a tokenizer reporting offsets in token order, without overlap",
            )
        return spans

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Embed every text in order. Blocking; the caller keeps it off any event loop."""
        return tuple(tuple(float(value) for value in vector) for vector in self._model.embed(texts))


class BackgroundLoadedEncoder:
    """An `Encoder` that answers its declared identity at once and loads its artifact off-thread.

    Exists so a process can bind a socket, or do anything else, while the model is still loading:
    the load dominates startup, and every step between construction and the first *use* of an
    embedding or a token count is independent of it.

    **Two properties answer immediately and five block.** `model_name` and `dim` are the store's
    declared identity — the model the caller asked to load, and the width the store recorded — so
    a consistency check that only compares those two against the store runs without weights.
    `n_special_tokens`, `max_sequence_tokens`, `count_tokens`, `token_char_spans` and `embed` are
    facts of the artifact, so each waits for the load. That split is the whole point: a check
    written against the declared identity does not drag the model onto a critical path, and one
    written against the artifact still cannot be answered without it.

    **The artifact is checked against the declared width by the loading thread itself**, the
    moment the load returns, rather than by whoever happens to touch it first. Checking here keeps
    the guarantee every caller actually needs — that no write is ever made through an encoder
    whose measured width disagrees with the index it is writing into — while moving *when* it is
    discovered off the critical path. The model *name* is deliberately not re-checked: the
    artifact reports back the name it was asked for, so comparing them tests nothing.

    **Every failure is latched and re-raised on each blocking access**, whether it is the width
    disagreeing or the load itself failing — a missing artifact, an unreadable tokenizer, a
    download that did not complete. Nothing is swallowed and nothing is retried: the load is
    attempted once, and a caller that reaches a blocking member gets the original failure rather
    than a second attempt's.

    A holder that must react to a failure *without* touching the encoder — to stop a process that
    would otherwise sit accepting requests it can never serve — waits on `failure()` instead.
    """

    __slots__ = ("_artifact", "_declared", "_dim", "_failure", "_loaded", "_model_name")

    def __init__(self, *, model_name: str, load: Callable[[str], Encoder]) -> None:
        self._model_name = model_name
        self._dim: int | None = None
        self._artifact: Encoder | None = None
        self._failure: BaseException | None = None
        # Separate events because the two facts become true independently and in either order: a
        # caller declares the store's width whenever it has opened the store, which may be before
        # or after the load finishes.
        self._declared = threading.Event()
        self._loaded = threading.Event()
        # Daemon, because this thread must never be the reason a process outlives its work. A
        # non-daemon loader would keep the interpreter alive through a shutdown that had already
        # decided to exit, and it holds nothing that needs releasing.
        threading.Thread(
            target=self._load_and_check, args=(load,), name="zikaron-encoder-load", daemon=True
        ).start()

    def declare_dim(self, dim: int) -> None:
        """Declare the width the store recorded, releasing the loader to check the artifact.

        Call exactly once, and before using this object as an `Encoder`: `dim` has nothing to
        answer until it is called. A caller that wants the artifact itself, with no recorded width
        to check it against, calls `artifact()` instead — which also releases the loader.
        """
        self._dim = dim
        self._declared.set()

    def release(self) -> None:
        """Release the loader with no width to check, for a caller that will not use this encoder.

        The counterpart to `declare_dim` for a caller that has abandoned the store it was going to
        check against — an open that failed after this was constructed. Without it the loading
        thread waits for a declaration that will never come, and while it is a daemon thread and so
        never keeps a process alive, a process that constructs many of these would accumulate one
        blocked thread per abandonment.
        """
        self._declared.set()

    def artifact(self) -> Encoder:
        """Block until the load finishes and return the loaded encoder itself.

        For a caller that needs the real artifact rather than this facade — creating a store,
        where the recorded width is about to be *derived* from the model rather than checked
        against it. Releases the loader with nothing to check, so it must not be combined with
        `declare_dim` on the same object.

        Raises:
            BaseException: whatever the load raised, re-raised unchanged.
        """
        self._declared.set()
        return self._resolved()

    def failure(self) -> BaseException | None:
        """Block until the load finishes, then report what it raised, if anything.

        The one member that reports a failure instead of raising it, so a caller whose job is to
        *react* to the failure does not have to catch what it is watching for.
        """
        self._loaded.wait()
        return self._failure

    @property
    def model_name(self) -> str:
        """The model this encoder was asked to load. Answered without waiting for it."""
        return self._model_name

    @property
    def dim(self) -> int:
        """The width declared by `declare_dim`. Answered without waiting for the load.

        Raises:
            ZikaronError: `BAD_CONFIG` if no width has been declared yet, which means this object
                is being used as an `Encoder` before the store it belongs to was opened.
        """
        if self._dim is None:
            raise _artifact_failure(
                self._model_name, "a declared index width, set once the store has been opened"
            )
        return self._dim

    @property
    def n_special_tokens(self) -> int:
        """The artifact's special-token count. Waits for the load."""
        return self._resolved().n_special_tokens

    @property
    def max_sequence_tokens(self) -> int:
        """The artifact's sequence cap. Waits for the load."""
        return self._resolved().max_sequence_tokens

    def count_tokens(self, text: str) -> int:
        """The artifact's token count for `text`. Waits for the load."""
        return self._resolved().count_tokens(text)

    def token_char_spans(self, text: str) -> tuple[tuple[int, int], ...]:
        """The artifact's character spans for `text`. Waits for the load."""
        return self._resolved().token_char_spans(text)

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """The artifact's embeddings for `texts`. Waits for the load."""
        return self._resolved().embed(texts)

    def _resolved(self) -> Encoder:
        # An undeclared facade would otherwise deadlock here rather than fail: this wait is for a
        # load that is itself waiting for the declaration that is never coming. `dim` answers the
        # same misuse with a refusal, and the members that block should not answer it with a hang.
        # Safe to read without synchronization, because every legitimate declaration
        # happens-before this object is published to anything that could call this.
        if not self._declared.is_set():
            raise _artifact_failure(
                self._model_name, "a declared index width, set once the store has been opened"
            )
        self._loaded.wait()
        if self._failure is not None:
            raise self._failure
        if self._artifact is None:  # pragma: no cover - unreachable while both are set together
            raise _artifact_failure(self._model_name, "a loaded model")
        return self._artifact

    def _load_and_check(self, load: Callable[[str], Encoder]) -> None:
        """Load the artifact, check its measured width against the declared one, and latch either.

        `BaseException` rather than `Exception`: this runs on its own thread, so nothing else can
        observe an escaping failure, and a caller blocked in `_resolved` would otherwise wait for
        an event that is never set. Everything reaches a waiting caller or `failure()`.
        """
        try:
            self._artifact = self._load_or_reject(load)
        except BaseException as error:
            self._failure = error
        finally:
            self._loaded.set()

    def _load_or_reject(self, load: Callable[[str], Encoder]) -> Encoder:
        artifact = load(self._model_name)
        self._declared.wait()
        if self._dim is not None and artifact.dim != self._dim:
            raise index_identity_disagrees(
                reported_model=artifact.model_name,
                reported_dim=artifact.dim,
                recorded_model=self._model_name,
                recorded_dim=self._dim,
            )
        return artifact
