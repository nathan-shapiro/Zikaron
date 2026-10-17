"""Where a module's documents live, and which source each one describes.

Every path here is relative to the Zikaron root in POSIX form — the form `zikaron-source` declares
and a search reports — so a document's location and its link can be compared as strings.
"""

import os
from dataclasses import dataclass
from typing import Final

DOCUMENT_SUFFIX: Final = ".md"
README_NAME: Final = "README.md"


def path_order(path: str) -> bytes:
    """The sort key for path order: the bytes of the root-relative POSIX path.

    Bytes rather than the string, because a path the filesystem could not decode carries surrogate
    escapes, which sort apart from the bytes they stand for.
    """
    return os.fsencode(path)


def _joined(directory: str, name: str) -> str:
    if not name:
        return directory
    return f"{directory}/{name}" if directory else name


def _under(path: str, directory: str) -> bool:
    return not directory or path == directory or path.startswith(f"{directory}/")


@dataclass(frozen=True, slots=True)
class Layout:
    """The documents directory and the module, both relative to the Zikaron root.

    `module` is empty for the root itself. `documents` is never empty, and may begin with `..`.
    """

    documents: str
    module: str

    @property
    def module_documents(self) -> str:
        """The directory holding this module's documents and its README."""
        return _joined(self.documents, self.module)

    @property
    def readme(self) -> str:
        """The module README's path."""
        return _joined(self.module_documents, README_NAME)

    def source(self, module_relative: str) -> str:
        """A source's root-relative path, from its path relative to the module."""
        return _joined(self.module, module_relative)

    def document_for(self, source: str) -> str:
        """Where the document describing `source` lives."""
        return f"{self.documents}/{source}{DOCUMENT_SUFFIX}"

    def source_for(self, document: str) -> str:
        """The source a document's location derives: its path under the documents directory,
        with the suffix removed. `document` is one of this module's, so it has both."""
        return document[len(self.documents) + 1 : -len(DOCUMENT_SUFFIX)]

    def holds_documents(self, source: str) -> bool:
        """Whether a root-relative path lies in the documents directory, which is never a source."""
        return _under(source, self.documents)

    @property
    def documents_contain_module(self) -> bool:
        """Whether the module lies in the documents directory, where it could hold no source."""
        return _under(self.module, self.documents)
