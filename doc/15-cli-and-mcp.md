# 15 — CLI and MCP server

Both clients live in `clients/parsifal-cli/` as one installable package
(`parsifal-cli`, Python ≥ 3.10) and never import Django: they talk to the
JSON API ([14-api.md](14-api.md)). A single **operation registry**
(`parsifal_cli/operations.py`) describes every API operation — id, method,
path, parameters, pagination/download/destructive flags — and both the
`parsifal` command tree and the MCP tools are generated from it. The
server-side test `parsifal/api/tests/test_cli_parity.py` fails whenever the
API's OpenAPI document and the registry disagree.

## Installation

```bash
pip install -e clients/parsifal-cli        # inside the repo; adds the `parsifal` command
# or, from a checkout, without the server: pip install ./clients/parsifal-cli
parsifal version
```

## Configuration

Precedence: command-line flags → environment → profile in the config file.

| Setting | Flag | Environment | Config file |
|---------|------|-------------|-------------|
| Server URL (default `http://localhost:8000`) | `--url` | `PARSIFAL_URL` | `url` |
| API token | `--token` | `PARSIFAL_TOKEN` | `token` |
| Profile name (default `default`) | `--profile` | `PARSIFAL_PROFILE` | section name |
| Config file location | — | `PARSIFAL_CONFIG` | `~/.config/parsifal/config.toml` (`XDG_CONFIG_HOME` respected) |

```bash
parsifal config set --url https://parsifal.example.org --token pfl_...   # written with mode 600
parsifal config set --profile lab --url http://lab-server:8000 --token pfl_...
parsifal --profile lab me
parsifal config show                                                     # token is masked
```

## Command tree

`parsifal <group> [<subgroup>] <command> [options]`. Every command's options
mirror the API parameters in kebab-case; `--review` accepts a numeric id or
`author/slug`.

| Group | Commands |
|-------|----------|
| (root) | `me`, `version`, `docs` (prints the workflow guide), `config show|set` |
| `token` | `list`, `create --name`, `revoke --id` |
| `user` | `list`, `create --username --email [--password …]` (administrators) |
| `review` | `list [--author --name --q --limit --offset --all]`, `create`, `get`, `overview`, `update`, `delete`, `rename --name` |
| `member` | `list` |
| `agent` | `list`, `create --name`, `new-token --id`, `delete --id` (permanent: account, tokens, decisions, quality assessments and extracted data; imported studies and classifications stay) |
| `question` | `list`, `create --description [--parent-id]`, `update --id`, `delete --id`, `reorder --ids …` |
| `keyword` | `list`, `create --description [--related-to P|I|C|O] [--synonyms …]`, `update --id`, `delete --id`, `import-picoc` |
| `search-string` | `get`, `set --search-string`, `generate` |
| `source` | `defaults`, `list`, `add --source-id | --name --url`, `update --id`, `remove --id`, `document-search --id --search-type --searched-at --years-from --years-to --result-count`; `source search-string list|set|copy-generic|delete --id` |
| `criteria` | `list`, `create --description --criteria-type I|E`, `update --id`, `delete --id` |
| `quality` | `question list|create|update|delete|reorder`, `answer list|create|suggested|update|delete`, `max-score`, `set-cutoff --cutoff`, `summary`, `get --article`, `assess --article --question-id --answer-id` |
| `extraction` | `field list|create|update|delete|reorder`, `get --article`, `set --article --field-id --value | --values …`, `done --article [--no-done]` |
| `article` | `list [--source-id --status --q --finished-data-extraction --all]`, `create`, `get --id`, `update --id`, `delete --id`, `set-status --ids … --status [--selection-criteria-id --comments]`, `import --source-id --bibtex`, `import-file --source-id --file`, `duplicates`, `resolve-duplicates [--ids …]` |
| `analytics` | `selection-by-source`, `final-by-year`, `facet-frequencies --facet`, `facet-matrix --rows --columns` |
| `facet` | `templates`, `list`, `create --template | --name [--categories …] [--multiple]`, `update --id`, `delete --id`, `reorder --ids …`; `facet category create|update|delete|reorder --facet` |
| `classification` | `get --article`, `set --article --facet-id --category-ids …` |
| `test-set` | `get`, `add --title [--doi]`, `update --id`, `delete --id`, `match` |
| `checklist` | `get`, `set --key --applied/--no-applied [--notes]` |
| `decision` | `list [--stage --user-id --article-id --status]`, `record --ids … --status [--stage --selection-criteria-id --comments]`, `remove-mine --article`, `article --article`, `summary`, `agreement [--user-a-id --user-b-id]`, `disagreements`, `consolidate [--rule unanimous|any_include|majority] [--ids …]` |
| `export` | `articles --format csv|xlsx|json -o FILE`, `extraction --format … -o FILE`, `report [--sections …] -o FILE` |
| `integration jev` | `show`, `set [--api-key -|@file|KEY] [--model jev-1.13.0]`, `test`, `remove` (your own Jev key) |
| `ai-screening` | `setup`, `start [--objective … --guidance … --threshold 0.9 --source-id S --rescreen]`, `step --id RUN [--size 8]`, `cancel --id RUN`, `runs`, `show --id RUN`, `results --id RUN [--outcome excluded|passed|error]`; composite `run` (the options of `start`, plus `--run RUN` to continue and `--step-size`, default 25) starts a run and screens until it ends, printing progress to stderr; Ctrl-C cancels it |

Conventions:

- **Text options** (`--bibtex`, `--search-string`, `--abstract`, `--comments`,
  `--description` of questions, `--objective`, `--value`…) accept `@path` to
  read a file and `-` to read stdin.
- **List options** are repeated: `--ids 1 --ids 2`, `--synonyms a --synonyms b`.
- **Output** is JSON when stdout is not a terminal or with `--json`; on a
  terminal, lists render as tables and objects as key/value pairs. `--all` on
  paginated lists fetches every page into one `{"count", "items"}` document.
- **Downloads** need `-o/--output FILE` (`-` streams to stdout).
- **Destructive commands** (`delete`, `remove`, `revoke`) ask for confirmation
  only when both stdin and stdout are terminals; scripts and agents pass
  `--yes` or simply run non-interactively.
- **Exit codes**: `0` ok · `1` error · `2` invalid input (HTTP 422 or bad
  reference) · `3` authentication/permission (401/403) · `4` not found ·
  `5` conflict (409) · `6` cannot connect. Error details go to stderr as
  `error: <detail>`.

## Example: an agent screening a review

```bash
export PARSIFAL_URL=http://localhost:8000 PARSIFAL_TOKEN=pfl_...
R=alice/llm-assisted-slrs
parsifal review overview --review $R                       # what exists / what is missing
parsifal article list --review $R --status U --all \
  | jq -r '.items[] | "\(.id)\t\(.title)\n\(.abstract)\n"'  # read titles/abstracts
parsifal criteria list --review $R                         # pick the reason
parsifal article set-status --review $R --ids 12 --ids 15 --status A --selection-criteria-id 3
parsifal article set-status --review $R --ids 13 --status R --selection-criteria-id 4 --comments "not empirical"
parsifal quality assess --review $R --article 12 --question-id 1 --answer-id 2
parsifal extraction set --review $R --article 12 --field-id 5 --value "ReviewBot"
parsifal export report --review $R -o report.docx
```

`parsifal docs` prints the full planning → conducting → reporting guide that
ships with the package (`parsifal_cli/data/workflow.md`); the MCP server
exposes the same text through its `parsifal_workflow_guide` tool.

## Tests

- `clients/parsifal-cli/tests/` (pytest): registry invariants, `--help` for
  every generated command, request shaping (JSON bodies, lists, `@file`,
  stdin, booleans, multipart upload, pagination `--all`, downloads), error
  exit codes, connection failures, config precedence and masking.
- `parsifal/api/tests/test_cli_parity.py`: registry ⇄ OpenAPI (ids, methods,
  paths, path/query parameters).
- `parsifal/api/tests/test_cli_e2e.py`: the real CLI against a
  `LiveServerTestCase` server, from `review create` to `export report`.
- Run everything with `tox` (env `cli` runs the pytest suite) or
  `python -m pytest clients/parsifal-cli`.

## MCP server (`parsifal-mcp`)

`parsifal_mcp/server.py` builds a [FastMCP](https://github.com/modelcontextprotocol/python-sdk)
server from the same registry: **one tool per API operation**, named
`parsifal_<operationId>` (e.g. `parsifal_articles_set_status`), with the same
parameters as the CLI (`review_id` = id or `author/slug`; lists are JSON
arrays; downloads take `output_path`). Tool annotations mark read-only,
destructive and idempotent operations so clients can ask for confirmation.

Composite tools (fewer round-trips for agents):

| Tool | Returns |
|------|---------|
| `parsifal_articles_screen_batch(review_id, limit=20, offset=0, status="U")` | A page of articles with title/abstract/keywords **and** the review's selection criteria — everything needed to decide, then call `parsifal_articles_set_status`. |
| `parsifal_review_protocol(review_id)` | The whole protocol as Markdown (also exposed as the resource `parsifal://reviews/{review_id}/protocol`). |
| `parsifal_workflow_guide()` | The planning → conducting → reporting guide (`parsifal docs`). |
| `parsifal_ai_screening_run(review_id, run_id=None, step_size=25, max_seconds=240, <start fields>)` | Exclude with AI in one call: starts a run (or continues `run_id`) and steps until it ends or the time budget passes; then `message` says to call again with `run_id`. Uses the Jev key of the token's user. |

### Install and connect

```bash
pip install -e "clients/parsifal-cli[mcp]"
export PARSIFAL_URL=http://localhost:8000 PARSIFAL_TOKEN=pfl_...

# Claude Code (stdio)
claude mcp add parsifal -e PARSIFAL_URL=$PARSIFAL_URL -e PARSIFAL_TOKEN=$PARSIFAL_TOKEN -- parsifal-mcp

# Codex / other stdio clients: command "parsifal-mcp", env PARSIFAL_URL + PARSIFAL_TOKEN
# Remote agents: streamable HTTP on http://host:8765/mcp
parsifal-mcp --transport http --host 0.0.0.0 --port 8765
```

`parsifal-mcp --url … --token … --profile …` override the environment and the
config file, exactly like the CLI. The server never touches the database; it
only talks to the API, so it can run anywhere the API is reachable.

### Tests

`clients/parsifal-cli/tests/test_mcp.py`: tool inventory = registry +
composites, input schemas and annotations, tool calls against a fake API
(JSON bodies, review references, downloads, errors as tool errors), the
composite tools and `parsifal-mcp --help`. The stdio transport was also
exercised end-to-end with the MCP Python client during development.
