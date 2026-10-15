import datetime

from django.test import TestCase

from parsifal.apps.core.exceptions import Conflict, NotFound, ValidationError
from parsifal.apps.reviews.models import ArticleClassification, Review, SearchSession
from parsifal.apps.reviews.services import classification, mapping, reviews, search, studies
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory, SourceFactory


class TestFacets(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory(review_type=Review.MAPPING)

    def test_templates_and_from_template(self):
        keys = [t["key"] for t in classification.list_templates()]
        self.assertIn("research_type", keys)
        facet = classification.add_facet_from_template(review=self.review, template="research_type")
        self.assertEqual(("fixed", "research_type", False), (facet.kind, facet.template, facet.multiple))
        self.assertEqual(6, facet.categories.count())
        self.assertEqual("Evaluation research", facet.categories.first().name)
        with self.assertRaises(Conflict):
            classification.add_facet_from_template(review=self.review, template="research_type")
        with self.assertRaises(ValidationError):
            classification.add_facet_from_template(review=self.review, template="nope")

    def test_custom_facet_and_categories(self):
        facet = classification.add_facet(
            review=self.review, name="Topic", categories=["Testing", "Requirements"], multiple=True
        )
        self.assertEqual("emerging", facet.kind)
        self.assertEqual(["Testing", "Requirements"], list(facet.categories.values_list("name", flat=True)))
        category = classification.add_category(review=self.review, facet_id=facet.pk, name="Maintenance")
        with self.assertRaises(Conflict):
            classification.add_category(review=self.review, facet_id=facet.pk, name="maintenance")
        classification.update_category(
            review=self.review, facet_id=facet.pk, category_id=category.pk, name="Evolution"
        )
        classification.reorder_categories(
            review=self.review,
            facet_id=facet.pk,
            ordered_ids=[category.pk] + list(facet.categories.exclude(pk=category.pk).values_list("pk", flat=True)),
        )
        self.assertEqual("Evolution", facet.categories.first().name)
        classification.remove_category(review=self.review, facet_id=facet.pk, category_id=category.pk)
        self.assertEqual(2, facet.categories.count())
        classification.update_facet(review=self.review, facet_id=facet.pk, name="Topics", kind="fixed")
        facet.refresh_from_db()
        self.assertEqual(("Topics", "fixed"), (facet.name, facet.kind))
        with self.assertRaises(ValidationError):
            classification.update_facet(review=self.review, facet_id=facet.pk, kind="weird")

    def test_scoping(self):
        other = ReviewFactory()
        foreign = classification.add_facet(review=other, name="X", categories=["a"])
        with self.assertRaises(NotFound):
            classification.add_category(review=self.review, facet_id=foreign.pk, name="b")
        with self.assertRaises(NotFound):
            classification.remove_facet(review=self.review, facet_id=foreign.pk)


class TestClassifyAndAggregate(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(review_type=Review.MAPPING, sources=[cls.source])
        cls.actor = cls.review.author
        cls.rtype = classification.add_facet_from_template(review=cls.review, template="research_type")
        cls.topic = classification.add_facet(
            review=cls.review, name="Topic", categories=["Testing", "Requirements"], multiple=True
        )
        cls.evaluation = cls.rtype.categories.get(name="Evaluation research")
        cls.proposal = cls.rtype.categories.get(name="Solution proposal")
        cls.testing = cls.topic.categories.get(name="Testing")
        cls.requirements = cls.topic.categories.get(name="Requirements")
        cls.a1 = ArticleFactory(review=cls.review, source=cls.source, status="A")
        cls.a2 = ArticleFactory(review=cls.review, source=cls.source, status="A")
        cls.rejected = ArticleFactory(review=cls.review, source=cls.source, status="R")

    def test_classify_single_and_multiple(self):
        rows = classification.classify(
            review=self.review,
            article_id=self.a1.pk,
            facet_id=self.rtype.pk,
            category_ids=[self.evaluation.pk],
            actor=self.actor,
            notes="clear eval",
        )
        by_facet = {row["facet"].pk: row for row in rows}
        self.assertEqual([self.evaluation], by_facet[self.rtype.pk]["categories"])
        self.assertEqual(
            ("clear eval", self.actor), (by_facet[self.rtype.pk]["notes"], by_facet[self.rtype.pk]["user"])
        )
        self.assertEqual([], by_facet[self.topic.pk]["categories"])

        with self.subTest(msg="single-choice replaces"):
            classification.classify(
                review=self.review, article_id=self.a1.pk, facet_id=self.rtype.pk, category_ids=[self.proposal.pk]
            )
            self.assertEqual(
                [self.proposal.pk],
                list(
                    ArticleClassification.objects.filter(article=self.a1, facet=self.rtype).values_list(
                        "category_id", flat=True
                    )
                ),
            )
        with self.subTest(msg="single-choice refuses two"):
            with self.assertRaises(ValidationError):
                classification.classify(
                    review=self.review,
                    article_id=self.a1.pk,
                    facet_id=self.rtype.pk,
                    category_ids=[self.proposal.pk, self.evaluation.pk],
                )
        with self.subTest(msg="multiple has set semantics"):
            classification.classify(
                review=self.review,
                article_id=self.a1.pk,
                facet_id=self.topic.pk,
                category_ids=[self.testing.pk, self.requirements.pk],
            )
            classification.classify(
                review=self.review, article_id=self.a1.pk, facet_id=self.topic.pk, category_ids=[self.requirements.pk]
            )
            self.assertEqual(
                [self.requirements.pk],
                list(
                    ArticleClassification.objects.filter(article=self.a1, facet=self.topic).values_list(
                        "category_id", flat=True
                    )
                ),
            )
        with self.subTest(msg="empty clears"):
            classification.classify(review=self.review, article_id=self.a1.pk, facet_id=self.topic.pk, category_ids=[])
            self.assertFalse(ArticleClassification.objects.filter(article=self.a1, facet=self.topic).exists())
        with self.subTest(msg="category must belong to facet"):
            with self.assertRaises(NotFound):
                classification.classify(
                    review=self.review,
                    article_id=self.a1.pk,
                    facet_id=self.topic.pk,
                    category_ids=[self.evaluation.pk],
                )

    def test_frequencies_and_matrix_use_final_selection(self):
        classification.classify(
            review=self.review, article_id=self.a1.pk, facet_id=self.rtype.pk, category_ids=[self.evaluation.pk]
        )
        classification.classify(
            review=self.review, article_id=self.a2.pk, facet_id=self.rtype.pk, category_ids=[self.evaluation.pk]
        )
        classification.classify(
            review=self.review, article_id=self.rejected.pk, facet_id=self.rtype.pk, category_ids=[self.proposal.pk]
        )
        classification.classify(
            review=self.review,
            article_id=self.a1.pk,
            facet_id=self.topic.pk,
            category_ids=[self.testing.pk, self.requirements.pk],
        )
        classification.classify(
            review=self.review, article_id=self.a2.pk, facet_id=self.topic.pk, category_ids=[self.testing.pk]
        )

        freq = classification.facet_frequencies(review=self.review, facet_id=self.rtype.pk)
        counts = {row["category"]: row["count"] for row in freq["categories"]}
        self.assertEqual((2, 2), (freq["total_articles"], freq["classified_articles"]))
        self.assertEqual((2, 0), (counts["Evaluation research"], counts["Solution proposal"]))

        matrix = classification.facet_matrix(
            review=self.review, row_facet_id=self.topic.pk, column_facet_id=self.rtype.pk
        )
        cells = {(c["row"], c["column"]): c["count"] for c in matrix["cells"]}
        self.assertEqual(2, cells[("Testing", "Evaluation research")])
        self.assertEqual(1, cells[("Requirements", "Evaluation research")])
        self.assertEqual(0, cells[("Testing", "Solution proposal")])
        self.assertEqual(len(self.topic.categories.all()) * len(self.rtype.categories.all()), len(matrix["cells"]))

    def test_update_facet_single_choice_guard(self):
        classification.classify(
            review=self.review,
            article_id=self.a1.pk,
            facet_id=self.topic.pk,
            category_ids=[self.testing.pk, self.requirements.pk],
        )
        with self.assertRaises(Conflict):
            classification.update_facet(review=self.review, facet_id=self.topic.pk, multiple=False)


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
        self.assertEqual(0, overview["classification_facets"])
