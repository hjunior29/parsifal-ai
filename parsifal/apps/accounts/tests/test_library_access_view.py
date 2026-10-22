from django.test import TestCase
from django.urls import reverse

from parsifal.apps.accounts.models import LibraryAccess
from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.utils.test import login_redirect_url

PROXY = "ez99.periodicos.capes.gov.br"


class TestLibraryAccessView(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.other = UserFactory()
        cls.url = reverse("settings:library_access")

    def setUp(self):
        self.client.force_login(self.user)

    def test_login_required(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), login_redirect_url(self.url))

    def test_the_page_explains_how_to_set_it_up(self):
        response = self.client.get(self.url)
        self.assertContains(response, "not configured")
        self.assertContains(response, "Acesso CAFe")
        self.assertContains(response, "How to set it up")
        self.assertContains(response, "never asks for your CAFe login")
        self.assertContains(response, reverse("docs:page", args=("library-access",)))
        self.assertContains(self.client.get(reverse("settings:profile")), self.url)  # in the settings menu

    def test_save_from_the_address_of_a_page_opened_through_capes(self):
        address = f"https://ieeexplore-ieee-org.{PROXY}/document/1234567"
        response = self.client.post(self.url, {"action": "save", "address": address}, follow=True)
        self.assertContains(response, f"Studies now open through {PROXY} with Via CAPES")
        self.assertContains(response, f"https://doi-org.{PROXY}/")
        self.assertEqual(PROXY, LibraryAccess.objects.get(user=self.user).proxy)
        # Saving again replaces it.
        self.client.post(self.url, {"action": "save", "address": "ezproxy.example.edu"})
        self.assertEqual(["ezproxy.example.edu"], list(LibraryAccess.objects.values_list("proxy", flat=True)))

    def test_what_cannot_be_saved_is_explained(self):
        response = self.client.post(self.url, {"action": "save", "address": "https://www.periodicos.capes.gov.br/"})
        self.assertContains(response, "the CAPES portal itself")
        self.assertContains(response, 'value="https://www.periodicos.capes.gov.br/"')  # kept to be corrected
        self.assertFalse(LibraryAccess.objects.exists())

    def test_remove(self):
        LibraryAccess.objects.create(user=self.user, proxy=PROXY)
        LibraryAccess.objects.create(user=self.other, proxy=PROXY)
        response = self.client.post(self.url, {"action": "remove"}, follow=True)
        self.assertContains(response, "The library access was removed.")
        self.assertEqual([self.other.pk], list(LibraryAccess.objects.values_list("user", flat=True)))
