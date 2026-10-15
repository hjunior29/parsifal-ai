import io
import os
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from PIL import Image

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.utils.test import login_redirect_url

MEDIA_ROOT = tempfile.mkdtemp(prefix="parsifal-test-media-")


def make_png(width, height):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(10, 20, 30)).save(buffer, format="PNG")
    return SimpleUploadedFile("picture.png", buffer.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class TestUploadPictureView(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.url = reverse("settings:upload_picture")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def tmp_path(self):
        return os.path.join(MEDIA_ROOT, "profile_pictures", f"{self.user.username}_tmp.jpg")

    def final_path(self):
        return os.path.join(MEDIA_ROOT, "profile_pictures", f"{self.user.username}.jpg")

    def test_login_required(self):
        response = self.client.post(self.url)
        self.assertRedirects(response, login_redirect_url(self.url))

    def test_upload_resizes_large_picture(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"picture": make_png(1120, 560)})

        with self.subTest(msg="Test redirect to picture page"):
            self.assertRedirects(response, reverse("settings:picture") + "?upload_picture=uploaded")

        with self.subTest(msg="Test temporary file resized to 560px wide"):
            self.assertTrue(os.path.exists(self.tmp_path()))
            width, height = Image.open(self.tmp_path()).size
            self.assertEqual((560, 280), (width, height))

    def test_upload_invalid_extension(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile("notes.txt", b"not an image", content_type="text/plain")
        response = self.client.post(self.url, {"picture": upload}, follow=True)
        self.assertContains(response, "Invalid file format.")

    def test_crop_uploaded_picture(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {"picture": make_png(400, 400)})
        response = self.client.post(
            reverse("settings:save_uploaded_picture"), {"x": "10", "y": "10", "w": "300", "h": "300"}
        )

        with self.subTest(msg="Test response is the image url"):
            self.assertEqual(200, response.status_code)
            self.assertIn(f"profile_pictures/{self.user.username}.jpg", response.content.decode())

        with self.subTest(msg="Test final picture is 200x200 and temp removed"):
            self.assertEqual((200, 200), Image.open(self.final_path()).size)
            self.assertFalse(os.path.exists(self.tmp_path()))
