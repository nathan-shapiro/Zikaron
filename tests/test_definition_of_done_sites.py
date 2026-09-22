"""The set of files that state the definition of done, pinned so nobody counts them by hand again.

**This class produced a finding in four consecutive sweep rounds**, and never the same finding
twice: a range that said seven after M28 made it nine; a "correction" to nine that conflated two
different greps; a sentence claiming the phrase-grep returns nine lines when it returned
several times that; and a hit reassigned to the wrong done-when item. Every one was a human counting
`grep` output and writing the total into prose, where the next edit falsified it.

**There are two quantities and confusing them is most of the damage.** This file pins the one that
can be pinned:

- **The phrase set.** Files carrying `additionally required before a milestone lands` verbatim.
  `design/build-plan.md` §M28 done-when 3 nominates a grep for this phrase as *the* count, which
  only works while the set is fixed — so it is fixed here, by name.
- **The rule set.** Files stating the rule in *any* words, which is larger and includes
  `design/distribution.md` §4 and `.github/workflows/check.yml`, neither of which carries the
  phrase. **Not pinned**, because "states the rule in some words" is not mechanically decidable, and
  a guard that pretends otherwise would be the third wrong count rather than the end of them.

So the guard's honest scope is: *the phrase set is exactly these files*. A new site that states the
rule without the phrase is invisible to it, and that is a real limit rather than an oversight — it
is why the phrase is worth keeping verbatim in the first place.
"""

from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parent.parent

#: Assembled from fragments so the *constant* is not a second occurrence of the phrase.
#:
#: **It does not keep this file out of its own grep, and an earlier version of this comment claimed
#: it did.** The module docstring above quotes the phrase verbatim, so this file *is* a hit — which
#: is why it appears in `DISCUSSES_THE_RULE`, and that entry is necessary only because the claim
#: was false. The comparison to `test_publication_hygiene.py` does not carry over either: none of
#: that guard's literals appears anywhere in it. **The honest scope here is that this file filters
#: itself by name**, which is weaker and is the thing a later reader needs to know.
PHRASE: Final = "additionally required " + "before a milestone lands"

#: Every file that must carry `PHRASE`, and no others may. **Written out rather than derived**: a
#: derived set follows whatever the tree does and guards nothing, which is exactly how the
#: `reviews/` exclusion in `test_design_pointers_resolve.py` came to filter an unwalked directory.
PHRASE_SITES: Final = frozenset(
    {
        "CLAUDE.md",
        "README.md",
        "check.sh",
        "check-matrix.sh",
        "design/build-plan.md",
        "design/coding-standards.md",
        ".claude/agents/memory-researcher.md",
        # Added deliberately, and the guard is what forced the decision. The kiro mirror had no
        # gate rule at all — `CLAUDE.md` calls `.kiro/` the fallback if the migration goes badly,
        # and the fallback did not know what "done" means. Carrying the rule across made this an
        # eighth site; the guard reddened rather than letting the set grow unnoticed, which is the
        # whole of what it is for.
        ".kiro/agents/memory-researcher.json",
    }
)

#: Files that may mention the phrase without being sites, because they *discuss* the rule rather
#: than state it. **A file in `PHRASE_SITES` is never filtered by this**, which the first version
#: got wrong: `design/build-plan.md` states the rule in its own header *and* argues at length about
#: how to count the sites, so listing it in both sets made it filter itself out and then report
#: itself missing. A site that talks about itself is still a site.
#:
#: **`FINDINGS-archive.md` is listed pre-emptively and currently filters nothing** — it carries no
#: occurrence of the phrase today, in the tree or at `HEAD`. Kept rather than dropped, because an
#: archive pass moving a live block into it would otherwise turn it into a phantom site overnight;
#: said out loud because an exclusion that silently covers nothing is the exact defect this file's
#: sibling guard was found to have, and "unreachable" has to be a stated property rather than an
#: accident.
DISCUSSES_THE_RULE: Final = frozenset(
    {
        "FINDINGS.md",
        "FINDINGS-archive.md",
        Path(__file__).relative_to(REPO).as_posix(),
    }
)

#: Directories whose contents quote the corpus rather than constituting it. A review round arguing
#: about the phrase is a record of what was believed, not a site that has drifted.
QUOTING_DIRECTORIES: Final = ("reviews/", "research/", "spikes/", "experiments/")

SEARCHED_SUFFIXES: Final = {".md", ".sh", ".yml", ".toml", ".json", ".py"}

#: Matched by **prefix**, not by equality, and that is the whole point. `check-matrix.sh` runs each
#: version with `ZIKARON_CACHE_SUFFIX`, so this tree carries `.mypy_cache.3.12`,
#: `.pytest_cache.3.13`, `.ruff_cache.3.14` and their siblings — three tools, the unsuffixed
#: default plus each of `check-matrix.sh`'s minors, where an exact-match list named three. A cache
#: that ever held the phrase would have been reported as a site that does not exist. **Stated scope
#: against reachable scope, for the third time in this suite**, and the first two were found by
#: review rather than by the guards themselves.
#: *(A count sat here and was wrong — "thirteen", reached only by also counting `.hypothesis`,
#: which no suffix produces and which is its own entry below. A hand-counted total in the comment
#: on the list whose whole subject is that hand-counted totals decay.)*
IGNORED_PREFIXES: Final = (
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
)

#: **`.git` is matched exactly, and that is the whole of this entry's reason.** It was in
#: `IGNORED_PREFIXES` for a day, and `".github".startswith(".git")` is `True` — so **every file
#: under `.github/` was invisible to this guard**, including `.github/workflows/check.yml`, which
#: the module docstring above names as a member of the rule set, and which is a `.yml`,
#: a suffix `SEARCHED_SUFFIXES` explicitly admits.
#:
#: **Stated scope against reachable scope for the fourth time in this suite, and this one was
#: introduced by the fix for the third.** Widening exact matches to prefixes caught the twelve
#: suffixed cache directories and silently swallowed the one directory whose name shares their
#: prefix. A cache directory needs prefix matching because `ZIKARON_CACHE_SUFFIX` appends to its
#: name; `.git` does not, and giving it one bought nothing and cost a whole tree.
IGNORED_EXACTLY: Final = frozenset({"zikaron.egg-info", ".git"})


def _files_carrying_the_phrase() -> set[str]:
    """Every tracked-ish file containing `PHRASE`, as repository-relative paths."""
    found: set[str] = set()
    for path in REPO.rglob("*"):
        if not path.is_file() or path.suffix not in SEARCHED_SUFFIXES:
            continue
        if any(part.startswith(IGNORED_PREFIXES) or part in IGNORED_EXACTLY for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):  # pragma: no cover - binary or unreadable
            continue
        if PHRASE in text:
            found.add(path.relative_to(REPO).as_posix())
    return found


def test_the_phrase_appears_in_exactly_the_files_that_are_meant_to_state_the_rule() -> None:
    """Both directions, because each failed separately in the rounds this file was written after.

    A **missing** site is a definition of done that has quietly stopped saying what CI is and is
    not. An **extra** one is a new file that will be swept up by done-when 3's grep and counted as a
    site, which is how a count starts disagreeing with the list it was derived from.
    """
    carrying = {
        name
        for name in _files_carrying_the_phrase()
        if name in PHRASE_SITES
        or not (name.startswith(QUOTING_DIRECTORIES) or name in DISCUSSES_THE_RULE)
    }
    missing = sorted(PHRASE_SITES - carrying)
    unexpected = sorted(carrying - PHRASE_SITES)
    assert not missing, (
        f"these files should state the rule and no longer carry the phrase: {missing}"
    )
    assert not unexpected, (
        f"these files carry the phrase but are not listed as sites: {unexpected}. "
        "Add them to PHRASE_SITES if they state the rule, or to DISCUSSES_THE_RULE if they only "
        "argue about it."
    )


#: **A second test was written here and deleted before it ever passed**, and the deletion is worth
#: more than the test would have been. It forbade a site from writing down how many sites there
#: are — the defect four rounds kept producing — by searching for `"<number> sites/places/files"`.
#: It fired three times and all three were false: `CLAUDE.md`'s *"survived two sweeps in seven
#: places"* (about a different sweep entirely), `design/coding-standards.md`'s *"five sites"* (about
#: `ResourceWarning` call sites), and — the one worth keeping — **`README.md`'s "POSIX
#: filesystem"**, in which `six files` is a literal substring.
#:
#: **A substring match with no word boundaries, in a guard written to end a class of counting
#: errors.** It could not distinguish the property it named from any other sentence containing the
#: same letters, which is this corpus's own *"can the assertion be satisfied by something other
#: than the property it names?"* — met in the inverse direction, firing on things that are not the
#: property. Deciding whether a count is *about the sites* needs the sentence's subject, which is
#: not cheap and is not mechanical. **The honest scope of this file is the set, not the count.**
