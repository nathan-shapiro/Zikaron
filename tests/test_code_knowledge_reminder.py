"""Which documented modules a search reached, and the reminder line.

`design/code-knowledge.md` §6 is normative.
"""

import pytest

from zikaron.core.code_knowledge.reminder import (
    CORPUS_NAME,
    ROOT_MODULE,
    corpora_reached,
    module_of,
    reminder_text,
)
from zikaron.install.assets import identity_vocabulary
from zikaron.install.code_knowledge import (
    CLAUDE_CODE_ORCHESTRATOR_PROMPT,
    CLAUDE_CODE_PLANNER_COMMAND,
    orchestrator_prompt,
)

PROJECT = "/work/project"


def _reached(*searched: str, corpora: tuple[str, ...]) -> tuple[str, ...]:
    return corpora_reached(searched, project=PROJECT, corpora=corpora)


class TestModuleOf:
    def test_a_module_s_corpus_names_its_module(self) -> None:
        assert module_of("code-knowledge/app/src/terminal") == "app/src/terminal"

    def test_the_bare_name_is_the_root_module(self) -> None:
        assert module_of(CORPUS_NAME) == ROOT_MODULE

    @pytest.mark.parametrize("name", ["docs", "code-knowledge/", "code-knowledgeable", "notes/x"])
    def test_any_other_corpus_is_no_module_s(self, name: str) -> None:
        assert module_of(name) is None


class TestTheMatchingTable:
    """A search reaches M when a path searched is M or lies under it, or M lies under it."""

    CORPORA = ("code-knowledge/src/a", "code-knowledge/src/b", "docs")

    def test_a_search_of_the_module_itself(self) -> None:
        assert _reached(f"{PROJECT}/src/a", corpora=self.CORPORA) == ("code-knowledge/src/a",)

    def test_a_search_under_the_module(self) -> None:
        reached = _reached(f"{PROJECT}/src/a/deep/x.rs", corpora=self.CORPORA)
        assert reached == ("code-knowledge/src/a",)

    def test_a_search_above_the_module_reaches_every_module_under_it(self) -> None:
        reached = _reached(f"{PROJECT}/src", corpora=self.CORPORA)
        assert reached == ("code-knowledge/src/a", "code-knowledge/src/b")

    def test_a_search_from_the_project_root_reaches_every_module(self) -> None:
        assert _reached(PROJECT, corpora=self.CORPORA) == (
            "code-knowledge/src/a",
            "code-knowledge/src/b",
        )

    def test_a_search_beside_the_module_reaches_nothing(self) -> None:
        assert _reached(f"{PROJECT}/src/c", corpora=self.CORPORA) == ()

    def test_a_sibling_sharing_a_prefix_is_beside_not_under(self) -> None:
        assert _reached(f"{PROJECT}/src/abc", corpora=self.CORPORA) == ()

    def test_a_search_spanning_two_modules_reaches_both(self) -> None:
        reached = _reached(f"{PROJECT}/src/a/x", f"{PROJECT}/src/b/y", corpora=self.CORPORA)
        assert reached == ("code-knowledge/src/a", "code-knowledge/src/b")

    def test_the_root_module_is_reached_by_every_search_inside_the_project(self) -> None:
        reached = _reached(f"{PROJECT}/anything/at/all", corpora=(CORPUS_NAME,))
        assert reached == (CORPUS_NAME,)

    def test_the_root_module_is_not_reached_from_outside_the_project(self) -> None:
        assert _reached("/elsewhere", corpora=(CORPUS_NAME,)) == ()

    def test_paths_are_compared_after_normalizing(self) -> None:
        assert _reached(f"{PROJECT}/src/b/../a/./x", corpora=self.CORPORA) == (
            "code-knowledge/src/a",
        )

    def test_a_module_s_case_is_not_compared(self) -> None:
        """The registry lower-cases a corpus's name, while the hook sends a path as written."""
        corpora = ("code-knowledge/src/components",)
        assert _reached(f"{PROJECT}/src/Components/x.tsx", corpora=corpora) == corpora
        assert _reached("/Work/Project/src/Components", corpora=corpora) == corpora

    def test_a_path_that_does_not_exist_still_lies_where_it_says(self) -> None:
        assert _reached(f"{PROJECT}/src/a/*.rs", corpora=self.CORPORA) == ("code-knowledge/src/a",)

    def test_a_hand_written_corpus_is_never_reached(self) -> None:
        assert _reached(PROJECT, corpora=("docs",)) == ()


class TestOrder:
    def test_the_deepest_module_comes_first_then_by_name(self) -> None:
        corpora = (
            "code-knowledge/src",
            CORPUS_NAME,
            "code-knowledge/src/b",
            "code-knowledge/src/a",
        )
        assert _reached(f"{PROJECT}/src/a/x", f"{PROJECT}/src/b/y", corpora=corpora) == (
            "code-knowledge/src/a",
            "code-knowledge/src/b",
            "code-knowledge/src",
            CORPUS_NAME,
        )

    def test_the_order_does_not_follow_the_registry_s(self) -> None:
        corpora = ("code-knowledge/src/b", "code-knowledge/src/a")
        assert _reached(PROJECT, corpora=corpora) == _reached(PROJECT, corpora=corpora[::-1])


class TestTheLine:
    def test_nothing_reached_is_no_line(self) -> None:
        assert reminder_text(()) is None

    def test_one_corpus_is_named_in_the_singular(self) -> None:
        line = reminder_text(("code-knowledge/src",))
        assert line is not None
        assert "the knowledge base code-knowledge/src." in line
        assert "zikaron_knowledge_search" in line

    def test_two_are_named_in_the_plural(self) -> None:
        line = reminder_text(("code-knowledge/a", "code-knowledge/b"))
        assert line is not None
        assert "the knowledge bases code-knowledge/a, code-knowledge/b." in line

    def test_it_opens_by_naming_where_it_comes_from(self) -> None:
        line = reminder_text(("code-knowledge/src",))
        assert line is not None
        assert line.startswith("Zikaron hook:")

    def test_six_reached_name_five_and_count_the_sixth(self) -> None:
        corpora = tuple(f"code-knowledge/m{n}" for n in range(6))
        line = reminder_text(corpora)
        assert line is not None
        assert ", ".join(corpora[:5]) + " and 1 more." in line
        assert corpora[5] not in line

    def test_it_is_one_line(self) -> None:
        line = reminder_text(("code-knowledge/a", "code-knowledge/b\nsecond line"))
        assert line is not None
        assert "\n" not in line
        assert "code-knowledge/b second line." in line


def test_the_loop_names_corpora_as_the_reminder_reads_them() -> None:
    """The orchestrator's loop registers each module's corpus; the reminder recognizes a module by
    the name it was registered under, so the two must spell it alike."""
    loop = orchestrator_prompt(
        identity_vocabulary(),
        own_prompt=CLAUDE_CODE_ORCHESTRATOR_PROMPT,
        spawn_instruction="",
        planner_command=CLAUDE_CODE_PLANNER_COMMAND,
    )
    assert (
        f"`{CORPUS_NAME}/<module>`, or `{CORPUS_NAME}` when `<module>` is `{ROOT_MODULE}`"
        in " ".join(loop.split())
    )
