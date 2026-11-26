import json

from parsifal_cli import cli
from parsifal_cli.operations import OPERATIONS
from tests.conftest import invoke


def test_every_command_has_help(runner):
    for op in OPERATIONS:
        result = runner.invoke(cli.app, [*op.group, op.command, "--help"])
        assert result.exit_code == 0, (op.cli_name, result.output)
        assert op.summary.split(".")[0][:30] in result.output


def test_me_prints_json(runner, fake_api):
    fake_api.route("GET", "/api/v1/me", 200, {"username": "alice", "id": 1})
    result = invoke(runner, ["me"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["username"] == "alice"
    assert fake_api.requests[0].headers["Authorization"] == "Bearer pfl_test_token_value_1234567890"


def test_review_reference_is_resolved(runner, fake_api):
    fake_api.route("GET", "/api/v1/reviews", 200, {"count": 1, "items": [{"id": 42}]})
    fake_api.route("GET", "/api/v1/reviews/42/overview", 200, {"id": 42, "articles": {"total": 0}})
    result = invoke(runner, ["review", "overview", "--review", "alice/my-slr"])
    assert result.exit_code == 0, result.output
    lookup = fake_api.requests[0]
    assert lookup.url.params["author"] == "alice" and lookup.url.params["name"] == "my-slr"
    assert fake_api.requests[1].url.path == "/api/v1/reviews/42/overview"


def test_invalid_review_reference(runner, fake_api):
    result = invoke(runner, ["review", "get", "--review", "not a ref"])
    assert result.exit_code == 2
    assert "Invalid review reference" in result.output


def test_body_lists_and_text_from_file(runner, fake_api, tmp_path):
    bib = tmp_path / "x.bib"
    bib.write_text("@article{k, title={T}}")
    fake_api.route(
        "POST",
        "/api/v1/reviews/7/articles/import",
        201,
        {"imported": 1, "failed": 0, "warnings": [], "article_ids": [1]},
    )
    result = invoke(runner, ["article", "import", "--review", "7", "--source-id", "3", "--bibtex", f"@{bib}"])
    assert result.exit_code == 0, result.output
    assert fake_api.last_json() == {"source_id": 3, "bibtex": "@article{k, title={T}}"}

    fake_api.route("POST", "/api/v1/reviews/7/articles/status", 200, {"count": 2})
    result = invoke(runner, ["article", "set-status", "--review", "7", "--ids", "1", "--ids", "2", "--status", "A"])
    assert result.exit_code == 0, result.output
    assert fake_api.last_json() == {"ids": [1, 2], "status": "A"}


def test_date_of_search(runner, fake_api):
    fake_api.route(
        "POST",
        "/api/v1/reviews/7/articles/import",
        201,
        {"imported": 1, "failed": 0, "warnings": [], "article_ids": [1]},
    )
    result = invoke(
        runner,
        [
            "article",
            "import",
            "--review",
            "7",
            "--source-id",
            "3",
            "--bibtex",
            "@article{k}",
            "--searched-at",
            "2026-09-30",
        ],
    )
    assert result.exit_code == 0, result.output
    assert fake_api.last_json() == {"source_id": 3, "bibtex": "@article{k}", "searched_at": "2026-09-30"}

    fake_api.route("PATCH", "/api/v1/reviews/7/sources/3/search", 200, {"source_id": 3, "searched_at": None})
    result = invoke(runner, ["source", "document-search", "--review", "7", "--id", "3", "--searched-at", ""])
    assert result.exit_code == 0, result.output
    assert fake_api.last_json() == {"searched_at": ""}

    rows = [{"source_id": 3, "source": "Scopus", "imported": 1, "searched_at": "2026-09-30"}]
    fake_api.route("GET", "/api/v1/reviews/7/sources/imports", 200, rows)
    result = invoke(runner, ["source", "imports", "--review", "7"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == rows


def test_history(runner, fake_api):
    page = {"count": 1, "items": [{"id": 9, "summary": "Changed the protocol (Objective)", "via": "cli"}]}
    fake_api.route("GET", "/api/v1/reviews/7/history", 200, page)
    result = invoke(
        runner,
        ["history", "list", "--review", "7", "--area", "planning", "--since", "2026-11-01", "--amendments"],
    )
    assert result.exit_code == 0, result.output
    request = fake_api.requests[-1]
    assert dict(request.url.params) == {"area": "planning", "since": "2026-11-01", "amendments": "true"}
    assert request.headers["User-Agent"].startswith("parsifal-cli/")  # the History says "CLI"
    assert json.loads(result.output)["items"][0]["id"] == 9


def test_inline_bibtex_is_not_read_as_a_file(runner, fake_api, tmp_path):
    fake_api.route(
        "POST",
        "/api/v1/reviews/7/articles/import",
        201,
        {"imported": 1, "failed": 0, "warnings": [], "article_ids": [1]},
    )
    inline = "@article{k, title={T}}"
    result = invoke(runner, ["article", "import", "--review", "7", "--source-id", "3", "--bibtex", inline])
    assert result.exit_code == 0, result.output
    assert fake_api.last_json() == {"source_id": 3, "bibtex": inline}


def test_missing_text_file_is_a_clean_error(runner, fake_api, tmp_path):
    result = invoke(
        runner, ["article", "import", "--review", "7", "--source-id", "3", "--bibtex", f"@{tmp_path}/nope.bib"]
    )
    assert result.exit_code != 0
    assert "Cannot read --bibtex" in result.output
    assert "Traceback" not in result.output


def test_stdin_text(runner, fake_api):
    fake_api.route("PUT", "/api/v1/reviews/7/search-string", 200, {"search_string": "a AND b"})
    result = invoke(runner, ["search-string", "set", "--review", "7", "--search-string", "-"], input="a AND b")
    assert result.exit_code == 0, result.output
    assert fake_api.last_json() == {"search_string": "a AND b"}


def test_boolean_option(runner, fake_api):
    fake_api.route(
        "PUT",
        "/api/v1/reviews/7/articles/9/extraction/done",
        200,
        {"article_id": 9, "finished_data_extraction": False, "values": []},
    )
    result = invoke(runner, ["extraction", "done", "--review", "7", "--article", "9", "--no-done"])
    assert result.exit_code == 0, result.output
    assert fake_api.last_json() == {"done": False}


def test_extraction_with_its_evidence(runner, fake_api):
    body = {"article_id": 9, "finished_data_extraction": False, "values": []}
    fake_api.route("PUT", "/api/v1/reviews/7/articles/9/extraction", 200, body)
    fake_api.route("PUT", "/api/v1/reviews/7/articles/9/extraction/evidence", 200, body)
    result = invoke(
        runner,
        ["extraction", "set", "--review", "7", "--article", "9", "--field-id", "3", "--value", "Brazil"]
        + ["--evidence", "p. 3, Table 2"],
    )
    assert result.exit_code == 0, result.output
    assert fake_api.last_json() == {"field_id": 3, "value": "Brazil", "evidence": "p. 3, Table 2"}
    result = invoke(
        runner, ["extraction", "evidence", "--review", "7", "--article", "9", "--field-id", "3", "--evidence", "p. 4"]
    )
    assert result.exit_code == 0, result.output
    assert fake_api.last_json() == {"field_id": 3, "evidence": "p. 4"}


def test_threats(runner, fake_api):
    threat = {"id": 4, "title": "One reviewer", "category": "Theoretical validity"}
    fake_api.route("POST", "/api/v1/reviews/7/threats", 201, threat)
    fake_api.route("PATCH", "/api/v1/reviews/7/threats/4", 200, threat)
    result = invoke(
        runner,
        ["threat", "create", "--review", "7", "--title", "One reviewer", "--category", "Theoretical validity"],
    )
    assert result.exit_code == 0, result.output
    assert fake_api.last_json() == {"title": "One reviewer", "category": "Theoretical validity"}
    result = invoke(runner, ["threat", "update", "--review", "7", "--id", "4", "--mitigation", "A test set"])
    assert result.exit_code == 0, result.output
    assert fake_api.last_json() == {"mitigation": "A test set"}


def test_manuscript_version_upload(runner, fake_api, tmp_path):
    paper = tmp_path / "paper.pdf"
    paper.write_bytes(b"%PDF-1.4")
    fake_api.route("POST", "/api/v1/reviews/7/manuscripts/2/versions", 201, {"id": 5, "number": 3})
    result = invoke(
        runner,
        ["manuscript", "version", "upload", "--review", "7", "--manuscript", "2", "--file", str(paper)]
        + ["--notes", "Camera ready"],
    )
    assert result.exit_code == 0, result.output
    request = fake_api.requests[-1]
    assert b"Camera ready" in request.content
    assert b"%PDF-1.4" in request.content


def test_rapid_review(runner, fake_api):
    fake_api.route("PATCH", "/api/v1/reviews/7", 200, {"id": 7})
    fake_api.route("POST", "/api/v1/reviews/7/threats/draft", 200, [])
    result = invoke(
        runner,
        ["review", "update", "--review", "7", "--demand", "practitioners", "--started-on", "2026-11-02"]
        + ["--practical-problem", "Flaky tests."],
    )
    assert result.exit_code == 0, result.output
    assert fake_api.last_json() == {
        "demand": "practitioners",
        "started_on": "2026-11-02",
        "practical_problem": "Flaky tests.",
    }
    result = invoke(runner, ["threat", "draft", "--review", "7"])
    assert result.exit_code == 0, result.output


def test_code_prefixes(runner, fake_api):
    fake_api.route("PATCH", "/api/v1/reviews/7", 200, {"id": 7})
    result = invoke(
        runner,
        ["review", "update", "--review", "7", "--code-prefixes", "question=QP", "--code-prefixes", "inclusion=CI"],
    )
    assert result.exit_code == 0, result.output
    assert fake_api.last_json() == {"code_prefixes": ["question=QP", "inclusion=CI"]}


def test_pagination_all(runner, fake_api):
    pages = {
        0: {"count": 3, "items": [{"id": 1}, {"id": 2}]},
        2: {"count": 3, "items": [{"id": 3}]},
    }

    def handler(request):
        fake_api.requests.append(request)
        offset = int(request.url.params.get("offset", 0))
        import httpx

        return httpx.Response(200, json=pages[offset])

    import httpx

    cli.state.transport = httpx.MockTransport(handler)
    result = invoke(runner, ["article", "list", "--review", "7", "--all", "--limit", "2"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert [item["id"] for item in body["items"]] == [1, 2, 3]
    assert len(fake_api.requests) == 2


def test_multipart_upload(runner, fake_api, tmp_path):
    bib = tmp_path / "upload.bib"
    bib.write_bytes(b"@article{k, title={T}}")
    fake_api.route(
        "POST",
        "/api/v1/reviews/7/articles/import/file",
        201,
        {"imported": 1, "failed": 0, "warnings": [], "article_ids": [1]},
    )
    result = invoke(runner, ["article", "import-file", "--review", "7", "--source-id", "3", "--file", str(bib)])
    assert result.exit_code == 0, result.output
    request = fake_api.requests[-1]
    assert request.headers["Content-Type"].startswith("multipart/form-data")
    assert b'name="source_id"' in request.content and b"@article{k" in request.content


def test_download_to_file(runner, fake_api, tmp_path):
    fake_api.route("GET", "/api/v1/reviews/7/export/articles.csv", 200, b"bibtex_key,title\n")
    out = tmp_path / "a.csv"
    result = invoke(runner, ["export", "articles", "--review", "7", "--format", "csv", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_bytes() == b"bibtex_key,title\n"


def test_error_exit_codes(runner, fake_api):
    fake_api.route("GET", "/api/v1/reviews/1", 404, {"detail": "Review 1 not found.", "code": "not_found"})
    result = invoke(runner, ["review", "get", "--review", "1"])
    assert result.exit_code == 4
    assert "Review 1 not found." in result.output

    fake_api.route(
        "POST", "/api/v1/reviews", 422, {"detail": [{"loc": ["body", "payload", "title"], "msg": "Field required"}]}
    )
    result = invoke(runner, ["review", "create", "--title", "x"])
    assert result.exit_code == 2
    assert "title: Field required" in result.output

    fake_api.route("GET", "/api/v1/me", 401, {"detail": "Unauthorized"})
    assert invoke(runner, ["me"]).exit_code == 3


def test_connection_failure(runner, monkeypatch, tmp_path):
    import httpx

    def boom(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(cli.state, "transport", httpx.MockTransport(boom))
    monkeypatch.setenv("PARSIFAL_URL", "http://localhost:1")
    monkeypatch.setenv("PARSIFAL_CONFIG", str(tmp_path / "c.toml"))
    result = invoke(runner, ["me"])
    assert result.exit_code == 6
    assert "Could not reach" in result.output


def test_delete_requires_yes_only_on_tty(runner, fake_api):
    fake_api.route("DELETE", "/api/v1/reviews/7/questions/3", 204, None)
    # CliRunner is not a TTY, so no confirmation prompt is shown
    result = invoke(runner, ["question", "delete", "--review", "7", "--id", "3"])
    assert result.exit_code == 0, result.output
    assert fake_api.requests[-1].method == "DELETE"


def test_docs_and_version(runner):
    assert "Planning" in runner.invoke(cli.app, ["docs"]).output
    assert runner.invoke(cli.app, ["version"]).output.strip() == cli.__version__


def test_library_access_set_sends_the_address(runner, fake_api):
    address = "https://ieeexplore-ieee-org.ez99.periodicos.capes.gov.br/document/1234567"
    saved = {"configured": True, "proxy": "ez99.periodicos.capes.gov.br", "label": "Via CAPES", "updated_at": None}
    fake_api.route("PUT", "/api/v1/integrations/library-access", 200, saved)
    result = invoke(runner, ["integration", "library-access", "set", "--address", address])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["proxy"] == "ez99.periodicos.capes.gov.br"
    request = fake_api.requests[-1]
    assert json.loads(request.content) == {"address": address}
