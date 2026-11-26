from django.test import TestCase
from django.urls import reverse

from parsifal.apps.reviews.models import SelectionCriteria
from parsifal.apps.reviews.tests.factories import ReviewFactory, SelectionCriteriaFactory

LONG = (
    "Tipo de publicação fora de periódico/conferência com revisão por pares ou ausência de revisão por pares; "
    "inclui estudos de workshops, preprints, teses e dissertações"
)


class CriteriaViewsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory()
        cls.protocol_url = reverse("protocol", args=(cls.review.author.username, cls.review.name))

    def setUp(self):
        self.client.force_login(self.review.author)

    def test_each_criterion_in_full_with_its_code(self):
        SelectionCriteriaFactory(review=self.review, criteria_type="E", description=LONG)
        SelectionCriteriaFactory(review=self.review, criteria_type="I", description="Proposes a tool")
        response = self.client.get(self.protocol_url)
        self.assertContains(response, f'<td class="js-criteria-text">{LONG}</td>', html=True)
        self.assertContains(response, '<span class="item-code js-code">EC1</span>', html=True)
        self.assertContains(response, '<span class="item-code js-code">IC1</span>', html=True)
        self.assertContains(response, 'data-code-prefix="EC"', html=False)

    def test_add_edit_reorder_remove(self):
        add = reverse("reviews:planning:add_criteria")
        response = self.client.post(
            add, {"review-id": self.review.pk, "criteria": "<b>A tool</b>", "criteria-type": "I"}
        )
        criteria = SelectionCriteria.objects.get(review=self.review)
        self.assertContains(response, f'data-criteria-id="{criteria.pk}"')
        self.assertContains(response, "&lt;b&gt;A tool&lt;/b&gt;")
        self.assertNotContains(response, "<b>A tool</b>")
        self.assertContains(response, ">IC1<")
        second = SelectionCriteria.objects.get(
            pk=self.client.post(add, {"review-id": self.review.pk, "criteria": "An evaluation", "criteria-type": "I"})
            .content.decode()
            .split('data-criteria-id="')[1]
            .split('"')[0]
        )
        self.assertEqual(1, second.order)
        response = self.client.post(
            reverse("reviews:planning:save_criteria"),
            {"review-id": self.review.pk, "criteria-id": criteria.pk, "criteria": "Proposes a tool"},
        )
        self.assertContains(response, "Proposes a tool")
        self.assertEqual(
            400,
            self.client.post(
                reverse("reviews:planning:save_criteria"),
                {"review-id": self.review.pk, "criteria-id": criteria.pk, "criteria": ""},
            ).status_code,
        )
        order = reverse("reviews:planning:save_criteria_order")
        self.assertEqual(
            200,
            self.client.post(order, {"review-id": self.review.pk, "ids": f"{second.pk},{criteria.pk}"}).status_code,
        )
        self.assertEqual(
            ["An evaluation", "Proposes a tool"],
            list(self.review.selectioncriteria_set.values_list("description", flat=True)),
        )
        self.client.post(
            reverse("reviews:planning:remove_criteria"), {"review-id": self.review.pk, "criteria-ids": str(second.pk)}
        )
        self.assertEqual(
            ["Proposes a tool"], list(self.review.selectioncriteria_set.values_list("description", flat=True))
        )

    def test_whether_a_study_must_meet_all_inclusion_criteria_or_one(self):
        response = self.client.get(self.protocol_url)
        self.assertContains(response, '<option value="all" selected>all inclusion criteria</option>', html=True)
        self.assertContains(response, "Include and Screen with AI follow this rule.")
        url = reverse("reviews:planning:save_inclusion_rule")
        response = self.client.post(url, {"review-id": self.review.pk, "inclusion-rule": "any"})
        self.assertContains(response, "at least one inclusion criterion")
        self.review.refresh_from_db()
        self.assertEqual("any", self.review.inclusion_rule)
        response = self.client.post(url, {"review-id": self.review.pk, "inclusion-rule": "most"})
        self.assertEqual(400, response.status_code)
        self.assertEqual(405, self.client.get(url, {"review-id": self.review.pk, "inclusion-rule": "all"}).status_code)
