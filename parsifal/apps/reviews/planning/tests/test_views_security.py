from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.models import (
    Article,
    DataExtractionField,
    Keyword,
    QualityAnswer,
    QualityQuestion,
    Question,
    SelectionCriteria,
    Source,
)
from parsifal.apps.reviews.tests.factories import (
    DataExtractionFieldFactory,
    DefaultSourceFactory,
    KeywordFactory,
    QualityAnswerFactory,
    QualityQuestionFactory,
    QuestionFactory,
    ReviewFactory,
    SelectionCriteriaFactory,
    SourceFactory,
)

# Every Planning endpoint that changes something: none of them may do it on a GET (no CSRF check there).
MUTATIONS = (
    "save_objective",
    "save_question",
    "save_question_order",
    "add_or_edit_question",
    "remove_question",
    "save_picoc",
    "import_pico_keywords",
    "remove_keyword",
    "save_generic_search_string",
    "save_source",
    "remove_source_from_review",
    "add_suggested_sources",
    "add_criteria",
    "save_inclusion_rule",
    "remove_criteria",
    "save_quality_assessment_question",
    "save_quality_assessment_question_order",
    "remove_quality_assessment_question",
    "save_quality_assessment_answer",
    "remove_quality_assessment_answer",
    "add_suggested_answer",
    "save_cutoff_score",
    "save_data_extraction_field",
    "save_data_extraction_field_order",
    "remove_data_extraction_field",
)


def url(name):
    return reverse(f"reviews:planning:{name}")


class PlanningSecurityTestCase(TestCase):
    """A member of one review (``mine``) aiming at the objects of a review they are not in (``theirs``)."""

    @classmethod
    def setUpTestData(cls):
        cls.member = UserFactory()
        cls.outsider = UserFactory()
        cls.mine = ReviewFactory(author=cls.member)
        cls.theirs = ReviewFactory(author=cls.outsider)
        cls.source = SourceFactory(name="Their library")
        cls.theirs.sources.add(cls.source)
        cls.article = Article.objects.create(review=cls.theirs, source=cls.source, title="Their study")
        cls.question = QuestionFactory(review=cls.theirs, question="Their question", order=1)
        cls.keyword = KeywordFactory(review=cls.theirs, description="their keyword")
        cls.criteria = SelectionCriteriaFactory(review=cls.theirs, description="Their criterion", criteria_type="E")
        cls.quality_question = QualityQuestionFactory(review=cls.theirs, description="Their QA question", order=1)
        cls.quality_answer = QualityAnswerFactory(review=cls.theirs, description="Their answer", weight=1.0)
        cls.field = DataExtractionFieldFactory(review=cls.theirs, description="Their field", field_type="S", order=1)

    def setUp(self):
        self.client.force_login(self.member)

    def post(self, name, data=None, review=None):
        return self.client.post(url(name), {"review-id": (review or self.mine).pk, **(data or {})})

    def assertRefused(self, response):
        self.assertIn(response.status_code, (400, 403, 404))


class TestStateChangingGets(PlanningSecurityTestCase):
    def test_no_mutation_answers_a_get(self):
        for name in MUTATIONS:
            with self.subTest(name):
                response = self.client.get(url(name), {"review-id": self.mine.pk})
                self.assertEqual(405, response.status_code)

    def test_a_get_does_not_remove_a_source(self):
        source = SourceFactory(name="My library")
        self.mine.sources.add(source)
        self.client.get(url("remove_source_from_review"), {"review-id": self.mine.pk, "source-id": source.pk})
        self.assertTrue(Source.objects.filter(pk=source.pk).exists())


class TestTheReviewIsNamedOnce(PlanningSecurityTestCase):
    def test_a_post_naming_another_review_in_the_query_string_is_refused(self):
        response = self.client.post(
            f"{url('remove_criteria')}?review-id={self.theirs.pk}",
            {"review-id": self.mine.pk, "criteria-ids": self.criteria.pk},
        )
        self.assertEqual(400, response.status_code)
        self.assertTrue(SelectionCriteria.objects.filter(pk=self.criteria.pk).exists())

    def test_the_same_review_in_both_places_is_fine(self):
        criteria = SelectionCriteriaFactory(review=self.mine, description="Mine", criteria_type="E")
        response = self.client.post(
            f"{url('remove_criteria')}?review-id={self.mine.pk}",
            {"review-id": self.mine.pk, "criteria-ids": criteria.pk},
        )
        self.assertEqual(200, response.status_code)
        self.assertFalse(SelectionCriteria.objects.filter(pk=criteria.pk).exists())

    def test_an_unknown_review_is_not_found(self):
        response = self.client.post(url("save_cutoff_score"), {"review-id": 999999, "cutoff-score": "1"})
        self.assertEqual(404, response.status_code)
        response = self.client.post(url("save_cutoff_score"), {"review-id": "abc", "cutoff-score": "1"})
        self.assertEqual(404, response.status_code)

    def test_someone_outside_the_review_is_forbidden(self):
        response = self.post("save_cutoff_score", {"cutoff-score": "3"}, review=self.theirs)
        self.assertEqual(403, response.status_code)
        self.theirs.refresh_from_db()
        self.assertNotEqual(3, self.theirs.quality_assessment_cutoff_score)


class TestAnotherReviewsObjects(PlanningSecurityTestCase):
    def test_research_questions(self):
        self.assertRefused(self.post("save_question", {"question-id": self.question.pk, "description": "Mine now"}))
        self.assertRefused(self.post("save_question_order", {"orders": f"{self.question.pk}:7"}))
        self.assertRefused(self.post("add_or_edit_question", {"question-id": self.question.pk}))
        self.assertRefused(self.post("remove_question", {"question-id": self.question.pk}))
        question = Question.objects.get(pk=self.question.pk)
        self.assertEqual(
            ("Their question", 1, self.theirs.pk), (question.question, question.order, question.review_id)
        )

    def test_keywords(self):
        self.assertRefused(self.post("remove_keyword", {"keyword-id": self.keyword.pk}))
        response = self.client.get(url("edit_keyword"), {"review-id": self.mine.pk, "keyword-id": self.keyword.pk})
        self.assertEqual(404, response.status_code)
        self.assertTrue(Keyword.objects.filter(pk=self.keyword.pk).exists())

    def test_sources(self):
        self.assertRefused(self.post("save_source", {"source-id": self.source.pk, "name": "Mine", "url": ""}))
        self.assertRefused(self.post("remove_source_from_review", {"source-id": self.source.pk}))
        self.assertRefused(self.post("add_suggested_sources", {"source-id": self.source.pk}))
        self.source.refresh_from_db()
        self.assertEqual("Their library", self.source.name)
        self.assertTrue(Article.objects.filter(pk=self.article.pk).exists())
        self.assertFalse(self.mine.sources.filter(pk=self.source.pk).exists())

    def test_a_default_source_cannot_be_edited(self):
        default = DefaultSourceFactory(name="Shared library")
        self.mine.sources.add(default)
        response = self.post("save_source", {"source-id": default.pk, "name": "<script>x</script>", "url": ""})
        self.assertEqual(400, response.status_code)
        default.refresh_from_db()
        self.assertEqual("Shared library", default.name)

    def test_selection_criteria(self):
        self.assertRefused(self.post("remove_criteria", {"criteria-ids": self.criteria.pk}))
        self.assertTrue(SelectionCriteria.objects.filter(pk=self.criteria.pk).exists())

    def test_quality_questions(self):
        pk = self.quality_question.pk
        response = self.client.get(
            url("edit_quality_assessment_question"), {"review-id": self.mine.pk, "quality-question-id": pk}
        )
        self.assertRefused(response)
        data = {"quality-question-id": pk, "description": "Mine now"}
        self.assertRefused(self.post("save_quality_assessment_question", data))
        self.assertRefused(self.post("save_quality_assessment_question_order", {"orders": f"{pk}:7"}))
        self.assertRefused(self.post("remove_quality_assessment_question", {"quality-question-id": pk}))
        question = QualityQuestion.objects.get(pk=pk)
        self.assertEqual(
            ("Their QA question", 1, self.theirs.pk), (question.description, question.order, question.review_id)
        )

    def test_quality_answers(self):
        pk = self.quality_answer.pk
        response = self.client.get(
            url("edit_quality_assessment_answer"), {"review-id": self.mine.pk, "quality-answer-id": pk}
        )
        self.assertRefused(response)
        data = {"quality-answer-id": pk, "description": "Mine now", "weight": "9"}
        self.assertRefused(self.post("save_quality_assessment_answer", data))
        self.assertRefused(self.post("remove_quality_assessment_answer", {"quality-answer-id": pk}))
        answer = QualityAnswer.objects.get(pk=pk)
        self.assertEqual(("Their answer", 1.0, self.theirs.pk), (answer.description, answer.weight, answer.review_id))

    def test_data_extraction_fields(self):
        pk = self.field.pk
        response = self.client.get(url("edit_data_extraction_field"), {"review-id": self.mine.pk, "field-id": pk})
        self.assertEqual(404, response.status_code)
        data = {"field-id": pk, "description": "Mine now", "field-type": "F", "lookup-values": ""}
        self.assertRefused(self.post("save_data_extraction_field", data))
        self.assertRefused(self.post("save_data_extraction_field_order", {"orders": f"{pk}:7"}))
        self.assertRefused(self.post("remove_data_extraction_field", {"field-id": pk}))
        field = DataExtractionField.objects.get(pk=pk)
        self.assertEqual(
            ("Their field", "S", 1, self.theirs.pk),
            (field.description, field.field_type, field.order, field.review_id),
        )


class TestOwnObjects(PlanningSecurityTestCase):
    """The same endpoints still work on the review's own objects."""

    def test_sources(self):
        response = self.post("save_source", {"source-id": "", "name": "My library", "url": "example.com"})
        self.assertEqual(200, response.status_code)
        source = self.mine.sources.get(name="My library")
        article = Article.objects.create(review=self.mine, source=source, title="My study")
        response = self.post("save_source", {"source-id": source.pk, "name": "My <library>", "url": ""})
        self.assertContains(response, "My &lt;library&gt;")
        response = self.post("remove_source_from_review", {"source-id": source.pk})
        self.assertEqual(200, response.status_code)
        self.assertFalse(Source.objects.filter(pk=source.pk).exists())
        self.assertFalse(Article.objects.filter(pk=article.pk).exists())

    def test_suggested_sources_are_escaped_and_added(self):
        default = DefaultSourceFactory(name="<b>Shared</b>", url="https://shared.example.com/?a=1&b=2")
        response = self.client.get(url("suggested_sources"), {"review-id": self.mine.pk})
        self.assertContains(response, "&lt;b&gt;Shared&lt;/b&gt;")
        self.assertNotContains(response, "<b>Shared</b>")
        self.assertContains(response, "a=1&amp;b=2")
        response = self.post("add_suggested_sources", {"source-id": default.pk})
        self.assertEqual(200, response.status_code)
        self.assertTrue(self.mine.sources.filter(pk=default.pk).exists())

    def test_questions_and_order(self):
        first = QuestionFactory(review=self.mine, question="First", order=0)
        second = QuestionFactory(review=self.mine, question="Second", order=1)
        response = self.post("save_question", {"question-id": first.pk, "description": "First, edited"})
        self.assertContains(response, "First, edited")
        response = self.post("save_question", {"question-id": "None", "description": "Third"})
        self.assertContains(response, "Third")
        response = self.post("save_question_order", {"orders": f"{second.pk}:0,{first.pk}:1,None:2"})
        self.assertEqual(200, response.status_code)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((0, 1), (second.order, first.order))
        self.assertEqual(200, self.post("remove_question", {"question-id": second.pk}).status_code)
        self.assertFalse(Question.objects.filter(pk=second.pk).exists())

    def test_keywords(self):
        self.mine.population = "teachers, students"
        self.mine.save()
        response = self.post("import_pico_keywords")
        self.assertContains(response, "teachers")
        keyword = self.mine.keywords.get(description="students")
        KeywordFactory(review=self.mine, description="pupils", synonym_of=keyword)
        self.assertEqual(200, self.post("remove_keyword", {"keyword-id": keyword.pk}).status_code)
        self.assertFalse(self.mine.keywords.filter(description__in=("students", "pupils")).exists())

    def test_criteria(self):
        response = self.post("add_criteria", {"criteria": "Not in English", "criteria-type": "E"})
        self.assertEqual(200, response.status_code)
        criteria = self.mine.selectioncriteria_set.get()
        self.assertEqual(200, self.post("remove_criteria", {"criteria-ids": criteria.pk}).status_code)
        self.assertFalse(self.mine.selectioncriteria_set.exists())

    def test_quality_checklist(self):
        response = self.post("add_suggested_answer")
        self.assertEqual(200, response.status_code)
        answer = self.mine.qualityanswer_set.order_by("-weight").first()
        self.assertEqual(
            200, self.post("remove_quality_assessment_answer", {"quality-answer-id": answer.pk}).status_code
        )
        self.assertFalse(QualityAnswer.objects.filter(pk=answer.pk).exists())
        response = self.post("save_quality_assessment_question", {"quality-question-id": "None", "description": "Q?"})
        self.assertEqual(200, response.status_code)
        question = self.mine.qualityquestion_set.get()
        self.assertEqual(
            200, self.post("save_quality_assessment_question_order", {"orders": f"{question.pk}:3"}).status_code
        )
        question.refresh_from_db()
        self.assertEqual(3, question.order)
        self.assertEqual(
            200, self.post("remove_quality_assessment_question", {"quality-question-id": question.pk}).status_code
        )
        self.assertFalse(self.mine.qualityquestion_set.exists())
        self.assertEqual(200, self.post("save_cutoff_score", {"cutoff-score": "1.5"}).status_code)
        self.mine.refresh_from_db()
        self.assertEqual(1.5, self.mine.quality_assessment_cutoff_score)

    def test_data_extraction_fields(self):
        data = {"field-id": "None", "description": "Country", "field-type": "O", "lookup-values": "BR\nPT"}
        self.assertEqual(200, self.post("save_data_extraction_field", data).status_code)
        field = self.mine.dataextractionfield_set.get()
        self.assertEqual(["BR", "PT"], sorted(field.get_select_values().values_list("value", flat=True)))
        self.assertEqual(200, self.post("save_data_extraction_field_order", {"orders": f"{field.pk}:4"}).status_code)
        field.refresh_from_db()
        self.assertEqual(4, field.order)
        self.assertEqual(200, self.post("remove_data_extraction_field", {"field-id": field.pk}).status_code)
        self.assertFalse(self.mine.dataextractionfield_set.exists())
