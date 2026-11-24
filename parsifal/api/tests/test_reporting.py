from parsifal.api.tests.base import ApiTestCase
from parsifal.apps.reviews.services import threats


class TestThreatsApi(ApiTestCase):
    def test_types(self):
        body = self.api("get", "/threats/types").json()
        self.assertEqual(list(threats.SUGGESTED_TYPES), body["types"])
        self.assertIn(
            {
                "title": "Poorly designed data extraction forms and recording of the data",
                "category": "Descriptive validity",
            },
            body["examples"],
        )

    def test_crud(self):
        path = self.review_path("/threats")
        response = self.api(
            "post",
            path,
            {"title": "One reviewer", "category": "Theoretical validity", "description": "Studies may be missed."},
        )
        self.assertEqual(201, response.status_code, response.content)
        threat = response.json()
        self.assertEqual(("One reviewer", "", 0), (threat["title"], threat["mitigation"], threat["order"]))
        body = self.api("patch", f"{path}/{threat['id']}", {"mitigation": "A test set."}).json()
        self.assertEqual(("Theoretical validity", "A test set."), (body["category"], body["mitigation"]))
        self.assertEqual(["One reviewer"], [t["title"] for t in self.api("get", path).json()])
        self.assertEqual(422, self.api("post", path, {"title": ""}).status_code)
        self.assertEqual(422, self.api("patch", f"{path}/{threat['id']}", {"title": " "}).status_code)
        with self.subTest(msg="a co-author too; not an outsider"):
            co_author = self.client_for(self.co_author)
            self.assertEqual(200, self.api("get", path, client=co_author).status_code)
            self.assertEqual(404, self.api("get", path, client=self.client_for(self.outsider)).status_code)
        self.assertEqual(204, self.api("delete", f"{path}/{threat['id']}").status_code)
        self.assertEqual(404, self.api("delete", f"{path}/{threat['id']}").status_code)
        self.assertEqual("api", self.review.events.order_by("pk").last().via)
