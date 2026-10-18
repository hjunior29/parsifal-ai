from parsifal.api.tests.base import ApiTestCase
from parsifal.apps.reviews.models import Review
from parsifal.apps.reviews.tests.factories import DefaultSourceFactory, ReviewFactory


class TestReviews(ApiTestCase):
    def test_list_is_scoped_to_membership(self):
        ReviewFactory()  # someone else's review
        with self.subTest(msg="author sees own review"):
            body = self.api("get", "/reviews").json()
            self.assertEqual(1, body["count"])
            self.assertEqual(self.review.pk, body["items"][0]["id"])
            self.assertEqual([self.co_author.username], body["items"][0]["co_authors"])
        with self.subTest(msg="co-author sees it too"):
            self.assertEqual(1, self.api("get", "/reviews", client=self.client_for(self.co_author)).json()["count"])
        with self.subTest(msg="outsider sees nothing"):
            self.assertEqual(0, self.api("get", "/reviews", client=self.client_for(self.outsider)).json()["count"])
        with self.subTest(msg="admin sees everything"):
            self.assertEqual(2, self.api("get", "/reviews", client=self.client_for(self.admin)).json()["count"])
        with self.subTest(msg="filters"):
            self.assertEqual(
                1, self.api("get", f"/reviews?author={self.author.username}&name={self.review.name}").json()["count"]
            )
            self.assertEqual(0, self.api("get", "/reviews?q=nomatchxyz").json()["count"])

    def test_create_get_update(self):
        response = self.api("post", "/reviews", {"title": "LLMs in SE", "description": "d"})
        self.assertEqual(201, response.status_code)
        body = response.json()
        self.assertEqual(("llms-in-se", self.author.username), (body["name"], body["author"]))

        response = self.api(
            "patch", f"/reviews/{body['id']}", {"objective": "Map the field", "population": "devs, teams"}
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("Map the field", response.json()["objective"])

        with self.subTest(msg="empty patch"):
            self.assertEqual(422, self.api("patch", f"/reviews/{body['id']}", {}).status_code)
        with self.subTest(msg="too long"):
            self.assertEqual(422, self.api("patch", f"/reviews/{body['id']}", {"description": "x" * 501}).status_code)
        with self.subTest(msg="outsider gets 404"):
            self.assertEqual(
                404, self.api("get", f"/reviews/{body['id']}", client=self.client_for(self.outsider)).status_code
            )

    def test_overview(self):
        body = self.api("get", self.review_path("/overview")).json()
        self.assertEqual(self.review.pk, body["id"])
        self.assertEqual(0, body["articles"]["total"])

    def test_owner_only_operations(self):
        co = self.client_for(self.co_author)
        self.assertEqual(403, self.api("put", self.review_path("/name"), {"name": "new-name"}, client=co).status_code)
        self.assertEqual(403, self.api("delete", self.review_path(), client=co).status_code)

    def test_rename_and_delete(self):
        response = self.api("put", self.review_path("/name"), {"name": "renamed"})
        self.assertEqual("renamed", response.json()["name"])
        self.assertEqual(422, self.api("put", self.review_path("/name"), {"name": "Not Slug"}).status_code)
        with self.subTest(msg="co-author cannot delete"):
            response = self.api("delete", self.review_path(), client=self.client_for(self.co_author))
            self.assertEqual(403, response.status_code)
        with self.subTest(msg="owner deletes"):
            self.assertEqual(204, self.api("delete", self.review_path()).status_code)
            self.assertFalse(Review.objects.filter(pk=self.review.pk).exists())

    def test_members(self):
        with self.subTest(msg="list"):
            usernames = [m["username"] for m in self.api("get", self.review_path("/members")).json()]
            self.assertEqual([self.author.username, self.co_author.username], usernames)
        with self.subTest(msg="humans can no longer be added or removed through the API"):
            self.assertEqual(405, self.api("post", self.review_path("/members"), {"username": "x"}).status_code)
            self.assertEqual(404, self.api("delete", self.review_path(f"/members/{self.co_author.pk}")).status_code)

    def test_default_sources(self):
        DefaultSourceFactory(name="Scopus")
        names = [s["name"] for s in self.api("get", "/sources/defaults").json()]
        self.assertIn("Scopus", names)
