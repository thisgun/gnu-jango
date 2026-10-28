"""OpenAPI contract tests for the shop catalogue reads (gnu_jango/api/contracts/shop.py)."""

from django.core.cache import cache
from django.test import TestCase

from gnu_jango.config.models import Config
from gnu_jango.core.contract_testing import ContractAssertions
from gnu_jango.shop.models import ShopCategory, ShopProduct, ShopProductRelation, ShopReview

CATEGORIES = "/api/v1/shop/categories"
CATEGORY_DETAIL = "/api/v1/shop/categories/{ca_id}"
PRODUCTS = "/api/v1/shop/products"
PRODUCT_DETAIL = "/api/v1/shop/products/{it_id}"
PRODUCT_BY_SEO = "/api/v1/shop/products/seo/{slug}"

CONTRACT_OPERATIONS = {
    ("GET", CATEGORIES),
    ("GET", CATEGORY_DETAIL),
    ("GET", PRODUCTS),
    ("GET", PRODUCT_DETAIL),
    ("GET", PRODUCT_BY_SEO),
}

CHOICE_OPTIONS = [
    {"io_no": 1, "io_id": "빨강\x1eL", "io_type": 0, "io_price": 0, "io_stock_qty": 10, "io_noti_qty": 2, "io_use": 1},
    {"io_no": 2, "io_id": "파랑\x1eM", "io_type": 0, "io_price": 500, "io_stock_qty": 0, "io_noti_qty": 2, "io_use": 0},
]
SUPPLY_OPTIONS = [
    {"io_no": 3, "io_id": "포장\x1e선물포장", "io_type": 1, "io_price": 2000, "io_stock_qty": 9999, "io_noti_qty": 100, "io_use": 1},
]


class ShopCatalogContractFixture(ContractAssertions, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.parent = ShopCategory.objects.create(ca_id="10", ca_name="의류", ca_order=1)
        cls.child = ShopCategory.objects.create(
            ca_id="1010", ca_name="셔츠", ca_parent="10", ca_list_mod=3, ca_list_row=2, ca_nocoupon=True
        )
        cls.leaf_parent = ShopCategory.objects.create(ca_id="20", ca_name="잡화", ca_order=2)
        ShopCategory.objects.create(ca_id="30", ca_name="빈 분류", ca_order=3)
        cls.optioned = ShopProduct.objects.create(
            it_id="CT001",
            category=cls.child,
            category2=cls.leaf_parent,
            it_name="옵션 셔츠",
            it_price=15000,
            it_notax=1,
            it_nocoupon=True,
            # subjects left blank: the payload makes them up from the option rows
            options=[*CHOICE_OPTIONS, *SUPPLY_OPTIONS],
            image_url="/media/shop/item/CT001_1.jpg",
            images=[{"url": "/media/shop/item/CT001_1.jpg"}, "/media/shop/item/CT001_2.jpg"],
            it_info_gubun="wear",
            it_info_value=[{"key": "material", "title": "", "value": "면 100%"}, {"key": "custom", "value": 3}],
        )
        cls.soldout = ShopProduct.objects.create(
            it_id="CT002",
            category=cls.child,
            it_name="품절 전화문의 상품",
            it_price=9000,
            it_soldout="1",
            it_tel_inq="1",
            it_stock_sms="1",
            it_type1="1",
        )
        cls.uncategorised = ShopProduct.objects.create(it_id="CT003", it_name="분류 없는 상품", it_price=100)
        ShopReview.objects.create(product=cls.optioned, is_subject="좋아요", is_score=4)
        ShopProductRelation.objects.create(product=cls.soldout, related=cls.optioned, ir_no=1)
        Config.objects.update_or_create(name="de_rel_list_use", defaults={"value": "1"})

    def setUp(self):
        cache.clear()


class ShopCategoryContractTests(ShopCatalogContractFixture):
    def test_categories_with_and_without_children_match_the_contract(self):
        response = self.client.get(CATEGORIES)

        tree = {row["ca_id"]: row for row in response.json()["data"]}
        self.assertEqual([child["ca_id"] for child in tree["10"]["children"]], ["1010"])
        self.assertEqual(tree["30"]["children"], [])
        self.assertMatchesContract(response, CATEGORIES)

    def test_a_child_category_carries_no_children_key(self):
        child = self.client.get(CATEGORIES).json()["data"][0]["children"][0]
        self.assertNotIn("children", child)

    def test_category_detail_with_subcategories_and_products_matches_the_contract(self):
        response = self.client.get("/api/v1/shop/categories/10")

        data = response.json()["data"]
        self.assertEqual([item["ca_id"] for item in data["subcategories"]], ["1010"])
        self.assertEqual({item["it_id"] for item in data["items"]}, {"CT001", "CT002"})
        self.assertMatchesContract(response, CATEGORY_DETAIL)

    def test_empty_category_detail_matches_the_contract(self):
        response = self.client.get("/api/v1/shop/categories/30")

        self.assertEqual(response.json()["data"]["items"], [])
        self.assertIsNone(response.json()["meta"]["from"])
        self.assertMatchesContract(response, CATEGORY_DETAIL)

    def test_category_detail_past_the_last_page_matches_the_contract(self):
        response = self.client.get("/api/v1/shop/categories/1010", {"page": 5})

        self.assertEqual(response.json()["data"]["items"], [])
        self.assertMatchesContract(response, CATEGORY_DETAIL)


class ShopProductContractTests(ShopCatalogContractFixture):
    def test_product_by_seo_address_matches_the_detail_contract(self):
        ShopProduct.objects.filter(pk="CT003").update(it_seo_title="no-category-product")

        response = self.client.get("/api/v1/shop/products/seo/no-category-product")

        self.assertEqual(response.json()["data"]["it_id"], "CT003")
        self.assertMatchesContract(response, PRODUCT_BY_SEO)

    def test_product_list_matches_the_contract(self):
        response = self.client.get(PRODUCTS)

        items = {item["it_id"]: item for item in response.json()["data"]}
        self.assertEqual(set(items), {"CT001", "CT002", "CT003"})
        self.assertIsNone(items["CT003"]["category"])
        self.assertEqual(items["CT003"]["images"], [])
        self.assertMatchesContract(response, PRODUCTS)

    def test_product_list_second_page_matches_the_contract(self):
        response = self.client.get(PRODUCTS, {"per_page": 2, "page": 2})

        self.assertEqual(len(response.json()["data"]), 1)
        self.assertEqual(response.json()["meta"]["current_page"], 2)
        self.assertMatchesContract(response, PRODUCTS)

    def test_product_with_choice_and_supply_options_and_images_matches_the_contract(self):
        response = self.client.get("/api/v1/shop/products/CT001")

        data = response.json()["data"]
        self.assertEqual([row["io_type"] for row in data["options"]], [0, 0, 1])
        self.assertEqual(data["it_option_subject"], "선택 옵션 1,선택 옵션 2")
        self.assertEqual(data["it_supply_subject"], "추가 옵션")
        self.assertEqual(len(data["images"]), 2)
        self.assertEqual(len(data["it_info_items"]), 2)
        self.assertEqual(data["it_notax"], 1)
        self.assertIs(data["it_nocoupon"], True)
        self.assertEqual(data["review_avg"], 4.0)
        self.assertMatchesContract(response, PRODUCT_DETAIL)

    def test_soldout_phone_inquiry_product_with_related_items_matches_the_contract(self):
        response = self.client.get("/api/v1/shop/products/CT002")

        data = response.json()["data"]
        self.assertEqual((data["it_soldout"], data["it_tel_inq"]), ("1", "1"))
        self.assertEqual([item["it_id"] for item in data["related_items"]], ["CT001"])
        self.assertEqual(data["prev_item"]["it_id"], "CT001")
        self.assertEqual(data["next_item"]["it_id"], "CT003")
        self.assertEqual(data["options"], [])
        self.assertMatchesContract(response, PRODUCT_DETAIL)

    def test_product_without_category_images_or_neighbour_matches_the_contract(self):
        response = self.client.get("/api/v1/shop/products/CT003")

        data = response.json()["data"]
        self.assertIsNone(data["category"])
        self.assertIsNone(data["next_item"])
        self.assertEqual((data["image_url"], data["images"]), ("", []))
        self.assertMatchesContract(response, PRODUCT_DETAIL)
