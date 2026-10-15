import re

from django.test import TestCase
from django.urls import reverse

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.docs import pages

LINK = re.compile(r'href="(/docs/[^"#]*)')


class TestDocsPages(TestCase):
    def test_every_page_renders_for_everyone(self):
        user = UserFactory()
        for page in pages.PAGES:
            url = reverse("docs:index") if page.slug == "index" else reverse("docs:page", args=(page.slug,))
            with self.subTest(page=page.slug, who="anonymous"):
                response = self.client.get(url)
                self.assertEqual(200, response.status_code)
                self.assertContains(response, page.title)
                self.assertContains(response, 'class="list-group-item active"')
            with self.subTest(page=page.slug, who="authenticated"):
                self.client.force_login(user)
                self.assertEqual(200, self.client.get(url).status_code)
                self.client.logout()

    def test_every_content_file_has_a_page_and_vice_versa(self):
        files = {path.stem for path in pages.CONTENT_DIR.glob("*.md")}
        self.assertEqual(files, set(pages.BY_SLUG))

    def test_unknown_page_is_404(self):
        self.assertEqual(404, self.client.get("/docs/nothing-here/").status_code)

    def test_internal_links_resolve(self):
        for page in pages.PAGES:
            url = reverse("docs:index") if page.slug == "index" else reverse("docs:page", args=(page.slug,))
            html = self.client.get(url).content.decode()
            for link in set(LINK.findall(html)):
                with self.subTest(page=page.slug, link=link):
                    self.assertEqual(200, self.client.get(link).status_code)

    def test_markdown_features_render(self):
        response = self.client.get(reverse("docs:page", args=("api",)))
        self.assertContains(response, "<table>")
        self.assertContains(response, "<pre><code")
        self.assertContains(response, 'href="/api/v1/docs"')

    def test_header_links_to_docs(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, reverse("docs:index"))
