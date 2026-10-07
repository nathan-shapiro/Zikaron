"""Every example in `zikaron.guard`'s docstrings runs and gives the output it shows.

The rule modules lead with examples so a reader meets the rule before the code; run as doctests,
an example cannot drift from the code beneath it.
"""

import doctest
import importlib
import pkgutil

import pytest

import zikaron.guard

MODULES = sorted(info.name for info in pkgutil.iter_modules(zikaron.guard.__path__))


@pytest.mark.parametrize("name", MODULES)
def test_docstring_examples(name: str) -> None:
    module = importlib.import_module(f"zikaron.guard.{name}")
    result = doctest.testmod(module, optionflags=doctest.ELLIPSIS)
    assert result.failed == 0
