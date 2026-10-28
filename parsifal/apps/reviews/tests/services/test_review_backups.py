import io
import tarfile

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.exceptions import PermissionDenied, ValidationError
from parsifal.apps.core.models import StoredFile
from parsifal.apps.core.tests.files import PDF, TemporaryFilesMixin
from parsifal.apps.reviews.models import (
    Article,
    ArticleClassification,
    ClassificationCategory,
    ClassificationFacet,
    DataExtraction,
    Keyword,
    ProcessChecklistItem,
    QualityAssessment,
    Question,
    Review,
    ReviewAgent,
    ReviewBackup,
    ReviewTestSetArticle,
    ScreeningResult,
    ScreeningRun,
    SearchSession,
    StudyDecision,
)
from parsifal.apps.reviews.services import agents, extraction, full_texts, quality, review_backups
from parsifal.apps.reviews.tests.factories import (
    DataExtractionFieldFactory,
    DefaultSourceFactory,
    QualityAnswerFactory,
    QualityQuestionFactory,
    ReviewFactory,
    SelectionCriteriaFactory,
    SourceFactory,
)


class ReviewBackupsTestCase(TemporaryFilesMixin, TestCase):
    """A review with something of everything it can hold."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = UserFactory(username="owner")
        cls.colleague = UserFactory(username="colleague")
        cls.scopus = DefaultSourceFactory(name="Scopus")
        cls.custom = SourceFactory(name="Our own list")
        cls.review = ReviewFactory(
            author=cls.owner, co_authors=[cls.colleague], sources=[cls.scopus, cls.custom], objective="Why"
        )
        review = cls.review
        cls.agent = agents.create_agent(review=review, actor=cls.owner, name="Jev")
        parent = Question.objects.create(review=review, question="RQ1")
        Question.objects.create(review=review, question="RQ1.1", parent_question=parent)
        cls.exclusion = SelectionCriteriaFactory(review=review, criteria_type="E", description="Not in English")
        cls.inclusion = SelectionCriteriaFactory(review=review, criteria_type="I", description="Proposes a tool")
        cls.missing = SelectionCriteriaFactory(review=review, criteria_type="E", description="Full text missing")
        review.prisma_not_retrieved = cls.missing
        review.save()
        session = SearchSession.objects.create(review=review, source=cls.scopus, search_string="agents AND tests")
        keyword = Keyword.objects.create(review=review, description="agent", related_to="I")
        Keyword.objects.create(review=review, description="bot", related_to="I", synonym_of=keyword)
        question = QualityQuestionFactory(review=review, description="Is it clear?")
        yes = QualityAnswerFactory(review=review, description="Yes", weight=1.0)
        country = DataExtractionFieldFactory(review=review, description="Country", field_type="M")
        brazil = country.dataextractionlookup_set.create(value="Brazil")
        country.dataextractionlookup_set.create(value="Portugal")
        facet = ClassificationFacet.objects.create(review=review, name="Type", description="", template="")
        category = ClassificationCategory.objects.create(facet=facet, name="Tool", description="")
        ProcessChecklistItem.objects.create(review=review, key="pilot", applied=True, notes="")
        cls.study = Article.objects.create(
            review=review, source=cls.scopus, title="A study", year="2020", status="A", found_via=session
        )
        cls.rejected = Article.objects.create(
            review=review, source=cls.custom, title="Out", status="R", selection_criteria=cls.exclusion
        )
        ReviewTestSetArticle.objects.create(
            review=review, title="A study", doi="", notes="", matched_article=cls.study
        )
        quality.assess(
            review=review, article_id=cls.study.pk, question_id=question.pk, answer_id=yes.pk, actor=cls.owner
        )
        extraction.toggle_select_value(
            review=review, article_id=cls.study.pk, field_id=country.pk, lookup_id=brazil.pk, actor=cls.colleague
        )
        ArticleClassification.objects.create(
            article=cls.study, facet=facet, category=category, user=cls.owner, notes=""
        )
        agent_user = cls.agent.agent.user
        cls.ai_run = ScreeningRun.objects.create(
            review=review,
            reviewer=agent_user,
            started_by=cls.owner,
            model="jev-1",
            parameters={
                "criteria": [{"key": "E1", "id": cls.exclusion.pk, "description": "Not in English"}],
                "skipped_criteria": [cls.missing.pk],
                "source_id": cls.scopus.pk,
                "threshold": 0.9,
            },
            status="finished",
            total=1,
            error="",
        )
        StudyDecision.objects.create(
            review=review,
            article=cls.rejected,
            user=agent_user,
            status="R",
            selection_criteria=cls.exclusion,
            comments="",
            run=cls.ai_run,
        )
        ScreeningResult.objects.create(
            run=cls.ai_run,
            article=cls.rejected,
            previous_status="U",
            model="jev-1",
            error="",
            status_set="R",
            selection_criteria=cls.exclusion,
            previous_updated_by=cls.colleague,
            previous_decision={
                "status": "U",
                "criteria_id": cls.exclusion.pk,
                "comments": "",
                "run_id": cls.ai_run.pk,
            },
        )
        StudyDecision.objects.create(
            review=review, article=cls.study, user=cls.colleague, stage="full_text", status="A", comments="ok"
        )
        cls.decided_at = StudyDecision.objects.get(user=cls.colleague).decided_at

    def setUp(self):
        super().setUp()  # the files folder is emptied before each test: the PDF is attached here
        full_texts.attach_pdf(review=self.review, article_id=self.study.pk, file=ContentFile(PDF), actor=self.owner)

    def counts(self, review):
        return {
            "questions": review.research_questions.count(),
            "criteria": review.selectioncriteria_set.count(),
            "sessions": review.searchsession_set.count(),
            "keywords": review.keywords.count(),
            "quality": (review.qualityquestion_set.count(), review.qualityanswer_set.count()),
            "fields": review.dataextractionfield_set.count(),
            "articles": review.article_set.count(),
            "assessments": QualityAssessment.objects.filter(article__review=review).count(),
            "extractions": DataExtraction.objects.filter(article__review=review).count(),
            "classifications": ArticleClassification.objects.filter(article__review=review).count(),
            "checklist": review.checklist_items.count(),
            "test_set": review.test_set.count(),
            "runs": review.screening_runs.count(),
            "results": ScreeningResult.objects.filter(run__review=review).count(),
            "decisions": review.decisions.count(),
            "sources": sorted(review.sources.values_list("name", flat=True)),
        }


class TestBackups(ReviewBackupsTestCase):
    def test_a_backup_holds_the_review_and_its_pdfs(self):
        backup = review_backups.create_backup(review=self.review, actor=self.owner)
        self.assertEqual((2, self.owner), (backup.studies, backup.created_by))
        self.assertTrue(backup.file.filename.startswith(f"{self.review.name}-"))
        with backup.file.open() as handle, tarfile.open(fileobj=io.BytesIO(handle.read())) as archive:
            names = archive.getnames()
        self.assertIn("review.json", names)
        self.assertIn("manifest.json", names)
        self.assertEqual(1, len([name for name in names if name.startswith("files/reviews/")]))

    def test_only_the_main_author(self):
        with self.assertRaises(PermissionDenied):
            review_backups.create_backup(review=self.review, actor=self.colleague)
        with self.assertRaises(PermissionDenied):
            review_backups.list_backups(self.review, self.colleague)

    @override_settings(PARSIFAL_REVIEW_BACKUPS_KEEP=2)
    def test_the_newest_are_kept(self):
        backups = [review_backups.create_backup(review=self.review, actor=self.owner) for _ in range(3)]
        self.assertEqual([backups[2].pk, backups[1].pk], list(self.review.backups.values_list("pk", flat=True)))
        self.assertFalse(StoredFile.objects.filter(pk=backups[0].file_id).exists())

    def test_upload_checks_the_file(self):
        backup = review_backups.create_backup(review=self.review, actor=self.owner)
        with backup.file.open() as handle:
            content = handle.read()
        uploaded = review_backups.upload_backup(
            review=self.review, actor=self.owner, filename="x.tar.gz", content=content
        )
        self.assertEqual(("Uploaded", 2, "x.tar.gz"), (uploaded.note, uploaded.studies, uploaded.file.filename))
        with self.assertRaisesMessage(ValidationError, "not a backup of a review"):
            review_backups.upload_backup(review=self.review, actor=self.owner, filename="x", content=b"nope")
        damaged = io.BytesIO()
        with tarfile.open(fileobj=io.BytesIO(content)) as source, tarfile.open(fileobj=damaged, mode="w:gz") as target:
            for member in source.getmembers():
                data = source.extractfile(member).read()
                if member.name == "review.json":
                    data = data.replace(b"A study", b"B study")
                target.addfile(member, io.BytesIO(data))
        with self.assertRaisesMessage(ValidationError, "damaged"):
            review_backups.upload_backup(
                review=self.review, actor=self.owner, filename="x", content=damaged.getvalue()
            )


class TestImport(ReviewBackupsTestCase):
    def import_backup(self, actor):
        backup = review_backups.create_backup(review=self.review, actor=self.owner)
        with backup.file.open() as handle:
            return review_backups.import_review(actor=actor, content=handle.read())

    def test_a_new_review_with_everything(self):
        newcomer = UserFactory(username="newcomer")
        copy = self.import_backup(newcomer)
        self.assertNotEqual(self.review.pk, copy.pk)
        self.assertEqual((newcomer, self.review.name, "Why"), (copy.author, copy.name, copy.objective))
        self.assertEqual(self.counts(self.review), self.counts(copy))
        with self.subTest(msg="references point to the copy's own objects"):
            self.assertEqual("Full text missing", copy.prisma_not_retrieved.description)
            self.assertEqual(copy, copy.prisma_not_retrieved.review)
            child = copy.research_questions.get(question="RQ1.1")
            self.assertEqual(copy.research_questions.get(question="RQ1"), child.parent_question)
            self.assertEqual("agent", copy.keywords.get(description="bot").synonym_of.description)
            study = copy.article_set.get(title="A study")
            self.assertEqual(copy, study.found_via.review)
            self.assertEqual(study, copy.test_set.get().matched_article)
            self.assertEqual(
                ["Brazil"], [v.value for v in DataExtraction.objects.get(article=study).select_values.all()]
            )
            self.assertEqual(copy, copy.article_set.get(title="Out").selection_criteria.review)
        with self.subTest(msg="the PDF is copied under the copy"):
            self.assertTrue(study.pdf.key.startswith(f"reviews/{copy.pk}/"))
            self.assertNotEqual(Article.objects.get(pk=self.study.pk).pdf.key, study.pdf.key)
            with study.pdf.open() as handle:
                self.assertEqual(PDF, handle.read())
        with self.subTest(msg="people by username; the agent as a new agent of the copy, without tokens"):
            self.assertIn(self.colleague, copy.co_authors.all())
            decision = copy.decisions.get(stage="full_text")
            self.assertEqual((self.colleague, self.decided_at), (decision.user, decision.decided_at))
            agent = ReviewAgent.objects.get(review=copy)
            self.assertNotEqual(self.agent.agent.user, agent.user)
            self.assertEqual("Jev", agent.name)
            self.assertFalse(agent.user.api_tokens.exists())
            self.assertEqual(agent.user, copy.decisions.get(stage="title_abstract").user)
        with self.subTest(msg="AI runs point to the copy's criteria, source and runs"):
            run = copy.screening_runs.get()
            self.assertEqual(agent.user, run.reviewer)
            criteria = copy.selectioncriteria_set
            self.assertEqual(criteria.get(description="Not in English").pk, run.parameters["criteria"][0]["id"])
            self.assertEqual([criteria.get(description="Full text missing").pk], run.parameters["skipped_criteria"])
            self.assertEqual(copy.sources.get(name="Scopus").pk, run.parameters["source_id"])
            result = ScreeningResult.objects.get(run=run)
            self.assertEqual(run.pk, result.previous_decision["run_id"])
            self.assertEqual(criteria.get(description="Not in English").pk, result.previous_decision["criteria_id"])
            self.assertEqual(run, copy.decisions.get(stage="title_abstract").run)
        with self.subTest(msg="default sources are shared, custom ones copied"):
            self.assertEqual(self.scopus, copy.sources.get(name="Scopus"))
            self.assertNotEqual(self.custom, copy.sources.get(name="Our own list"))
        self.assertEqual(f"{self.review.name}-1", self.import_backup(newcomer).name)

    def test_someone_without_an_account_gets_an_inactive_one(self):
        backup = review_backups.create_backup(review=self.review, actor=self.owner)
        with backup.file.open() as handle:
            content = handle.read()
        self.colleague.delete()  # as in another Parsifal, where nobody is called "colleague"
        copy = review_backups.import_review(actor=self.owner, content=content)
        person = User.objects.get(username="colleague")
        self.assertFalse(person.is_active)
        self.assertFalse(person.has_usable_password())
        self.assertEqual(person, copy.decisions.get(stage="full_text").user)

    def test_not_a_backup(self):
        with self.assertRaisesMessage(ValidationError, "not a backup of a review"):
            review_backups.import_review(actor=self.owner, content=b"nope")
        self.assertEqual(1, Review.objects.count())


class TestRestore(ReviewBackupsTestCase):
    def test_the_review_back_as_it_was(self):
        backup = review_backups.create_backup(review=self.review, actor=self.owner)
        before = self.counts(self.review)
        token = self.agent.token
        Article.objects.filter(pk=self.rejected.pk).delete()
        SelectionCriteriaFactory(review=self.review, criteria_type="E", description="Added later")
        self.review.objective = "Changed"
        self.review.save()
        review_backups.restore_backup(review=self.review, actor=self.owner, backup_id=backup.pk)
        self.review.refresh_from_db()
        self.assertEqual(before, self.counts(self.review))
        self.assertEqual("Why", self.review.objective)
        self.assertEqual("Full text missing", self.review.prisma_not_retrieved.description)
        with self.subTest(msg="the agent and its token stay"):
            agent = ReviewAgent.objects.get(review=self.review)
            self.assertEqual(self.agent.agent.pk, agent.pk)
            self.assertTrue(agent.user.api_tokens.filter(pk=token.pk).exists())
            self.assertEqual(agent.user, self.review.decisions.get(stage="title_abstract").user)
        with self.subTest(msg="what was there before is backed up first"):
            notes = list(self.review.backups.values_list("note", flat=True))
            self.assertEqual(f"Before restoring {backup.file.filename}", notes[0])
        with self.subTest(msg="the study's PDF is there"):
            with self.review.article_set.get(title="A study").pdf.open() as handle:
                self.assertEqual(PDF, handle.read())
        self.assertEqual(2, ReviewBackup.objects.filter(review=self.review).count())

    def test_only_the_main_author(self):
        backup = review_backups.create_backup(review=self.review, actor=self.owner)
        with self.assertRaises(PermissionDenied):
            review_backups.restore_backup(review=self.review, actor=self.colleague, backup_id=backup.pk)
