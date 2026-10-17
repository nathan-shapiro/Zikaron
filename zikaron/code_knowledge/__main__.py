"""`python -m zikaron.code_knowledge` — the same command as `zikaron code-knowledge`.

A package needs `__main__` to be executable; turning `main`'s status into an exit is this file's
only job.
"""

import sys

from zikaron.code_knowledge.main import main

sys.exit(main())
