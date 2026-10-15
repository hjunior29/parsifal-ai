import json

from django.test import Client, TestCase

from parsifal.apps.accounts.models import ApiToken
from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.tests.factories import ReviewFactory, SourceFactory

API = "/api/v1"


class ApiTestCase(TestCase):
    """Creates an author with a token-authenticated client, a co-author, an outsider and a review."""

    @classmethod
    def setUpTestData(cls):
        cls.author = UserFactory()
        cls.co_author = UserFactory()
        cls.outsider = UserFactory()
        cls.admin = UserFactory(is_superuser=True, is_staff=True)
        cls.source = SourceFactory()
        cls.review = ReviewFactory(author=cls.author, co_authors=[cls.co_author], sources=[cls.source])
        cls.keys = {}
        for user in (cls.author, cls.co_author, cls.outsider, cls.admin):
            _token, cls.keys[user.pk] = ApiToken.create_for(user, "tests")

    def client_for(self, user):
        return Client(headers={"Authorization": f"Bearer {self.keys[user.pk]}"})

    def setUp(self):
        self.client = self.client_for(self.author)

    def api(self, method, path, payload=None, client=None, **kwargs):
        client = client or self.client
        url = f"{API}{path}"
        if payload is not None:
            kwargs.update(data=json.dumps(payload), content_type="application/json")
        return getattr(client, method.lower())(url, **kwargs)

    def review_path(self, suffix=""):
        return f"/reviews/{self.review.pk}{suffix}"
