# Self-hosting

A Parsifal instance is one process and one directory. The database is SQLite;
uploaded pictures, backups and (by default) collected static files live in the
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
| `PARSIFAL_DATA_DIR` | `./data` (`/data`) | Database, media, backups. |
| `PARSIFAL_ALLOW_SIGNUP` | `False` | Open registration. |
| `PARSIFAL_HTTPS` | `False` | Secure cookies, HSTS and HTTPS redirect when behind TLS. |
| `CSRF_TRUSTED_ORIGINS` | empty | Public origin when it differs from the host Django sees. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | console | Without `EMAIL_HOST`, e-mails (password reset) are written to the log. |

## HTTPS

Put a reverse proxy (Caddy, nginx, Traefik) in front of port 8000, forward
`X-Forwarded-Proto`, and set `PARSIFAL_HTTPS=True`, `ALLOWED_HOSTS` and
`CSRF_TRUSTED_ORIGINS=https://your-host`.

## Backups

```bash
python manage.py backup                        # <data dir>/backups/parsifal-<timestamp>.sqlite3
python manage.py restore --file <backup> --yes # replaces the live database; stop other processes first
```

`backup` uses SQLite's online backup API and is safe while the application
runs. Back up the whole data directory to keep uploaded pictures too.

## Upgrading

Take a backup, `git pull`, rebuild (`docker compose build && docker compose up -d`)
or `pip install -r requirements/production.txt && python manage.py migrate &&
python manage.py collectstatic --noinput`. Migrations run automatically when the
container starts.
