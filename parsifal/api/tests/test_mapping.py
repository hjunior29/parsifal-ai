from parsifal.api.tests.base import ApiTestCase
from parsifal.apps.reviews.tests.factories import ArticleFactory


class TestMappingStudyApi(ApiTestCase):
    def test_review_type_and_protocol_texts(self):
        response = self.api("post", "/reviews", {"title": "A map", "review_type": "mapping"})
        self.assertEqual(201, response.status_code)
        self.assertEqual("mapping", response.json()["review_type"])
        response = self.api(
            "patch", self.review_path(), {"review_type": "mapping", "validity_threats": "Descriptive validity..."}
        )
        self.assertEqual(
            ("mapping", "Descriptive validity..."),
            (response.json()["review_type"], response.json()["validity_threats"]),
        )
        self.assertEqual(422, self.api("patch", self.review_path(), {"review_type": "tertiary"}).status_code)
        self.assertEqual("mapping", self.api("get", self.review_path("/overview")).json()["review_type"])

    def test_search_documentation(self):
        response = self.api(
            "patch",
            self.review_path(f"/sources/{self.source.pk}/search"),
            {
                "search_type": "snowballing",
                "searched_at": "2026-10-01",
                "years_from": 2015,
                "years_to": 2026,
                "result_count": 42,
            },
        )
        self.assertEqual(200, response.status_code, response.content)
        body = response.json()
        self.assertEqual(
            ("snowballing", "2026-10-01", 2015, 2026, 42),
            (body["search_type"], body["searched_at"], body["years_from"], body["years_to"], body["result_count"]),
        )
        self.assertEqual(
            422,
            self.api("patch", self.review_path(f"/sources/{self.source.pk}/search"), {"years_from": 2030}).status_code,
        )
        listed = self.api("get", self.review_path("/sources/search-strings")).json()
        self.assertEqual(42, listed[0]["result_count"])

        imported = self.api(
            "post",
            self.review_path("/articles/import"),
            {"source_id": self.source.pk, "bibtex": "@article{k, title={T}}"},
        ).json()
        article = self.api("get", self.review_path(f"/articles/{imported['article_ids'][0]}")).json()
        self.assertIsNotNone(article["found_via_id"])

    def test_facets_classification_and_analytics(self):
        templates = self.api("get", "/facets/templates").json()
        self.assertIn("research_type", [t["key"] for t in templates])

        rtype = self.api("post", self.review_path("/facets"), {"template": "research_type"}).json()
        self.assertEqual(6, len(rtype["categories"]))
        topic = self.api(
            "post", self.review_path("/facets"), {"name": "Topic", "multiple": True, "categories": ["Testing"]}
        ).json()
        self.assertEqual(422, self.api("post", self.review_path("/facets"), {}).status_code)
        self.assertEqual(409, self.api("post", self.review_path("/facets"), {"name": "topic"}).status_code)

        requirements = self.api(
            "post", self.review_path(f"/facets/{topic['id']}/categories"), {"name": "Requirements"}
        ).json()
        self.assertEqual(
            201,
            self.api(
                "post", self.review_path(f"/facets/{topic['id']}/categories"), {"name": "Maintenance"}
            ).status_code,
        )
        self.api(
            "patch",
            self.review_path(f"/facets/{topic['id']}/categories/{requirements['id']}"),
            {"name": "Requirements engineering"},
        )
        self.assertEqual(
            200,
            self.api(
                "put",
                self.review_path(f"/facets/{topic['id']}/categories/order"),
                {
                    "ids": [requirements["id"], topic["categories"][0]["id"]]
                    + [
                        c["id"]
                        for c in self.api("get", self.review_path("/facets")).json()[1]["categories"]
                        if c["name"] == "Maintenance"
                    ]
                },
            ).status_code,
        )
        self.assertEqual(
            200, self.api("put", self.review_path("/facets/order"), {"ids": [topic["id"], rtype["id"]]}).status_code
        )
        facets = self.api("get", self.review_path("/facets")).json()
        self.assertEqual(["Topic", "Research type"], [f["name"] for f in facets])
        self.assertEqual("Requirements engineering", facets[0]["categories"][0]["name"])

        a1 = ArticleFactory(review=self.review, source=self.source, status="A")
        a2 = ArticleFactory(review=self.review, source=self.source, status="A")
        evaluation = next(c for c in rtype["categories"] if c["name"] == "Evaluation research")
        testing = topic["categories"][0]
        path = self.review_path(f"/articles/{a1.pk}/classification")
        body = self.api(
            "put", path, {"facet_id": rtype["id"], "category_ids": [evaluation["id"]], "notes": "clear"}
        ).json()
        facet_row = next(f for f in body["facets"] if f["facet_id"] == rtype["id"])
        self.assertEqual(
            (["Evaluation research"], "clear", self.author.username),
            (facet_row["categories"], facet_row["notes"], facet_row["user"]),
        )
        self.api("put", path, {"facet_id": topic["id"], "category_ids": [testing["id"], requirements["id"]]})
        self.api(
            "put",
            self.review_path(f"/articles/{a2.pk}/classification"),
            {"facet_id": rtype["id"], "category_ids": [evaluation["id"]]},
        )
        self.api(
            "put",
            self.review_path(f"/articles/{a2.pk}/classification"),
            {"facet_id": topic["id"], "category_ids": [testing["id"]]},
        )

        with self.subTest(msg="single-choice facet rejects two categories"):
            response = self.api(
                "put", path, {"facet_id": rtype["id"], "category_ids": [c["id"] for c in rtype["categories"][:2]]}
            )
            self.assertEqual(422, response.status_code)

        freq = self.api("get", self.review_path(f"/analytics/facets/{rtype['id']}/frequencies")).json()
        self.assertEqual(2, next(c["count"] for c in freq["categories"] if c["category"] == "Evaluation research"))
        matrix = self.api(
            "get", self.review_path(f"/analytics/facet-matrix?rows={topic['id']}&columns={rtype['id']}")
        ).json()
        cells = {(c["row"], c["column"]): c["count"] for c in matrix["cells"]}
        self.assertEqual(2, cells[("Testing", "Evaluation research")])
        self.assertEqual(1, cells[("Requirements engineering", "Evaluation research")])

        self.assertEqual(
            204,
            self.api("delete", self.review_path(f"/facets/{topic['id']}/categories/{requirements['id']}")).status_code,
        )
        self.assertEqual(204, self.api("delete", self.review_path(f"/facets/{topic['id']}")).status_code)
        self.assertEqual(1, len(self.api("get", self.review_path("/facets")).json()))

    def test_test_set_and_checklist(self):
        item = self.api("post", self.review_path("/test-set"), {"title": "Known paper", "doi": "10.1/x"}).json()
        self.assertIsNone(item["matched_article_id"])
        ArticleFactory(review=self.review, source=self.source, title="other", doi="10.1/X")
        report = self.api("post", self.review_path("/test-set/match")).json()
        self.assertEqual((1, 1, 1.0), (report["total"], report["found"], report["recall"]))
        self.api("patch", self.review_path(f"/test-set/{item['id']}"), {"doi": "", "title": "Nothing like it"})
        self.assertEqual(0, self.api("get", self.review_path("/test-set")).json()["found"])
        self.assertEqual(204, self.api("delete", self.review_path(f"/test-set/{item['id']}")).status_code)

        checklist = self.api("get", self.review_path("/checklist")).json()
        self.assertEqual((0, 26), (checklist["applied"], checklist["total"]))
        checklist = self.api(
            "put", self.review_path("/checklist/search_database"), {"applied": True, "notes": "Scopus"}
        ).json()
        self.assertEqual(1, checklist["applied"])
        self.assertEqual(422, self.api("put", self.review_path("/checklist/bogus"), {"applied": True}).status_code)

    def test_outsider_cannot_see_mapping_resources(self):
        outsider = self.client_for(self.outsider)
        for path in ("/facets", "/test-set", "/checklist"):
            self.assertEqual(404, self.api("get", self.review_path(path), client=outsider).status_code)
