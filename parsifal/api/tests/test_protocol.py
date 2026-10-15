from parsifal.api.tests.base import ApiTestCase
from parsifal.apps.reviews.models import Source
from parsifal.apps.reviews.tests.factories import ArticleFactory, DefaultSourceFactory


class TestQuestionsApi(ApiTestCase):
    def test_crud_and_order(self):
        q1 = self.api("post", self.review_path("/questions"), {"description": "RQ1?"}).json()
        q2 = self.api("post", self.review_path("/questions"), {"description": "RQ2?", "parent_id": q1["id"]}).json()
        self.assertEqual(q1["id"], q2["parent_question_id"])
        self.assertEqual(
            200,
            self.api("patch", self.review_path(f"/questions/{q1['id']}"), {"description": "RQ1 revised?"}).status_code,
        )
        self.assertEqual(
            200, self.api("put", self.review_path("/questions/order"), {"ids": [q2["id"], q1["id"]]}).status_code
        )
        listed = self.api("get", self.review_path("/questions")).json()
        self.assertEqual([q2["id"], q1["id"]], [q["id"] for q in listed])
        self.assertEqual(204, self.api("delete", self.review_path(f"/questions/{q2['id']}")).status_code)
        self.assertEqual(404, self.api("delete", self.review_path(f"/questions/{q2['id']}")).status_code)
        self.assertEqual(422, self.api("post", self.review_path("/questions"), {"description": ""}).status_code)


class TestKeywordsApi(ApiTestCase):
    def test_keywords_and_search_string(self):
        self.api("patch", self.review_path(), {"population": "software engineers", "intervention": "LLM"})
        imported = self.api("post", self.review_path("/keywords/import-picoc")).json()
        self.assertEqual({"software engineers", "LLM"}, {k["description"] for k in imported})

        llm = next(k for k in imported if k["description"] == "LLM")
        response = self.api(
            "patch", self.review_path(f"/keywords/{llm['id']}"), {"synonyms": ["large language model", "GPT"]}
        )
        self.assertEqual(["GPT", "large language model"], response.json()["synonyms"])

        created = self.api("post", self.review_path("/keywords"), {"description": "productivity", "related_to": "O"})
        self.assertEqual(201, created.status_code)

        generated = self.api("post", self.review_path("/search-string/generate")).json()["search_string"]
        self.assertEqual(
            '("software engineers") AND ("LLM" OR "GPT" OR "large language model") AND ("productivity")', generated
        )

        self.api("put", self.review_path("/search-string"), {"search_string": generated})
        self.assertEqual(generated, self.api("get", self.review_path("/search-string")).json()["search_string"])

        self.assertEqual(204, self.api("delete", self.review_path(f"/keywords/{llm['id']}")).status_code)
        self.assertEqual(2, len(self.api("get", self.review_path("/keywords")).json()))


class TestSourcesApi(ApiTestCase):
    def test_attach_default_custom_update_detach(self):
        default = DefaultSourceFactory(name="ACM Digital Library")
        response = self.api("post", self.review_path("/sources"), {"source_id": default.pk})
        self.assertEqual(201, response.status_code)
        self.assertEqual(409, self.api("post", self.review_path("/sources"), {"source_id": default.pk}).status_code)
        self.assertEqual(422, self.api("post", self.review_path("/sources"), {}).status_code)

        custom = self.api("post", self.review_path("/sources"), {"name": "arXiv", "url": "arxiv.org"}).json()
        self.assertEqual("http://arxiv.org", custom["url"])
        self.assertEqual(422, self.api("patch", self.review_path(f"/sources/{default.pk}"), {"name": "x"}).status_code)
        self.assertEqual(
            "arXiv.org",
            self.api("patch", self.review_path(f"/sources/{custom['id']}"), {"name": "arXiv.org"}).json()["name"],
        )

        ArticleFactory(review=self.review, source=default)
        self.assertEqual(204, self.api("delete", self.review_path(f"/sources/{default.pk}")).status_code)
        self.assertEqual(0, self.review.article_set.count())
        self.assertEqual(204, self.api("delete", self.review_path(f"/sources/{custom['id']}")).status_code)
        self.assertFalse(Source.objects.filter(pk=custom["id"]).exists())
        self.assertEqual([self.source.pk], [s["id"] for s in self.api("get", self.review_path("/sources")).json()])

    def test_source_search_strings(self):
        self.api("put", self.review_path("/search-string"), {"search_string": "generic"})
        response = self.api("post", self.review_path(f"/sources/{self.source.pk}/search-string/copy-generic"))
        self.assertEqual(200, response.status_code)
        self.assertEqual("generic", response.json()["search_string"])
        self.api("put", self.review_path(f"/sources/{self.source.pk}/search-string"), {"search_string": "adapted"})
        listed = self.api("get", self.review_path("/sources/search-strings")).json()
        self.assertEqual(
            [(self.source.pk, self.source.name, "adapted")],
            [(r["source_id"], r["source"], r["search_string"]) for r in listed],
        )
        self.assertEqual(
            204, self.api("delete", self.review_path(f"/sources/{self.source.pk}/search-string")).status_code
        )
        self.assertEqual(
            404, self.api("delete", self.review_path(f"/sources/{self.source.pk}/search-string")).status_code
        )


class TestCriteriaApi(ApiTestCase):
    def test_crud(self):
        inc = self.api(
            "post", self.review_path("/criteria"), {"description": "Peer reviewed", "criteria_type": "I"}
        ).json()
        self.assertEqual(
            422,
            self.api("post", self.review_path("/criteria"), {"description": "x", "criteria_type": "Z"}).status_code,
        )
        self.assertEqual(
            "Peer-reviewed",
            self.api("patch", self.review_path(f"/criteria/{inc['id']}"), {"description": "Peer-reviewed"}).json()[
                "description"
            ],
        )
        self.assertEqual(1, len(self.api("get", self.review_path("/criteria")).json()))
        self.assertEqual(204, self.api("delete", self.review_path(f"/criteria/{inc['id']}")).status_code)
