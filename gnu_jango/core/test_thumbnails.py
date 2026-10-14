"""List-size picture copies made by Django (gnu_jango.core.thumbnails).

Product cards, cart lines, banners and gallery cards get a resized copy instead of the original
upload; the copy URL is signed so only pictures the API handed out can be resized.
"""

import io
import shutil
import tempfile
from pathlib import Path

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings
from PIL import Image

from gnu_jango.core.thumbnails import THUMBNAIL_WIDTHS, thumbnail_url
from gnu_jango.shop.models import ShopProduct

WEBP = "image/webp,image/apng,image/*,*/*;q=0.8"


def png_bytes(width, height, mode="RGB"):
    buffer = io.BytesIO()
    Image.new(mode, (width, height), (200, 120, 40) if mode == "RGB" else (200, 120, 40, 128)).save(buffer, "PNG")
    return buffer.getvalue()


class ThumbnailTestBase(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.legacy_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.legacy_root, ignore_errors=True)
        overrides = override_settings(
            MEDIA_ROOT=self.media_root,
            MEDIA_URL="/media/",
            LEGACY_GNUBOARD5_SOURCE_ROOTS=self.legacy_root,
            LEGACY_GNUBOARD5_BASE_URL="http://legacy.example",
        )
        overrides.enable()
        self.addCleanup(overrides.disable)
        cache.clear()

    def media_image(self, name, width=1200, height=800, mode="RGB"):
        return default_storage.save(name, ContentFile(png_bytes(width, height, mode)))

    def legacy_image(self, relative, width=1200, height=800):
        path = Path(self.legacy_root) / "data" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png_bytes(width, height))
        return path

    def fetch(self, url, accept=WEBP):
        return self.client.get(url, HTTP_ACCEPT=accept)


class ThumbnailUrlTests(ThumbnailTestBase):
    def test_a_media_picture_gets_a_signed_copy_url(self):
        name = self.media_image("shop/products/A1/photo.png")

        url = thumbnail_url(f"/media/{name}", 400)

        self.assertTrue(url.startswith("/api/v1/thumbs/"))
        self.assertIn("/400/media/shop/products/A1/photo.png", url)

    def test_a_legacy_data_picture_on_this_server_gets_a_copy_url(self):
        self.legacy_image("item/IT1/image-01.png")

        for original in ("/data/item/IT1/image-01.png", "http://legacy.example/data/item/IT1/image-01.png"):
            with self.subTest(original=original):
                self.assertIn("/400/data/item/IT1/image-01.png", thumbnail_url(original, 400))

    def test_pictures_this_server_cannot_read_keep_their_original_url(self):
        for original in (
            "http://legacy.example/data/item/NOPE/image-01.png",  # not copied to this server
            "https://cdn.example.com/a.png",  # someone else's host
            "/media/shop/logo.svg",  # vector
            "/media/shop/anim.gif",  # may be animated
            "/sample-data/product-1.webp",  # bundled demo asset
            "",
        ):
            with self.subTest(original=original):
                self.assertEqual(thumbnail_url(original, 400), original)

    def test_only_listed_widths_are_used(self):
        name = self.media_image("shop/products/A1/w.png")

        self.assertEqual(thumbnail_url(f"/media/{name}", 333), f"/media/{name}")
        self.assertEqual(set(THUMBNAIL_WIDTHS), {240, 400, 800, 1440, 1920})


class ThumbnailViewTests(ThumbnailTestBase):
    def test_the_copy_is_a_smaller_webp_cached_for_a_year(self):
        name = self.media_image("shop/products/A1/big.png", 1200, 800)

        response = self.fetch(thumbnail_url(f"/media/{name}", 400))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/webp")
        self.assertEqual(Image.open(io.BytesIO(response.content)).size, (400, 267))
        self.assertEqual(response["Cache-Control"], "public, max-age=31536000, s-maxage=31536000, immutable")
        self.assertIn("accept", response["Vary"].lower())
        self.assertNotIn("cookie", response["Vary"].lower())

    def test_a_signed_in_browser_still_gets_the_cacheable_copy(self):
        name = self.media_image("shop/products/A1/member.png")
        self.client.cookies["sessionid"] = "a" * 32
        self.client.cookies["csrftoken"] = "b" * 32

        response = self.fetch(thumbnail_url(f"/media/{name}", 400))

        self.assertEqual(response["Cache-Control"], "public, max-age=31536000, s-maxage=31536000, immutable")
        self.assertNotIn("cookie", response["Vary"].lower())
        self.assertNotIn("Set-Cookie", response)

    def test_browsers_without_webp_get_the_original_format(self):
        name = self.media_image("shop/products/A1/alpha.png", 900, 900, mode="RGBA")

        response = self.fetch(thumbnail_url(f"/media/{name}", 240), accept="image/png,image/*")

        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(Image.open(io.BytesIO(response.content)).size, (240, 240))

    def test_a_small_picture_is_not_enlarged(self):
        name = self.media_image("shop/products/A1/small.png", 300, 200)

        response = self.fetch(thumbnail_url(f"/media/{name}", 400))

        self.assertEqual(Image.open(io.BytesIO(response.content)).size, (300, 200))

    def test_legacy_data_pictures_are_resized_too(self):
        self.legacy_image("item/IT1/image-01.png", 1000, 1000)

        response = self.fetch(thumbnail_url("/data/item/IT1/image-01.png", 400))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Image.open(io.BytesIO(response.content)).size, (400, 400))

    def test_a_forged_or_altered_url_opens_nothing(self):
        name = self.media_image("shop/products/A1/secret.png")
        url = thumbnail_url(f"/media/{name}", 400)
        signature = url.split("/")[4]

        for forged in (
            url.replace(signature, "0" * len(signature)),
            url.replace("/400/", "/800/"),
            url.replace("secret.png", "other.png"),
            f"/api/v1/thumbs/{signature}/400/media/../../etc/passwd",
            f"/api/v1/thumbs/{signature}/333/media/{name}",
            f"/api/v1/thumbs/{signature}/400/elsewhere/{name}",
        ):
            with self.subTest(forged=forged):
                self.assertEqual(self.fetch(forged).status_code, 404)

    def test_a_picture_with_too_many_pixels_is_not_decoded_and_the_original_is_used(self):
        name = self.media_image("shop/products/A1/bomb.png", 120, 120)

        with mock.patch("gnu_jango.core.thumbnails.MAX_SOURCE_PIXELS", 100 * 100):
            response = self.fetch(thumbnail_url(f"/media/{name}", 400))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"/media/{name}")
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_when_no_copy_can_be_made_the_browser_is_sent_to_the_original(self):
        name = self.media_image("shop/products/A1/fails.png")

        with mock.patch("gnu_jango.core.thumbnails._make_copy", side_effect=OSError("storage is read-only")):
            response = self.fetch(thumbnail_url(f"/media/{name}", 400))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"/media/{name}")

    def test_a_browser_that_refuses_webp_gets_the_original_format(self):
        name = self.media_image("shop/products/A1/no-webp.png", 600, 600)

        response = self.fetch(thumbnail_url(f"/media/{name}", 400), accept="image/webp;q=0, image/png")

        self.assertEqual(response["Content-Type"], "image/png")

    def test_a_missing_source_is_a_404(self):
        url = thumbnail_url("/media/shop/products/A1/gone.png", 400)

        self.assertEqual(self.fetch(url).status_code, 404)

    def test_the_copy_is_made_once_and_reused(self):
        name = self.media_image("shop/products/A1/once.png")
        url = thumbnail_url(f"/media/{name}", 400)

        first = self.fetch(url).content
        cache.clear()
        second = self.fetch(url).content

        self.assertEqual(first, second)
        copies = [path for path in Path(self.media_root).rglob("*.webp")]
        self.assertEqual(len(copies), 1)


class ProductPayloadThumbnailTests(ThumbnailTestBase):
    def test_lists_get_the_copy_and_the_detail_keeps_the_original(self):
        name = self.media_image("shop/products/P1/main.png")
        ShopProduct.objects.create(it_id="P1", it_name="Lamp", it_use=1, image_url=f"/media/{name}")

        listed = self.client.get("/api/v1/shop/products", {"per_page": 5}).json()["data"]
        row = next(item for item in listed if item["it_id"] == "P1")
        detail = self.client.get("/api/v1/shop/products/P1").json()["data"]

        self.assertIn("/api/v1/thumbs/", row["image_url"])
        self.assertIn("/400/", row["image_url"])
        self.assertEqual(detail["images"][0], f"/media/{name}")


class BoardCopyGateTests(TestCase):
    """A copy URL never expires, so board pictures only get one when any visitor may see them."""

    def test_copies_only_for_posts_every_visitor_may_read(self):
        from gnu_jango.api.v1_board import _public_copy_allowed

        public = SimpleNamespace(bo_read_level=1, bo_read_point=0)
        cases = (
            (public, False, True),
            (public, True, False),  # secret post
            (SimpleNamespace(bo_read_level=2, bo_read_point=0), False, False),  # members only
            (SimpleNamespace(bo_read_level=1, bo_read_point=-10), False, False),  # reading costs points
            (None, False, False),
        )
        for board, is_secret, allowed in cases:
            with self.subTest(board=board, is_secret=is_secret):
                self.assertEqual(_public_copy_allowed(board, is_secret), allowed)
