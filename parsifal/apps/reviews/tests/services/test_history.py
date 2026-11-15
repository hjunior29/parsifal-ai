import datetime

from django.test import RequestFactory, TestCase
from django.utils import timezone

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.models import Article, ReviewEvent
from parsifal.apps.reviews.services import agents, history, reviews, selection
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory


class TestRecord(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = UserFactory(username="owner", first_name="Ada", last_name="Lovelace")
        cls.review = ReviewFactory(author=cls.owner)

    def test_who_and_through_what(self):
        with self.subTest(msg="outside a request: Parsifal itself"):
            event = history.record(self.review, ReviewEvent.REVIEW, history.CHANGED, "Did something")
            self.assertEqual((None, "", ReviewEvent.SYSTEM), (event.actor, event.actor_name, event.via))
        with self.subTest(msg="acting"):
            with history.acting(self.owner, ReviewEvent.CLI):
                event = history.record(self.review, ReviewEvent.REVIEW, history.CHANGED, "Did something")
            self.assertEqual((self.owner, "Ada Lovelace", ReviewEvent.CLI), (event.actor, event.actor_name, event.via))
        for headers, via in (
            ({}, ReviewEvent.WEB),
            ({"HTTP_AUTHORIZATION": "Bearer x"}, ReviewEvent.API),
            ({"HTTP_AUTHORIZATION": "Bearer x", "HTTP_USER_AGENT": "parsifal-cli/1.0"}, ReviewEvent.CLI),
            ({"HTTP_AUTHORIZATION": "Bearer x", "HTTP_USER_AGENT": "parsifal-mcp/1.0"}, ReviewEvent.MCP),
            ({"HTTP_USER_AGENT": "parsifal-cli/1.0"}, ReviewEvent.WEB),  # no token: the browser's session
        ):
            with self.subTest(msg=f"a request: {via}"):
                request = RequestFactory().get("/", **headers)
                request.user = self.owner
                with history.acting(request=request):
                    event = history.record(self.review, ReviewEvent.REVIEW, history.CHANGED, "Did something")
                self.assertEqual((self.owner, via), (event.actor, event.via))

    def test_studies_and_items(self):
        studies = ArticleFactory.create_batch(3, review=self.review)
        event = history.record(
            self.review,
            ReviewEvent.STUDIES,
            history.REMOVED,
            "Deleted 3 studies",
            articles=[studies[0], studies[1].pk, studies[1]],
            items=range(history.MAX_ITEMS + 2),
        )
        self.assertEqual({studies[0], studies[1]}, set(event.articles.all()))
        self.assertEqual(history.MAX_ITEMS + 1, len(event.items))
        self.assertEqual("… and 2 more", event.items[-1])

    def test_an_amendment_is_a_planning_change_once_studies_were_imported(self):
        before = history.record(self.review, ReviewEvent.PLANNING, history.ADDED, "Added a question")
        ArticleFactory(review=self.review)
        after = history.record(self.review, ReviewEvent.PLANNING, history.CHANGED, "Changed a question")
        elsewhere = history.record(self.review, ReviewEvent.SELECTION, history.CHANGED, "Accepted a study")
        self.assertEqual([False, True, False], [before.amendment, after.amendment, elsewhere.amendment])

    def test_tracker(self):
        review = ReviewFactory(title="Old")
        tracker = history.track(review, "title", "review_type", "quality_assessment_cutoff_score", "objective")
        review.title, review.review_type, review.quality_assessment_cutoff_score = "New", "mapping", 2.5
        self.assertEqual(
            [
                {"key": "title", "field": "Title", "before": "Old", "after": "New"},
                {
                    "key": "review_type",
                    "field": "Review type",
                    "before": "Systematic literature review",
                    "after": "Systematic mapping study",
                },
                {
                    "key": "quality_assessment_cutoff_score",
                    "field": "Quality assessment cutoff score",
                    "before": "0",
                    "after": "2.5",
                },
            ],
            tracker.changes(),
        )

    def test_summaries(self):
        self.assertEqual("“a b”", history.quote("  a\n b "))
        self.assertEqual(80, len(history.quote("x" * 200)) - 2)
        self.assertEqual(("1 study", "2 studies"), (history.studies(1), history.studies(2)))
        self.assertEqual(
            ("Yes", "", "2026-10-01"),
            (history.show(True), history.show(None), history.show(datetime.date(2026, 10, 1))),
        )


class TestListEvents(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = UserFactory(username="owner")
        cls.colleague = UserFactory(username="colleague", first_name="Grace", last_name="Hopper")
        cls.review = ReviewFactory(author=cls.owner, co_authors=[cls.colleague])
        cls.study = ArticleFactory(review=cls.review)
        with history.acting(cls.owner, ReviewEvent.WEB):
            cls.criterion = history.record(
                cls.review,
                ReviewEvent.PLANNING,
                history.ADDED,
                "Added the exclusion criterion “Not in English”",
                changes=[history.change("Description", "", "Not in English")],
            )
        with history.acting(cls.colleague, ReviewEvent.CLI):
            cls.accepted = history.record(
                cls.review, ReviewEvent.SELECTION, history.CHANGED, "Accepted a study", articles=[cls.study]
            )
        cls.old = history.record(cls.review, ReviewEvent.REVIEW, history.REMOVED, "Removed a co-author")
        ReviewEvent.objects.filter(pk=cls.old.pk).update(created_at=timezone.now() - datetime.timedelta(days=10))
        history.record(ReviewFactory(), ReviewEvent.REVIEW, history.CHANGED, "Another review")

    def summaries(self, **filters):
        return [event.summary for event in history.list_events(self.review, **filters)]

    def test_newest_first(self):
        self.assertEqual(
            ["Accepted a study", "Added the exclusion criterion “Not in English”", "Removed a co-author"],
            self.summaries(),
        )
        self.assertEqual([1, 0, 0], [event.study_count for event in history.list_events(self.review)])

    def test_filters(self):
        today = timezone.localdate()
        accepted, criterion, old = (
            ["Accepted a study"],
            ["Added the exclusion criterion “Not in English”"],
            ["Removed a co-author"],
        )
        for filters, expected in (
            ({"area": "planning"}, criterion),
            ({"action": "remove"}, old),
            ({"actor": "COLLEAGUE"}, accepted),
            ({"via": "cli"}, accepted),
            ({"article_id": self.study.pk}, accepted),
            ({"since": today}, accepted + criterion),
            ({"since": str(today - datetime.timedelta(days=10)), "until": today - datetime.timedelta(days=1)}, old),
            ({"query": "english"}, criterion),
            ({"query": "hopper"}, accepted),
            ({"query": "not english"}, criterion),
            ({"amendments": True}, criterion),
            ({"amendments": False}, accepted + old),
        ):
            with self.subTest(filters=filters):
                self.assertEqual(expected, self.summaries(**filters))

    def test_bad_filters(self):
        for filters in ({"area": "nowhere"}, {"via": "fax"}, {"since": "10/01/2026"}):
            with self.subTest(filters=filters), self.assertRaises(ValidationError):
                self.summaries(**filters)

    def test_actors(self):
        self.assertEqual([("colleague", "Grace Hopper"), ("owner", "owner")], history.actors(self.review))

    def test_event_studies(self):
        self.assertEqual([self.study], history.event_studies(self.accepted))


class TestReviewEvents(TestCase):
    """What the review services record."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = UserFactory(username="owner")

    def events(self, review):
        return list(review.events.order_by("pk").values_list("area", "action", "summary"))

    def test_create_update_rename(self):
        review = reviews.create_review(actor=self.owner, title="Agents")
        with history.acting(self.owner, ReviewEvent.API):
            reviews.update_review(review=review, title="Agents", objective="Why")
            reviews.update_review(review=review, title="AI agents", description="About them", inclusion_rule="any")
            reviews.update_review(review=review, objective="Why")  # nothing changes: nothing recorded
            reviews.rename_review(review=review, name="ai-agents")
        self.assertEqual(
            [
                ("review", "add", "Created the review “Agents”"),
                ("planning", "change", "Changed the protocol (Objective)"),
                ("review", "change", "Changed the review details (Title, Description)"),
                ("planning", "change", "Changed the protocol (A study must meet)"),
                ("review", "change", "Changed the review details (Name)"),
            ],
            self.events(review),
        )
        event = review.events.get(summary="Changed the protocol (A study must meet)")
        self.assertEqual(
            [
                {
                    "key": "inclusion_rule",
                    "field": "A study must meet",
                    "before": "all inclusion criteria",
                    "after": "at least one inclusion criterion",
                }
            ],
            event.changes,
        )
        self.assertEqual({self.owner}, {event.actor for event in review.events.all()})
        self.assertEqual(ReviewEvent.SYSTEM, review.events.order_by("pk").first().via)  # created outside a request

    def test_agents(self):
        review = ReviewFactory(author=self.owner)
        created = agents.create_agent(review=review, actor=self.owner, name="Jev")
        agent_user = created.agent.user
        with history.acting(agent_user, ReviewEvent.MCP):
            history.record(review, ReviewEvent.SELECTION, history.CHANGED, "Rejected a study")
        agents.new_token(review=review, actor=self.owner, agent_id=agent_user.pk)
        agents.delete_agent(review=review, actor=self.owner, agent_id=agent_user.pk)
        self.assertEqual(
            [
                ("review", "add", "Added the AI agent “Jev” (agent-jev) as co-author"),
                ("selection", "change", "Rejected a study"),
                ("review", "change", "Gave the AI agent “Jev” a new API token"),
                ("review", "remove", "Deleted the AI agent “Jev” and what it recorded"),
            ],
            self.events(review),
        )
        by_agent = review.events.get(summary="Rejected a study")
        self.assertEqual((None, "Jev"), (by_agent.actor, by_agent.actor_name))
        self.assertEqual(self.owner, review.events.order_by("pk").last().actor)

    def test_reset(self):
        colleague = UserFactory(username="colleague")
        review = ReviewFactory(author=self.owner, co_authors=[colleague])
        accepted = ArticleFactory(review=review, status=Article.ACCEPTED)
        ArticleFactory(review=review, status=Article.DUPLICATED)
        review.decisions.create(article=accepted, user=colleague, status=Article.ACCEPTED)
        selection.reset(review=review, actor=self.owner, reviewer_ids=[colleague.pk])
        event = review.events.get()
        self.assertEqual(
            ("selection", "Reset the study selection: 1 study unclassified again, 1 decision deleted (colleague)"),
            (event.area, event.summary),
        )
        self.assertEqual([accepted], list(event.articles.all()))
