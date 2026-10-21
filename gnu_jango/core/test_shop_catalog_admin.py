"""youngcart catalog admin parity: option builder, related products and product copy."""

import json
from tempfile import TemporaryDirectory

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from gnu_jango.core.management.commands.migrate_gnuboard5 import Command as GnuboardImportCommand
from gnu_jango.shop.models import (
    ShopCategory,
    ShopProduct,
    ShopProductRelation,
    ShopReview,
    ShopStockAdjustment,
)
from gnu_jango.shop.product_copy import copy_product, next_product_id
from gnu_jango.shop.product_options import (
    clean_option_subject,
    normalize_option_rows,
    option_combinations,
    split_option_values,
    supply_subject,
)
from gnu_jango.shop.product_relations import mirror_product_relations, related_product_ids

SEP = "\x1e"
API = "/api/v1/shop"
FILE_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def form_data(form):
    """POST data that re-submits a bound-less form with its current values."""
    data = {}
    for bound in form:
        widget = bound.field.widget
        if bound.field.disabled:
            continue
        value = bound.value()
        if isinstance(widget, forms.MultiWidget):
            parts = value if isinstance(value, (list, tuple)) else widget.decompress(value)
            for suffix, sub_widget, part in zip(widget.widgets_names, widget.widgets, parts):
                formatted = sub_widget.format_value(part)
                data[bound.html_name + suffix] = "" if formatted is None else formatted
        elif isinstance(widget, forms.CheckboxInput):
            if widget.check_test(value):
                data[bound.html_name] = "on"
        elif isinstance(widget, forms.SelectMultiple):
            data[bound.html_name] = [str(item) for item in (value or [])]
        else:
            formatted = widget.format_value(value)
            if isinstance(formatted, list):
                formatted = formatted[0] if formatted else ""
            data[bound.html_name] = "" if formatted is None else formatted
    return data


def change_form_data(response):
    """The admin change page's own POST data: the main form plus every inline formset."""
    data = form_data(response.context["adminform"].form)
    for inline in response.context["inline_admin_formsets"]:
        data.update(form_data(inline.formset.management_form))
        for form in inline.formset.forms:
            data.update(form_data(form))
    return data


class OptionRuleTests(SimpleTestCase):
    def test_values_split_like_youngcart(self):
        self.assertEqual(split_option_values(" 빨강, 파랑,,빨강 ,"), ["빨강", "파랑"])

    def test_combinations_put_the_first_option_outermost(self):
        self.assertEqual(
            option_combinations([["빨강", "파랑"], ["S", "L"]]),
            [f"빨강{SEP}S", f"빨강{SEP}L", f"파랑{SEP}S", f"파랑{SEP}L"],
        )
        self.assertEqual(option_combinations([]), [])

    def test_rows_are_typed_ordered_and_numbered(self):
        rows = normalize_option_rows([
            {"io_id": f"포장{SEP}선물", "io_type": 1, "io_price": "500", "io_stock_qty": "3"},
            {"io_id": f"빨강{SEP}L", "io_type": "0", "io_price": -1000, "io_stock_qty": 5, "io_noti_qty": 1, "io_use": "0", "extra": "x"},
        ])
        self.assertEqual(rows, [
            {"io_no": 1, "io_id": f"빨강{SEP}L", "io_type": 0, "io_price": -1000, "io_stock_qty": 5, "io_noti_qty": 1, "io_use": 0},
            {"io_no": 2, "io_id": f"포장{SEP}선물", "io_type": 1, "io_price": 500, "io_stock_qty": 3, "io_noti_qty": 0, "io_use": 1},
        ])

    def test_bad_rows_are_refused_with_a_reason(self):
        cases = {
            "중복": [{"io_id": "A", "io_type": 0}, {"io_id": " A ", "io_type": 0}],
            "정수": [{"io_id": "A", "io_type": 0, "io_price": "1.5"}],
            "0 이상": [{"io_id": "A", "io_type": 0, "io_stock_qty": -1}],
            "따옴표": [{"io_id": 'A"B', "io_type": 0}],
            "단계 수": [{"io_id": "A", "io_type": 0}, {"io_id": f"B{SEP}C", "io_type": 0}],
            "3단계": [{"io_id": SEP.join("ABCD"), "io_type": 0}],
            "항목명": [{"io_id": "포장", "io_type": 1}],
            "io_type": [{"io_id": "A", "io_type": 2}],
            "비어": [{"io_id": f"A{SEP}", "io_type": 0}],
            "사용여부": [{"io_id": "A", "io_type": 0, "io_use": 3}],
            "쉼표": [{"io_id": "A,B", "io_type": 0}],
        }
        for expected, rows in cases.items():
            with self.subTest(expected), self.assertRaises(ValidationError) as caught:
                normalize_option_rows(rows)
            self.assertIn(expected, " ".join(caught.exception.messages))
        with self.assertRaises(ValidationError):
            normalize_option_rows({"io_id": "A"})
        # plain text that merely contains "on...=" is not markup
        self.assertEqual(normalize_option_rows([{"io_id": "Condition=A", "io_type": 0}])[0]["io_id"], "Condition=A")

    def test_option_subject_matches_the_levels(self):
        rows = normalize_option_rows([{"io_id": f"빨강{SEP}L", "io_type": 0}, {"io_id": f"포장{SEP}선물", "io_type": 1}])
        self.assertEqual(clean_option_subject(" 색상 , 사이즈", rows), "색상,사이즈")
        self.assertEqual(clean_option_subject("", rows), "")
        self.assertEqual(clean_option_subject("색상", []), "")
        with self.assertRaises(ValidationError):
            clean_option_subject("색상", rows)
        self.assertEqual(supply_subject(rows), "포장")


class AdminBase(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="catalog-admin", email="catalog-admin@example.test", password="password"
        )
        self.client.force_login(self.admin)
        self.category = ShopCategory.objects.create(ca_id="10", ca_name="의류")

    def product(self, it_id="OPT-1", **fields):
        fields.setdefault("it_use", "1")
        return ShopProduct.objects.create(it_id=it_id, it_name=f"상품 {it_id}", category=self.category, **fields)

    def change_url(self, product):
        return reverse("admin:shop_shopproduct_change", args=[product.it_id])

    def post_change(self, product, **changes):
        response = self.client.get(self.change_url(product))
        self.assertEqual(response.status_code, 200)
        data = change_form_data(response)
        data.update(changes)
        return self.client.post(self.change_url(product), data)


class OptionBuilderAdminTests(AdminBase):
    def test_the_change_page_draws_the_builder_over_the_json(self):
        product = self.product(options=[{"io_id": "A", "io_type": 0, "io_stock_qty": 1}])
        html = self.client.get(self.change_url(product)).content.decode()
        self.assertIn("data-option-builder", html)
        self.assertIn("admin_next/js/product_option_builder.js", html)
        self.assertIn('type="hidden" name="it_option_subject"', html)

    def test_saving_builder_rows_stores_typed_rows_and_the_subjects(self):
        product = self.product()
        rows = [
            {"io_id": f"빨강{SEP}L", "io_type": 0, "io_price": "1000", "io_stock_qty": "5", "io_noti_qty": "1", "io_use": 1},
            {"io_id": f"파랑{SEP}L", "io_type": 0, "io_price": 0, "io_stock_qty": 0, "io_noti_qty": 0, "io_use": 0},
            {"io_id": f"포장{SEP}선물포장", "io_type": 1, "io_price": 500, "io_stock_qty": 9, "io_noti_qty": 0, "io_use": 1},
        ]
        response = self.post_change(product, options=json.dumps(rows), it_option_subject="색상,사이즈", it_supply_subject="")
        self.assertEqual(response.status_code, 302, response.content[:2000])
        product.refresh_from_db()
        self.assertEqual([row["io_no"] for row in product.options], [1, 2, 3])
        self.assertEqual(product.options[0]["io_price"], 1000)
        self.assertEqual(product.it_option_subject, "색상,사이즈")
        self.assertEqual(product.it_supply_subject, "포장")
        # option stock edits still leave a stock history row
        self.assertTrue(ShopStockAdjustment.objects.filter(it_id=product.it_id, scope="option", io_id=f"빨강{SEP}L").exists())

    def test_duplicate_or_mismatched_rows_are_refused(self):
        product = self.product()
        duplicate = [{"io_id": "A", "io_type": 0}, {"io_id": "A", "io_type": 0}]
        response = self.post_change(product, options=json.dumps(duplicate), it_option_subject="색상")
        self.assertEqual(response.status_code, 200)
        self.assertIn("중복", response.content.decode())
        response = self.post_change(product, options=json.dumps([{"io_id": "A", "io_type": 0}]), it_option_subject="색상,사이즈")
        self.assertEqual(response.status_code, 200)
        self.assertIn("옵션명은 1개여야", response.content.decode())
        product.refresh_from_db()
        self.assertEqual(product.options, [])

    def test_legacy_option_ids_do_not_block_editing_the_stock(self):
        legacy = [
            {"io_no": 1, "io_id": 'A"B', "io_type": 0, "io_price": 0, "io_stock_qty": 1, "io_noti_qty": 0, "io_use": 1},
            {"io_no": 2, "io_id": "C,D", "io_type": 0, "io_price": 0, "io_stock_qty": 1, "io_noti_qty": 0, "io_use": 1},
            {"io_no": 3, "io_id": "E", "io_type": 0, "io_price": 0, "io_stock_qty": 1, "io_noti_qty": 0, "io_use": 1},
        ]
        product = self.product(options=legacy)
        edited = [dict(row, io_stock_qty=row["io_stock_qty"] + 5) for row in legacy]
        response = self.post_change(product, options=json.dumps(edited))
        self.assertEqual(response.status_code, 302, response.content[:2000])
        product.refresh_from_db()
        self.assertEqual([(row["io_id"], row["io_stock_qty"]) for row in product.options], [('A"B', 6), ("C,D", 6), ("E", 6)])

        # a new or renamed row is still checked strictly
        added = [*edited, {"io_id": 'X"Y', "io_type": 0}]
        response = self.post_change(product, options=json.dumps(added))
        self.assertEqual(response.status_code, 200)
        self.assertIn("따옴표", response.content.decode())
        renamed = [dict(edited[0], io_id="A,B2"), *edited[1:]]
        self.assertIn("쉼표", self.post_change(product, options=json.dumps(renamed)).content.decode())

    def test_stored_ids_are_kept_verbatim_by_the_normalizer(self):
        stored = [{"io_id": "C,D", "io_type": 0}]
        self.assertEqual(normalize_option_rows([{"io_id": "C,D", "io_type": 0, "io_stock_qty": 3}], stored=stored)[0]["io_id"], "C,D")
        with self.assertRaises(ValidationError):
            normalize_option_rows([{"io_id": "C,D", "io_type": 1}], stored=stored)  # another type is a new row

    def test_untouched_legacy_rows_do_not_block_an_unrelated_edit(self):
        # imported rows the strict checks would refuse (4 levels) are re-sent unchanged by the builder
        legacy = [{"io_no": 7, "io_id": SEP.join("ABCD"), "io_type": 0, "io_price": 0, "io_stock_qty": 2, "io_noti_qty": 0, "io_use": 1}]
        product = self.product(options=legacy)
        resent = [{"io_id": SEP.join("ABCD"), "io_type": 0, "io_price": "0", "io_stock_qty": 2, "io_noti_qty": 0, "io_use": 1}]
        response = self.post_change(product, options=json.dumps(resent), it_name="이름만 변경")
        self.assertEqual(response.status_code, 302, response.content[:2000])
        product.refresh_from_db()
        self.assertEqual((product.it_name, product.options), ("이름만 변경", legacy))

    def test_clearing_the_options_clears_the_option_subject(self):
        product = self.product(options=[{"io_id": "A", "io_type": 0, "io_stock_qty": 1}], it_option_subject="색상")
        response = self.post_change(product, options="[]", it_option_subject="색상")
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        self.assertEqual((product.options, product.it_option_subject), ([], ""))


class RelatedProductTests(AdminBase):
    def test_adding_related_products_in_the_admin_lists_both_ways(self):
        main, first, second = self.product("REL-A"), self.product("REL-B"), self.product("REL-C")
        response = self.client.get(self.change_url(main))
        data = change_form_data(response)
        data.update({
            "relations-TOTAL_FORMS": "2",
            "relations-0-related": first.it_id, "relations-0-ir_no": "1",
            "relations-1-related": second.it_id, "relations-1-ir_no": "0",
        })
        response = self.client.post(self.change_url(main), data)
        self.assertEqual(response.status_code, 302, response.content[:2000])
        self.assertEqual(related_product_ids("REL-A"), ["REL-C", "REL-B"])
        self.assertEqual(related_product_ids("REL-B"), ["REL-A"])
        self.assertEqual(related_product_ids("REL-C"), ["REL-A"])

        # removing one on the main product removes its way back too
        response = self.client.get(self.change_url(main))
        data = change_form_data(response)
        delete_index = next(
            index for index, form in enumerate(response.context["inline_admin_formsets"][0].formset.forms)
            if form.instance.related_id == "REL-B"
        )
        data[f"relations-{delete_index}-DELETE"] = "on"
        self.assertEqual(self.client.post(self.change_url(main), data).status_code, 302)
        self.assertEqual(related_product_ids("REL-A"), ["REL-C"])
        self.assertEqual(related_product_ids("REL-B"), [])

    def test_saving_without_touching_the_related_list_keeps_one_way_relations(self):
        main, other, third = self.product("REL-A"), self.product("REL-B"), self.product("REL-C")
        # imported from youngcart: REL-B lists REL-A, REL-A does not list it back
        ShopProductRelation.objects.create(product=other, related=main, ir_no=1)
        data = change_form_data(self.client.get(self.change_url(main)))
        data["it_name"] = "이름만 변경"
        self.assertEqual(self.client.post(self.change_url(main), data).status_code, 302)
        self.assertEqual(related_product_ids("REL-B"), ["REL-A"])

        # editing the list mirrors it (and logs what it drops)
        data = change_form_data(self.client.get(self.change_url(main)))
        data.update({"relations-TOTAL_FORMS": "1", "relations-0-related": third.it_id, "relations-0-ir_no": "0"})
        with self.assertLogs("gnu_jango.shop.product_relations", "INFO") as logs:
            self.assertEqual(self.client.post(self.change_url(main), data).status_code, 302)
        self.assertEqual(related_product_ids("REL-B"), [])
        self.assertEqual(related_product_ids("REL-C"), ["REL-A"])
        self.assertIn("REL-B", logs.output[0])

    def test_a_product_cannot_relate_to_itself(self):
        main = self.product("REL-A")
        data = change_form_data(self.client.get(self.change_url(main)))
        data.update({"relations-TOTAL_FORMS": "1", "relations-0-related": main.it_id, "relations-0-ir_no": "0"})
        response = self.client.post(self.change_url(main), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("자기 자신은 관련상품으로", response.content.decode())
        self.assertFalse(ShopProductRelation.objects.exists())

    def test_mirroring_keeps_the_other_products_order(self):
        main, other, third = self.product("REL-A"), self.product("REL-B"), self.product("REL-C")
        ShopProductRelation.objects.create(product=other, related=third, ir_no=4)
        ShopProductRelation.objects.create(product=main, related=other, ir_no=1)
        mirror_product_relations(main)
        self.assertEqual(related_product_ids("REL-B"), ["REL-C", "REL-A"])
        self.assertEqual(ShopProductRelation.objects.get(product=other, related=main).ir_no, 5)

    def test_the_detail_api_lists_related_products_in_order(self):
        main, first, unsold = self.product("REL-A"), self.product("REL-B"), self.product("REL-C", it_use="0")
        ShopProductRelation.objects.create(product=main, related=unsold, ir_no=1)
        ShopProductRelation.objects.create(product=main, related=first, ir_no=2)
        data = APIClient().get(f"{API}/products/REL-A").json()["data"]
        self.assertEqual([row["it_id"] for row in data["related_items"]], ["REL-B"])

    def test_the_importer_reads_g5_shop_item_relation(self):
        self.product("REL-A")
        self.product("REL-B")
        command = GnuboardImportCommand()
        rows = [
            {"it_id": "REL-A", "it_id2": "REL-B", "ir_no": 0},
            {"it_id": "REL-B", "it_id2": "REL-A", "ir_no": 0},
            {"it_id": "REL-A", "it_id2": "REL-A", "ir_no": 1},
            {"it_id": "REL-A", "it_id2": "GONE", "ir_no": 2},
        ]
        self.assertEqual(command.import_shop_item_relations(rows), 2)
        self.assertEqual(command.import_shop_item_relations(rows), 2)  # idempotent
        self.assertEqual(ShopProductRelation.objects.count(), 2)


class ProductCopyTests(AdminBase):
    def setUp(self):
        super().setUp()
        self.second = ShopCategory.objects.create(ca_id="20", ca_name="잡화")
        self.source = self.product(
            "COPY-1",
            category2=self.second,
            it_price=12000,
            it_seo_title="copy-one",
            it_hit=50,
            it_sum_qty=7,
            it_use_cnt=3,
            it_use_avg=4.5,
            it_option_subject="색상",
            options=[{"io_no": 1, "io_id": "빨강", "io_type": 0, "io_price": 0, "io_stock_qty": 4, "io_noti_qty": 1, "io_use": 1}],
            image_url="/data/item/COPY-1/a.jpg",
            images=["/data/item/COPY-1/a.jpg", "https://cdn.example.test/b.jpg"],
        )
        ShopReview.objects.create(product=self.source, is_subject="좋아요", is_content="좋아요", is_score=5)

    def test_copy_takes_fields_options_and_categories_but_not_counters(self):
        copy = copy_product(self.source, "COPY-2")
        self.assertEqual((copy.it_name, copy.it_price, copy.category_id, copy.category2_id), ("상품 COPY-1", 12000, "10", "20"))
        self.assertEqual(copy.options, self.source.options)
        self.assertEqual(copy.it_option_subject, "색상")
        self.assertEqual((copy.it_hit, copy.it_sum_qty, copy.it_use_cnt, float(copy.it_use_avg)), (0, 0, 0, 0.0))
        self.assertEqual(copy.it_seo_title, "")
        # imported / external images are shared references (never deleted by either product)
        self.assertEqual(copy.images, self.source.images)
        self.assertEqual(copy.reviews.count(), 0)
        self.source.refresh_from_db()
        self.assertEqual(self.source.it_hit, 50)

    def test_a_taken_or_bad_code_is_refused(self):
        for bad in ("COPY-1", "", "한글", "x" * 21):
            with self.subTest(bad), self.assertRaises(ValidationError):
                copy_product(self.source, bad)

    def test_uploaded_images_get_their_own_files(self):
        with TemporaryDirectory() as media, self.settings(MEDIA_ROOT=media, MEDIA_URL="/media/", STORAGES=FILE_STORAGES):
            path = default_storage.save("shop/products/COPY-1/abc_photo.png", ContentFile(b"png-bytes"))
            url = default_storage.url(path)
            self.source.images = [{"url": url, "storage_path": path}, "https://cdn.example.test/b.jpg"]
            self.source.image_url = url
            self.source.save()
            copy = copy_product(self.source, "COPY-2")
            new_image = copy.images[0]
            self.assertTrue(new_image["storage_path"].startswith("shop/products/COPY-2/"))
            self.assertTrue(new_image["storage_path"].endswith("_photo.png"))
            self.assertNotEqual(new_image["storage_path"], path)
            with default_storage.open(new_image["storage_path"]) as handle:
                self.assertEqual(handle.read(), b"png-bytes")
            self.assertEqual(copy.image_url, new_image["url"])
            self.assertEqual(copy.images[1], "https://cdn.example.test/b.jpg")

    def test_a_missing_upload_is_left_out_of_the_copy(self):
        with TemporaryDirectory() as media, self.settings(MEDIA_ROOT=media, MEDIA_URL="/media/", STORAGES=FILE_STORAGES):
            self.source.images = [{"url": "/media/shop/products/COPY-1/x_gone.png", "storage_path": "shop/products/COPY-1/x_gone.png"}]
            self.source.image_url = "/media/shop/products/COPY-1/x_gone.png"
            self.source.save()
            copy = copy_product(self.source, "COPY-2")
            self.assertEqual((copy.images, copy.image_url), ([], ""))

    def test_the_copy_page_proposes_a_time_code_and_copies(self):
        url = reverse("admin:shop_shopproduct_copy", args=["COPY-1"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        proposed = response.context["form"].initial["new_it_id"]
        self.assertTrue(proposed.isdigit())
        response = self.client.post(url, {"new_it_id": "COPY-9"})
        self.assertRedirects(response, reverse("admin:shop_shopproduct_change", args=["COPY-9"]), fetch_redirect_response=False)
        self.assertTrue(ShopProduct.objects.filter(pk="COPY-9").exists())
        response = self.client.post(url, {"new_it_id": "COPY-9"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("이미 존재하는 상품코드", response.content.decode())
        self.assertContains(self.client.get(self.change_url(self.source)), url)

    def test_the_list_action_copies_each_selected_product(self):
        self.product("COPY-B")
        response = self.client.post(
            reverse("admin:shop_shopproduct_changelist"),
            {"action": "copy_selected_products", "_selected_action": ["COPY-1", "COPY-B"]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ShopProduct.objects.count(), 4)
        copies = ShopProduct.objects.exclude(pk__in=["COPY-1", "COPY-B"])
        self.assertTrue(all(product.it_id.isdigit() for product in copies))

    def test_next_product_id_skips_taken_codes(self):
        first = next_product_id()
        ShopProduct.objects.create(it_id=first, it_name="taken")
        self.assertGreater(int(next_product_id()), int(first) - 1)
        self.assertNotEqual(next_product_id(), first)
        self.assertNotIn(next_product_id(reserved=[str(int(first) + 1)]), {first, str(int(first) + 1)})


