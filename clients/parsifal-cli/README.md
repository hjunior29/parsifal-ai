# parsifal-cli

Command-line client (`parsifal`) and MCP server (`parsifal-mcp`) for a
[Parsifal](https://github.com/hjunior29/parsifal-ai) instance. Both are thin
clients of the JSON API (`/api/v1/`): every API operation is one CLI command
and one MCP tool, generated from a single registry.

```bash
pip install -e clients/parsifal-cli          # from the repository
export PARSIFAL_URL=http://localhost:8000
export PARSIFAL_TOKEN=pfl_...                # Settings → API tokens
parsifal me
parsifal review list
parsifal docs                                # the review workflow, for agents
```

See `doc/15-cli-and-mcp.md` in the repository for the full guide.
