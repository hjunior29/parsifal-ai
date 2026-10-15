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
