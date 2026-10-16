from django.test import TestCase

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from parsifal.apps.reviews.models import Review, Source
from parsifal.apps.reviews.services import reviews
from parsifal.apps.reviews.tests.factories import ArticleFactory, DefaultSourceFactory, ReviewFactory, SourceFactory


class TestCreateAndRename(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def test_create_generates_unique_slug(self):
        first = reviews.create_review(actor=self.user, title="Test SLR", description="d")
        second = reviews.create_review(actor=self.user, title="Test SLR")
        third = reviews.create_review(actor=self.user, title=")")
        self.assertEqual(("test-slr", "test-slr-1", "literature-review"), (first.name, second.name, third.name))
        self.assertEqual(self.user, first.author)

    def test_create_validation(self):
        with self.assertRaises(ValidationError):
            reviews.create_review(actor=self.user, title="")
        with self.assertRaises(ValidationError):
            reviews.create_review(actor=self.user, title="x" * 256)

    def test_rename(self):
        review = reviews.create_review(actor=self.user, title="One")
        reviews.create_review(actor=self.user, title="Two")
        reviews.rename_review(review=review, name="two")
        review.refresh_from_db()
        with self.subTest(msg="collision suffixed"):
            self.assertEqual("two-1", review.name)
        with self.subTest(msg="renaming to own name is a no-op"):
            reviews.rename_review(review=review, name="two-1")
            review.refresh_from_db()
            self.assertEqual("two-1", review.name)
        with self.assertRaises(ValidationError):
            reviews.rename_review(review=review, name="Not A Slug")

    def test_update_fields(self):
        review = ReviewFactory(author=self.user)
        reviews.update_review(review=review, objective="Obj", population="devs", quality_assessment_cutoff_score="2,5")
        review.refresh_from_db()
        self.assertEqual(("Obj", "devs"), (review.objective, review.population))
        with self.assertRaises(ValidationError):
            reviews.update_review(review=review, quality_assessment_cutoff_score="2,5x")

    def test_update_rejects_unknown_and_too_long(self):
        review = ReviewFactory(author=self.user)
        with self.assertRaises(ValidationError):
            reviews.update_review(review=review, author_id=1)
        with self.assertRaises(ValidationError):
            reviews.update_review(review=review, description="x" * 501)
        with self.assertRaises(ValidationError):
            reviews.update_review(review=review, quality_assessment_cutoff_score=-1)


class TestMembershipAndTransfer(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = UserFactory()
        cls.co_author = UserFactory()
        cls.outsider = UserFactory()
        cls.review = ReviewFactory(author=cls.author, co_authors=[cls.co_author], name="shared")

    def test_guards(self):
        reviews.require_member(self.review, self.co_author)
        reviews.require_owner(self.review, self.author)
        with self.assertRaises(PermissionDenied):
            reviews.require_member(self.review, self.outsider)
        with self.assertRaises(PermissionDenied):
            reviews.require_owner(self.review, self.co_author)

    def test_add_remove_co_author(self):
        reviews.add_co_author(review=self.review, user=self.outsider)
        self.assertTrue(self.review.is_author_or_coauthor(self.outsider))
        with self.assertRaises(Conflict):
            reviews.add_co_author(review=self.review, user=self.outsider)
        with self.assertRaises(Conflict):
            reviews.add_co_author(review=self.review, user=self.author)
        reviews.remove_co_author(review=self.review, user=self.outsider)
        with self.assertRaises(NotFound):
            reviews.remove_co_author(review=self.review, user=self.outsider)

    def test_find_user(self):
        self.assertEqual(self.author, reviews.find_user(username=self.author.username.upper()))
        self.assertEqual(self.author, reviews.find_user(email=self.author.email))
        with self.assertRaises(NotFound):
            reviews.find_user(username="nobody")

    def test_get_review(self):
        self.assertEqual(self.review, reviews.get_review(author_username=self.author.username.upper(), name="shared"))
        with self.assertRaises(NotFound):
            reviews.get_review(author_username=self.author.username, name="missing")


class TestDeleteAndOverview(TestCase):
    def test_delete_removes_custom_sources_only(self):
        default = DefaultSourceFactory()
        custom = SourceFactory()
        review = ReviewFactory(sources=[default, custom])
        reviews.delete_review(review=review)
        self.assertFalse(Review.objects.filter(pk=review.pk).exists())
        self.assertTrue(Source.objects.filter(pk=default.pk).exists())
        self.assertFalse(Source.objects.filter(pk=custom.pk).exists())

    def test_overview_counts(self):
        source = SourceFactory()
        review = ReviewFactory(sources=[source])
        ArticleFactory(review=review, source=source, status="A", finished_data_extraction=True)
        ArticleFactory(review=review, source=source, status="R")
        ArticleFactory(review=review, source=source)
        overview = reviews.review_overview(review)
        self.assertEqual(1, overview["sources"])
        self.assertEqual(
            {
                "total": 3,
                "unclassified": 1,
                "accepted": 1,
                "rejected": 1,
                "duplicated": 0,
                "final_selection": 1,
                "extraction_done": 1,
            },
            overview["articles"],
        )
        self.assertFalse(overview["has_generic_search_string"])
