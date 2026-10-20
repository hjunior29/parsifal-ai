# Architecture Decision Records

Decisions taken for the `parsifal-ai` fork, in the order they were made.
Format: context → decision → consequences. Dates are when the decision was
recorded.

---

## ADR-001 — SQLite is the only supported database

**Date:** 2026-10-15 · **Status:** accepted

**Context.** Upstream runs on PostgreSQL 12. The fork targets a single
self-hosted instance (one researcher or a small team). The owner has
independent reasons not to run PostgreSQL. The code has no Postgres-specific
constructs; all 87 migrations apply on SQLite and the 75 existing tests pass
on it unchanged (verified 2026-10-15).

**Decision.** `DATABASE_URL` defaults to a SQLite file inside a configurable
data directory (`PARSIFAL_DATA_DIR`, default `./data/`). PostgreSQL support is
not maintained or tested; `psycopg2-binary` is removed from requirements.

**Consequences.**
- Enable WAL mode and a busy timeout at connection time (SQLite + gunicorn
  workers); avoid long write transactions in imports (batch commits).
- Add DB constraints the code relied on Postgres-less `get_or_create` for
  (see known issues D4) — they work the same in SQLite.
- CI drops the PostgreSQL service.
- Anything needing vector search (future AI features) uses a separate store
  or `sqlite-vec`; not a reason to bring Postgres back.

---

## ADR-002 — API-first: JSON API with thin CLI and MCP clients

**Date:** 2026-10-15 · **Status:** accepted

**Context.** Coding agents (Claude Code, Codex, …) must operate the whole
system — create reviews, edit protocols, import studies, classify, assess,
extract, export. Options considered: (a) an HTTP API with thin CLI/MCP
clients; (b) an in-process CLI using the ORM directly (Django management
commands) with a stdio MCP wrapper; (c) MCP only.

**Decision.** (a). A versioned JSON API (`/api/v1/`) implemented with
**django-ninja** over a new **service layer**. The `parsifal` CLI and the MCP
server are thin clients of that API; one CLI command ≙ one MCP tool ≙ one API
operation, generated from the same operation registry so parity is enforced
by tests.

**Consequences.**
- Works whether the agent runs on the same machine or remotely; the web UI
  and the API share the service layer, so behaviour cannot drift.
- Requires authentication for agents → ADR-004.
- The CLI/MCP package can have its own Python requirement (≥ 3.10 for the
  `mcp` SDK) independent of the server (ADR-005).
- django-ninja chosen over DRF for Pydantic schemas (reusable by the clients),
  automatic OpenAPI, and smaller surface; it supports Django 4.2 / Python 3.10.

---

## ADR-003 — Remove public-SaaS and social features

**Date:** 2026-10-15 · **Status:** accepted

**Context.** `blog`, `help` (CMS), `activities` (follow/feed), reCAPTCHA,
Google Analytics and Sentry exist to run parsif.al as a public service. They
add code, dependencies and templates with no value for a self-hosted
instance and would need to be documented and tested.

**Decision.** Remove `blog`, `activities`, `help` (replaced by this `doc/`
folder and a static help link), `core.Media`, reCAPTCHA, Google Analytics and
Sentry. Keep `invites` (co-authorship) with e-mail optional, keep `library`,
keep `accounts`/`authentication` with public sign-up disabled by default.

**Consequences.**
- Smaller diff to maintain; harder to merge upstream changes touching those
  apps (acceptable — upstream is low-activity).
- `Profile` follower helpers, `core.home` feed, `reviews.views.reviews`
  follower counts, and `invites.SendInviteForm` contacts must be adapted.
- Database: tables of removed apps are dropped by a migration before the apps
  leave `INSTALLED_APPS`; since the fork starts from empty databases, a reset
  of migrations is acceptable but not required.

---

## ADR-004 — Single admin created at setup; agents authenticate with API tokens

**Date:** 2026-10-15 · **Status:** accepted

**Context.** Self-hosted instance; no public sign-up. Agents need credentials
that are easy to provision and revoke.

**Decision.** `parsifal init` (management command) creates the database,
loads default sources and creates the admin user. Users (admin, co-authors)
generate **personal API tokens** (`ApiToken` model: hashed token, name,
created, last used, revoked). The API accepts `Authorization: Bearer <token>`
and acts **as that user**, so the existing author/co-author rules apply
unchanged. Session auth remains for the web UI. Additional users are created
by the admin (UI/CLI), or by enabling sign-up via a setting.

**Consequences.**
- No new permission model; `Review.is_author_or_coauthor` stays the single
  source of truth.
- Tokens are shown once; stored hashed (SHA-256).
- CLI/MCP read the token from `PARSIFAL_TOKEN` / config file.

---

## ADR-005 — Python 3.10 as the minimum runtime; Django 4.2 kept for now

**Date:** 2026-10-15 (amended the same day) · **Status:** accepted

**Context.** Python 3.9 reached end-of-life in October 2025; Django 4.2 LTS
support ended April 2026. The Python `mcp` SDK requires ≥ 3.10. The initial
decision was to leave the runtime untouched; the maintainer then asked for the
3.9 → 3.10 upgrade to be done immediately if cheap. It is: the code uses no
removed APIs, Django 4.2 supports Python 3.8–3.12, and the suite is small.

**Decision.** Minimum Python is **3.10** (`requires-python >= 3.10` in
`pyproject.toml`, tox env `py310`, CI on 3.10). Django stays on 4.2 for now.
The CLI/MCP client package shares the same minimum.

**Consequences.**
- Server and clients can use `match`, `X | Y` unions and `zoneinfo`.
- Moving to 3.12 later is a configuration change (tox, CI, Dockerfile).
- Django 5.x upgrade remains an optional phase.

---

## ADR-006 — Support both SLR (Kitchenham & Charters 2007) and SMS (Petersen et al. 2015)

**Date:** 2026-10-15 · **Status:** accepted (design only; implementation later)

**Context.** Parsifal implements the SLR process. The owner's research also
needs **systematic mapping studies**, which differ in research questions,
search breadth, optional quality assessment, classification schemes
(facets), and visualisation (bubble plots).

**Decision.** Add a `Review.review_type` (`slr` | `mapping`) that switches
which steps are required and which artefacts are offered, and add the
mapping-specific entities (classification schemes/facets with categories,
per-article classifications, facet×facet aggregations) as additions to the
existing model rather than a parallel model. Details in
[10-methodology.md](10-methodology.md).

**Consequences.**
- Existing SLR behaviour is the default; nothing changes for current data.
- Quality assessment becomes optional for mapping reviews (it is already
  effectively optional in the code).
- Both guideline texts are indexed in the local code-rag instance
  (`kitchenham-2007`, `petersen-2015`) for consultation during development.

---

## ADR-007 — Documentation lives in `doc/`, in English

**Date:** 2026-10-15 · **Status:** accepted

Project documentation (this folder) is written in English, in Markdown, one
topic per file, indexed from `doc/README.md`. Code comments and identifiers
are English. Conversation with the maintainer may be in Portuguese; artefacts
are not.

---

## ADR-008 — Second trimming round: no public profiles, no invites, no transfer, no Scopus

**Date:** 2026-10-16 · **Status:** accepted

**Context.** After phases 0–9 the maintainer reviewed the remaining inherited
features and judged several of them unnecessary for a self-hosted instance
used by one researcher plus a few collaborators and agents.

**Decision.** Remove: e-mail invitations (replaced by a "Manage access" page
where the main author adds existing accounts by username; superseded by
agent accounts, see below), ownership
transfer (UI, service, API, CLI), the Scopus/Elsevier search integration,
profile pictures, the public profile fields (public e-mail, location, URL,
institution), the public `/<username>/` page (now the logged-in user's own
review list only) and the never-functional "Published reviews" panel, and
the advertised but untranslated pt-br language. Keep: the `library` app,
sitemaps/About/Support, password reset by e-mail.

**Consequences.** `django.contrib.sites`, `Pillow` and the `invites` app are
gone; upstream databases keep orphan `invites_*` tables and the removed
`auth_profile` columns are dropped by `authentication.0011`. Accounts are
created by administrators (admin site, API, CLI); agents get their own account
and are added as co-authors.

## Agents are co-authors created from the review

**Context.** Actions through the API, CLI and MCP should not be attributed to
the human, and there is only one human (created by `init`); "adding an
existing account" made no sense.

**Decision.** The main author creates an AI agent from *Manage access* (or
`agents_create`): a new account (`ReviewAgent`, unusable password, username
`agent-<name>`) that belongs to that review, is a co-author, and gets a token
shown once. Adding an existing account by username was removed from the web,
API (`members_add`/`members_remove`), CLI and MCP. Agents cannot manage
agents. Deleting an agent is permanent and deletes the account with its
tokens, decisions, quality assessments and extracted data (those FKs cascade);
imported studies and classifications stay, with the author cleared. Deleting
the review deletes its agents.

**Consequences.** Migration `reviews.0041`. The decision count, quality
assessments and extractions of an agent are shown before deleting it.

## AI screening with Jev (phases 1 and 2 of study selection)

**Context.** Helder screens in two phases: first remove the studies that meet
an exclusion criterion, then judge the rest against the inclusion criteria.
Jev (TypeSafe) is a hosted decision model that returns a probability per
allowed answer, cheap and fast enough to run over every title and abstract.
Its known weaknesses (first-option bias, overconfidence when information is
missing, sensitivity to wording) are documented in the analysis Helder
reviewed (Akita, 2026-10-03).

**Decision.**
- Web first: *Exclude with AI* on the study selection page opens a window
  prefilled from the review; the context fields are editable per run, the
  exclusion criteria, the task, the rules and the study fields are not (the
  request became an editable template on 2026-10-20, see below).
- One reviewer (Jev), no second model. Per study, title + keywords + abstract
  only; one `choice` question (criteria + `none`) asked in three rotated
  orders in the same request and averaged. Reject when
  `1 − p(none) ≥ threshold` (default 0.9), with the most probable criterion;
  otherwise leave the study unclassified for the next phase.
- Every run is made in the name of a **reviewer** chosen when it starts
  (2026-10-19, replacing a dedicated "Jev" agent): the main author may pick
  any member, anyone else only themselves. The run records the reviewer's
  `StudyDecision` for every study it sends (nothing is skipped): R with the
  criterion, or U "no exclusion criterion". Recording the U decisions is what
  makes two reviewers comparable (kappa, unanimous consolidation).
- The studies sent are chosen by **status** (2026-10-19): any mix of U, R, A,
  D, default R + U. At first a run sent only U plus the reviewer's own earlier
  rejections, so the first reviewer's rejections never reached a second one and
  their agreement compared only the studies the first had kept (kappa 0). The
  study's status follows the decision only when it was U or rejected by the
  same reviewer; accepted studies, duplicates and studies rejected by someone
  else keep theirs, so screening as a second reviewer (e.g. another model)
  never undoes the first one. A study changed by someone else meanwhile is
  left alone (`ScreeningResult.previous_status`).
  The run log (`ScreeningRun`, `ScreeningResult`) keeps every answer and the
  parameters snapshot.
- The model is chosen per run from Jev's own list (`GET /v1/models`, asked
  when the window or Settings → Integrations opens); the default is saved per
  user.
- The API key is per user in *Settings → Integrations*
  (`accounts.Integration`), encrypted at rest with a key derived from
  `SECRET_KEY` (it must be readable to be sent to Jev, so it cannot be
  hashed like Parsifal's own API tokens), never rendered back.
  `JEV_API_URL` can point to a compatible server.
- The browser drives the run in steps of 8 studies (4 concurrent requests),
  so there is no task queue; the client retries 429/5xx/529 with backoff.
- A run cannot be stopped (2026-10-19). An interruption (page closed,
  connection lost, Jev refusing the key or unavailable) leaves it running with
  its remaining studies and `error`; the window offers **Continue** (stepping
  it again, same parameters) unless a step ran in the last 30 s
  (`last_step_at`, driven elsewhere). Starting a new run discards it. The
  cancel operation was removed from the web, API, CLI and MCP.
- **Include with AI** (phase 2, 2026-10-19), a run `phase` next to the
  exclusion one, with the same window, reviewer, model, statuses (default
  U + A) and continuation. A study must meet *every* inclusion criterion, which
  one choice question cannot express (it picks one option), so each criterion
  gets its own **yes/no** question (Jev's `noul`, which its documentation
  recommends for checking independent conditions), asked with its yes and no
  descriptions in both orders. The first version had a third answer, "unclear";
  Helder dropped it the same day: it gave the model an escape that diluted
  p(meets) and could be read in more than one way, while the probability
  already shows doubt. Accept when the **lowest** p(meets) reaches the
  **threshold** (an average would let a criterion clearly met make up for a
  weak one); otherwise the reviewer's decision is unclassified (outcome
  `undecided`) and the study is left to the reviewers. **Include with AI never
  rejects** (Helder, same day): excluding is phase 1's job, so phase 2 only
  looks for what to include. That also makes it the mirror of phase 1 for
  agreement: exclusion screens R + U and only rejects; inclusion screens A + U
  and only accepts, so a second AI reviewer (another model or parameters)
  screens the same studies and Cohen's kappa compares like with like. How the
  undecided studies are settled (by hand or otherwise) is left for later; their
  comment keeps Jev's p(meets) per criterion. The window is the exclusion one
  with one threshold (0.5–0.99, default 0.9). The status rule mirrors
  exclusion: it changes unclassified studies and those this reviewer accepted;
  rejected studies are never touched. Before that, for a few hours, inclusion
  had a separate accept and reject threshold (the reject one down to
  1 − accept); runs made then keep `accept_threshold` and
  `reject_threshold` in their parameters. The decision replaces the reviewer's
  phase-1 decision (same stage), so agreement compares the reviewer's last
  word.

**Consequences.** Migrations `accounts.0002`, `accounts.0003` (encrypted key), `reviews.0042`, `reviews.0043`
(reviewer, no agent kind), `reviews.0044` (`last_step_at`), `reviews.0045` (`phase`, `p_include`, outcomes
`included` and `undecided`). The API, CLI and
MCP mirror the web one to one (`jev_integration_*`, `ai_screening_*`); runs use
the Jev key of the caller. The CLI command `ai-screening run` and the MCP tool
`parsifal_ai_screening_run` loop over the steps like the web page does.
Thresholds should be checked against the reviewer's own decisions before
relying on them.


## Full texts: one PDF per study, in a private folder or an S3-compatible bucket

**Context.** Helder wants the whole analysis inside Parsifal, so the accepted
studies' PDFs should live next to them. Storage must stay simple: a folder
when the instance runs locally, an object store such as Tigris when it runs in
the cloud. The PDFs are copyrighted and private to the review.

**Decision.** `Article.pdf` points at a generic `core.StoredFile` row (key in
the storage, uploaded name, size, SHA-256, uploader). One PDF per study, any
status may have one; no automatic fetching by DOI. Files live in the "files"
storage: `FileSystemStorage` at `<data dir>/files`, or django-storages'
`S3Storage` when `PARSIFAL_FILES_BUCKET` is set (private bucket, SigV4 links
that expire, credentials read by boto3 from the environment and never put in
the settings). The study window gets a *Full text* tab that frames the PDF
with the browser's own viewer and opens it in a new tab; that route checks
review membership and sends the file (folder) or redirects to a signed link
(bucket). The API streams the file in both cases, so clients need no redirect
handling. The `/media/` route, which served anything under `MEDIA_ROOT`
without a login, was removed: nothing public is uploaded any more.

**Consequences.** Migrations `core.0004` and `reviews.0046`;
`requirements/s3.txt` (part of `production.txt`, so of the Docker image).
Operations `articles_pdf_upload`, `articles_pdf_download`,
`articles_pdf_delete` (CLI `article pdf upload|download|delete`). Attaching a
PDF saves only `pdf`, keeping `updated_by`, which AI screening uses to decide
which statuses a run may change. `manage.py backup` still copies only the
database: `<data dir>/files` must be backed up with it. Switching between
folder and bucket does not move existing files. The unused jQuery File Upload
plugin and the commented-out "Files" tab were removed.

## Starred studies: one shared mark per study in the review

**Context.** Helder wants to mark studies and come back to them. The mark
belongs to the review — whoever sets it (him or an agent), the study is
starred in that review — unlike a future personal favourite in the library
("I like this paper"), which is another feature.

**Decision.** `Article.starred_at` and `starred_by`: one star per study,
independent of its status; starring again keeps who starred it first; anyone
in the review unstars it; `updated_by` is left alone (AI screening relies on
it). On the study list the star is a column of its own next to the checkbox,
far from the Status column, and the filter is a star button with the count
attached to the search box — the "Show" radios stay statuses only. Clicking
the column header sorts starred first. The study window shows the star in its
title, away from the study's fields. No bulk star: starring is a judgement on
one study, so the Action menu (statuses, removal) does not offer it, nor does
the API (`articles_star`, `articles_unstar`, `starred` filter on
`articles_list`).

**Consequences.** Migration `reviews.0047`. The study rows are rendered by one
template (`partial_conducting_article_row.html`) for the list and after a
save, and status updates in the page target the status cell only.

## AI screening: the request to Jev is an editable template

**Context.** Testing prompts in Jev's playground, Helder found wordings that
fit his review better than Parsifal's fixed task and rules (the review context
in the state instead of in every question, no keywords, the criteria alone as
options). He wants to change the text around the data from the window, while
the data themselves — criteria, review title, objective, research questions,
PICOC, the study — keep coming from the review and the fields above.

**Decision.** Each phase has a request template (`services/screening_requests.py`),
a JSON object with `state` and `question`, shown at the end of the *Exclude/
Include with AI* window and editable as text. The data are placeholders
(`{{review}}`, `{{review.<field>}}`, `{{guidance}}`, `{{study}}`,
`{{study.<field>}}`, `{{key}}`, `{{criterion}}`) filled in by Parsifal; a whole
placeholder with an empty value is left out, as empty context fields always
were. The structure is the reviewer's too, except what Parsifal reads the
answers by: the question's `type`, and its `criteria` (exclusion: one
`{{key}}` entry, repeated per criterion, plus `none`; inclusion: `true` and
`false`). Parsifal keeps repeating the question per order and per criterion.
A template that breaks this is refused before anything is sent. The default
template reproduces the previous request exactly. A new run starts from the
template of the review's last run of the same phase, so two reviewers are
asked the same way; each run stores it in `parameters.template`. A preview
(web, `ai_screening_preview` in the API, CLI, MCP) shows the body sent about
one study without sending it, with buttons to copy `state` and `questions`
for the playground.

**Consequences.** No migration: the template lives in the run's parameters,
and runs from before it existed use the default. The setup operation returns
`template`, `template_default` and `placeholders` instead of `task`, `rules`,
`none_description` and `sent_fields`.
