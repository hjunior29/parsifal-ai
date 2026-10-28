# Self-hosting

A Parsifal instance is one process and one directory. The database is SQLite;
the studies' PDFs, backups and (by default) collected static files live in the
**data directory** (`PARSIFAL_DATA_DIR`, `./data` or `/data` in Docker).

## Docker

```bash
git clone https://github.com/hjunior29/parsifal-ai.git && cd parsifal-ai
cp .env.example .env     # set SECRET_KEY: python -c "import secrets; print(secrets.token_urlsafe(50))"
docker compose build
docker compose run --rm parsifal init --username alice --email you@example.org --token "my laptop"
docker compose up -d     # http://localhost:8000
```

`init` applies migrations, loads the default digital libraries, creates the
administrator (a random password is printed unless `--password` is given) and,
with `--token`, prints an API token once. The container's default command
(`serve`) migrates on every start and runs gunicorn; `docker compose run --rm
parsifal manage <command>` runs any management command.

## Plain Python

```bash
python3.10 -m venv .venv && source .venv/bin/activate
pip install -r requirements/production.txt
export DJANGO_SETTINGS_MODULE=parsifal.settings.production SECRET_KEY=... ALLOWED_HOSTS=parsifal.example.org
python manage.py collectstatic --noinput
python manage.py init --username alice --email you@example.org --token cli
gunicorn parsifal.wsgi:application --bind 0.0.0.0:8000 --workers 2
```

## Settings that matter

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | insecure placeholder | Required for any reachable instance. |
| `DEBUG` | `True` (`False` in Docker) | Never `True` when reachable by others. |
| `ALLOWED_HOSTS` | `127.0.0.1,localhost` (`*` in Docker) | Host names of the instance. |
| `PARSIFAL_DATA_DIR` | `./data` (`/data`) | Database, the studies' PDFs (`files/`), backups. |
| `PARSIFAL_ALLOW_SIGNUP` | `False` | Open registration. |
| `PARSIFAL_HTTPS` | `False` | Secure cookies, HSTS and HTTPS redirect when behind TLS. |
| `CSRF_TRUSTED_ORIGINS` | empty | Public origin when it differs from the host Django sees. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | console | Without `EMAIL_HOST`, e-mails (password reset) are written to the log. |
| `PARSIFAL_PDF_MAX_MB` | `50` | Largest PDF accepted per study. |
| `PARSIFAL_FILES_BUCKET` | empty | Keep the PDFs in an S3-compatible bucket (next section). |

## Full texts in a bucket

Each study may have one PDF, kept in `<data dir>/files/` and read only through
a route that checks the reader is a member of the review. To keep the PDFs in
a bucket instead (Tigris, Cloudflare R2, MinIO, AWS S3), set:

```
PARSIFAL_FILES_BUCKET=my-papers
AWS_ENDPOINT_URL_S3=https://fly.storage.tigris.dev   # your provider's endpoint
AWS_REGION=auto
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

The bucket stays private: the browser gets a signed link that expires (5
minutes, `PARSIFAL_FILES_LINK_SECONDS`). The Docker image already has the S3
client; a plain-Python install needs `pip install -r requirements/s3.txt`.
Existing PDFs are not moved when you switch: copy them over first.

## HTTPS

Put a reverse proxy (Caddy, nginx, Traefik) in front of port 8000, forward
`X-Forwarded-Proto`, and set `PARSIFAL_HTTPS=True`, `ALLOWED_HOSTS` and
`CSRF_TRUSTED_ORIGINS=https://your-host`.

## Backups

```bash
python manage.py backup                        # <data dir>/backups/parsifal-<timestamp>.tar.gz
python manage.py backup --keep 10              # then only the 10 newest of that folder remain
python manage.py restore --file <backup> --yes # the database and the files; stop other processes first
```

A backup is one `.tar.gz`: a copy of the database (SQLite's online backup API,
safe while the application runs), every study's PDF — from `files/` or from
the bucket — and a manifest with each file's checksum. `restore` checks the
checksums, backs up the current state first (`backups/before-restore-…`), then
replaces the database and writes back the PDFs that are missing; an old
`.sqlite3` backup restores the database alone. In Docker, `serve` takes a
backup before applying migrations (`PARSIFAL_BACKUP_KEEP`, default 10, are
kept).

## Upgrading

Take a backup, `git pull`, rebuild (`docker compose build && docker compose up -d`)
or `pip install -r requirements/production.txt && python manage.py migrate &&
python manage.py collectstatic --noinput`. Migrations run automatically when the
container starts.
