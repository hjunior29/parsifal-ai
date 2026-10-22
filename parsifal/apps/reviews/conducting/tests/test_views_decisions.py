from django.test import TestCase
from django.urls import reverse

from parsifal.apps.accounts.models import LibraryAccess
from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.conducting.views import build_article_table_row
from parsifal.apps.reviews.models import Article, StudyDecision
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    ReviewFactory,
    SelectionCriteriaFactory,
    SourceFactory,
)


class TestDecisionViews(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.human = UserFactory(username="alice")
        cls.agent = UserFactory(username="agent")
        cls.outsider = UserFactory()
        cls.review = ReviewFactory(author=cls.human, co_authors=[cls.agent], sources=[cls.source])
        cls.criteria = SelectionCriteriaFactory(review=cls.review, description="Relevant")
        cls.a1, cls.a2 = ArticleFactory.create_batch(2, review=cls.review, source=cls.source)

    def test_study_list_has_a_search_box_and_each_row_its_doi(self):
        Article.objects.filter(pk=self.a1.pk).update(doi='10.1/"x"')
        self.client.force_login(self.human)
        response = self.client.get(
            reverse("reviews:conducting:source_articles"), {"review-id": self.review.pk, "source-id": "None"}
        )
        self.assertContains(response, 'placeholder="Search title, DOI or BibTeX key"', html=False)
        self.assertContains(
            response, f'<tr oid="{self.a1.pk}" article-status="U" article-doi="10.1/&quot;x&quot;" article-starred="0"'
        )
        self.a1.refresh_from_db()
        self.assertIn('article-doi="10.1/&quot;x&quot;"', build_article_table_row(self.a1))  # row after a save

    def test_external_link_falls_back_to_the_doi(self):
        self.client.force_login(self.human)

        def details():
            return self.client.get(
                reverse("reviews:conducting:article_details"), {"review-id": self.review.pk, "article-id": self.a1.pk}
            )

        Article.objects.filter(pk=self.a1.pk).update(url="", doi="10.1007/978-3-031-70518-2\\_12")
        response = details()
        self.assertContains(response, 'href="https://doi.org/10.1007/978-3-031-70518-2_12" target="_blank"')
        self.assertContains(response, "External Link")
        self.assertContains(response, "Opens the DOI at doi.org")
        Article.objects.filter(pk=self.a1.pk).update(url="https://example.org/a1")
        response = details()
        self.assertContains(response, 'href="https://example.org/a1" target="_blank"')
        self.assertContains(response, 'title="Change the URL via Article URL"')
        Article.objects.filter(pk=self.a1.pk).update(url="", doi="")
        self.assertNotContains(details(), "External Link")

    def test_via_capes_with_the_users_library_access(self):
        self.client.force_login(self.human)
        url = reverse("reviews:conducting:article_details")
        params = {"review-id": self.review.pk, "article-id": self.a1.pk}
        Article.objects.filter(pk=self.a1.pk).update(url="https://www.scopus.com/record/1", doi="10.1109/X.1")
        self.assertNotContains(self.client.get(url, params), "js-access-link")
        LibraryAccess.objects.create(user=self.human, proxy="ez99.periodicos.capes.gov.br")
        response = self.client.get(url, params)
        self.assertContains(response, 'href="https://doi-org.ez99.periodicos.capes.gov.br/10.1109/X.1"')
        self.assertContains(response, "Via CAPES")
        self.assertContains(response, "Opens the DOI through your institution's access")
        self.assertContains(response, "External Link")  # unchanged, next to it
        # Without a DOI, the study's URL through the proxy.
        Article.objects.filter(pk=self.a1.pk).update(doi="")
        response = self.client.get(url, params)
        self.assertContains(response, 'href="https://www-scopus-com.ez99.periodicos.capes.gov.br/record/1"')
        # Each member's own access: another reviewer without one sees no link.
        self.client.force_login(self.agent)
        self.assertNotContains(self.client.get(url, params), "js-access-link")

    def test_article_details_shows_reviewers_tab(self):
        StudyDecision.objects.create(review=self.review, article=self.a1, user=self.agent, status="A")
        self.client.force_login(self.human)
        response = self.client.get(
            reverse("reviews:conducting:article_details"), {"review-id": self.review.pk, "article-id": self.a1.pk}
        )
        self.assertContains(response, "Reviewers")
        self.assertContains(response, "agent")
        self.assertContains(response, "btn-record-decision")
        # The pane is moved inside <form id="article-details"> by JS; a nested <form> would be dropped by browsers.
        self.assertContains(response, 'id="decision-form"')
        self.assertNotContains(response, '<form id="decision-form"')
        self.assertNotContains(response, "{#")  # multi-line {# #} comments are rendered as text by Django

    def test_record_decision(self):
        self.client.force_login(self.human)
        response = self.client.post(
            reverse("reviews:conducting:record_decision"),
            {
                "review-id": self.review.pk,
                "article-id": self.a1.pk,
                "decision-status": "R",
                "decision-stage": "title_abstract",
                "decision-criteria": self.criteria.pk,
                "decision-comments": "out of scope",
            },
        )
        self.assertEqual(200, response.status_code)
        self.assertContains(response, "Your decision was recorded.")
        decision = StudyDecision.objects.get(article=self.a1, user=self.human)
        self.assertEqual(
            ("R", self.criteria, "out of scope"), (decision.status, decision.selection_criteria, decision.comments)
        )
        with self.subTest(msg="consolidated status untouched"):
            self.a1.refresh_from_db()
            self.assertEqual(Article.UNCLASSIFIED, self.a1.status)
        with self.subTest(msg="invalid status"):
            response = self.client.post(
                reverse("reviews:conducting:record_decision"),
                {"review-id": self.review.pk, "article-id": self.a1.pk, "decision-status": "Z"},
            )
            self.assertEqual(400, response.status_code)
        with self.subTest(msg="outsider forbidden"):
            self.client.force_login(self.outsider)
            response = self.client.post(
                reverse("reviews:conducting:record_decision"),
                {"review-id": self.review.pk, "article-id": self.a1.pk, "decision-status": "A"},
            )
            self.assertEqual(403, response.status_code)

    def test_saving_the_study_keeps_its_own_fields_after_the_reviewers_tab_was_opened(self):
        """
        The Reviewers tab sits inside the study's form once opened: saving the study used to send the decision's
        empty comment, status and reason in place of the study's, and the study lost its comments.
        """
        self.client.force_login(self.human)
        details = self.client.get(
            reverse("reviews:conducting:article_details"), {"review-id": self.review.pk, "article-id": self.a1.pk}
        )
        for name in ("decision-status", "decision-stage", "decision-criteria", "decision-comments"):
            self.assertContains(details, f'name="{name}"')
        self.assertNotContains(details, 'name="comments" class="form-control input-sm"')
        fields = {
            "review-id": self.review.pk,
            "article-id": self.a1.pk,
            **{name: "" for name in ("bibtex-key", "author", "journal", "year", "pages", "volume", "abstract")},
            **{name: "" for name in ("document-type", "doi", "url", "affiliation", "author_keywords", "keywords")},
            **{name: "" for name in ("publisher", "issn", "language", "note")},
            "title": "A study",
            "status": "R",
            "selection_criteria": self.criteria.pk,
            "comments": "Excluded: not about screening tools.",
            # What the Reviewers tab adds to the form, as the browser sends it.
            "decision-status": "A",
            "decision-stage": "title_abstract",
            "decision-criteria": "",
            "decision-comments": "",
        }
        response = self.client.post(reverse("reviews:conducting:save_article_details"), fields)
        self.assertEqual(200, response.status_code)
        self.a1.refresh_from_db()
        self.assertEqual(
            ("Excluded: not about screening tools.", "R", self.criteria),
            (self.a1.comments, self.a1.status, self.a1.selection_criteria),
        )
        self.assertFalse(StudyDecision.objects.filter(article=self.a1).exists())  # saving the study records none

    def test_agreement_compares_the_two_reviewers_chosen(self):
        third = UserFactory(username="bob")
        self.review.co_authors.add(third)
        for article, votes in ((self.a1, "AAR"), (self.a2, "RAR")):
            for user, status in zip((self.human, self.agent, third), votes):
                StudyDecision.objects.create(review=self.review, article=article, user=user, status=status)
        self.client.force_login(self.human)
        url = reverse("reviews:conducting:agreement")
        response = self.client.get(url, {"review-id": self.review.pk})
        self.assertContains(response, "agent × alice")  # the first two by default
        self.assertContains(response, 'id="agreement-user-a"', html=False)
        self.assertContains(response, f'<option value="{third.pk}">bob</option>', html=True)
        response = self.client.get(url, {"review-id": self.review.pk, "user-a": self.human.pk, "user-b": third.pk})
        self.assertContains(response, "alice × bob")
        self.assertContains(response, f'<option value="{third.pk}" selected>bob</option>', html=True)
        self.assertContains(response, f'data-article-id="{self.a1.pk}"', html=False)  # alice A, bob R
        self.assertNotContains(response, f'data-article-id="{self.a2.pk}"', html=False)  # both R
        self.assertContains(
            response, "to the decisions of <strong>alice</strong> and\n      <strong>bob</strong>", html=False
        )
        same = self.client.get(url, {"review-id": self.review.pk, "user-a": third.pk, "user-b": third.pk})
        self.assertContains(same, "Choose two different reviewers to compare.")
        response = self.client.post(
            reverse("reviews:conducting:consolidate"),
            {
                "review-id": self.review.pk,
                "stage": "title_abstract",
                "rule": "unanimous",
                "user-a": self.human.pk,
                "user-b": third.pk,
            },
        )
        self.assertContains(response, "the rule decided 1 article(s)")  # a2: alice and bob both R; a1: A and R
        self.assertContains(response, "alice × bob")
        self.a2.refresh_from_db()
        self.assertEqual(Article.REJECTED, self.a2.status)

    def test_data_analysis_shows_the_selection_in_numbers(self):
        Article.objects.filter(pk=self.a1.pk).update(status=Article.REJECTED, selection_criteria=self.criteria)
        Article.objects.filter(pk=self.a2.pk).update(status=Article.DUPLICATED)
        self.client.force_login(self.human)
        page = self.client.get(reverse("data_analysis", args=(self.human.username, self.review.name)))
        self.assertContains(page, "Study Selection in Numbers")
        self.assertContains(page, "<strong>2</strong> imported", html=False)
        self.assertContains(page, "50% of the imported")
        self.assertContains(page, "100% of the not duplicated")  # the one study left is rejected
        self.assertContains(page, "Exclusion Criteria Most Used")
        self.assertContains(page, 'id="analysis-criteria"', html=False)
        self.assertContains(page, "Studies Per Year and Status")

    def test_the_columns_each_user_chooses(self):
        self.client.force_login(self.human)
        url = reverse("reviews:conducting:source_articles")
        params = {"review-id": self.review.pk, "source-id": "None"}
        page = self.client.get(url, params).content.decode()
        headings = [
            heading
            for heading in ("Bibtex Key", "Title", "Author", "AI relevance", "Status")
            if f">{heading}</th>" in page
        ]
        self.assertEqual(["Bibtex Key", "Title", "Author", "AI relevance", "Status"], headings)  # the default
        self.assertNotIn(">DOI</th>", page)

        save = reverse("reviews:conducting:save_study_columns")
        response = self.client.post(save, {"review-id": self.review.pk, "columns": ["status", "doi", "title"]})
        self.assertEqual({"columns": ["status", "doi", "title"]}, response.json())
        page = self.client.get(url, params).content.decode()
        self.assertLess(page.index(">Status</th>"), page.index(">DOI</th>"))
        self.assertLess(page.index(">DOI</th>"), page.index(">Title</th>"))
        self.assertNotIn(">Author</th>", page)
        self.assertNotIn('class="ai-header"', page)
        self.assertIn(f'article-title="{self.a1.title}"', page)  # the search reads the row, whatever is shown
        # Another user keeps the default; the Columns window lists the user's columns first, checked.
        self.client.force_login(self.agent)
        self.assertIn(">Author</th>", self.client.get(url, params).content.decode())
        self.client.force_login(self.human)
        window = self.client.get(reverse("study_selection", args=(self.human.username, self.review.name)))
        self.assertContains(window, 'id="modal-columns"', html=False)
        content = window.content.decode()
        self.assertLess(content.index('data-key="status"'), content.index('data-key="author"'))
        self.assertEqual(400, self.client.post(save, {"review-id": self.review.pk, "columns": []}).status_code)
        self.assertIn(
            "Unknown column", self.client.post(save, {"review-id": self.review.pk, "columns": ["x"]}).json()["error"]
        )

    def test_agreement_and_consolidate(self):
        for article, human, agent in ((self.a1, "A", "A"), (self.a2, "A", "R")):
            StudyDecision.objects.create(review=self.review, article=article, user=self.human, status=human)
            StudyDecision.objects.create(review=self.review, article=article, user=self.agent, status=agent)
        self.client.force_login(self.human)

        response = self.client.get(reverse("reviews:conducting:agreement"), {"review-id": self.review.pk})
        self.assertEqual(200, response.status_code)
        self.assertContains(response, "agent × alice")
        self.assertContains(response, "Cohen")
        self.assertContains(response, self.a2.title)  # the disagreement
        # each disagreement opens its article's details (from the page's script)
        self.assertContains(response, f'class="js-open-article" data-article-id="{self.a2.pk}"', html=False)
        self.assertNotContains(response, f'data-article-id="{self.a1.pk}"', html=False)
        self.assertEqual(
            400,
            self.client.get(
                reverse("reviews:conducting:agreement"), {"review-id": self.review.pk, "stage": "x"}
            ).status_code,
        )

        response = self.client.post(
            reverse("reviews:conducting:consolidate"),
            {"review-id": self.review.pk, "stage": "title_abstract", "rule": "unanimous"},
        )
        self.assertEqual(200, response.status_code)
        self.assertContains(
            response, "the rule decided 1 article(s), 1 of them changed status (the others already had it);"
        )
        self.assertContains(response, "1 could not be decided and kept their status.")
        self.assertContains(response, "rule <strong>Unanimous</strong> at stage <strong>Title and abstract")
        self.assertNotContains(response, "<strong>title_abstract</strong>")
        self.a1.refresh_from_db()
        self.a2.refresh_from_db()
        self.assertEqual(("A", "U"), (self.a1.status, self.a2.status))
        self.assertEqual(
            400,
            self.client.post(
                reverse("reviews:conducting:consolidate"), {"review-id": self.review.pk, "rule": "coin"}
            ).status_code,
        )

    def test_disagreements_show_the_status_now_and_the_rule_used_stays_selected(self):
        StudyDecision.objects.create(review=self.review, article=self.a1, user=self.human, status="U")
        StudyDecision.objects.create(review=self.review, article=self.a1, user=self.agent, status="R")
        Article.objects.filter(pk=self.a1.pk).update(status="R", updated_by=self.agent)
        self.client.force_login(self.human)
        response = self.client.get(reverse("reviews:conducting:agreement"), {"review-id": self.review.pk})
        self.assertContains(response, "<th>Status now</th>", html=True)
        self.assertContains(response, '<span class="label label-danger">Rejected</span>', html=True)
        self.assertContains(response, '<small class="text-muted">by agent</small>', html=True)
        self.assertContains(response, "Status now set by:")
        self.assertContains(response, "<strong>agent</strong> (1)")
        self.assertContains(response, "Consolidating does not remove a disagreement")

        response = self.client.post(
            reverse("reviews:conducting:consolidate"), {"review-id": self.review.pk, "rule": "majority"}
        )
        self.assertContains(response, "the rule decided 0 article(s), 0 of them changed status")  # a tie
        self.assertContains(response, '<option value="majority" selected>', html=False)
        self.assertContains(response, self.a1.title)  # still a disagreement

    def test_agreement_without_decisions(self):
        self.client.force_login(self.human)
        response = self.client.get(reverse("reviews:conducting:agreement"), {"review-id": self.review.pk})
        self.assertContains(response, "No independent decisions yet")
        self.assertContains(response, "At least two reviewers")
