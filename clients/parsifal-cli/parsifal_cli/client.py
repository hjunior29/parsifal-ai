"""HTTP client: executes registry operations against the API and normalises errors."""

import json
import re

import httpx

from parsifal_cli import __version__
from parsifal_cli.operations import BODY, FILE, FORM, PATH, QUERY

# Exit codes used by the CLI (documented in doc/15-cli-and-mcp.md)
EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_AUTH, EXIT_NOT_FOUND, EXIT_CONFLICT, EXIT_CONNECTION = 0, 1, 2, 3, 4, 5, 6

STATUS_EXIT_CODES = {401: EXIT_AUTH, 403: EXIT_AUTH, 404: EXIT_NOT_FOUND, 409: EXIT_CONFLICT, 422: EXIT_USAGE}


class ApiError(Exception):
    def __init__(self, status, detail, code=None, field=None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.code = code
        self.field = field

    @property
    def exit_code(self):
        return STATUS_EXIT_CODES.get(self.status, EXIT_ERROR)

    @classmethod
    def from_response(cls, response):
        try:
            body = response.json()
        except ValueError:
            body = {}
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, list):  # request-shape errors from the schema layer
            detail = "; ".join(f"{'.'.join(str(p) for p in e.get('loc', [])[1:])}: {e.get('msg')}" for e in detail)
        if not detail:
            detail = response.text.strip()[:300] or f"HTTP {response.status_code}"
        return cls(
            response.status_code,
            detail,
            body.get("code") if isinstance(body, dict) else None,
            body.get("field") if isinstance(body, dict) else None,
        )


class ConnectionFailed(Exception):
    exit_code = EXIT_CONNECTION


REVIEW_REF = re.compile(r"^(?P<author>[\w.@+-]+)/(?P<name>[\w-]+)$")


class ApiClient:
    def __init__(self, settings, transport=None, timeout=60.0):
        headers = {"User-Agent": f"parsifal-cli/{__version__}", "Accept": "application/json"}
        if settings.token:
            headers["Authorization"] = f"Bearer {settings.token}"
        self.settings = settings
        self._client = httpx.Client(base_url=settings.api_base, headers=headers, transport=transport, timeout=timeout)

    def close(self):
        self._client.close()

    def request(self, method, path, *, params=None, json_body=None, data=None, files=None):
        try:
            response = self._client.request(method, path, params=params, json=json_body, data=data, files=files)
        except httpx.HTTPError as error:
            raise ConnectionFailed(f"Could not reach {self.settings.api_base}: {error}") from error
        if response.status_code >= 400:
            raise ApiError.from_response(response)
        return response

    def resolve_review(self, ref):
        """Accept a review id or ``author/slug`` and return the id."""
        ref = str(ref).strip()
        if ref.isdigit():
            return int(ref)
        match = REVIEW_REF.match(ref)
        if not match:
            raise ApiError(422, f"Invalid review reference {ref!r}: use an id or author/slug.")
        response = self.request(
            "GET", "/reviews", params={"author": match["author"], "name": match["name"], "limit": 1}
        )
        items = response.json().get("items", [])
        if not items:
            raise ApiError(404, f"Review {ref!r} not found.")
        return items[0]["id"]

    def call(self, operation, values, *, all_pages=False, limit=None, offset=None):
        """
        Execute ``operation`` with ``values`` (a mapping param name → value). Returns parsed JSON, ``None`` for 204,
        or the raw ``httpx.Response`` for downloads.
        """
        path_values, query, body, form, files = {}, {}, {}, {}, {}
        for param in operation.params:
            value = values.get(param.name)
            if value is None or value == [] or value == ():
                continue
            if param.kind == PATH:
                if param.name == "review_id":
                    value = self.resolve_review(value)
                path_values[param.name] = value
            elif param.kind == QUERY:
                query[param.name] = value
            elif param.kind == BODY:
                body[param.name] = value
            elif param.kind == FORM:
                form[param.name] = str(value)
            elif param.kind == FILE:
                files[param.name] = open(value, "rb")  # noqa: SIM115 - closed by httpx after the request

        path = operation.path.format(**path_values)
        if operation.paginated:
            if limit is not None:
                query["limit"] = limit
            if offset is not None:
                query["offset"] = offset
            if all_pages:
                return self._all_pages(path, query)

        json_body = body if operation.body_mode == "json" else None
        try:
            response = self.request(
                operation.method, path, params=query, json_body=json_body, data=form or None, files=files or None
            )
        finally:
            for handle in files.values():
                handle.close()
        if operation.download:
            return response
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _all_pages(self, path, query):
        query = dict(query)
        query.setdefault("limit", 200)
        query["offset"] = 0
        items = []
        while True:
            page = self.request("GET", path, params=query).json()
            items.extend(page["items"])
            query["offset"] += query["limit"]
            if query["offset"] >= page["count"] or not page["items"]:
                return {"count": page["count"], "items": items}


BIBTEX_ENTRY = re.compile(r"@\w+\s*[{(]")


def read_text_argument(value):
    """``@path`` reads a file, ``-`` reads stdin; anything else is returned unchanged.

    BibTeX text also starts with ``@`` (``@article{...``): a value that opens a BibTeX entry is literal text, so
    inline BibTeX works as well as ``@refs.bib``.
    """
    import sys

    if value is None:
        return None
    if value == "-":
        return sys.stdin.read()
    if isinstance(value, str) and value.startswith("@") and len(value) > 1 and not BIBTEX_ENTRY.match(value):
        with open(value[1:], encoding="utf-8") as handle:
            return handle.read()
    return value


def dumps(data):
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)
