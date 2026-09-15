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
    """An indexer holds this knowledge base's lock, so its database must not be unlinked."""
