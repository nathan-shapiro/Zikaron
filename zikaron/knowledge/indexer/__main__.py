"""`python -m zikaron.knowledge.indexer`.

A separate module from `main.py` because `python -m zikaron.knowledge.indexer` resolves a
*package*, and a package needs `__main__` to be executable. `main.py` returns a status rather than
exiting so a test can drive it in-process; turning that status into an exit is this file's only
job.

**Its coverage reads 0% and that is not a gap.** The test that exercises it runs the module as a
subprocess, which is the only way to exercise an entry point at all, and coverage does not follow
a child process.
"""

import sys

from zikaron.knowledge.indexer.main import main

sys.exit(main())
