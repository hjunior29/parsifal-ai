from django.test import SimpleTestCase, override_settings

from parsifal.apps.core import crypto


class TestCrypto(SimpleTestCase):
    def test_round_trip_and_ciphertext_hides_the_value(self):
        token = crypto.encrypt("fake-secret-value")
        self.assertNotIn("fake-secret-value", token)
        self.assertNotEqual(token, crypto.encrypt("fake-secret-value"))  # random IV
        self.assertEqual("fake-secret-value", crypto.decrypt(token))

    def test_another_secret_key_cannot_decrypt(self):
        token = crypto.encrypt("fake-secret-value")
        with override_settings(SECRET_KEY="another-secret-key"):
            with self.assertRaises(crypto.DecryptionError):
                crypto.decrypt(token)
        with self.assertRaises(crypto.DecryptionError):
            crypto.decrypt("not a token")
