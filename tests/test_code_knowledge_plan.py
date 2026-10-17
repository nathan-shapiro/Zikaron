"""The planner's decisions, from a module's sources and documents alone — no repository, no files.

`design/code-knowledge.md` §3.4 to §3.6 and §4 are normative. Every class a document can be in, and
every removal, move and work item that follows from it, is reached here through `Survey`, which is
everything the planner judges; `test_code_knowledge_command.py` covers the walk, git and the disk.
"""

from collections.abc import Mapping, Sequence

import pytest

from zikaron.core.code_knowledge import readme
from zikaron.core.code_knowledge.document import (
    SECTION_HEADINGS,
    Defect,
    Document,
    front_matter,
    relinked,
    title,
)
from zikaron.core.code_knowledge.layout import Layout, path_order
from zikaron.core.code_knowledge.plan import (
    DocumentClass,
    DocumentedFile,
    ForeignFile,
    Move,
    Plan,
    Survey,
    UnverifiableSource,
    WorkKind,
    judge,
    plan,
)
from zikaron.core.knowledge.source_hash import Hashed, SourceState

LAYOUT = Layout(documents="code-knowledge", module="mod")

A = "mod/a.scala"
B = "mod/b.scala"
C = "mod/c.scala"
HASH_A = "a" * 40
HASH_B = "b" * 40
HASH_C = "c" * 40
OTHER = "f" * 40


def document(
    source: str,
    blob: str,
    *,
    heading: str | None = None,
    role: str = "What this file is for.",
    headings: Sequence[str] = SECTION_HEADINGS,
) -> str:
    """A document as §4 lays it out, with any one part replaceable."""
    sections = "".join(f"## {name}\nSomething.\n\n" for name in headings)
    named = title(source) if heading is None else heading
    return f"{front_matter(source, blob)}{named}\n\n{role}\n\n{sections}"


def with_block(text: str, block: str) -> str:
    """`text` with its front-matter block replaced by `block`."""
    return block + text.split("---\n", 2)[2]


def doc_path(source: str) -> str:
    return LAYOUT.document_for(source)


def survey(
    sources: Mapping[str, Hashed],
    documents: Mapping[str, str | None] | None = None,
    *,
    readme_text: str | None = None,
    readme_present: bool | None = None,
) -> Survey:
    return Survey(
        layout=LAYOUT,
        sources=sources,
        documents={} if documents is None else documents,
        readme=readme_text,
        readme_present=readme_text is not None if readme_present is None else readme_present,
    )


def current_readme(hashes: Mapping[str, str]) -> str:
    return (
        f"{readme.front_matter(readme.module_digest(hashes))}# `mod`\n\nOverview.\n\n"
        "## How its parts relate\n\nText.\n"
    )


def work(result: Plan) -> list[tuple[WorkKind, str, Defect | None]]:
    return [(item.kind, item.source, item.defect) for item in result.work]


class TestEachClassFromADocumentsTextAlone:
    def test_a_document_with_no_link_is_foreign(self) -> None:
        found = survey({A: HASH_A}, {doc_path(A): "# Notes written by hand\n"})
        assert judge(found, doc_path(A)).document_class is DocumentClass.FOREIGN

    def test_a_document_that_could_not_be_read_is_foreign(self) -> None:
        found = survey({A: HASH_A}, {doc_path(A): None})
        assert judge(found, doc_path(A)).document_class is DocumentClass.FOREIGN

    def test_a_link_naming_another_source_is_invalid(self) -> None:
        found = survey({A: HASH_A, B: HASH_B}, {doc_path(A): document(B, HASH_B)})
        verdict = judge(found, doc_path(A))
        assert (verdict.document_class, verdict.defect) == (
            DocumentClass.INVALID,
            Defect.WRONG_SOURCE,
        )

    def test_a_malformed_link_is_invalid(self) -> None:
        malformed = f"---\nzikaron-source: {A}\n---\n"
        found = survey({A: HASH_A}, {doc_path(A): with_block(document(A, HASH_A), malformed)})
        assert judge(found, doc_path(A)).defect is Defect.MALFORMED_LINK

    @pytest.mark.parametrize("heading", ["# Foo", f"# {A}", "", f"## `{A}`"])
    def test_a_missing_title_is_invalid(self, heading: str) -> None:
        found = survey({A: HASH_A}, {doc_path(A): document(A, HASH_A, heading=heading)})
        assert judge(found, doc_path(A)).defect is Defect.NO_TITLE

    def test_a_document_with_nothing_after_its_front_matter_is_invalid(self) -> None:
        found = survey({A: HASH_A}, {doc_path(A): front_matter(A, HASH_A)})
        assert judge(found, doc_path(A)).defect is Defect.NO_TITLE

    def test_a_missing_role_line_is_invalid(self) -> None:
        found = survey({A: HASH_A}, {doc_path(A): document(A, HASH_A, role="")})
        assert judge(found, doc_path(A)).defect is Defect.NO_ROLE_LINE

    @pytest.mark.parametrize("missing", SECTION_HEADINGS)
    def test_a_missing_heading_is_invalid(self, missing: str) -> None:
        headings = [name for name in SECTION_HEADINGS if name != missing]
        found = survey({A: HASH_A}, {doc_path(A): document(A, HASH_A, headings=headings)})
        assert judge(found, doc_path(A)).defect is Defect.MISSING_HEADING

    def test_a_wrong_blob_is_stale(self) -> None:
        found = survey({A: HASH_A}, {doc_path(A): document(A, OTHER)})
        assert judge(found, doc_path(A)).document_class is DocumentClass.STALE

    def test_a_blob_of_the_wrong_width_is_stale(self) -> None:
        found = survey({A: HASH_A}, {doc_path(A): document(A, "a" * 64)})
        assert judge(found, doc_path(A)).document_class is DocumentClass.STALE

    def test_a_well_formed_current_document_is_fresh(self) -> None:
        found = survey({A: HASH_A}, {doc_path(A): document(A, HASH_A)})
        assert judge(found, doc_path(A)).document_class is DocumentClass.FRESH

    def test_a_linked_document_whose_location_derives_no_source_is_orphaned(self) -> None:
        found = survey({A: HASH_A}, {doc_path(B): document(B, HASH_B)})
        assert judge(found, doc_path(B)).document_class is DocumentClass.ORPHANED

    @pytest.mark.parametrize("state", [SourceState.MISSING, SourceState.UNVERIFIABLE])
    def test_a_document_whose_source_has_no_hash_is_unverified(self, state: SourceState) -> None:
        found = survey({A: state}, {doc_path(A): document(A, HASH_A, role="")})
        assert judge(found, doc_path(A)).document_class is DocumentClass.UNVERIFIED

    def test_a_source_with_no_document_is_missing(self) -> None:
        assert work(plan(survey({A: HASH_A}))) == [(WorkKind.MISSING, A, None)]


class TestWorkItems:
    def test_each_item_carries_its_document_path_and_its_block_at_the_hash_now(self) -> None:
        (item,) = plan(survey({A: HASH_A}, {doc_path(A): document(A, OTHER)})).work
        assert item.document == "code-knowledge/mod/a.scala.md"
        assert (
            item.front_matter == f"---\nzikaron-source: {A}\nzikaron-source-blob: {HASH_A}\n---\n"
        )

    def test_work_is_in_byte_order_of_the_root_relative_path(self) -> None:
        sources: dict[str, Hashed] = {"mod/b": HASH_B, "mod/B": HASH_B, "mod/a/z": HASH_A}
        listed = [item.source for item in plan(survey(sources)).work]
        assert listed == ["mod/B", "mod/a/z", "mod/b"]
        assert listed == sorted(listed, key=path_order)

    def test_an_invalid_item_names_its_reason(self) -> None:
        found = survey({A: HASH_A}, {doc_path(A): document(A, HASH_A, role="")})
        assert work(plan(found)) == [(WorkKind.INVALID, A, Defect.NO_ROLE_LINE)]

    def test_limit_holds_back_the_rest_and_counts_it(self) -> None:
        result = plan(survey({A: HASH_A, B: HASH_B, C: HASH_C}), limit=2)
        assert [item.source for item in result.work] == [A, B]
        assert result.remaining == 1

    def test_limit_bounds_the_removal_of_documents_to_rewrite_and_nothing_else(self) -> None:
        documents = {
            doc_path(A): document(A, OTHER),
            doc_path(B): document(B, HASH_B, role=""),
            doc_path(C): document(C, OTHER),
            "code-knowledge/mod/gone.scala.md": document("mod/gone.scala", OTHER),
        }
        result = plan(survey({A: HASH_A, B: HASH_B, C: HASH_C}, documents), limit=1)
        assert result.removals == (doc_path(A), "code-knowledge/mod/gone.scala.md")

    def test_a_source_named_readme_at_the_module_top_is_unplaceable(self) -> None:
        result = plan(survey({"mod/README": HASH_A, "mod/sub/README": HASH_B}))
        assert result.unplaceable == ("mod/README",)
        assert [item.source for item in result.work] == ["mod/sub/README"]

    def test_the_same_survey_plans_identically(self) -> None:
        documents = {doc_path(A): document(A, OTHER), doc_path(B): "hand\n"}
        found = survey({A: HASH_A, B: HASH_B, C: SourceState.MISSING}, documents)
        assert plan(found, limit=1) == plan(found, limit=1)


class TestNothingWithoutALinkIsTouched:
    def test_a_foreign_file_is_reported_and_neither_removed_nor_moved(self) -> None:
        documents = {"code-knowledge/mod/notes.md": "written by hand\n"}
        result = plan(survey({A: HASH_A}, documents))
        assert result.foreign == (ForeignFile("code-knowledge/mod/notes.md", None),)
        assert "code-knowledge/mod/notes.md" not in result.removals
        assert result.moves == ()

    def test_a_foreign_file_survives_a_module_with_no_sources_at_all(self) -> None:
        documents = {doc_path(A): f"hand-written, blob {HASH_A}\n"}
        result = plan(survey({}, documents))
        assert result.removals == ()
        assert result.moves == ()

    def test_a_source_whose_document_path_holds_a_foreign_file_is_reported_not_listed(
        self,
    ) -> None:
        result = plan(survey({A: HASH_A}, {doc_path(A): "hand-written\n"}))
        assert result.work == ()
        assert result.foreign == (ForeignFile(doc_path(A), A),)
        assert result.up_to_date(applied=True) is False  # the README is still owed
        assert result.readme is not None


class TestUnverifiableSources:
    @pytest.mark.parametrize("state", [SourceState.MISSING, SourceState.UNVERIFIABLE])
    def test_its_document_is_neither_listed_nor_touched_and_it_is_reported(
        self, state: SourceState
    ) -> None:
        result = plan(survey({A: state}, {doc_path(A): document(A, OTHER, headings=())}))
        assert result.work == ()
        assert result.removals == ()
        assert result.unverifiable == (UnverifiableSource(A, state),)

    def test_a_source_with_no_hash_and_no_document_is_not_listed(self) -> None:
        result = plan(survey({A: SourceState.UNVERIFIABLE}))
        assert result.work == ()


class TestMoves:
    def test_a_pure_rename_moves_the_document_and_lists_no_work_for_its_source(self) -> None:
        result = plan(survey({B: HASH_A}, {doc_path(A): document(A, HASH_A)}))
        assert result.moves == (Move(origin=doc_path(A), target=doc_path(B), source=B),)
        assert result.work == ()
        assert result.removals == ()

    def test_an_orphan_matching_two_undocumented_sources_is_removed(self) -> None:
        result = plan(survey({B: HASH_A, C: HASH_A}, {doc_path(A): document(A, HASH_A)}))
        assert result.moves == ()
        assert result.removals == (doc_path(A),)

    def test_two_orphans_matching_one_source_are_both_removed(self) -> None:
        documents = {
            doc_path(A): document(A, HASH_C),
            doc_path(B): document(B, HASH_C),
        }
        result = plan(survey({C: HASH_C}, documents))
        assert result.moves == ()
        assert result.removals == (doc_path(A), doc_path(B))
        assert work(result) == [(WorkKind.MISSING, C, None)]

    def test_a_source_already_documented_is_not_a_target(self) -> None:
        documents = {doc_path(A): document(A, HASH_B), doc_path(B): document(B, OTHER)}
        result = plan(survey({B: HASH_B}, documents))
        assert result.moves == ()
        assert result.removals == (doc_path(A), doc_path(B))

    def test_a_move_never_lands_on_a_foreign_file(self) -> None:
        documents = {doc_path(A): document(A, HASH_A), doc_path(B): "hand-written\n"}
        result = plan(survey({B: HASH_A}, documents))
        assert result.moves == ()
        assert result.removals == (doc_path(A),)
        assert result.foreign == (ForeignFile(doc_path(B), B),)
        assert result.work == ()

    def test_an_orphan_that_is_not_well_formed_is_removed_rather_than_moved(self) -> None:
        documents = {doc_path(A): document(A, HASH_A, headings=SECTION_HEADINGS[:3])}
        result = plan(survey({B: HASH_A}, documents))
        assert result.moves == ()
        assert work(result) == [(WorkKind.MISSING, B, None)]

    def test_an_orphan_with_a_malformed_link_is_removed(self) -> None:
        malformed = "---\nzikaron-source-blob: " + HASH_A + "\n---\n"
        malformed_document = with_block(document(A, HASH_A), malformed)
        result = plan(survey({B: HASH_A}, {doc_path(A): malformed_document}))
        assert result.moves == ()
        assert result.removals == (doc_path(A),)

    def test_a_document_written_at_another_sources_path_is_invalid_there(self) -> None:
        result = plan(survey({A: HASH_A, B: HASH_B}, {doc_path(A): document(B, HASH_B)}))
        assert work(result) == [
            (WorkKind.INVALID, A, Defect.WRONG_SOURCE),
            (WorkKind.MISSING, B, None),
        ]

    def test_a_document_written_where_no_source_derives_moves_to_its_own(self) -> None:
        misplaced = "code-knowledge/mod/elsewhere/a.scala.md"
        result = plan(survey({A: HASH_A}, {misplaced: document(A, HASH_A)}))
        assert result.moves == (Move(origin=misplaced, target=doc_path(A), source=A),)
        assert result.work == ()


class TestTheReadme:
    def test_it_waits_while_any_file_work_remains(self) -> None:
        assert plan(survey({A: HASH_A})).readme is None

    def test_it_waits_for_work_held_back_by_the_limit(self) -> None:
        documents = {doc_path(A): document(A, HASH_A)}
        assert plan(survey({A: HASH_A, B: HASH_B}, documents), limit=0).readme is None

    def test_it_waits_for_an_unverifiable_source(self) -> None:
        documents = {doc_path(A): document(A, HASH_A)}
        assert plan(survey({A: HASH_A, B: SourceState.MISSING}, documents)).readme is None

    def test_it_is_listed_once_every_document_is_fresh_with_every_role_line(self) -> None:
        documents = {doc_path(A): document(A, HASH_A, role="Reads quotes.\nAnd writes them.")}
        item = plan(survey({A: HASH_A}, documents)).readme
        assert item is not None
        assert item.document == "code-knowledge/mod/README.md"
        assert item.documents == "code-knowledge"
        assert item.files == (DocumentedFile(A, "Reads quotes. And writes them."),)
        assert item.front_matter == readme.front_matter(readme.module_digest({A: HASH_A}))

    def test_files_lists_only_fresh_documents_and_what_a_move_supplies(self) -> None:
        documents = {
            doc_path(A): document(A, HASH_A, role="Is a."),
            "code-knowledge/mod/old.scala.md": document("mod/old.scala", HASH_B, role="Is b."),
            doc_path(C): "hand-written\n",
        }
        item = plan(survey({A: HASH_A, B: HASH_B, C: HASH_C}, documents)).readme
        assert item is not None
        assert item.files == (DocumentedFile(A, "Is a."), DocumentedFile(B, "Is b."))

    def test_its_role_lines_are_in_byte_order_of_the_root_relative_path(self) -> None:
        """The README's documenter samples a long list across it, which covers the module's
        directories only because the list is in path order (§3.6)."""
        sources: dict[str, Hashed] = {"mod/b": HASH_B, "mod/B": HASH_B, "mod/a/z": HASH_A}
        documents = {
            doc_path(source): document(source, hashed) for source, hashed in sources.items()
        }
        item = plan(survey(sources, documents)).readme
        assert item is not None
        assert [file.source for file in item.files] == ["mod/B", "mod/a/z", "mod/b"]

    def test_a_current_readme_is_not_listed(self) -> None:
        documents = {doc_path(A): document(A, HASH_A)}
        result = plan(survey({A: HASH_A}, documents, readme_text=current_readme({A: HASH_A})))
        assert result.readme is None
        assert result.up_to_date(applied=False) is True

    def test_it_is_listed_again_when_a_source_hash_moves(self) -> None:
        documents = {doc_path(A): document(A, HASH_B)}
        result = plan(survey({A: HASH_B}, documents, readme_text=current_readme({A: HASH_A})))
        assert result.readme is not None

    def test_it_is_listed_again_when_a_source_path_moves(self) -> None:
        documents = {doc_path(A): document(A, HASH_A)}
        result = plan(survey({B: HASH_A}, documents, readme_text=current_readme({A: HASH_A})))
        assert result.moves != ()
        assert result.readme is not None

    def test_a_readme_that_lists_its_files_is_listed(self) -> None:
        listing = current_readme({A: HASH_A}) + "\n## Files\n\n- `mod/a.scala` — Is a.\n"
        documents = {doc_path(A): document(A, HASH_A)}
        assert plan(survey({A: HASH_A}, documents, readme_text=listing)).readme is not None

    @pytest.mark.parametrize(
        "untitled",
        [
            current_readme({A: HASH_A}).replace("# `mod`\n", ""),
            readme.front_matter(readme.module_digest({A: HASH_A})) + "Overview.\n\n# `mod`\n",
            readme.front_matter(readme.module_digest({A: HASH_A})) + "## `mod`\n\nOverview.\n",
        ],
        ids=["no title", "title after the overview", "a ## line first"],
    )
    def test_a_readme_without_a_title_first_is_listed(self, untitled: str) -> None:
        documents = {doc_path(A): document(A, HASH_A)}
        assert plan(survey({A: HASH_A}, documents, readme_text=untitled)).readme is not None

    def test_a_readme_written_by_hand_is_listed_and_removed_under_apply(self) -> None:
        documents = {doc_path(A): document(A, HASH_A)}
        result = plan(survey({A: HASH_A}, documents, readme_text="# My notes\n"))
        assert result.readme is not None
        assert result.removals == ("code-knowledge/mod/README.md",)

    def test_an_absent_readme_is_listed_and_nothing_is_removed(self) -> None:
        documents = {doc_path(A): document(A, HASH_A)}
        result = plan(survey({A: HASH_A}, documents))
        assert result.readme is not None
        assert result.removals == ()

    def test_an_unreadable_readme_is_listed_and_removed(self) -> None:
        documents = {doc_path(A): document(A, HASH_A)}
        result = plan(survey({A: HASH_A}, documents, readme_present=True))
        assert result.readme is not None
        assert result.removals == ("code-knowledge/mod/README.md",)


class TestUpToDate:
    def test_it_holds_exactly_when_nothing_is_owed(self) -> None:
        documents = {doc_path(A): document(A, HASH_A), doc_path(B): "hand\n"}
        hashes = {A: HASH_A, B: HASH_B, "mod/README": HASH_C}
        result = plan(survey(hashes, documents, readme_text=current_readme(hashes)))
        assert result.up_to_date(applied=False) is True
        assert result.foreign != ()
        assert result.unplaceable != ()

    def test_it_is_false_on_a_run_held_back_by_the_limit(self) -> None:
        result = plan(survey({A: HASH_A}), limit=0)
        assert result.work == ()
        assert result.up_to_date(applied=True) is False

    def test_it_is_false_with_an_unverifiable_source(self) -> None:
        hashes: dict[str, Hashed] = {A: SourceState.UNVERIFIABLE}
        result = plan(survey(hashes, readme_text=current_readme({})))
        assert result.up_to_date(applied=True) is False

    def test_a_dry_run_with_a_removal_still_to_make_is_not_up_to_date(self) -> None:
        hashes = {A: HASH_A}
        documents = {doc_path(A): document(A, HASH_A), doc_path(B): document(B, HASH_B)}
        result = plan(survey(hashes, documents, readme_text=current_readme(hashes)))
        assert result.removals == (doc_path(B),)
        assert result.up_to_date(applied=False) is False
        assert result.up_to_date(applied=True) is True


class TestTheDocumentFormat:
    def test_the_role_line_is_every_non_blank_line_between_title_and_first_heading(self) -> None:
        parsed = Document.parse(document(A, HASH_A, role="One.\n\n  Two.  "))
        assert parsed.role == "One. Two."

    def test_a_heading_needs_exactly_two_marks_and_a_space(self) -> None:
        text = document(A, HASH_A, headings=()) + "###  Purpose\n##Declarations\n## Behavior  \n"
        assert Document.parse(text).headings == frozenset({"Behavior"})

    def test_carriage_returns_are_read_through(self) -> None:
        text = document(A, HASH_A).replace("\n", "\r\n")
        found = survey({A: HASH_A}, {doc_path(A): text})
        assert judge(found, doc_path(A)).document_class is DocumentClass.FRESH

    def test_relinked_changes_the_source_line_and_the_title_and_nothing_else(self) -> None:
        original = document(A, HASH_A).replace("\n", "\r\n", 3) + "a.scala again\n"
        moved = relinked(original, B)
        assert moved.split("\n")[1] == f"zikaron-source: {B}\r"
        assert Document.parse(moved).defect(B) is None
        assert moved.replace(B, A) == original

    @pytest.mark.parametrize("text", ["no front matter\n", front_matter(A, HASH_A)])
    def test_relinked_refuses_a_document_it_could_not_have_judged_movable(self, text: str) -> None:
        with pytest.raises(ValueError, match="relinked needs"):
            relinked(text, B)


class TestTheModuleDigest:
    def test_it_is_independent_of_the_order_sources_arrive_in(self) -> None:
        forward = readme.module_digest({A: HASH_A, B: HASH_B})
        assert forward == readme.module_digest({B: HASH_B, A: HASH_A})

    def test_it_moves_with_a_path_or_a_hash(self) -> None:
        digest = readme.module_digest({A: HASH_A})
        assert digest != readme.module_digest({B: HASH_A})
        assert digest != readme.module_digest({A: HASH_B})

    @pytest.mark.parametrize(
        "text",
        [
            "# no front matter\n",
            "---\nzikaron-module-digest: x\n---\n# `mod`\n",
            "---\nunclosed\n# `mod`\n",
        ],
    )
    def test_a_readme_without_the_digest_is_not_current(self, text: str) -> None:
        assert readme.is_current(text, readme.module_digest({})) is False

    def test_a_digest_given_twice_is_not_current(self) -> None:
        digest = readme.module_digest({})
        text = f"---\nzikaron-module-digest: {digest}\nzikaron-module-digest: {digest}\n---\n"
        assert readme.is_current(text + "# `mod`\n", digest) is False

    def test_the_role_list_is_one_line_per_file_in_the_items_order(self) -> None:
        listed = readme.roles([(B, "Is b."), (A, "Is a.")])
        assert listed == f"- `{B}` — Is b.\n- `{A}` — Is a.\n"
