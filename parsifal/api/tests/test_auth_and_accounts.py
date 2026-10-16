from django.test import Client

from parsifal.api.tests.base import API, ApiTestCase
from parsifal.apps.accounts.models import ApiToken
from parsifal.apps.authentication.tests.factories import UserFactory


class TestAuthentication(ApiTestCase):
    def test_missing_or_invalid_token(self):
        anonymous = Client()
        self.assertEqual(401, anonymous.get(f"{API}/me").status_code)
        bad = Client(headers={"Authorization": "Bearer pfl_not-a-real-token"})
        self.assertEqual(401, bad.get(f"{API}/me").status_code)

    def test_token_identifies_user_and_records_use(self):
        response = self.api("get", "/me")
        self.assertEqual(200, response.status_code)
        self.assertEqual(self.author.username, response.json()["username"])
        token = self.author.api_tokens.get()
        self.assertIsNotNone(token.last_used_at)

    def test_revoked_token_is_rejected(self):
        self.author.api_tokens.get().revoke()
        self.assertEqual(401, self.api("get", "/me").status_code)

    def test_inactive_user_is_rejected(self):
        self.author.is_active = False
        self.author.save()
        self.assertEqual(401, self.api("get", "/me").status_code)

    def test_session_authentication_works(self):
        session_client = Client()
        session_client.force_login(self.co_author)
        response = session_client.get(f"{API}/me")
        self.assertEqual(200, response.status_code)
        self.assertEqual(self.co_author.username, response.json()["username"])

    def test_openapi_schema_lists_unique_operation_ids(self):
        response = Client().get(f"{API}/openapi.json")
        self.assertEqual(200, response.status_code)
        operation_ids = [
            operation["operationId"] for methods in response.json()["paths"].values() for operation in methods.values()
        ]
        self.assertGreater(len(operation_ids), 70)
        self.assertEqual(len(operation_ids), len(set(operation_ids)))


class TestTokens(ApiTestCase):
    def test_list_create_revoke(self):
        response = self.api("post", "/tokens", {"name": "Claude Code"})
        self.assertEqual(201, response.status_code)
        body = response.json()
        self.assertTrue(body["key"].startswith("pfl_"))
        self.assertEqual(body["key"][:12], body["prefix"])

        with self.subTest(msg="new token authenticates"):
            self.assertEqual(
                200, Client(headers={"Authorization": f"Bearer {body['key']}"}).get(f"{API}/me").status_code
            )

        with self.subTest(msg="list shows two tokens, never the key"):
            tokens = self.api("get", "/tokens").json()
            self.assertEqual(2, len(tokens))
            self.assertNotIn("key", tokens[0])

        with self.subTest(msg="revoke"):
            self.assertEqual(204, self.api("delete", f"/tokens/{body['id']}").status_code)
            self.assertIsNotNone(ApiToken.objects.get(pk=body["id"]).revoked_at)

        with self.subTest(msg="cannot revoke someone else's token"):
            other = self.co_author.api_tokens.get()
            self.assertEqual(404, self.api("delete", f"/tokens/{other.pk}").status_code)

    def test_blank_name(self):
        self.assertEqual(422, self.api("post", "/tokens", {"name": "  "}).status_code)


class TestUsers(ApiTestCase):
    def test_admin_only(self):
        self.assertEqual(403, self.api("get", "/users").status_code)
        self.assertEqual(403, self.api("post", "/users", {"username": "x", "email": "x@example.com"}).status_code)

    def test_admin_creates_user(self):
        admin = self.client_for(self.admin)
        response = self.api(
            "post", "/users", {"username": "newbie", "email": "new@example.com", "password": "S3cret!!"}, client=admin
        )
        self.assertEqual(201, response.status_code)
        self.assertEqual("newbie", response.json()["username"])
        with self.subTest(msg="reserved or non-ascii usernames are rejected"):
            for name in ("admin", "docs", "joão"):
                response = self.api("post", "/users", {"username": name, "email": f"{name}@example.com"}, client=admin)
                self.assertEqual(422, response.status_code, name)
        with self.subTest(msg="duplicate username conflicts"):
            response = self.api("post", "/users", {"username": "NEWBIE", "email": "other@example.com"}, client=admin)
            self.assertEqual(409, response.status_code)
        with self.subTest(msg="list includes the new user"):
            usernames = [u["username"] for u in self.api("get", "/users", client=admin).json()]
            self.assertIn("newbie", usernames)
            UserFactory()  # unrelated user still listed
            self.assertGreater(len(self.api("get", "/users", client=admin).json()), len(usernames))
