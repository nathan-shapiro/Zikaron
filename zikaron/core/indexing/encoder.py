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

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError
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

        model = TextEmbedding(model_name=model_name)
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
