"""Which of the walked files this scan considers part of the corpus, once git has been consulted.

Two narrowings happen here and they are governed by different rules, which is the whole reason
this is one module rather than two steps buried in a scan:

- **The tracked-file intersection decides candidacy**, so a failure of anything it rests on
  degrades the scan to consulting git not at all. A candidate set intersected with a subprocess
  that did not answer is an empty corpus wearing the shape of an answer.
- **The `.gitattributes` exclusion only removes**, and runs after candidacy is settled, so a
  failure there means *attributes unavailable, the sniff governs* — flipping the mode at that
  point would retroactively invalidate a set already computed under another one.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from zikaron.core.knowledge import git, text, walk
from zikaron.core.knowledge.counters import ScanCounters, SkipReason
from zikaron.core.knowledge.meta import GitMode


@dataclass(slots=True)
class GitAnswers:
    """What git said about this tree, and whether it was able to say it.

    `effective` is the mode the scan actually ran under, which may be weaker than the configured
    one. Every collection is empty under `off`, which is the same thing as the rule each one
    carries not being applied at all.
    """

    effective: GitMode
    listed: Mapping[str, str] = field(default_factory=dict)
    reported_changed: frozenset[str] = frozenset()
    ignored: frozenset[str] = frozenset()
    attributes_available: bool = True


async def gather(root: Path, probed: GitMode, found: Sequence[walk.Candidate]) -> GitAnswers:
    """What git says about this tree, or the answer that it could not be asked.

    **Any failure of a call that decides candidacy degrades the whole scan to consulting git not
    at all**, and every git-derived answer is discarded with it. Stated over failure in general
    rather than over a list of causes: the common modern cause — a dubious-ownership refusal
    inside a container — is not one anybody enumerates, and the outcomes nobody enumerates are
    exactly the ones a list would misclassify as answers.

    Args:
        root: the corpus root.
        probed: the mode a work-tree probe already established, which is `off` outside one.
        found: every walked candidate, before any filter. The ignore question is asked about all
            of them because ignoring is the first rule applied, so a file that is both ignored and
            over the size cap is reported as ignored.
    """
    if probed is GitMode.OFF:
        return GitAnswers(effective=GitMode.OFF)
    try:
        listed = await git.list_files(root)
        reported = await git.changed_paths(root)
        ignored: frozenset[str] = frozenset()
        if probed is GitMode.ALL:
            ignored = await git.ignored_paths(root, [candidate.path for candidate in found])
    except git.GitUnavailableError:
        return GitAnswers(effective=GitMode.OFF)
    return GitAnswers(effective=probed, listed=listed, reported_changed=reported, ignored=ignored)


def _tracked_only(admitted: Sequence[walk.Candidate], answers: GitAnswers) -> list[walk.Candidate]:
    """The candidates git tracks, when the corpus asked for only those.

    A file the walk found and git does not track is **seen and outside the corpus without being
    skipped**: no skip reason describes it, and inventing one would put a value on a reported
    table that the schema does not carry. What explains its absence is the mode, which a status
    report gives beside the counts.
    """
    if answers.effective is not GitMode.TRACKED:
        return list(admitted)
    return [candidate for candidate in admitted if candidate.path in answers.listed]


async def _without_attribute_binaries(
    root: Path,
    admitted: Sequence[walk.Candidate],
    answers: GitAnswers,
    counters: ScanCounters,
) -> list[walk.Candidate]:
    """Drop the candidates the repository's own attributes call binary.

    Asked about **every** admitted candidate, including those git already cleared as unchanged.
    That is the non-obvious half: marking an unchanged file binary in `.gitattributes` leaves its
    own blob hash untouched, so a batch run only over the files being read this scan would never
    discover the exclusion — and the answer comes from the working tree, so an uncommitted edit to
    `.gitattributes` changes the corpus with no file change to notice it by.

    A failure is recorded on `answers` rather than raised or degraded, because this call cannot
    change what is a candidate — only which candidates survive.
    """
    if answers.effective is GitMode.OFF or not admitted:
        return list(admitted)
    try:
        attributes = await git.attributes(
            root, [candidate.path for candidate in admitted], text.ATTRIBUTES
        )
    except git.GitUnavailableError:
        answers.attributes_available = False
        return list(admitted)
    kept: list[walk.Candidate] = []
    for candidate in admitted:
        if text.excluded_by_attributes(attributes.get(candidate.path, {})):
            counters.skip(SkipReason.BINARY)
        else:
            kept.append(candidate)
    return kept


async def narrow(
    root: Path,
    admitted: Sequence[walk.Candidate],
    answers: GitAnswers,
    counters: ScanCounters,
) -> list[walk.Candidate]:
    """Everything git removes from what the walk admitted, in the order the rules apply.

    The intersection first, because it decides membership; the attribute exclusion second, over
    whatever survived, because asking about files that are not candidates would spend a subprocess
    on answers nobody reads.
    """
    return await _without_attribute_binaries(
        root, _tracked_only(admitted, answers), answers, counters
    )
