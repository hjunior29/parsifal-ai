import datetime
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.models import Article, ReviewTestSetArticle, SearchSession
from parsifal.apps.reviews.services import mapping
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


class ClearSourceViewTest(TestCase):
    fixtures = ["source_initial_data.json"]

    @classmethod
    def setUpTestData(cls):
        cls.source, cls.other = SourceFactory(), SourceFactory()
        cls.review = ReviewFactory(sources=[cls.source, cls.other])
        cls.url = reverse("reviews:conducting:clear_source_articles")

    def setUp(self):
        for index in range(2):
            Article.objects.create(review=self.review, source=self.source, title=f"Wrong {index}")
        Article.objects.create(review=self.review, source=self.other, title="Right")

    def test_import_page_offers_delete_only_for_sources_with_studies(self):
        self.client.force_login(self.review.author)
        response = self.client.get(reverse("import_studies", args=(self.review.author.username, self.review.name)))
        self.assertContains(response, "Delete all", count=2)
        self.assertContains(response, 'data-count="2"')

    def test_clear_one_source(self):
        self.client.force_login(self.review.author)
        response = self.client.post(self.url, {"review-id": self.review.pk, "source-id": self.source.pk}, follow=True)
        self.assertContains(response, "2 studies deleted.")
        self.assertEqual(["Right"], list(self.review.article_set.values_list("title", flat=True)))

    def test_requires_post_and_author(self):
        self.client.force_login(self.review.author)
        self.assertEqual(405, self.client.get(self.url, {"review-id": self.review.pk}).status_code)
        self.client.force_login(UserFactory())
        response = self.client.post(self.url, {"review-id": self.review.pk, "source-id": self.source.pk})
        self.assertEqual(403, response.status_code)
        self.assertEqual(3, self.review.article_set.count())

    def test_source_of_another_review_is_refused(self):
        self.client.force_login(self.review.author)
        response = self.client.post(
            self.url, {"review-id": self.review.pk, "source-id": SourceFactory().pk}, follow=True
        )
        self.assertContains(response, "not found in this review")
        self.assertEqual(3, self.review.article_set.count())


class SearchDateViewTest(TestCase):
    """The Date of Search column of Import Studies, saved as soon as it changes."""

    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory(name="Scopus")
        cls.review = ReviewFactory(sources=[cls.source])
        cls.url = reverse("reviews:conducting:save_searched_at")
        cls.page = reverse("import_studies", args=(cls.review.author.username, cls.review.name))

    def post(self, value, source=None):
        return self.client.post(
            self.url, {"review-id": self.review.pk, "source-id": (source or self.source).pk, "searched-at": value}
        )

    def test_save_show_and_clear(self):
        self.client.force_login(self.review.author)
        response = self.post("2026-10-01")
        self.assertEqual((200, b"2026-10-01"), (response.status_code, response.content))
        self.assertEqual(
            datetime.date(2026, 10, 1), SearchSession.objects.get(review=self.review, source=self.source).searched_at
        )
        self.assertContains(self.client.get(self.page), 'value="2026-10-01"')

        response = self.post("")
        self.assertEqual((200, b""), (response.status_code, response.content))
        self.assertIsNone(SearchSession.objects.get(review=self.review, source=self.source).searched_at)

    def test_bad_date_and_source_of_another_review(self):
        self.client.force_login(self.review.author)
        response = self.post("01/10/2026")
        self.assertEqual(400, response.status_code)
        self.assertIn(b"YYYY-MM-DD", response.content)
        self.assertEqual(400, self.post("2026-10-01", source=SourceFactory()).status_code)
        self.assertFalse(SearchSession.objects.filter(searched_at__isnull=False).exists())

    def test_requires_post_and_author(self):
        self.client.force_login(self.review.author)
        self.assertEqual(405, self.client.get(self.url, {"review-id": self.review.pk}).status_code)
        self.client.force_login(UserFactory())
        self.assertEqual(403, self.post("2026-10-01").status_code)
        self.assertFalse(SearchSession.objects.exists())


class KnownStudiesViewTest(TestCase):
    """The Known Studies panel of Import Studies: the test set that evaluates the search."""

    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory(name="Scopus")
        cls.review = ReviewFactory(sources=[cls.source])
        cls.url = reverse("reviews:conducting:known_studies")
        cls.page = reverse("import_studies", args=(cls.review.author.username, cls.review.name))

    def post(self, action, **data):
        return self.client.post(self.url, {"review-id": self.review.pk, "action": action, **data}, follow=True)

    def test_without_known_studies_the_panel_only_offers_to_add_one(self):
        self.client.force_login(self.review.author)
        response = self.client.get(self.page)
        self.assertContains(response, "Optional. Studies you already know are relevant")
        self.assertContains(response, "Add a known study")
        self.assertNotContains(response, "found by the search")

    def test_add_edit_and_remove(self):
        self.client.force_login(self.review.author)
        response = self.post("add", title="Rapid reviews in software engineering", doi="", notes="arXiv preprint")
        self.assertEqual(self.page + "#known-studies", response.redirect_chain[-1][0])
        self.assertContains(response, "The known study was added.")
        self.assertContains(response, "<strong>0 of 1</strong> found by the search")
        self.assertContains(response, "not found")
        known = self.review.test_set.get()

        self.client.post(
            reverse("reviews:conducting:import_bibtex_raw_content"),
            {
                "review-id": self.review.pk,
                "source-id": self.source.pk,
                "bibtex_file": "@article{k, title={Rapid Reviews in Software Engineering}}",
            },
        )
        response = self.client.get(self.page)
        self.assertContains(response, "<strong>1 of 1</strong> found by the search")
        self.assertContains(response, "in Scopus")

        response = self.client.get(self.page, {"edit-known": known.pk})
        self.assertContains(response, 'name="known-id" value="{0}"'.format(known.pk))
        response = self.post("update", **{"known-id": known.pk, "title": "Another", "doi": "10.1/x", "notes": ""})
        self.assertContains(response, "The known study was saved.")
        known.refresh_from_db()
        self.assertEqual(("Another", "10.1/x", None), (known.title, known.doi, known.matched_article))

        response = self.post("remove", **{"known-id": known.pk})
        self.assertContains(response, "The known study was removed.")
        self.assertFalse(self.review.test_set.exists())

    def test_errors_and_a_known_study_of_another_review(self):
        self.client.force_login(self.review.author)
        self.assertContains(self.post("add", title=""), "required")
        other = mapping.add_test_set_article(review=ReviewFactory(), title="Theirs")
        self.assertContains(self.post("remove", **{"known-id": other.pk}), "not found in this review")
        self.assertContains(self.post("update", **{"known-id": other.pk, "title": "Mine"}), "not found in this review")
        other.refresh_from_db()
        self.assertEqual("Theirs", other.title)

    def test_requires_post_and_author(self):
        self.client.force_login(self.review.author)
        self.assertEqual(405, self.client.get(self.url, {"review-id": self.review.pk}).status_code)
        self.client.force_login(UserFactory())
        self.assertEqual(403, self.client.post(self.url, {"review-id": self.review.pk, "action": "add"}).status_code)
        self.assertFalse(ReviewTestSetArticle.objects.exists())
