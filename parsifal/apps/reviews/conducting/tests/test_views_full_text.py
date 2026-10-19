import io
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.tests.files import PDF, TemporaryFilesMixin
from parsifal.apps.reviews.conducting import views
from parsifal.apps.reviews.models import Article
from parsifal.apps.reviews.services import full_texts
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory, SourceFactory


class TestFullTextViews(TemporaryFilesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.author = UserFactory(username="alice")
        cls.outsider = UserFactory()
        cls.review = ReviewFactory(author=cls.author, sources=[cls.source])
        cls.article = ArticleFactory(review=cls.review, source=cls.source)

    def setUp(self):
        super().setUp()
        self.client.force_login(self.author)

    def details(self):
        return self.client.get(
            reverse("reviews:conducting:article_details"), {"review-id": self.review.pk, "article-id": self.article.pk}
        )

    def upload(self, content=PDF, name="Smith 2020.pdf", **extra):
        data = {"review-id": self.review.pk, "article-id": self.article.pk, **extra}
        if content is not None:
            data["pdf"] = SimpleUploadedFile(name, content, content_type="application/pdf")
        return self.client.post(reverse("reviews:conducting:upload_article_pdf"), data)

    def attach(self):
        return full_texts.attach_pdf(
            review=self.review, article_id=self.article.pk, file=io.BytesIO(PDF), filename="Smith 2020.pdf"
        )

    def test_the_full_text_tab_offers_the_upload(self):
        response = self.details()
        self.assertContains(response, 'href="#tab-full-text"')
        self.assertContains(response, "This study has no PDF yet.")
        self.assertContains(response, "PDF only, up to 50 MB.")
        self.assertContains(response, 'accept="application/pdf,.pdf"')
        self.assertNotContains(response, "article-pdf-frame")
        with self.subTest(msg="a study being added has no tab yet"):
            response = self.client.get(
                reverse("reviews:conducting:new_article"), {"review-id": self.review.pk, "source-id": self.source.pk}
            )
            self.assertNotContains(response, "tab-full-text")

    def test_upload_shows_the_pdf(self):
        response = self.upload()
        self.assertEqual(200, response.status_code)
        url = reverse("reviews:conducting:article_pdf", args=(self.article.pk,))
        self.assertContains(response, "The PDF was uploaded.")
        self.assertContains(response, "Smith 2020.pdf")
        # The frame gets its src only when the tab opens; the button opens the same route in a new tab.
        self.assertContains(response, f'data-src="{url}"')
        self.assertContains(response, f'<a href="{url}" target="_blank"')
        self.assertNotContains(response, "<form")  # the tab lives inside the article form
        self.assertEqual("Smith 2020.pdf", Article.objects.get(pk=self.article.pk).pdf.filename)
        response = self.details()
        self.assertContains(response, 'title="Has a PDF"')
        self.assertContains(response, f'data-src="{url}"')

    def test_upload_errors(self):
        self.assertContains(self.upload(b"<html></html>"), "Only PDF files are accepted.", status_code=400)
        self.assertContains(self.upload(None), "Choose a PDF to upload.", status_code=400)
        self.client.force_login(self.outsider)
        self.assertEqual(403, self.upload().status_code)
        self.assertEqual([], self.stored_files())

    def test_the_pdf_route_serves_members_only(self):
        url = reverse("reviews:conducting:article_pdf", args=(self.article.pk,))
        self.assertEqual(404, self.client.get(url).status_code)  # no PDF yet
        self.attach()
        response = self.client.get(url)
        self.assertEqual(200, response.status_code)
        self.assertEqual(PDF, b"".join(response.streaming_content))
        self.assertEqual("application/pdf", response["Content-Type"])
        self.assertTrue(response["Content-Disposition"].startswith("inline;"), response["Content-Disposition"])
        self.assertEqual("SAMEORIGIN", response["X-Frame-Options"])  # framed by the Full text tab
        self.client.force_login(self.outsider)
        self.assertEqual(404, self.client.get(url).status_code)
        self.client.logout()
        self.assertEqual(302, self.client.get(url).status_code)

    def test_in_a_bucket_the_route_sends_to_a_link_that_expires(self):
        pdf = self.attach()
        bucket = mock.Mock()
        bucket.url.return_value = f"https://bucket.example/{pdf.key}?X-Amz-Expires=300&X-Amz-Signature=abc"
        with (
            mock.patch.object(views, "files_are_local", return_value=False),
            mock.patch.object(views, "files_storage", return_value=bucket),
        ):
            response = self.client.get(reverse("reviews:conducting:article_pdf", args=(self.article.pk,)))
        self.assertRedirects(response, bucket.url.return_value, fetch_redirect_response=False)
        bucket.url.assert_called_once_with(pdf.key)

    def test_remove(self):
        self.attach()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("reviews:conducting:remove_article_pdf"),
                {"review-id": self.review.pk, "article-id": self.article.pk},
            )
        self.assertContains(response, "The PDF was removed.")
        self.assertContains(response, "This study has no PDF yet.")
        self.assertEqual([], self.stored_files())
        response = self.client.post(
            reverse("reviews:conducting:remove_article_pdf"),
            {"review-id": self.review.pk, "article-id": self.article.pk},
        )
        self.assertContains(response, "has no PDF", status_code=400)
