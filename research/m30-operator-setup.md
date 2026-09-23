# M30 operator setup: PyPI trusted publishing and Codecov, exact steps

## Brief

Produce exact, current, step-by-step setup instructions for two things the Zikaron operator must
do by hand and has never done: (1) register a PyPI **pending publisher** for the not-yet-created
project `zikaron`, publishing via GitHub Actions workflow `release.yml` from
`nathan-shapiro/Zikaron` using environment `release`; (2) connect the public GitHub repo to
Codecov and get a working coverage badge. Field-name and button-label accuracy is the point; where
a UI recently changed or a label could not be confirmed directly (PyPI's OIDC login blocks
unauthenticated fetch of the live form), that is flagged rather than guessed.

## Method

Read PyPI's official trusted-publishers docs (`docs.pypi.org/trusted-publishers/*`) directly via
WebFetch, cross-checked against a PyPI blog announcement and independent write-ups (Simon
Willison's TIL, a search-aggregated set of blog posts quoting the same field labels) since the live
`pypi.org/manage/account/publishing/` form is behind login and could not be fetched directly. Read
Codecov's official docs (`docs.codecov.com/docs/quick-start`, `.../status-badges`,
`.../codecov-tokens`) directly. Read GitHub's own docs (via search-engine synthesis, since direct
fetch of `docs.github.com` pages was not attempted individually beyond the environments page) for
the environment-creation and secrets menu paths. Searched for the tokenless-upload change history
to date the "does a public repo still need `CODECOV_TOKEN`" answer correctly for late 2026.

Queries used: PyPI 2FA requirement history and current state; PyPI trusted-publisher pending-flow
field names (direct fetch + corroborating search); PyPI trusted-publisher common failure messages
(direct fetch of the troubleshooting page); GitHub environment creation menu path; Codecov
tokenless upload for public repos with GitHub Actions; Codecov badge URL format and token
requirement for public repos.

## Task 1 — PyPI pending publisher for `zikaron`

### Account prerequisites

- **A PyPI account is required**, created at `https://pypi.org/account/register/` (standard
  username/email/password + email verification flow; not independently re-verified here since it
  is unchanged, generic web signup).
- **2FA is mandatory**, but scoped to *management actions*, not account creation or browsing.
  PyPI's blog: enforcement began **2024-01-01** for "all users, all projects" — a user can log in,
  browse and download without 2FA, but **any management action (including registering a
  publisher) requires 2FA to be enabled first** [PyPI blog, 2FA enforcement announcement, 2023-12-13].
  Use either a hardware/security-key device (PyPI's stated preference) or a TOTP authenticator app;
  set it up from the account's security settings before attempting the publisher form.
- Trusted Publishing itself needs no PyPI API token — that is the point of OIDC — so no token
  generation step is needed for Task 1.

### Where the form lives

The **pending-publisher form is on the same page as normal trusted-publisher management**, reached
from the account (not a project) sidebar, because the project does not exist yet:

1. Log in at pypi.org.
2. Open your account menu → **"Publishing"** (PyPI's own docs describe this as: "Go to your
   account's publishing page and select 'Add a new publisher'" — the account sidebar item is
   labeled **Publishing**) [docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/].
3. This lands on `pypi.org/manage/account/publishing/` (confirmed by URL from multiple
   corroborating sources; the live page itself could not be fetched directly here since it
   redirects to login when unauthenticated — flagging this rather than asserting the page's exact
   visual layout).
4. On that page, per PyPI's own docs, a **"Manage Publishers"** section sits at the top (existing
   publishers, if any) and an **"Add a new pending publisher"** section/form sits at the bottom
   [corroborated by direct fetch of `docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/`
   plus independent secondary sources describing the same page].

**Flag**: the exact wording "Add a new pending publisher" is from PyPI's docs prose describing the
UI, not a pixel-verified screenshot of the current live form — PyPI has redesigned this page before
(it used to be split across separate "trusted publisher" UI). If the operator sees a page titled
differently (e.g. just "Publishing" with tabs for "Pending publishers" vs "Active publishers"),
trust what is on screen over this note.

### Fields, with `zikaron` values

Selecting **"GitHub"** as the publisher type opens a form with these fields (label wording per
PyPI's docs, corroborated by two independent secondary write-ups quoting the same labels)
[docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/;
docs.pypi.org/trusted-publishers/adding-a-publisher/]:

| Field | Value for this project |
|---|---|
| **PyPI Project Name** | `zikaron` |
| **Owner** | `nathan-shapiro` |
| **Repository name** | `Zikaron` |
| **Workflow name** | `release.yml` (PyPI wants just the filename, e.g. `release.yml`; some PyPI copy shows it as `.github/workflows/release.yml` — provide the filename that matches your workflow's actual path; both docs pages disagree slightly on whether the example shows the bare filename or the full path, so check the placeholder text in the live field before typing) |
| **Environment name** | `release` |

Click the submit button — PyPI's docs describe it simply as **"Add"** (unverified against a live
screenshot; could read "Add publisher" or similar on the current form).

**No project reservation happens yet.** The project name `zikaron` is *not* reserved on PyPI by
this step — it only becomes reserved (and the project created) the first time a matching workflow
run actually publishes [docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/]. So
someone else could in principle register `zikaron` on PyPI before your first successful publish;
there is no docs-stated way to lock the name earlier.

### The GitHub side: does the `release` environment need to exist first?

**Yes, effectively** — although PyPI's form will *accept* an environment name that doesn't yet
exist in the repo (nothing on the PyPI side validates against GitHub), the OIDC claim your
`release.yml` workflow presents at publish time must include `environment: release`, which only
happens if the workflow job itself declares `environment: release` — and for that to gate anything
meaningfully (see protection rules below) the environment should be created in GitHub first, or the
first publish attempt will simply mismatch and fail (`invalid-publisher`/`invalid-pending-publisher`,
see Common failure below).

**Exact GitHub menu path** [GitHub Docs, "Managing environments for deployment", corroborated by
search synthesis]:

1. Repository main page → **Settings** (top of repo, requires admin on the repo; for a personal
   account repo you must be the owner).
2. Left sidebar → **Environments**.
3. **New environment** button.
4. Type the name — `release` — then **Configure environment**.

Environment names are case-insensitive, ≤255 chars, unique per repo.

**Protection rules**: optional, but this is exactly the feature PyPI's own docs call out as the
reason to set an environment at all — "configuring an environment is optional, but strongly
recommended" because it "allows you to require manual approval before uploads occur"
[docs.pypi.org/trusted-publishers/adding-a-publisher/]. For a solo-maintainer repo the useful
protection rule is **"Required reviewers"** (add yourself) so a publish run pauses for manual
approval before it can mint a PyPI OIDC token — worth setting if you want a checkpoint before an
irreversible release upload; not required for the mechanism to work at all. No protection rule is
mandatory for trusted publishing itself.

The workflow job that publishes must reference this environment, e.g.:
```yaml
jobs:
  publish:
    environment: release
    permissions:
      id-token: write   # required for OIDC
```
(This is the well-established shape of a trusted-publishing job per PyPI's own guide; not itself a
UI/label claim so not independently re-verified line-by-line here, but the `environment:` key and
`id-token: write` permission are both required and documented across every source consulted.)

### What the first successful publish looks like, and what changes after

- On the **first** publish where the OIDC claims match (owner, repo, workflow filename,
  environment all line up with what's registered), PyPI **creates the project** `zikaron` from that
  upload, and the pending publisher is **automatically converted into a normal (active) publisher**
  — no separate step, no extra configuration [docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/,
  explicit: "pending" publishers convert to normal publishers on first use].
- After that, the "Publishing" page for the now-created `zikaron` project shows the trusted
  publisher under the project's own management page rather than only the account-level pending
  list.
- The uploader identity (whoever's GitHub Actions run triggers the OIDC exchange) becomes the
  project's initial owner in PyPI's ownership model, per the same doc.

### Most common failure

Per PyPI's own troubleshooting doc, the two errors to expect from a misconfigured attempt
[docs.pypi.org/trusted-publishers/troubleshooting/]:

- **`invalid-pending-publisher` / `invalid-publisher`** — the OIDC token PyPI receives is valid but
  doesn't match any registered publisher. PyPI's own guidance: "Check for typos! If you're using
  GitHub Actions, check if the workflow is using the same environment as configured when the
  publisher was configured on PyPI," and separately, "check that the `repository_owner`,
  `repository` and workflow filename values are the same on both sides." In practice this means:
  the workflow file was renamed/moved after registering (mismatched filename), the job doesn't
  declare `environment: release` (mismatched or missing environment), or the repo was
  renamed/transferred (mismatched owner/repo).
- **"Non-user identities cannot create new projects"** — happens when the pending publisher
  succeeded at the identity level but the package metadata being uploaded (the name in
  `pyproject.toml` / built distribution) doesn't match the registered pending-publisher project
  name exactly. Fix: make the built package's name match `zikaron` exactly, or delete and
  re-register the pending publisher under the correct name.

## Task 2 — Codecov for the public GitHub repo

### Signing in and permissions

- Go to `codecov.io`, sign in with **"Sign up with GitHub"** (or "Log in with GitHub"). Codecov
  uses GitHub OAuth; GitHub will show a standard OAuth consent screen naming what's requested.
  Codecov's own quick-start describes this only as connecting "your individual code host account"
  [docs.codecov.com/docs/quick-start] — it does not itemize OAuth scopes in the fetched text, so the
  precise scope list is not independently confirmed here. Expect it to request read access to your
  repositories and org membership (standard for any CI-coverage SaaS); review the actual GitHub
  OAuth consent screen at sign-in time rather than trusting a scope list from this note.

### GitHub App installation — required, and it can be scoped

- **The Codecov GitHub App must be installed** — Codecov's docs are explicit: "If you are a GitHub
  user you **MUST** install the Codecov GitHub app for your organization - Codecov can't function
  without it" [docs.codecov.com/docs/quick-start].
- During installation, GitHub's own App-install flow (standard for every GitHub App, not
  Codecov-specific) offers **"All repositories"** or **"Only select repositories"** — so yes, it can
  be scoped to just this one repo. Codecov's quick-start text doesn't re-describe this GitHub-native
  step in the fetched excerpt, but it is standard GitHub App installation UI and independently
  well-established; flagging that the exact radio-button wording ("Only select repositories") is
  from GitHub's general App-install UI knowledge, not re-verified against a fresh screenshot this
  session.

### Is a token still required for a public repo on GitHub Actions in 2026?

**Generally no**, with one carve-out. Codecov's own tokens doc states: **"For public repositories, a
token is required if the upload is for a commit on a protected branch"** (and the org hasn't
disabled token auth) [docs.codecov.com/docs/codecov-tokens]. Codecov introduced **tokenless
uploads** for public-repo GitHub Actions specifically to remove the token requirement for ordinary
CI runs and fork PRs [about.codecov.io blog, "Tokenless Uploads for GitHub Actions"; corroborated by
codecov-action GitHub issues discussing the v4/v5 tokenless behavior].

Practical read for `main`-branch CI on a public repo: if `main` is **not** configured as a GitHub
*protected branch*, tokenless upload should work with no `CODECOV_TOKEN` secret at all. If `main`
**is** branch-protected (or you want to be safe against the v4→v5 tokenless regressions several
users hit — see `codecov/codecov-action` issues #1818, #1602, #1671, where tokenless uploads broke
after upgrading action versions in 2024–2025), **set `CODECOV_TOKEN` anyway**; it costs nothing and
sidesteps every tokenless edge case reported. This is the pragmatic recommendation, not a docs
quote — flagging it as synthesis, not a vendor claim.

### Finding the repository upload token in the Codecov UI

Exact path per Codecov's own docs [docs.codecov.com/docs/codecov-tokens;
docs.codecov.com/docs/quick-start]:

1. In the Codecov app, find your repo in the repository list and click **"Configure"** (or open the
   repo, then its **"Configuration"** tab).
2. The token is shown in the **"General"** section of that Configuration tab.

(One fetched excerpt also described a "setup repo" button with "copy the token as shown in step
one" — likely the first-time onboarding wizard rather than the steady-state Configuration tab;
both lead to the same token. If the operator doesn't see "Configure" on first login, look for a
"setup repo" / onboarding prompt instead.)

### Adding `CODECOV_TOKEN` to GitHub

Standard GitHub Actions secret path (not Codecov-specific, well-established GitHub UI, not
independently re-screenshotted this session):

1. Repo → **Settings**.
2. Left sidebar → **Secrets and variables** → **Actions**.
3. **"New repository secret"** button.
4. Name: `CODECOV_TOKEN`. Value: the token copied from Codecov's Configuration/General page.

### Badge URL

Codecov's own status-badges doc gives the format [docs.codecov.com/docs/status-badges]:

```
https://codecov.io/gh/<owner>/<repo>/graph/badge.svg          (default branch)
https://codecov.io/gh/<owner>/<repo>/branch/<branch>/graph/badge.svg   (specific branch)
```

For this repo: `https://codecov.io/gh/nathan-shapiro/Zikaron/branch/main/graph/badge.svg`.

**Token query parameter**: the docs are explicit that this is needed **only for private repos** —
"If you're trying to render a badge for a private repo, you will need to append the `token` query
parameter to your badge svg URLs" [docs.codecov.com/docs/status-badges]. For a public repo, no
`?token=` is needed; **so the form the brief asked about confirming,
`https://codecov.io/gh/<owner>/<repo>/branch/main/graph/badge.svg`, is still correct for a public
repo as of the docs consulted (fetched 2026-09-23).**

Copy the exact, live URL from the Codecov UI rather than hand-typing it: docs point to the
**"Badges & Graphs"** section of the repo's **Configuration** page in the Codecov app
[docs.codecov.com/docs/status-badges] — that page also offers ready-made Markdown/RST/HTML
snippets, which is the safer way to get the URL exactly right (case of `owner`/`repo`, branch name)
than retyping it.

### Time to badge resolution

**Not stated in any source fetched this session.** Codecov's quick-start and status-badges docs
describe the mechanism but not a specific propagation delay after the first upload. Practically,
badges are dynamically generated per-request from the latest processed report, so the badge should
reflect the first successfully *processed* upload almost immediately (seconds to low minutes) —
but this is inference, not a documented number, and is flagged as such. If the operator sees a
"pending" or grey badge right after a first CI run, the likely cause is upload processing lag (wait
a few minutes and reload) rather than a config problem — but there is no vendor-stated SLA to cite.

## Evidence quality and gaps

- **PyPI's live pending-publisher form could not be fetched directly** (login-gated); field names
  and page structure ("Publishing" account-sidebar item, "Manage Publishers" / "Add a new pending
  publisher" sections) rest on PyPI's own docs prose plus corroborating independent write-ups that
  quote the same labels, not a fresh screenshot. This is the single biggest source of "confirm
  against what's actually on screen" risk in this note.
- **The workflow-name field's exact expected format** (bare filename `release.yml` vs full path
  `.github/workflows/release.yml`) was inconsistent between PyPI's two docs pages fetched — flagged
  explicitly above rather than resolved by guessing.
- **Codecov OAuth scope list and GitHub-App "select repositories" wording** were not independently
  re-verified against current screenshots; both are standard, low-risk UI patterns but are flagged
  as synthesis/general-knowledge rather than a docs quote.
- **Badge propagation time** is unsupported by any source found; presented as inference only.
- The Codecov tokenless-upload behavior has known **regressions between codecov-action v4 and v5**
  reported in GitHub issues through 2024–2025 (#1818, #1602, #1671 on `codecov/codecov-action`) —
  this is why the note recommends setting `CODECOV_TOKEN` even where docs say it's optional for
  public unprotected-branch repos.

## Sources

1. [Trusted Publishers overview](https://docs.pypi.org/trusted-publishers/) — PyPI Docs
2. [Creating a PyPI Project Through OIDC (pending publisher)](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) — PyPI Docs
3. [Adding a Trusted Publisher to an Existing PyPI Project](https://docs.pypi.org/trusted-publishers/adding-a-publisher/) — PyPI Docs
4. [Trusted Publishers Troubleshooting](https://docs.pypi.org/trusted-publishers/troubleshooting/) — PyPI Docs
5. [Publishing with a Trusted Publisher](https://docs.pypi.org/trusted-publishers/using-a-publisher/) — PyPI Docs
6. [2FA Requirement for PyPI begins 2024-01-01](https://blog.pypi.org/posts/2023-12-13-2fa-enforcement/) — PyPI Blog, 2023-12-13
7. [Securing PyPI accounts via Two-Factor Authentication](https://blog.pypi.org/posts/2023-05-25-securing-pypi-with-2fa/) — PyPI Blog, 2023-05-25
8. [Codecov Quick Start](https://docs.codecov.com/docs/quick-start) — Codecov Docs
9. [Codecov Status Badges](https://docs.codecov.com/docs/status-badges) — Codecov Docs
10. [Codecov Tokens](https://docs.codecov.com/docs/codecov-tokens) — Codecov Docs
11. [Tokenless Uploads for GitHub Actions](https://about.codecov.io/blog/tokenless-uploads-for-github-actions/) — Codecov Blog
12. [codecov/codecov-action Issue #1818 — tokenless upload error despite success](https://github.com/codecov/codecov-action/issues/1818)
13. [codecov/codecov-action Issue #1602 — "Token required because repository is private"](https://github.com/codecov/codecov-action/issues/1602)
14. [codecov/codecov-action Issue #1671 — "Token required - not valid tokenless upload" when token is provided](https://github.com/codecov/codecov-action/issues/1671)
15. [Managing environments for deployment](https://docs.github.com/actions/deployment/targeting-different-environments/using-environments-for-deployment) — GitHub Docs
16. [Publish releases to PyPI from GitHub Actions without a password or token](https://til.simonwillison.net/pypi/pypi-releases-from-github) — Simon Willison TIL (corroborating secondary source, not primary)
17. [Publishing package distributions using GitHub Actions CI/CD workflows](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/) — Python Packaging User Guide
