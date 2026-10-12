import json
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.api.v1_shop import (
    GUEST_ORDER_PASSWORD_HASH_PREFIX,
    auth_cart_config_name,
    guest_order_password_config_name,
)
from gnu_jango.api.v1_community import _qa_meta_config_name, _qa_save_meta
from gnu_jango.config.models import Config
from gnu_jango.shop.models import (
    ShopAddress,
    ShopCategory,
    ShopCoupon,
    ShopOrder,
    ShopPersonalPay,
    ShopProduct,
    ShopQA,
    ShopReview,
    ShopWishlist,
)


def tiny_png_bytes():
    output = BytesIO()
    Image.new("RGB", (1, 1), (255, 255, 255)).save(output, format="PNG")
    return output.getvalue()


class ShopSecurityApiTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.settings_override.enable()

        User = get_user_model()
        self.user = User.objects.create_user(username="shopuser", password="password123")
        self.other = User.objects.create_user(username="otheruser", password="password123")
        self.staff = User.objects.create_user(username="staff", password="password123", is_staff=True)
        self.category = ShopCategory.objects.create(ca_id="10", ca_name="Category")
        self.product = ShopProduct.objects.create(
            it_id="P001",
            category=self.category,
            it_name="Security product",
            it_price=1000,
            it_stock_qty=10,
        )

    def tearDown(self):
        self.settings_override.disable()
        self.media_root.cleanup()

    def auth_headers(self, user):
        access = RefreshToken.for_user(user).access_token
        return {"HTTP_AUTHORIZATION": f"Bearer {access}"}

    def set_authenticated_cart(self, user, items):
        Config.objects.update_or_create(
            name=auth_cart_config_name(user),
            defaults={"value": json.dumps(items, ensure_ascii=False)},
        )

    def test_guest_order_password_lookup_uses_hash_and_migrates_plaintext(self):
        order = ShopOrder.objects.create(
            od_id="ODGUEST1",
            od_name="Guest",
            od_receipt_price=1000,
            od_misu=1000,
            od_status="order",
        )
        Config.objects.create(name=guest_order_password_config_name(order.od_id), value="guestpass")

        wrong = self.client.post(
            "/api/v1/shop/orders/lookup",
            data=json.dumps({"od_id": order.od_id, "od_pwd": "wrongpass"}),
            content_type="application/json",
        )
        self.assertEqual(wrong.status_code, 404)

        ok = self.client.post(
            "/api/v1/shop/orders/lookup",
            data=json.dumps({"od_id": order.od_id, "od_pwd": "guestpass"}),
            content_type="application/json",
        )
        self.assertEqual(ok.status_code, 200)
        stored = Config.objects.get(name=guest_order_password_config_name(order.od_id)).value
        self.assertTrue(stored.startswith(GUEST_ORDER_PASSWORD_HASH_PREFIX))
        self.assertNotEqual(stored, "guestpass")

    def test_coupon_apply_rejects_coupon_owned_by_another_user(self):
        cart_item = {
            "ct_id": "cart-1",
            "it_id": self.product.it_id,
            "it_name": self.product.it_name,
            "ct_price": 1000,
            "ct_qty": 1,
        }
        self.set_authenticated_cart(self.user, [cart_item])
        other_coupon = ShopCoupon.objects.create(
            user=self.other,
            cp_subject="Other coupon",
            cp_method=2,
            cp_price=500,
            cp_start=timezone.localdate(),
        )

        response = self.client.post(
            "/api/v1/shop/coupons/apply-to-cart",
            data=json.dumps({"ct_id": "cart-1", "cp_id": other_coupon.pk}),
            content_type="application/json",
            **self.auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 404)
        stored = json.loads(Config.objects.get(name=auth_cart_config_name(self.user)).value)
        self.assertEqual(stored[0].get("cp_id", ""), "")
        self.assertEqual(stored[0].get("cp_price", 0), 0)

    def test_personalpay_list_requires_authentication_and_is_scoped_to_member(self):
        own = ShopPersonalPay.objects.create(
            pp_id="PPUSER001",
            user=self.user,
            pp_name="Member",
            pp_email="member@example.test",
            pp_price=1000,
        )
        ShopPersonalPay.objects.create(
            pp_id="PPOTHER001",
            user=self.other,
            pp_name="Other member",
            pp_email="other@example.test",
            pp_price=1000,
        )
        ShopPersonalPay.objects.create(
            pp_id="PPGUEST001",
            user=None,
            pp_name="Guest",
            pp_email="guest@example.test",
            pp_price=1000,
        )

        anonymous = self.client.get("/api/v1/shop/personalpay")
        self.assertEqual(anonymous.status_code, 401)

        own_list = self.client.get("/api/v1/shop/personalpay", **self.auth_headers(self.user))
        self.assertEqual(own_list.status_code, 200)
        self.assertEqual([row["pp_id"] for row in own_list.json()["data"]], [own.pp_id])

        other_list = self.client.get("/api/v1/shop/personalpay", **self.auth_headers(self.other))
        self.assertEqual(other_list.status_code, 200)
        self.assertEqual([row["pp_id"] for row in other_list.json()["data"]], ["PPOTHER001"])

        staff_list = self.client.get("/api/v1/shop/personalpay", **self.auth_headers(self.staff))
        self.assertEqual(staff_list.status_code, 200)
        self.assertCountEqual(
            [row["pp_id"] for row in staff_list.json()["data"]],
            ["PPUSER001", "PPOTHER001", "PPGUEST001"],
        )

        other_detail = self.client.get(
            f"/api/v1/shop/personalpay/{own.pp_id}",
            **self.auth_headers(self.other),
        )
        self.assertEqual(other_detail.status_code, 403)

    def test_payment_confirm_requires_order_owner_and_verified_provider(self):
        order = ShopOrder.objects.create(
            od_id="ODPAY1",
            user=self.user,
            od_name="Buyer",
            od_receipt_price=1000,
            od_misu=1000,
            od_status="order",
        )

        denied = self.client.post(
            "/api/v1/shop/payment/confirm",
            data=json.dumps({"order_id": order.od_id, "amount": 1000, "pg_service": "bank"}),
            content_type="application/json",
            **self.auth_headers(self.other),
        )
        self.assertEqual(denied.status_code, 404)
        order.refresh_from_db()
        self.assertEqual(order.od_status, "order")

        bank_confirmation = self.client.post(
            "/api/v1/shop/payment/confirm",
            data=json.dumps({"order_id": order.od_id, "amount": 1000, "pg_service": "bank"}),
            content_type="application/json",
            **self.auth_headers(self.user),
        )
        self.assertEqual(bank_confirmation.status_code, 409)
        order.refresh_from_db()
        self.assertEqual(order.od_status, "order")
        self.assertEqual(order.od_misu, 1000)

    def test_member_shop_collections_are_scoped_to_the_authenticated_user(self):
        other_product = ShopProduct.objects.create(
            it_id="P002",
            category=self.category,
            it_name="Other member product",
            it_price=2000,
        )
        own_address = ShopAddress.objects.create(
            user=self.user,
            ad_name="Member",
            ad_hp="010-1111-1111",
            ad_addr1="Member private address",
        )
        other_address = ShopAddress.objects.create(
            user=self.other,
            ad_name="Other member",
            ad_hp="010-2222-2222",
            ad_addr1="Other private address",
        )
        own_order = ShopOrder.objects.create(
            od_id="ODOWNER001",
            user=self.user,
            od_name="Member",
            od_hp="010-1111-1111",
            od_addr1="Member order address",
        )
        other_order = ShopOrder.objects.create(
            od_id="ODOTHER001",
            user=self.other,
            od_name="Other member",
            od_hp="010-2222-2222",
            od_addr1="Other order address",
        )
        own_coupon = ShopCoupon.objects.create(
            user=self.user,
            cp_subject="Member coupon",
            cp_price=1000,
            cp_start=timezone.localdate(),
        )
        other_coupon = ShopCoupon.objects.create(
            user=self.other,
            cp_subject="Other coupon",
            cp_price=2000,
            cp_start=timezone.localdate(),
        )
        ShopWishlist.objects.create(user=self.user, product=self.product, it_id=self.product.it_id)
        ShopWishlist.objects.create(user=self.other, product=other_product, it_id=other_product.it_id)
        self.set_authenticated_cart(
            self.user,
            [{"ct_id": "own-cart", "it_id": self.product.it_id, "ct_qty": 1}],
        )
        self.set_authenticated_cart(
            self.other,
            [{"ct_id": "other-cart", "it_id": other_product.it_id, "ct_qty": 1}],
        )
        own_review = ShopReview.objects.create(
            product=self.product,
            user=self.user,
            is_subject="Member review",
            is_content="Member review content",
        )
        other_review = ShopReview.objects.create(
            product=other_product,
            user=self.other,
            is_subject="Other review",
            is_content="Other review content",
        )
        own_qa = ShopQA.objects.create(
            product=self.product,
            user=self.user,
            iq_subject="Member question",
            iq_question="Member private question",
            iq_secret=1,
            iq_email="member@example.test",
            iq_hp="010-1111-1111",
        )
        other_qa = ShopQA.objects.create(
            product=other_product,
            user=self.other,
            iq_subject="Other question",
            iq_question="Other private question",
            iq_secret=1,
            iq_email="other@example.test",
            iq_hp="010-2222-2222",
        )

        endpoints = (
            ("/api/v1/shop/cart", "items", "it_id", self.product.it_id, other_product.it_id),
            ("/api/v1/shop/wishlist", None, "it_id", self.product.it_id, other_product.it_id),
            ("/api/v1/shop/addresses", None, "ad_id", own_address.pk, other_address.pk),
            ("/api/v1/shop/orders", None, "od_id", own_order.od_id, other_order.od_id),
            ("/api/v1/shop/coupons", None, "cp_id", own_coupon.cp_id, other_coupon.cp_id),
            ("/api/v1/shop/reviews/mine", None, "is_id", str(own_review.pk), str(other_review.pk)),
            ("/api/v1/shop/reviews/qna/mine", None, "iq_id", str(own_qa.pk), str(other_qa.pk)),
        )

        for path, nested_key, id_key, own_id, other_id in endpoints:
            with self.subTest(path=path, member="owner"):
                response = self.client.get(path, **self.auth_headers(self.user))
                self.assertEqual(response.status_code, 200)
                rows = response.json()["data"]
                if nested_key:
                    rows = rows[nested_key]
                row_ids = {str(row[id_key]) for row in rows}
                self.assertIn(str(own_id), row_ids)
                self.assertNotIn(str(other_id), row_ids)

            with self.subTest(path=path, member="other"):
                response = self.client.get(path, **self.auth_headers(self.other))
                self.assertEqual(response.status_code, 200)
                rows = response.json()["data"]
                if nested_key:
                    rows = rows[nested_key]
                row_ids = {str(row[id_key]) for row in rows}
                self.assertIn(str(other_id), row_ids)
                self.assertNotIn(str(own_id), row_ids)

    def test_member_private_details_mask_foreign_data_and_reject_mutations(self):
        address = ShopAddress.objects.create(
            user=self.user,
            ad_name="Member",
            ad_hp="010-1111-1111",
            ad_addr1="Member private address",
        )
        order = ShopOrder.objects.create(
            od_id="ODPRIVATE001",
            user=self.user,
            od_name="Member",
            od_hp="010-1111-1111",
            od_addr1="Member order address",
            od_misu=1000,
            od_status="order",
        )
        review = ShopReview.objects.create(
            product=self.product,
            user=self.user,
            is_subject="Member review",
            is_content="Original review content",
        )
        qa = ShopQA.objects.create(
            product=self.product,
            user=self.user,
            iq_subject="Member secret question",
            iq_question="Original secret question",
            iq_answer="Private staff answer",
            iq_secret=1,
            iq_email="member@example.test",
            iq_hp="010-1111-1111",
        )
        other_headers = self.auth_headers(self.other)

        foreign_address_patch = self.client.patch(
            f"/api/v1/shop/addresses/{address.pk}",
            data=json.dumps({"ad_addr1": "Overwritten by another member"}),
            content_type="application/json",
            **other_headers,
        )
        self.assertEqual(foreign_address_patch.status_code, 404)
        foreign_address_delete = self.client.delete(
            f"/api/v1/shop/addresses/{address.pk}",
            **other_headers,
        )
        self.assertEqual(foreign_address_delete.status_code, 404)
        address.refresh_from_db()
        self.assertEqual(address.ad_addr1, "Member private address")

        self.assertEqual(
            self.client.get(f"/api/v1/shop/orders/{order.od_id}", **other_headers).status_code,
            404,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/v1/shop/orders/{order.od_id}",
                data=json.dumps({"reason": "foreign cancellation"}),
                content_type="application/json",
                **other_headers,
            ).status_code,
            404,
        )
        order.refresh_from_db()
        self.assertEqual(order.od_status, "order")
        self.assertEqual(order.od_addr1, "Member order address")

        self.assertEqual(
            self.client.patch(
                f"/api/v1/shop/reviews/{review.pk}",
                data=json.dumps({"is_content": "Overwritten by another member"}),
                content_type="application/json",
                **other_headers,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(f"/api/v1/shop/reviews/{review.pk}", **other_headers).status_code,
            403,
        )
        review.refresh_from_db()
        self.assertEqual(review.is_content, "Original review content")

        foreign_qa = self.client.get(f"/api/v1/shop/reviews/qna/{qa.pk}", **other_headers)
        self.assertEqual(foreign_qa.status_code, 200)
        foreign_qa_data = foreign_qa.json()["data"]
        self.assertFalse(foreign_qa_data["can_view"])
        self.assertFalse(foreign_qa_data["can_edit"])
        self.assertEqual(foreign_qa_data["iq_question"], "")
        self.assertEqual(foreign_qa_data["iq_answer"], "")
        self.assertEqual(foreign_qa_data["iq_email"], "")
        self.assertEqual(foreign_qa_data["iq_hp"], "")
        self.assertEqual(
            self.client.patch(
                f"/api/v1/shop/reviews/qna/{qa.pk}",
                data=json.dumps({"iq_question": "Overwritten by another member"}),
                content_type="application/json",
                **other_headers,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(f"/api/v1/shop/reviews/qna/{qa.pk}", **other_headers).status_code,
            403,
        )
        qa.refresh_from_db()
        self.assertEqual(qa.iq_question, "Original secret question")

        owner_qa = self.client.get(
            f"/api/v1/shop/reviews/qna/{qa.pk}",
            **self.auth_headers(self.user),
        )
        self.assertEqual(owner_qa.status_code, 200)
        self.assertTrue(owner_qa.json()["data"]["can_view"])
        self.assertEqual(owner_qa.json()["data"]["iq_question"], "Original secret question")

    def test_missing_member_shop_resources_return_not_found(self):
        headers = self.auth_headers(self.user)
        self.assertEqual(
            self.client.patch(
                "/api/v1/shop/addresses/999999",
                data=json.dumps({"ad_name": "Missing address"}),
                content_type="application/json",
                **headers,
            ).status_code,
            404,
        )
        self.assertEqual(self.client.get("/api/v1/shop/orders/ODMISSING", **headers).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/shop/reviews/999999", **headers).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/shop/reviews/qna/999999", **headers).status_code, 404)

    def test_product_image_upload_requires_staff_and_valid_image_content(self):
        fake_image = SimpleUploadedFile("bad.png", b"not an image", content_type="image/png")
        anonymous = self.client.post(
            f"/api/v1/shop/products/{self.product.it_id}/images",
            data={"file": fake_image},
        )
        self.assertIn(anonymous.status_code, {401, 403})

        fake_image = SimpleUploadedFile("bad.png", b"not an image", content_type="image/png")
        invalid = self.client.post(
            f"/api/v1/shop/products/{self.product.it_id}/images",
            data={"file": fake_image},
            **self.auth_headers(self.staff),
        )
        self.assertEqual(invalid.status_code, 400)

        valid_image = SimpleUploadedFile("ok.png", tiny_png_bytes(), content_type="image/png")
        uploaded = self.client.post(
            f"/api/v1/shop/products/{self.product.it_id}/images",
            data={"file": valid_image},
            **self.auth_headers(self.staff),
        )
        self.assertEqual(uploaded.status_code, 201)

    def test_refresh_token_rotates_and_blacklists_previous_token(self):
        refresh = str(RefreshToken.for_user(self.user))

        response = self.client.post(
            "/api/v1/auth/refresh",
            data=json.dumps({"refresh_token": refresh}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        rotated = response.json()["data"]["refresh_token"]
        self.assertNotEqual(rotated, refresh)

        reused = self.client.post(
            "/api/v1/auth/refresh",
            data=json.dumps({"refresh_token": refresh}),
            content_type="application/json",
        )
        self.assertEqual(reused.status_code, 401)


class ConfigSideTableCleanupTests(TestCase):
    """Companion Config rows must not outlive the record they belong to.

    Only the API delete paths used to clear them, so deleting a Q&A or an order
    through the admin or a queryset left the row behind; a cleanup found 24
    stale qa_meta rows and 57 stale guest_order_pwd rows.
    """

    def _make_qa_with_meta(self, subject):
        qa = ShopQA.objects.create(iq_subject=subject, iq_question="q")
        _qa_save_meta(qa.pk, {"parent": 0, "related": 0, "answer_subject": "", "files": [{}, {}]})
        name = _qa_meta_config_name(qa.pk)
        self.assertTrue(Config.objects.filter(name=name).exists())
        return qa, name

    def test_deleting_qa_instance_removes_its_meta_row(self):
        qa, name = self._make_qa_with_meta("instance delete")

        qa.delete()

        self.assertFalse(Config.objects.filter(name=name).exists())

    def test_deleting_qa_queryset_removes_its_meta_row(self):
        qa, name = self._make_qa_with_meta("queryset delete")

        ShopQA.objects.filter(pk=qa.pk).delete()

        self.assertFalse(Config.objects.filter(name=name).exists())

    def test_deleting_order_removes_guest_password_row(self):
        order = ShopOrder.objects.create(od_id="TESTORDER0001")
        name = guest_order_password_config_name(order.od_id)
        Config.objects.create(name=name, value="hash$synthetic")

        order.delete()

        self.assertFalse(Config.objects.filter(name=name).exists())
