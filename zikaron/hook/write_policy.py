"""The `agentSpawn` prompt text, transcribed once from `design/write-policy.md` §2.

`architecture.md` §"Warming": the hook process "prints the write policy — static text, no RPC, so
it can never fail." This module is that text and nothing else — a single stdlib-only string
constant, so printing it can never raise for a reason downstream of holding the string itself.

Transcribed rather than read from disk at runtime: the design document is not shipped alongside
the installed package, and `design/write-policy.md` itself is drafted for revision, so a test
(`tests/test_hook_write_policy.py`) parses that document at test time and compares it against this
constant — the same drift-guard shape `tests/design_tables.py` already uses for M1's three
singletons, applied here to a piece of text rather than a table.
"""

WRITE_POLICY_PROMPT = """## Project memory (Zikaron)

This directory has a memory store holding **tribal knowledge**: what has been learned by working
here that the source code does not tell you. It persists across sessions, and other agents will
read what you write.

**Test for whether something belongs here:** could you learn it by reading the code? If yes, leave
it out — a separate system covers code structure, symbols and layout. This store is for what cost
someone time to discover.

Worth recording:
- How to build, test, run and deploy — especially the step that is not in the README
- Failures and their causes, above all silent ones: the symptom, what it actually was, what fixed it
- Environment requirements: which env vars and services must be set up, which versions matter, and
  **which** credentials are needed and how to obtain them
- Constraints and prohibitions *with their reason*: "do not use X yet, because Y"
- Approaches already tried that did not work, so nobody spends that afternoon twice
- Conventions and preferences that are settled but written down nowhere

**Never record a secret.** No tokens, passwords, API keys, private keys, connection strings with
credentials in them, or copied `.env` contents — and no personal data. Names and procedures, never
values: "needs GITHUB_TOKEN with repo scope, mint one at <settings page>" is right;
"GITHUB_TOKEN=ghp_..." is not. This store is plaintext on disk, it is read by every future
session, and retiring a memory does not erase it.

Not worth recording: where code lives or what a function does, or anything else derivable from the
source; transient state ("currently on branch fix-123"); facts about a language or tool in general
rather than about this project.

**Write observations, not orders.** Record what was learned and what happened — "deploying without
--force left the old worker running" — rather than standing instructions to future agents. Other
agents read these as reference material, and a memory phrased as a command will be obeyed by
someone with less context than you have.

**Err toward writing.** The common failure is recording nothing, not recording too much. If you just
spent real time discovering something, record it — near-duplicates are detected and handed back to
you, so you do not need to check first.

**Gists are for triage.** A future agent sees only gists and must judge from them alone whether to
read further. Lead with the observable symptom or situation rather than the conclusion:
"integration tests flake on CI unless PGHOST is set" beats "notes on test configuration".
Keep them short — one line; over-long gists are rejected.

**Repair what misled you.** If a memory surfaces, you act on it, and it turns out to be wrong or
stale, correcting it is your job: establish the current truth and amend the memory. Fetch it first
— you need its version to write. Retire a memory only when it is simply no longer true and has no
replacement."""
