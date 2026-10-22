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
