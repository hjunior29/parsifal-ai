"""
The CLI/MCP operation registry (clients/parsifal-cli) must mirror the API exactly: same operationIds, methods
and paths. This test fails whenever an endpoint is added or renamed without updating the registry.
"""

import re

from django.test import SimpleTestCase

from parsifal.api.api import api

try:
    from parsifal_cli.operations import OPERATIONS
except ImportError:  # pragma: no cover - the client package is a dev dependency (requirements/tests.txt)
    OPERATIONS = None

CONVERTER = re.compile(r"\{(?:int|str|slug|uuid|path):")


class TestRegistryParity(SimpleTestCase):
    def setUp(self):
        if OPERATIONS is None:
            self.skipTest("parsifal-cli is not installed")

    def api_operations(self):
        schema = api.get_openapi_schema()
        found = {}
        for path, methods in schema["paths"].items():
            for method, operation in methods.items():
                found[operation["operationId"]] = (method.upper(), path.replace("/api/v1", "", 1))
        return found

    def test_every_api_operation_is_in_the_registry(self):
        expected = self.api_operations()
        registry = {op.id: (op.method, CONVERTER.sub("{", op.path)) for op in OPERATIONS}
        with self.subTest(msg="same operation ids"):
            self.assertEqual(set(expected), set(registry))
        for operation_id, (method, path) in expected.items():
            with self.subTest(operation=operation_id):
                self.assertEqual((method, path), registry[operation_id])

    def test_registry_params_match_schema(self):
        schema = api.get_openapi_schema()
        by_id = {op["operationId"]: op for methods in schema["paths"].values() for op in methods.values()}
        for operation in OPERATIONS:
            spec = by_id[operation.id]
            declared = {p["name"] for p in spec.get("parameters", []) if p["in"] in ("path", "query")}
            registered = {p.name for p in operation.params if p.kind in ("path", "query")}
            # pagination parameters are added by the CLI itself
            registered |= {"limit", "offset"} if operation.paginated else set()
            declared -= {"limit", "offset"}
            registered -= {"limit", "offset"}
            with self.subTest(operation=operation.id):
                self.assertEqual(declared, registered)
