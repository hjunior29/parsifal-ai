from django.core.files.uploadedfile import SimpleUploadedFile

from parsifal.api.tests.base import API, ApiTestCase
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

    def test_date_of_search(self):
        path = self.review_path(f"/sources/{self.source.pk}/search")
        imported = self.api(
            "post",
            self.review_path("/articles/import"),
            {"source_id": self.source.pk, "bibtex": "@article{k, title={T}}", "searched_at": "2026-09-30"},
        )
        self.assertEqual(201, imported.status_code, imported.content)
        self.assertEqual(
            [{"source_id": self.source.pk, "source": self.source.name, "imported": 1, "searched_at": "2026-09-30"}],
            self.api("get", self.review_path("/sources/imports")).json(),
        )
        article = self.api("get", self.review_path(f"/articles/{imported.json()['article_ids'][0]}")).json()
        self.assertIsNotNone(article["found_via_id"])

        self.assertEqual(200, self.api("patch", path, {"result_count": 3}).status_code)
        self.assertEqual("2026-09-30", self.api("get", self.review_path("/sources/imports")).json()[0]["searched_at"])
        for empty in ("", None):
            self.api("patch", path, {"searched_at": "2026-09-30"})
            body = self.api("patch", path, {"searched_at": empty}).json()
            self.assertEqual((None, 3), (body["searched_at"], body["result_count"]))
        self.assertEqual(422, self.api("patch", path, {"searched_at": "30/09/2026"}).status_code)

        with self.subTest(msg="the file import takes the date too"):
            response = self.client.post(
                f"{API}{self.review_path('/articles/import/file')}",
                {
                    "source_id": self.source.pk,
                    "searched_at": "2026-10-02",
                    "file": SimpleUploadedFile("x.bib", b"@article{k2, title={U}}"),
                },
            )
            self.assertEqual(201, response.status_code, response.content)
            self.assertEqual(
                "2026-10-02", self.api("get", self.review_path("/sources/imports")).json()[0]["searched_at"]
            )

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
        for path in ("/test-set", "/checklist"):
            self.assertEqual(404, self.api("get", self.review_path(path), client=outsider).status_code)
