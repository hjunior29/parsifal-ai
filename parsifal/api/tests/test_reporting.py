import hashlib

from django.core.files.uploadedfile import SimpleUploadedFile

from parsifal.api.tests.base import ApiTestCase
from parsifal.apps.core.tests.files import PDF, TemporaryFilesMixin
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


class TestManuscriptsApi(TemporaryFilesMixin, ApiTestCase):
    def upload(self, manuscript_id, content=PDF, name="paper.pdf", notes=None, client=None):
        data = {"file": SimpleUploadedFile(name, content)}
        if notes is not None:
            data["notes"] = notes
        return (client or self.client).post(
            f"/api/v1{self.review_path(f'/manuscripts/{manuscript_id}/versions')}", data
        )

    def test_manuscripts_and_their_versions(self):
        path = self.review_path("/manuscripts")
        response = self.api("post", path, {"name": "Full paper", "description": "SBES template"})
        self.assertEqual(201, response.status_code, response.content)
        paper = response.json()
        self.assertEqual(("Full paper", "SBES template", []), (paper["name"], paper["description"], paper["versions"]))
        self.assertEqual(422, self.api("post", path, {"name": "full paper"}).status_code)

        response = self.upload(paper["id"], notes="First draft")
        self.assertEqual(201, response.status_code, response.content)
        first = response.json()
        self.assertEqual(
            {
                "number": 1,
                "filename": "paper.pdf",
                "content_type": "application/pdf",
                "size": len(PDF),
                "sha256": hashlib.sha256(PDF).hexdigest(),
                "notes": "First draft",
                "created_by": self.author.username,
            },
            {
                key: first[key]
                for key in ("number", "filename", "content_type", "size", "sha256", "notes", "created_by")
            },
        )
        second = self.upload(paper["id"], name="paper v2.pdf").json()
        self.assertEqual(2, second["number"])
        self.assertEqual(422, self.upload(paper["id"], content=b"not a pdf").status_code)
        listed = self.api("get", path).json()
        self.assertEqual([2, 1], [version["number"] for version in listed[0]["versions"]])

        download = self.api("get", self.review_path(f"/manuscripts/{paper['id']}/versions/{first['id']}/file"))
        self.assertEqual(200, download.status_code)
        self.assertEqual(PDF, b"".join(download.streaming_content))
        self.assertIn('filename="paper.pdf"', download["Content-Disposition"])

        body = self.api("patch", f"{path}/{paper['id']}", {"name": "Journal article"}).json()
        self.assertEqual(("Journal article", "SBES template"), (body["name"], body["description"]))
        self.assertEqual(
            204, self.api("delete", self.review_path(f"/manuscripts/{paper['id']}/versions/{first['id']}")).status_code
        )
        self.assertEqual([2], [v["number"] for v in self.api("get", path).json()[0]["versions"]])
        self.assertEqual(204, self.api("delete", f"{path}/{paper['id']}").status_code)
        self.assertEqual([], self.api("get", path).json())

    def test_members_only(self):
        paper = self.api("post", self.review_path("/manuscripts"), {"name": "Full paper"}).json()
        version = self.upload(paper["id"]).json()
        outsider = self.client_for(self.outsider)
        file_path = self.review_path(f"/manuscripts/{paper['id']}/versions/{version['id']}/file")
        self.assertEqual(404, self.api("get", file_path, client=outsider).status_code)
        self.assertEqual(404, self.upload(paper["id"], client=outsider).status_code)
        self.assertEqual(200, self.api("get", file_path, client=self.client_for(self.co_author)).status_code)
