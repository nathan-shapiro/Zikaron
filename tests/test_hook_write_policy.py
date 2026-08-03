"""The `agentSpawn` prompt text, checked against its source block in `design/write-policy.md` §2.

Same drift-guard shape M1's three singletons already established: parse the design document at
test time rather than comparing against a second hand-typed copy, so a revision to the prompt on
either side of the boundary fails a test instead of silently diverging.
"""

from tests.design_tables import fenced_code
from zikaron.hook.write_policy import WRITE_POLICY_PROMPT

DOCUMENT = "write-policy.md"
HEADING = "## 2. The prompt"


def test_prompt_matches_the_design_document_exactly() -> None:
    assert fenced_code(DOCUMENT, HEADING, "") == WRITE_POLICY_PROMPT


def test_prompt_is_a_single_line_gist_instruction_present() -> None:
    """A cheap, independent sanity check that the drift guard above is reading the right block —
    not a duplicate assertion of its content, but a check on a property the exact-match test
    could theoretically pass by accident if both sides were wrong in the identical way (e.g. an
    empty string on both). `write-policy.md` §1 states the gist instruction is load-bearing
    (D13's relevance-triage argument), so its absence would mean this guard is reading the wrong
    fence entirely.
    """
    assert "Gists are for triage" in WRITE_POLICY_PROMPT


def test_prompt_is_stripped_of_markdown_fence_markers() -> None:
    assert not WRITE_POLICY_PROMPT.startswith("```")
    assert not WRITE_POLICY_PROMPT.rstrip().endswith("```")
