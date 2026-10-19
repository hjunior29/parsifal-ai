"""
MCP server exposing a Parsifal instance to agents. Tools are generated from the same operation registry as the
CLI (``parsifal_<operationId>``), plus a few composite tools that save round-trips (screening batches, the
protocol as Markdown, running an Exclude with AI screening to its end).

Run ``parsifal-mcp`` (stdio, the default for Claude Code / Codex) or ``parsifal-mcp --transport http --port 8765``.
Configuration comes from PARSIFAL_URL / PARSIFAL_TOKEN (or a profile in the config file), exactly like the CLI.
"""

import argparse
import inspect
import json
from importlib import resources
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from parsifal_cli import __version__, config, screening
from parsifal_cli.client import ApiClient, ApiError, ConnectionFailed
from parsifal_cli.operations import BOOL, BY_ID, FILE, FLOAT, INT, LIST_INT, LIST_STR, OPERATIONS, PATH, TEXT

TOOL_PREFIX = "parsifal_"

PYTHON_TYPES = {INT: int, FLOAT: float, BOOL: bool, LIST_INT: list[int], LIST_STR: list[str], TEXT: str}

INSTRUCTIONS = (
    "Parsifal manages systematic literature reviews (Kitchenham & Charters) and systematic mapping studies. "
    "Start with parsifal_reviews_list and parsifal_reviews_overview to see what exists; call "
    "parsifal_workflow_guide for the step-by-step process. Tools mirror the JSON API one to one; "
    "`review_id` accepts a numeric id or author/slug. Decisions you record (selection status, quality answers, "
    "extracted values) are attributed to the token's user, so keep the human author informed."
)


def dumps(data):
    return json.dumps(data, ensure_ascii=False, default=str)


class ToolContext:
    """Creates API clients for tool calls; tests inject a mock transport."""

    def __init__(self, settings=None, transport=None):
        self.settings = settings
        self.transport = transport

    def client(self):
        return ApiClient(self.settings or config.resolve(), transport=self.transport)


def _description(operation):
    lines = [operation.summary, f"HTTP {operation.method} {operation.path}."]
    details = []
    for param in operation.params:
        if param.help:
            details.append(f"{param.name}: {param.help}")
    if details:
        lines.append("Parameters — " + " ".join(details))
    if operation.paginated:
        lines.append("Paginated: limit/offset (or all=true to fetch every page).")
    if operation.download:
        lines.append("Saves the downloaded file to output_path and returns its location.")
    return " ".join(lines)


def _run(context, operation, values, *, all_pages=False, limit=None, offset=None, output_path=None):
    client = context.client()
    try:
        result = client.call(operation, values, all_pages=all_pages, limit=limit, offset=offset)
    except (ApiError, ConnectionFailed) as error:
        raise ToolError(str(error)) from error
    except OSError as error:
        raise ToolError(str(error)) from error
    finally:
        client.close()
    if operation.download:
        if not output_path:
            raise ToolError("output_path is required for downloads.")
        Path(output_path).write_bytes(result.content)
        return dumps({"saved": str(output_path), "bytes": len(result.content)})
    return dumps(result)


def make_tool(operation, context):
    """Build a function whose signature matches the operation's parameters."""

    def tool(**kwargs):
        values = {}
        for param in operation.params:
            value = kwargs.get(param.name)
            if param.kind == FILE and value is not None:
                value = str(value)
            values[param.name] = value
        return _run(
            context,
            operation,
            values,
            all_pages=bool(kwargs.get("all", False)),
            limit=kwargs.get("limit"),
            offset=kwargs.get("offset"),
            output_path=kwargs.get("output_path"),
        )

    parameters, annotations = [], {}

    def add(name, python_type, required, default=None):
        annotation = python_type if required else python_type | None
        parameters.append(
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                default=inspect.Parameter.empty if required else default,
                annotation=annotation,
            )
        )
        annotations[name] = annotation

    for param in operation.params:
        python_type = PYTHON_TYPES.get(param.type, str)
        if param.kind == PATH and param.name == "review_id":
            python_type = int | str  # id or author/slug; agents often send the id as a number
        if param.kind == FILE:
            python_type = str
        add(param.name, python_type, param.required)
    if operation.paginated:
        add("limit", int, False)
        add("offset", int, False)
        add("all", bool, False, False)
    if operation.download:
        add("output_path", str, True)

    annotations["return"] = str
    tool.__signature__ = inspect.Signature(parameters, return_annotation=str)
    tool.__annotations__ = annotations
    tool.__name__ = TOOL_PREFIX + operation.id
    tool.__doc__ = _description(operation)
    return tool


# ---------------------------------------------------------------------------------------------------------------------
# Composite tools
# ---------------------------------------------------------------------------------------------------------------------

SCREENING_FIELDS = (
    "id",
    "bibtex_key",
    "title",
    "author",
    "year",
    "journal",
    "abstract",
    "keywords",
    "author_keywords",
    "doi",
    "source_id",
)


def screen_batch(context, review_id, limit=20, offset=0, status="U"):
    """Unclassified articles with the fields needed to screen them, plus the review's selection criteria."""
    client = context.client()
    try:
        rid = client.resolve_review(review_id)
        page = client.request(
            "GET", f"/reviews/{rid}/articles", params={"status": status, "limit": limit, "offset": offset}
        ).json()
        criteria = client.request("GET", f"/reviews/{rid}/criteria").json()
    except (ApiError, ConnectionFailed) as error:
        raise ToolError(str(error)) from error
    finally:
        client.close()
    return {
        "review_id": rid,
        "status": status,
        "count": page["count"],
        "offset": offset,
        "limit": limit,
        "criteria": criteria,
        "articles": [{key: article.get(key) for key in SCREENING_FIELDS} for article in page["items"]],
    }


def protocol_markdown(context, review_id):
    """The review protocol rendered as Markdown — handy as context for an agent."""
    client = context.client()
    try:
        rid = client.resolve_review(review_id)
        get = lambda suffix: client.request("GET", f"/reviews/{rid}{suffix}").json()  # noqa: E731
        review = get("")
        questions = get("/questions")
        keywords = get("/keywords")
        search_string = get("/search-string")["search_string"]
        sources = get("/sources")
        criteria = get("/criteria")
        quality_questions = get("/quality/questions")
        quality_answers = get("/quality/answers")
        fields = get("/extraction/fields")
    except (ApiError, ConnectionFailed) as error:
        raise ToolError(str(error)) from error
    finally:
        client.close()

    lines = [f"# {review['title']}", "", review.get("description", ""), ""]
    lines += ["## Objective", "", review.get("objective") or "_not defined_", ""]
    lines += ["## PICOC", ""]
    for key in ("population", "intervention", "comparison", "outcome", "context"):
        lines.append(f"- **{key.capitalize()}**: {review.get(key) or '_—_'}")
    lines += ["", "## Research questions", ""]
    lines += [f"{i}. {q['question']}" for i, q in enumerate(questions, 1)] or ["_none_"]
    lines += ["", "## Keywords and synonyms", ""]
    lines += [
        f"- {k['description']} ({k['related_to'] or '-'}): {', '.join(k['synonyms']) or '—'}" for k in keywords
    ] or ["_none_"]
    lines += ["", "## Search string", "", "```", search_string or "", "```", ""]
    lines += ["## Sources", ""] + ([f"- {s['name']} ({s['url']}) [id {s['id']}]" for s in sources] or ["_none_"])
    lines += ["", "## Selection criteria", ""]
    lines += [f"- [{c['criteria_type']}] {c['description']} (id {c['id']})" for c in criteria] or ["_none_"]
    lines += ["", "## Quality assessment", ""]
    lines += [f"- Q{q['id']}: {q['description']}" for q in quality_questions] or ["_no checklist_"]
    lines += [f"- answer {a['id']}: {a['description']} = {a['weight']}" for a in quality_answers]
    lines += [f"- cutoff: {review.get('quality_assessment_cutoff_score')}", ""]
    lines += ["## Data extraction form", ""]
    for field in fields:
        options = ", ".join(f"{lk['value']} (id {lk['id']})" for lk in field["lookup_values"])
        lines.append(
            f"- {field['description']} [{field['field_type']}] (id {field['id']}){': ' + options if options else ''}"
        )
    if not fields:
        lines.append("_none_")
    return "\n".join(lines) + "\n"


def workflow_guide():
    return resources.files("parsifal_cli").joinpath("data/workflow.md").read_text(encoding="utf-8")


SCREENING_RUN_DESCRIPTION = (
    "Exclude with AI (phase 1 of study selection, phase='exclusion', the default) or Include with AI (phase 2, "
    "phase='inclusion'), in one call: starts a run (or continues run_id) and screens with Jev until the run ends or "
    "max_seconds pass. reviewer_id is the member of the review the decisions are recorded as (only the main author "
    "may name someone else; see parsifal_ai_screening_setup). A run sends the studies with the given statuses (U, R, "
    "A, D; default R and U for exclusion, A and U for inclusion) and rewrites the reviewer's decisions on them. "
    "Exclusion: 'rejected' with the criterion when the probability that some exclusion criterion applies reaches the "
    "threshold, else 'unclassified'. Inclusion: one yes/no question per inclusion criterion; 'accepted' when the "
    "probability that every criterion is met reaches accept_threshold, 'rejected' when the probability that one is "
    "not met reaches reject_threshold, else 'unclassified' (inclusion runs refuse threshold). Only "
    "unclassified studies and those this reviewer classified change status, so two reviewers can screen the same "
    "studies and be compared (parsifal_decisions_agreement). "
    "Uses the Jev API key of the token's user (parsifal_jev_integration_set). Start fields left out take the "
    "review's values. If the result says it is still running, call again with run_id."
)


def screening_run(
    tool_context, review_id, *, run_id=None, step_size=screening.DEFAULT_STEP_SIZE, max_seconds=240, **start
):
    client = tool_context.client()
    try:
        run = screening.drive(
            client,
            review_id,
            run_id=run_id,
            start={name: value for name, value in start.items() if value is not None},
            step_size=step_size,
            max_seconds=max_seconds,
        )
    except (ApiError, ConnectionFailed) as error:
        raise ToolError(str(error)) from error
    finally:
        client.close()
    run.pop("parameters", None)
    if screening.interrupted(run):
        run["message"] = (
            f"Interrupted: {run['error']} The run keeps the studies left ({screening.progress_line(run)}); once the "
            f"problem is solved, call parsifal_ai_screening_run again with run_id={run['id']}."
        )
    elif run["status"] == "running":
        run["message"] = (
            f"Time budget reached ({screening.progress_line(run)}). Call parsifal_ai_screening_run again with "
            f"run_id={run['id']} to continue."
        )
    else:
        run["message"] = f"Run {run['status']}: {screening.progress_line(run)}."
    return run


def make_screening_run_tool(tool_context):
    """The composite tool, with the start parameters of the registry plus run_id, step_size and max_seconds."""

    def tool(**kwargs):  # kwargs may include "context", the PICOC field
        return dumps(screening_run(tool_context, **kwargs))

    parameters = [
        inspect.Parameter("review_id", inspect.Parameter.KEYWORD_ONLY, annotation=int | str),
        inspect.Parameter("run_id", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=int | None),
        inspect.Parameter(
            "step_size", inspect.Parameter.KEYWORD_ONLY, default=screening.DEFAULT_STEP_SIZE, annotation=int
        ),
        inspect.Parameter("max_seconds", inspect.Parameter.KEYWORD_ONLY, default=240, annotation=int),
    ]
    for param in screening.START_PARAMS:
        python_type = PYTHON_TYPES.get(param.type, str)
        parameters.append(
            inspect.Parameter(param.name, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=python_type | None)
        )
    tool.__signature__ = inspect.Signature(parameters, return_annotation=str)
    tool.__annotations__ = {**{p.name: p.annotation for p in parameters}, "return": str}
    tool.__name__ = TOOL_PREFIX + "ai_screening_run"
    tool.__doc__ = SCREENING_RUN_DESCRIPTION
    return tool


def build_server(settings=None, transport=None, host="127.0.0.1", port=8765):
    context = ToolContext(settings, transport)
    server = FastMCP("parsifal", instructions=INSTRUCTIONS, host=host, port=port)

    for operation in OPERATIONS:
        server.add_tool(
            make_tool(operation, context),
            name=TOOL_PREFIX + operation.id,
            description=_description(operation),
            annotations=ToolAnnotations(
                title=operation.cli_name,
                readOnlyHint=operation.method == "GET",
                destructiveHint=operation.destructive,
                idempotentHint=operation.method in ("GET", "PUT", "DELETE"),
                openWorldHint=False,
            ),
        )

    @server.tool(
        name=TOOL_PREFIX + "articles_screen_batch",
        description=(
            "A page of articles to screen (default: unclassified) with title, abstract and keywords, together "
            "with the review's inclusion/exclusion criteria. Then record decisions with parsifal_articles_set_status."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    def articles_screen_batch(review_id: int | str, limit: int = 20, offset: int = 0, status: str = "U") -> str:
        return dumps(screen_batch(context, review_id, limit, offset, status))

    @server.tool(
        name=TOOL_PREFIX + "review_protocol",
        description="The complete protocol of a review (objective, PICOC, questions, keywords, search string, "
        "sources, criteria, quality checklist, extraction form) as Markdown.",
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    def review_protocol(review_id: int | str) -> str:
        return protocol_markdown(context, review_id)

    @server.tool(
        name=TOOL_PREFIX + "workflow_guide",
        description="How to run a systematic review with Parsifal, step by step (planning, conducting, reporting).",
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    def workflow_guide_tool() -> str:
        return workflow_guide()

    server.add_tool(
        make_screening_run_tool(context),
        name=TOOL_PREFIX + "ai_screening_run",
        description=SCREENING_RUN_DESCRIPTION,
        annotations=ToolAnnotations(
            title="ai-screening run", readOnlyHint=False, destructiveHint=False, openWorldHint=True
        ),
    )

    @server.resource("parsifal://reviews/{review_id}/protocol", mime_type="text/markdown")
    def protocol_resource(review_id: str) -> str:
        return protocol_markdown(context, review_id)

    return server


def main(argv=None):
    parser = argparse.ArgumentParser(prog="parsifal-mcp", description="MCP server for a Parsifal instance.")
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--url", help="Parsifal server URL (default: PARSIFAL_URL / profile).")
    parser.add_argument("--token", help="API token (default: PARSIFAL_TOKEN / profile).")
    parser.add_argument("--profile", help="Profile from the config file.")
    parser.add_argument("--version", action="version", version=f"parsifal-mcp {__version__}")
    args = parser.parse_args(argv)

    settings = config.resolve(args.url, args.token, args.profile)
    server = build_server(settings, host=args.host, port=args.port)
    server.run(transport="streamable-http" if args.transport == "http" else "stdio")


COMPOSITE_TOOLS = (
    TOOL_PREFIX + "ai_screening_run",
    TOOL_PREFIX + "articles_screen_batch",
    TOOL_PREFIX + "review_protocol",
    TOOL_PREFIX + "workflow_guide",
)

__all__ = ["build_server", "main", "BY_ID", "COMPOSITE_TOOLS", "TOOL_PREFIX"]

if __name__ == "__main__":  # pragma: no cover
    main()
