from django.test import Client

from parsifal.api.tests.base import ApiTestCase
from parsifal.apps.reviews.models import ReviewEvent
from parsifal.apps.reviews.tests.factories import ArticleFactory


class HistoryApiTest(ApiTestCase):
    def test_changes_are_recorded_with_who_and_through_what(self):
        self.api("PATCH", self.review_path(), {"objective": "Why"})
        cli = Client(
            headers={"Authorization": f"Bearer {self.keys[self.co_author.pk]}", "User-Agent": "parsifal-cli/1"}
        )
        self.api("PATCH", self.review_path(), {"title": "Agents"}, client=cli)
        mcp = Client(headers={"Authorization": f"Bearer {self.keys[self.author.pk]}", "User-Agent": "parsifal-mcp/1"})
        self.api("PATCH", self.review_path(), {"description": "About them"}, client=mcp)
        body = self.api("GET", self.review_path("/history")).json()
        self.assertEqual(3, body["count"])
        self.assertEqual(
            [
                ("Changed the review details (Description)", self.author.username, "mcp", "review"),
                ("Changed the review details (Title)", self.co_author.username, "cli", "review"),
                ("Changed the protocol (Objective)", self.author.username, "api", "planning"),
            ],
            [(event["summary"], event["actor"], event["via"], event["area"]) for event in body["items"]],
        )
        self.assertEqual(
            [{"key": "objective", "field": "Objective", "before": "", "after": "Why"}], body["items"][2]["changes"]
        )

    def test_filters(self):
        study = ArticleFactory(review=self.review)
        ReviewEvent.objects.create(
            review=self.review, area="selection", action="change", summary="Accepted a study", actor=self.co_author
        ).articles.add(study)
        ReviewEvent.objects.create(review=self.review, area="planning", action="add", summary="Added a question")
        for query, expected in (
            ("?area=planning", ["Added a question"]),
            (f"?article_id={study.pk}", ["Accepted a study"]),
            (f"?actor={self.co_author.username}", ["Accepted a study"]),
            ("?q=question", ["Added a question"]),
            ("?amendments=false", ["Added a question", "Accepted a study"]),
        ):
            with self.subTest(query=query):
                body = self.api("GET", self.review_path(f"/history{query}")).json()
                self.assertEqual(expected, [event["summary"] for event in body["items"]])
        accepted = self.api("GET", self.review_path(f"/history?article_id={study.pk}")).json()["items"][0]
        self.assertEqual([study.pk], accepted["article_ids"])
        self.assertEqual(422, self.api("GET", self.review_path("/history?area=nowhere")).status_code)

    def test_members_only(self):
        response = self.api("GET", self.review_path("/history"), client=self.client_for(self.outsider))
        self.assertEqual(404, response.status_code)
        self.assertEqual(
            200, self.api("GET", self.review_path("/history"), client=self.client_for(self.co_author)).status_code
        )
