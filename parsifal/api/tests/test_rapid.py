from parsifal.api.tests.base import ApiTestCase
from parsifal.apps.reviews.models import Review
from parsifal.apps.reviews.tests.factories import ArticleFactory


class TestRapidReviewApi(ApiTestCase):
    def setUp(self):
        super().setUp()
        Review.objects.filter(pk=self.review.pk).update(review_type=Review.RAPID)

    def test_create_and_practical_context(self):
        body = self.api("post", "/reviews", {"title": "A rapid review", "review_type": "rapid"}).json()
        self.assertEqual("rapid", body["review_type"])
        body = self.api(
            "patch",
            self.review_path(),
            {"demand": "practitioners", "practical_problem": "Flaky tests.", "started_on": "2026-11-02"},
        ).json()
        self.assertEqual(
            ("practitioners", "Flaky tests.", "2026-11-02", None),
            (body["demand"], body["practical_problem"], body["started_on"], body["deadline"]),
        )
        self.assertIsNone(self.api("patch", self.review_path(), {"started_on": ""}).json()["started_on"])
        self.assertEqual(422, self.api("patch", self.review_path(), {"demand": "boss"}).status_code)

    def test_checklist_and_draft(self):
        body = self.api("get", self.review_path("/checklist"), QUERY_STRING="catalog=rapid").json()
        self.assertEqual("rapid", body["catalog"])
        self.assertTrue(any(item["threat"] for item in body["items"]))
        body = self.api(
            "put", self.review_path("/checklist/rr_single_source"), {"applied": True, "notes": "Scopus"}
        ).json()
        self.assertEqual((1, "rapid"), (body["applied"], body["catalog"]))
        added = self.api("post", self.review_path("/threats/draft")).json()
        self.assertEqual([("A single search source", "Scopus")], [(t["title"], t["mitigation"]) for t in added])
        self.assertEqual([], self.api("post", self.review_path("/threats/draft")).json())
        self.assertEqual("petersen", self.api("get", self.review_path("/checklist")).json()["catalog"])

    def test_other_reviews_have_none_of_it(self):
        Review.objects.filter(pk=self.review.pk).update(review_type=Review.SLR)
        self.assertEqual(
            422, self.api("get", self.review_path("/checklist"), QUERY_STRING="catalog=rapid").status_code
        )
        self.assertEqual(
            422, self.api("put", self.review_path("/checklist/rr_single_source"), {"applied": True}).status_code
        )
        self.assertEqual(422, self.api("post", self.review_path("/threats/draft")).status_code)


class TestRoundsApi(ApiTestCase):
    def setUp(self):
        super().setUp()
        Review.objects.filter(pk=self.review.pk).update(review_type=Review.RAPID)
        self.one = ArticleFactory(review=self.review, source=self.source, title="One")
        self.two = ArticleFactory(review=self.review, source=self.source, title="Two")

    def test_round_mode(self):
        body = self.api(
            "post",
            self.review_path("/articles/status"),
            {"ids": [self.one.pk], "status": "A", "stage": "title"},
        ).json()
        self.assertEqual(1, body["count"])
        decision = self.api("get", self.review_path(f"/articles/{self.one.pk}/decisions")).json()
        self.assertEqual([("title", "A")], [(d["stage"], d["status"]) for d in decision])
        pending = self.api("get", self.review_path("/articles"), QUERY_STRING="stage=title&stage_state=pending")
        self.assertEqual(["Two"], [a["title"] for a in pending.json()["items"]])
        nxt = self.api("get", self.review_path("/articles"), QUERY_STRING="stage=title_abstract").json()
        self.assertEqual(["One"], [a["title"] for a in nxt["items"]])
        body = self.api(
            "post",
            self.review_path("/articles/status"),
            {
                "all_matching": True,
                "match_stage": "title",
                "match_stage_state": "pending",
                "status": "R",
                "stage": "title",
            },
        ).json()
        self.assertEqual(1, body["count"])
        self.two.refresh_from_db()
        self.assertEqual("R", self.two.status)

    def test_decisions_default_to_the_first_round(self):
        self.api("post", self.review_path("/decisions"), {"ids": [self.one.pk], "status": "R"})
        summary = self.api("get", self.review_path("/decisions/summary")).json()
        self.assertEqual(["title"], [row["stage"] for row in summary])

    def test_funnel_and_prisma(self):
        funnel = self.api("get", self.review_path("/analytics/funnel")).json()
        self.assertEqual(["records", "title", "title_abstract", "full_text"], [row["key"] for row in funnel])
        prisma = self.api("get", self.review_path("/analytics/prisma")).json()
        self.assertEqual(["title", "title_abstract"], [row["stage"] for row in prisma["excluded_by_round"]])
        Review.objects.filter(pk=self.review.pk).update(review_type=Review.SLR)
        self.assertEqual(422, self.api("get", self.review_path("/analytics/funnel")).status_code)
        self.assertEqual(
            422,
            self.api(
                "post", self.review_path("/articles/status"), {"ids": [self.one.pk], "status": "A", "stage": "title"}
            ).status_code,
        )
