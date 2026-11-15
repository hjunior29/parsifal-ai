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


class ProtocolHistoryApiTest(ApiTestCase):
    """The services of Planning record what the web pages do, through the API."""

    def summaries(self):
        body = self.api("GET", self.review_path("/history?area=planning&limit=100")).json()
        return [event["summary"] for event in reversed(body["items"])]

    def test_protocol(self):
        q1 = self.api("POST", self.review_path("/questions"), {"description": "RQ1"}).json()["id"]
        q2 = self.api("POST", self.review_path("/questions"), {"description": "RQ2"}).json()["id"]
        self.api("PATCH", self.review_path(f"/questions/{q1}"), {"description": "RQ1, again"})
        self.api("PUT", self.review_path("/questions/order"), {"ids": [q2, q1]})
        self.api("PUT", self.review_path("/questions/order"), {"ids": [q2, q1]})  # the same order: nothing
        keyword = self.api(
            "POST",
            self.review_path("/keywords"),
            {"description": "glasses", "related_to": "I", "synonyms": ["eyewear"]},
        ).json()["id"]
        self.api("PATCH", self.review_path(f"/keywords/{keyword}"), {"synonyms": ["eyewear", "HMD"]})
        self.api("PUT", self.review_path("/search-string"), {"search_string": "glasses"})
        criteria = self.api(
            "POST", self.review_path("/criteria"), {"description": "Not in English", "criteria_type": "E"}
        ).json()["id"]
        self.api("PATCH", self.review_path(f"/criteria/{criteria}"), {"description": "Not written in English"})
        self.api("DELETE", self.review_path(f"/questions/{q1}"))
        self.assertEqual(
            [
                "Added the research question “RQ1”",
                "Added the research question “RQ2”",
                "Changed the research question “RQ1, again”",
                "Reordered the research questions",
                "Added the keyword “glasses”",
                "Changed the keyword “glasses”",
                "Changed the search string",
                "Added the exclusion criterion “Not in English”",
                "Changed the exclusion criterion “Not written in English”",
                "Removed the research question “RQ1, again”",
            ],
            self.summaries(),
        )

    def test_quality_extraction_and_classification(self):
        answers = self.api("POST", self.review_path("/quality/answers/suggested")).json()
        self.api("PATCH", self.review_path(f"/quality/answers/{answers[0]['id']}"), {"weight": 2})
        self.api("PUT", self.review_path("/quality/cutoff"), {"cutoff": 1.5})
        field = self.api(
            "POST",
            self.review_path("/extraction/fields"),
            {"description": "Country", "field_type": "M", "lookup_values": ["Brazil"]},
        ).json()["id"]
        self.api("PATCH", self.review_path(f"/extraction/fields/{field}"), {"lookup_values": ["Brazil", "Chile"]})
        facet = self.api("POST", self.review_path("/facets"), {"template": "venue_type"}).json()
        category = facet["categories"][0]["id"]
        self.api("DELETE", self.review_path(f"/facets/{facet['id']}/categories/{category}"))
        self.assertEqual(
            [
                "Added the suggested quality assessment answers",
                "Changed the quality assessment answer “Yes”",
                "Changed the protocol (Quality assessment cutoff score)",
                "Added the data extraction field “Country”",
                "Changed the data extraction field “Country”",
                "Added the classification facet “Venue type”",
                "Removed the category “Venue type: Journal”",
            ],
            self.summaries(),
        )
        events = self.api("GET", self.review_path("/history?area=planning&q=Chile")).json()["items"]
        self.assertEqual(
            [{"key": "options", "field": "Options", "before": "", "after": "Chile"}], events[0]["changes"]
        )
