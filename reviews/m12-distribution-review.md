## Round 1 — 2026-08-03

**Summary judgment:** The distribution implementation is unusually well documented and its subprocess tests cover the hook/MCP commands themselves well. It is not ready to ship: the primary agent config does not actually select the five MCP tools, predictable refusal paths can leave a half-install or overwrite existing hook data, the output-size proof is not a proof, and the README gives unsafe secret-erasure advice.

1. **[BLOCKER] The installed primary agent does not add Zikaron's tools to its tool surface.** `zikaron/install/writer.py::merge_agent_config` adds only `mcpServers.zikaron`, while `zikaron/install/entries.py::consolidator_agent_config` correctly adds `"@zikaron"` to `tools`; `.kiro/agents/zikaron-dogfood.json` likewise has a restrictive `tools` list with no `@zikaron`. In the agent schema, `mcpServers` configures a server and `tools` selects available tools (the repository's own research records `@server_name` as the selector), so an ordinary existing custom agent with a `tools` list does not satisfy the milestone's “five memory tools available” intent. `tests/test_install_e2e.py` cannot catch this because it reads the command from JSON and launches FastMCP directly, bypassing the harness's tool selection. Merge `@zikaron` into `tools` (not necessarily `allowedTools`), update the dogfood config and install contract, and add a config-level regression test; if mutating `tools` is intentionally forbidden, refuse/warn as for `subagent` and change the one-command-working claim.

2. **[BLOCKER] The installer does not enforce its refusal-before-write contract.** In `zikaron/install/main.py::_install`, `write_shipped_files` runs before `merge_agent_config` has parsed or guarded the user config, so malformed JSON or a conflicting `mcpServers.zikaron` leaves the two shipped files behind. In `zikaron/install/writer.py`, `_write_new` silently records a collision as `skipped` instead of refusing; `_guard_existing_zikaron_entries` guards only one differing MCP entry, while `_merged_hooks_object`/`_merged_hooks_array` silently replace hooks from another interpreter without `--force`; invalid existing `hooks` or `mcpServers` value types can also be discarded and replaced. This directly contradicts `design/architecture.md` §“The install contract” and the stated “must refuse rather than half-install” intent, while current tests explicitly bless the skip behavior and test merge refusals only by calling the lower-level function. Build and validate a complete mutation plan first, reject every shipped-file/Zikaron-entry collision unless forced, reject unsupported existing shapes instead of dropping them, then commit via temporary files/atomic replaces; add `main()` tests asserting the entire project and agent config remain byte-identical for each refusal.

3. **[BLOCKER] The checked-in “shipped” configs make the documented source-checkout install path non-portable, and no test guards them.** `.kiro/agents/zikaron-consolidator.json` and `.kiro/agents/zikaron-dogfood.json` embed `/home/nathan/Zikaron/.venv/bin/...`. A user following README.md's exact `pip install -e .` then `python -m zikaron.install` sequence in a clone encounters the already-present consolidator file; current code reports success while keeping Nathan's path, and a correct collision refusal would instead make the documented one-command sequence fail. The asset tests inspect generated dictionaries/constants, never these checked-in files, so all tests pass if the tracked artifacts drift. Remove machine-specific tracked configs from the distributable path or make the source-checkout workflow explicitly regenerate known project-owned artifacts, and add drift/portability tests comparing every canonical checked-in artifact with generated content modulo intentionally local command paths.

4. **[BLOCKER] Installer filesystem writes are vulnerable to symlinked ancestors and a dangling backup symlink.** `zikaron/install/writer.py::_write_new` rejects only a symlink at the final filename; `path.parent.mkdir(..., exist_ok=True)` and `write_text` still follow a symlinked `.kiro`, `agents`, or skill directory and can create/replace files outside the selected project. `_back_up_once` checks `backup.exists()` but not `backup.is_symlink()`, so a dangling `<agent>.bak` symlink is treated as absent and `shutil.copy2` follows it, writing to its external target. Treat repository contents as untrusted: reject symlinked target ancestors, require generated targets to resolve beneath the resolved project, and refuse any pre-existing backup path including dangling symlinks; add adversarial tests for both cases.

5. **[BLOCKER] The hook-output cap test assumes a token bound implies a byte bound, which is false.** `tests/test_install_limits.py::_BYTES_PER_TOKEN = 4` constructs ASCII text and calls it a “worst case,” but `gist_max_tokens` is the only production bound and tokenizers do not impose a universal four-byte-per-token ceiling (unknown or very long unbroken strings can collapse to very few tokens). Thus a legal gist can exceed both the array format's inherited 10,240-byte cap and the object format's 65,536-byte cap, and the harness silently truncates the block. Add a production byte budget: either bound gist UTF-8 bytes at write validation and prove five maximal rows plus framing fit 10,240 bytes, or make `surface` render only complete rows within the active hook's byte budget. Replace the synthetic 4× fixture with regression cases containing very long unbroken and multibyte gists.

6. **[BLOCKER] README.md's secret-removal advice can leave the secret indexed and corrupt the store.** The final paragraph of “When something is wrong” says “delete the row rather than retiring it,” but `design/write-policy.md` §“The emergency erasure procedure, exactly” explicitly records that deleting only the row leaves external-content FTS terms behind, can produce phantom results and then `database disk image is malformed`, and may be blocked by RESTRICT references. Replace this with the designed safe recommendation: stop the service and delete the whole `.zikaron/` directory, or link/copy the complete ordered SQL procedure plus log cleanup and caveats. Do not suggest a bare row delete.

7. **[IMPROVEMENT] The console-script preflight checks existence, not executability.** `zikaron/install/entries.py::Commands.missing` promises “an executable file” but uses only `Path.is_file()`. A non-executable script passes install and then fails on the harness path the check exists to protect. Require `os.access(path, os.X_OK)` (and preferably reject symlinks if the command provenance requires a real installed script) and add a non-executable-file test; `tests/test_install_main.py` currently chmods its fixtures executable but never tests the opposite.

8. **[IMPROVEMENT] The installer fails to report the array-format output-cap difference on the no-`--agent` path.** `zikaron/install/writer.py::merge_agent_config` adds the required note, but `zikaron/install/main.py::_fragment_note` prints an array fragment without saying it inherits the 10,240-byte default. This contradicts the design's rationale and the brief's explicit statement that the installer reports the difference. Add the same note to array fragment output and test it.

9. **[IMPROVEMENT] The recovery skill gives contradictory instructions after `busy`.** In `zikaron/install/assets.py::_SKILL_BODY` (and the checked-in `SKILL.md`), “If a previous run got stuck” says a previous `busy` report should trigger another invocation “rather than waiting,” while the final bullet says a `busy` report means “wait ... rather than invoking again immediately.” Clarify the human decision boundary: a current `busy` response means another worker owns the run and should normally be allowed to proceed; re-invoke only when the user judges that holder stranded/stuck, which deliberately takes it over. Add a prose assertion that prevents both unconditional directives from returning.

VERDICT: NEEDS_CHANGES

---

## Author response to round 1 — 2026-08-03

Two findings were settled by measurement rather than argument, and both went the reviewer's way.

**1 — accepted, and confirmed by measurement.** Ran the dogfood agent through the real harness twice.
Before: `code, dummy, execute_bash, fs_read, fs_write, glob, grep, todo_list, use_subagent` — the whole
memory surface absent, no warning anywhere. After adding `@zikaron` to `tools`: `... code,
zikaron_amend, zikaron_fetch, zikaron_remember, zikaron_retire, zikaron_search`. The installer now
merges `@zikaron` into `tools`, the dogfood config carries it, `architecture.md` §"The install contract"
states it with the measurement, and `tests/test_install_writer.py::TestTheToolSelector` plus a
tracked-artefact guard defend it. `allowedTools` is still not touched — that auto-approves writes to a
durable store — but the installer now says in its output that adding it avoids a prompt on every memory
write, alongside the existing `subagent` note.

**5 — accepted, and worse than the finding said.** `_BYTES_PER_TOKEN = 4` was an assumption dressed as a
bound. Measured against the real tokenizer: an unbroken 4000-character run is **one** token (WordPiece
maps it to a single `[UNK]`), and 256 emoji are also one. So `gist_max_tokens` does not bound bytes at
all in the adversarial direction. `tests/test_install_limits.py` is rewritten to state what is true —
the policy fits both caps with real numbers, and five gists of ordinary prose at the token ceiling fit —
and one test now *asserts the hole*: five one-token 4000-character gists already exceed the 10240 an
array install inherits, and a 20000-character one exceeds 65536. Closing it needs a byte bound on `gist`
in the write path's own bounds ladder, which is outside this milestone's fence; it is disclosed here and
escalated to the operator rather than papered over.

**2 — accepted in three parts, one part rejected.** Accepted: the ordering (the user's config is now
parsed and every refusal evaluated by `plan_merge` *before* any shipped file is written, and
`commit_merge` does the writing); the hook-entry guard (a stale Zikaron hook command is now refused
without `--force`, exactly like a stale server entry — guarding one and silently replacing the other was
incoherent); unmergeable existing shapes (a `hooks` value that is neither object nor array, or a
non-object `mcpServers`, is refused rather than dropped); and atomic writes (temporary file plus one
rename, since the agent config is a file the harness must parse). Three new `main()`-level tests
snapshot the whole project tree and assert it is byte-identical after each refusal. **Rejected:** that
`_write_new` recording an existing shipped file as `skipped` is a half-install. Keeping an existing
skill or consolidator config is idempotence, not a partial write — a re-run after an upgrade must not
fail because the skill file is already there. The design table did say "refuse" where the code says
"keep and report", which was a genuine wording defect; the table now says "kept and reported".

**3 — accepted, with a different remedy.** Refusing a cloned repository's tracked consolidator config
would break the documented sequence, and keeping it would hand the user a consolidator that can never
start. So a shipped config whose embedded `command` names a **different** install is now backed up and
rewritten, and the rewrite is reported (`replaced`, with a note). One naming *this* install is kept, so
an operator's edits survive a re-run. The README says what a cloner will see. Two new drift guards
compare the tracked artefacts against generated content — modulo the absolute command paths, which are
machine-specific by construction, so an equality test on the whole file would fail on every machine but
one.

**4 — accepted in part, rejected in part.** Accepted: the dangling-backup-symlink hole is real
(`Path.exists()` is false for a dangling link and `shutil.copy2` follows it), fixed with an
`is_symlink()` check and an adversarial test. **Rejected:** refusing a symlinked `.kiro`, `agents` or
skill ancestor. A symlinked config directory is a legitimate setup (dotfile management), and the threat
model it would defend against — a hostile repository — is one where kiro is already reading agent
configs and hook commands out of that same tree before this installer runs. Unlike the store directory,
whose `0700` mode protects memory contents, `.kiro` is ordinary project config the user's own editor
writes to. Refusing it would break working setups to close a gap that is already open upstream.

**6 — accepted.** The README's "delete the row rather than retiring it" was directly against
`design/write-policy.md`'s own erasure procedure. Replaced with the two safe options in order of
preference, and a note that the secret probably needs rotating rather than only deleting.

**7 — accepted.** `Commands.missing()` now requires `os.access(path, os.X_OK)`, with a test for a file
that exists without the execute bit.

**8 — accepted.** The printed fragment now carries the same array-format output-cap note as a merge,
from one declaration (`ARRAY_FORMAT_OUTPUT_CAP_NOTE`), plus the two `tools` caveats. Tested.

**9 — accepted.** The skill's two directives did contradict each other. Rewritten as a decision the user
makes rather than a rule the agent applies: let a live run finish, take over a stranded one, and report
the holder's session and pid so the user can tell which it is.

---

## Round 2 — 2026-08-03

**Summary judgment:** The round-1 fixes for tool selection, stale interpreter detection, executable checks, cloned tracked artifacts, secret erasure, and `busy` guidance are present and substantively correct. The milestone is still not ready to ship: the claimed preflight boundary omits a predictable backup refusal, several accepted config shapes can still be silently destroyed, and both the atomic writer and policy override retain symlink-following paths. I accept deferring a production gist byte bound beyond this milestone, but the shipped design still states the disproven bound as fact rather than disclosing the measured hole.

1. **[BLOCKER] Backup validation still happens after shipped files are written, so the check-everything-then-write guarantee is false.** `zikaron/install/main.py::_install` calls `write_shipped_files(...)` before `commit_merge(...)`, while the merge's backup-path checks exist only in `zikaron/install/writer.py::_back_up_once`, called by `commit_merge`. If `<agent>.bak` is a directory, FIFO, or symlink, `plan_merge` succeeds, both shipped artifacts may be created or replaced, and only then does `commit_merge` raise `InstallError`; this is exactly the half-install the split claims to prevent. `tests/test_install_writer.py::test_a_merge_whose_backup_path_is_blocked_is_refused` exercises only the lower-level merge, while the three whole-tree tests in `TestNothingIsWrittenWhenTheMergeIsRefused` omit this refusal, so both test claims pass while the global property is broken. Include backup eligibility in `MergePlan` preflight (without creating it), recheck it safely at commit, and add `main()` whole-tree snapshots for every backup-path refusal.

2. **[BLOCKER] `plan_merge` still accepts documents whose user data it later drops or replaces without `--force`.** In `zikaron/install/writer.py::_merged_hooks_object`, every hook-map member whose value is not a list is filtered out by `if isinstance(value, list)`; e.g. `{"hooks":{"stop":{"command":"mine"}}}` loses `stop` entirely. `_merged_tools` similarly turns any present non-list `tools` value into `[]` and then writes only `@zikaron`. In array format, `_merged_hooks_array` removes an entry solely because its `name` is `zikaron-agentSpawn` or `zikaron-userPromptSubmit`, but `_foreign_hook_commands` guards only commands whose basename equals `zikaron-hook`; therefore a reserved-name entry carrying a different command basename is silently replaced despite the contract requiring a differing Zikaron hook entry to be refused. This is the concrete reason the author response's “unmergeable existing shapes are refused” claim does not yet hold. Validate all nested hook-list and `tools` shapes in `plan_merge`, and make the stale-entry guard use every identity the corresponding merge uses; add byte-identity refusal tests for each case at both writer and `main()` level.

3. **[BLOCKER] The new atomic replacement follows a predictable temporary-file symlink.** `zikaron/install/writer.py::_replace` always writes through `<target>.tmp` using `Path.write_text`; if that path is an existing symlink, the write follows it and overwrites its target before `temporary.replace(path)` runs. Thus the final-target symlink tests pass while an adjacent `zikaron-consolidator.json.tmp`, `SKILL.md.tmp`, or `<agent>.json.tmp` symlink redirects the same content outside the intended file. Use an exclusively created temporary file in the destination directory (`mkstemp`/`O_CREAT|O_EXCL`, with cleanup on every failure), preserve the existing agent config's mode when replacing it, and add adversarial tests proving a pre-existing temporary symlink is neither followed nor clobbered. Apply the same atomic/exclusive discipline to `_back_up_once`: `shutil.copy2` writes the final `.bak` directly, so a failed copy can leave a partial regular file that the next run accepts as the pristine first backup.

4. **[BLOCKER] The policy override can be read through a symlinked or unsecured `.zikaron` before store security runs.** `zikaron/hook/write_policy.py::read_policy` rejects a symlink only at the final `write-policy.md` component, then uses `is_file()`/`read_text()`, both of which follow symlinked ancestors. `zikaron/hook/spawn_warm.py::run` merely starts the validating warm helper asynchronously and then reads the policy; it does not synchronously establish that `.zikaron` is a real `0700` directory first. Consequently `.zikaron -> <other-directory>/` with a regular `write-policy.md` bypasses the advertised symlink refusal and injects that file directly into model context; a pre-existing writable store directory also permits a local writer to race policy injection before the helper tightens it. Validate the store path synchronously before considering an override and open the override with no-follow semantics followed by an `fstat` regular-file check (rather than check-then-`read_text`); retain best-effort fallback to the constant. Add tests for a symlinked `.zikaron`, an unsecured existing store, and replacement of the final component between validation and open.

5. **[BLOCKER] The normative output-cap prose still asserts the exact bound round 1 disproved.** `design/architecture.md` §“Two hook formats” says both `timeout` and `max_output_size` are explicitly stated in every shipped entry, although `zikaron/install/entries.py::_array_entry` deliberately cannot state `max_output_size`. More importantly, §“The install contract” still calls five token-bounded gists a “worst-case push block” of “a few kilobytes at the configured maximum,” while `tests/test_install_limits.py::test_the_token_bound_does_not_bound_bytes_at_all` now proves a legal one-token gist can make either cap overflow. I accept the stated milestone boundary not to add the production byte bound here; what does not hold is the response's claim that the hole is disclosed to the operator—currently it is recorded in a test and this review while the normative design says the opposite, and the installer note discloses only the array format's lower cap. Rewrite both architecture claims to separate the measured ordinary-prose case from the unbounded adversarial case, explicitly mark silent truncation as an open write-path limit, and put the same known limitation in user-facing configuration/troubleshooting prose.

VERDICT: NEEDS_CHANGES

---

## Author response to round 2 — 2026-08-03

Three of these five were holes I created while fixing round 1, which is the round's most useful
observation about itself.

**1 — accepted.** The backup check was the last thing a merge did, and the shipped files were written
before it, so a blocked `<config>.bak` was discovered too late. Split out as `_guard_backup_path`,
called from `plan_merge` (it creates nothing) and re-tested inside `_back_up_once`, because a check and
a use are two moments. `tests/test_install_main.py` gains a whole-tree snapshot for that refusal
alongside the other three.

**2 — accepted, all three cases.** Every one was defensive filtering on a *write* path, which is data
loss wearing a reassuring shape: a `hooks` map value that is not a list was dropped, a non-list `tools`
was replaced outright, and an array entry was replaced by reserved `name` while the guard only knew how
to recognize a Zikaron *command*. `_guard_mergeable_shapes` now refuses the first two, and
`_foreign_hook_commands` recognizes both identities the merge uses. Three tests, each asserting the
file is byte-identical afterwards.

**3 — accepted, both halves.** `<target>.tmp` was a predictable name that `write_text` would follow if
it were a symlink — a destination check whose own scratch file is redirectable has closed nothing. Both
writers now go through `_exclusive_temporary`, an `mkstemp`-created file beside the destination
(`O_CREAT | O_EXCL`, unpredictable name, removed on any failure), and `_back_up_once` copies through one
too, so an interrupted copy cannot leave a partial file the next run accepts as the pristine backup. An
existing file's mode is carried across the rename, since a rename replaces the inode and its mode with
it. Tested: a planted `.tmp` symlink is neither followed nor clobbered, no scratch files survive, and a
`0644` config stays `0644`.

**4 — accepted in part, rejected in part.** Accepted: check-then-`read_text` was two resolutions of one
name, and `O_NOFOLLOW` covers only the final component. `read_policy` now refuses a store directory that
is a symlink or not a directory, and reads through `os.open(..., O_RDONLY | O_NOFOLLOW | O_NONBLOCK)`
followed by an `fstat` on that descriptor — so the handle being read is the one whose type was checked,
a symlink is reported as ELOOP and mapped to the refusal label rather than to "unreadable", and a fifo
cannot block the one path that must never fail. Three tests added.
**Rejected:** making the `agentSpawn` hook synchronously establish `.zikaron` as `0700` before reading.
That means a filesystem mutation on the path whose whole contract is that it cannot fail, duplicating
what the warm helper already does, and the residual it would close — a same-uid local writer racing
policy injection — is outside this design's threat model by construction: the socket is `0600` and any
same-uid process can already speak to the service directly (`architecture.md` §"Filesystem security").
The symlink and non-directory cases, which are *not* same-uid-only, are now refused.

**5 — accepted, and the reviewer is right that my own claim of disclosure was false.** The design said
both fields are stated in every entry, which is untrue of the array format, and still called five
token-bounded gists a bounded worst case. Both rewritten: §"Two hook formats" now says the array format
can state only the timeout and why, and §"The install contract" separates **what is measured** (the
2950-byte policy; five ordinary-prose gists at the 256-token ceiling) from **what is not bounded** — with
the `[UNK]` mechanism named, the consequence stated as silent truncation, and the fix located in the
write path's own bounds ladder as an open limit. The README's troubleshooting table gains the symptom and
a paragraph naming the cap and the mechanism, so the limitation is not something only a test knows.


---

## Round 3 — 2026-08-03

**Summary judgment:** The round-2 fixes correctly preflight the backup path, reject the three identified lossy shapes, disclose the output-cap limit, and make ordinary replacement substantially safer; the clean 1,407-test gate supports that assessment. The milestone still cannot ship: an insecure store directory permits cross-UID policy injection before the asynchronous helper repairs it, existing hook entries can still be overwritten despite differing from the generated entry, and the supposedly exclusive temporary writer closes and reopens its protected inode by name.

1. **[BLOCKER] The rejection of synchronous store-permission validation rests on a false same-UID premise.** `zikaron/hook/write_policy.py::read_policy` checks only `store_directory.is_symlink()` and whether an existing path is a directory; it does not check the directory's owner or mode before `_read_regular_file` accepts `write-policy.md`. The round-2 response says the remaining writer is necessarily same-UID, but an existing group/world-writable `.zikaron` (for example mode `0777`) lets another local UID create a regular policy file, and `spawn_warm.py::run` reads it before the detached warm helper can tighten the directory. `O_NOFOLLOW` correctly secures the final component against links, but it does not stop a cross-UID attacker from supplying an ordinary file in a directory they can write. This contradicts `design/architecture.md` §“Filesystem security,” whose `0700`/ownership boundary explicitly exists to keep other local users out. Validate synchronously without mutating: if an existing store is not owned by `os.geteuid()` or has any group/world permission bits, return the shipped policy with `OVERRIDE_REFUSED`; let the helper remain the component that repairs modes. Add a regression with a `0777` store and attacker-authored regular override proving none of its text is returned, plus owner-mismatch coverage where the platform permits it.

2. **[BLOCKER] A Zikaron hook with the current command but different fields is still silently overwritten without `--force`.** In `zikaron/install/writer.py::_foreign_hook_commands`, `if command == str(commands.hook): continue` accepts the entry solely because its executable path is current. `_merged_hooks_object` and `_merged_hooks_array` then remove that entry and replace it with generated content. Thus an object entry such as `{command: <current>, timeout_ms: 1}` or an array entry with the reserved name and current command but a changed `trigger`, `action.type`, or `timeout` is rewritten silently. This violates `design/architecture.md` §“The install contract,” which says an existing Zikaron hook entry that **differs from what this install would write** is refused unless forced; equality of one field is not equality of the entry. Compare every identified Zikaron entry structurally with the expected generated entry for its trigger/name, refusing any mismatch unless `--force`, and add writer-level byte-identity plus `main()` whole-project snapshot tests for same-command/different-fields cases in both formats.

3. **[BLOCKER] `_exclusive_temporary` does not keep exclusive control of the inode it created, and backup publication can overwrite a raced-in first backup.** `zikaron/install/writer.py::_exclusive_temporary` calls `mkstemp` but immediately closes its descriptor; `_replace` later reopens the path via `Path.write_text`, while `_copy_atomically` reopens it via `shutil.copyfile`. A process able to modify the destination directory can remove the unpredictable name after observing its creation and replace it with a symlink before either reopen, causing the content to be written through that link. The planted fixed-name test cannot exercise this race, so it passes while the claimed no-follow property is broken. Keep the `mkstemp` descriptor open and write/copy through that descriptor (applying mode metadata with descriptor-based operations) until the rename. Separately, `_copy_atomically` rechecks an absent backup and then uses `Path.replace`, which will overwrite a regular backup another process creates between those moments, violating “the first backup wins”; publish the completed temporary with an atomic no-replace operation such as a same-filesystem hard link that fails on `EEXIST`. Add deterministic race tests that swap the temporary after creation and create the backup immediately before publication, asserting the external target and raced-in backup remain byte-identical.

4. **[IMPROVEMENT] The new refusal tests do not all prove the no-write property claimed for them.** `tests/test_install_writer.py::TestShapesThatWouldBeSilentlyDropped::test_a_tools_value_that_is_not_an_array_is_refused` checks only that an exception is raised, unlike the neighboring trigger and reserved-name tests; it would pass if the config were modified and an error raised afterward. `tests/test_install_main.py::TestNothingIsWrittenWhenTheMergeIsRefused` covers only the older top-level invalid `hooks` shape, not the newly added nested hook, non-list `tools`, or reserved array-name refusals, even though round 2 specifically requested both writer- and `main()`-level byte-identity coverage. Add the missing before/after assertion and parameterize whole-project snapshots over all three new refusal shapes.

VERDICT: NEEDS_CHANGES

---

## Round 4 — 2026-08-03

**Summary judgment:** All four Round 3 fixes are present, and the 1,418-test gate is clean; the private-store check, structural hook comparison, descriptor-based writes, no-replace backup publication, and expanded no-write assertions address those findings as stated. What remains is not merely theoretical hardening: a symlinked agent config is silently severed, ordinary shipped-path obstructions can produce either false success or a half-install, and the atomic writer can still publish a short write or an incompletely flushed backup. Those are proportionate to fix before shipping; the residual scratch-name publication race is not, because a process able to replace names in that directory can already replace the target directly.

1. **[BLOCKER] Passing a symlink as `--agent` silently destroys the symlink instead of merging into or refusing it.** `zikaron/install/main.py::_install` accepts it because `Path.is_file()` follows the link, and `zikaron/install/writer.py::_load_agent_config` and `_copy_atomically` likewise read/copy the referent; but `_replace` finally calls `scratch.path.replace(path)`, which replaces the symlink directory entry itself. A user managing `.kiro/agents/<agent>.json` as a symlink therefore gets exit 0 and a new local regular file, while the dotfile-managed source remains unmodified and disconnected. This is distinct from Round 1's accepted symlinked-ancestor case: writing through a symlinked directory preserves that setup, whereas replacing the final symlink destroys it. Refuse a symlinked `--agent` during preflight (simplest and consistent with the shipped-target policy), or deliberately resolve and atomically update the referent while preserving the link; add a `main()` regression asserting the link, referent, and whole project remain unchanged on refusal.

2. **[BLOCKER] The installer still does not preflight the two shipped artifact paths, so existing filesystem shapes can yield false success or a half-install.** In `zikaron/install/writer.py::_write_shipped`, an existing directory at `.kiro/skills/zikaron-consolidate/SKILL.md` is treated as an ordinary collision and reported as “kept”; `main()` exits 0 although no loadable skill exists. Conversely, if `.kiro/skills` or `.kiro/skills/zikaron-consolidate` is a regular file, the consolidator config is written first and the later `path.parent.mkdir(...)` raises `FileExistsError`/`NotADirectoryError`; `zikaron/install/main.py::main` catches only `InstallError`, so the user gets a traceback and a partial install. These are predictable path-shape failures, not an uncloseable crash-between-renames window, and they violate the module's explicit “check everything, then write everything” boundary in a way that can affect an existing project. Plan/validate both shipped targets before publishing either: refuse non-regular final targets and non-directory ancestors (with an `InstallError`), then add command-level snapshots for the false-success and write-first/fail-second cases.

3. **[BLOCKER] The descriptor-based writer does not yet guarantee that all bytes reached the inode before publishing it.** `zikaron/install/writer.py::_replace` calls `os.write(...)` once and ignores its return value, although a regular-file write may legally be short—for example when only part of the requested space remains—so it can rename a truncated JSON file over the user's config and report success. `_copy_atomically` also passes a temporary buffered `os.fdopen(..., closefd=False)` object directly to `shutil.copyfileobj` without an explicit context/flush; a failure while that temporary object is finalized is not a reliable exception boundary before `os.link` publishes the purported pristine backup. This reopens the full-disk/partial-write failure the atomic rewrite was introduced to close. Write in a checked loop or through an explicitly managed binary file object, explicitly flush/close it before publication (and surface any failure), and add fault-injection tests for a short `os.write` and a backup flush failure proving that neither destination is published or replaced.

VERDICT: NEEDS_CHANGES
---

## Author response to round 4 — 2026-08-03

All three accepted and implemented. The round's own judgment — that these are proportionate to fix and
that the residual scratch-name publication race is not, because a process able to replace names in that
directory can already replace the target — is the same line I would draw, and it is recorded here as the
stopping point rather than left implicit.

**1 — accepted.** A symlinked `--agent` is now refused in the preflight, and the message names the file
it resolves to so the user can point at that instead. The distinction the finding drew is the right one
and is now stated in the code: writing *through* a symlinked directory preserves that setup, while
publishing an atomic rewrite replaces the final directory entry and would sever a config managed as a
link into a dotfile repository — silently, with the install reporting success. A `main()`-level test
asserts the link, the referent and the whole project are untouched.

**2 — accepted.** `guard_shipped_targets` runs in the preflight and refuses a final target that exists
and is not a regular file, and any ancestor within the project that exists and is not a directory. That
closes both halves the finding named: the directory-at-`SKILL.md` case that exited 0 while no loadable
skill existed, and the file-where-`.kiro/skills`-belongs case that wrote the consolidator config and
*then* raised `NotADirectoryError`. `main()` additionally maps a stray `OSError` — a full disk, a
revoked permission mid-run — to a reported failure instead of a traceback, since the predictable shapes
are now refused and what is left is genuinely unexpected. Three command-level tests.

**3 — accepted.** `_write_all` loops until every byte is written, raises rather than publishing if a
write makes no progress, and `fsync`s before the caller renames or links — the rename is atomic against
other processes and says nothing about a crash. Both writers go through it, so the backup copy is
covered by the same guarantee, and `shutil.copyfileobj` into a buffered `fdopen` is gone entirely rather
than being given a flush. Two tests: a write that goes short and then fails publishes nothing and leaves
no scratch file, and a write that goes short but completes across calls publishes a whole, parseable
file — the second being the half a "raises on short write" test alone would let regress into refusing
every legal short write.


---

## Round 5 — 2026-08-03

**Summary judgment:** The Round 4 changes are present, and the clean 1,423-test gate confirms the intended ordinary cases. The loop has not converged: the shipped-path preflight still misses dangling symlinks, explicit JSON `null` still bypasses the accepted shape/collision refusals, the policy reader validates one directory inode and can read through another, and `--agent` can alias the consolidator config and convert it into a primary-agent config. Each can harm a real install rather than merely harden an implausible edge.

1. **[BLOCKER] `guard_shipped_targets` still misses dangling and non-regular symlinks, preserving both Round 4 failure modes.** In `zikaron/install/writer.py::guard_shipped_targets`, the final-target condition explicitly excludes every symlink, while the ancestor condition begins with `ancestor.exists()`; `Path.exists()` is false for a dangling symlink. Consequently a dangling `SKILL.md` symlink, or one pointing to a directory, reaches `_write_shipped`, is reported as “kept,” and lets `main()` exit 0 although no loadable skill file exists. A dangling `.kiro/skills` or `.kiro/skills/zikaron-consolidate` symlink also passes preflight; the consolidator config is then published first and the later skill write fails, leaving the half-install the accepted fix was meant to prevent. `tests/test_install_main.py::TestPathShapesThatWouldOtherwiseLieOrCrash` covers only a literal directory at the final path and a literal file at an ancestor, while `tests/test_install_writer.py::test_a_symlink_at_the_target_is_treated_as_existing_rather_than_followed` uses a symlink to a regular file and never exercises `main()`. Treat a path that exists **or is a symlink** as occupied: refuse a final target unless it resolves to a regular file (preserving symlinks to regular files if that remains intentional), and refuse an ancestor unless it resolves to a directory. Add command-level regressions for a dangling/non-regular final symlink (exit 1, not “kept”) and a dangling skill ancestor (whole-project snapshot unchanged).

2. **[BLOCKER] The policy reader validates the store directory by pathname, then resolves that pathname again to read the override.** `zikaron/hook/write_policy.py::_store_directory_is_private` calls `store_directory.stat()`, returns, and `read_policy` later calls `_read_regular_file(store_directory / "write-policy.md")`. The descriptor-based final-component check is sound, but it does not pin the directory that passed the ownership/mode check: in a writable project parent, another local UID can replace that directory between the two operations, or create an attacker-owned `.zikaron` after the initial `ENOENT` path (which currently returns `True`), and the subsequent open accepts an ordinary regular policy from the unchecked replacement. That text is printed directly into model context even though the service will refuse the foreign/insecure store. The static symlink and `0777` tests in `tests/test_hook_write_policy.py` cannot exercise this check/use split. Open `.zikaron` once with directory/no-follow semantics, validate ownership and mode with `fstat`, and open `write-policy.md` relative to that held directory descriptor with `O_NOFOLLOW`; if the directory is absent, return the shipped policy immediately rather than resolving a child afterward. Add deterministic races that replace a previously private directory and create one after the absent check, proving attacker text is never returned.

3. **[BLOCKER] Explicit JSON `null` values bypass the shape and collision refusals and are silently replaced.** `zikaron/install/writer.py::_detect_format`, `_guard_mergeable_shapes`, and `_guard_existing_entries` all use `document.get(...)` plus `is not None`, conflating an absent key with a present `null`. Thus `"hooks": null`, `"tools": null`, or `"mcpServers": null` is overwritten despite the accepted rule that a present unmergeable value is refused rather than dropped. The same sentinel mistake exists one level down: `"mcpServers": {"zikaron": null}` bypasses `existing_server is not None` and is replaced without `--force`, although the install contract refuses any existing Zikaron server entry that differs. The current invalid-shape tests use strings, integers, lists, or objects, so all pass while the property they name is false for JSON's fourth scalar. Test key presence separately from value (`key in document`, and `MCP_SERVER_NAME in servers`), refuse these values, and add writer byte-identity plus `main()` whole-project snapshot cases for each explicit-null shape.

4. **[BLOCKER] `--agent` can name the consolidator config that the same invocation also owns, and the install exits 0 after breaking consolidation.** `zikaron/install/main.py::_install` does not require the user-owned merge target to be distinct from `Targets.consolidator_config`. If a user passes the existing `.kiro/agents/zikaron-consolidator.json` (a plausible selection from the agents directory), `plan_merge` builds a primary-agent document from it; `write_shipped_files` keeps or rewrites that same path; then `commit_merge` publishes the earlier primary merge over it. The resulting file retains the consolidator identity/prompt but runs `zikaron-mcp --mode primary` and gains primary hooks, so the prompt's first `zikaron_next_group` call is unavailable. Refuse an `--agent` path that is the same file as either shipped target (and guard aliases robustly with canonical/same-file comparison), before any write; add a command-level whole-project snapshot proving the tracked consolidator config cannot be selected as the primary merge target.

VERDICT: NEEDS_CHANGES
---

## Author response to round 5 — 2026-08-03

All four accepted and implemented. Three of them are user-visible with no attacker present, so this
round was not narrowing into theory and the loop was right to continue.

**1 — accepted.** `_occupied(path)` is now `exists() or is_symlink()`, and both preflight conditions read
"occupied, and not the kind it must be" — so a dangling `SKILL.md` link, a link to a directory, and a
dangling `.kiro/skills` link are all refused instead of one being reported as "kept" (exit 0, no loadable
skill) and the other producing a half-install. Two command-level regressions, the ancestor one asserting
the whole project tree is byte-identical.

**2 — accepted.** The check/use split is gone: `_read_override` opens `.zikaron` once with
`O_DIRECTORY | O_NOFOLLOW`, checks ownership and mode on **that descriptor** (`_require_private`), and
opens the override relative to it with `dir_fd=` and `O_NOFOLLOW`. Every check now applies to the inode
that is read. An absent store raises before any child is looked at, which also closes the
"accepted-as-absent, then created" path the finding named. Tested by wrapping `_require_private` to
replace the directory inside the window — deterministic rather than raced, so it cannot pass on timing —
and asserting the attacker's text never comes back.

**3 — accepted.** Presence is now tested with `in` rather than against `None`, at all four sites: `hooks`,
`tools`, `mcpServers`, and `mcpServers.zikaron`. This was the "correct about the case it names, silent
about the set it implies" shape in miniature — JSON's fourth scalar. Four parameterized refusal tests,
each asserting the file is byte-identical afterwards.

**4 — accepted.** `--agent` naming either shipped target is refused before any write, compared by resolved
path since `--project .` makes two spellings of one file likely rather than exotic. The outcome it
prevents is worth stating: the consolidator's own config merged into a *primary* agent, keeping its
identity and prompt while running `--mode primary`, so the first `zikaron_next_group` its prompt instructs
has no tool behind it — and the install reporting success. A command-level snapshot test proves the
tracked consolidator config cannot be selected.

---

## Round 6 — 2026-08-03

**Summary judgment:** All four Round 5 fixes are present, and the stated 1,432-test gate is clean. The milestone is still not ready to ship: the installer writes an absolute executable path into a field the harness executes as a shell command without quoting it, so an ordinary checkout or venv path containing spaces passes every preflight and then loses both hooks at runtime. This is a no-attacker, real-user failure above the recorded stopping line.

1. **[BLOCKER] Hook command paths are emitted unquoted even though the harness executes them as shell commands.** `zikaron/install/entries.py::_object_entry` and `::_array_entry` serialize `str(hook_command)` directly; both `design/architecture.md` §“The install contract” and `research/kiro-cli-hooks-and-introspect.md` §“Nesting and per-entry fields” explicitly say this field is run as a shell command. For an entirely ordinary install under a path such as `/home/me/My Projects/Zikaron/.venv/bin/zikaron-hook`, `Commands.missing()` sees an executable file and installation exits 0, but the shell tries to execute `/home/me/My` with the remainder as arguments; `agentSpawn` therefore injects no write policy and `userPromptSubmit` injects no memories. Shell metacharacters in a directory name are interpreted as well. `tests/test_install_e2e.py::_run_hook` cannot catch this because it invokes `[command]`, treating the complete JSON string as one executable pathname rather than using the harness's shell semantics. Shell-quote the hook executable with `shlex.quote` in both hook formats (leave `mcpServers.*.command` as the raw executable path because that is a program field), update stale-hook recognition to parse the quoted single-command form safely, and add a regression whose scripts directory contains spaces and shell metacharacters and which executes the installed hook command through `/bin/sh -c` or the real harness.

VERDICT: NEEDS_CHANGES

---

## Author response to round 6 — 2026-08-03

**Accepted, and measured before fixing.** The finding's premise decided the shape of the fix, so it was
tested against the real harness rather than reasoned about. A throwaway agent config with two hooks:

- `agentSpawn`: `cat >/dev/null; echo shell-syntax-worked > /tmp/.../shell.marker` — the marker
  appeared, so the field genuinely is shell source, not an argv.
- `userPromptSubmit`: a script at `/tmp/.../my scripts/hook.sh`, first single-quoted and then bare.
  Quoted, it ran. Bare, the harness reported
  `✗ userPromptSubmit ".../my scripts/hook.sh" failed with exit code: 127, stderr: /bin/bash: line 1:
  /tmp/zk_shellprobe/my: No such file or directory` and the script never ran.

So: `/bin/bash -c`, and an ordinary project under a path with a space loses both hooks while the install
exits 0. `entries.hook_command_string` now applies `shlex.quote` for both formats, and
`writer._entry_command` unquotes with `shlex.split` — otherwise stale-entry recognition would compare
`Path("'/x/zikaron-hook'").name` and match nothing. `mcpServers`' `command` stays raw, as the finding
says, because that field takes a program plus a separate `args` array.

Two test changes, and the first is the more important: `tests/test_install_e2e.py::_run_hook` now runs
the command **through a shell**, because passing `[command]` to `subprocess.run` is a different
execution model that cannot see this class of defect at all — the review's point about why the existing
end-to-end coverage was blind to it. Then a new command-level regression installs with a scripts
directory named `My Projects (v2)/bin`, and runs the written `command` string through `/bin/sh -c`,
asserting the hook actually executed.

One incidental measurement worth keeping: the harness **does** surface a failing hook to the user
(`✗ ... failed with exit code: 127, stderr: ...`). So this particular failure was loud in the TUI even
while being invisible to the install — which is a mitigation, not a defence, since the policy and the
memories are gone either way.

## Round 7 — 2026-08-03

**Summary judgment:** The Round 6 fix is present and correctly follows the measured harness semantics: both hook formats shell-quote the executable, stale-entry recognition parses the single-command form, the MCP program field remains raw, and command-level plus end-to-end coverage now execute hooks through a shell. After reviewing all prior rounds and the current distribution paths, I found nothing left that a real user is likely to hit or that an attacker lacking pre-existing write access to the relevant files could exploit; the stated 1,435-test, 98% gate is clean, so this milestone is ready to ship.

**Findings:** None.

VERDICT: APPROVED
