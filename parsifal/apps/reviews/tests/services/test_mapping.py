import datetime

from django.test import TestCase

from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import Review, SearchSession
from parsifal.apps.reviews.services import mapping, reviews, search, studies
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory, SourceFactory


class TestTestSetAndChecklist(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(review_type=Review.MAPPING, sources=[cls.source])

    def test_test_set_matching(self):
        known = mapping.add_test_set_article(
            review=self.review, title="Tool support for mapping studies", doi="10.1/ABC"
        )
        report = mapping.test_set_report(self.review)
        self.assertEqual((1, 0, 0.0), (report["total"], report["found"], report["recall"]))

        ArticleFactory(review=self.review, source=self.source, title="Other", doi="10.1/abc")
        report = mapping.match_test_set(review=self.review)
        self.assertEqual(1, report["found"])
        known.refresh_from_db()
        self.assertEqual("Other", known.matched_article.title)

        second = mapping.add_test_set_article(review=self.review, title="Automating Study Selection")
        self.assertIsNone(second.matched_article)
        ArticleFactory(review=self.review, source=self.source, title="automating study selection!")
        self.assertEqual(2, mapping.match_test_set(review=self.review)["found"])

        mapping.update_test_set_article(review=self.review, item_id=second.pk, title="Something else entirely")
        second.refresh_from_db()
        self.assertIsNone(second.matched_article)
        mapping.remove_test_set_article(review=self.review, item_id=second.pk)
        self.assertEqual(1, self.review.test_set.count())
        with self.assertRaises(ValidationError):
            mapping.add_test_set_article(review=self.review, title="")

    def test_known_studies_follow_every_change_to_the_studies(self):
        """Imported, added, edited or deleted, the studies are matched again: the recall is always current."""
        doi = mapping.add_test_set_article(review=self.review, title="Rapid reviews", doi="https://doi.org/10.1/ABC")
        title = mapping.add_test_set_article(review=self.review, title="Moiré patterns – a survey")
        self.assertEqual(0, mapping.test_set_report(self.review)["found"])

        bibtex = (
            "@article{k1, title={Another title}, doi={10.1/abc}}\n"
            "@article{k2, title={Moir{\\'e} Patterns - A Survey}}"
        )
        result = studies.import_bibtex(review=self.review, source_id=self.source.pk, content=bibtex)
        first, second = result.articles
        doi.refresh_from_db()
        title.refresh_from_db()
        self.assertEqual((first, second), (doi.matched_article, title.matched_article))

        copy = studies.create_article(review=self.review, source_id=self.source.pk, title="Moire patterns, a survey")
        studies.delete_articles(review=self.review, article_ids=[second.pk])
        title.refresh_from_db()
        self.assertEqual(copy, title.matched_article)

        studies.update_article(review=self.review, article_id=copy.pk, title="Something else")
        studies.clear_articles(review=self.review, source_id=self.source.pk)
        report = mapping.test_set_report(self.review)
        self.assertEqual((2, 0, 0.0), (report["total"], report["found"], report["recall"]))

    def test_a_known_study_links_to_a_copy_not_marked_duplicated(self):
        known = mapping.add_test_set_article(review=self.review, title="Known")
        duplicated = ArticleFactory(review=self.review, source=self.source, title="Known", status="D")
        kept = ArticleFactory(review=self.review, source=self.source, title="Known")
        mapping.match_test_set(review=self.review)
        known.refresh_from_db()
        self.assertEqual(kept, known.matched_article)
        self.assertNotEqual(duplicated, known.matched_article)

    def test_checklist(self):
        initial = mapping.checklist(self.review)
        self.assertEqual((0, 26, 0.0), (initial["applied"], initial["total"], initial["ratio"]))
        result = mapping.set_checklist_item(
            review=self.review, key="search_database", applied=True, notes="Scopus, IEEE"
        )
        self.assertEqual(1, result["applied"])
        row = next(r for r in result["items"] if r["key"] == "search_database")
        self.assertEqual(("Study identification", True, "Scopus, IEEE"), (row["phase"], row["applied"], row["notes"]))
        mapping.set_checklist_item(review=self.review, key="search_database", applied=False)
        self.assertEqual(0, mapping.checklist(self.review)["applied"])
        with self.assertRaises(ValidationError):
            mapping.set_checklist_item(review=self.review, key="bogus", applied=True)


class TestSearchMetadataAndReviewFields(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(sources=[cls.source])

    def test_update_source_search_and_provenance(self):
        session = search.update_source_search(
            review=self.review,
            source_id=self.source.pk,
            search_type="snowballing",
            searched_at="2026-10-01",
            years_from=2015,
            years_to="2026",
            result_count=120,
        )
        self.assertEqual(
            ("snowballing", datetime.date(2026, 10, 1), 2015, 2026, 120),
            (session.search_type, session.searched_at, session.years_from, session.years_to, session.result_count),
        )
        with self.assertRaises(ValidationError):
            search.update_source_search(review=self.review, source_id=self.source.pk, years_from=2030)
        with self.assertRaises(ValidationError):
            search.update_source_search(review=self.review, source_id=self.source.pk, searched_at="not-a-date")
        with self.assertRaises(ValidationError):
            search.update_source_search(review=self.review, source_id=self.source.pk, search_type="telepathy")

        result = studies.import_bibtex(review=self.review, source_id=self.source.pk, content="@article{k, title={T}}")
        self.assertEqual(session, result.articles[0].found_via)
        self.assertEqual(1, SearchSession.objects.get(pk=session.pk).found_articles.count())

    def test_review_type_and_protocol_texts(self):
        reviews.update_review(review=self.review, review_type="mapping", validity_threats="Descriptive validity: ...")
        self.review.refresh_from_db()
        self.assertTrue(self.review.is_mapping_study)
        self.assertEqual("Descriptive validity: ...", self.review.validity_threats)
        with self.assertRaises(ValidationError):
            reviews.update_review(review=self.review, review_type="tertiary")
        overview = reviews.review_overview(self.review)
        self.assertEqual("mapping", overview["review_type"])
        self.assertEqual({"total": 0, "found": 0}, overview["test_set"])
