from parsifal.api.tests.base import ApiTestCase
from parsifal.apps.reviews.models import Article
from parsifal.apps.reviews.tests.factories import ArticleFactory, SelectionCriteriaFactory


class TestDecisionsApi(ApiTestCase):
    """The author (human) and the co-author (an agent's token) screen independently, then consolidate."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.articles = ArticleFactory.create_batch(3, review=cls.review, source=cls.source)
        cls.criteria = SelectionCriteriaFactory(review=cls.review)

    def test_independent_screening_agreement_and_consolidation(self):
        agent = self.client_for(self.co_author)
        ids = [a.pk for a in self.articles]

        response = self.api(
            "post",
            self.review_path("/decisions"),
            {"ids": ids, "status": "A", "selection_criteria_id": self.criteria.pk, "comments": "fits RQ1"},
            client=agent,
        )
        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual({self.co_author.username}, {d["user"] for d in response.json()})

        self.api("post", self.review_path("/decisions"), {"ids": ids[:2], "status": "A"})
        self.api("post", self.review_path("/decisions"), {"ids": ids[2:], "status": "R"})

        with self.subTest(msg="article status untouched so far"):
            self.assertEqual({"U"}, set(Article.objects.filter(pk__in=ids).values_list("status", flat=True)))

        with self.subTest(msg="listing and per-article decisions"):
            listed = self.api("get", self.review_path(f"/decisions?user_id={self.co_author.pk}")).json()
            self.assertEqual(3, len(listed))
            per_article = self.api("get", self.review_path(f"/articles/{ids[2]}/decisions")).json()
            self.assertEqual({"A", "R"}, {d["status"] for d in per_article})

        with self.subTest(msg="agreement"):
            report = self.api("get", self.review_path("/decisions/agreement")).json()
            self.assertEqual((3, 2), (report["compared"], report["agreed"]))
            self.assertIn(
                report["interpretation"], {"poor", "slight", "fair", "moderate", "substantial", "almost perfect"}
            )

        with self.subTest(msg="disagreements"):
            rows = self.api("get", self.review_path("/decisions/disagreements")).json()
            self.assertEqual([ids[2]], [row["article"]["id"] for row in rows])

        with self.subTest(msg="summary"):
            summary = self.api("get", self.review_path("/decisions/summary")).json()
            self.assertEqual(3, summary[0]["articles"])

        with self.subTest(msg="consolidate unanimous then any_include"):
            result = self.api("post", self.review_path("/decisions/consolidate"), {"rule": "unanimous"}).json()
            self.assertEqual((2, 1, 2), (result["resolved"], result["unresolved"], result["changed"]))
            self.assertEqual(ids[:2], result["changed_ids"])
            self.assertEqual("U", Article.objects.get(pk=ids[2]).status)
            with self.subTest(msg="the disagreement stays, with the status the article has now"):
                rows = self.api("get", self.review_path("/decisions/disagreements")).json()
                self.assertEqual([(ids[2], "U")], [(row["article"]["id"], row["article"]["status"]) for row in rows])
            again = self.api("post", self.review_path("/decisions/consolidate"), {"rule": "unanimous"}).json()
            self.assertEqual((2, 0, []), (again["resolved"], again["changed"], again["changed_ids"]))
            result = self.api(
                "post", self.review_path("/decisions/consolidate"), {"rule": "any_include", "ids": [ids[2]]}
            ).json()
            self.assertEqual(([ids[2]], [ids[2]]), (result["resolved_ids"], result["changed_ids"]))
            self.assertEqual("A", Article.objects.get(pk=ids[2]).status)
            rows = self.api("get", self.review_path("/decisions/disagreements")).json()
            self.assertEqual(
                [("A", self.author.username)], [(r["article"]["status"], r["article"]["updated_by"]) for r in rows]
            )
            self.assertEqual(
                422, self.api("post", self.review_path("/decisions/consolidate"), {"rule": "coin"}).status_code
            )

        with self.subTest(msg="remove my decision"):
            self.assertEqual(
                204,
                self.api("delete", self.review_path(f"/articles/{ids[0]}/decisions/mine"), client=agent).status_code,
            )
            self.assertEqual(
                404,
                self.api("delete", self.review_path(f"/articles/{ids[0]}/decisions/mine"), client=agent).status_code,
            )

    def test_validation_and_scoping(self):
        foreign = ArticleFactory()
        self.assertEqual(
            404, self.api("post", self.review_path("/decisions"), {"ids": [foreign.pk], "status": "A"}).status_code
        )
        self.assertEqual(
            422,
            self.api(
                "post", self.review_path("/decisions"), {"ids": [self.articles[0].pk], "status": "Z"}
            ).status_code,
        )
        self.assertEqual(
            422,
            self.api(
                "post", self.review_path("/decisions"), {"ids": [self.articles[0].pk], "status": "A", "stage": "nope"}
            ).status_code,
        )
        self.assertEqual(422, self.api("get", self.review_path("/decisions/agreement")).status_code)
        self.assertEqual(
            404, self.api("get", self.review_path("/decisions"), client=self.client_for(self.outsider)).status_code
        )
