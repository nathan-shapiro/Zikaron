# `CLAUDE_PROJECT_DIR` is exported to hooks, not to the agent's shell

**Measured 2026-09-24**, in a live Claude Code session on Linux, from the agent's own Bash tool.
Written because two normative passages disagreed about it and M31's refusal wording rests on the
answer: `zikaron/project/resolve.py` says the fallback rung is what a typed command resolves
through in practice, while `design/harness.md` §"The nesting limit" offered `pytest -m
integration_kiro` run from inside a Claude Code session as a live example of a subprocess
*inheriting* the variable.

## What was run, and what it printed

```
$ echo "CLAUDE_PROJECT_DIR=${CLAUDE_PROJECT_DIR:-<unset>}"
CLAUDE_PROJECT_DIR=<unset>

$ echo "CLAUDECODE=${CLAUDECODE:-<unset>}"
CLAUDECODE=1

$ echo "CLAUDE_CODE_SESSION_ID set: $([ -n "${CLAUDE_CODE_SESSION_ID:-}" ] && echo yes || echo no)"
CLAUDE_CODE_SESSION_ID set: yes

$ bash -c 'echo "CLAUDE_PROJECT_DIR=${CLAUDE_PROJECT_DIR:-<unset>}"'      # a grandchild
CLAUDE_PROJECT_DIR=<unset>
```

The marker `CLAUDECODE` and the session id **are** exported to the shell; `CLAUDE_PROJECT_DIR` is
not, and a further child does not acquire it either.

## What this establishes, and what it does not

**Establishes:** in this Claude Code version, a process the agent's shell tool spawns resolves D17
through the **fallback rung**, not the harness rung — so `zikaron knowledge` and `zikaron init`
typed by an agent key the store to the working directory, exactly as one typed by a person does.
That is what makes the rung worth naming in a refusal: it is the ordinary case rather than the
exotic one, and it is why a command run from a subdirectory addresses a different project.

**Does not establish** that the variable is absent from *every* process under a Claude Code
session. It is documented as reaching hooks, and it was not probed there here. The nesting hazard
`harness.md` describes remains real for a process that does inherit it — the point narrowed is only
that the agent's shell is not such a process in this version.

**n=1, one platform, one harness version, and a vendor may change it.** The claim to carry forward
is the measured one, and `tests/conftest.py::_no_inherited_harness_environment` keeps deleting the
variable regardless, which costs nothing and stays correct whichever way a future version goes.

## Re-deriving it

Run `echo "${CLAUDE_PROJECT_DIR:-unset}"` from the agent's shell inside a live session. There is no
hermetic equivalent: a test can only read `HarnessSpec.project_dir_variable`, which is the
*declaration*, never what the harness exported.
