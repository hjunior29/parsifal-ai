from django.test import TestCase

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.core.exceptions import ValidationError
from parsifal.apps.reviews.services import study_columns


class TestStudyColumns(TestCase):
    def test_chosen_kept_and_default(self):
        user = UserFactory()
        self.assertEqual(study_columns.DEFAULT, study_columns.for_user(user))
        self.assertEqual(["title", "doi"], study_columns.save(user, ["title", "doi", "title"]))
        self.assertEqual(["title", "doi"], study_columns.for_user(user))
        study_columns.save(user, study_columns.DEFAULT)
        user.profile.refresh_from_db()
        self.assertEqual([], user.profile.study_columns)  # the default is kept as nothing chosen
        with self.assertRaisesMessage(ValidationError, "Choose at least one column."):
            study_columns.save(user, [])
        with self.assertRaisesMessage(ValidationError, "Unknown column 'nope'"):
            study_columns.clean(["title", "nope"])

    def test_the_window_lists_the_users_columns_first(self):
        choices = study_columns.choices(["status", "title"])
        self.assertEqual(["status", "title"], [c["key"] for c in choices[:2]])
        self.assertEqual([True, True, False], [c["shown"] for c in choices[:3]])
        self.assertEqual(len(study_columns.KEYS), len(choices))
