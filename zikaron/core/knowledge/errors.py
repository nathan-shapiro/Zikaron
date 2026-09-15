"""What a knowledge-base lifecycle call refuses, and why.

Deliberately **not** `ZikaronError`. That type carries the numeric codes two independently written
clients agree on over the wire, and every one of them describes something a client asked the
memory service to do. A knowledge-base name that is already taken, a corpus root that does not
exist, or a database an indexer is holding are none of those, and giving them wire codes would put
values on that contract no RPC can return.

One class per refusal rather than one class with a reason field. Each carries a message naming
what to do about it, which is what the command prints; no caller branches on the class today. What
the split buys is that a caller which needs to — a tool surface mapping refusals onto wire codes —
can do so on the type rather than by matching prose, and a message may then be reworded without
silently changing which branch it takes.
"""


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
    """


class InvalidRootError(KnowledgeError):
    """The corpus root is absent, is not a directory, or is a root a corpus should not have.

    The root is the one caller-supplied string in this system with any path semantics at all, and
    it is validated rather than refused outright: indexing a docs tree or a vendored dependency
    outside the project is a legitimate use.
    """


class IndexerBusyError(KnowledgeError):
    """An indexer holds this knowledge base's lock.

    Raised by anything that must not proceed alongside a build: a second build, and the removal of
    a database a writer may still hold. Whether the recorded holder is *live* is a question only
    its own host can answer, so this is raised on a lock that cannot be shown to be dead rather
    than on one proved alive — refusing is recoverable, and the alternative is not.
    """


class DanglingKnowledgeBaseError(KnowledgeError):
    """The knowledge base is registered but its database file is gone, and with it its definition.

    Everything that says what this corpus *is* — its root, its globs, its `git_mode`, its size cap
    — lives in that file, because the registry deliberately owns only the name and description. So
    a build has nothing to walk and cannot invent one; the way back is to remove the name and add
    it again, which loses nothing, since a knowledge base in this state has never indexed anything.
    """


class CorpusRootMissingError(KnowledgeError):
    """The directory this knowledge base indexes is gone.

    A refusal rather than an empty walk, because an empty walk means *every indexed file has been
    deleted* — which would destroy the whole index on the strength of an unmounted drive or a
    renamed parent. The index is kept as it is, ready for the root's return.
    """
