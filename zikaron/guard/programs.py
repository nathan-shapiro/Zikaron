"""The command words that execute text they are handed: shells and row 4's interpreters.

`design/edit-guards.md` §3.2 decides three things by them: whether a heredoc body is scanned (its
opener's pipeline has one), which commands row 4 judges, and where row 5's walk back from `tee`
stops. Each is matched as the whole word, after `position.command_name` has removed quotes and
the path prefix — so `ssh` is not `sh`, and `/bin/bash` is `bash`.

>>> [is_shell(w) for w in ("bash", "sh", "zsh", "ssh", "fish")]
[True, True, True, False, False]
>>> [is_interpreter(w) for w in ("python3.12", "python3.14t", "pypy3", "nodejs", "ipython")]
[True, True, True, True, False]
"""

import re
from typing import Final

_SHELL: Final = re.compile(r"(ba|z|da|k)?sh")
_PYTHON: Final = re.compile(r"python[0-9.]*t?|pypy[0-9]*")
_NODE: Final = re.compile(r"node|nodejs")


def is_shell(word: str) -> bool:
    """`sh`, `bash`, `zsh`, `dash` or `ksh`."""
    return _SHELL.fullmatch(word) is not None


def is_python(word: str) -> bool:
    """A Python interpreter word, versioned or free-threaded (`python3.14t`), or PyPy."""
    return _PYTHON.fullmatch(word) is not None


def is_interpreter(word: str) -> bool:
    """One of row 4's interpreter words: Python's, or node's."""
    return is_python(word) or _NODE.fullmatch(word) is not None


def executes_text(word: str) -> bool:
    """A shell or an interpreter: what reaches the next command is that program's output."""
    return is_shell(word) or is_interpreter(word)
