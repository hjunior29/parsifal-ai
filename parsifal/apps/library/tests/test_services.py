from django.test import TestCase

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.exceptions import Conflict, NotFound, ValidationError
from parsifal.apps.library import services
from parsifal.apps.library.models import Document, Folder


class TestLibraryServices(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = UserFactory(username="alice")
        cls.bob = UserFactory(username="bob")

    def test_folders_are_per_user(self):
        folder = services.create_folder(self.alice, name="  Thesis ")
        self.assertEqual(("Thesis", "thesis"), (folder.name, folder.slug))
        with self.assertRaises(Conflict):
            services.create_folder(self.alice, name="Thesis")
        # Bob may use the same name; Alice cannot see Bob's folder.
        bobs = services.create_folder(self.bob, name="Thesis")
        self.assertEqual("thesis-1", bobs.slug)
        with self.assertRaises(NotFound):
            services.get_folder(self.alice, bobs.pk)
        with self.assertRaises(NotFound):
            services.rename_folder(self.alice, folder_id=bobs.pk, name="Stolen")
        with self.assertRaises(ValidationError):
            services.create_folder(self.alice, name="")

    def test_documents_fields_and_scope(self):
        document = services.create_document(self.alice, title="Paper", entry_type="ARTICLE", year=" 2020 ")
        self.assertEqual(("article", "2020"), (document.entry_type, document.year))
        with self.assertRaises(ValidationError):
            services.create_document(self.alice, title="Paper", entry_type="poem")
        with self.assertRaises(ValidationError):
            services.create_document(self.alice, title="Paper", nonsense="x")
        with self.assertRaises(ValidationError):
            services.create_document(self.alice, abstract="without identification")
        updated = services.update_document(self.alice, document_id=document.pk, year=None, journal="JoT")
        self.assertEqual((None, "JoT"), (updated.year, updated.journal))
        with self.assertRaises(NotFound):
            services.get_document(self.bob, document.pk)
        with self.assertRaises(NotFound):
            services.delete_documents(self.bob, document_ids=[document.pk])
        self.assertTrue(Document.objects.filter(pk=document.pk).exists())

    def test_folder_membership(self):
        inbox = services.create_folder(self.alice, name="Inbox")
        done = services.create_folder(self.alice, name="Done")
        a = services.create_document(self.alice, title="A")
        b = services.create_document(self.alice, title="B")
        foreign = services.create_document(self.bob, title="Bob's")

        services.add_to_folder(self.alice, folder_id=inbox.pk, document_ids=[a.pk, b.pk, a.pk])
        self.assertEqual(2, inbox.documents.count())
        with self.assertRaises(NotFound):
            services.add_to_folder(self.alice, folder_id=inbox.pk, document_ids=[foreign.pk])

        destination = services.move_documents(
            self.alice, from_folder_id=inbox.pk, to_folder_id=done.pk, document_ids=[a.pk]
        )
        self.assertEqual(done, destination)
        self.assertEqual([b], list(inbox.documents.all()))
        self.assertEqual([a], list(done.documents.all()))

        services.remove_from_folder(self.alice, folder_id=inbox.pk, document_ids=[b.pk])
        self.assertEqual(0, inbox.documents.count())
        self.assertTrue(Document.objects.filter(pk=b.pk).exists())

        self.assertEqual(["A"], [d.title for d in services.list_documents(self.alice, folder_id=done.pk)])
        self.assertEqual(["A", "B"], [d.title for d in services.list_documents(self.alice)])
        self.assertEqual(["B", "A"], [d.title for d in services.list_documents(self.alice, order="-title")])
        with self.assertRaises(ValidationError):
            services.list_documents(self.alice, order="doi")

        services.delete_folder(self.alice, folder_id=done.pk)
        self.assertFalse(Folder.objects.filter(pk=done.pk).exists())
        self.assertTrue(Document.objects.filter(pk=a.pk).exists())

    def test_import_bibtex(self):
        folder = services.create_folder(self.alice, name="Imported")
        bibtex = """
        @Article{Key1, title={T1}, author={A}, year={2020}, link={http://x}, author_keywords={k1}}
        @Misc{Key2, title={%s}}
        """ % (
            "x" * 1001
        )
        result = services.import_bibtex(self.alice, content=bibtex, folder_id=folder.pk)
        self.assertEqual(2, result.imported)
        self.assertEqual(2, folder.documents.count())
        first = Document.objects.get(bibtexkey="Key1")
        self.assertEqual(("article", "http://x", "k1"), (first.entry_type, first.url, first.keywords))
        second = Document.objects.get(bibtexkey="Key2")
        self.assertEqual(("misc", 1000), (second.entry_type, len(second.title)))
        self.assertEqual(["Key2: title truncated to 1000 characters."], result.warnings)
        with self.assertRaises(ValidationError):
            services.import_bibtex(self.alice, content="")
        with self.assertRaises(NotFound):
            services.import_bibtex(self.alice, content=bibtex, folder_id=services.create_folder(self.bob, name="B").pk)

    def test_unknown_entry_type_is_dropped_with_a_warning(self):
        warnings = []
        document = services.document_from_entry(
            {"ID": "Key3", "ENTRYTYPE": "poem", "title": "T"}, user=self.alice, warnings=warnings
        )
        self.assertIsNone(document.entry_type)
        self.assertEqual(["Key3: unknown entry type 'poem' ignored."], warnings)
