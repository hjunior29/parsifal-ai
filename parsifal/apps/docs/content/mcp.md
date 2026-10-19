# MCP server

`parsifal-mcp` exposes this instance to agents through the
[Model Context Protocol](https://modelcontextprotocol.io/): one tool per API
operation (`parsifal_<operationId>`, for example `parsifal_articles_set_status`)
plus a few composite tools that save round-trips.

## Install and connect

```bash
pip install -e "clients/parsifal-cli[mcp]"
export PARSIFAL_URL=http://localhost:8000 PARSIFAL_TOKEN=pfl_...

# Claude Code (stdio)
claude mcp add parsifal -e PARSIFAL_URL=$PARSIFAL_URL -e PARSIFAL_TOKEN=$PARSIFAL_TOKEN -- parsifal-mcp

# Other stdio clients (Codex, Cursor, ...): command "parsifal-mcp" with the two environment variables.
# Remote agents: streamable HTTP
parsifal-mcp --transport http --host 0.0.0.0 --port 8765    # http://host:8765/mcp
```

`parsifal-mcp --url … --token … --profile …` override the environment, exactly
like the CLI. The server only talks to the API; it never touches the database.

## Tools

| Tool | Purpose |
|------|---------|
| `parsifal_reviews_list`, `parsifal_reviews_overview` | Find a review and see what exists / what is missing. |
| `parsifal_review_protocol` | The whole protocol as Markdown (also the resource `parsifal://reviews/{id}/protocol`). |
| `parsifal_articles_screen_batch` | A page of articles to screen (title, abstract, keywords) **with** the review's inclusion/exclusion criteria. |
| `parsifal_articles_set_status`, `parsifal_decisions_record` | Record selection decisions — consolidated, or as the agent's own independent decision. |
| `parsifal_article_quality_assess`, `parsifal_article_extraction_set`, `parsifal_article_classification_set` | Quality answers, extracted values, classification. |
| `parsifal_workflow_guide` | The planning → conducting → reporting guide. |
| `parsifal_ai_screening_run` | Exclude with AI in one call: Jev rejects the studies that clearly meet an exclusion criterion (continue with `run_id` if the time budget runs out). |
| `parsifal_export_*` | Save CSV/XLSX/JSON/DOCX files (`output_path`). |

Tool annotations tell the client which tools are read-only, idempotent or
destructive, so it can ask you before deleting anything. `review_id` accepts a
numeric id or `author/slug`; lists are JSON arrays.

## Suggested first prompt

> Use the parsifal tools. Call `parsifal_workflow_guide` once, then
> `parsifal_reviews_overview` for review `alice/llm-assisted-slrs` and tell me
> what is missing in the protocol before we start screening.

See [Working with AI agents](/docs/agents/) for the recommended division of
work between the agent and the human reviewer.
