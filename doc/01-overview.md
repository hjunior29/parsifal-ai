# 01 — Project Overview

## What Parsifal is

Parsifal is a Django web application that supports researchers performing
**Systematic Literature Reviews (SLRs)** in software engineering. It implements
the three-phase process described by Kitchenham & Charters (2007):

1. **Planning** — define objective, PICOC, research questions, keywords and
   synonyms, a generic search string, digital-library sources, inclusion and
   exclusion criteria, a quality-assessment checklist, and a data-extraction
   form.
2. **Conducting** — adapt the search string per source, import candidate
   studies (BibTeX), select studies (accept / reject / duplicate), assess
   quality with weighted answers and a cut-off score, extract data from the
   final selection, and inspect simple analytics (studies per source, per year).
3. **Reporting** — export the protocol and conducting summary to a `.docx`
   file, and export study lists and extracted data to `.xls`.

The upstream project (`vitorfs/parsifal`, hosted at parsif.al) is a public,
multi-user SaaS with social features (followers, activity feed, blog, help
centre, e-mail invites). The code in this repository is a fork at upstream
version **2.2.1** (`parsifal/__init__.py`).

## Fork goals (`parsifal-ai`)

This fork turns Parsifal into an **open, self-hosted tool for conducting
systematic reviews and systematic mapping studies with AI assistance**. The
guiding rule is: keep the existing application and its conventions intact, and
add a small number of changes that unlock a very different way of using it.

| Goal | Summary | Where it is documented |
|------|---------|------------------------|
| Self-hosted, single-instance | One admin account created at setup; co-authors still possible; no public sign-up, reCAPTCHA, analytics or Sentry. | [decisions.md](decisions.md) ADR-003, ADR-004 |
| SQLite as the database | Replace PostgreSQL. All 87 migrations and the 75 existing tests already run on SQLite unchanged. | ADR-001, [09-testing.md](09-testing.md) |
| Machine interface for agents | A JSON HTTP API that covers every operation end-to-end, plus a thin `parsifal` CLI and an MCP server built on top of it, so Claude Code, Codex and similar agents can create, read, update and delete everything a human can through the UI. | ADR-002, [11-system-design.md](11-system-design.md) |
| Methodological breadth | Keep Kitchenham & Charters (2007) SLR support and add Petersen et al. (2015) **systematic mapping study** support (classification schemes, keywording, bubble plots, no mandatory quality assessment). | ADR-006, [10-methodology.md](10-methodology.md) |
| Tests for everything new | Every new component ships with tests; the existing suite is kept green. | [09-testing.md](09-testing.md) |
| AI "harness" (future) | The engine that actually drives a review with LLMs is **out of scope for now**; it will be a client of the API/CLI/MCP layer described here. | [12-roadmap.md](12-roadmap.md) |

## Tech stack (as of this fork's starting point)

| Layer | Technology | Notes |
|-------|------------|-------|
| Language | Python 3.9 (upstream) → **3.10 minimum** (fork, ADR-005) | Upgraded in phase 0. |
| Framework | Django 4.2.28 | Settings split into `base/local/production/tests`. |
| Database | PostgreSQL 12 (upstream) → **SQLite** (fork) | `dj-database-url` reads `DATABASE_URL`. |
| Frontend | Bootstrap 3.4, jQuery 3.6, Mustache, server-rendered templates | Pages call AJAX endpoints that return HTML fragments or plain text. |
| Static files | django-compressor | `COMPRESS_ENABLED` defaults to `not DEBUG`. |
| Forms | django-crispy-forms (bootstrap3 pack) | Used sparingly; most forms are hand-written. |
| Imports/exports | bibtexparser 1.3, xlwt, python-docx | See [07-import-export.md](07-import-export.md). |
| External APIs | Elsevier (Scopus) search | Requires `ELSEVIER_API_KEY`; ScienceDirect endpoint is disabled. |
| Deployment (upstream) | gunicorn + nginx + supervisor | `bin/`, `etc/`. See [08-configuration-and-deployment.md](08-configuration-and-deployment.md). |
| QA tooling | black (119 cols), isort, flake8, tox, coverage, towncrier | `Makefile`, `tox.ini`, `setup.cfg`, `pyproject.toml`. |

## Repository layout

```
parsifal-ai/
├── manage.py
├── parsifal/
│   ├── settings/           # base.py, local.py, production.py, tests.py
│   ├── urls.py             # root URL conf (page routes live here)
│   ├── wsgi.py
│   ├── apps/
│   │   ├── reviews/        # core domain: Review, Article, protocol entities
│   │   │   ├── planning/   # protocol-building AJAX views
│   │   │   ├── conducting/ # search, import, selection, QA, extraction views
│   │   │   ├── reporting/  # docx export
│   │   │   └── settings/   # rename/transfer/delete a review
│   │   ├── library/        # personal BibTeX library (Document, Folder)
│   │   ├── accounts/       # profile, e-mail, picture settings
│   │   ├── authentication/ # Profile model, sign-up, auth backend
│   │   ├── invites/        # co-author invitations
│   │   ├── activities/     # follow/unfollow + feed (SaaS feature)
│   │   ├── blog/           # news entries (SaaS feature)
│   │   ├── help/           # help-centre articles (SaaS feature)
│   │   └── core/           # home page, Media model, context processor, mgmt commands
│   ├── templates/          # base.html, registration/, includes/, errors
│   ├── static/             # vendor CSS/JS, parsifal.css/js
│   ├── utils/              # elsevier client, recaptcha, mask, version
│   └── newsfragments/      # towncrier changelog fragments
├── requirements/           # base, local, tests, production
├── bin/, etc/              # upstream deployment scripts (gunicorn, nginx, supervisor)
├── .github/workflows/      # tox, codecov, CodeQL
└── doc/                    # this documentation
```

## How to read this documentation

| File | Audience / purpose |
|------|--------------------|
| [02-architecture.md](02-architecture.md) | How a request flows, URL scheme, authorization, frontend/AJAX contract, settings. |
| [03-domain-model.md](03-domain-model.md) | Every model, relationship, status enum and derived rule (final selection, duplicates, scores). |
| [04-review-workflow.md](04-review-workflow.md) | The user-facing workflow step by step, mapped to code and to Kitchenham's guidelines. |
| [05-apps-reference.md](05-apps-reference.md) | One section per Django app: responsibility, models, views, templates, tests, fork disposition. |
| [06-http-endpoints.md](06-http-endpoints.md) | Complete inventory of page and AJAX endpoints with inputs/outputs — the contract the API must replicate. |
| [07-import-export.md](07-import-export.md) | BibTeX field mapping, XLS/DOCX exports, Elsevier search. |
| [08-configuration-and-deployment.md](08-configuration-and-deployment.md) | Environment variables, settings modules, deployment scripts, CI. |
| [09-testing.md](09-testing.md) | Current test suite, conventions, coverage gaps, how to run on SQLite. |
| [10-methodology.md](10-methodology.md) | Kitchenham 2007 vs Petersen 2015: what the code implements, what mapping studies additionally need. |
| [11-system-design.md](11-system-design.md) | Target design for the fork: service layer, API, CLI, MCP, auth tokens, SQLite, conventions for new code. |
| [12-roadmap.md](12-roadmap.md) | Phased implementation plan with deliverables, tests and acceptance criteria. |
| [13-known-issues.md](13-known-issues.md) | Technical debt and bugs observed in the inherited code that affect the fork. |
| [decisions.md](decisions.md) | Architecture Decision Records for the fork. |
