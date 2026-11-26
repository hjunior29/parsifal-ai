from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.models import Question
from parsifal.apps.reviews.tests.factories import DataExtractionFieldFactory, ReviewFactory


class ReviewCodesViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory()
        cls.url = reverse("review_codes", args=(cls.review.author.username, cls.review.name))

    def setUp(self):
        self.client.force_login(self.review.author)

    def test_main_author_only(self):
        colleague = UserFactory()
        self.review.co_authors.add(colleague)
        self.client.force_login(colleague)
        self.assertNotEqual(200, self.client.get(self.url).status_code)

    def test_prefixes(self):
        page = self.client.get(self.url)
        self.assertContains(page, 'name="prefix-question" value="RQ"', html=False)
        self.assertContains(page, "No name starts with a code typed by hand.")
        data = {
            f"prefix-{kind}": prefix
            for kind, prefix in (
                ("question", "QP"),
                ("inclusion", "CI"),
                ("exclusion", "CE"),
                ("quality", "QA"),
                ("extraction", "EX"),
            )
        }
        response = self.client.post(self.url, data, follow=True)
        self.assertContains(response, "The prefixes were saved.")
        self.review.refresh_from_db()
        self.assertEqual("QP", self.review.code_prefixes["question"])
        response = self.client.post(self.url, dict(data, **{"prefix-inclusion": "CE"}), follow=True)
        self.assertContains(response, "Each kind needs a prefix of its own.")

    def test_strip_the_codes_checked(self):
        kept = Question.objects.create(review=self.review, question="RQ1: Kept as it is?", order=0)
        stripped = DataExtractionFieldFactory(review=self.review, description="EX01 | Country")
        page = self.client.get(self.url)
        self.assertContains(page, "EX01 | Country")
        response = self.client.post(self.url, {"action": "strip", "keys": [f"extraction-{stripped.pk}"]}, follow=True)
        self.assertContains(response, "The codes were removed from 1 names.")
        stripped.refresh_from_db()
        kept.refresh_from_db()
        self.assertEqual(("Country", "RQ1: Kept as it is?"), (stripped.description, kept.question))
