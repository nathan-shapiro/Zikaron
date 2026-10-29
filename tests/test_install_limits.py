"""What bounds a hook's output against each harness's injection budget.

Both harnesses cut a hook's output past a fixed number of characters, and kiro marks the cut to the
model alone, so the failure these guard against is a write policy the model received part of, or an
injected block cut off mid-memory, with nothing anyone else can see.

**A token bound is not a size bound.** WordPiece maps anything outside its vocabulary to a single
`[UNK]` token, so a 4000-character unbroken run counts as **one token**. The write path therefore
also bounds a gist's *characters*, and that bound is what turns the block assertions below into
arithmetic over a limit the write path enforces. It proves the block fits Claude Code's budget;
under kiro's smaller one it does not, and the per-harness figure in `design/harness.md` §"Injection
budgets" says how long the five gists may be before the block overruns it.
"""

import re
import uuid as uuid_module

import pytest

from tests.design_tables import section_lines, table_with_columns
from zikaron.core.config.keys import CONFIG_KEYS, IntBounds
from zikaron.core.indexing.chunking import GIST_MAX_CHARACTERS, utf16_units
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.records.memory import Tier
from zikaron.core.retrieval.block import render
from zikaron.core.retrieval.ranking import PoolRow, RankedMemory
from zikaron.harness.spec import CLAUDE_CODE, KIRO
from zikaron.hook import connect, push
from zikaron.hook.limits import HOOK_TIMEOUT_SECONDS
from zikaron.hook.write_policy import SUBAGENT_WRITE_POLICY_PROMPT, WRITE_POLICY_PROMPT

#: The push limit the design fixes for the injected block: the top five gists.
_PUSH_LIMIT = 5

#: Where the design states the shipped policy's measured size, for the guard below.
_POLICY_SIZE_DOCUMENT = "architecture.md"
_POLICY_SIZE_HEADING = "## Distribution artefacts"

_MODEL = "BAAI/bge-small-en-v1.5"

#: The figure `schema.md` states for the worst-case block, in UTF-16 units.
_STATED_WORST_CASE = re.compile(r"\*\*([\d,]+) units")

#: The figure `harness.md` states for the longest gists a kiro block fits with.
_STATED_KIRO_GIST = re.compile(r"\*\*([\d,]+)\*\* units per gist")


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


def test_the_design_states_the_size_the_shipped_policy_actually_is() -> None:
    """The figure `architecture.md` quotes, against the constant it describes.

    Pinned because every edit to the prompt's prose moves it, and the assertions that the policy
    *fits* say nothing about what it measures. Both spellings are checked: characters are what both
    harnesses' budgets count, and an edit that swaps an ASCII character for a multi-byte one moves
    only the byte figure.
    """
    section = "\n".join(section_lines(_POLICY_SIZE_DOCUMENT, _POLICY_SIZE_HEADING))
    stated = re.findall(r"\*\*(\d+) bytes\*\* \((\d+)\s*\n?\s*characters\)", section)
    assert len(stated) == 2, (
        f"{_POLICY_SIZE_DOCUMENT} / {_POLICY_SIZE_HEADING} no longer states both policy sizes in "
        "the form this guard reads; restate them or move the guard, but do not leave either "
        "unpinned — there are two variants and pinning one is how the other goes stale"
    )
    assert [(int(size), int(length)) for size, length in stated] == [
        (len(text.encode("utf-8")), len(text))
        for text in (WRITE_POLICY_PROMPT, SUBAGENT_WRITE_POLICY_PROMPT)
    ]


@pytest.mark.integration
def test_ordinary_prose_at_the_token_ceiling_fits_claude_codes_budget() -> None:
    """Five gists of real English, each as long as the largest `gist_max_tokens` any configuration
    allows, counted by the tokenizer that will actually count them.

    Integration tier because it loads the real tokenizer — and it has to: substituting an assumed
    token-to-size ratio for the measured one is the defect a test like this exists to avoid.
    """
    encoder = FastEmbedEncoder.load(_MODEL)
    ceiling = _gist_max_tokens_ceiling()
    words = "integration tests flake on continuous integration unless the database host is set "
    gist = words
    while encoder.count_tokens(gist + words) <= ceiling:
        gist += words
    assert encoder.count_tokens(gist) <= ceiling
    assert not CLAUDE_CODE.exceeds_injection_budget(_block_of(gist))


@pytest.mark.integration
def test_the_token_bound_does_not_bound_size_at_all() -> None:
    """The measurement behind the character bound, kept as a test so the hole is a recorded fact
    rather than a remembered one — and paired with the bound that closes it.

    An unbroken run of 4000 characters is **one** token: WordPiece has no vocabulary entry for it,
    so it becomes a single `[UNK]`. A gist like that satisfies every *token* bound the write path
    states, and the run can grow without the token count moving, so no budget is safe from it.
    """
    encoder = FastEmbedEncoder.load(_MODEL)
    modest = "a" * 4000
    assert encoder.count_tokens(modest) == 1, "an unbroken run is one [UNK], whatever its length"
    enormous = "a" * 20_000
    assert encoder.count_tokens(enormous) <= _gist_max_tokens_ceiling()
    for spec in (KIRO, CLAUDE_CODE):
        assert spec.exceeds_injection_budget(_block_of(modest))
    # Neither gist can reach a block, because the write path bounds a gist in a unit that actually
    # constrains size.
    assert len(modest) > GIST_MAX_CHARACTERS
    assert len(enormous) > GIST_MAX_CHARACTERS


#: One UTF-16 unit and three UTF-8 bytes.
_BMP_THREE_BYTE = "漢"

#: Two UTF-16 units and four UTF-8 bytes.
_ASTRAL_FOUR_BYTE = "\U00010348"


def _at_the_gist_bound(filler: str) -> str:
    """The longest gist the write path admits, built by repeating `filler`."""
    gist = filler * (GIST_MAX_CHARACTERS // utf16_units(filler))
    assert utf16_units(gist) == GIST_MAX_CHARACTERS
    return gist


def test_a_worst_case_block_fits_claude_codes_budget() -> None:
    """The assertion the character bound exists to make possible: five rows, each gist as long as
    the write path will accept.

    Exercised with the cheapest and the most expensive characters the bound admits, because an
    ASCII-only fixture is the *best* case per character and would prove the claim only for
    one-unit-per-character content. No tokenizer here, deliberately: the claim is arithmetic over a
    bound the write path enforces, so it needs no model and belongs in the default tier.
    """
    for filler in ("a", _BMP_THREE_BYTE, _ASTRAL_FOUR_BYTE):
        assert not CLAUDE_CODE.exceeds_injection_budget(_block_of(_at_the_gist_bound(filler)))


def test_the_kiro_figure_is_the_longest_gist_a_five_row_block_fits_with() -> None:
    """`harness.md` states how long five gists may be before a block overruns kiro's cut, and the
    figure is framing plus five gists, so it moves whenever the block's prose moves. Measured here
    from `block.render` rather than trusted: five gists at the figure fit, five one longer do not.
    """
    section = "\n".join(section_lines("harness.md", "## Injection budgets"))
    stated = [int(found.replace(",", "")) for found in _STATED_KIRO_GIST.findall(section)]
    assert len(stated) == 1, f"expected one per-gist figure for kiro, found {stated}"
    (per_gist,) = stated
    assert not KIRO.exceeds_injection_budget(_block_of("a" * per_gist))
    assert KIRO.exceeds_injection_budget(_block_of("a" * (per_gist + 1)))


#: What the hook's own process start before `run` and its print after are allowed out of the
#: margin. `hook/envelope.py` has the whole process measured at ~48-68 ms; a second is the room left
#: for a host far more loaded than that measurement's.
_PROCESS_START_AND_PRINT_SECONDS = 1.0


def test_the_stated_timeout_leaves_the_hooks_own_deadline_room_to_fire_first() -> None:
    """Both internal deadlines have to expire before the harness's does, because ours produces a
    `hook.log` line and a model-facing relay while the harness's kill produces neither — and the
    cold-start one has to be the longer, or a service the push found absent gets no more time to
    start than a running one gets to answer.

    The cold-start deadline leaves the least room, and that room pays for what runs past it: the
    connect's last attempt, a connect and a `health()` exchange each bounded by
    `_CONNECT_TIMEOUT_SECONDS` and one poll interval before it, then this process's own start and
    print.
    """
    assert push._DEADLINE_SECONDS * 2 <= HOOK_TIMEOUT_SECONDS
    assert push._DEADLINE_SECONDS < push._COLD_START_DEADLINE_SECONDS
    connect_overrun = 2 * connect._CONNECT_TIMEOUT_SECONDS + connect._POLL_INTERVAL_SECONDS
    margin = HOOK_TIMEOUT_SECONDS - push._COLD_START_DEADLINE_SECONDS
    assert margin >= connect_overrun + _PROCESS_START_AND_PRINT_SECONDS


def test_the_designs_stated_worst_case_block_matches_what_the_block_actually_renders() -> None:
    """`schema.md`'s `gist.characters` row states the worst-case block as the derivation that makes
    `GIST_MAX_CHARACTERS` worth having. That figure is framing plus five gists, so it moves whenever
    the block's prose moves; this is the only place it is checked.
    """
    rows = table_with_columns("schema.md", "## Bounds", ("Bound", "Value", "Why"))
    why = [row["Why"] for row in rows if "gist.characters" in row["Bound"]]
    assert len(why) == 1, "schema.md must state the gist character bound exactly once"
    found = [int(group.replace(",", "")) for group in _STATED_WORST_CASE.findall(why[0])]
    assert len(found) == 1, f"expected one units figure, found {found}"
    assert utf16_units(_block_of(_at_the_gist_bound("a"))) == found[0]
