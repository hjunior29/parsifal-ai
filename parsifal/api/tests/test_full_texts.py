import hashlib

from django.core.files.uploadedfile import SimpleUploadedFile

from parsifal.api.tests.base import ApiTestCase
from parsifal.apps.core.tests.files import PDF, TemporaryFilesMixin
from parsifal.apps.reviews.models import Article
from parsifal.apps.reviews.tests.factories import ArticleFactory


class TestFullTextApi(TemporaryFilesMixin, ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.article = ArticleFactory(review=cls.review, source=cls.source, status=Article.ACCEPTED)

    def pdf_path(self, article=None):
        return self.review_path(f"/articles/{(article or self.article).pk}/pdf")

    def upload(self, content=PDF, name="Smith 2020.pdf", client=None):
        return (client or self.client).post(
            f"/api/v1{self.pdf_path()}", {"file": SimpleUploadedFile(name, content, content_type="application/pdf")}
        )

    def test_upload_download_and_delete(self):
        self.assertIsNone(self.api("get", self.review_path(f"/articles/{self.article.pk}")).json()["pdf"])
        self.assertEqual(404, self.api("get", self.pdf_path()).status_code)

        response = self.upload()
        self.assertEqual(201, response.status_code, response.content)
        body = response.json()
        self.assertEqual(
            {
                "filename": "Smith 2020.pdf",
                "content_type": "application/pdf",
                "size": len(PDF),
                "sha256": hashlib.sha256(PDF).hexdigest(),
                "uploaded_by": self.author.username,
            },
            {key: value for key, value in body.items() if key != "uploaded_at"},
        )
        article = self.api("get", self.review_path(f"/articles/{self.article.pk}")).json()
        self.assertEqual(("Smith 2020.pdf", "A"), (article["pdf"]["filename"], article["status"]))
        listed = self.api("get", self.review_path("/articles")).json()["items"]
        self.assertEqual(["Smith 2020.pdf"], [a["pdf"]["filename"] for a in listed if a["pdf"]])

        response = self.api("get", self.pdf_path())
        self.assertEqual(200, response.status_code)
        self.assertEqual(PDF, b"".join(response.streaming_content))
        self.assertEqual("application/pdf", response["Content-Type"])
        self.assertIn('attachment; filename="Smith 2020.pdf"', response["Content-Disposition"])

        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(204, self.api("delete", self.pdf_path()).status_code)
        self.assertEqual([], self.stored_files())
        self.assertEqual(404, self.api("delete", self.pdf_path()).status_code)

    def test_refuses_what_is_not_a_pdf(self):
        response = self.upload(b"PK\x03\x04 not a pdf", name="paper.pdf")
        self.assertEqual(422, response.status_code)
        self.assertEqual(("validation_error", "file"), (response.json()["code"], response.json()["field"]))
        self.assertEqual([], self.stored_files())

    def test_members_only(self):
        self.assertEqual(201, self.upload(client=self.client_for(self.co_author)).status_code)
        outsider = self.client_for(self.outsider)
        self.assertEqual(404, self.upload(client=outsider).status_code)
        self.assertEqual(404, self.api("get", self.pdf_path(), client=outsider).status_code)
        self.assertEqual(404, self.api("delete", self.pdf_path(), client=outsider).status_code)
        other = ArticleFactory()
        self.assertEqual(404, self.api("get", self.pdf_path(other)).status_code)
