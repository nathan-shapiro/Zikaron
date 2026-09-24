"""`python -m zikaron.project` — the module form of `zikaron init`."""

import sys

from zikaron.project.initialize import main

if __name__ == "__main__":
    sys.exit(main())
