"""What the shipped `max_output_size` does and does not bound.

The harness truncates hook stdout past `max_output_size` **silently**, so the failure this number
guards against is a write policy the model received two thirds of, or an injected block cut off
mid-memory, with nothing on any channel saying so.

**The first version of this file proved the wrong thing.** It multiplied `gist_max_tokens` by four
bytes per token and called the product a worst case. Measured against the real tokenizer, that
factor is not a bound at all: WordPiece maps anything outside its vocabulary to a single `[UNK]`
token, so a 4000-character unbroken run counts as **one token**, and so do 256 emoji.
`gist_max_tokens` therefore does not constrain bytes in the adversarial direction at all, and the
tests below state what is actually true rather than restating the assumption:

- the shipped policy fits, with the real number;
- a block of five gists of *ordinary prose* at the configured token ceiling fits;
- a single pathological gist can exceed any cap, which is a **disclosed hole in the store's own
  bounds** rather than something this file can close: nothing in the write path bounds a gist's
  byte length, and closing it belongs to the bounds ladder rather than to the hook's output cap.
"""

import uuid as uuid_module

import pytest

from zikaron.core.config.keys import CONFIG_KEYS, IntBounds
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.records.memory import Tier
from zikaron.core.retrieval.block import render
from zikaron.core.retrieval.ranking import PoolRow, RankedMemory
from zikaron.hook.limits import MAX_OUTPUT_SIZE, TIMEOUT_MS
from zikaron.hook.write_policy import WRITE_POLICY_PROMPT

#: The push limit the design fixes for the injected block: the top five gists.
_PUSH_LIMIT = 5

#: The harness's own default, which an array-format entry inherits because that format documents no
#: `max_output_size` field to state.
_HARNESS_DEFAULT_OUTPUT_SIZE = 10_240

_MODEL = "BAAI/bge-small-en-v1.5"


def _gist_max_tokens_ceiling() -> int:
    """The largest `gist_max_tokens` any configuration permits — not its default."""
    keys = [key for key in CONFIG_KEYS if key.name == "gist_max_tokens"]
    assert len(keys) == 1
    bounds = keys[0].bounds
    assert isinstance(bounds, IntBounds), "gist_max_tokens is a token count, so an integer bound"
    ceiling = bounds.maximum
    assert ceiling is not None, "an unbounded token count would make this whole bound unprovable"
    return ceiling


def _block_of(gist: str) -> str:
    """The injected block for five demoted rows sharing one gist — the largest shape it can take."""
    rows = [
        RankedMemory(
            row=PoolRow(
                uuid=str(uuid_module.uuid4()),
                tier=Tier.LONG_TERM,
                gist=gist,
                active=False,
                superseded_by=str(uuid_module.uuid4()),
                created_at="2026-08-03T00:00:00+00:00",
                updated_at="2026-08-03T00:00:00+00:00",
            ),
            fused_score=1.0 - index / 10,
            dense_rank=index + 1,
            lexical_rank=index + 1,
            best_distance=0.1,
        )
        for index in range(_PUSH_LIMIT)
    ]
    return render(rows)


def test_the_write_policy_fits_inside_the_shipped_output_cap() -> None:
    assert len(WRITE_POLICY_PROMPT.encode("utf-8")) < MAX_OUTPUT_SIZE


def test_the_write_policy_also_fits_the_default_an_array_install_inherits() -> None:
    """Worth its own test: an array-format install cannot state `max_output_size`, so if the policy
    did not fit the harness default those installs would be silently broken and the test above would
    not say so.
    """
    assert len(WRITE_POLICY_PROMPT.encode("utf-8")) < _HARNESS_DEFAULT_OUTPUT_SIZE


@pytest.mark.integration
def test_ordinary_prose_at_the_token_ceiling_fits_the_shipped_cap() -> None:
    """Five gists of real English, each as long as the largest `gist_max_tokens` any configuration
    allows, counted by the tokenizer that will actually count them.

    Integration tier because it loads the real tokenizer — and it has to: the defect in the previous
    version of this test was substituting an assumed token/byte ratio for the measured one.
    """
    encoder = FastEmbedEncoder.load(_MODEL)
    ceiling = _gist_max_tokens_ceiling()
    words = "integration tests flake on continuous integration unless the database host is set "
    gist = words
    while encoder.count_tokens(gist + words) <= ceiling:
        gist += words
    assert encoder.count_tokens(gist) <= ceiling
    block = _block_of(gist)
    assert len(block.encode("utf-8")) < MAX_OUTPUT_SIZE


@pytest.mark.integration
def test_the_token_bound_does_not_bound_bytes_at_all() -> None:
    """The measurement that overturned this file's first version, kept as a test so the hole is a
    recorded fact rather than a remembered one.

    An unbroken run of 4000 characters is **one** token: WordPiece has no vocabulary entry for
    it, so
    it becomes a single `[UNK]`. A gist like that passes every bound the write path states and
    produces a block far past any `max_output_size`, which the harness then truncates in silence.
    Nothing here can fix that; a byte bound on `gist` belongs to the write path's bounds ladder.
    """
    encoder = FastEmbedEncoder.load(_MODEL)
    modest = "a" * 4000
    assert encoder.count_tokens(modest) == 1, "an unbroken run is one [UNK], whatever its length"

    # Five of those already blow the cap an array-format install inherits, which is the realistic
    # exposure: that format documents no `max_output_size` field for us to state.
    assert len(_block_of(modest).encode("utf-8")) > _HARNESS_DEFAULT_OUTPUT_SIZE

    # And the run can grow without the token count moving, so no output cap is safe from it — the
    # point being that this is unbounded rather than merely large.
    enormous = "a" * 20_000
    assert encoder.count_tokens(enormous) <= _gist_max_tokens_ceiling()
    assert len(_block_of(enormous).encode("utf-8")) > MAX_OUTPUT_SIZE


def test_the_stated_timeout_leaves_the_hooks_own_deadline_room_to_fire_first() -> None:
    """The internal deadline has to expire before the harness's does, because ours produces a
    `hook.log` line and a model-facing relay while the harness's kill produces neither.
    """
    internal_deadline_seconds = 2.0
    assert internal_deadline_seconds * 2 <= TIMEOUT_MS / 1000
