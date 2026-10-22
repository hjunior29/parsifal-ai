from django.test import Client

from parsifal.api.tests.base import API, ApiTestCase
from parsifal.apps.accounts.models import ApiToken
from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.tests.factories import ArticleFactory


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

        with self.subTest(msg="an active token cannot be deleted"):
            self.assertEqual(409, self.api("delete", f"/tokens/{body['id']}").status_code)
            self.assertTrue(ApiToken.objects.filter(pk=body["id"]).exists())

        with self.subTest(msg="revoke"):
            self.assertEqual(204, self.api("post", f"/tokens/{body['id']}/revoke").status_code)
            self.assertIsNotNone(ApiToken.objects.get(pk=body["id"]).revoked_at)

        with self.subTest(msg="cannot revoke or delete someone else's token"):
            other = self.co_author.api_tokens.get()
            self.assertEqual(404, self.api("post", f"/tokens/{other.pk}/revoke").status_code)
            self.assertEqual(404, self.api("delete", f"/tokens/{other.pk}").status_code)

        with self.subTest(msg="delete after revoking"):
            self.assertEqual(204, self.api("delete", f"/tokens/{body['id']}").status_code)
            self.assertFalse(ApiToken.objects.filter(pk=body["id"]).exists())
            self.assertEqual(404, self.api("delete", f"/tokens/{body['id']}").status_code)

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


class TestMeUpdate(ApiTestCase):
    def test_update_profile_fields(self):
        response = self.api("patch", "/me", {"first_name": " Ada ", "last_name": "Lovelace"})
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            ("Ada", "Lovelace", self.author.email),
            tuple(response.json()[k] for k in ("first_name", "last_name", "email")),
        )

        with self.subTest(msg="e-mail is validated and must be unique"):
            self.assertEqual(422, self.api("patch", "/me", {"email": "not-an-email"}).status_code)
            self.assertEqual(409, self.api("patch", "/me", {"email": self.co_author.email.upper()}).status_code)
            response = self.api("patch", "/me", {"email": "ada@example.org"})
            self.assertEqual("ada@example.org", response.json()["email"])

        with self.subTest(msg="too long names are rejected"):
            self.assertEqual(422, self.api("patch", "/me", {"first_name": "x" * 151}).status_code)

        self.author.refresh_from_db()
        self.assertEqual(
            ("Ada", "Lovelace", "ada@example.org"), (self.author.first_name, self.author.last_name, self.author.email)
        )


class TestLibraryAccess(ApiTestCase):
    PROXY = "ez99.periodicos.capes.gov.br"

    def test_set_show_remove_and_the_studies_access_url(self):
        article = ArticleFactory(review=self.review, source=self.source, doi="10.1109/X.1", url="")
        article_path = self.review_path(f"/articles/{article.pk}")
        self.assertEqual(
            {"configured": False, "proxy": None, "label": None, "updated_at": None},
            self.api("get", "/integrations/library-access").json(),
        )
        self.assertIsNone(self.api("get", article_path).json()["access_url"])

        address = f"https://ieeexplore-ieee-org.{self.PROXY}/document/1234567"
        response = self.api("put", "/integrations/library-access", {"address": address})
        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual(
            (True, self.PROXY, "Via CAPES"), tuple(response.json()[k] for k in ("configured", "proxy", "label"))
        )
        expected = f"https://doi-org.{self.PROXY}/10.1109/X.1"
        self.assertEqual(expected, self.api("get", article_path).json()["access_url"])
        listed = self.api("get", self.review_path("/articles")).json()["items"]
        self.assertEqual([expected], [item["access_url"] for item in listed])
        # Each user's own: a co-author without one gets none.
        co_author = self.client_for(self.co_author)
        self.assertIsNone(self.api("get", article_path, client=co_author).json()["access_url"])

        response = self.api("put", "/integrations/library-access", {"address": "https://www.periodicos.capes.gov.br"})
        self.assertEqual(422, response.status_code)
        self.assertIn("the CAPES portal itself", response.content.decode())

        self.assertEqual(204, self.api("delete", "/integrations/library-access").status_code)
        self.assertFalse(self.api("get", "/integrations/library-access").json()["configured"])
        self.assertIsNone(self.api("get", article_path).json()["access_url"])


class TestStudyColumns(ApiTestCase):
    def test_the_columns_of_the_study_list(self):
        me = self.api("get", "/me").json()
        self.assertEqual("star", me["study_columns"][0])
        response = self.api("patch", "/me", {"study_columns": ["title", "status"]})
        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual(["title", "status"], response.json()["study_columns"])
        self.assertEqual(422, self.api("patch", "/me", {"study_columns": ["nope"]}).status_code)
        self.assertEqual(["title", "status"], self.api("get", "/me").json()["study_columns"])
