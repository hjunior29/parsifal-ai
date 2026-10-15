from django.db import connection
from django.test import TestCase


class TestSQLiteConfiguration(TestCase):
    def pragma(self, name):
        with connection.cursor() as cursor:
            cursor.execute(f"PRAGMA {name}")
            return cursor.fetchone()[0]

    def test_sqlite_pragmas_applied(self):
        if connection.vendor != "sqlite":
            self.skipTest("SQLite-only test")

        with self.subTest(msg="foreign keys enforced"):
            self.assertEqual(1, self.pragma("foreign_keys"))

        with self.subTest(msg="busy timeout set"):
            self.assertEqual(5000, self.pragma("busy_timeout"))
