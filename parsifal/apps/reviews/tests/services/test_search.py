from django.test import TestCase

from parsifal.apps.core.exceptions import NotFound
from parsifal.apps.reviews.models import SearchSession
from parsifal.apps.reviews.services import protocol, search
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
