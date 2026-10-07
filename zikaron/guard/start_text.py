"""The guard start text `zikaron-hook --components guards|both` emits (`design/edit-guards.md` §5).

A module of its own, importing nothing, because the hook that emits it runs on every session and
subagent start and must not load the rule engine to print a constant. Its wording is
memory-reviewer's, held to `reviews/m37-edit-guards-review.md` by a test, like `messages`.
"""

from typing import Final

GUARD_START_TEXT: Final = """## Editing files (Zikaron edit guards)

Authored files in this project are edited with Read then Edit, or with Write for a new file, and
never with `sed -i`, an inline interpreter script, a script written to scratch and then run, or
a heredoc or other redirect of literal text into a file, each of which changes text that has not
been read in its current state. A hook in this project refuses a Bash command that does so.
A path under /tmp, /var/tmp or $TMPDIR is scratch and exempt as a target; a script run from
there is judged by what it writes, not by where it is. After each edit, a reminder from this
project's hooks notes that the file has not been re-read; it asks for one re-read of the edited
material and its surroundings once that file's editing is finished, not one re-read per edit."""
