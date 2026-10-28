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
| `token` | `list`, `create --name`, `revoke --id`, `delete --id` (revoked only) |
| `user` | `list`, `create --username --email [--password …]` (administrators) |
| `review` | `list [--author --name --q --limit --offset --all]`, `create`, `get`, `overview`, `update`, `delete`, `rename --name`, `reset-selection [--reviewer-ids U …]` (every study but duplicates unclassified, the chosen reviewers' decisions deleted; asks for confirmation) |
| `member` | `list` |
| `agent` | `list`, `create --name`, `new-token --id`, `delete --id` (permanent: account, tokens, decisions, quality assessments and extracted data; imported studies and classifications stay) |
| `question` | `list`, `create --description [--parent-id]`, `update --id`, `delete --id`, `reorder --ids …` |
| `keyword` | `list`, `create --description [--related-to P|I|C|O] [--synonyms …]`, `update --id`, `delete --id`, `import-picoc` |
| `search-string` | `get`, `set --search-string`, `generate` |
| `source` | `defaults`, `list`, `add --source-id | --name --url`, `update --id`, `remove --id`, `document-search --id --search-type --searched-at --years-from --years-to --result-count`; `source search-string list|set|copy-generic|delete --id` |
| `criteria` | `list`, `create --description --criteria-type I|E`, `update --id`, `delete --id` |
| `quality` | `question list|create|update|delete|reorder`, `answer list|create|suggested|update|delete`, `max-score`, `set-cutoff --cutoff`, `summary`, `studies [--q --state done|pending|above|below --order title|-title|year|-year --all]`, `get --article`, `assess --article --question-id [--answer-id]` (no `--answer-id`: clear the answer) |
| `extraction` | `field list|create|update|delete|reorder`, `get --article`, `set --article --field-id --value | --values …`, `done --article [--no-done]`, `studies [--q --done/--no-done --all]` |
| `article` | `list [--source-id --status --q --finished-data-extraction --starred --order COLUMN|-COLUMN --all]` (`--order`: title, ai_score, star, year, status… as the study list's columns), `star --article`, `unstar --article`, `create`, `get --id`, `update --id`, `delete --id`, `set-status --ids …|--all-matching [--match-source-id --match-status --match-q --match-starred] --status [--selection-criteria-id --comments]`, `delete-batch --ids …|--all-matching [--match-*]`, `import --source-id --bibtex`, `import-file --source-id --file`, `duplicates`, `resolve-duplicates [--ids …]`, `pdf upload --article --file`, `pdf download --article -o FILE`, `pdf delete --article` |
| `analytics` | `selection-by-source`, `final-by-year`, `selection-summary`, `criteria-usage`, `studies-by-year`, `quality`, `extraction`, `facet-frequencies --facet`, `facet-matrix --rows --columns` |
| `facet` | `templates`, `list`, `create --template | --name [--categories …] [--multiple]`, `update --id`, `delete --id`, `reorder --ids …`; `facet category create|update|delete|reorder --facet` |
| `classification` | `get --article`, `set --article --facet-id --category-ids …` |
| `test-set` | `get`, `add --title [--doi]`, `update --id`, `delete --id`, `match` |
| `checklist` | `get`, `set --key --applied/--no-applied [--notes]` |
| `decision` | `list [--stage --user-id --article-id --status]`, `record --ids … --status [--stage --selection-criteria-id --comments]`, `remove-mine --article`, `article --article`, `summary`, `agreement [--user-a-id --user-b-id]`, `disagreements`, `consolidate [--rule unanimous|any_include|majority] [--ids …]` |
| `export` | `articles --format csv|xlsx|json -o FILE`, `extraction --format … -o FILE`, `report [--sections …] -o FILE` |
| `integration library-access` | `show`, `set --address URL` (the proxy's address or any page opened through it), `remove` — your library proxy, so studies carry `access_url` |
| `integration jev` | `show`, `set [--api-key -|@file|KEY] [--model jev-1.13.0]`, `test [--api-key -]` (Jev's models for the saved key or for one you are about to save), `remove` (your own Jev key) |
| `ai-screening` | `setup [--phase inclusion|screen --defaults]` (`start`: the settings a run starts from, the last run's of the action), `start --reviewer-id U [--phase inclusion|screen --model M --objective … --guidance … --template @request.json --threshold 0.9 --thresholds I1=0.9 --source-id S (0: all) --statuses R --statuses U --criteria-ids C --defaults]` (what is left out takes the last run's settings, `--defaults` Parsifal's), `preview [same options, --article A]` (the request a run would send to Jev about one study; nothing is sent), `step --id RUN [--size 64]` (also continues an interrupted run), `runs`, `show --id RUN`, `results --id RUN [--outcome excluded|passed|included|undecided|error]`, `impact --reviewer-id U [--phase … --statuses … --source-id S | --run-id RUN]` (what a run would rewrite), `rerun --id RUN [--reviewer-id --model --threshold --thresholds --statuses --source-id --criteria-ids]` (a new run with RUN's settings), `undo-preview --id RUN`, `undo --id RUN` (only the latest run: takes back what still stands of it and deletes it); composite `run` (the options of `start`, plus `--run RUN` to continue and `--step-size`, default 64) starts a run and screens until it ends, printing progress to stderr; when the run is interrupted (Jev refused the key or was unavailable) or on Ctrl-C it exits with code 1 and says how to continue with `--run RUN` |

Conventions:

- **Text options** (`--bibtex`, `--search-string`, `--abstract`, `--comments`,
  `--description` of questions, `--objective`, `--value`…) accept `@path` to
  read a file and `-` to read stdin.
- **List options** are repeated: `--ids 1 --ids 2`, `--synonyms a --synonyms b`.
- **Output** is JSON when stdout is not a terminal or with `--json`; on a
  terminal, lists render as tables and objects as key/value pairs. `--all` on
  paginated lists fetches every page into one `{"count", "items"}` document.
- **Downloads** need `-o/--output FILE` (`-` streams to stdout).
- **Destructive commands** (`delete`, `remove`, `revoke`, `ai-screening undo`) ask for confirmation
  only when both stdin and stdout are terminals; scripts and agents pass
  `--yes` or simply run non-interactively. An operation can name a `check` in the registry, called first
  with the same values: its `message` is shown, and the CLI asks when the operation is destructive or the check
  says `confirm`. `ai-screening undo` shows `undo-preview`; `ai-screening start`, `rerun` and the composite `run`
  ask `impact` and stop to ask only when the run would rewrite the reviewer's decisions.
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
parsifal article set-status --review $R --all-matching --match-status U --match-q "survey" --status R  # every match
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
| `parsifal_ai_screening_run(review_id, reviewer_id, run_id=None, step_size=64, max_seconds=240, <start fields>)` | Exclude with AI (or Include with AI, `phase="inclusion"`, or Screen with AI, `phase="screen"`) in one call; what is left out takes the last run's settings (`defaults=true`: Parsifal's): starts a run as `reviewer_id` (or continues `run_id`) and steps until it ends or the time budget passes; then `message` says to call again with `run_id`. Uses the Jev key of the token's user, who can only screen as itself unless it is the main author. |

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
