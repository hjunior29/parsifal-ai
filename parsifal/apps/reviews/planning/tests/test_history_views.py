from django.test import TestCase
from django.urls import reverse

from parsifal.apps.reviews.models import DataExtraction, Keyword, QualityQuestion, ReviewEvent
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    DataExtractionFieldFactory,
    DefaultSourceFactory,
    KeywordFactory,
    QualityAnswerFactory,
    QualityQuestionFactory,
    QuestionFactory,
    ReviewFactory,
    SelectionCriteriaFactory,
)


def planning(name):
    return reverse(f"reviews:planning:{name}")


class PlanningHistoryTest(TestCase):
    """What the web pages of Planning record in the History: the same as the services, as the user, through the web."""

    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory(objective="Why", population="workers")
        cls.author = cls.review.author

    def setUp(self):
        self.client.force_login(self.author)

    def post(self, name, data):
        response = self.client.post(planning(name), {"review-id": self.review.pk, **data})
        self.assertEqual(200, response.status_code, response.content)
        return response

    def events(self, since=0):
        return list(self.review.events.order_by("pk").filter(pk__gt=since).values_list("action", "summary"))

    def latest(self):
        return self.review.events.order_by("pk").last()

    def test_objective_and_picoc(self):
        self.post("save_objective", {"objective": "Why not"})
        picoc = {
            "population": "workers",
            "intervention": "smart glasses",
            "comparison": "",
            "outcome": "",
            "context": "",
        }
        self.post("save_picoc", picoc)
        self.post("save_picoc", picoc)  # nothing changes: nothing recorded
        self.assertEqual(
            [("change", "Changed the protocol (Objective)"), ("change", "Changed the protocol (Intervention)")],
            self.events(),
        )
        event = self.latest()
        self.assertEqual((self.author, ReviewEvent.WEB, False), (event.actor, event.via, event.amendment))
        self.assertEqual(
            [{"key": "intervention", "field": "Intervention", "before": "", "after": "smart glasses"}], event.changes
        )

    def test_an_amendment_once_studies_were_imported(self):
        ArticleFactory(review=self.review)
        self.post("save_objective", {"objective": "Why, really"})
        self.assertTrue(self.latest().amendment)

    def test_research_questions(self):
        self.post("save_question", {"question-id": "None", "description": "RQ1: how?"})
        question = self.review.research_questions.get()
        self.post("save_question", {"question-id": question.pk, "description": "RQ1: how, exactly?"})
        other = QuestionFactory(review=self.review, question="RQ2", order=1)
        self.post("save_question_order", {"orders": f"{question.pk}:1,{other.pk}:0"})
        self.post("remove_question", {"question-id": question.pk})
        self.assertEqual(
            [
                ("add", "Added the research question “RQ1: how?”"),
                ("change", "Changed the research question “RQ1: how, exactly?”"),
                ("change", "Reordered the research questions"),
                ("remove", "Removed the research question “RQ1: how, exactly?”"),
            ],
            self.events(),
        )
        reordered = self.review.events.get(summary="Reordered the research questions")
        self.assertEqual(["RQ2", "RQ1: how, exactly?"], reordered.items)

    def test_keywords(self):
        self.client.post(
            planning("add_keyword"),
            {
                "review-id": self.review.pk,
                "description": "glasses",
                "related_to": "I",
                "synonym-TOTAL_FORMS": "1",
                "synonym-INITIAL_FORMS": "0",
                "synonym-0-description": "eyewear",
            },
        )
        keyword = Keyword.objects.get(review=self.review, description="glasses")
        self.assertEqual("Added the keyword “glasses”", self.latest().summary)
        self.assertIn(
            {"key": "synonyms", "field": "Synonyms", "before": "", "after": "eyewear"}, self.latest().changes
        )
        synonym = keyword.synonyms.get()
        self.client.post(
            planning("edit_keyword"),
            {
                "review-id": self.review.pk,
                "keyword-id": keyword.pk,
                "description": "smart glasses",
                "related_to": "I",
                "synonym-TOTAL_FORMS": "2",
                "synonym-INITIAL_FORMS": "1",
                "synonym-0-id": synonym.pk,
                "synonym-0-description": "eyewear",
                "synonym-1-description": "head-mounted display",
            },
        )
        event = self.latest()
        self.assertEqual("Changed the keyword “smart glasses”", event.summary)
        self.assertEqual(
            [
                {"key": "description", "field": "Description", "before": "glasses", "after": "smart glasses"},
                {
                    "key": "synonyms",
                    "field": "Synonyms",
                    "before": "eyewear",
                    "after": "eyewear, head-mounted display",
                },
            ],
            event.changes,
        )
        self.post("remove_keyword", {"keyword-id": keyword.pk})
        self.assertEqual(("remove", "Removed the keyword “smart glasses”"), self.events()[-1])
        self.post("import_pico_keywords", {})
        self.assertEqual("Added 1 keyword from the PICOC", self.latest().summary)
        self.assertEqual(["workers (Population)"], self.latest().items)

    def test_search_string_sources_and_criteria(self):
        self.post("save_generic_search_string", {"search-string": "glasses AND work"})
        scopus = DefaultSourceFactory(name="Scopus")
        self.post("add_suggested_sources", {"source-id": [scopus.pk]})
        self.post("save_source", {"source-id": "", "name": "Our list", "url": ""})
        ArticleFactory(review=self.review, source=scopus, title="A study")
        self.post("remove_source_from_review", {"source-id": scopus.pk})
        self.post("add_criteria", {"criteria": "Not in English", "criteria-type": "E"})
        criteria = self.review.selectioncriteria_set.get()
        self.post("remove_criteria", {"criteria-ids": str(criteria.pk)})
        self.assertEqual(
            [
                ("change", "Changed the search string"),
                ("add", "Added the source “Scopus”"),
                ("add", "Added the source “Our list”"),
                ("remove", "Removed the source “Scopus” and its 1 study"),
                ("add", "Added the exclusion criterion “Not in English”"),
                ("remove", "Removed the exclusion criterion “Not in English”"),
            ],
            self.events(),
        )
        self.assertEqual(["A study"], self.review.events.get(summary__startswith="Removed the source").items)

    def test_quality_checklist(self):
        self.post("save_quality_assessment_question", {"quality-question-id": "None", "description": "Is it clear?"})
        question = QualityQuestion.objects.get(review=self.review)
        self.post("save_quality_assessment_question", {"quality-question-id": question.pk, "description": "Clear?"})
        self.post("remove_quality_assessment_question", {"quality-question-id": question.pk})
        self.post("add_suggested_answer", {})
        answer = self.review.qualityanswer_set.get(description="Yes")
        self.post(
            "save_quality_assessment_answer", {"quality-answer-id": answer.pk, "description": "Yes", "weight": "2"}
        )
        self.post("save_cutoff_score", {"cutoff-score": "1.5"})
        self.assertEqual(
            [
                ("add", "Added the quality assessment question “Is it clear?”"),
                ("change", "Changed the quality assessment question “Clear?”"),
                ("remove", "Removed the quality assessment question “Clear?”"),
                ("add", "Added the suggested quality assessment answers"),
                ("change", "Changed the quality assessment answer “Yes”"),
                ("change", "Changed the protocol (Quality assessment cutoff score)"),
            ],
            self.events(),
        )
        self.assertEqual(
            [{"key": "weight", "field": "Weight", "before": "1", "after": "2"}],
            self.review.events.get(summary="Changed the quality assessment answer “Yes”").changes,
        )

    def test_data_extraction_form(self):
        self.post(
            "save_data_extraction_field",
            {"field-id": "None", "description": "Country", "field-type": "O", "lookup-values": "Brazil\nPortugal"},
        )
        field = self.review.dataextractionfield_set.get()
        DataExtraction.objects.create(article=ArticleFactory(review=self.review), field=field)
        since = self.latest().pk
        self.post(
            "save_data_extraction_field",
            {"field-id": field.pk, "description": "Country", "field-type": "M", "lookup-values": "Brazil\nChile"},
        )
        other = DataExtractionFieldFactory(review=self.review, description="Year", field_type="I", order=1)
        self.post("save_data_extraction_field_order", {"orders": f"{field.pk}:1,{other.pk}:0"})
        self.post("remove_data_extraction_field", {"field-id": field.pk})
        added = self.review.events.get(summary="Added the data extraction field “Country”")
        self.assertIn({"key": "options", "field": "Options", "before": "", "after": "Brazil\nPortugal"}, added.changes)
        self.assertEqual(
            [
                ("change", "Changed the data extraction field “Country”"),
                ("change", "Reordered the data extraction fields"),
                ("remove", "Removed the data extraction field “Country”"),
            ],
            self.events(since),
        )
        changed = self.review.events.get(summary="Changed the data extraction field “Country”")
        self.assertEqual(
            [
                {"key": "field_type", "field": "Type", "before": "Select One Field", "after": "Select Many Field"},
                {"key": "options", "field": "Options", "before": "Portugal", "after": "Chile"},
                {"key": "values", "field": "Values extracted", "before": "1 study", "after": "cleared"},
            ],
            changed.changes,
        )

    def test_nothing_changes_nothing_is_recorded(self):
        question = QualityQuestionFactory(review=self.review, description="Clear?")
        answer = QualityAnswerFactory(review=self.review, description="Yes", weight=1.0)
        self.post("save_quality_assessment_question", {"quality-question-id": question.pk, "description": "Clear?"})
        self.post(
            "save_quality_assessment_answer", {"quality-answer-id": answer.pk, "description": "Yes", "weight": "1"}
        )
        keyword = KeywordFactory(review=self.review, description="glasses", related_to="I")
        self.client.post(
            planning("edit_keyword"),
            {
                "review-id": self.review.pk,
                "keyword-id": keyword.pk,
                "description": "glasses",
                "related_to": "I",
                "synonym-TOTAL_FORMS": "0",
                "synonym-INITIAL_FORMS": "0",
            },
        )
        SelectionCriteriaFactory(review=self.review)
        self.assertEqual([], self.events())
