# Command-line client

`parsifal` is a thin client of the [JSON API](/docs/api/): one command per API
operation, generated from a single registry, so the CLI never lags behind the
server.

## Install and configure

```bash
pip install -e clients/parsifal-cli        # from a checkout of the repository
export PARSIFAL_URL=http://localhost:8000
export PARSIFAL_TOKEN=pfl_...
parsifal me
```

Or save a profile (file `~/.config/parsifal/config.toml`, mode 600):

```bash
parsifal config set --url https://parsifal.example.org --token pfl_...
parsifal config set --profile lab --url http://lab-server:8000 --token pfl_...
parsifal --profile lab review list
parsifal config show                       # the token is masked
```

Flags (`--url`, `--token`, `--profile`) override environment variables, which
override the config file.

## Commands

`parsifal <group> [<subgroup>] <command> [options]`. Options mirror the API
parameters in kebab-case; `--review` accepts a numeric id or `author/slug`.

| Group | Commands |
|-------|----------|
| root | `me`, `version`, `docs`, `config show|set` |
| `token`, `user` | `list`, `create`, `revoke` / `create` (administrators) |
| `library` | `folder list|create|rename|delete|add|remove|move`, `document list|create|get|update|delete|delete-batch`, `import`, `import-file` |
| `review` | `list`, `create`, `get`, `overview`, `update`, `delete`, `rename`, `reset-selection` |
| `member` | `list` |
| `agent` | `list`, `create`, `new-token`, `delete` (permanent: account, tokens, decisions, quality assessments and extracted data; imported studies and classifications stay) |
| `question`, `keyword`, `criteria` | `list`, `create`, `update`, `delete` (+ `reorder`, `import-picoc`) |
| `search-string` | `get`, `set`, `generate` |
| `source` | `defaults`, `list`, `add`, `update`, `remove`, `document-search`; `source search-string list|set|copy-generic|delete` |
| `quality` | `question …`, `answer …`, `max-score`, `set-cutoff`, `summary`, `get`, `assess` |
| `extraction` | `field …`, `get`, `set`, `done` |
| `article` | `list`, `create`, `get`, `update`, `delete`, `set-status`, `import`, `import-file`, `duplicates`, `resolve-duplicates`, `delete-batch`, `clear`, `star`/`unstar` (`--article`; `list --starred` shows the starred ones); `article pdf upload|download|delete` (the study's PDF: `--article`, `--file` / `-o FILE`) |
| `facet`, `classification`, `test-set`, `checklist` | optional classification steps — see [Classification and search evaluation](/docs/classification/) |
| `decision` | `list`, `record`, `remove-mine`, `article`, `summary`, `agreement`, `disagreements`, `consolidate` |
| `analytics` | `selection-by-source`, `final-by-year`, `facet-frequencies`, `facet-matrix` |
| `export` | `articles`, `extraction`, `report` (all take `-o FILE`) |
| `integration jev` | `show`, `set`, `test`, `remove` |
| `ai-screening` | `setup`, `preview` (the request a run would send), `impact` (what a run would rewrite), `start`, `step`, `runs`, `show`, `results`, `rerun` (a new run with another's settings), `undo-preview`, `undo` (the latest run), and `run` (start, or continue with `--run`, and screen to the end; `--phase inclusion` for Include with AI, `--phase screen` for Screen with AI; what is left out takes the last run's settings, `--defaults` Parsifal's; `--criteria-ids` picks the criteria sent) — see [Exclude, include and screen with AI](/docs/ai-screening/) |

`parsifal <group> --help` lists the options of every command.

## Conventions

- Text options (`--bibtex`, `--search-string`, `--abstract`, `--objective`…)
  accept `@path` to read a file and `-` to read stdin.
- List options are repeated: `--ids 1 --ids 2`, `--synonyms a --synonyms b`.
- Output is JSON when piped or with `--json`; tables on a terminal. `--all`
  fetches every page of a list.
- Exit codes: `0` ok · `1` error · `2` invalid input · `3` authentication or
  permission · `4` not found · `5` conflict · `6` cannot connect.
- Destructive commands ask for confirmation only on an interactive terminal;
  scripts pass `--yes`. Some say first what they will do: `ai-screening undo`
  shows what undoing the run takes back, and `ai-screening start`, `run` and
  `rerun` ask only when the run would rewrite the reviewer's decisions.

## Example

```bash
R=alice/llm-assisted-slrs
parsifal review overview --review $R
parsifal article import --review $R --source-id 7 --bibtex @scopus.bib
parsifal article list --review $R --status U --all | jq -r '.items[] | "\(.id)\t\(.title)"'
parsifal article set-status --review $R --ids 12 --ids 15 --status A --selection-criteria-id 3
parsifal export report --review $R -o report.docx
```

`parsifal docs` prints the whole workflow (planning → conducting → reporting)
command by command.
