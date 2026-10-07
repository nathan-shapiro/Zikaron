"""The find-replace rule's two properties over generated commands (`design/edit-guards.md` §1).

**Determinism**: the same payload, `$TMPDIR` and scratch scripts always yield the same output. And
**totality**: no command makes the rule raise — a raise would still be an allow, by §6, but a
silent one that hides every form in the command. Row 6's file read is a stand-in answering one
fixed script for every path, so a generated `bash /tmp/x` judges a script without touching the
machine's own `/tmp`.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from zikaron.guard.decision import decide
from zikaron.guard.scratch import Location


def _one_script(path: str) -> str:
    del path
    return "sed -i 's/a/b/' f\nopen('f','w')\npython3 /tmp/x"


#: Fragments that exercise every stage: quoting, heredocs, continuations, substitutions,
#: separators, redirects, the override and each form's command word.
_FRAGMENTS = (
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


@settings(max_examples=400, deadline=None)
@given(command=commands, location=locations)
def test_the_decision_is_deterministic_and_total(command: str, location: Location) -> None:
    first = decide(command, location, read=_one_script)
    assert first == decide(command, location, read=_one_script)
