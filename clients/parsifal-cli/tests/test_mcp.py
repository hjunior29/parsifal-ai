import asyncio
import json

import httpx
import pytest

from parsifal_cli.config import Settings
from parsifal_cli.operations import OPERATIONS
from parsifal_mcp import server as mcp_server
from tests.conftest import FakeApi


@pytest.fixture
def fake_api():
    return FakeApi()


@pytest.fixture
def server(fake_api):
    settings = Settings(url="http://testserver", token="pfl_test_token_value_1234567890")
    return mcp_server.build_server(settings, transport=fake_api.transport)


def run(coro):
    return asyncio.run(coro)


def text_of(result):
    """call_tool returns content blocks (optionally with structured output); extract the text."""
    blocks = result[0] if isinstance(result, tuple) else result
    return "".join(getattr(block, "text", "") for block in blocks)


def test_one_tool_per_operation_plus_composites(server):
    tools = run(server.list_tools())
    names = {tool.name for tool in tools}
    expected = {mcp_server.TOOL_PREFIX + op.id for op in OPERATIONS} | set(mcp_server.COMPOSITE_TOOLS)
    assert names == expected


def test_tool_schemas_reflect_registry(server):
    tools = {tool.name: tool for tool in run(server.list_tools())}
    set_status = tools["parsifal_articles_set_status"]
    schema = set_status.inputSchema
    assert set(schema["required"]) == {"review_id", "ids", "status"}
    assert schema["properties"]["ids"]["type"] == "array"
    assert set_status.annotations.destructiveHint is False
    assert tools["parsifal_reviews_delete"].annotations.destructiveHint is True
    assert tools["parsifal_reviews_get"].annotations.readOnlyHint is True
    export = tools["parsifal_export_report"].inputSchema
    assert "output_path" in export["required"]
    listing = tools["parsifal_articles_list"].inputSchema["properties"]
    assert {"limit", "offset", "all"} <= set(listing)


def test_call_simple_tool(server, fake_api):
    fake_api.route("GET", "/api/v1/me", 200, {"username": "alice"})
    result = run(server.call_tool("parsifal_me", {}))
    assert json.loads(text_of(result))["username"] == "alice"
    assert fake_api.requests[0].headers["Authorization"].startswith("Bearer pfl_test")


def test_call_tool_with_body_and_review_reference(server, fake_api):
    fake_api.route("GET", "/api/v1/reviews", 200, {"count": 1, "items": [{"id": 5}]})
    fake_api.route("POST", "/api/v1/reviews/5/articles/status", 200, {"count": 2})
    result = run(
        server.call_tool(
            "parsifal_articles_set_status", {"review_id": "alice/slr", "ids": [1, 2], "status": "A", "comments": "ok"}
        )
    )
    assert json.loads(text_of(result)) == {"count": 2}
    assert json.loads(fake_api.requests[-1].content) == {"ids": [1, 2], "status": "A", "comments": "ok"}


def test_api_error_becomes_tool_error(server, fake_api):
    fake_api.route("GET", "/api/v1/reviews/9", 404, {"detail": "Review 9 not found.", "code": "not_found"})
    with pytest.raises(Exception) as excinfo:
        run(server.call_tool("parsifal_reviews_get", {"review_id": "9"}))
    assert "Review 9 not found." in str(excinfo.value)


def test_download_tool_saves_file(server, fake_api, tmp_path):
    fake_api.route("GET", "/api/v1/reviews/5/export/report.docx", 200, b"PK\x03\x04docx")
    out = tmp_path / "report.docx"
    result = run(server.call_tool("parsifal_export_report", {"review_id": "5", "output_path": str(out)}))
    assert json.loads(text_of(result)) == {"saved": str(out), "bytes": 8}
    assert out.read_bytes().startswith(b"PK")


def test_screen_batch_and_protocol(server, fake_api):
    fake_api.route(
        "GET",
        "/api/v1/reviews/5/articles",
        200,
        {
            "count": 1,
            "items": [{"id": 1, "title": "T", "abstract": "A", "keywords": "k", "status": "U", "extra": "x"}],
        },
    )
    fake_api.route(
        "GET", "/api/v1/reviews/5/criteria", 200, [{"id": 3, "description": "Relevant", "criteria_type": "I"}]
    )
    batch = json.loads(text_of(run(server.call_tool("parsifal_articles_screen_batch", {"review_id": "5"}))))
    assert batch["count"] == 1 and batch["criteria"][0]["id"] == 3
    assert "extra" not in batch["articles"][0] and batch["articles"][0]["abstract"] == "A"
    assert fake_api.requests[0].url.params["status"] == "U"

    fake_api.route(
        "GET",
        "/api/v1/reviews/5",
        200,
        {
            "title": "My SLR",
            "description": "d",
            "objective": "o",
            "population": "p",
            "quality_assessment_cutoff_score": 1.0,
        },
    )
    fake_api.route("GET", "/api/v1/reviews/5/questions", 200, [{"question": "RQ1?"}])
    fake_api.route(
        "GET", "/api/v1/reviews/5/keywords", 200, [{"description": "LLM", "related_to": "I", "synonyms": ["GPT"]}]
    )
    fake_api.route("GET", "/api/v1/reviews/5/search-string", 200, {"search_string": "a AND b"})
    fake_api.route("GET", "/api/v1/reviews/5/sources", 200, [{"id": 1, "name": "Scopus", "url": "http://s"}])
    fake_api.route("GET", "/api/v1/reviews/5/quality/questions", 200, [])
    fake_api.route("GET", "/api/v1/reviews/5/quality/answers", 200, [])
    fake_api.route(
        "GET",
        "/api/v1/reviews/5/extraction/fields",
        200,
        [{"id": 7, "description": "Method", "field_type": "O", "lookup_values": [{"id": 8, "value": "Survey"}]}],
    )
    markdown = text_of(run(server.call_tool("parsifal_review_protocol", {"review_id": "5"})))
    for fragment in (
        "# My SLR",
        "1. RQ1?",
        "- LLM (I): GPT",
        "a AND b",
        "Scopus",
        "[I] Relevant",
        "Method [O] (id 7): Survey (id 8)",
    ):
        assert fragment in markdown


def test_workflow_guide_tool(server):
    text = text_of(run(server.call_tool("parsifal_workflow_guide", {})))
    assert "Planning" in text and "Conducting" in text


def test_main_help(capsys):
    with pytest.raises(SystemExit) as excinfo:
        mcp_server.main(["--help"])
    assert excinfo.value.code == 0
    assert "--transport" in capsys.readouterr().out


def test_connection_error_is_reported(fake_api):
    def boom(request):
        raise httpx.ConnectError("refused")

    settings = Settings(url="http://localhost:1", token="pfl_x")
    server = mcp_server.build_server(settings, transport=httpx.MockTransport(boom))
    with pytest.raises(Exception) as excinfo:
        run(server.call_tool("parsifal_me", {}))
    assert "Could not reach" in str(excinfo.value)


def test_review_reference_accepts_a_number_or_a_string(server, fake_api):
    fake_api.route("GET", "/api/v1/reviews/7/overview", 200, {"id": 7})
    for reference in (7, "7"):
        result = run(server.call_tool("parsifal_reviews_overview", {"review_id": reference}))
        assert json.loads(text_of(result))["id"] == 7


def test_ai_screening_run_tool(server, fake_api):
    from tests.test_screening import RUN, bodies, routes

    routes(fake_api)
    tools = {tool.name: tool for tool in run(server.list_tools())}
    schema = tools["parsifal_ai_screening_run"].inputSchema
    assert schema["required"] == ["review_id"]
    assert {"run_id", "step_size", "max_seconds", "threshold", "guidance", "objective", "rescreen"} <= set(
        schema["properties"]
    )

    result = json.loads(
        text_of(run(server.call_tool("parsifal_ai_screening_run", {"review_id": 7, "threshold": 0.95})))
    )
    assert (result["id"], result["status"], result["excluded"]) == (RUN["id"], "finished", 1)
    assert result["message"] == "Run finished: 2/2 screened · 1 rejected · 1 passed · 0 errors."
    assert "parameters" not in result
    assert bodies(fake_api, "POST", "/api/v1/reviews/7/ai-screening/runs") == [{"threshold": 0.95}]


def test_ai_screening_run_tool_reports_still_running(server, fake_api, monkeypatch):
    from parsifal_cli import screening
    from tests.test_screening import routes

    routes(fake_api)
    ticks = iter([0, 0, 1000])
    drive = screening.drive
    monkeypatch.setattr(screening, "drive", lambda *args, **kwargs: drive(*args, clock=lambda: next(ticks), **kwargs))
    result = json.loads(
        text_of(run(server.call_tool("parsifal_ai_screening_run", {"review_id": 7, "run_id": 3, "max_seconds": 60})))
    )
    assert result["status"] == "running"
    assert "run_id=3 to continue" in result["message"]
