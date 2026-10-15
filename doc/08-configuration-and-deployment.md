# 08 — Configuration and Deployment

## Settings modules

All settings live in `parsifal/settings/`. `manage.py` defaults to
`parsifal.settings.local`; `parsifal/wsgi.py` defaults to
`parsifal.settings.production`; tox and CI pass `--settings=parsifal.settings.tests`.

| Module | Extends | What it changes |
|--------|---------|-----------------|
| `base.py` | — | Everything common: apps, middleware, templates, DB, auth, i18n, static/media, third-party keys. |
| `local.py` | base | Adds `debug_toolbar` and `silk` (profiler) apps + middleware; console e-mail backend. |
| `production.py` | base | Secure cookies, HSTS, SSL redirect, proxy header; SMTP e-mail from env; Sentry SDK init. |
| `tests.py` | base | MD5 password hasher (speed); `GOOGLE_RECAPTCHA_ENABLED = False`. |

Configuration values are read with `python-decouple` (`config(...)`) from the
environment or a `.env` file in the project root (`.env.example` is the
template). `DATABASE_URL` is parsed by `dj-database-url`.

## Environment variables

| Variable | Default (base.py) | Used by | Fork relevance |
|----------|-------------------|---------|----------------|
| `SECRET_KEY` | `"parsifal.settings.local"` | Django | Must be set in self-hosted deployments. |
| `DEBUG` | `True` | Django | |
| `ALLOWED_HOSTS` | `127.0.0.1,localhost` (CSV) | Django | |
| `ADMINS` | `""` (`name,email;name,email`) | Django error mail | |
| `DATABASE_URL` | `postgres://richardwagner:holygrail@localhost:5432/parsifal` | `dj_database_url` | **Fork default becomes `sqlite:///<data dir>/parsifal.sqlite3`** (ADR-001). |
| `LANGUAGE_CODE` | `en-us` | i18n | `LANGUAGES` lists en-us and pt-br but `parsifal/locale/` does not exist in the repo. |
| `TIME_ZONE` | `UTC` | | |
| `COMPRESS_ENABLED` | `not DEBUG` | django-compressor | |
| `ELSEVIER_API_KEY` | `""` | Scopus search (`parsifal/utils/elsevier/client.py`) | Optional. |
| `GOOGLE_ANALYTICS_UA` | `""` | `base.html` (production only) | Removed in fork (ADR-003). |
| `GOOGLE_RECAPTCHA_ENABLED` / `_SITE_KEY` / `_SECRET_KEY` | `False` / `""` / `""` | sign-up form | Removed in fork (ADR-003). |
| `SENTRY_DSN` | `""` | `production.py`, `base.html` | Removed in fork (ADR-003). |
| `PARSIFAL_ENVIRONMENT` | `local` | context processor, `environment` command | Keep. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | required in `production.py` | invites, password reset | Keep optional; self-hosted may use console/file backend. |
| `EMAIL_BACKEND` | (only in `.env.example`) | not read by settings | `.env.example` lists it but `base.py` never calls `config("EMAIL_BACKEND")`; `local.py` hard-codes the console backend. |

Other notable constants in `base.py`:

- `AUTHENTICATION_BACKENDS = ("parsifal.apps.authentication.backends.CaseInsensitiveUsernameOrEmailModelBackend",)` — login with username **or** e-mail, case-insensitive.
- `ABSOLUTE_URL_OVERRIDES["auth.user"] = /<username>/` — a user's "profile" is their review list.
- `LOGIN_REDIRECT_URL = "login_redirect"` → `/<username>/`.
- `STATIC_ROOT = BASE_DIR.parent.parent / "static"` and `MEDIA_ROOT = BASE_DIR.parent.parent / "media/"` — i.e. **two levels above the repository root** (matches the upstream `/home/parsifal/{parsifal,static,media}` layout). Self-hosted/Docker deployments should override these (see [11-system-design.md](11-system-design.md)).
- `DATA_UPLOAD_MAX_MEMORY_SIZE = 10 MB` — limits BibTeX uploads posted as form data.
- `SITE_ID = 1` — `django.contrib.sites` is used by `invites` to build absolute invite links.
- `DEFAULT_AUTO_FIELD = BigAutoField`.

## Installed apps and middleware

`INSTALLED_APPS` (base): Django contrib (admin, auth, contenttypes, sessions,
messages, staticfiles, sites, sitemaps, humanize), `compressor`,
`crispy_forms`, and the first-party apps `reviews`, `reviews.planning`,
`reviews.conducting`, `reviews.reporting`, `reviews.settings`, `accounts`,
`activities`, `authentication`, `blog`, `core`, `help`, `invites`, `library`.

Middleware is the Django default stack (security, sessions, common, CSRF,
auth, messages, clickjacking). No custom middleware exists.

Template context processor `parsifal.apps.core.context_processors.settings`
exposes `parsifal_version`, `parsifal_release`, `parsifal_environment`,
`recaptcha_*`, `google_analytics_ua`, `sentry_dsn` to every template.

## Running locally (current state)

```bash
uv venv --python 3.9 .venv            # or python3.9 -m venv .venv
uv pip install --python .venv/bin/python -r requirements/local.txt
cp .env.example .env                   # DATABASE_URL=sqlite:////tmp/db.sqlite3 by default
.venv/bin/python manage.py migrate
.venv/bin/python manage.py loaddata source_initial_data   # 7 default digital libraries
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

`requirements/local.txt` adds `django-debug-toolbar`, `django-silk`, `ipython`
and `towncrier` on top of `tests.txt`.

## Management commands

| Command | File | Purpose |
|---------|------|---------|
| `environment` | `apps/core/management/commands/environment.py` | Prints `PARSIFAL_ENVIRONMENT` (used by `bin/deploy`). |
| `release` | `apps/core/management/commands/release.py` | Prints `parsifal@<version>` (used for Sentry releases). |

There are no data-management commands; the fork will add `parsifal init`-style
bootstrap commands (see roadmap).

## Upstream deployment (for reference)

The upstream production layout, encoded in `bin/` and `etc/`:

- `bin/gunicorn_start` — gunicorn, 3 workers, Unix socket `/home/parsifal/run/gunicorn.sock`, `parsifal.settings.production`.
- `etc/supervisord` — supervisor program running `gunicorn_start`.
- `etc/nginx.conf` — TLS termination, redirects `www.` → apex, serves `/static/` and `/media/` from `/home/parsifal/{static,media}`, proxies the rest to gunicorn with `X-Forwarded-*` headers (`SECURE_PROXY_SSL_HEADER` relies on them).
- `bin/deploy` — `git pull`, `pip install -r requirements/production.txt`, `migrate`, `collectstatic`, `supervisorctl restart`, then Sentry release bookkeeping.

`requirements/production.txt` = base + `gunicorn` + `sentry-sdk`.

None of this is used by the fork's target (single container / single process
with SQLite); it is documented so the design in
[11-system-design.md](11-system-design.md) can replace it deliberately.

## Continuous integration

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `.github/workflows/tox.yml` | PR to `master`/`dev`, manual | Ubuntu 22.04, Python 3.9, installs PostgreSQL and creates the `parsifal` DB, runs `tox` (py39 tests + flake8 + isort + `makemigrations --check`). |
| `.github/workflows/codecov.yml` | PR to `master` | Same Postgres setup, `coverage run manage.py test`, uploads to Codecov. |
| `.github/workflows/codeql-analysis.yml` | push to `master`/`dev`, PR to `master`, weekly | CodeQL for Python and JavaScript. |

Both test workflows depend on PostgreSQL only because `DATABASE_URL` defaults
to Postgres; with the SQLite default they reduce to `pip install && tox`.

## Code quality tooling

- `make build` → `isort parsifal && black parsifal && flake8 parsifal && makemigrations --check`.
- `pyproject.toml`: black line length 119, excludes `migrations`.
- `setup.cfg`: flake8 (119 cols, ignores migrations), coverage (branch, omits migrations and tests), isort (Django section, first-party `parsifal`).
- `tox.ini`: envs `py39`, `flake8`, `isort`, `migrations`.
- `towncrier`: changelog fragments in `parsifal/newsfragments/`, compiled into `CHANGELOG.md`.

## Versioning

`parsifal/__init__.py` holds `VERSION = (2, 2, 1, "final", 0)`;
`parsifal/utils/version.py` renders it PEP 440-style (adds `.devYYYYMMDDHHMMSS`
from the last git commit for alpha builds). `PARSIFAL_RELEASE` =
`parsifal@<version>`.
