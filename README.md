<p align="center">
  <a href="https://parsif.al">
    <img src="https://parsif.al/static/img/dark_grail.svg" alt="Parsifal logo" height="128">
  </a>
</p>

<h3 align="center">Parsifal</h3>

<p align="center">
  Parsifal is a tool to support researchers to perform systematic literature reviews.
  <br>
  <br>
  <a href="https://github.com/vitorfs/parsifal/issues/new">Report bug</a>
  ·
  <a href="https://parsif.al/blog/">Blog</a>
  ·
  <a href="https://parsif.al/help/">Help</a>
</p>

## Status

[![codecov](https://codecov.io/gh/vitorfs/parsifal/branch/master/graph/badge.svg?token=FGjSTTlvuG)](https://codecov.io/gh/vitorfs/parsifal)
[![code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

## About

A systematic literature review is a secondary study with the objective to identify, analyze and interpret all available evidence from primary studies related to a specific research question. As suggested by Kitchenham and Charters, the activity to perform a systematic literature review involves planning, conducting, and reporting the review.

Performing a systematic literature review is a labor-intensive task that requires a huge amount of work from the researcher, designing the protocol, adjusting the search string, filtering the results, sometimes more than a thousand articles, selecting those articles that attend the inclusion criteria, and removing those articles that attend the exclude criteria. After that, the researcher might start to analyze the relevant result one by one.

## Tech Stack

The project is currently running on the following versions:

* Python 3.10+
* Django 4.2
* SQLite
* Bootstrap 3.4
* jQuery 3.6

## Running with Docker

```bash
cp .env.example .env            # set a real SECRET_KEY
docker compose build
docker compose run --rm parsifal init --username admin --email you@example.org --token "my laptop"
docker compose up -d            # http://localhost:8000 — data lives in ./data
```

See [doc/16-self-hosting.md](doc/16-self-hosting.md) for HTTPS, e-mail, backups and upgrades.

## Running Locally

To run the project locally first you need to clone the repository:

```bash
git clone https://github.com/hjunior29/parsifal-ai.git
cd parsifal-ai
```

Create a virtualenv with Python 3.10 or newer and install the development requirements:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements/local.txt
```

Optionally create a `.env` file from the template (all values have local defaults):

```bash
cp .env.example .env
```

Parsifal uses SQLite. By default the database, uploaded files and collected static files live in `./data/`
(override with `PARSIFAL_DATA_DIR`, or point `DATABASE_URL` to another SQLite file).

Run the migrations, load the default digital libraries and create your user:

```bash
python manage.py migrate
python manage.py loaddata source_initial_data
python manage.py createsuperuser
```

Run the local server:

```bash
python manage.py runserver
```

Or bootstrap everything in one step (migrations, default sources, administrator and an API token):

```bash
python manage.py init --username admin --email you@example.com --token "my laptop"
```

Run the test suite and linters:

```bash
tox
```

## API, CLI and agents

Every operation of a review is available through a JSON API at `/api/v1/` (interactive docs at
`/api/v1/docs`). Create a personal token under *Settings → API tokens* and call the API with
`Authorization: Bearer <token>`.

The `parsifal` command-line client wraps the whole API for scripts and AI coding agents:

```bash
pip install -e clients/parsifal-cli
export PARSIFAL_URL=http://localhost:8000 PARSIFAL_TOKEN=pfl_...
parsifal review overview --review admin/my-review
parsifal docs    # the review workflow, command by command

# MCP server for Claude Code, Codex and other agents (same operations as tools)
pip install -e "clients/parsifal-cli[mcp]"
claude mcp add parsifal -e PARSIFAL_URL=$PARSIFAL_URL -e PARSIFAL_TOKEN=$PARSIFAL_TOKEN -- parsifal-mcp
```

A running instance documents these features itself at `/docs/`. Developer documentation:
[doc/14-api.md](doc/14-api.md), [doc/15-cli-and-mcp.md](doc/15-cli-and-mcp.md) and the rest of
[doc/](doc/README.md).

## License

The source code is released under the [MIT License](https://github.com/vitorfs/parsifal/blob/master/LICENSE).
