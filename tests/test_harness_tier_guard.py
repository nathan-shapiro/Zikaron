"""The backstop that keeps a harness tier from reporting success it did not earn.

`conftest.pytest_runtest_makereport` turns a skip inside `integration_kiro` or `integration_claude`
into a failure. Every test in those tiers already fails on its own when its binary is absent, so
this wrapper is defence in depth — its job is to catch the **next** test somebody adds.

It is tested through `pytester`, a nested pytest in a temporary directory, because the thing that
could break it is not our logic: it is pytest's own wrapper-hook semantics changing under a version
bump, or `item.keywords` no longer carrying marker names. A unit test of a predicate would keep
passing through exactly that. This is the same reasoning the `integration_kiro` tier rests on — a
contract with someone else's code is only checked by running it.
"""

import pytest

_TIER_TEST = """
import pytest

@pytest.mark.{marker}
def test_skips() -> None:
    pytest.skip("the binary is missing")
"""

_UNMARKED_TEST = """
import pytest

def test_skips() -> None:
    pytest.skip("an ordinary conditional skip")
"""


def _nested(pytester: pytest.Pytester, body: str, marker: str | None) -> pytest.RunResult:
    pytester.makeini("[pytest]\nmarkers =\n    integration_kiro: x\n    integration_claude: x\n")
    # Import the real hook rather than restating it: a copy would pass while the original rotted.
    pytester.makeconftest("from tests.conftest import pytest_runtest_makereport  # noqa: F401")
    pytester.makepyfile(body)
    return pytester.runpytest("-p", "no:cacheprovider", *(("-m", marker) if marker else ()))


@pytest.mark.parametrize("marker", ["integration_kiro", "integration_claude"])
def test_a_skip_inside_a_harness_tier_is_reported_as_a_failure(
    pytester: pytest.Pytester, marker: str
) -> None:
    result = _nested(pytester, _TIER_TEST.format(marker=marker), marker)
    result.assert_outcomes(failed=1, skipped=0)


@pytest.mark.parametrize("marker", ["integration_kiro", "integration_claude"])
def test_the_failure_keeps_the_reason_the_skip_gave(pytester: pytest.Pytester, marker: str) -> None:
    """A backstop that discards the diagnosis makes the failure harder to act on than the skip."""
    result = _nested(pytester, _TIER_TEST.format(marker=marker), marker)
    result.stdout.fnmatch_lines(["*the binary is missing*"])


def test_an_ordinary_skip_outside_the_tiers_is_left_alone(pytester: pytest.Pytester) -> None:
    """Deliberately narrow. `tests/test_install_assets.py` skips on *checkout state* rather than on
    a binary, which is legitimate, and a wrapper that failed every skip in the suite would be a
    worse defect than the one it guards."""
    result = _nested(pytester, _UNMARKED_TEST, None)
    result.assert_outcomes(skipped=1, failed=0)
