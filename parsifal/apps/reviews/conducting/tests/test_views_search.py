from django.test import TestCase
from django.urls import reverse

from parsifal.apps.accounts import services as integrations
from parsifal.apps.reviews.models import SearchSession
from parsifal.apps.reviews.tests.factories import ReviewFactory, SourceFactory

PROXY = "ez99.periodicos.capes.gov.br"


class SearchPageTest(TestCase):
    """Search: each string to copy, and each source a link away, also through the user's library proxy."""

    @classmethod
    def setUpTestData(cls):
        cls.scopus = SourceFactory(name="Scopus", url="http://www.scopus.com")
        cls.review = ReviewFactory(sources=[cls.scopus])
        generic = cls.review.get_generic_search_string()
        generic.search_string = '"rapid review" AND "software engineering"'
        generic.save()
        SearchSession.objects.create(review=cls.review, source=cls.scopus, search_string='TITLE-ABS-KEY("rapid")')
        cls.page = reverse("search_studies", args=(cls.review.author.username, cls.review.name))

    def test_the_strings_can_be_copied_and_the_source_opened(self):
        self.client.force_login(self.review.author)
        response = self.client.get(self.page)
        self.assertContains(response, 'data-text="&quot;rapid review&quot; AND &quot;software engineering&quot;"')
        self.assertContains(response, 'data-copy-from="#search-string-{0}"'.format(self.scopus.pk))
        self.assertContains(response, 'id="search-string-{0}"'.format(self.scopus.pk))
        self.assertContains(response, 'href="http://www.scopus.com"')
        self.assertContains(response, "Open Scopus")
        self.assertNotContains(response, "Via CAPES")

    def test_through_the_library_proxy(self):
        integrations.save_library_access(self.review.author, address=PROXY)
        self.client.force_login(self.review.author)
        response = self.client.get(self.page)
        self.assertContains(response, 'href="https://www-scopus-com.{0}/"'.format(PROXY))
        self.assertContains(response, "Via CAPES")
