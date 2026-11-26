from django.contrib.auth.models import User
from django.test import TestCase


class HomeUnauthenticatedUser(TestCase):
    def setUp(self):
        self.response = self.client.get("/")

    def test_get(self):
        self.assertEqual(self.response.status_code, 200)

    def test_template(self):
        self.assertTemplateUsed(self.response, "core/cover.html")

    def test_landing_sections_and_assets(self):
        self.assertContains(self.response, "cover.css")
        self.assertContains(self.response, "cover.js")
        self.assertContains(self.response, 'id="workspace-preview"')
        self.assertContains(self.response, "PRISMA 2020")
        self.assertContains(self.response, "Rapid Reviews")
        self.assertContains(self.response, "Systematic Mapping Studies")
        self.assertContains(self.response, "parsifal-mcp")
        self.assertContains(
            self.response,
            "https://www.elsevier.com/__data/promis_misc/525444systematicreviewsguide.pdf",
        )
        self.assertContains(self.response, "https://doi.org/10.1016/j.infsof.2015.03.007")
        self.assertContains(self.response, "https://arxiv.org/abs/2003.10006")
        self.assertContains(self.response, "Helder Junior")
        self.assertContains(self.response, 'class="site-footer"')
        self.assertNotContains(self.response, "Log in to Parsifal")


class HomeAuthenticatedUser(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="john", password="s3cr3tp4ssw0rd", email="john@doe.com")
        self.client.login(username="john", password="s3cr3tp4ssw0rd")
        self.response = self.client.get("/")

    def test_get(self):
        self.assertEqual(self.response.status_code, 200)

    def test_template(self):
        self.assertTemplateUsed(self.response, "core/home.html")


class AboutPage(TestCase):
    def test_get(self):
        response = self.client.get("/about/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/about.html")
        self.assertContains(response, "Helder Junior")
        self.assertContains(response, "Rapid Reviews")
        self.assertContains(response, "https://arxiv.org/abs/2003.10006")
        self.assertContains(response, "https://doi.org/10.1016/j.infsof.2015.03.007")
        self.assertContains(response, "https://doi.org/10.1136/bmj.n71")
