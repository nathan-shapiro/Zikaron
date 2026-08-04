"""`python -m zikaron.install`.

A separate module from `main.py` because `python -m zikaron.install` — the invocation the install
docs give — resolves a *package*, and a package needs `__main__` to be executable. `main.py` returns
a status rather than exiting so a test can drive it in-process; turning that status into an exit is
this file's only job.

**Its coverage reads 0% and that is not a gap.** The test that exercises it
(`tests/test_install_main.py::TestTheDocumentedInvocation`) runs `python -m zikaron.install` as a
subprocess, which is the only way to exercise an entry point at all, and coverage does not follow a
child process. Deleting the test would raise nothing and lower nothing.
"""

import sys

from zikaron.install.main import main

sys.exit(main())
