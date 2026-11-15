from django.test import TestCase
from django.urls import reverse

from parsifal.apps.reviews.models import ReviewEvent, SearchSession
from parsifal.apps.reviews.tests.factories import ArticleFactory, ReviewFactory, SourceFactory

EMPTY = ("bibtex-key", "author", "journal", "pages", "volume", "abstract", "document-type", "doi", "url")
EMPTY += ("affiliation", "author_keywords", "keywords", "publisher", "issn", "language", "note", "comments")


def conducting(name):
    return reverse(f"reviews:conducting:{name}")


class ConductingHistoryTest(TestCase):
    """The web views of Conducting that change the review themselves record it as the services do."""

    @classmethod
    def setUpTestData(cls):
        cls.scopus = SourceFactory(name="Scopus")
        cls.review = ReviewFactory(sources=[cls.scopus])
        SearchSession.objects.create(review=cls.review, source=None, search_string="a AND b")

    def setUp(self):
        self.client.force_login(self.review.author)

    def summaries(self):
        return list(self.review.events.order_by("pk").values_list("summary", flat=True))

    def study(self, article_id, **fields):
        data = {"review-id": self.review.pk, "article-id": article_id, "source-id": self.scopus.pk}
        data.update({name: "" for name in EMPTY}, title="A study", year="", status="U", selection_criteria="")
        data.update(fields)
        self.assertEqual(200, self.client.post(conducting("save_article_details"), data).status_code)

    def test_study_window(self):
        self.study("None")
        article = self.review.article_set.get()
        self.study(article.pk, year="2021", status="A")
        self.study(article.pk, year="2021", status="A")  # nothing changes
        self.assertEqual(
            [
                "Added the study “A study” to “Scopus”",
                "Changed the details of the study “A study”",
                "Accepted the study “A study”",
            ],
            self.summaries(),
        )
        event = self.review.events.order_by("pk").last()
        self.assertEqual((self.review.author, ReviewEvent.WEB), (event.actor, event.via))
        self.assertEqual([article], list(event.articles.all()))

    def test_search_strings(self):
        data = {"review-id": self.review.pk, "source-id": self.scopus.pk}
        self.client.post(conducting("save_source_string"), {**data, "search_string": "TITLE(a)"})
        self.client.post(conducting("import_base_string"), data)
        self.client.post(conducting("remove_source_string"), data)
        self.assertEqual(
            [
                "Added the search string of “Scopus”",
                "Changed the search string of “Scopus”",
                "Removed the search string of “Scopus”",
            ],
            self.summaries(),
        )

    def test_the_study_history_link(self):
        article = ArticleFactory(review=self.review, title="A study")
        response = self.client.get(conducting("study_window"), {"review-id": self.review.pk, "article-id": article.pk})
        url = reverse("review_history", args=(self.review.author.username, self.review.name))
        self.assertContains(response, f'href="{url}?study={article.pk}"')
