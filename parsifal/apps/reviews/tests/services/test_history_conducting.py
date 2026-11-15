from django.core.files.base import ContentFile
from django.test import TestCase

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.tests.files import PDF, TemporaryFilesMixin
from parsifal.apps.reviews.models import Article, ClassificationFacet, ReviewEvent, StudyDecision
from parsifal.apps.reviews.services import (
    ai_runs,
    analytics,
    classification,
    decisions,
    extraction,
    full_texts,
    history,
    mapping,
    quality,
    search,
    studies,
)
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    DataExtractionFieldFactory,
    DataExtractionLookupFactory,
    QualityAnswerFactory,
    QualityQuestionFactory,
    ReviewFactory,
    SelectionCriteriaFactory,
    SourceFactory,
)
from parsifal.apps.reviews.tests.services.test_ai_screening import EXCLUDE_E2, KEEP, AiScreeningTestCase


class HistoryTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = UserFactory(username="owner")
        cls.colleague = UserFactory(username="colleague")
        cls.scopus = SourceFactory(name="Scopus")
        cls.review = ReviewFactory(author=cls.owner, co_authors=[cls.colleague], sources=[cls.scopus])

    def events(self, **filters):
        return list(self.review.events.filter(**filters).order_by("pk").values_list("area", "action", "summary"))

    def latest(self):
        return self.review.events.order_by("pk").last()


class TestSearchAndStudies(TemporaryFilesMixin, HistoryTestCase):
    def test_search(self):
        search.set_source_search_string(review=self.review, source_id=self.scopus.pk, search_string="a AND b")
        search.set_source_search_string(review=self.review, source_id=self.scopus.pk, search_string="a AND c")
        search.update_source_search(review=self.review, source_id=self.scopus.pk, searched_at="2026-10-01")
        search.update_source_search(review=self.review, source_id=self.scopus.pk, searched_at="2026-10-01")
        search.remove_source_search_string(review=self.review, source_id=self.scopus.pk)
        item = mapping.add_test_set_article(review=self.review, title="A known study")
        mapping.remove_test_set_article(review=self.review, item_id=item.pk)
        self.assertEqual(
            [
                ("search", "add", "Added the search string of “Scopus”"),
                ("search", "change", "Changed the search string of “Scopus”"),
                ("search", "change", "Changed the search documentation of “Scopus”"),
                ("search", "remove", "Removed the search string of “Scopus”"),
                ("search", "add", "Added the known study of the test set “A known study”"),
                ("search", "remove", "Removed the known study of the test set “A known study”"),
            ],
            self.events(),
        )
        documented = self.review.events.get(summary="Changed the search documentation of “Scopus”")
        self.assertEqual(
            [{"key": "searched_at", "field": "Date of search", "before": "", "after": "2026-10-01"}],
            documented.changes,
        )

    def test_studies(self):
        result = studies.import_bibtex(
            review=self.review,
            source_id=self.scopus.pk,
            content="@article{k1, title={One}}\n@article{k2, title={Two}}",
            actor=self.owner,
        )
        imported = self.latest()
        self.assertEqual(("studies", "Imported 2 studies into “Scopus”"), (imported.area, imported.summary))
        self.assertEqual(set(result.articles), set(imported.articles.all()))
        one, two = sorted(result.articles, key=lambda article: article.title)
        studies.update_article(review=self.review, article_id=one.pk, actor=self.owner, year="2020", status="R")
        studies.set_starred(review=self.review, article_id=one.pk, starred=True, actor=self.owner)
        studies.set_starred(review=self.review, article_id=one.pk, starred=True, actor=self.owner)  # nothing
        full_texts.attach_pdf(review=self.review, article_id=one.pk, file=ContentFile(PDF), filename="one.pdf")
        full_texts.remove_pdf(review=self.review, article_id=one.pk)
        studies.set_status(review=self.review, article_ids=[one.pk, two.pk], status="A", actor=self.owner)
        studies.resolve_duplicates(review=self.review, article_ids=[two.pk], actor=self.owner)
        studies.delete_articles(review=self.review, article_ids=[one.pk, two.pk])
        self.assertEqual(
            [
                ("studies", "change", "Changed the details of the study “One”"),
                ("selection", "change", "Rejected the study “One”"),
                ("studies", "change", "Starred the study “One”"),
                ("studies", "add", "Added a PDF to the study “One”"),
                ("studies", "remove", "Removed the PDF of the study “One”"),
                ("selection", "change", "Accepted 2 studies"),
                ("selection", "change", "Marked the study “Two” as duplicate"),
                ("studies", "remove", "Deleted 2 studies"),
            ],
            self.events(pk__gt=imported.pk),
        )
        accepted = self.review.events.get(summary="Accepted 2 studies")
        self.assertEqual(["1 was Rejected", "1 was Unclassified"], accepted.items)
        self.assertEqual(["One", "Two"], self.review.events.get(summary="Deleted 2 studies").items)
        rejected = self.review.events.get(summary="Rejected the study “One”")
        self.assertEqual(
            [{"key": "status", "field": "Status", "before": "Unclassified", "after": "Rejected"}], rejected.changes
        )

    def test_clearing_a_source(self):
        ArticleFactory(review=self.review, source=self.scopus, title="Wrong export")
        studies.clear_articles(review=self.review, source_id=self.scopus.pk)
        event = self.latest()
        self.assertEqual("Deleted the 1 study imported into “Scopus”", event.summary)
        self.assertEqual(["Wrong export"], event.items)


class TestSelectionQualityExtraction(HistoryTestCase):
    def test_decisions(self):
        study = ArticleFactory(review=self.review, title="A study")
        other = ArticleFactory(review=self.review, title="Another")
        criterion = SelectionCriteriaFactory(review=self.review, criteria_type="E", description="Not in English")
        decisions.record_decision(review=self.review, article_id=study.pk, actor=self.colleague, status="R")
        decisions.record_decision(
            review=self.review, article_id=study.pk, actor=self.colleague, status="R", criteria_id=criterion.pk
        )
        decisions.record_decision(
            review=self.review, article_id=study.pk, actor=self.colleague, status="R", criteria_id=criterion.pk
        )  # the same: nothing
        decisions.record_decisions(review=self.review, article_ids=[study.pk, other.pk], actor=self.owner, status="R")
        decisions.consolidate(review=self.review, stage=StudyDecision.TITLE_ABSTRACT)
        decisions.remove_decision(review=self.review, article_id=study.pk, actor=self.colleague)
        self.assertEqual(
            [
                (
                    "selection",
                    "change",
                    "Recorded the decision Rejected for the study “A study” (Title and abstract screening)",
                ),
                (
                    "selection",
                    "change",
                    "Recorded the decision Rejected for the study “A study” (Title and abstract screening)",
                ),
                ("selection", "change", "Recorded the decision Rejected for 2 studies (Title and abstract screening)"),
                (
                    "selection",
                    "change",
                    "Consolidated the decisions (Title and abstract screening, rule unanimous): 2 studies changed",
                ),
                (
                    "selection",
                    "remove",
                    "Removed the decision Rejected on the study “A study” (Title and abstract screening)",
                ),
            ],
            self.events(),
        )
        first, second = self.review.events.order_by("pk")[:2]
        self.assertEqual(self.colleague, first.actor)
        self.assertEqual(
            [{"key": "selection_criteria", "field": "Criterion", "before": "", "after": "Not in English"}],
            second.changes,
        )
        consolidated = self.review.events.get(summary__startswith="Consolidated")
        self.assertEqual(["2 now Rejected", "2 resolved", "0 left undecided"], consolidated.items)
        self.assertEqual({study, other}, set(consolidated.articles.all()))

    def test_quality_extraction_classification_prisma(self):
        study = ArticleFactory(review=self.review, title="A study", status=Article.ACCEPTED)
        question = QualityQuestionFactory(review=self.review, description="Clear?")
        yes = QualityAnswerFactory(review=self.review, description="Yes")
        quality.assess(review=self.review, article_id=study.pk, question_id=question.pk, answer_id=yes.pk)
        quality.assess(review=self.review, article_id=study.pk, question_id=question.pk, answer_id=None)
        country = DataExtractionFieldFactory(review=self.review, description="Country", field_type="M")
        brazil = DataExtractionLookupFactory(field=country, value="Brazil")
        extraction.toggle_select_value(
            review=self.review, article_id=study.pk, field_id=country.pk, lookup_id=brazil.pk
        )
        year = DataExtractionFieldFactory(review=self.review, description="Year", field_type="I")
        extraction.set_value(review=self.review, article_id=study.pk, field_id=year.pk, value="2020")
        extraction.set_value(review=self.review, article_id=study.pk, field_id=year.pk, value="2020")  # nothing
        extraction.mark_done(review=self.review, article_id=study.pk)
        facet = classification.add_facet(
            review=self.review, name="Type", kind=ClassificationFacet.FIXED, categories=["Tool"]
        )
        tool = facet.categories.get()
        since = self.latest().pk
        classification.classify(review=self.review, article_id=study.pk, facet_id=facet.pk, category_ids=[tool.pk])
        missing = SelectionCriteriaFactory(review=self.review, criteria_type="E", description="No full text")
        analytics.set_prisma_not_retrieved(review=self.review, criteria_id=missing.pk)
        self.assertEqual(
            [
                ("quality", "change", "Answered “Clear?” for the study “A study”"),
                ("quality", "change", "Cleared the answer to “Clear?” for the study “A study”"),
                ("extraction", "change", "Extracted “Country” for the study “A study”"),
                ("extraction", "change", "Extracted “Year” for the study “A study”"),
                ("extraction", "change", "Marked the data extraction of the study “A study” as done"),
                ("planning", "add", "Added the classification facet “Type”"),
            ],
            self.events(pk__lte=since),
        )
        self.assertEqual(
            [
                ("extraction", "change", "Classified the study “A study” in “Type”"),
                ("analysis", "change", "Changed the criterion of the reports not retrieved (PRISMA flow diagram)"),
            ],
            self.events(pk__gt=since),
        )
        year_event = self.review.events.get(summary="Extracted “Year” for the study “A study”")
        self.assertEqual([{"key": "value", "field": "Year", "before": "", "after": "2020"}], year_event.changes)


class TestAiRuns(AiScreeningTestCase):
    def test_a_run_is_recorded_once_not_per_study(self):
        first = self.article(title="First")
        self.article(title="Second")
        since = self.review.events.order_by("pk").last().pk
        with history.acting(self.owner, ReviewEvent.WEB):
            run = self.start()
            self.step(run, [EXCLUDE_E2, KEEP])
            ai_runs.undo_run(review=self.review, actor=self.owner, run_id=run.pk)
        events = list(self.review.events.filter(pk__gt=since).order_by("pk"))
        self.assertEqual(
            [
                f"Started Exclude with AI (run #{run.pk}) on 2 studies as Screener A, model jev-1.13.0",
                f"Finished Exclude with AI (run #{run.pk}): 1 excluded, 1 passed to the next phase",
                f"Undid Exclude with AI (run #{run.pk})",
            ],
            [event.summary for event in events],
        )
        self.assertEqual(["E1: Not a primary study", "E2: Not in English"], events[0].items)
        self.assertEqual([first], list(events[1].articles.all()))
        self.assertEqual({None}, {event.run_id for event in events})  # the run was deleted when it was undone
        self.assertEqual({self.owner}, {event.actor for event in events})
