import datetime

from django.test import TestCase

from parsifal.apps.core.exceptions import NotFound, ValidationError
from parsifal.apps.reviews.models import Article, SearchSession
from parsifal.apps.reviews.services import protocol, search, studies
from parsifal.apps.reviews.tests.factories import ReviewFactory, SourceFactory


class TestSourceSearchStrings(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.scopus = SourceFactory(name="Scopus")
        cls.ieee = SourceFactory(name="IEEE")
        cls.review = ReviewFactory(sources=[cls.scopus, cls.ieee])

    def test_add_slots_is_idempotent(self):
        created = search.add_source_search_strings(review=self.review, source_ids=[self.scopus.pk, self.ieee.pk])
        self.assertEqual(2, len(created))
        self.assertEqual([], search.add_source_search_strings(review=self.review, source_ids=[self.scopus.pk]))
        self.assertEqual(["IEEE", "Scopus"], [s.source.name for s in search.list_source_search_strings(self.review)])

    def test_set_copy_remove(self):
        protocol.set_generic_search_string(review=self.review, search_string="a AND b")
        search.copy_generic_search_string(review=self.review, source_id=self.scopus.pk)
        self.assertEqual("a AND b", SearchSession.objects.get(review=self.review, source=self.scopus).search_string)
        search.set_source_search_string(review=self.review, source_id=self.scopus.pk, search_string="TITLE-ABS-KEY(a)")
        self.assertEqual(1, SearchSession.objects.filter(review=self.review, source=self.scopus).count())
        search.remove_source_search_string(review=self.review, source_id=self.scopus.pk)
        with self.assertRaises(NotFound):
            search.remove_source_search_string(review=self.review, source_id=self.scopus.pk)

    def test_source_must_be_attached(self):
        detached = SourceFactory()
        with self.assertRaises(NotFound):
            search.set_source_search_string(review=self.review, source_id=detached.pk, search_string="x")
        with self.assertRaises(NotFound):
            search.add_source_search_strings(review=self.review, source_ids=[detached.pk])


class TestDateOfSearch(TestCase):
    """The date each source was searched: Import Studies, the import itself and the search documentation."""

    @classmethod
    def setUpTestData(cls):
        cls.scopus = SourceFactory(name="Scopus")
        cls.ieee = SourceFactory(name="IEEE")
        cls.review = ReviewFactory(sources=[cls.scopus, cls.ieee])

    def test_imports_list_counts_and_dates(self):
        Article.objects.create(review=self.review, source=self.scopus, title="One")
        Article.objects.create(review=self.review, source=self.scopus, title="Two")
        Article.objects.create(review=ReviewFactory(sources=[self.scopus]), source=self.scopus, title="Elsewhere")
        search.update_source_search(review=self.review, source_id=self.scopus.pk, searched_at="2026-10-01")
        self.assertEqual(
            [("IEEE", 0, None), ("Scopus", 2, datetime.date(2026, 10, 1))],
            [(row.source.name, row.imported, row.searched_at) for row in search.list_source_imports(self.review)],
        )

    def test_only_the_fields_given_change_and_empty_clears(self):
        search.update_source_search(
            review=self.review, source_id=self.scopus.pk, searched_at="2026-10-01", result_count=12
        )
        session = search.update_source_search(review=self.review, source_id=self.scopus.pk, years_from=2015)
        self.assertEqual(
            (datetime.date(2026, 10, 1), 12, 2015), (session.searched_at, session.result_count, session.years_from)
        )
        for empty in ("", None):
            search.update_source_search(review=self.review, source_id=self.scopus.pk, searched_at="2026-10-01")
            session = search.update_source_search(review=self.review, source_id=self.scopus.pk, searched_at=empty)
            self.assertIsNone(session.searched_at)
            self.assertEqual(12, session.result_count)
        session = search.update_source_search(review=self.review, source_id=self.scopus.pk, result_count=None)
        self.assertIsNone(session.result_count)
        with self.assertRaises(ValidationError):
            search.update_source_search(review=self.review, source_id=self.scopus.pk, query="x")

    def test_import_saves_the_date_and_links_the_studies(self):
        result = studies.import_bibtex(
            review=self.review, source_id=self.ieee.pk, content="@article{k, title={T}}", searched_at="2026-09-30"
        )
        session = SearchSession.objects.get(review=self.review, source=self.ieee)
        self.assertEqual(datetime.date(2026, 9, 30), session.searched_at)
        self.assertEqual(session, result.articles[0].found_via)

        studies.import_bibtex(review=self.review, source_id=self.ieee.pk, content="@article{k2, title={U}}")
        self.assertEqual(datetime.date(2026, 9, 30), SearchSession.objects.get(pk=session.pk).searched_at)

    def test_import_with_a_bad_date_imports_nothing(self):
        with self.assertRaises(ValidationError):
            studies.import_bibtex(
                review=self.review, source_id=self.ieee.pk, content="@article{k, title={T}}", searched_at="30/09/2026"
            )
        self.assertFalse(self.review.article_set.exists())
