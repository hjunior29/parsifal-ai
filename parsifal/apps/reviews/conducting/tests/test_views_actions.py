from django.test import TestCase
from django.urls import reverse

from parsifal.apps.reviews.models import Article, DataExtraction, DataExtractionField, QualityAssessment
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    DataExtractionFieldFactory,
    DataExtractionLookupFactory,
    QualityAnswerFactory,
    QualityQuestionFactory,
    ReviewFactory,
    SourceFactory,
)


class ConductingActionsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(sources=[cls.source])
        cls.other_review = ReviewFactory()
        cls.foreign_article = ArticleFactory(review=cls.other_review)

    def setUp(self):
        self.client.force_login(self.review.author)

    def post(self, name, **data):
        data.setdefault("review-id", self.review.pk)
        return self.client.post(reverse(f"reviews:conducting:{name}"), data)


class TestBulkActions(ConductingActionsTestCase):
    def test_accept_and_remove(self):
        a1, a2 = ArticleFactory.create_batch(2, review=self.review, source=self.source)
        response = self.post("multiple_articles_action_accept", article_ids=f"{a1.pk}|{a2.pk}")
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {Article.ACCEPTED}, set(Article.objects.filter(review=self.review).values_list("status", flat=True))
        )
        self.assertEqual(self.review.author, Article.objects.get(pk=a1.pk).updated_by)

        response = self.post("multiple_articles_action_remove", article_ids=f"{a1.pk}|")
        self.assertEqual(200, response.status_code)
        self.assertFalse(Article.objects.filter(pk=a1.pk).exists())

    def test_foreign_article_rejected(self):
        response = self.post("multiple_articles_action_reject", article_ids=str(self.foreign_article.pk))
        self.assertEqual(400, response.status_code)
        self.foreign_article.refresh_from_db()
        self.assertEqual(Article.UNCLASSIFIED, self.foreign_article.status)

    def test_every_study_of_the_list(self):
        other = SourceFactory()
        self.review.sources.add(other)
        match = [ArticleFactory(review=self.review, source=self.source, title=f"Agents {n}") for n in range(3)]
        accepted = ArticleFactory(review=self.review, source=self.source, title="Agents accepted", status="A")
        elsewhere = ArticleFactory(review=self.review, source=other, title="Agents elsewhere")
        unmatched = ArticleFactory(review=self.review, source=self.source, title="Something else")
        filters = {"select-all": "filter", "source-id": self.source.pk, "status": "U", "q": "agents", "starred": ""}
        response = self.post("multiple_articles_action_reject", article_ids="", **filters)
        self.assertEqual(200, response.status_code)
        statuses = dict(self.review.article_set.values_list("pk", "status"))
        self.assertEqual(["R", "R", "R"], [statuses[a.pk] for a in match])
        self.assertEqual(("A", "U", "U"), (statuses[accepted.pk], statuses[elsewhere.pk], statuses[unmatched.pk]))
        self.assertEqual({self.review.author.pk}, {a.updated_by_id for a in Article.objects.filter(status="R")})

        response = self.post(
            "multiple_articles_action_remove",
            article_ids="",
            **{"select-all": "filter", "status": "ALL", "q": "agents"},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual([unmatched.pk], list(self.review.article_set.values_list("pk", flat=True)))

    def test_every_study_of_another_reviews_source_is_not_found(self):
        source = self.other_review.sources.create(name="Theirs")
        response = self.post(
            "multiple_articles_action_accept", article_ids="", **{"select-all": "filter", "source-id": source.pk}
        )
        self.assertEqual(404, response.status_code)

    def test_a_get_changes_nothing(self):
        article = ArticleFactory(review=self.review, source=self.source)
        url = reverse("reviews:conducting:multiple_articles_action_accept")
        response = self.client.get(url, {"review-id": self.review.pk, "article_ids": article.pk})
        self.assertEqual(405, response.status_code)
        article.refresh_from_db()
        self.assertEqual(Article.UNCLASSIFIED, article.status)


class TestQualityAssessmentView(ConductingActionsTestCase):
    def test_save_quality_assessment_returns_score(self):
        article = ArticleFactory(review=self.review, source=self.source, status="A")
        question = QualityQuestionFactory(review=self.review)
        answer = QualityAnswerFactory(review=self.review, weight=0.5)
        response = self.post(
            "save_quality_assessment", **{"article-id": article.pk, "question-id": question.pk, "answer-id": answer.pk}
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("0.5", response.content.decode())
        self.assertEqual(self.review.author, QualityAssessment.objects.get(article=article, question=question).user)

    def test_save_quality_assessment_without_answer_clears_it(self):
        article = ArticleFactory(review=self.review, source=self.source, status="A")
        question, other = QualityQuestionFactory.create_batch(2, review=self.review)
        answer = QualityAnswerFactory(review=self.review, weight=1.0)
        for each in (question, other):
            self.post(
                "save_quality_assessment", **{"article-id": article.pk, "question-id": each.pk, "answer-id": answer.pk}
            )
        response = self.post(
            "save_quality_assessment", **{"article-id": article.pk, "question-id": question.pk, "answer-id": ""}
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("1.0", response.content.decode())
        self.assertFalse(QualityAssessment.objects.filter(article=article, question=question).exists())
        self.assertTrue(QualityAssessment.objects.filter(article=article, question=other).exists())

    def test_save_quality_assessment_foreign_question(self):
        article = ArticleFactory(review=self.review, source=self.source, status="A")
        question = QualityQuestionFactory(review=self.other_review)
        answer = QualityAnswerFactory(review=self.review)
        response = self.post(
            "save_quality_assessment", **{"article-id": article.pk, "question-id": question.pk, "answer-id": answer.pk}
        )
        self.assertEqual(400, response.status_code)
        self.assertFalse(QualityAssessment.objects.exists())


class TestDataExtractionViews(ConductingActionsTestCase):
    def test_save_scalar_and_toggle_many(self):
        article = ArticleFactory(review=self.review, source=self.source, status="A")
        text = DataExtractionFieldFactory(review=self.review)
        many = DataExtractionFieldFactory(review=self.review, field_type=DataExtractionField.SELECT_MANY_FIELD)
        lookup = DataExtractionLookupFactory(field=many)

        response = self.post(
            "save_data_extraction", **{"article-id": article.pk, "field-id": text.pk, "value": " hi "}
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("hi", DataExtraction.objects.get(article=article, field=text).value)

        for expected in (1, 0):
            self.post("save_data_extraction", **{"article-id": article.pk, "field-id": many.pk, "value": lookup.pk})
            self.assertEqual(expected, DataExtraction.objects.get(article=article, field=many).select_values.count())

    def test_invalid_value_returns_message(self):
        article = ArticleFactory(review=self.review, source=self.source, status="A")
        number = DataExtractionFieldFactory(review=self.review, field_type=DataExtractionField.INTEGER_FIELD)
        response = self.post(
            "save_data_extraction", **{"article-id": article.pk, "field-id": number.pk, "value": "abc"}
        )
        self.assertEqual(400, response.status_code)
        self.assertIn("Expected value: integer number", response.content.decode())

    def test_mark_done(self):
        article = ArticleFactory(review=self.review, source=self.source, status="A")
        self.post("save_data_extraction_status", **{"article-id": article.pk, "action": "mark_as_done"})
        article.refresh_from_db()
        self.assertTrue(article.finished_data_extraction)
        response = self.post(
            "save_data_extraction_status", **{"article-id": self.foreign_article.pk, "action": "mark_as_done"}
        )
        self.assertEqual(400, response.status_code)


class TestDuplicatesViews(ConductingActionsTestCase):
    def test_resolve_all_and_one(self):
        a1 = ArticleFactory(review=self.review, source=self.source, title="Same Title")
        a2 = ArticleFactory(review=self.review, source=self.source, title="same title")
        b1 = ArticleFactory(review=self.review, source=self.source, title="Other")
        b2 = ArticleFactory(review=self.review, source=self.source, title="other")

        response = self.post("resolve_duplicated", **{"article-id": b2.pk})
        self.assertEqual(200, response.status_code)
        b2.refresh_from_db()
        self.assertEqual(Article.DUPLICATED, b2.status)

        response = self.post("resolve_all")
        self.assertEqual(str(a2.pk), response.content.decode())
        a1.refresh_from_db()
        b1.refresh_from_db()
        self.assertEqual((Article.UNCLASSIFIED, Article.UNCLASSIFIED), (a1.status, b1.status))

    def test_find_duplicates_partial(self):
        ArticleFactory(review=self.review, source=self.source, title="Dup")
        ArticleFactory(review=self.review, source=self.source, title="dup")
        response = self.client.get(reverse("reviews:conducting:find_duplicates"), {"review-id": self.review.pk})
        self.assertEqual(200, response.status_code)
        self.assertContains(response, "Dup")


class TestExports(ConductingActionsTestCase):
    def test_export_results_and_extraction(self):
        article = ArticleFactory(review=self.review, source=self.source, status="A", title="Exported")
        field = DataExtractionFieldFactory(review=self.review, description="Notes")
        DataExtraction.objects.create(article=article, field=field, value="note")

        response = self.post("export_results")
        with self.subTest(msg="articles.xls"):
            self.assertEqual(200, response.status_code)
            self.assertEqual("attachment; filename=articles.xls", response["Content-Disposition"])
            self.assertGreater(len(response.content), 0)

        response = self.post("export_data_extraction")
        with self.subTest(msg="data_extraction.xls"):
            self.assertEqual(200, response.status_code)
            self.assertEqual("attachment; filename=data_extraction.xls", response["Content-Disposition"])
            self.assertGreater(len(response.content), 0)
