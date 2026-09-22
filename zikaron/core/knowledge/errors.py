"""What a knowledge-base lifecycle call refuses, and why.

Deliberately **not** `ZikaronError`. That type carries the numeric codes two independently written
clients agree on over the wire; these classes are the **lifecycle** refusals, raised down in `core`
where no wire shape exists yet.

The boundary that gives them codes is `service/dispatch_knowledge.py`, and it does so on the
exception's **type** — `KNOWLEDGE_BASE_UNKNOWN`, `_EXISTS`, `_BUSY` and `_CONFIRM_REQUIRED` are
the four a caller can branch on. Raising `ZikaronError` here instead would put the wire contract
in the layer that cannot know whether it is being reached over one.

One class per refusal rather than one class with a reason field. Each carries a message naming
what to do about it, which is what the command prints, and the split is what lets the caller that
does branch — the tool surface, which maps refusals onto wire codes — do so on the **type** rather
than by matching prose, so a message may be reworded without silently changing which branch it
takes.

**Four of them carry the value the refusal is about, as a field, and that is the same argument one
level down.** A wire payload states things like *which path*, *which key*, *which holder*; filling
one of those from `str(error)` puts a whole sentence where a client expects a value, and then the
message cannot be reworded after all — it has become the contract. So the refusal carries both: the
sentence for whoever prints it, and the value for whoever has to name it.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zikaron.core.knowledge.lock import LockHolder


class KnowledgeError(Exception):
    """A knowledge-base operation could not proceed, with a message written for its caller."""


class DuplicateNameError(KnowledgeError):
    """A knowledge base with that name is already registered.

    Never an upsert: silently reconfiguring a corpus underneath whoever created it is worse than
    a failed call, so the way to change a knowledge base's configuration is to remove and re-add
    it. Renaming, which touches no file, is the cheap operation.
    """


class UnknownKnowledgeBaseError(KnowledgeError):
    """No knowledge base is registered under that name."""


class InvalidNameError(KnowledgeError):
    """A name that is empty, or blank once whitespace is discounted.

    The *only* constraint on a name. Names are free-form because none of one ever reaches a
    filesystem path, so there is no grammar to satisfy — but a name has to be something a caller
    can ask for again, and the empty string is not.

    `value` is the string that was refused, and it is carried because more than one parameter of a
    single call can be a name: a rename takes the corpus's current one and its new one, and a
    caller told only *a name was blank* cannot tell which of the two to resend. Whoever answers
    that caller matches this against the names it was given and reports the parameter it arrived
    under.
    """

    def __init__(self, message: str, *, value: str) -> None:
        super().__init__(message)
        self.value = value


class InvalidRootError(KnowledgeError):
    """The corpus root is absent, is not a directory, or is a root a corpus should not have.

    The root is the one caller-supplied string in this system with any path semantics at all, and
    it is validated rather than refused outright: indexing a docs tree or a vendored dependency
    outside the project is a legitimate use.

    `path` is the value that was refused — **as resolved**, which is the one a caller needs to see:
    a relative path refused for not existing is most usefully reported against the directory it
    actually resolved to. The exception is a path there is no resolved form of, a `~` prefix naming
    no home directory this machine knows; that one is reported as supplied, since expansion is
    where it stopped.
    """

    def __init__(self, message: str, *, path: Path) -> None:
        super().__init__(message)
        self.path = path


@dataclass(frozen=True, slots=True)
class SettingBounds:
    """One per-corpus setting's declared range, as a refusal reports it."""

    key: str
    value: int
    expected: str


class InvalidSettingError(KnowledgeError):
    """A per-corpus setting a caller supplied is outside the range configuration declares for it.

    Deliberately **not** the store's `bad_config`, which is the easy mistake here because the range
    comes from the configuration schema: that code says a stored or configured value is unusable
    and sends whoever reads it to a file to fix, where the thing that is actually wrong is the
    number the caller just typed. The range is the same range either way — read from that schema
    rather than restated — which is what keeps a corpus created through a tool reproducible by
    writing a configuration file.
    """

    def __init__(self, message: str, *, bounds: SettingBounds) -> None:
        super().__init__(message)
        self.bounds = bounds


class IndexerBusyError(KnowledgeError):
    """An indexer holds this knowledge base's lock.

    Raised on two opposite readings of the evidence, because two different questions are being
    asked of it.

    Anything that must not proceed **alongside** a build — a second build, the removal of a
    database a writer may still hold — raises it on a lock that cannot be shown to be *dead*,
    rather than on one proved alive. Whether a recorded holder is live is a question only its own
    host can answer, and refusing a corpus that turns out to be idle is recoverable where unlinking
    a database out from under a live writer is not.

    An operator's **forced release** raises it on the one case that evidence contradicts: a process
    on this host answers to the recorded pid. That is the opposite test, and deliberately so — the
    verb exists to clear a lock whose owner is gone, so the only thing that should stop it is
    finding an owner that is not.

    `holder` is who is recorded as holding it, so that a surface reporting this can say *which pid
    on which host, and since when* rather than quoting the whole refusal into a field a client
    reads as a value.
    """

    def __init__(self, message: str, *, holder: "LockHolder") -> None:
        super().__init__(message)
        self.holder = holder


class DanglingKnowledgeBaseError(KnowledgeError):
    """The knowledge base is registered but its database file is gone, and with it its definition.

    Everything that says what this corpus *is* — its root, its globs, its `git_mode`, its size cap
    — lives in that file, because the registry deliberately owns only the name and description. So
    a build has nothing to walk and cannot invent one; the way back is to remove the name and add
    it again, which loses nothing, since a knowledge base in this state has never indexed anything.
    """


class RegistryUnavailableError(KnowledgeError):
    """The store that holds the list of knowledge bases could not be read.

    Distinguished from *this project has no knowledge bases*, which is the answer it would
    otherwise be indistinguishable from: the registry lives in the memory store, so a store that
    will not open makes every corpus undiscoverable while leaving each one's own database intact.
    A caller told the list is empty would conclude the corpora are gone.
    """


class CorpusRootMissingError(KnowledgeError):
    """The directory this knowledge base indexes is gone.

    A refusal rather than an empty walk, because an empty walk means *every indexed file has been
    deleted* — which would destroy the whole index on the strength of an unmounted drive or a
    renamed parent. The index is kept as it is, ready for the root's return.
    """
