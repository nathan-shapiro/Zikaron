"""Which documented modules a search reached, and the line that reminds the agent of them.

`design/code-knowledge.md` §6 is normative. A module's corpus is registered as
`code-knowledge/<module>`, or as `code-knowledge` for the root module `.`, and a search reached
module M when a path it searched is M or lies under it, or M lies under a path it searched — so a
search from the project's root reaches every module. Paths are compared lexically, normalized and
absolute, and without regard to case, since a registered name is lower-cased while a search's
path carries the directory's own case; nothing here touches a file.
"""

import os
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath
from typing import Final

#: The name of the root module's corpus, and the prefix of every other module's.
CORPUS_NAME: Final = "code-knowledge"

#: The module the project's own directory is.
ROOT_MODULE: Final = "."

#: How many corpora one line names; the rest are counted.
NAMED_AT_MOST: Final = 5


def module_of(corpus: str) -> str | None:
    """The module a corpus documents, read off its name, or `None` for a corpus no module owns."""
    if corpus == CORPUS_NAME:
        return ROOT_MODULE
    prefix = f"{CORPUS_NAME}/"
    if corpus.startswith(prefix) and len(corpus) > len(prefix):
        return corpus.removeprefix(prefix)
    return None


def corpora_reached(
    searched: Iterable[str], *, project: str, corpora: Iterable[str]
) -> tuple[str, ...]:
    """The code-knowledge corpora among `corpora` whose module a search of `searched` reached —
    the deepest module first, then by name, so the most specific comes first.

    `searched` and `project` are absolute paths.
    """
    paths = [_normalized(path) for path in searched]
    reached: list[tuple[int, str, str]] = []
    for corpus in corpora:
        module = module_of(corpus)
        if module is None:
            continue
        root = _normalized(str(PurePosixPath(project) / module))
        if any(path.is_relative_to(root) or root.is_relative_to(path) for path in paths):
            reached.append((-len(PurePosixPath(module).parts), module, corpus))
    return tuple(corpus for _, _, corpus in sorted(reached))


def reminder_text(corpora: Sequence[str]) -> str | None:
    """The one line for a search that reached `corpora`, in their order, or `None` for none.

    A statement rather than an instruction, opening with where it comes from: text framed as an
    out-of-band instruction can trip a model's injection defenses, and this line arrives with no
    start text to explain it (`research/claude-code-tool-hooks-docs.md` §3.3). A registered name
    keeps its whitespace, so each name's runs of it are folded to one space to keep the line one.
    """
    if not corpora:
        return None
    named = [" ".join(corpus.split()) for corpus in corpora[:NAMED_AT_MOST]]
    more = len(corpora) - len(named)
    listed = ", ".join(named) + (f" and {more} more" if more else "")
    noun = "knowledge base" if len(corpora) == 1 else "knowledge bases"
    return (
        f"Zikaron hook: code this search covered is documented in the {noun} {listed}. "
        "zikaron_knowledge_search there finds what a file is for and what it depends on, "
        "as a lead to check against the code."
    )


def _normalized(path: str) -> PurePosixPath:
    return PurePosixPath(os.path.normpath(path).lower())
