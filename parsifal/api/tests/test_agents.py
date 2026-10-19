from parsifal.api.tests.base import API, ApiTestCase
from parsifal.apps.accounts.models import ApiToken
from parsifal.apps.reviews.models import Article, StudyDecision
from parsifal.apps.reviews.tests.factories import ArticleFactory


class TestAgentsApi(ApiTestCase):
    def create(self, name="Screening bot"):
        response = self.api("post", self.review_path("/agents"), {"name": name})
        self.assertEqual(201, response.status_code, response.content)
        return response.json()

    def test_create_list_and_token_is_shown_once(self):
        agent = self.create()
        self.assertEqual(("Screening bot", "agent-screening-bot"), (agent["name"], agent["username"]))
        self.assertTrue(agent["token"].startswith("pfl_"))
        listed = self.api("get", self.review_path("/agents")).json()
        self.assertEqual(1, len(listed))
        self.assertNotIn("token", listed[0])
        self.assertEqual(
            {"decisions": 0, "quality_assessments": 0, "data_extractions": 0, "active_tokens": 1},
            {key: listed[0][key] for key in ("decisions", "quality_assessments", "data_extractions", "active_tokens")},
        )
        members = [m["username"] for m in self.api("get", self.review_path("/members")).json()]
        self.assertIn("agent-screening-bot", members)

    def test_the_agent_works_with_its_own_token_and_is_attributed(self):
        agent = self.create()
        from django.test import Client

        as_agent = Client(headers={"Authorization": f"Bearer {agent['token']}"})
        article = ArticleFactory(review=self.review, source=self.source)
        response = self.api(
            "post", self.review_path("/decisions"), {"ids": [article.pk], "status": "A"}, client=as_agent
        )
        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual(agent["id"], StudyDecision.objects.get().user_id)
        self.assertEqual(Article.UNCLASSIFIED, Article.objects.get(pk=article.pk).status)
        with self.subTest(msg="an agent cannot manage agents or delete the review"):
            self.assertEqual(
                403, self.api("post", self.review_path("/agents"), {"name": "Child"}, client=as_agent).status_code
            )
            self.assertEqual(
                403,
                self.api("delete", self.review_path(f"/agents/{agent['id']}"), client=as_agent).status_code,
            )
            self.assertEqual(403, self.api("delete", self.review_path(), client=as_agent).status_code)

    def test_new_token(self):
        agent = self.create()
        renewed = self.api("post", self.review_path(f"/agents/{agent['id']}/token"))
        self.assertEqual(200, renewed.status_code)
        self.assertNotEqual(agent["token"], renewed.json()["token"])
        self.assertIsNone(ApiToken.objects.authenticate(agent["token"]))
        self.assertIsNotNone(ApiToken.objects.authenticate(renewed.json()["token"]))

    def test_delete_is_permanent_and_scoped(self):
        agent = self.create()
        with self.subTest(msg="co-author and outsider cannot"):
            self.assertEqual(
                403,
                self.api(
                    "delete", self.review_path(f"/agents/{agent['id']}"), client=self.client_for(self.co_author)
                ).status_code,
            )
            self.assertEqual(
                404,
                self.api(
                    "delete", self.review_path(f"/agents/{agent['id']}"), client=self.client_for(self.outsider)
                ).status_code,
            )
        with self.subTest(msg="owner deletes the account and the token stops working"):
            self.assertEqual(204, self.api("delete", self.review_path(f"/agents/{agent['id']}")).status_code)
            self.assertIsNone(ApiToken.objects.authenticate(agent["token"]))
            self.assertEqual([], self.api("get", self.review_path("/agents")).json())
            self.assertEqual(404, self.api("delete", self.review_path(f"/agents/{agent['id']}")).status_code)

    def test_validation(self):
        self.assertEqual(422, self.api("post", self.review_path("/agents"), {"name": "  "}).status_code)
        self.assertEqual(422, self.api("post", self.review_path("/agents"), {"name": "x" * 51}).status_code)
        self.assertTrue(API)
