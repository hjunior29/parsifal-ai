# 16 — Self-hosting

A Parsifal instance is **one process and one directory**: Django served by
gunicorn (static files through WhiteNoise, media through Django) and a data
directory holding the SQLite database, uploaded pictures and backups. No
PostgreSQL, Redis, nginx or workers are required.

## Option A — Docker (recommended)

```bash
git clone https://github.com/hjunior29/parsifal-ai.git && cd parsifal-ai
cp .env.example .env            # set SECRET_KEY (python -c "import secrets; print(secrets.token_urlsafe(50))")
docker compose build
docker compose run --rm parsifal init --username alice --email you@example.org --token "my laptop"
docker compose up -d            # http://localhost:8000
```

- `init` applies migrations, loads the default digital libraries, creates the
  administrator (prints a random password unless `--password` is given) and,
  with `--token NAME`, prints an API token for the CLI/MCP clients.
- `serve` (the container's default command) runs `migrate` and
  `load_default_sources` on every start, then gunicorn
  (`GUNICORN_WORKERS`, default 2; `GUNICORN_TIMEOUT`, default 120).
- The `./data` directory is mounted at `/data` (`PARSIFAL_DATA_DIR`). Back it
  up, or use `docker compose run --rm parsifal manage backup`.
- Other management commands: `docker compose run --rm parsifal manage <command>`.
- Change the published port with `PARSIFAL_PORT=8080 docker compose up -d`.

### Behind HTTPS

Put a reverse proxy (Caddy, nginx, Traefik) in front of port 8000 and set in
`.env`:

```
PARSIFAL_HTTPS=True                          # secure cookies, HSTS, HTTPS redirect
ALLOWED_HOSTS=parsifal.example.org
CSRF_TRUSTED_ORIGINS=https://parsifal.example.org
```

The proxy must forward `X-Forwarded-Proto` (the settings read
`SECURE_PROXY_SSL_HEADER`). Without `PARSIFAL_HTTPS` the instance works on
plain HTTP for a trusted network.

### E-mail

Without `EMAIL_HOST`, password-reset and invite e-mails are written to the
container log (`docker compose logs parsifal`), where the administrator can
copy the links. For real delivery set `EMAIL_HOST`, `EMAIL_PORT`,
`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`,
`DEFAULT_FROM_EMAIL`.

## Option B — plain Python

```bash
python3.10 -m venv .venv && source .venv/bin/activate
pip install -r requirements/production.txt
export DJANGO_SETTINGS_MODULE=parsifal.settings.production
export SECRET_KEY=... ALLOWED_HOSTS=localhost,parsifal.example.org PARSIFAL_DATA_DIR=/var/lib/parsifal
python manage.py collectstatic --noinput
python manage.py init --username alice --email you@example.org --token cli
gunicorn parsifal.wsgi:application --bind 0.0.0.0:8000 --workers 2
```

Run it under systemd or supervisor; the upstream `etc/` and `bin/` examples
still show the nginx + supervisor layout if you prefer a front web server.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | insecure placeholder | **Required** for any reachable instance; `init` warns when missing. |
| `DEBUG` | `True` (`False` in Docker) | Never `True` on a reachable instance. |
| `ALLOWED_HOSTS` | `127.0.0.1,localhost` (`*` in Docker) | Comma-separated host names. |
| `PARSIFAL_DATA_DIR` | `./data` (`/data` in Docker) | Database, media, backups. |
| `PARSIFAL_STATIC_ROOT` | `<data dir>/static` (`/app/staticfiles` in Docker) | Collected static files served by WhiteNoise. |
| `COMPRESS_ENABLED` | `False` | django-compressor bundling; off so WhiteNoise serves the collected files as they are. |
| `DATABASE_URL` | `sqlite:///<data dir>/parsifal.sqlite3` | Only SQLite is supported. |
| `PARSIFAL_ALLOW_SIGNUP` | `False` | Open registration. |
| `PARSIFAL_HTTPS` | `False` | Secure cookies, HSTS, SSL redirect (production settings). |
| `CSRF_TRUSTED_ORIGINS` | empty | Needed when the public origin differs from the host Django sees. |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL` | console backend | SMTP delivery. |
| `GUNICORN_WORKERS`, `GUNICORN_TIMEOUT`, `PORT` | `2`, `120`, `8000` | Container only. |

## Backups and restore

```bash
python manage.py backup                      # <data dir>/backups/parsifal-YYYYmmdd-HHMMSS.sqlite3
python manage.py backup --output /mnt/nas/parsifal.sqlite3
python manage.py restore --file backups/parsifal-20261015-120000.sqlite3 --yes
```

`backup` uses SQLite's online backup API through a dedicated connection, so it
is safe while the application is running (WAL mode). `restore` replaces the
live database contents; stop other processes first. Uploaded pictures are
plain files under `<data dir>/media/` — include them in your backup routine.

## Upgrading

```bash
git pull
docker compose build && docker compose up -d     # migrations run on start
# or, plain Python: pip install -r requirements/production.txt && python manage.py migrate && collectstatic
```

Take a `backup` before upgrading; read `CHANGELOG.md` / `parsifal/newsfragments/`.

## Connecting agents

Create a token (Settings → API tokens, `init --token`, or
`manage.py create_api_token --user admin`), then follow
[15-cli-and-mcp.md](15-cli-and-mcp.md):

```bash
pip install -e "clients/parsifal-cli[mcp]"
export PARSIFAL_URL=http://localhost:8000 PARSIFAL_TOKEN=pfl_...
claude mcp add parsifal -e PARSIFAL_URL=$PARSIFAL_URL -e PARSIFAL_TOKEN=$PARSIFAL_TOKEN -- parsifal-mcp
```

## Security checklist

- Unique `SECRET_KEY`; `DEBUG=False`; explicit `ALLOWED_HOSTS`.
- `PARSIFAL_HTTPS=True` behind TLS; keep sign-up closed unless needed.
- Tokens are hashed at rest; revoke them from Settings → API tokens when a
  machine is retired.
- The `/media/` route serves only uploaded profile pictures; the `/admin/`
  site is available to superusers — protect it at the proxy if exposed to the
  internet.
- Restrict the data directory's permissions; it contains everything.
