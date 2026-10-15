from pathlib import Path

from django.test import TestCase

from parsifal.apps.core.exceptions import NotFound, ValidationError
from parsifal.apps.reviews.models import Article
from parsifal.apps.reviews.services import studies
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    ReviewFactory,
    SelectionCriteriaFactory,
    SourceFactory,
)

DATA = Path(__file__).resolve().parent.parent / "data"


class TestImportBibtex(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(sources=[cls.source])
        cls.actor = cls.review.author

    def test_scopus_export_mapping(self):
        result = studies.import_bibtex(
            review=self.review,
            source_id=self.source.pk,
            content=(DATA / "scopus_sample.bib").read_text(),
            actor=self.actor,
        )
        with self.subTest(msg="Test counts"):
            self.assertEqual((2, 0), (result.imported, result.failed))
            self.assertEqual([], result.warnings)

        article = Article.objects.get(review=self.review, bibtex_key="Smith2020")
        expected = {
            "title": "Large language models for systematic literature reviews: a mapping study",
            "author": "Smith, J. and Doe, A.",
            "journal": "Information and Software Technology",
            "year": "2020",
            "year_int": 2020,
            "volume": "128",
            "pages": "106-118",
            "doi": "10.1016/j.infsof.2020.106118",
            "document_type": "Article",
            "url": "https://www.scopus.com/inward/record.uri?eid=2-s2.0-0000000000",
            "author_keywords": "Systematic literature review; Large language models; Mapping study",
            "keywords": "Software engineering; Reviews",
            "publisher": "Elsevier B.V.",
            "issn": "09505849",
            "language": "English",
            "note": "cited By 12",
            "status": Article.UNCLASSIFIED,
        }
        for field, value in expected.items():
            with self.subTest(field=field):
                self.assertEqual(value, getattr(article, field))

        with self.subTest(msg="Test provenance"):
            self.assertEqual(self.source, article.source)
            self.assertEqual(self.actor, article.created_by)

    def test_ieee_export_bytes_and_url_alias(self):
        result = studies.import_bibtex(
            review=self.review, source_id=self.source.pk, content=(DATA / "ieee_sample.bib").read_bytes()
        )
        self.assertEqual(2, result.imported)
        article = Article.objects.get(review=self.review, bibtex_key="8812345")
        with self.subTest(msg="Test keywords alias"):
            self.assertEqual("Systematic mapping;Tools;Software engineering", article.keywords)
        with self.subTest(msg="Test url alias"):
            self.assertEqual(
                "https://ieeexplore.ieee.org/document/0000002",
                Article.objects.get(review=self.review, bibtex_key="Duplicate2018").url,
            )

    def test_truncation_is_reported(self):
        content = "@article{long,\n title={%s},\n year={2021}\n}" % ("x" * 1200)
        result = studies.import_bibtex(review=self.review, source_id=self.source.pk, content=content)
        article = Article.objects.get(review=self.review, bibtex_key="long")
        self.assertEqual(1000, len(article.title))
        self.assertEqual(["long: title truncated to 1000 characters."], result.warnings)

    def test_source_must_belong_to_review(self):
        other_source = SourceFactory()
        with self.assertRaises(NotFound):
            studies.import_bibtex(review=self.review, source_id=other_source.pk, content="@article{a, title={A}}")

    def test_empty_content(self):
        with self.assertRaises(ValidationError):
            studies.import_bibtex(review=self.review, source_id=self.source.pk, content="   ")

    def test_year_parsing(self):
        for raw, expected in (("2020", 2020), ("c. 1999", 1999), ("n.d.", None), ("", None), (None, None)):
            with self.subTest(raw=raw):
                self.assertEqual(expected, Article.parse_year(raw))


class TestArticleCrud(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(sources=[cls.source])
        cls.actor = cls.review.author
        cls.criteria = SelectionCriteriaFactory(review=cls.review)
        cls.other_review = ReviewFactory()
        cls.foreign_article = ArticleFactory(review=cls.other_review)

    def test_create_and_update(self):
        article = studies.create_article(
            review=self.review, source_id=self.source.pk, actor=self.actor, title="Manual entry", year="2022"
        )
        with self.subTest(msg="Test created"):
            self.assertEqual("Manual entry", article.title)
            self.assertEqual(2022, article.year_int)
            self.assertEqual(self.actor, article.created_by)

        updated = studies.update_article(
            review=self.review,
            article_id=article.pk,
            actor=self.actor,
            status=Article.ACCEPTED,
            selection_criteria_id=self.criteria.pk,
            comments="relevant",
        )
        with self.subTest(msg="Test updated"):
            self.assertEqual(Article.ACCEPTED, updated.status)
            self.assertEqual(self.criteria, updated.selection_criteria)
            self.assertEqual("relevant", updated.comments)

    def test_unknown_field_and_too_long(self):
        with self.assertRaises(ValidationError):
            studies.create_article(review=self.review, source_id=self.source.pk, bogus="x")
        with self.assertRaises(ValidationError):
            studies.create_article(review=self.review, source_id=self.source.pk, doi="x" * 51)

    def test_invalid_status(self):
        article = ArticleFactory(review=self.review, source=self.source)
        with self.assertRaises(ValidationError):
            studies.update_article(review=self.review, article_id=article.pk, status="X")

    def test_scoping(self):
        with self.subTest(msg="update article of another review"):
            with self.assertRaises(NotFound):
                studies.update_article(review=self.review, article_id=self.foreign_article.pk, title="hack")
        with self.subTest(msg="criteria of another review"):
            article = ArticleFactory(review=self.review, source=self.source)
            foreign_criteria = SelectionCriteriaFactory(review=self.other_review)
            with self.assertRaises(NotFound):
                studies.update_article(
                    review=self.review, article_id=article.pk, selection_criteria_id=foreign_criteria.pk
                )
        with self.subTest(msg="delete across reviews is refused entirely"):
            article = ArticleFactory(review=self.review, source=self.source)
            with self.assertRaises(NotFound):
                studies.delete_articles(review=self.review, article_ids=[article.pk, self.foreign_article.pk])
            self.assertTrue(Article.objects.filter(pk=article.pk).exists())

    def test_set_status_bulk(self):
        articles = ArticleFactory.create_batch(3, review=self.review, source=self.source)
        count = studies.set_status(
            review=self.review,
            article_ids=[a.pk for a in articles[:2]],
            status=Article.REJECTED,
            selection_criteria_id=self.criteria.pk,
            comments="out of scope",
            actor=self.actor,
        )
        self.assertEqual(2, count)
        statuses = list(
            Article.objects.filter(pk__in=[a.pk for a in articles]).order_by("pk").values_list("status", flat=True)
        )
        self.assertEqual([Article.REJECTED, Article.REJECTED, Article.UNCLASSIFIED], statuses)
        rejected = Article.objects.get(pk=articles[0].pk)
        self.assertEqual(
            (self.criteria, "out of scope", self.actor),
            (rejected.selection_criteria, rejected.comments, rejected.updated_by),
        )

    def test_list_articles_filters(self):
        other_source = SourceFactory()
        self.review.sources.add(other_source)
        ArticleFactory(review=self.review, source=self.source, title="Alpha study", status=Article.ACCEPTED)
        ArticleFactory(review=self.review, source=other_source, title="Beta study", status=Article.REJECTED)
        with self.subTest(msg="by source"):
            self.assertEqual(1, studies.list_articles(self.review, source_id=other_source.pk).count())
        with self.subTest(msg="by status"):
            self.assertEqual("Alpha study", studies.list_articles(self.review, status="A").get().title)
        with self.subTest(msg="by query"):
            self.assertEqual("Beta study", studies.list_articles(self.review, query="beta").get().title)


class TestDuplicates(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(sources=[cls.source])
        cls.a1 = ArticleFactory(review=cls.review, source=cls.source, title="Tool Support for Mapping")
        cls.a2 = ArticleFactory(review=cls.review, source=cls.source, title="tool support for mapping")
        cls.a3 = ArticleFactory(review=cls.review, source=cls.source, title="Tool support for mapping!")
        cls.unique = ArticleFactory(review=cls.review, source=cls.source, title="Something else")

    def test_find_duplicates_groups_by_slug(self):
        groups = studies.find_duplicates(self.review)
        self.assertEqual(1, len(groups))
        self.assertEqual([self.a1.pk, self.a2.pk, self.a3.pk], [a.pk for a in groups[0]])

    def test_resolve_all_keeps_oldest(self):
        marked = studies.resolve_duplicates(review=self.review)
        self.assertEqual({self.a2.pk, self.a3.pk}, {a.pk for a in marked})
        self.a1.refresh_from_db()
        self.assertEqual(Article.UNCLASSIFIED, self.a1.status)
        self.assertEqual([], studies.find_duplicates(self.review))

    def test_resolve_specific(self):
        studies.resolve_duplicates(review=self.review, article_ids=[self.a3.pk])
        self.a3.refresh_from_db()
        self.assertEqual(Article.DUPLICATED, self.a3.status)
        self.assertEqual(1, len(studies.find_duplicates(self.review)))

    def test_resolve_foreign_article(self):
        foreign = ArticleFactory()
        with self.assertRaises(NotFound):
            studies.resolve_duplicates(review=self.review, article_ids=[foreign.pk])
