import json

import httpx
import pytest
from typer.testing import CliRunner

from parsifal_cli import cli


class FakeApi:
    """Records requests and answers from a dict of (METHOD, path) → (status, body)."""

    def __init__(self):
        self.requests = []
        self.routes = {}
        self.sequences = {}

    def route(self, method, path, status=200, body=None):
        self.routes[(method, path)] = (status, body)

    def route_many(self, method, path, *bodies, status=200):
        """Answer successive requests with successive bodies (the last one repeats)."""
        self.sequences[(method, path)] = [(status, body) for body in bodies]

    def handler(self, request):
        self.requests.append(request)
        key = (request.method, request.url.path)
        if key in self.sequences:
            queue = self.sequences[key]
            self.routes[key] = queue.pop(0) if len(queue) > 1 else queue[0]
        if key not in self.routes:
            return httpx.Response(404, json={"detail": f"no route {key}", "code": "not_found"})
        status, body = self.routes[key]
        if body is None:
            return httpx.Response(status)
        if isinstance(body, bytes):
            return httpx.Response(status, content=body, headers={"Content-Disposition": 'attachment; filename="x"'})
        return httpx.Response(status, json=body)

    @property
    def transport(self):
        return httpx.MockTransport(self.handler)

    def last_json(self):
        return json.loads(self.requests[-1].content or b"null")


@pytest.fixture
def fake_api(monkeypatch, tmp_path):
    api = FakeApi()
    monkeypatch.setattr(cli.state, "transport", api.transport)
    monkeypatch.setenv("PARSIFAL_URL", "http://testserver")
    monkeypatch.setenv("PARSIFAL_TOKEN", "pfl_test_token_value_1234567890")
    monkeypatch.setenv("PARSIFAL_CONFIG", str(tmp_path / "config.toml"))
    return api


@pytest.fixture
def runner():
    return CliRunner()


def invoke(runner, args, **kwargs):
    return runner.invoke(cli.app, ["--json", *args], **kwargs)
