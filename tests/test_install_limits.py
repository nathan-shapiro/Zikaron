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
- a single pathological gist can exceed any cap **through the token bound alone**, which is why the
  write path also bounds a gist's *characters*. That bound is what turns the worst-case block
  assertions below from an observation about one prose sample into arithmetic over a limit the
  write path enforces — and it is enforced in the bounds ladder, not here, since an output cap
  cannot fix a store's own bounds.
"""

import uuid as uuid_module

import pytest

from zikaron.core.config.keys import CONFIG_KEYS, IntBounds
from zikaron.core.indexing.chunking import GIST_MAX_CHARACTERS, utf16_units
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.records.memory import Tier
from zikaron.core.retrieval.block import render
from zikaron.core.retrieval.ranking import PoolRow, RankedMemory
from zikaron.harness.spec import CLAUDE_CODE, KIRO
from zikaron.hook import push
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
    recorded fact rather than a remembered one — and now paired with the bound that closes it.

    An unbroken run of 4000 characters is **one** token: WordPiece has no vocabulary entry for it,
    so it becomes a single `[UNK]`. A gist like that satisfies every *token* bound the write path
    states, and the run can grow without the token count moving, so no output cap is safe from it.
    """
    encoder = FastEmbedEncoder.load(_MODEL)
    modest = "a" * 4000
    assert encoder.count_tokens(modest) == 1, "an unbroken run is one [UNK], whatever its length"
    assert len(_block_of(modest).encode("utf-8")) > _HARNESS_DEFAULT_OUTPUT_SIZE

    enormous = "a" * 20_000
    assert encoder.count_tokens(enormous) <= _gist_max_tokens_ceiling()
    assert len(_block_of(enormous).encode("utf-8")) > MAX_OUTPUT_SIZE

    # What changed: neither of those gists can reach a block any more, because the write path now
    # bounds a gist in a unit that actually constrains size. The hole is closed at the source
    # rather than papered over at the output cap.
    assert len(modest) > GIST_MAX_CHARACTERS
    assert len(enormous) > GIST_MAX_CHARACTERS


#: One UTF-16 unit and three UTF-8 bytes — the most bytes any single unit can cost.
_BMP_THREE_BYTE = "漢"

#: Two UTF-16 units and four UTF-8 bytes, so two bytes per unit: cheaper *per unit* than the above,
#: which is the non-obvious part.
_ASTRAL_FOUR_BYTE = "\U00010348"


def _at_the_gist_bound(filler: str) -> str:
    """The longest gist the write path admits, built by repeating `filler`."""
    gist = filler * (GIST_MAX_CHARACTERS // utf16_units(filler))
    assert utf16_units(gist) == GIST_MAX_CHARACTERS
    return gist


def test_a_worst_case_block_fits_every_supported_harnesss_injection_budget() -> None:
    """The assertion the character bound exists to make possible, and the one M12 could only make
    by accident: five rows, each gist as long as the write path will accept, measured against each
    harness in that harness's own unit.

    Exercised with the cheapest and the most expensive characters the bound admits, because an
    ASCII-only fixture is the *best* case per character and would prove the universal claim only
    for one-unit-per-character content — which is precisely the gap that made an earlier version of
    this test pass while the claim it stated was false for astral text.

    No tokenizer here, deliberately. The claim is arithmetic over a bound the write path enforces,
    not an observation about how one prose sample happened to tokenize, which is why it needs no
    model and belongs in the default tier.
    """
    for filler in ("a", _BMP_THREE_BYTE, _ASTRAL_FOUR_BYTE):
        block = _block_of(_at_the_gist_bound(filler))
        for spec in (KIRO, CLAUDE_CODE):
            assert not spec.exceeds_injection_budget(block), filler


def test_the_byte_worst_case_is_a_three_byte_bmp_character_not_a_four_byte_astral_one() -> None:
    """The cross-unit step, made concrete rather than argued — and the direction is not the obvious
    one, which is why it is asserted.

    Once the gist bound counts UTF-16 units, the widest character in *bytes* is not the widest in
    UTF-8. A three-byte Basic-Multilingual-Plane character is one unit, so it spends three bytes
    per unit; a four-byte astral character is two units, so it spends only two. The ceiling that
    carries the kiro byte claim is therefore three bytes per unit, and this pins both the ordering
    and the resulting fit.
    """
    assert len(_BMP_THREE_BYTE.encode("utf-8")) == 3
    assert utf16_units(_BMP_THREE_BYTE) == 1
    assert len(_ASTRAL_FOUR_BYTE.encode("utf-8")) == 4
    assert utf16_units(_ASTRAL_FOUR_BYTE) == 2

    widest = _block_of(_at_the_gist_bound(_BMP_THREE_BYTE))
    astral = _block_of(_at_the_gist_bound(_ASTRAL_FOUR_BYTE))
    assert len(widest.encode("utf-8")) > len(astral.encode("utf-8"))
    assert len(widest.encode("utf-8")) < MAX_OUTPUT_SIZE
    assert not KIRO.exceeds_injection_budget(widest)


def test_the_stated_timeout_leaves_the_hooks_own_deadline_room_to_fire_first() -> None:
    """The internal deadline has to expire before the harness's does, because ours produces a
    `hook.log` line and a model-facing relay while the harness's kill produces neither.
    """
    assert push._DEADLINE_SECONDS * 2 <= TIMEOUT_MS / 1000
