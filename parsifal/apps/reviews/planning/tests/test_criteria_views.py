from django.test import TestCase
from django.urls import reverse

from parsifal.apps.reviews.models import SelectionCriteria
from parsifal.apps.reviews.tests.factories import ReviewFactory, SelectionCriteriaFactory

LONG = (
    "CE6 — Tipo de publicação fora de periódico/conferência com revisão por pares ou ausência de revisão por pares; "
    "inclui estudos de workshops, preprints, teses e dissertações"
)


class CriteriaViewsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory()
        cls.protocol_url = reverse("protocol", args=(cls.review.author.username, cls.review.name))

    def setUp(self):
        self.client.force_login(self.review.author)

    def test_long_criteria_are_listed_in_full(self):
        SelectionCriteriaFactory(review=self.review, criteria_type="E", description=LONG)
        response = self.client.get(self.protocol_url)
        self.assertContains(response, 'role="option" aria-selected="false" data-id=')
        self.assertContains(response, f">{LONG}</div>")
        self.assertContains(response, 'class="form-control criteria-listbox" id="exclusion-criteria"')

    def test_add_returns_an_escaped_list_row(self):
        response = self.client.get(
            reverse("reviews:planning:add_criteria"),
            {"review-id": self.review.pk, "criteria": "<b>CI9</b>", "criteria-type": "I"},
        )
        criteria = SelectionCriteria.objects.get(review=self.review)
        self.assertContains(response, f'data-id="{criteria.pk}"')
        self.assertContains(response, "&lt;b&gt;CI9&lt;/b&gt;")
        self.assertNotContains(response, "<b>CI9</b>")
