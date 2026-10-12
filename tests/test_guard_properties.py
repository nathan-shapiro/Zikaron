"""The command rules' two properties over generated commands (`design/guards.md` §1).

**Determinism**: the same payload, `$TMPDIR`, platform and scratch scripts always yield the same
output, and so does the same call with warnings turned into errors (§9.2). And **totality**: no
command makes a rule raise — a raise would still be an allow, by §6, but a silent one that hides
every form in the command. Row 6's file read is a stand-in answering one fixed script for every
path, so a generated `bash /tmp/x` judges a script without touching the machine's own `/tmp`.
"""

import re
import warnings

from hypothesis import given, settings
from hypothesis import strategies as st

from zikaron.guard.decision import decide
from zikaron.guard.scratch import Location


def _one_script(path: str) -> str:
    del path
    return "sed -i 's/a/b/' f\nopen('f','w')\npython3 /tmp/x"


#: Fragments that exercise every stage: quoting, heredocs, continuations, substitutions,
#: separators, redirects, the override, each form's command word, and the self-match rule's
#: programs, options, patterns and filters.
_FRAGMENTS = (
    "pgrep ",
    "pkill ",
    "-f ",
    "-af ",
    "-A ",
    "-int ",
    "--signal ",
    "! ",
    "grep -v ",
    "-e ",
    "[m]x",
    "[[:alpha:]]",
    "$$",
    "sed -i ",
    "perl -pi -e ",
    "gawk -i inplace ",
    "python3 -c ",
    "node -e ",
    "cat ",
    "echo ",
    "tee ",
    "bash ",
    "python3 ",
    "xargs ",
    "timeout 5 ",
    "<<'EOF'",
    "<<-X",
    "<<<",
    "EOF",
    "'",
    '"',
    "\\",
    "\n",
    " | ",
    " && ",
    "; ",
    " > ",
    " >> ",
    "2>&1",
    "$(",
    ")",
    "(",
    "{ ",
    ">(",
    "#",
    " #ZIKARON-FORCE #Reason: a b",
    "open('f','w')",
    "Path('/tmp/x').write_text(s)",
    "/tmp/x",  # noqa: S108 — command text, never opened
    "f",
    "s/a/b/",
    " ",
)

commands = st.lists(st.sampled_from(_FRAGMENTS), max_size=24).map("".join) | st.text(max_size=80)
locations = st.builds(
    Location,
    cwd=st.sampled_from(["/home/u/proj", "/tmp/w"]),  # noqa: S108 — payload values, never opened
    tmpdir=st.sampled_from([None, "", "/", "/var/folders/x/T", "rel"]),
)


platforms = st.sampled_from(["linux", "darwin", "win32"])


@settings(max_examples=400, deadline=None)
@given(command=commands, location=locations, platform=platforms)
def test_the_decision_is_deterministic_and_total(
    command: str, location: Location, platform: str
) -> None:
    first = decide(command, location, platform=platform, read=_one_script)
    assert first == decide(command, location, platform=platform, read=_one_script)
    re.purge()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert first == decide(command, location, platform=platform, read=_one_script)
