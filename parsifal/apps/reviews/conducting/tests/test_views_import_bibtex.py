from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.models import Article
from parsifal.apps.reviews.tests.factories import ReviewFactory, SourceFactory

DATA = Path(__file__).resolve().parent.parent.parent / "tests" / "data"


class ImportBibtexViewsTest(TestCase):
    fixtures = ["source_initial_data.json"]

    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(sources=[cls.source])
        cls.outsider = UserFactory()
        cls.file_url = reverse("reviews:conducting:import_bibtex")
        cls.raw_url = reverse("reviews:conducting:import_bibtex_raw_content")
        cls.redirect_url = reverse("import_studies", args=(cls.review.author.username, cls.review.name))

    def test_upload_file(self):
        self.client.force_login(self.review.author)
        upload = SimpleUploadedFile("export.bib", (DATA / "scopus_sample.bib").read_bytes(), "application/x-bibtex")
        response = self.client.post(
            self.file_url, {"review-id": self.review.pk, "source-id": self.source.pk, "bibtex": upload}, follow=True
        )
        with self.subTest(msg="Test redirect"):
            self.assertEqual(self.redirect_url, response.redirect_chain[-1][0])
        with self.subTest(msg="Test success message"):
            self.assertContains(response, "2 articles successfully imported to")
        with self.subTest(msg="Test articles created with provenance"):
            self.assertEqual(2, Article.objects.filter(review=self.review, source=self.source).count())
            self.assertEqual(self.review.author, Article.objects.filter(review=self.review).first().created_by)

    def test_upload_invalid_extension(self):
        self.client.force_login(self.review.author)
        upload = SimpleUploadedFile("export.txt", b"@article{a, title={A}}", "text/plain")
        response = self.client.post(
            self.file_url, {"review-id": self.review.pk, "source-id": self.source.pk, "bibtex": upload}, follow=True
        )
        self.assertContains(response, "Invalid file type.")
        self.assertFalse(Article.objects.filter(review=self.review).exists())

    def test_raw_content_and_empty_content(self):
        self.client.force_login(self.review.author)
        self.client.post(
            self.raw_url,
            {"review-id": self.review.pk, "source-id": self.source.pk, "bibtex_file": "@article{k1, title={One}}"},
        )
        self.assertEqual("One", Article.objects.get(review=self.review, bibtex_key="k1").title)

        response = self.client.post(
            self.raw_url, {"review-id": self.review.pk, "source-id": self.source.pk, "bibtex_file": ""}, follow=True
        )
        self.assertContains(response, "An error occurred while trying to parse the bibtex file.")

    def test_outsider_forbidden(self):
        self.client.force_login(self.outsider)
        response = self.client.post(
            self.raw_url,
            {"review-id": self.review.pk, "source-id": self.source.pk, "bibtex_file": "@article{k, title={T}}"},
        )
        self.assertEqual(403, response.status_code)
        self.assertFalse(Article.objects.filter(review=self.review).exists())
