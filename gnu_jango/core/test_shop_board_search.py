"""Shop review / Q&A lists: the search field (sfl) and hiding who asked a secret question.

Mirrors the reference API (api/v1/shop/reviews.php, reviews_qna_routes.php): `q` (or `stx`) with an
`sfl` whitelist — exact match for the writer's name and member id, prefix match for the item id,
substring match otherwise, every field when sfl is empty or unknown — and a secret question that the
viewer may not read shows "비공개" instead of its writer.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.shop.models import ShopProduct, ShopQA, ShopReview

API = "/api/v1/shop"
HIDDEN_NAME = "비공개"


class ShopBoardSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lamp = ShopProduct.objects.create(it_id="SRCH001", it_name="Brass lamp")
        cls.chair = ShopProduct.objects.create(it_id="SRCH002", it_name="Oak chair")
        cls.lamp_review = ShopReview.objects.create(
            product=cls.lamp, is_subject="Warm light", is_content="Looks like brass", is_name="kim", mb_id="kim"
        )
        cls.chair_review = ShopReview.objects.create(
            product=cls.chair, is_subject="Brass feet", is_content="Sturdy", is_name="lee", mb_id="lee"
        )
        cls.lamp_question = ShopQA.objects.create(
            product=cls.lamp, iq_subject="Bulb size?", iq_question="Which brass bulb", iq_name="park", mb_id="park"
        )
        cls.chair_question = ShopQA.objects.create(
            product=cls.chair, iq_subject="Brass legs?", iq_question="Colour", iq_name="choi", mb_id="choi"
        )

    def ids(self, path, **params):
        response = APIClient().get(f"{API}/{path}", params)
        self.assertEqual(response.status_code, 200, response.content[:300])
        key = "is_id" if path == "reviews" else "iq_id"
        return {row[key] for row in response.json()["data"]}

    def test_reviews_search_every_field_without_sfl(self):
        self.assertEqual(self.ids("reviews", q="brass"), {str(self.lamp_review.pk), str(self.chair_review.pk)})

    def test_reviews_search_one_field_with_sfl(self):
        self.assertEqual(self.ids("reviews", q="brass", sfl="i.it_name"), {str(self.lamp_review.pk)})
        self.assertEqual(self.ids("reviews", q="brass", sfl="r.is_subject"), {str(self.chair_review.pk)})

    def test_reviews_name_and_member_id_match_exactly(self):
        self.assertEqual(self.ids("reviews", q="kim", sfl="r.is_name"), {str(self.lamp_review.pk)})
        self.assertEqual(self.ids("reviews", q="ki", sfl="r.mb_id"), set())

    def test_reviews_item_id_matches_as_a_prefix(self):
        self.assertEqual(self.ids("reviews", q="SRCH00", sfl="r.it_id"), {str(self.lamp_review.pk), str(self.chair_review.pk)})
        self.assertEqual(self.ids("reviews", q="RCH001", sfl="r.it_id"), set())

    def test_stx_is_the_same_as_q_and_unknown_sfl_searches_everything(self):
        self.assertEqual(self.ids("reviews", stx="brass", sfl="no.such"), {str(self.lamp_review.pk), str(self.chair_review.pk)})

    def test_qna_search_one_field_with_sfl(self):
        self.assertEqual(self.ids("reviews/qna", q="brass"), {str(self.lamp_question.pk), str(self.chair_question.pk)})
        self.assertEqual(self.ids("reviews/qna", q="brass", sfl="q.iq_subject"), {str(self.chair_question.pk)})
        self.assertEqual(self.ids("reviews/qna", q="brass", sfl="q.iq_question"), {str(self.lamp_question.pk)})


class GeneralInquiryIsolationTests(TestCase):
    """1:1 inquiries are ShopQA rows on the "__general_qa__" pseudo product. They belong to the 1:1 API
    (community_qas) only — the product Q&A list, detail and "my product questions" must not serve them."""

    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.member = user_model.objects.create_user(username="member1", password="pw-member-123")
        general = ShopProduct.objects.create(it_id="__general_qa__", it_name="General Q&A")
        product = ShopProduct.objects.create(it_id="ITEM01", it_name="Real item")
        cls.inquiry = ShopQA.objects.create(
            product=general, user=cls.member, mb_id="member1", iq_name="Member", iq_subject="My account", iq_question="Private"
        )
        cls.question = ShopQA.objects.create(
            product=product, user=cls.member, mb_id="member1", iq_name="Member", iq_subject="Size?", iq_question="Public"
        )

    def client_for(self, user=None):
        client = APIClient()
        if user is not None:
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        return client

    def test_public_product_qna_list_leaves_out_one_to_one_inquiries(self):
        ids = {row["iq_id"] for row in self.client_for().get(f"{API}/reviews/qna").json()["data"]}

        self.assertEqual(ids, {str(self.question.pk)})

    def test_my_product_questions_leave_out_one_to_one_inquiries(self):
        ids = {row["iq_id"] for row in self.client_for(self.member).get(f"{API}/reviews/qna/mine").json()["data"]}

        self.assertEqual(ids, {str(self.question.pk)})

    def test_product_qna_detail_does_not_serve_a_one_to_one_inquiry(self):
        response = self.client_for(self.member).get(f"{API}/reviews/qna/{self.inquiry.pk}")

        self.assertEqual(response.status_code, 404)


class SecretQuestionWriterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.asker = user_model.objects.create_user(username="asker", password="pw-asker-123")
        cls.stranger = user_model.objects.create_user(username="stranger", password="pw-stranger-123")
        product = ShopProduct.objects.create(it_id="SECRET01", it_name="Secret item")
        cls.question = ShopQA.objects.create(
            product=product,
            user=cls.asker,
            mb_id="asker",
            mb_nick="Asker Nick",
            iq_name="Real Name",
            iq_subject="Private matter",
            iq_question="Details",
            iq_secret=1,
        )

    def row(self, user=None):
        client = APIClient()
        if user is not None:
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        response = client.get(f"{API}/reviews/qna", {"it_id": "SECRET01"})
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()["data"][0]

    def test_visitors_do_not_learn_who_asked(self):
        for viewer in (None, self.stranger):
            row = self.row(viewer)
            self.assertEqual(row["iq_name"], HIDDEN_NAME)
            self.assertEqual(row["mb_nick"], HIDDEN_NAME)
            self.assertEqual(row["mb_id"], "")

    def test_the_asker_still_sees_their_own_name(self):
        row = self.row(self.asker)

        self.assertEqual(row["iq_name"], "Real Name")
        self.assertEqual(row["mb_id"], "asker")
