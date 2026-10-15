from django.test import TestCase

from parsifal.apps.core.exceptions import Conflict, NotFound, ValidationError
from parsifal.apps.reviews.models import Keyword, SearchSession, SelectionCriteria, Source
from parsifal.apps.reviews.services import protocol
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    DefaultSourceFactory,
    KeywordFactory,
    QuestionFactory,
    ReviewFactory,
    SelectionCriteriaFactory,
    SourceFactory,
)


class TestQuestions(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory()
        cls.other = ReviewFactory()

    def test_add_update_remove(self):
        q1 = protocol.add_question(review=self.review, description="What is X?")
        q2 = protocol.add_question(review=self.review, description="How is Y?")
        with self.subTest(msg="order appended"):
            self.assertEqual((0, 1), (q1.order, q2.order))
        protocol.update_question(review=self.review, question_id=q1.pk, description="What is Z?")
        q1.refresh_from_db()
        self.assertEqual("What is Z?", q1.question)
        protocol.remove_question(review=self.review, question_id=q2.pk)
        self.assertEqual(1, self.review.research_questions.count())

    def test_reorder(self):
        questions = [QuestionFactory(review=self.review) for _ in range(3)]
        protocol.reorder_questions(review=self.review, ordered_ids=[questions[2].pk, questions[0].pk, questions[1].pk])
        self.assertEqual(
            [questions[2].pk, questions[0].pk, questions[1].pk],
            list(self.review.research_questions.order_by("order").values_list("pk", flat=True)),
        )

    def test_scoping_and_validation(self):
        foreign = QuestionFactory(review=self.other)
        with self.assertRaises(NotFound):
            protocol.update_question(review=self.review, question_id=foreign.pk, description="x")
        with self.assertRaises(NotFound):
            protocol.reorder_questions(review=self.review, ordered_ids=[foreign.pk])
        with self.assertRaises(ValidationError):
            protocol.add_question(review=self.review, description="")
        with self.assertRaises(ValidationError):
            protocol.add_question(review=self.review, description="x" * 501)


class TestKeywordsAndSearchString(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory(
            population="software engineering, software development",
            intervention="large language models",
            comparison="",
            outcome="productivity",
        )

    def test_import_picoc_keywords_is_idempotent(self):
        created = protocol.import_picoc_keywords(review=self.review)
        self.assertEqual(
            {"software engineering", "software development", "large language models", "productivity"},
            {k.description for k in created},
        )
        self.assertEqual(Keyword.INTERVENTION, Keyword.objects.get(description="large language models").related_to)
        self.assertEqual([], protocol.import_picoc_keywords(review=self.review))

    def test_add_keyword_with_synonyms_and_generate(self):
        protocol.add_keyword(
            review=self.review, description="LLM", related_to=Keyword.INTERVENTION, synonyms=["GPT", " "]
        )
        protocol.add_keyword(review=self.review, description="developer", related_to=Keyword.POPULATION)
        self.assertEqual('("developer") AND ("LLM" OR "GPT")', protocol.generate_search_string(self.review))

    def test_update_keyword_replaces_synonyms(self):
        keyword = protocol.add_keyword(review=self.review, description="test", synonyms=["a", "b"])
        protocol.update_keyword(review=self.review, keyword_id=keyword.pk, description="testing", synonyms=["c"])
        keyword.refresh_from_db()
        self.assertEqual("testing", keyword.description)
        self.assertEqual(["c"], list(keyword.synonyms.values_list("description", flat=True)))

    def test_remove_keyword_removes_synonyms(self):
        keyword = protocol.add_keyword(review=self.review, description="test", synonyms=["a", "b"])
        protocol.remove_keyword(review=self.review, keyword_id=keyword.pk)
        self.assertFalse(Keyword.objects.filter(review=self.review).exists())

    def test_invalid_related_to_and_scoping(self):
        with self.assertRaises(ValidationError):
            protocol.add_keyword(review=self.review, description="x", related_to="Z")
        foreign = KeywordFactory()
        with self.assertRaises(NotFound):
            protocol.remove_keyword(review=self.review, keyword_id=foreign.pk)

    def test_generic_search_string_upsert(self):
        self.assertIsNone(protocol.get_generic_search_string(self.review))
        protocol.set_generic_search_string(review=self.review, search_string="a AND b")
        protocol.set_generic_search_string(review=self.review, search_string="a AND c")
        sessions = SearchSession.objects.filter(review=self.review, source=None)
        self.assertEqual(1, sessions.count())
        self.assertEqual("a AND c", sessions.get().search_string)


class TestSources(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.default = DefaultSourceFactory(name="IEEE Digital Library")
        cls.review = ReviewFactory()

    def test_attach_default_twice(self):
        protocol.attach_source(review=self.review, source_id=self.default.pk)
        with self.assertRaises(Conflict):
            protocol.attach_source(review=self.review, source_id=self.default.pk)

    def test_attach_requires_default(self):
        custom = SourceFactory()
        with self.assertRaises(NotFound):
            protocol.attach_source(review=self.review, source_id=custom.pk)

    def test_create_update_custom_source(self):
        source = protocol.create_source(review=self.review, name="My Library", url="mylib.example.org")
        self.assertEqual("http://mylib.example.org", source.url)
        self.assertIn(source, self.review.sources.all())
        protocol.update_source(review=self.review, source_id=source.pk, name="Renamed")
        source.refresh_from_db()
        self.assertEqual("Renamed", source.name)

    def test_default_source_cannot_be_edited(self):
        protocol.attach_source(review=self.review, source_id=self.default.pk)
        with self.assertRaises(ValidationError):
            protocol.update_source(review=self.review, source_id=self.default.pk, name="hacked")

    def test_detach_default_deletes_review_articles_only(self):
        protocol.attach_source(review=self.review, source_id=self.default.pk)
        mine = ArticleFactory(review=self.review, source=self.default)
        theirs = ArticleFactory(source=self.default)
        SearchSession.objects.create(review=self.review, source=self.default, search_string="q")
        protocol.detach_source(review=self.review, source_id=self.default.pk)
        with self.subTest(msg="default source kept"):
            self.assertTrue(Source.objects.filter(pk=self.default.pk).exists())
        with self.subTest(msg="review articles and search string deleted"):
            self.assertFalse(type(mine).objects.filter(pk=mine.pk).exists())
            self.assertFalse(SearchSession.objects.filter(review=self.review, source=self.default).exists())
        with self.subTest(msg="other review untouched"):
            self.assertTrue(type(theirs).objects.filter(pk=theirs.pk).exists())

    def test_detach_custom_deletes_source(self):
        source = protocol.create_source(review=self.review, name="Custom")
        protocol.detach_source(review=self.review, source_id=source.pk)
        self.assertFalse(Source.objects.filter(pk=source.pk).exists())


class TestCriteria(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory()

    def test_add_update_remove(self):
        criteria = protocol.add_criteria(review=self.review, description="Peer reviewed", criteria_type="I")
        protocol.update_criteria(review=self.review, criteria_id=criteria.pk, description="Peer-reviewed only")
        criteria.refresh_from_db()
        self.assertEqual(
            ("Peer-reviewed only", SelectionCriteria.INCLUSION), (criteria.description, criteria.criteria_type)
        )
        protocol.remove_criteria(review=self.review, criteria_id=criteria.pk)
        self.assertFalse(self.review.selectioncriteria_set.exists())

    def test_invalid_type_and_scoping(self):
        with self.assertRaises(ValidationError):
            protocol.add_criteria(review=self.review, description="x", criteria_type="Q")
        foreign = SelectionCriteriaFactory()
        with self.assertRaises(NotFound):
            protocol.remove_criteria(review=self.review, criteria_id=foreign.pk)
