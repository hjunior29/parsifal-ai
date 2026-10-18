from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from parsifal.apps.accounts.models import ApiToken
from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.tests.factories import ReviewFactory
from parsifal.utils.test import login_redirect_url


class TestManageAccessView(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = UserFactory()
        cls.co_author = UserFactory()
        cls.other = UserFactory(username="newbie")
        cls.review = ReviewFactory(author=cls.author, co_authors=[cls.co_author])
        cls.url = reverse("manage_access", args=(cls.author.username, cls.review.name))

    def test_login_required(self):
        self.assertRedirects(self.client.get(self.url), login_redirect_url(self.url))

    def test_main_author_required(self):
        self.client.force_login(self.co_author)
        self.assertEqual(403, self.client.get(self.url).status_code)

    def test_get_lists_members(self):
        self.client.force_login(self.author)
        response = self.client.get(self.url)
        self.assertEqual(200, response.status_code)
        self.assertContains(response, self.co_author.username)
        self.assertContains(response, "Main author")

    def test_no_way_to_add_an_existing_account(self):
        self.client.force_login(self.author)
        response = self.client.get(self.url)
        self.assertNotContains(response, "existing account")
        self.client.post(self.url, {"action": "add", "username": self.other.username}, follow=True)
        self.assertFalse(self.review.is_author_or_coauthor(self.other))

    def test_create_agent_shows_the_token_once(self):
        self.client.force_login(self.author)
        response = self.client.post(self.url, {"action": "create_agent", "name": "Triagem Claude"})
        self.assertEqual(200, response.status_code)
        agent = self.review.agents.get()
        token = response.context["new_token"]
        self.assertContains(response, token)
        self.assertEqual("agent-triagem-claude", agent.user.username)
        self.assertTrue(self.review.is_author_or_coauthor(agent.user))
        self.assertFalse(agent.user.has_usable_password())
        self.assertEqual(agent.user, ApiToken.objects.authenticate(token))
        self.assertNotContains(self.client.get(self.url), token)

    def test_page_states_what_deleting_an_agent_removes(self):
        self.client.force_login(self.author)
        self.client.post(self.url, {"action": "create_agent", "name": "Bot"})
        response = self.client.get(self.url)
        for text in ("AI agent", "Delete agent", "its account, its API tokens and everything recorded under it"):
            self.assertContains(response, text)
        self.assertContains(response, "permanently deletes its account, its API tokens and everything it recorded")

    def test_new_token_and_delete(self):
        self.client.force_login(self.author)
        first = self.client.post(self.url, {"action": "create_agent", "name": "Bot"}).context["new_token"]
        agent = self.review.agents.get()
        second = self.client.post(self.url, {"action": "new_token", "user_id": agent.user_id}).context["new_token"]
        self.assertIsNone(ApiToken.objects.authenticate(first))
        self.assertEqual(agent.user, ApiToken.objects.authenticate(second))

        response = self.client.post(self.url, {"action": "delete_agent", "user_id": agent.user_id}, follow=True)
        self.assertContains(response, "Agent Bot and everything it recorded were deleted.")
        self.assertFalse(User.objects.filter(pk=agent.user_id).exists())
        self.assertIsNone(ApiToken.objects.authenticate(second))

    def test_other_co_authors_cannot_manage_agents(self):
        self.client.force_login(self.co_author)
        response = self.client.post(self.url, {"action": "create_agent", "name": "Sneaky"})
        self.assertEqual(403, response.status_code)
        self.assertFalse(self.review.agents.exists())
