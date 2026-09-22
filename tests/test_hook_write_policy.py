"""The `agentSpawn` prompt text, checked against its source block in `design/write-policy.md` §2,
and the optional operator override that may replace it.

Same drift-guard shape the schema singletons already establish: parse the design document at
test time rather than comparing against a second hand-typed copy, so a revision to the prompt on
either side of the boundary fails a test instead of silently diverging.
"""

import os
from pathlib import Path

import pytest

from tests.design_tables import fenced_code
from zikaron.harness.spec import CLAUDE_CODE, KIRO
from zikaron.hook import write_policy
from zikaron.hook.limits import MAX_OUTPUT_SIZE
from zikaron.hook.write_policy import (
    OVERRIDE_EMPTY,
    OVERRIDE_OVERSIZE,
    OVERRIDE_REFUSED,
    OVERRIDE_UNREADABLE,
    WRITE_POLICY_PROMPT,
    read_policy,
)

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


class TestReadPolicyOverride:
    """`read_policy`'s conditions (`architecture.md` §"The install contract").

    Every fixture here creates the store at `0700`, which is what `ensure_store_dir` — the helper
    the service and the warm helper both use — enforces. Not decoration: an override is honoured
    only from a directory no other user could have written into, so a fixture using a plain
    `mkdir()` would be testing the refusal path while claiming to test the ordinary one.

    Every case asserts on **both** halves of the returned pair, because the label is the whole
    difference between a fallback an operator can see and one they cannot: a test that only checked
    the text would pass identically whether the note were correct, wrong, or absent.
    """

    def test_absent_override_returns_the_constant_and_no_label(self, tmp_path: Path) -> None:
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        assert read_policy(store, spec=KIRO) == (WRITE_POLICY_PROMPT, None)

    def test_a_missing_store_directory_is_the_absent_case(self, tmp_path: Path) -> None:
        """The very first session of a project, before anything has created `.zikaron` — the most
        common state this function will ever be called in, and it must be the silent one."""
        assert read_policy(tmp_path / ".zikaron", spec=KIRO) == (WRITE_POLICY_PROMPT, None)

    def test_a_clean_override_replaces_the_constant_with_no_label(self, tmp_path: Path) -> None:
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        (store / "write-policy.md").write_text("## My own policy\n\nRecord less.\n")
        assert read_policy(store, spec=KIRO) == ("## My own policy\n\nRecord less.\n", None)

    def test_a_symlinked_override_is_refused_and_labelled(self, tmp_path: Path) -> None:
        """The case the refusal exists for: this text is printed straight into a model's context, so
        a symlink is an exfiltration path for exactly what the policy's own "never record a secret"
        paragraph exists to keep out of the store.
        """
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        secret = tmp_path / "id_rsa"
        secret.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n")
        (store / "write-policy.md").symlink_to(secret)
        text, note = read_policy(store, spec=KIRO)
        assert note == OVERRIDE_REFUSED
        assert text == WRITE_POLICY_PROMPT
        assert "PRIVATE KEY" not in text

    def test_an_override_reached_through_a_symlinked_store_directory_is_refused(
        self, tmp_path: Path
    ) -> None:
        """`O_NOFOLLOW` speaks for the final component only, so the store directory needs its own
        check: otherwise `.zikaron -> elsewhere/` reads a policy the advertised symlink refusal was
        supposed to have stopped, and from a store the service would refuse to open at all.
        """
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "write-policy.md").write_text("## Injected through a symlinked store\n")
        store = tmp_path / ".zikaron"
        store.symlink_to(elsewhere)
        assert read_policy(store, spec=KIRO) == (WRITE_POLICY_PROMPT, OVERRIDE_REFUSED)

    def test_a_file_where_the_store_directory_should_be_is_refused(self, tmp_path: Path) -> None:
        store = tmp_path / ".zikaron"
        store.write_text("not a directory")
        assert read_policy(store, spec=KIRO) == (WRITE_POLICY_PROMPT, OVERRIDE_REFUSED)

    def test_an_override_in_a_world_writable_store_is_refused(self, tmp_path: Path) -> None:
        """The case an obvious reading gets wrong: no symlink is involved, so `O_NOFOLLOW` cannot
        see it, and another local user with write access to a `0777` store could have authored this
        file. Its text must not reach the model's context.
        """
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o777)
        store.chmod(0o777)
        (store / "write-policy.md").write_text("## Authored by somebody else\n")
        text, note = read_policy(store, spec=KIRO)
        assert note == OVERRIDE_REFUSED
        assert text == WRITE_POLICY_PROMPT
        assert "somebody else" not in text

    def test_an_override_in_a_group_writable_store_is_refused(self, tmp_path: Path) -> None:
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        store.chmod(0o770)
        (store / "write-policy.md").write_text("## Authored by the group\n")
        assert read_policy(store, spec=KIRO) == (WRITE_POLICY_PROMPT, OVERRIDE_REFUSED)

    def test_a_group_readable_store_is_also_refused(self, tmp_path: Path) -> None:
        """`0750` cannot be written by the group, but it is not the boundary the design draws, and a
        store whose mode has drifted at all is one whose history this cannot reconstruct.
        """
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        store.chmod(0o750)
        (store / "write-policy.md").write_text("## Readable by the group\n")
        assert read_policy(store, spec=KIRO) == (WRITE_POLICY_PROMPT, OVERRIDE_REFUSED)

    def test_a_private_store_still_honours_its_override(self, tmp_path: Path) -> None:
        """The ordinary case, asserted beside the refusals so the check cannot pass by refusing
        everything."""
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        (store / "write-policy.md").write_text("## Mine\n")
        assert read_policy(store, spec=KIRO) == ("## Mine\n", None)

    def test_a_directory_swapped_in_after_validation_cannot_supply_the_policy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The check/use split, forced deterministically: the store directory is replaced by an
        attacker-shaped one *between* the ownership check and the read. Because the read goes
        through the descriptor that was checked, the swap cannot change what comes back.

        `_require_private` is wrapped rather than raced with threads, so the window is entered
        exactly once and the test cannot pass by luck of timing.
        """
        private = tmp_path / ".zikaron"
        private.mkdir(mode=0o700)
        private.chmod(0o700)
        (private / "write-policy.md").write_text("## The real one\n")
        hostile = tmp_path / "hostile"
        hostile.mkdir(mode=0o777)
        hostile.chmod(0o777)
        (hostile / "write-policy.md").write_text("## Swapped in\n")

        real_require = write_policy._require_private

        def _swap_then_check(directory: int, store_directory: Path) -> None:
            real_require(directory, store_directory)
            private.rename(tmp_path / "moved-away")
            hostile.rename(private)

        monkeypatch.setattr(write_policy, "_require_private", _swap_then_check)
        text, note = read_policy(private, spec=KIRO)
        assert note is None
        assert text == "## The real one\n"
        assert "Swapped in" not in text

    def test_a_store_created_after_an_absent_check_cannot_supply_the_policy(
        self, tmp_path: Path
    ) -> None:
        """An absent store is the ordinary first-session case, and it used to be accepted by a
        *pathname* check that a later read resolved again. Opening the directory first means an
        absent one raises before any child is looked at, so there is no window to create one in.
        """
        assert read_policy(tmp_path / ".zikaron", spec=KIRO) == (WRITE_POLICY_PROMPT, None)

    def test_a_fifo_override_is_refused_without_blocking(self, tmp_path: Path) -> None:
        """Opening a fifo for reading blocks until a writer arrives, which would hang the one path
        `architecture.md` promises cannot fail. `O_NONBLOCK` plus the `fstat` refuse it instead.
        """
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        os.mkfifo(store / "write-policy.md")
        assert read_policy(store, spec=KIRO) == (WRITE_POLICY_PROMPT, OVERRIDE_REFUSED)

    def test_a_directory_in_the_overrides_place_is_refused_and_labelled(
        self, tmp_path: Path
    ) -> None:
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        (store / "write-policy.md").mkdir()
        assert read_policy(store, spec=KIRO) == (WRITE_POLICY_PROMPT, OVERRIDE_REFUSED)

    def test_an_unreadable_override_falls_back_and_is_labelled(self, tmp_path: Path) -> None:
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        override = store / "write-policy.md"
        override.write_text("unreadable")
        override.chmod(0o000)
        try:
            assert read_policy(store, spec=KIRO) == (WRITE_POLICY_PROMPT, OVERRIDE_UNREADABLE)
        finally:
            override.chmod(0o600)

    def test_undecodable_bytes_fall_back_and_are_labelled(self, tmp_path: Path) -> None:
        """`UnicodeDecodeError` is not an `OSError`, so it needs its own place in the caught tuple —
        a mutation dropping it would make an operator's mis-encoded file crash the one path
        `architecture.md` promises cannot fail.
        """
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        (store / "write-policy.md").write_bytes(b"\xff\xfe\x00 not utf-8")
        assert read_policy(store, spec=KIRO) == (WRITE_POLICY_PROMPT, OVERRIDE_UNREADABLE)

    def test_a_blank_override_falls_back_and_is_labelled(self, tmp_path: Path) -> None:
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        (store / "write-policy.md").write_text("   \n\t\n")
        assert read_policy(store, spec=KIRO) == (WRITE_POLICY_PROMPT, OVERRIDE_EMPTY)

    def test_an_oversize_override_is_used_anyway_and_labelled(self, tmp_path: Path) -> None:
        """Used, not truncated and not refused: a harness that overruns its injection budget
        delivers only part of the text, and the label is the only way an operator learns it.
        """
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        oversize = "x" * (MAX_OUTPUT_SIZE + 1)
        (store / "write-policy.md").write_text(oversize)
        assert read_policy(store, spec=KIRO) == (oversize, OVERRIDE_OVERSIZE)

    def test_an_override_exactly_at_the_limit_is_not_labelled(self, tmp_path: Path) -> None:
        """The bound is inclusive: `>` the budget, not `>=`. A fixture one byte over and one byte
        under is what separates the two, since a fixture merely "large" passes either way.
        """
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        at_limit = "x" * MAX_OUTPUT_SIZE
        (store / "write-policy.md").write_text(at_limit)
        assert read_policy(store, spec=KIRO) == (at_limit, None)

    def test_kiros_bound_counts_bytes_not_characters(self, tmp_path: Path) -> None:
        """Kiro's `max_output_size` is a byte cap, and multi-byte characters are exactly where a
        `len(text)` check would silently under-count. One character over the cap in bytes, well
        under it in characters.
        """
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        # Each `—` is 3 bytes in UTF-8, so this is ~1/3 the cap in characters and just over it in
        # bytes.
        text = "—" * (MAX_OUTPUT_SIZE // 3 + 1)
        assert len(text) < MAX_OUTPUT_SIZE
        (store / "write-policy.md").write_text(text)
        assert read_policy(store, spec=KIRO) == (text, OVERRIDE_OVERSIZE)

    def test_claude_codes_bound_counts_characters_not_bytes(self, tmp_path: Path) -> None:
        """The converse of the test above, and the reason the unit travels with the number rather
        than being assumed by the caller: the same multi-byte text that overruns a byte-denominated
        budget sits comfortably inside a character-denominated one three times its size in bytes.
        A check that measured bytes here would label a policy this harness delivers whole.
        """
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        text = "—" * CLAUDE_CODE.injection_budget
        assert len(text.encode("utf-8")) > CLAUDE_CODE.injection_budget
        (store / "write-policy.md").write_text(text)
        assert read_policy(store, spec=CLAUDE_CODE) == (text, None)

    def test_an_override_between_the_two_budgets_is_labelled_only_on_the_smaller_harness(
        self, tmp_path: Path
    ) -> None:
        """The whole reason this is a parameter. One file, two harnesses, opposite answers: a
        policy well inside kiro's budget overruns Claude Code's by more than sixfold, and a single
        hard-coded figure would necessarily be wrong for one of them.
        """
        store = tmp_path / ".zikaron"
        store.mkdir(mode=0o700)
        store.chmod(0o700)
        between = "x" * (CLAUDE_CODE.injection_budget + 1)
        assert len(between.encode("utf-8")) < KIRO.injection_budget
        (store / "write-policy.md").write_text(between)
        assert read_policy(store, spec=KIRO) == (between, None)
        assert read_policy(store, spec=CLAUDE_CODE) == (between, OVERRIDE_OVERSIZE)

    def test_the_shipped_policy_fits_every_supported_harness(self) -> None:
        """The constant this module falls back to is the one text guaranteed to be injected, so it
        must fit under every harness rather than only the one with the larger budget.
        """
        for spec in (KIRO, CLAUDE_CODE):
            assert not spec.exceeds_injection_budget(WRITE_POLICY_PROMPT)
