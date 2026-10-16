from pathlib import Path

from parsifal.api.tests.base import API, ApiTestCase
from parsifal.apps.library.models import Document, Folder

DATA = Path(__file__).resolve().parents[2] / "apps" / "reviews" / "tests" / "data"

BIBTEX = """
@article{Smith2020,
  title = {Automating study selection},
  author = {Smith, John and Doe, Jane},
  journal = {Journal of Testing},
  year = {2020},
  doi = {10.1000/xyz},
  author_keywords = {slr; automation},
  link = {https://example.org/smith2020},
  correspondence_address1 = {Somewhere},
}
@inproceedings{Jones2019,
  title = {A mapping study},
  author = {Jones, Ann},
  booktitle = {Proc. of Testing},
  year = {2019},
}
"""


class TestFolders(ApiTestCase):
    def test_crud_and_scoping(self):
        response = self.api("post", "/library/folders", {"name": "Thesis"})
        self.assertEqual(201, response.status_code)
        folder = response.json()
        self.assertEqual({"id": folder["id"], "name": "Thesis", "slug": "thesis", "document_count": 0}, folder)

        with self.subTest(msg="duplicate name conflicts, blank name is invalid"):
            self.assertEqual(409, self.api("post", "/library/folders", {"name": "Thesis"}).status_code)
            self.assertEqual(422, self.api("post", "/library/folders", {"name": "  "}).status_code)
            self.assertEqual(422, self.api("post", "/library/folders", {"name": "x" * 51}).status_code)

        with self.subTest(msg="listed for the owner only"):
            self.assertEqual(["Thesis"], [f["name"] for f in self.api("get", "/library/folders").json()])
            self.assertEqual([], self.api("get", "/library/folders", client=self.client_for(self.outsider)).json())

        with self.subTest(msg="rename"):
            response = self.api("patch", f"/library/folders/{folder['id']}", {"name": "PhD"})
            self.assertEqual(200, response.status_code)
            self.assertEqual("PhD", response.json()["name"])

        with self.subTest(msg="other users get 404"):
            outsider = self.client_for(self.outsider)
            self.assertEqual(
                404,
                self.api(
                    "get", "/library/documents", client=outsider, QUERY_STRING=f"folder_id={folder['id']}"
                ).status_code,
            )
            self.assertEqual(
                404,
                self.api("patch", f"/library/folders/{folder['id']}", {"name": "Mine"}, client=outsider).status_code,
            )
            self.assertEqual(404, self.api("delete", f"/library/folders/{folder['id']}", client=outsider).status_code)
            self.assertTrue(Folder.objects.filter(pk=folder["id"]).exists())

        with self.subTest(msg="delete keeps the documents"):
            document = self.api("post", "/library/documents", {"title": "Kept"}).json()
            self.api("post", f"/library/folders/{folder['id']}/documents", {"ids": [document["id"]]})
            self.assertEqual(204, self.api("delete", f"/library/folders/{folder['id']}").status_code)
            self.assertFalse(Folder.objects.filter(pk=folder["id"]).exists())
            self.assertTrue(Document.objects.filter(pk=document["id"]).exists())
            self.assertEqual(404, self.api("delete", f"/library/folders/{folder['id']}").status_code)


class TestDocuments(ApiTestCase):
    def test_create_get_update_delete(self):
        response = self.api(
            "post",
            "/library/documents",
            {"entry_type": "Article", "title": "Automating study selection", "year": "2020", "doi": "10.1000/xyz"},
        )
        self.assertEqual(201, response.status_code)
        document = response.json()
        self.assertEqual("article", document["entry_type"])
        self.assertEqual([], document["folder_ids"])
        self.assertIsNone(document["journal"])

        with self.subTest(msg="validation"):
            self.assertEqual(
                422, self.api("post", "/library/documents", {"entry_type": "poem", "title": "x"}).status_code
            )
            self.assertEqual(422, self.api("post", "/library/documents", {"abstract": "no title"}).status_code)
            self.assertEqual(422, self.api("post", "/library/documents", {"title": "x", "year": "y" * 51}).status_code)

        with self.subTest(msg="patch changes only the fields sent; null clears"):
            response = self.api("patch", f"/library/documents/{document['id']}", {"journal": "JoT", "doi": None})
            self.assertEqual(200, response.status_code)
            self.assertEqual(
                ("JoT", None, "2020"), (response.json()["journal"], response.json()["doi"], response.json()["year"])
            )

        with self.subTest(msg="scoped to the owner"):
            outsider = self.client_for(self.outsider)
            self.assertEqual(404, self.api("get", f"/library/documents/{document['id']}", client=outsider).status_code)
            self.assertEqual(
                404,
                self.api(
                    "patch", f"/library/documents/{document['id']}", {"title": "Hijack"}, client=outsider
                ).status_code,
            )
            self.assertEqual(
                404, self.api("delete", f"/library/documents/{document['id']}", client=outsider).status_code
            )
            self.assertEqual(
                404,
                self.api("post", "/library/documents/delete", {"ids": [document["id"]]}, client=outsider).status_code,
            )

        with self.subTest(msg="delete"):
            self.assertEqual(200, self.api("get", f"/library/documents/{document['id']}").status_code)
            self.assertEqual(204, self.api("delete", f"/library/documents/{document['id']}").status_code)
            self.assertEqual(404, self.api("get", f"/library/documents/{document['id']}").status_code)

    def test_list_filter_order_and_folders(self):
        ids = [
            self.api("post", "/library/documents", {"title": title, "author": author, "year": year}).json()["id"]
            for title, author, year in (("Beta", "Zed", "2019"), ("Alpha", "Young", "2021"), ("Gamma", "Xi", "2020"))
        ]
        Document.objects.create(user=self.outsider, title="Alpha of someone else")

        with self.subTest(msg="default order is title; only my documents"):
            response = self.api("get", "/library/documents")
            self.assertEqual(200, response.status_code)
            self.assertEqual(3, response.json()["count"])
            self.assertEqual(["Alpha", "Beta", "Gamma"], [d["title"] for d in response.json()["items"]])

        with self.subTest(msg="order and search"):
            titles = [
                d["title"] for d in self.api("get", "/library/documents", QUERY_STRING="order=-year").json()["items"]
            ]
            self.assertEqual(["Alpha", "Gamma", "Beta"], titles)
            titles = [d["title"] for d in self.api("get", "/library/documents", QUERY_STRING="q=amm").json()["items"]]
            self.assertEqual(["Gamma"], titles)
            self.assertEqual(422, self.api("get", "/library/documents", QUERY_STRING="order=doi").status_code)

        with self.subTest(msg="pagination"):
            page = self.api("get", "/library/documents", QUERY_STRING="limit=2&offset=2").json()
            self.assertEqual((3, 1), (page["count"], len(page["items"])))

        inbox = self.api("post", "/library/folders", {"name": "Inbox"}).json()
        done = self.api("post", "/library/folders", {"name": "Done"}).json()
        with self.subTest(msg="add to folder"):
            response = self.api("post", f"/library/folders/{inbox['id']}/documents", {"ids": ids[:2]})
            self.assertEqual(200, response.status_code)
            self.assertEqual(2, response.json()["document_count"])
            titles = [
                d["title"]
                for d in self.api("get", "/library/documents", QUERY_STRING=f"folder_id={inbox['id']}").json()["items"]
            ]
            self.assertEqual(["Alpha", "Beta"], titles)
            self.assertEqual([inbox["id"]], self.api("get", f"/library/documents/{ids[0]}").json()["folder_ids"])

        with self.subTest(msg="documents of another user cannot be added"):
            foreign = Document.objects.get(user=self.outsider)
            self.assertEqual(
                404, self.api("post", f"/library/folders/{inbox['id']}/documents", {"ids": [foreign.pk]}).status_code
            )

        with self.subTest(msg="move"):
            response = self.api(
                "post", f"/library/folders/{inbox['id']}/documents/move", {"ids": [ids[0]], "to_folder_id": done["id"]}
            )
            self.assertEqual(200, response.status_code)
            self.assertEqual(("Done", 1), (response.json()["name"], response.json()["document_count"]))
            self.assertEqual(
                [ids[1]],
                [
                    d["id"]
                    for d in self.api("get", "/library/documents", QUERY_STRING=f"folder_id={inbox['id']}").json()[
                        "items"
                    ]
                ],
            )

        with self.subTest(msg="remove from folder keeps the document"):
            response = self.api("post", f"/library/folders/{inbox['id']}/documents/remove", {"ids": [ids[1]]})
            self.assertEqual(0, response.json()["document_count"])
            self.assertEqual(200, self.api("get", f"/library/documents/{ids[1]}").status_code)

        with self.subTest(msg="batch delete"):
            response = self.api("post", "/library/documents/delete", {"ids": ids})
            self.assertEqual(200, response.status_code)
            self.assertEqual(3, response.json()["count"])
            self.assertEqual(0, Document.objects.filter(user=self.author).count())
            self.assertEqual(1, Document.objects.filter(user=self.outsider).count())


class TestLibraryImport(ApiTestCase):
    def test_import_text_with_aliases_and_folder(self):
        folder = self.api("post", "/library/folders", {"name": "Imported"}).json()
        response = self.api("post", "/library/import", {"bibtex": BIBTEX, "folder_id": folder["id"]})
        self.assertEqual(201, response.status_code)
        body = response.json()
        self.assertEqual((2, folder["id"], []), (body["imported"], body["folder_id"], body["warnings"]))

        smith = Document.objects.get(user=self.author, bibtexkey="Smith2020")
        self.assertEqual("article", smith.entry_type)
        self.assertEqual("slr; automation", smith.keywords)
        self.assertEqual("https://example.org/smith2020", smith.url)
        self.assertEqual("Somewhere", smith.address)
        self.assertEqual("Smith, John and Doe, Jane", smith.author)
        jones = Document.objects.get(user=self.author, bibtexkey="Jones2019")
        self.assertEqual(("inproceedings", "Proc. of Testing"), (jones.entry_type, jones.booktitle))
        self.assertEqual(
            {"Smith2020", "Jones2019"},
            set(Folder.objects.get(pk=folder["id"]).documents.values_list("bibtexkey", flat=True)),
        )

        with self.subTest(msg="empty content and unknown folder"):
            self.assertEqual(422, self.api("post", "/library/import", {"bibtex": "  "}).status_code)
            self.assertEqual(
                404, self.api("post", "/library/import", {"bibtex": BIBTEX, "folder_id": 9999}).status_code
            )
            self.assertEqual(2, Document.objects.filter(user=self.author).count())

    def test_import_file(self):
        with open(DATA / "ieee_sample.bib", "rb") as handle:
            response = self.client.post(f"{API}/library/import/file", {"file": handle})
        self.assertEqual(201, response.status_code)
        self.assertEqual(2, response.json()["imported"])
        self.assertIsNone(response.json()["folder_id"])
        self.assertEqual(2, Document.objects.filter(user=self.author).count())
