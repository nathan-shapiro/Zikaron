# pgrep/pkill ancestor exclusion, per platform (input to M38's deny-or-allow rule)

Researched 2026-10-11 by memory-assistant for memory-researcher. No shell was available in this
session, so **nothing below was run on a machine**: every behavioural claim is read from a man
page, source file, changelog or package listing and is labelled with how it was established.
Where a claim rests on code reading rather than an observed run it says so, and anything I could
not establish is marked **UNVERIFIED**.

## 1. The brief, restated

Zikaron M38 is a deterministic Claude Code PreToolUse hook that refuses a `pgrep -f` or `pkill -f`
whose pattern would match its own command line. Claude Code runs a Bash command as
`bash -c '... eval '<command>' && pwd -P >| ...'`, so the calling shell stays alive with the
command text in its argv. On the measured Linux machine (procps-ng 4.0.4), `pgrep -f PAT` matches
that shell and `pkill -f PAT` kills it; procps-ng's `-A`/`--ignore-ancestors` removes the match.
The guard ships on Linux and macOS arm64 (D35), so the deny rule, and the fix the deny message
recommends, depend on per-platform facts: does the platform exclude ancestors by default, is there
a flag to do so, and what does `-a` mean there. Six questions were asked (macOS, FreeBSD, the
procps-ng `-A` release and semantics, packaged versions, procps-ng's default self-only
exclusion, upstream discussion). A follow-up asked what macOS's `-l` does (answered in section 3).

## 2. Answer in one table

"Default" = what happens with no flag. "Source" numbers refer to the list at the end.

| Platform (version) | Default ancestor exclusion | Flag to exclude ancestors | Meaning of `-a` | Source |
|---|---|---|---|---|
| Linux procps-ng >= 4.0.1 (Ubuntu 24.04 and 26.04, Debian 12 and 13, Fedora 43+, RHEL 10, Alpine `procps-ng` pkg) | **Self only.** Ancestors, including the calling shell, are matchable | `-A` / `--ignore-ancestors` (whole PPID chain) | `pgrep -a`: list PID and full command line (output only; no effect on matching). `pkill -a`: not in pkill's option string, so rejected (code reading) | S1, S2, S4, S6, S9 |
| Linux procps-ng 3.3.17 (Ubuntu 22.04, RHEL 9, CentOS Stream 9, Debian 11) | **Self only** | **None.** `-A` is absent from the option string and the man page | same as above | S5, S11, S12, S15, S19, S20 |
| Alpine / BusyBox pgrep (busybox 1.38.0-r7 on edge; 1.37.0 source read) | **Self only** (`proc->pid == pid`); no parent/ancestor logic anywhere in the scan loop | **None** | `-a`: show command line too (output only). `-f` is supported and matches the whole cmdline | S21, S22, S23 |
| macOS 26.5 (adv_cmds-237); man page text identical at adv_cmds-235 (macOS 15.6) | **Self AND every ancestor** (whole PPID chain, from `getppid()` upward) | none needed; **no `-A` exists** (not in the getopt string) | **`-a`: include process ancestors in the match list**, i.e. it turns the protection OFF. (`-l` is output formatting only; section 3) | S24 to S29 |
| FreeBSD 15.0 `pkill(1)` | Same as macOS (same NetBSD-derived code) | none; no `-A` | `-a`: include ancestors | S30 to S33 |
| GitHub `ubuntu-latest` | Ubuntu 24.04 today (procps 4.0.4); **migrates to Ubuntu 26.04 between 2026-10-19 and 2026-11-19** (procps 4.0.4-9ubuntu1). Both have `-A` | `-A` | Linux semantics | S34 to S36 |
| GitHub `macos-latest` | macOS 26 arm64 | n/a | macOS semantics | S34 |

Consequences, stated as inference from the table and not as a source claim:

- A platform-blind rule "deny `pgrep|pkill -f` unless `-A`" is **wrong on macOS twice over**: it
  denies a command that is already safe, and the fix it recommends (`-A`) is an unknown option
  there (the getopt string at S25 has no `A`; the failure mode is presumably a usage error, not
  tested).
- On macOS the *dangerous* spelling is `-a` (`pgrep -af PAT`, `pkill -af PAT`, `pgrep -fa`), which
  re-includes the calling shell. On Linux the same letters are harmless to ancestor matching and
  the danger is the *absence* of `-A`.
- On procps-ng 3.3.17 and BusyBox there is no ancestor flag at all, so a deny message that says
  only "add `-A`" sends the agent to a command that fails there. The portable fix is to change the
  pattern, not the flags (section 10).

## 3. Q1 - macOS pgrep/pkill

**Does it exclude its own ancestors by default? Yes.** The current man page (macOS 26.5 ships
adv_cmds-237, S24, S26) says, for `-a`: "Include process ancestors in the match list. By default,
the current pgrep or pkill process and all of its ancestors are excluded (unless -v is used)."
(S24; identical text at adv_cmds-235 per S27, in the `main` branch per S28, and in the Xcode man
page set per S29). The `.Dd` date is 2020-10-05.

**Mechanism, from `pkill.c` at adv_cmds-237 and `main` (S25, S28).** `case 'a': ancestors++;`.
After matching, `if (!ancestors) { pid = mypid; while (pid) { ... } }` walks the process table:
the inner loop skips `mypid` itself (`PSKIP`), so on the first pass nothing is found for `mypid`
and the code does `pid = getppid()`; every later pass finds the row whose pid equals `pid`, sets
`selected[i] = 0` and moves to that row's parent pid (`SYSMON_ATTR_PROC_PPID` on Apple,
`ki_ppid` elsewhere). The walk ends at pid 0, or breaks if a pid in the chain is not in the table.
So it is the **full PPID chain**, not just the parent. The code is the NetBSD 1.6 pkill (header
`$NetBSD: pkill.c,v 1.16 2005/10/10`) with FreeBSD's 2009 ancestor patch (section 4) and Apple's
sysmon port.

**What `-a` means on macOS: "include process ancestors"** - your belief is confirmed by the man
page text above and by `case 'a': ancestors++`. It is the opposite of Linux's `-a`
(`--list-full`).

**Does `-f` match the full argument list? Yes.** Man page: "Match against full argument lists.
The default is to match against process names." (S24). In the Apple code the argument vector comes
from `SYSMON_ATTR_PROC_ARGUMENTS` and is joined with single spaces (`"%s "` format) before
`regexec` (S25).

**What `-l` does on macOS (follow-up; VERIFIED against the adv_cmds-237 man page source).** The
`.It Fl l` entry in `pkill/pkill.1` at tag adv_cmds-237 reads, with the roff markup removed: "Long
output. For pgrep, print the process name in addition to the process ID for each matching
process. If used in conjunction with -f, print the process ID and the full argument list for each
matching process. For pkill, display the kill command used for each process killed." (S24, read
from the raw source; the same sentence rendered from the Xcode man page set, S29, two independent
fetches.) The coordinator's recollection held, with two differences of wording: the real text says
"for each matching process" after both clauses, and the `-l` entry also covers `pkill`, where it
shows the kill command used. **Reading for the guard (inference):** `-l` is an output-format flag
and, per the man page, has no effect on which processes match, so `pgrep -lf PAT` on macOS keeps
the default ancestor exclusion and is as safe as `pgrep -f PAT`; `-lf` on macOS corresponds to
Linux's `-a` (full command line), while macOS's `-a` corresponds to nothing on Linux. I did not
read the `case 'l'` code to confirm it touches only output (UNVERIFIED at code level). The
usage string in the Apple source is `[-Lfilnoqvx] [-d delim]` for pgrep, and `l` is in the getopt
string (S25).

**Does it exclude the parent shell inside `$( ... )` or a pipeline? By code reading, yes; I did not
run it (UNVERIFIED empirically; no macOS host).** The walk starts at `getppid()` and follows
PPIDs to the root, so every process on the path from pgrep up to launchd is deselected, which
covers: the forked subshell of `$( ... )` (whether or not bash exec'd pgrep into it), the main
shell, a `timeout` or `sudo` wrapper, and Claude Code's `zsh -c ... eval '...'` wrapper. Pipeline
stages are *siblings*, not ancestors, so `pgrep -f foo | grep foo` can still match the `grep`
sibling; this holds on every platform, with or without `-A` (inferred from the same logic).

**Caveats.** (a) The man page says ancestors are excluded "unless -v is used"; I did not trace
whether the ancestor block is ordered before or after inversion, and FreeBSD's 2025 rewording
(S32) says `-a` does not unhide the process itself "even with -v". Irrelevant to a `-f PAT` guard
unless `-v` is in the command. (b) Apple's `PSKIP` also skips processes flagged as system
(`PROC_FLAG_SYSTEM`); a PPID chain that passed through one would be cut there. I did not find a
real chain where that matters. (c) No `-A` in the Apple getopt string
`"DF:G:ILP:U:ac:d:fg:ilnoqt:u:vx"`.

## 4. Q2 - FreeBSD pkill(1)

- Current text (FreeBSD 15.0-RELEASE, page dated 2025-06-24, S30): `-a` "Include process
  ancestors in the match list. By default, the current pgrep or pkill process and all of its
  ancestors are excluded." No `-A`. Also: "a running pgrep or pkill process will never consider
  itself nor system processes (kernel threads) as a potential match."
- **Introduced 2009-05-17** by Brian Somers, commit `0a091aeb` (S31). The commit message is a
  near-exact description of the Claude Code problem: it says ignoring ourself and our ancestors
  was added because "It is almost always surprising when you kill a 'sh -c ...' ancestor or when
  you kill yourself when using -f." The same commit added the `ancestors` variable, the
  ancestor-walk loop and the `-a` switch "for backwards compatibility" (summary from the commit page).
- 2025-06-24, Kyle Evans, commit `88a2d48d` "pkill: better document ancestor-hiding" (S32): moves
  the statement into the pgrep and pkill DESCRIPTION paragraphs and adds that `-a` will not
  "unhide" the pgrep/pkill process itself, even with `-v`.
- Which FreeBSD release first shipped the 2009 change: **UNVERIFIED** (head commit in 2009-05; I
  did not check branch/MFC history).
- History line (S30): pkill/pgrep first appeared in NetBSD 1.6, modelled on Solaris 7, first in
  FreeBSD 5.3. The NetBSD-derived code header in S33 predates the ancestor logic, so the BSD
  ancestor behaviour is FreeBSD's 2009 addition, which Apple inherited (whether NetBSD itself
  later added it was not checked).

## 5. Q3 and Q5 - procps-ng `-A`, and what the default excludes

**Release that introduced `-A`: procps-ng 4.0.1** (tag dated 2022-10-20, S3 tags page). NEWS entry
under the `procps-ng-4.0.1` heading (S1): "pgrep: Add -A to ignore ancestors" with the tracker tag
`merge #160`. The only NEWS line about ancestors in the file.

**Development history** (S7, S8, S9):
- MR !160, Chris Down, opened 2022-08-10, merged 2022-08-31 by Craig Small: "pgrep: Add support
  for ignoring ancestors with -A/--ignore-ancestors". First revision checked only one level of
  the hierarchy.
- MR !162, Chris Down, merged 2022-09-01: "pgrep: Look at all ancestors in --ignore-ancestors".
  Its whole description: "Previously we mistakenly only checked one previous level of the
  hierarchy." Both merges precede the 4.0.1 tag, so **every released `-A` (4.0.1 onward) walks the
  whole chain**. I confirmed the loop in the v4.0.1 tag's `pgrep.c` (S4) and v4.0.4 (S2).

**Precise semantics (v4.0.4 `src/pgrep.c`, S2).** `get_our_ancestors()` starts with
`search_pid = getpid()`, then repeatedly scans the whole process table (`procps_pids_get`) for the
task whose PID equals `search_pid`, appends that task's `PPID` to a list and makes it the next
`search_pid`; it stops when no task matches (after pid 1's parent 0). The list holds every
ancestor from the parent upward. `case 'A': opt_ignore_ancestors = get_our_ancestors();`. In
`select_procs()`: `if (PIDS_GETINT(PID) == myself) continue; else if (opt_ignore_ancestors &&
match_numlist(PIDS_GETINT(PID), opt_ignore_ancestors)) continue;`.
Consequences (code reading): the walk is by real PPID chain from the pgrep process, so a forked
subshell running `$(pgrep -A ...)` and the shell above it are both ancestors and both excluded;
`sudo`, `timeout`, `env`, container shims likewise (the commit message says that was the point).
Not excluded: non-ancestors, e.g. pipeline siblings, background jobs, or a process reparented
away from the chain. The list is built once at option-parse time, and it is empty (no exclusion)
if the flag is absent.

**Man page (S6):** "Ignore all ancestors of pgrep, pkill, or pidwait. For example, this can be
useful when elevating with sudo or similar tools." Not versioned in the page itself. Help text:
` -A, --ignore-ancestors    exclude our ancestors from results`. The man pages for Debian 12
(footer 2022-08-31, S16), Debian 13 (2023-01-16, S17) and Ubuntu 24.04 (S15) all carry it;
Ubuntu 22.04's does not (S15).

**Q5: by default procps-ng excludes only itself - confirmed.**
- Man page NOTES (S6, S15, S16): "The running pgrep, pkill, or pidwait process will never report
  itself as a match."
- Code: `if (PIDS_GETINT(PID) == myself) continue;` with `myself = getpid()` (S3, S2); the 3.3.17
  equivalent is `if (task.XXXID == myself) continue;` with `pid_t myself = getpid();` (S5).
- `-f`: man page "The pattern is normally only matched against the process name. When -f is set,
  the full command line is used." (S6). Code: `opt_full` selects the task's full cmdline for
  `cmdsearch` instead of the `CMD` string (S3).
- `-a`: "List the full command line as well as the process ID. (pgrep only.)" (S6). In
  `parse_opts` the string `"lad:vw"` is appended only for pgrep, `"eq:"` for pkill, `"e"` for
  pidwait (S2), so **`pkill -a` is not an accepted option on procps-ng** (code reading, not run).
  `case 'a': opt_longlong = 1;`.

## 6. Q4 - packaged procps-ng versions

| Distro | procps version | Has `-A`? | Listing |
|---|---|---|---|
| Ubuntu 22.04 jammy | 2:3.3.17-6ubuntu2.1 (security and updates) | **No** | S12, S13 |
| Ubuntu 24.04 noble | 2:4.0.4-4ubuntu3 (release pocket); 2:4.0.4-4ubuntu3.3 in noble-updates (2026-08-26) | Yes | S12, S13 |
| Ubuntu 26.04 resolute | 2:4.0.4-9ubuntu1 | Yes | S12 |
| Debian 11 bullseye | 2:3.3.17-5 | No | S15 |
| Debian 12 bookworm | 2:4.0.2-3 | Yes (man page checked) | S14, S16 |
| Debian 13 trixie | 2:4.0.4-9 | Yes (man page checked) | S14, S17 |
| Debian sid / testing | 2:4.0.7-1 | Yes | S14, S15 |
| Fedora 43 / 44 / 45 / Rawhide | 4.0.4-7.fc43.1 / 4.0.6-1.fc44 / 4.0.6-2.fc45 / 4.0.7-1.fc46 | Yes (by version) | S18 |
| RHEL 9 | procps-ng 3.3.17 (RHSA-2023:6705 ships 3.3.17-13.el9; Rocky 9 BaseOS carries 3.3.17-14.el9; CentOS Stream 9 spec is 3.3.17-15) | **No**: the stream spec's patch list and changelog contain nothing about ancestors | S19, S20, S11 |
| RHEL 10 (CentOS Stream 10 spec) | 4.0.4-13 | Yes (by version; no ancestor patch needed) | S20 |
| Alpine | BusyBox provides `pgrep`/`pkill` by default (busybox 1.38.0-r7 on edge). `procps-ng` is an optional package: 4.0.4-r3 on v3.22, 4.0.7-r2 on edge | BusyBox: no. procps-ng package: yes | S21 |
| GitHub `ubuntu-latest` | Ubuntu 24.04.5 image 20261004.327.1 now (procps 4.0.4); Ubuntu 26.04 (procps 4.0.4-9ubuntu1) from the migration | Yes | S34 to S36 |

Latest upstream procps-ng release is 4.0.7 (2026-08-12) per the tags page (S3).

Gaps: I did not retrieve an exact RHEL 9 NVR from Red Hat's own current package catalogue (login
walled); the version rests on Red Hat's 2023 advisory plus the Rocky and CentOS Stream
artefacts, which agree on the 3.3.17 base. I did not check Alpine's stable branches beyond v3.22
for `procps-ng`, nor Fedora 42 and earlier. The "Has -A" column is derived from the version
(introduced 4.0.1) except where a man page was read.

Cumulative reading: of the Linux targets in the brief, **Ubuntu 22.04, RHEL 9 (and its rebuilds)
and Alpine's default pgrep lack `-A`**, so a `-A` recommendation fails there.

## 7. BusyBox (Alpine) in detail

Source read: BusyBox 1.37.0 `procps/pgrep.c` from Debian's source mirror (S23), cross-checked
against the GitHub mirror and Elixir (S22). The scan loop has exactly one identity skip,
`if (proc->pid == pid) continue;` with `pid = getpid()`. The only other per-process tests are the
user-supplied `-P` (parent pid) and `-s` (session) filters. There is no ancestor or parent
exclusion, so **BusyBox `pgrep -f PAT` and `pkill -f PAT` match and kill the calling shell** just
as procps does (code reading). `-f` is supported: it sets `PSSCAN_ARGVN`, and the full argv
(control bytes mapped to spaces) is what the regex runs against. Usage strings:
`pgrep [-flanovx] [-s SID|-P PPID|PATTERN]` (here `-a` = "Show command line too", `-l` = "Show
command name too") and `pkill [-l|-SIGNAL] [-xfvnoe] [-s SID|-P PPID|PATTERN]` (an older doc page,
S21, lacks the `-a`). Neither is an ancestor flag.

## 8. Q6 - upstream discussion

- **The only upstream record found is MR !160 itself** (S7), whose description is the
  motivation. Quotes (short): the problem is that "the elevating shim layers linger as a parent
  and are returned in the results", demonstrated with `sudo pkill -9 -cf someelevatedcmdline`
  killing the invoking `sudo`; "This is a situation we've actually seen in production"; and the
  fix "excludes pgrep's ancestors from the results". The justification for walking the whole
  chain is that mechanisms in Docker or Kubernetes "may have many more" shim layers. It is
  framed around `sudo`/`doas`, **not around `sh -c` or `eval` wrappers**, though the mechanism
  (an ancestor's argv contains the pattern) is identical. The MR has 4 notes; the notes endpoint
  needs authentication (HTTP 401) and the HTML MR page returned 403 to my fetcher, so the
  review discussion was **not read** (UNVERIFIED what the maintainer said).
- I searched the procps-ng issue tracker through the GitLab API for `ancestors`, `pkill -f`,
  `pgrep parent`, `pgrep itself`, `sudo`, and listed merge requests matching `pgrep`. No issue
  reports "pgrep -f matches the calling shell" as such. Nearest hits, none on point: #406
  (closed 2025-12-19) is about the `--help` wording of `-f`; #142 is a feature request for
  descendant matching. No mailing list for procps-ng was found.
- **The FreeBSD 2009 commit message (S31) is the clearest statement of the problem in primary
  sources**: killing a `sh -c ...` ancestor, or yourself, when using `-f` was "almost always
  surprising". It predates procps-ng's fix by 13 years and is why BSD hides ancestors by default
  while procps made it opt-in.
- Related real-world precedent, seen only in a search result and not fetched: monitoring-plugins'
  `check_procs` has a commit "ignore plugin parent process" (2013), the same class of problem in
  a plugin that scans for its own parent.

## 9. Method notes and evidence quality

- **Tooling.** WebSearch and WebFetch only. WebFetch answers come from a small model summarising
  the page, so a quoted line is the summariser's rendering of the source. Where a claim carries
  weight I fetched it more than once or from two independent places: the macOS `-a` sentence
  appeared identically in five fetches (Apple repo `main`, tags adv_cmds-237 and -235, Xcode man
  page set, a search snippet); the macOS `-l` entry in two (adv_cmds-237 raw roff source and the
  Xcode man page set); the procps `get_our_ancestors()` body came from v4.0.4 and its loop
  was re-checked at v4.0.1; the BusyBox loop came from Elixir, the GitHub mirror and Debian's
  copy. I did not obtain a verbatim, line-by-line view of the whole 4.0.4 `pgrep.c`.
- **Strong evidence (primary, version-pinned):** NEWS 4.0.1 line; MR !160 and !162 text; procps
  4.0.4 `get_our_ancestors()`; FreeBSD 2009 commit message; FreeBSD 15.0 man page; Apple
  adv_cmds-237 man page and `pkill.c`; BusyBox 1.37.0 source; Debian and Ubuntu package pages.
- **Code-reading only, never run (UNVERIFIED as behaviour):** that macOS excludes the subshell and
  shell in `$( ... )` and pipelines; that `pkill -a` is rejected on procps-ng; that `-A` on macOS
  yields a usage error; that BusyBox and 3.3.17 reject `-A`; that BusyBox kills the calling shell;
  that macOS `-l` affects output only (man page says so; `case 'l'` not read).
- **Not verified:** the FreeBSD release carrying the 2009 change; Apple's behaviour before
  adv_cmds-235; macOS 26.0 through 26.4 (only 26.5 mapped to adv_cmds-237, via
  `distribution-macOS` tag `macos-265`; macOS 15.6 via `macos-156` maps to adv_cmds-235);
  RHEL 9's exact current NVR from Red Hat; Alpine stable busybox and `procps-ng` versions beyond
  those listed; the MR !160 review notes.
- **Date caveat.** The tags page, Debian, Fedora and GitHub changelog pages were read on
  2026-10-11; versions and the `ubuntu-latest` mapping will drift (the migration window opens
  eight days after this note).

## 10. Implications for M38 (proposals, labelled as inference)

1. **The deny rule must be platform-aware.** On procps-ng and BusyBox the unsafe command is
   `-f` (without `-A` where `-A` exists); on macOS and FreeBSD it is `-f` *together with* `-a`,
   and plain `-f` (or `-lf`) is already safe. A platform-blind "deny `-f` without `-A`" is a false
   positive on every macOS `pgrep -f`/`pkill -f`. The options are a per-platform rule, or a
   conservative rule that tolerates macOS false positives and recommends a fix valid there too
   (item 2).
2. **The recommended fix cannot be `-A` alone.** `-A` works on procps-ng >= 4.0.1 only (Ubuntu
   24.04 and 26.04, Debian 12 and 13, Fedora, RHEL 10, the Linux CI runner). It is absent on
   Ubuntu 22.04, RHEL 9, Alpine's BusyBox and every macOS. The portable remedy is to make the
   pattern fail to match its own text: write one character of the pattern as a bracket class, so
   `pgrep -f '[f]oo'` rather than `pgrep -f 'foo'`; the command line then contains `[f]oo`, which
   the regex `[f]oo` does not match because of the `]`. This is general shell folklore and
   reasoning, **not something I read in a cited source or ran in this session**; it also fails if
   the same command text carries the unbracketed pattern elsewhere. Worth a measurement before
   it goes in a deny message.
3. **If the hook can probe the platform** (a cheap `uname`/`pgrep --version` is not "regex-only",
   so this is a design question for you), the message can say "add `-A`" on procps-ng >= 4.0.1,
   "drop `-a`" on macOS, and "bracket the pattern" elsewhere. If it must stay static, the
   bracket form is the only recommendation true on all four families.
4. **Residual risk after any ancestor exclusion is siblings.** `pgrep -f foo | grep foo` can match
   its own pipeline sibling on every platform (procps `-A`, macOS default). The hook's deny need
   not cover it, but the message should not claim `-A` makes `-f` safe in general.
5. `pidwait` shares procps's code and flags (S6); BusyBox has no `pidwait`.
6. Not covered by the brief but adjacent: `pkill -a` on macOS re-enables the self-kill; on
   procps-ng the letter `-a` in a cluster (`-fa`) is legal for `pgrep` and illegal for `pkill`.

## 11. Open questions and leads

- Run the statements marked code-reading-only on a real macOS 26 arm64 host and on
  Alpine/BusyBox, preferably through the actual Claude Code wrapper (`zsh -c ... eval '...'`).
  That would turn the macOS "excludes the shell" claim and the BusyBox "kills the shell" claim
  into measurements (CLAUDE.md's "Measure before you assert").
- Read the 4 notes on MR !160 with an authenticated session, in case the maintainers discussed
  the `sh -c` case or the choice to make ancestor exclusion opt-in rather than default.
- Decide whether `uname`/`--version` probing is allowed by D38's "deterministic regex-only"
  framing, since that determines which of the messages in section 10 is available.
- Confirm that the bracket trick survives Claude Code's `eval '<command>'` quoting (single quotes
  inside the pattern get re-escaped) and BSD/ERE and BusyBox regex dialects.

## 12. Searches and fetches used

Web searches: `procps-ng pgrep "ignore-ancestors" -A add option issue gitlab`; `macOS pkill man
page "ancestors" -a "Include process ancestors in the match list"`; `procps-ng pgrep -f matches
parent shell bash -c "pgrep -f" matches itself sh -c issue`; `Debian bug procps pkill -f kills
parent shell "sh -c" pgrep should exclude parent processes`; `pgrep -f ssh "bash -c" matches the
shell itself ... [p]attern`; `RHEL 9 procps-ng version 3.3.17 pgrep man page "ignore-ancestors"
...`; `access.redhat.com procps-ng-3.3.17 el9 RHEL 9 package`; `macOS pgrep -f inside bash
script does not match itself or parent shell ...`; `apple-oss-distributions distribution-macOS
release.json adv_cmds macos-26`; `actions/runner-images ubuntu-latest migrate Ubuntu 26.04
announcement`. Also GitLab REST API queries against `procps-ng/procps` for issues (search terms
`ancestors`, `pkill -f`, `pgrep parent`, `pgrep itself`, `sudo`) and merge requests (`pgrep`).
Follow-up (macOS `-l`): raw `pkill.1` at tag adv_cmds-237 and the Xcode man page set, asked for
the `-l` entry verbatim.

## Sources

S1. procps-ng NEWS (master). https://gitlab.com/procps-ng/procps/-/raw/master/NEWS (the 4.0.1 section is the evidence; the file also shows 4.0.7 and a NEXT section)
S2. procps-ng `src/pgrep.c` at v4.0.4. https://gitlab.com/procps-ng/procps/-/raw/v4.0.4/src/pgrep.c
S3. procps-ng `src/pgrep.c` (master) https://gitlab.com/procps-ng/procps/-/raw/master/src/pgrep.c ; release tags and dates https://gitlab.com/procps-ng/procps/-/tags
S4. procps-ng `src/pgrep.c` at v4.0.1. https://gitlab.com/procps-ng/procps/-/raw/v4.0.1/src/pgrep.c
S5. procps-ng `pgrep.c` at v3.3.17 (no `-A`; `task.XXXID == myself`). https://gitlab.com/procps-ng/procps/-/raw/v3.3.17/pgrep.c
S6. procps-ng `man/pgrep.1` (master). https://gitlab.com/procps-ng/procps/-/raw/master/man/pgrep.1
S7. procps-ng MR !160, "pgrep: Add support for ignoring ancestors with -A/--ignore-ancestors", Chris Down, 2022-08-10, merged 2022-08-31. API (readable): https://gitlab.com/api/v4/projects/procps-ng%2Fprocps/merge_requests/160 ; HTML (403 to my fetcher): https://gitlab.com/procps-ng/procps/-/merge_requests/160
S8. procps-ng MR !162, "pgrep: Look at all ancestors in --ignore-ancestors", Chris Down, merged 2022-09-01. https://gitlab.com/api/v4/projects/procps-ng%2Fprocps/merge_requests/162
S9. Commit 4b44ab98. https://gitlab.com/procps-ng/procps/-/commit/4b44ab98c144dae099442e30a62966a7689818c6 (mirror: https://git.psf.lt/emo/procps/commit/4b44ab98c144dae099442e30a62966a7689818c6)
S10. procps-ng issue tracker (queried through the API). https://gitlab.com/procps-ng/procps/-/work_items (e.g. #406 https://gitlab.com/procps-ng/procps/-/work_items/406, #142 https://gitlab.com/procps-ng/procps/-/work_items/142)
S11. Rocky Linux 9 BaseOS package index (procps-ng-3.3.17-14.el9, 2024-04-20). https://dl.rockylinux.org/pub/rocky/9/BaseOS/x86_64/os/Packages/p/
S12. Ubuntu package pages: https://packages.ubuntu.com/jammy/procps , https://packages.ubuntu.com/noble/procps , https://packages.ubuntu.com/resolute/procps
S13. Launchpad procps publishing history (noble-updates 4.0.4-4ubuntu3.3, 2026-08-26; jammy 3.3.17-6ubuntu2.1). https://launchpad.net/ubuntu/+source/procps
S14. Debian package pages: https://packages.debian.org/bookworm/procps , https://packages.debian.org/trixie/procps , https://packages.debian.org/sid/procps
S15. Debian Package Tracker https://tracker.debian.org/pkg/procps . Ubuntu man pages: https://manpages.ubuntu.com/manpages/jammy/en/man1/pgrep.1.html (no `-A`) and https://manpages.ubuntu.com/manpages/noble/en/man1/pgrep.1.html (has `-A`)
S16. Debian 12 pgrep man page (footer procps-ng 2022-08-31). https://manpages.debian.org/bookworm/procps/pgrep.1.en.html
S17. Debian 13 pgrep man page (footer 2023-01-16). https://manpages.debian.org/trixie/procps/pgrep.1.en.html
S18. Fedora package page for procps-ng (Rawhide 4.0.7-1.fc46; F45 4.0.6-2; F44 4.0.6-1; F43 4.0.4-7.fc43.1). https://packages.fedoraproject.org/pkgs/procps-ng/procps-ng/
S19. Red Hat advisory RHSA-2023:6705, "Low: procps-ng security and bug fix update", 2023-11-07, procps-ng-3.3.17-13.el9. https://access.redhat.com/errata/RHSA-2023:6705
S20. CentOS Stream spec files: c9s https://gitlab.com/redhat/centos-stream/rpms/procps-ng/-/raw/c9s/procps-ng.spec (3.3.17-15) ; c10s https://gitlab.com/redhat/centos-stream/rpms/procps-ng/-/raw/c10s/procps-ng.spec (4.0.4-13)
S21. Alpine package index: procps-ng edge and v3.22 https://pkgs.alpinelinux.org/packages?name=procps-ng&branch=edge , https://pkgs.alpinelinux.org/packages?name=procps-ng&branch=v3.22&repo=&arch=x86_64 ; busybox edge https://pkgs.alpinelinux.org/packages?name=busybox&branch=edge&repo=main&arch=x86_64 ; BusyBox applet docs https://busybox.net/downloads/BusyBox.html
S22. BusyBox `procps/pgrep.c`: https://elixir.bootlin.com/busybox/latest/source/procps/pgrep.c and https://github.com/mirror/busybox/blob/master/procps/pgrep.c
S23. BusyBox 1.37.0-6 `procps/pgrep.c` (Debian sources; full scan loop). https://sources.debian.org/data/main/b/busybox/1:1.37.0-6/procps/pgrep.c
S24. Apple `adv_cmds-237` `pkill/pkill.1` (.Dd October 5, 2020); the source of the `-a`, `-f` and `-l` quotes. https://raw.githubusercontent.com/apple-oss-distributions/adv_cmds/adv_cmds-237/pkill/pkill.1
S25. Apple `adv_cmds-237` `pkill/pkill.c` (`case 'a'`, `if (!ancestors)` walk, getopt string, `PSKIP`, sysmon arguments). https://raw.githubusercontent.com/apple-oss-distributions/adv_cmds/adv_cmds-237/pkill/pkill.c
S26. Apple `distribution-macOS` release manifests: macos-265 (macOS 26.5) -> adv_cmds-237 https://raw.githubusercontent.com/apple-oss-distributions/distribution-macOS/macos-265/release.json ; macos-156 (macOS 15.6) -> adv_cmds-235 https://raw.githubusercontent.com/apple-oss-distributions/distribution-macOS/macos-156/release.json ; tags https://github.com/apple-oss-distributions/distribution-macOS/tags
S27. Apple `adv_cmds-235` `pkill/pkill.1`. https://raw.githubusercontent.com/apple-oss-distributions/adv_cmds/adv_cmds-235/pkill/pkill.1 ; adv_cmds tags https://github.com/apple-oss-distributions/adv_cmds/tags
S28. Apple `adv_cmds` main branch `pkill.c` and `pkill.1` (identical content). https://raw.githubusercontent.com/apple-oss-distributions/adv_cmds/main/pkill/pkill.c , https://github.com/apple-oss-distributions/adv_cmds/blob/main/pkill/pkill.c
S29. Xcode man page set, pkill(1) (footer "October 5, 2020 | Mac OS X 12"). https://keith.github.io/xcode-man-pages/pkill.1.html
S30. FreeBSD 15.0-RELEASE pkill(1), page date 2025-06-24. https://man.freebsd.org/cgi/man.cgi?query=pkill&sektion=1&manpath=FreeBSD+15.0-RELEASE
S31. FreeBSD commit 0a091aeb, Brian Somers, 2009-05-17, "When finding processes, ignore ourself and our ancestors." https://cgit.freebsd.org/src/commit/bin/pkill/pkill.c?id=0a091aebdec028802362e203e4f37a7e3a8756ca ; logs https://cgit.freebsd.org/src/log/bin/pkill/pkill.c , https://cgit.freebsd.org/src/log/bin/pkill/pkill.1
S32. FreeBSD commit 88a2d48d, Kyle Evans, 2025-06-24, "pkill: better document ancestor-hiding". https://cgit.freebsd.org/src/commit/bin/pkill/pkill.1?id=88a2d48d39d9845e36c8e95a9204001b11e7257e
S33. FreeBSD `bin/pkill/pkill.c` (current; NetBSD header, `PSKIP`, ancestors walk). https://cgit.freebsd.org/src/plain/bin/pkill/pkill.c
S34. GitHub runner-images README (image/label table: `ubuntu-latest` = Ubuntu 24.04, `macos-latest` = macOS 26 arm64; `ubuntu-26.04` available). https://raw.githubusercontent.com/actions/runner-images/main/README.md
S35. GitHub runner-images Ubuntu 24.04 readme (24.04.5 LTS, image 20261004.327.1; lists neither procps nor pgrep). https://raw.githubusercontent.com/actions/runner-images/main/images/ubuntu/Ubuntu2404-Readme.md
S36. GitHub changelog, "Ubuntu 26 generally available and latest migration", 2026-09-17: `ubuntu-latest` moves to 26.04 gradually between 2026-10-19 and 2026-11-19. https://github.blog/changelog/2026-09-17-ubuntu-26-generally-available-and-latest-migration
