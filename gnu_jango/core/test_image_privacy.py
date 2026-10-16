"""Uploaded photos must not publish where they were taken.

Phone photos carry EXIF (GPS position, camera serial, time). Boards serve the original file, so the
metadata is removed before storage; the EXIF orientation is applied first so the picture does not
turn sideways once the tag that rotated it is gone.
"""

import io
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from gnu_jango.core.image_privacy import strip_image_metadata

ORIENTATION = 0x0112
MAKE = 0x010F
GPS_IFD = 0x8825


def _jpeg_with_exif(size=(40, 20), orientation=6):
    image = Image.new("RGB", size, (200, 30, 30))
    exif = image.getexif()
    exif[MAKE] = "PrivacyTestCam"
    exif[ORIENTATION] = orientation
    exif.get_ifd(GPS_IFD).update({1: "N", 2: (37.0, 33.0, 0.0), 3: "E", 4: (126.0, 58.0, 0.0)})
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif, quality=90)
    return buffer.getvalue()


def _plain_jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (30, 30), (10, 120, 10)).save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def _opened(data):
    return Image.open(io.BytesIO(data))


class StripImageMetadataTests(SimpleTestCase):
    def test_exif_and_gps_are_removed_and_orientation_is_applied(self):
        upload = SimpleUploadedFile("photo.jpg", _jpeg_with_exif(), content_type="image/jpeg")

        cleaned = strip_image_metadata(upload)

        image = _opened(cleaned.read())
        self.assertEqual(dict(image.getexif()), {})
        self.assertNotIn(b"PrivacyTestCam", cleaned.open().read())
        # Orientation 6 means "rotate 90° clockwise to display": 40x20 becomes 20x40.
        self.assertEqual(image.size, (20, 40))
        self.assertEqual(cleaned.name, "photo.jpg")
        self.assertEqual(cleaned.content_type, "image/jpeg")

    def test_a_photo_without_metadata_is_returned_untouched(self):
        data = _plain_jpeg()
        upload = SimpleUploadedFile("plain.jpg", data, content_type="image/jpeg")

        cleaned = strip_image_metadata(upload)

        self.assertIs(cleaned, upload)
        self.assertEqual(cleaned.read(), data)

    def test_png_text_and_exif_chunks_are_removed_without_changing_pixels(self):
        from PIL.PngImagePlugin import PngInfo

        image = Image.new("RGB", (8, 8), (1, 2, 3))
        info = PngInfo()
        info.add_text("Comment", "png-secret-location")
        exif = image.getexif()
        exif[MAKE] = "PrivacyTestCam"
        buffer = io.BytesIO()
        image.save(buffer, "PNG", pnginfo=info, exif=exif)
        upload = SimpleUploadedFile("shot.png", buffer.getvalue(), content_type="image/png")

        cleaned = strip_image_metadata(upload)

        data = cleaned.read()
        self.assertNotIn(b"png-secret-location", data)
        self.assertNotIn(b"PrivacyTestCam", data)
        self.assertEqual(_opened(data).getpixel((0, 0)), (1, 2, 3))

    def test_gifs_and_other_files_are_left_alone(self):
        buffer = io.BytesIO()
        Image.new("P", (4, 4)).save(buffer, "GIF")
        gif = SimpleUploadedFile("anim.gif", buffer.getvalue(), content_type="image/gif")
        pdf = SimpleUploadedFile("doc.pdf", b"%PDF-1.4 test", content_type="application/pdf")

        self.assertIs(strip_image_metadata(gif), gif)
        self.assertIs(strip_image_metadata(pdf), pdf)

    def test_a_broken_image_is_returned_as_is_for_the_validators_to_reject(self):
        upload = SimpleUploadedFile("broken.jpg", b"not an image", content_type="image/jpeg")

        self.assertIs(strip_image_metadata(upload), upload)


class EditorUploadPrivacyTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        user = get_user_model().objects.create_user(username="photo-writer", password="test-pass-123")
        self.client = APIClient()
        self.client.force_authenticate(user=user)

    def test_editor_upload_stores_the_photo_without_location(self):
        upload = SimpleUploadedFile("trip.jpg", _jpeg_with_exif(), content_type="image/jpeg")

        response = self.client.post("/api/v1/upload", {"file": upload}, format="multipart")

        self.assertEqual(response.status_code, 201, response.content)
        stored = response.json()["data"]["url"].split("/media/", 1)[1]
        with default_storage.open(stored) as handle:
            data = handle.read()
        self.assertEqual(dict(_opened(data).getexif()), {})
        self.assertNotIn(b"PrivacyTestCam", data)

    def test_editor_upload_rejects_a_file_that_is_not_the_image_it_claims(self):
        fake = SimpleUploadedFile("fake.jpg", b"<html><script>alert(1)</script></html>", content_type="image/jpeg")

        response = self.client.post("/api/v1/upload", {"file": fake}, format="multipart")

        self.assertEqual(response.status_code, 422, response.content)


class BoardAttachmentPrivacyTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)

    def test_a_board_attachment_is_stored_without_location_but_keeps_its_name(self):
        from django.utils import timezone

        from gnu_jango.api.v1_board import _save_post_file
        from gnu_jango.bbs.models import Board, Group, Post

        group = Group.objects.create(gr_id="photo", gr_subject="Photo")
        board = Board.objects.create(group=group, bo_table="photo_privacy", bo_subject="Photos")
        post = Post.objects.create(
            board=board, wr_num=-1, wr_parent=0, wr_subject="trip", wr_content="",
            wr_name="writer", wr_datetime=timezone.now(),
        )
        upload = SimpleUploadedFile("jeju-trip.jpg", _jpeg_with_exif(), content_type="image/jpeg")

        post_file = _save_post_file(board, post, upload, 0)

        self.assertEqual(post_file.bf_source, "jeju-trip.jpg")
        with post_file.bf_file.open("rb") as handle:
            data = handle.read()
        self.assertEqual(dict(_opened(data).getexif()), {})
        self.assertNotIn(b"PrivacyTestCam", data)
