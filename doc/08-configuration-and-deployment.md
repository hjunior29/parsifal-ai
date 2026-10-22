# 08 — Configuration and Deployment

## Settings modules

All settings live in `parsifal/settings/`. `manage.py` defaults to
`parsifal.settings.local`; `parsifal/wsgi.py` defaults to
`parsifal.settings.production`; tox and CI pass `--settings=parsifal.settings.tests`.

| Module | Extends | What it changes |
|--------|---------|-----------------|
| `base.py` | — | Everything common: apps, middleware, templates, DB, auth, i18n, static/media, third-party keys. |
| `local.py` | base | Adds `debug_toolbar`, and `silk` (profiler) only when `SILK=1` (it writes every request and query into the database); console e-mail backend. |
| `production.py` | base | Phase 6: security headers/cookies gated by `PARSIFAL_HTTPS`; SMTP when `EMAIL_HOST` is set, console backend otherwise; `CSRF_TRUSTED_ORIGINS`. Used by the Docker image. |
| `tests.py` | base | MD5 password hasher (speed); `GOOGLE_RECAPTCHA_ENABLED = False`. |

Configuration values are read with `python-decouple` (`config(...)`) from the
environment or a `.env` file in the project root (`.env.example` is the
template). `DATABASE_URL` is parsed by `dj-database-url`.

## Environment variables

| Variable | Default (base.py) | Used by | Fork relevance |
|----------|-------------------|---------|----------------|
| `SECRET_KEY` | `"parsifal.settings.local"` | Django, `core/crypto.py` | Must be set in self-hosted deployments. It also derives the key that encrypts the users' Jev API keys: after changing it, each user saves their Jev key again (API tokens are hashed and not affected). |
| `DEBUG` | `True` | Django | |
| `ALLOWED_HOSTS` | `127.0.0.1,localhost` (CSV) | Django | |
| `ADMINS` | `""` (`name,email;name,email`) | Django error mail | |
| `PARSIFAL_DATA_DIR` | `<repo root>/data` (created on startup) | settings | Holds the SQLite file, `files/` (the studies' PDFs, unless they go to a bucket), `media/` and (by default) collected `static/`. Added in phase 0. |
| `PARSIFAL_STATIC_ROOT` | `<PARSIFAL_DATA_DIR>/static` | settings | Phase 6. Docker collects into `/app/staticfiles`, outside the data volume. |
| `PARSIFAL_PDF_MAX_MB` | `50` | `services/full_texts.py` | Largest PDF accepted per study. |
| `PARSIFAL_FILES_BUCKET` | empty | `STORAGES["files"]` | When set, the studies' PDFs go to this S3-compatible bucket (django-storages `S3Storage`, `requirements/s3.txt`) instead of `<PARSIFAL_DATA_DIR>/files`. Private bucket, SigV4 links that expire. |
| `AWS_ENDPOINT_URL_S3`, `AWS_REGION` | empty | `STORAGES["files"]` | The bucket's endpoint and region. |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | empty | boto3 | Read by boto3 from the environment; never copied into the settings. |
| `PARSIFAL_FILES_PREFIX`, `PARSIFAL_FILES_LINK_SECONDS` | empty, `300` | `STORAGES["files"]` | Folder inside the bucket; lifetime of the signed links the browser is sent to. |
| `DATABASE_URL` | `sqlite:///<PARSIFAL_DATA_DIR>/parsifal.sqlite3` (upstream: a Postgres URL) | `dj_database_url` | SQLite connections get `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=30000`, `foreign_keys=ON` via `core/database.py` (ADR-001). |
| `LANGUAGE_CODE` | `en-us` | i18n | `LANGUAGES` lists en-us and pt-br but `parsifal/locale/` does not exist in the repo. |
| `TIME_ZONE` | `UTC` | | |
| `COMPRESS_ENABLED` | `False` (upstream: `not DEBUG`) | django-compressor | Phase 6: off by default; WhiteNoise serves collected files. |
| ~~`ELSEVIER_API_KEY`~~ | — | — | Scopus search removed (cleanup round, 2026-10-16). |
| `PARSIFAL_ALLOW_SIGNUP` | `False` | `SignUpView`, header, cover page | Added in phase 1. When `False`, `/signup/` answers 403 unless the request carries a pending invite code; the admin creates accounts (`createsuperuser`, admin site) or users arrive through co-author invites. |
| `PARSIFAL_ENVIRONMENT` | `local` | context processor, `environment` command | Keep. |
| `JEV_API_URL` | `https://api.typesafe.ai` | `core/jev.py` | Base URL of Jev for *Exclude/Include/Screen with AI*; can point to a compatible server. The API key is per user, in Settings → Integrations. |
| `JEV_REQUESTS_PER_MINUTE` | `1080` | `core/jev.py` | Requests per minute sent to Jev with one key, across the threads of a process (TypeSafe allows 1,200); a 429 holds them all for its Retry-After. Lower it if Jev answers 429 often; `0` turns the spacing off. |
| `PARSIFAL_HTTPS` | `False` | `production.py` | Phase 6. Enables secure cookies, HSTS and the HTTPS redirect. |
| `CSRF_TRUSTED_ORIGINS` | empty (CSV) | `production.py` | Phase 6. |
| `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `SERVER_EMAIL` | console backend / `Parsifal <noreply@localhost>` | `production.py` | Phase 6. SMTP is used automatically when `EMAIL_HOST` is set. |
| ~~`GOOGLE_ANALYTICS_UA`, `GOOGLE_RECAPTCHA_*`, `SENTRY_DSN`~~ | — | — | Removed in phase 1 (ADR-003). |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | required in `production.py` | invites, password reset | Keep optional; self-hosted may use console/file backend. |
| `EMAIL_BACKEND` | (only in `.env.example`) | not read by settings | `.env.example` lists it but `base.py` never calls `config("EMAIL_BACKEND")`; `local.py` hard-codes the console backend. |

Other notable constants in `base.py`:

- `AUTHENTICATION_BACKENDS = ("parsifal.apps.authentication.backends.CaseInsensitiveUsernameOrEmailModelBackend",)` — login with username **or** e-mail, case-insensitive.
- `ABSOLUTE_URL_OVERRIDES["auth.user"] = /<username>/` — a user's "profile" is their review list.
- `LOGIN_REDIRECT_URL = "login_redirect"` → `/<username>/`.
- `STATIC_ROOT = PARSIFAL_DATA_DIR / "static"` and `MEDIA_ROOT = PARSIFAL_DATA_DIR / "media"` (upstream kept them two levels above the repository root to match its `/home/parsifal/{parsifal,static,media}` layout). `MEDIA_ROOT` is no longer served (nothing public is uploaded).
- `STORAGES["files"]` — where the studies' PDFs are kept: `FileSystemStorage` at `PARSIFAL_DATA_DIR / "files"`, or `S3Storage` when `PARSIFAL_FILES_BUCKET` is set. Code reaches it through `core.models.files_storage()`; the test settings point it at a temporary folder.
- `DATA_UPLOAD_MAX_MEMORY_SIZE = 10 MB` — limits BibTeX uploads posted as form data.
- `SITE_ID = 1` — `django.contrib.sites` is used by `invites` to build absolute invite links.
- `DEFAULT_AUTO_FIELD = BigAutoField`.

## Installed apps and middleware

`INSTALLED_APPS` (base): Django contrib (admin, auth, contenttypes, sessions,
messages, staticfiles, sites, sitemaps, humanize), `compressor`,
`crispy_forms`, and the first-party apps `reviews`, `reviews.planning`,
`reviews.conducting`, `reviews.reporting`, `reviews.settings`, `accounts`,
`authentication`, `core`, `docs` (phase 9), `invites`, `library`, plus `ninja` and
`parsifal.api` (phase 3). `activities`, `blog` and `help` were removed in phase 1.

Middleware is the Django default stack (security, sessions, common, CSRF,
auth, messages, clickjacking). No custom middleware exists.

Template context processor `parsifal.apps.core.context_processors.settings`
exposes `parsifal_version`, `parsifal_release`, `parsifal_environment` and
`allow_signup` to every template.

## Running locally (current state)

```bash
uv venv --python 3.10 .venv           # or python3.10 -m venv .venv
uv pip install --python .venv/bin/python -r requirements/local.txt
cp .env.example .env                   # optional: every value has a local default
.venv/bin/python manage.py migrate     # creates ./data/parsifal.sqlite3
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
| `release` | `apps/core/management/commands/release.py` | Prints `parsifal@<version>`. |
| `init` | `apps/core/management/commands/init.py` | Phase 3. Migrate, load default sources, create the administrator (`--username`, `--email`, `--password`; random password printed if omitted), optionally `--token NAME` prints an API token; warns about an insecure `SECRET_KEY`. Idempotent. |
| `create_api_token` | `apps/core/management/commands/create_api_token.py` | Phase 3. `--user <username> [--name CLI]` prints a new token. |
| `load_default_sources` | `apps/core/management/commands/load_default_sources.py` | Phase 3. Idempotent alternative to `loaddata source_initial_data`. |

Other settings added by the fork: `NINJA_PAGINATION_PER_PAGE = 100`,
`NINJA_PAGINATION_MAX_LIMIT = 1000` (API list endpoints). The API itself is
documented in [14-api.md](14-api.md).

## Deployment (fork)

See [16-self-hosting.md](16-self-hosting.md): `Dockerfile` + `docker-compose.yml`
(single container, `./data` volume), `bin/entrypoint.sh`, WhiteNoise for
static files, Django-served `/media/`, `manage.py backup`/`restore`.

## Upstream deployment (for reference)

The upstream production layout, encoded in `bin/` and `etc/`:

- `bin/gunicorn_start` — gunicorn, 3 workers, Unix socket `/home/parsifal/run/gunicorn.sock`, `parsifal.settings.production`.
- `etc/supervisord` — supervisor program running `gunicorn_start`.
- `etc/nginx.conf` — TLS termination, redirects `www.` → apex, serves `/static/` and `/media/` from `/home/parsifal/{static,media}`, proxies the rest to gunicorn with `X-Forwarded-*` headers (`SECURE_PROXY_SSL_HEADER` relies on them).
- `bin/deploy` — `git pull`, `pip install -r requirements/production.txt`, `migrate`, `collectstatic`, `supervisorctl restart`, then Sentry release bookkeeping.

`requirements/production.txt` = base + `gunicorn` (`sentry-sdk` removed in phase 1).

None of this is used by the fork's target (single container / single process
with SQLite); it is documented so the design in
[11-system-design.md](11-system-design.md) can replace it deliberately.

## Continuous integration

Since 2026-10-18 every workflow runs **only when started by hand** (`workflow_dispatch`, Actions tab): automatic
runs on push, pull request and schedule are off while the fork is in active development. Run the checks locally
(see [09-testing.md](09-testing.md)). To turn them back on, restore the `on:` triggers listed below.

| Workflow | Former trigger | What it does |
|----------|----------------|--------------|
| `.github/workflows/tox.yml` | push to `dev`, PR to `master`/`dev`, manual | Ubuntu 22.04, Python 3.10, `tox` (py310 tests + flake8 + isort + `makemigrations --check`). No database service needed. |
| `.github/workflows/codecov.yml` | PR to `master`/`dev` | `coverage run manage.py test`, uploads to Codecov (`fail_ci_if_error: false` so a missing token does not block). |
| `.github/workflows/codeql-analysis.yml` | push/PR to `master`/`dev`, weekly | CodeQL v3 for Python and JavaScript. |
| `.github/workflows/docker.yml` | push to `dev`, PR to `master`/`dev`, manual | Builds the image and smoke-tests it. |

Upstream's workflows installed PostgreSQL in CI; phase 0 removed that along
with the Postgres default.

## Code quality tooling

- `make build` → `isort parsifal && black parsifal && flake8 parsifal && makemigrations --check`.
- `pyproject.toml`: black line length 119, target `py310`, excludes `migrations`.
- `setup.cfg`: flake8 (119 cols, ignores migrations), coverage (branch, omits migrations and tests), isort (Django section, first-party `parsifal`).
- `tox.ini`: envs `py310`, `flake8`, `isort`, `migrations` (`basepython = python3.10`).
- `towncrier`: changelog fragments in `parsifal/newsfragments/`, compiled into `CHANGELOG.md`.

## Versioning

`parsifal/__init__.py` holds `VERSION = (2, 2, 1, "final", 0)`;
`parsifal/utils/version.py` renders it PEP 440-style (adds `.devYYYYMMDDHHMMSS`
from the last git commit for alpha builds). `PARSIFAL_RELEASE` =
`parsifal@<version>`.
