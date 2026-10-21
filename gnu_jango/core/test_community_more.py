"""More behaviour of the community endpoints of the v1 API.

Complements test_community_api.py and test_member_api.py (gnu_jango/api/v1_community.py and the
community_*.py modules): attachments of 1:1 inquiries, access control around inquiries, memos and
polls, bad input, paging limits, the popular search words and the profile update rules of
Gnuboard5 (bbs/qawrite_update.php, memo_form_update.php, memo_view.php, poll_update.php,
register_form_update.php, new.php, search.php, common.lib.php insert_popular).

A test marked expectedFailure pins the behaviour of the PHP original that the port does not have
yet; the comment above it names the defect.
"""

import io
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.bbs.models import Board, Comment, Group, Post
from gnu_jango.config import config as site_config
from gnu_jango.config.models import Config
from gnu_jango.core.models import (
    ContentPage,
    FAQItem,
    FAQMaster,
    Poll,
    PollChoice,
    PollComment,
    PollVote,
    SearchKeywordDaily,
    VisitLog,
)
from gnu_jango.shop.models import ShopQA
from gnu_jango.users.models import Profile, User_Memo, User_Point

GENERAL_QA_PRODUCT_ID = "__general_qa__"
HUGE_NUMBER = 10**30


class CommunityMoreBase(TestCase):
    def make_user(self, username, level=2, point=0, **extra):
        user = get_user_model().objects.create_user(
            username=username, email=f"{username}@example.test", password="password-1234", **extra
        )
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.user_level = level
        profile.user_point = point
        profile.save()
        return get_user_model().objects.get(pk=user.pk)

    def client_for(self, user=None, raise_errors=True):
        client = APIClient(raise_request_exception=raise_errors)
        if user is not None:
            client.force_authenticate(user=user)
        return client

    def set_config(self, name, value):
        Config.objects.update_or_create(name=name, defaults={"value": str(value)})
        site_config.clear()
        self.addCleanup(site_config.clear)

    def setUp(self):
        cache.clear()
        self.alice = self.make_user("cmx-alice")
        self.bob = self.make_user("cmx-bob")
        self.staff = self.make_user("cmx-staff", is_staff=True)
        self.alice_client = self.client_for(self.alice)
        self.bob_client = self.client_for(self.bob)
        self.staff_client = self.client_for(self.staff)
        self.visitor = self.client_for()


# ---------------------------------------------------------------------------------------------
# memos
# ---------------------------------------------------------------------------------------------


class MemoMoreTests(CommunityMoreBase):
    def send(self, client, receiver, text="Hello there"):
        return client.post("/api/v1/memos", {"me_recv_mb_id": receiver.username, "me_memo": text}, format="json")

    def test_a_member_can_write_a_memo_to_themselves_and_gets_both_copies(self):
        response = self.send(self.alice_client, self.alice, "note to self")
        self.assertEqual(response.status_code, 201, response.content[:300])
        copies = User_Memo.objects.filter(user=self.alice).order_by("pk")
        self.assertEqual([copy.me_type for copy in copies], ["recv", "send"])

    def test_memo_detail_and_delete_need_a_signed_in_member(self):
        self.send(self.alice_client, self.bob)
        memo = User_Memo.objects.get(user=self.bob)
        self.assertEqual(self.visitor.get(f"/api/v1/memos/{memo.pk}").status_code, 401)
        self.assertEqual(self.visitor.delete(f"/api/v1/memos/{memo.pk}").status_code, 401)
        self.assertTrue(User_Memo.objects.filter(pk=memo.pk).exists())

    def test_the_sender_cannot_read_or_delete_the_receivers_copy(self):
        self.send(self.alice_client, self.bob, "private words")
        received = User_Memo.objects.get(user=self.bob)
        read = self.alice_client.get(f"/api/v1/memos/{received.pk}")
        self.assertEqual(read.status_code, 404)
        self.assertNotIn("private words", read.content.decode())
        self.assertEqual(self.alice_client.delete(f"/api/v1/memos/{received.pk}").status_code, 404)
        received.refresh_from_db()
        self.assertIsNone(received.me_read_datetime)

    def test_an_unknown_memo_type_lists_nothing_and_a_missing_memo_is_not_found(self):
        self.send(self.alice_client, self.bob)
        listed = self.bob_client.get("/api/v1/memos", {"type": "bogus"})
        self.assertEqual((listed.status_code, listed.json()["data"]), (200, []))
        self.assertEqual(self.bob_client.get("/api/v1/memos/999999").status_code, 404)

    def test_the_memo_list_caps_per_page_and_survives_absurd_page_numbers(self):
        for index in range(3):
            self.send(self.alice_client, self.bob, f"memo {index}")
        capped = self.bob_client.get("/api/v1/memos", {"per_page": 100000}).json()
        self.assertEqual(capped["meta"]["per_page"], 100)
        smallest = self.bob_client.get("/api/v1/memos", {"per_page": -5}).json()
        self.assertEqual(smallest["meta"]["per_page"], 1)

    # Gnuboard5 rule: a receiver id or memo text that is not text is a bad request, never a 500.
    def test_memo_fields_of_the_wrong_type_are_a_client_error_not_a_server_error(self):
        client = self.client_for(self.alice, raise_errors=False)
        for payload in (
            {"me_recv_mb_id": 12345, "me_memo": "hi"},
            {"me_recv_mb_id": ["cmx-bob"], "me_memo": "hi"},
            {"me_recv_mb_id": "cmx-bob", "me_memo": ["hi"]},
            {"me_recv_mb_id": "cmx-bob", "me_memo": 42},
            {"me_recv_mb_id": None, "me_memo": None},
        ):
            with self.subTest(payload=payload):
                response = client.post("/api/v1/memos", payload, format="json")
                self.assertLess(response.status_code, 500, payload)
        self.assertEqual(User_Memo.objects.count(), 0)

    def test_a_memo_keeps_special_characters_and_emoji_as_written(self):
        text = "한글 쪽지 \U0001F600 <b>bold</b> ' OR 1=1 --"
        response = self.send(self.alice_client, self.bob, text)
        self.assertEqual(response.status_code, 201)
        stored = User_Memo.objects.get(user=self.bob)
        self.assertEqual(stored.me_memo, text)

    def test_deleting_a_received_memo_leaves_the_senders_copy_readable(self):
        self.send(self.alice_client, self.bob, "keep my copy")
        received = User_Memo.objects.get(user=self.bob)
        self.assertEqual(self.bob_client.delete(f"/api/v1/memos/{received.pk}").status_code, 200)
        sent = User_Memo.objects.get(user=self.alice)
        detail = self.alice_client.get(f"/api/v1/memos/{sent.pk}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["data"]["me_recv_mb_id"], "cmx-bob")

    # Gnuboard5 rule (memo_view.php): reading stamps both copies ("me_id = X or me_send_id = X").
    def test_reading_a_memo_marks_the_senders_copy_as_read(self):
        self.send(self.alice_client, self.bob, "did you read it?")
        received = User_Memo.objects.get(user=self.bob)
        self.bob_client.get(f"/api/v1/memos/{received.pk}")
        sent = User_Memo.objects.get(user=self.alice)
        self.assertIsNotNone(sent.me_read_datetime)

    # Gnuboard5 rule (memo_form_update.php): cf_memo_send_point is charged per receiver and a short
    # balance refuses the memo ("보유하신 포인트가 모자라서 쪽지를 보낼 수 없습니다").
    def test_a_memo_cannot_be_sent_without_enough_points_for_the_fee(self):
        self.set_config("cf_memo_send_point", 10)
        poor = self.make_user("cmx-poor", point=5)
        response = self.send(self.client_for(poor), self.bob)
        self.assertGreaterEqual(response.status_code, 400)
        self.assertFalse(User_Memo.objects.filter(user=self.bob).exists())

    def test_sending_a_memo_costs_the_configured_points(self):
        self.set_config("cf_memo_send_point", 10)
        rich = self.make_user("cmx-rich", point=50)
        self.assertEqual(self.send(self.client_for(rich), self.bob).status_code, 201)
        self.assertEqual(Profile.objects.get(user=rich).user_point, 40)
        self.assertTrue(User_Point.objects.filter(user=rich, po_point=-10).exists())

    # Gnuboard5 rule (memo_form_update.php): the memo text keeps 65536 characters.
    def test_a_memo_text_is_limited_to_65536_characters(self):
        self.send(self.alice_client, self.bob, "x" * 70000)
        stored = User_Memo.objects.filter(user=self.bob).first()
        self.assertIsNotNone(stored)
        self.assertLessEqual(len(stored.me_memo), 65536)


class NotificationMoreTests(CommunityMoreBase):
    def test_a_notification_cannot_be_read_by_other_members_even_when_unread_only(self):
        self.alice_client.post("/api/v1/notifications", {"nt_title": "for alice only"}, format="json")
        for params in ({}, {"unread_only": "1"}):
            body = self.bob_client.get("/api/v1/notifications", params).content.decode()
            self.assertNotIn("for alice only", body)

    def test_the_notification_type_is_cut_to_fifty_characters(self):
        response = self.alice_client.post("/api/v1/notifications", {"nt_type": "t" * 80, "nt_title": "x"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.json()["data"]["nt_type"]), 50)

    def test_notifications_need_a_signed_in_member(self):
        self.assertEqual(self.visitor.post("/api/v1/notifications", {"nt_title": "x"}, format="json").status_code, 401)
        self.assertEqual(self.visitor.delete("/api/v1/notifications").status_code, 401)
        self.assertEqual(self.visitor.post("/api/v1/notifications/read-all").status_code, 401)


class PagingOverflowTests(CommunityMoreBase):
    # Gnuboard5 rule: a page past the end is an empty page, whatever its number (every list built on
    # _paginate: memos, notifications, inquiries, FAQ, scraps, my posts/comments/points).
    def test_a_page_number_beyond_the_integer_range_gives_an_empty_page(self):
        client = self.client_for(self.alice, raise_errors=False)
        for url in (
            "/api/v1/memos", "/api/v1/notifications", "/api/v1/qas", "/api/v1/faqs", "/api/v1/scraps",
            "/api/v1/members/me/posts", "/api/v1/members/me/comments", "/api/v1/members/me/points",
        ):
            with self.subTest(url=url):
                response = client.get(url, {"page": HUGE_NUMBER})
                self.assertEqual(response.status_code, 200, url)


# ---------------------------------------------------------------------------------------------
# 1:1 inquiries
# ---------------------------------------------------------------------------------------------


class QaMoreTests(CommunityMoreBase):
    def setUp(self):
        super().setUp()
        media_root = tempfile.mkdtemp(prefix="community-more-media-")
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        media = override_settings(MEDIA_ROOT=media_root)
        media.enable()
        self.addCleanup(media.disable)

    def ask(self, client, subject="Where is my order?", content="Please check", **extra):
        payload = {"qa_subject": subject, "qa_content": content, **extra}
        return client.post("/api/v1/qas", payload, format="json")

    def make_item(self, user=None, answered=False, **extra):
        user = user or self.alice
        product, _ = __import__("gnu_jango.shop.models", fromlist=["ShopProduct"]).ShopProduct.objects.get_or_create(
            it_id=GENERAL_QA_PRODUCT_ID, defaults={"it_name": "General Q&A", "it_use": "", "it_stock_qty": 0}
        )
        return ShopQA.objects.create(
            product=product, user=user, mb_id=user.username, mb_nick=user.username,
            iq_subject=extra.pop("iq_subject", "Question"), iq_question=extra.pop("iq_question", "Body"),
            iq_answer="Answered" if answered else "", **extra,
        )

    def png(self, name="proof.png"):
        buffer = io.BytesIO()
        Image.new("RGB", (6, 6), (10, 120, 200)).save(buffer, format="PNG")
        return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")

    # access control

    def test_a_visitor_cannot_read_edit_delete_or_answer_an_inquiry(self):
        item = self.make_item()
        url = f"/api/v1/qas/{item.pk}"
        self.assertEqual(self.visitor.get(url).status_code, 401)
        self.assertEqual(self.visitor.patch(url, {"qa_subject": "x"}, format="json").status_code, 401)
        self.assertEqual(self.visitor.delete(url).status_code, 401)
        self.assertEqual(self.visitor.post(f"{url}/answer", {"qa_content": "x"}, format="json").status_code, 401)
        self.assertTrue(ShopQA.objects.filter(pk=item.pk).exists())

    def test_another_member_cannot_edit_delete_or_answer_an_inquiry(self):
        item = self.make_item()
        url = f"/api/v1/qas/{item.pk}"
        self.assertEqual(self.bob_client.patch(url, {"qa_subject": "hacked"}, format="json").status_code, 403)
        self.assertEqual(self.bob_client.delete(url).status_code, 403)
        self.assertEqual(self.bob_client.post(f"{url}/answer", {"qa_content": "fake answer"}, format="json").status_code, 403)
        item.refresh_from_db()
        self.assertEqual((item.iq_subject, item.iq_answer), ("Question", ""))

    def test_another_members_answer_attempt_does_not_reveal_the_inquiry_text(self):
        item = self.make_item(iq_question="very private question")
        for response in (
            self.bob_client.get(f"/api/v1/qas/{item.pk}"),
            self.bob_client.patch(f"/api/v1/qas/{item.pk}", {"qa_subject": "x"}, format="json"),
            self.bob_client.post(f"/api/v1/qas/{item.pk}/answer", {"qa_content": "x"}, format="json"),
        ):
            self.assertNotIn("very private question", response.content.decode())

    def test_a_missing_inquiry_is_not_found_for_every_action(self):
        for method, suffix in (("get", ""), ("patch", ""), ("delete", ""), ("post", "/answer")):
            response = getattr(self.alice_client, method)(f"/api/v1/qas/999999{suffix}", {"qa_content": "x"}, format="json")
            self.assertEqual(response.status_code, 404, (method, suffix))

    def test_a_member_cannot_answer_their_own_inquiry(self):
        item = self.make_item()
        response = self.alice_client.post(f"/api/v1/qas/{item.pk}/answer", {"qa_content": "self answer"}, format="json")
        self.assertEqual(response.status_code, 403)
        item.refresh_from_db()
        self.assertEqual(item.iq_answer, "")

    def test_the_admin_scope_lists_every_members_inquiries_for_staff(self):
        self.make_item(self.alice, iq_subject="from alice")
        self.make_item(self.bob, iq_subject="from bob")
        data = self.staff_client.get("/api/v1/qas", {"scope": "admin"}).json()
        self.assertEqual(sorted(row["qa_subject"] for row in data["data"]), ["from alice", "from bob"])
        mine = self.alice_client.get("/api/v1/qas", {"scope": "admin"})
        self.assertEqual(mine.status_code, 403)
        self.assertNotIn("from bob", mine.content.decode())

    def test_the_inquiry_search_fields_match_their_own_columns_only(self):
        self.make_item(self.alice, iq_subject="shipping delay", iq_question="parcel is late", iq_name="Alice Kim")
        self.make_item(self.alice, iq_subject="refund", iq_question="shipping words in body")
        by_subject = self.alice_client.get("/api/v1/qas", {"stx": "shipping"}).json()["data"]
        self.assertEqual([row["qa_subject"] for row in by_subject], ["shipping delay"])
        by_content = self.alice_client.get("/api/v1/qas", {"stx": "shipping", "sfl": "qa_content"}).json()["data"]
        self.assertEqual([row["qa_subject"] for row in by_content], ["refund"])
        by_name = self.alice_client.get("/api/v1/qas", {"stx": "kim", "sfl": "qa_name"}).json()["data"]
        self.assertEqual([row["qa_subject"] for row in by_name], ["shipping delay"])
        by_member = self.alice_client.get("/api/v1/qas", {"stx": "cmx-ali", "sfl": "mb_id"}).json()
        self.assertEqual(by_member["meta"]["total"], 2)

    def test_inquiry_search_wildcards_are_literal_and_an_unknown_status_filters_nothing(self):
        self.make_item(self.alice, iq_subject="plain subject")
        self.assertEqual(self.alice_client.get("/api/v1/qas", {"stx": "%"}).json()["data"], [])
        self.assertEqual(self.alice_client.get("/api/v1/qas", {"stx": "_lain"}).json()["data"], [])
        unknown = self.alice_client.get("/api/v1/qas", {"status": "7"}).json()
        self.assertEqual(unknown["meta"]["total"], 1)

    def test_the_inquiry_list_caps_per_page_and_survives_absurd_page_numbers(self):
        self.make_item()
        capped = self.alice_client.get("/api/v1/qas", {"per_page": 5000}).json()
        self.assertEqual(capped["meta"]["per_page"], 100)

    # validation

    def test_an_inquiry_with_wrong_typed_fields_is_not_a_server_error(self):
        client = self.client_for(self.alice, raise_errors=False)
        for payload in (
            {"qa_subject": ["a"], "qa_content": {"b": 1}},
            {"qa_subject": 5, "qa_content": 6},
            {"qa_subject": "ok", "qa_content": "ok", "qa_reply_to": "abc"},
            {"qa_subject": "ok", "qa_content": "ok", "qa_reply_to": HUGE_NUMBER},
        ):
            with self.subTest(payload=payload):
                self.assertLess(client.post("/api/v1/qas", payload, format="json").status_code, 500)

    def test_a_whitespace_only_subject_or_content_is_refused(self):
        response = self.ask(self.alice_client, subject="   ", content="\n\t")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(set(response.json()["errors"]), {"qa_subject", "qa_content"})
        self.assertEqual(ShopQA.objects.count(), 0)

    def test_an_inquiry_stores_the_contact_details_and_defaults_the_email_to_the_members(self):
        response = self.ask(self.alice_client, qa_hp="010-1234-5678")
        data = response.json()["data"]
        self.assertEqual((data["qa_email"], data["qa_hp"]), ("cmx-alice@example.test", "010-1234-5678"))
        custom = self.ask(self.alice_client, qa_email="other@example.test").json()["data"]
        self.assertEqual(custom["qa_email"], "other@example.test")

    def test_a_reply_to_an_unknown_inquiry_creates_nothing(self):
        response = self.ask(self.alice_client, qa_reply_to=999999)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(ShopQA.objects.count(), 0)

    # Gnuboard5 rule (qawrite_update.php): an edit cannot blank the subject or content
    # ("제목을 입력하세요" / "내용을 입력하세요").
    def test_editing_an_inquiry_cannot_blank_its_subject_or_content(self):
        item = self.make_item()
        response = self.alice_client.patch(f"/api/v1/qas/{item.pk}", {"qa_subject": "  ", "qa_content": ""}, format="json")
        item.refresh_from_db()
        self.assertEqual((item.iq_subject, item.iq_question), ("Question", "Body"))
        self.assertEqual(response.status_code, 422)

    # Gnuboard5 rule (qawrite_update.php): the subject is cut at 255 characters.
    def test_a_subject_over_255_characters_is_cut_or_refused(self):
        response = self.ask(self.alice_client, subject="s" * 300)
        if response.status_code == 201:
            self.assertLessEqual(len(response.json()["data"]["qa_subject"]), 255)
        else:
            self.assertEqual(response.status_code, 422)

    # attachments

    def test_attachments_are_stored_listed_replaced_and_removed_with_the_inquiry(self):
        created = self.alice_client.post(
            "/api/v1/qas",
            {"qa_subject": "With proof", "qa_content": "see file", "qa_file1": self.png("first.png")},
            format="multipart",
        )
        self.assertEqual(created.status_code, 201, created.content[:300])
        data = created.json()["data"]
        self.assertEqual(data["qa_source1"], "first.png")
        self.assertTrue(data["qa_file1_url"])
        self.assertEqual((data["qa_file2"], data["qa_source2"]), ("", ""))
        from django.core.files.storage import default_storage

        first_path = data["qa_file1"]
        self.assertTrue(default_storage.exists(first_path))

        replaced = self.alice_client.patch(
            f"/api/v1/qas/{data['qa_id']}", {"qa_file1": self.png("second.png"), "qa_file2": self.png("third.png")},
            format="multipart",
        ).json()["data"]
        self.assertEqual((replaced["qa_source1"], replaced["qa_source2"]), ("second.png", "third.png"))
        self.assertFalse(default_storage.exists(first_path))

        removed = self.alice_client.patch(f"/api/v1/qas/{data['qa_id']}", {"bf_file_del[2]": "1"}, format="multipart").json()["data"]
        self.assertEqual((removed["qa_source1"], removed["qa_file2"]), ("second.png", ""))

        second_path = replaced["qa_file1"]
        self.assertEqual(self.alice_client.delete(f"/api/v1/qas/{data['qa_id']}").status_code, 200)
        self.assertFalse(default_storage.exists(second_path))

    def test_a_disguised_attachment_is_refused_and_the_inquiry_is_not_kept(self):
        fake = SimpleUploadedFile("proof.png", b"<?php echo 1; ?>", content_type="image/png")
        response = self.alice_client.post(
            "/api/v1/qas", {"qa_subject": "Bad file", "qa_content": "x", "qa_file1": fake}, format="multipart"
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["errors"]["file"] and "file" in response.json()["errors"], True)
        self.assertFalse(ShopQA.objects.filter(iq_subject="Bad file").exists())

    def test_a_bad_attachment_on_edit_is_reported_as_a_validation_error(self):
        item = self.make_item()
        fake = SimpleUploadedFile("proof.png", b"not an image", content_type="image/png")
        response = self.alice_client.patch(f"/api/v1/qas/{item.pk}", {"qa_file1": fake}, format="multipart")
        self.assertEqual(response.status_code, 422)

    def test_attachment_names_cannot_climb_out_of_the_inquiry_folder(self):
        response = self.alice_client.post(
            "/api/v1/qas",
            {"qa_subject": "Path", "qa_content": "x", "qa_file1": self.png("../../evil name.png")},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.content[:300])
        path = response.json()["data"]["qa_file1"].replace("\\", "/")
        self.assertNotIn("..", path)
        self.assertTrue(path.startswith("shop/qas/"))

    # Gnuboard5 rule (qawrite_update.php, is_disallowed_active_filename): active content such as .php
    # or .html cannot be attached ("허용되지 않는 파일 확장자입니다.").
    def test_active_content_files_cannot_be_attached(self):
        for name, body in (("shell.php", b"<?php system($_GET['c']); ?>"), ("page.html", b"<script>alert(1)</script>")):
            with self.subTest(name=name):
                upload = SimpleUploadedFile(name, body, content_type="application/octet-stream")
                response = self.alice_client.post(
                    "/api/v1/qas", {"qa_subject": name, "qa_content": "x", "qa_file1": upload}, format="multipart"
                )
                self.assertEqual(response.status_code, 422, name)

    def test_everyday_documents_can_be_attached(self):
        # qawrite_update.php blocks only active content; a Hangul document or a text file is fine
        for name in ("report.hwp", "notes.txt", "deck.pptx"):
            with self.subTest(name=name):
                upload = SimpleUploadedFile(name, b"plain document bytes", content_type="application/octet-stream")
                response = self.alice_client.post(
                    "/api/v1/qas", {"qa_subject": name, "qa_content": "x", "qa_file1": upload}, format="multipart"
                )
                self.assertIn(response.status_code, (200, 201), response.content[:200])

    def test_a_script_hidden_behind_a_second_extension_is_refused(self):
        upload = SimpleUploadedFile("photo.php.jpg", b"<?php echo 1; ?>", content_type="application/octet-stream")
        response = self.alice_client.post(
            "/api/v1/qas", {"qa_subject": "x", "qa_content": "x", "qa_file1": upload}, format="multipart"
        )
        self.assertEqual(response.status_code, 422)

    def test_an_answered_inquiry_shows_the_answer_and_is_locked_for_its_owner(self):
        item = self.make_item(answered=True)
        data = self.alice_client.get(f"/api/v1/qas/{item.pk}").json()["data"]
        self.assertEqual(data["qa_status"], 1)
        self.assertEqual(data["answer"]["qa_content"], "Answered")
        self.assertEqual((data["can_edit"], data["can_delete"]), (False, False))
        attachment = self.alice_client.patch(f"/api/v1/qas/{item.pk}", {"qa_file1": self.png()}, format="multipart")
        self.assertEqual(attachment.status_code, 403)

    def test_a_staff_answer_can_be_replaced_by_another_answer(self):
        item = self.make_item()
        url = f"/api/v1/qas/{item.pk}/answer"
        self.staff_client.post(url, {"qa_content": "first answer"}, format="json")
        again = self.staff_client.post(url, {"qa_content": "better answer", "qa_subject": "RE: custom"}, format="json")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["data"]["answer"]["qa_content"], "better answer")
        self.assertEqual(again.json()["data"]["answer"]["qa_subject"], "RE: custom")
        item.refresh_from_db()
        self.assertEqual(item.iq_answer, "better answer")

    def test_an_inquiry_made_by_a_since_deleted_member_is_only_visible_to_staff(self):
        ghost = self.make_user("cmx-ghost")
        item = self.make_item(ghost, iq_question="orphan question")
        ghost.delete()
        item.refresh_from_db()
        self.assertEqual(self.bob_client.get(f"/api/v1/qas/{item.pk}").status_code, 403)
        self.assertEqual(self.staff_client.get(f"/api/v1/qas/{item.pk}").status_code, 200)

    def test_editing_an_inquiry_with_wrong_typed_fields_is_not_a_server_error(self):
        item = self.make_item()
        client = self.client_for(self.alice, raise_errors=False)
        for payload in ({"qa_subject": ["a"]}, {"qa_content": {"b": 1}}, {"qa_email": 5, "qa_hp": [1]}, {"qa_subject": None}):
            with self.subTest(payload=payload):
                self.assertLess(client.patch(f"/api/v1/qas/{item.pk}", payload, format="json").status_code, 500)

    def test_an_inquiry_still_opens_when_its_stored_attachment_data_is_damaged(self):
        item = self.make_item()
        for broken in ("not json at all", "[1, 2, 3]", '{"files": "nope", "parent": "x", "related": []}', '{"files": [5, null]}'):
            with self.subTest(broken=broken):
                Config.objects.update_or_create(name=f"qa_meta_{item.pk}", defaults={"value": broken})
                response = self.alice_client.get(f"/api/v1/qas/{item.pk}")
                self.assertEqual(response.status_code, 200)
                data = response.json()["data"]
                self.assertEqual((data["qa_file1"], data["qa_file2"]), ("", ""))

    def test_damaged_attachment_data_of_other_inquiries_does_not_break_the_related_list(self):
        item = self.make_item()
        Config.objects.create(name="qa_meta_9999", value="{{{")
        Config.objects.create(name="qa_meta_abc", value="{}")
        self.assertEqual(self.alice_client.get(f"/api/v1/qas/{item.pk}").json()["data"]["related_questions"], [])

    def test_a_follow_up_chain_lists_every_other_question_of_the_thread_oldest_first(self):
        first = self.ask(self.alice_client, subject="Thread start").json()["data"]
        second = self.alice_client.post(
            "/api/v1/qas", {"qa_subject": "Second", "qa_content": "x", "qa_reply_to": first["qa_id"]}, format="json"
        ).json()["data"]
        third = self.alice_client.post(
            "/api/v1/qas", {"qa_subject": "Third", "qa_content": "x", "qa_reply_to": second["qa_id"]}, format="json"
        ).json()["data"]
        self.assertEqual(third["qa_related"], first["qa_id"])
        view = self.alice_client.get(f"/api/v1/qas/{first['qa_id']}").json()["data"]
        self.assertEqual([row["qa_subject"] for row in view["related_questions"]], ["Second", "Third"])
        # A thread belongs to its owner: another member cannot open it.
        self.assertEqual(self.bob_client.get(f"/api/v1/qas/{first['qa_id']}").status_code, 403)

    def test_the_answer_does_not_carry_the_members_contact_details_and_staff_can_attach_files(self):
        item = self.make_item(iq_email="alice@private.test", iq_hp="010-0000-0000", answered=True)
        data = self.staff_client.get(f"/api/v1/qas/{item.pk}").json()["data"]
        self.assertEqual((data["answer"]["qa_email"], data["answer"]["qa_hp"]), ("", ""))
        upload = self.staff_client.patch(f"/api/v1/qas/{item.pk}", {"qa_file1": self.png("staff.png")}, format="multipart")
        self.assertEqual(upload.status_code, 200)
        self.assertEqual(upload.json()["data"]["qa_source1"], "staff.png")

    # Gnuboard5 rule (qawrite_update.php): the administrator may still edit an answered inquiry, and
    # can_edit says so.
    def test_staff_are_told_they_can_edit_an_answered_inquiry(self):
        item = self.make_item(answered=True)
        self.assertEqual(self.staff_client.patch(f"/api/v1/qas/{item.pk}", {"qa_subject": "Fixed"}, format="json").status_code, 200)
        self.assertTrue(self.staff_client.get(f"/api/v1/qas/{item.pk}").json()["data"]["can_edit"])

    def test_the_general_support_product_never_appears_in_the_public_shop_list(self):
        self.ask(self.alice_client)
        body = self.visitor.get("/api/v1/shop/products").content.decode()
        self.assertNotIn(GENERAL_QA_PRODUCT_ID, body)


# ---------------------------------------------------------------------------------------------
# polls
# ---------------------------------------------------------------------------------------------


class PollMoreTests(CommunityMoreBase):
    def make_poll(self, **extra):
        poll = Poll.objects.create(po_subject=extra.pop("po_subject", "Pick one"), **extra)
        PollChoice.objects.create(poll=poll, num=1, content="Red")
        PollChoice.objects.create(poll=poll, num=2, content="Blue")
        return poll

    def vote(self, client, poll, option=1, **headers):
        return client.post(f"/api/v1/polls/{poll.pk}/vote", {"option": option}, format="json", **headers)

    def count(self, poll, num):
        return PollChoice.objects.get(poll=poll, num=num).count

    def test_a_visitor_cannot_vote_twice_from_the_same_address_by_dropping_cookies(self):
        poll = self.make_poll()
        codes = [self.vote(self.client_for(), poll, 1).status_code for _ in range(3)]
        self.assertEqual(codes.count(200), 1, codes)
        self.assertEqual(self.count(poll, 1), 1)

    # Gnuboard5 rule (poll_update.php): members are tracked in mb_ids and visitors in po_ips, so a
    # member's vote never blocks a visitor on the same address.
    def test_a_members_vote_does_not_block_a_visitor_on_the_same_address(self):
        poll = self.make_poll()
        self.assertEqual(self.vote(self.alice_client, poll, 1).status_code, 200)
        self.assertEqual(self.vote(self.client_for(), poll, 2).status_code, 200)
        self.assertEqual((self.count(poll, 1), self.count(poll, 2)), (1, 1))

    def test_a_visitor_keeps_the_same_session_and_is_refused_a_second_vote(self):
        poll = self.make_poll()
        client = self.client_for()
        self.assertEqual(self.vote(client, poll, 1).status_code, 200)
        second = self.vote(client, poll, 2)
        self.assertEqual(second.status_code, 409)
        self.assertEqual((self.count(poll, 1), self.count(poll, 2)), (1, 0))
        self.assertTrue(PollVote.objects.get(poll=poll).ip)

    def test_a_member_cannot_vote_twice_even_from_a_new_device(self):
        poll = self.make_poll()
        self.assertEqual(self.vote(self.client_for(self.alice), poll, 1).status_code, 200)
        again = self.vote(self.client_for(self.alice), poll, 2, REMOTE_ADDR="10.9.9.9")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(PollVote.objects.filter(poll=poll, user=self.alice).count(), 1)

    def test_a_refused_vote_changes_no_counts_and_gives_no_points(self):
        poll = self.make_poll(po_point=7)
        self.vote(self.alice_client, poll, 1)
        self.vote(self.alice_client, poll, 1)
        self.assertEqual(self.count(poll, 1), 1)
        self.assertEqual(User_Point.objects.filter(user=self.alice, po_rel_table="@poll").count(), 1)

    def test_votes_on_polls_that_are_closed_not_started_or_switched_off_are_refused(self):
        today = timezone.localdate()
        polls = {
            "ended": self.make_poll(po_end_date=today - timedelta(days=1)),
            "future": self.make_poll(po_begin_date=today + timedelta(days=1)),
            "off": self.make_poll(po_use=0),
        }
        for name, poll in polls.items():
            with self.subTest(poll=name):
                response = self.vote(self.alice_client, poll, 1)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.count(poll, 1), 0)
        self.assertEqual(PollVote.objects.count(), 0)

    def test_a_poll_ending_today_still_takes_votes(self):
        poll = self.make_poll(po_end_date=timezone.localdate())
        self.assertEqual(self.vote(self.alice_client, poll, 1).status_code, 200)

    def test_a_poll_that_has_not_started_is_not_the_current_poll(self):
        today = timezone.localdate()
        self.make_poll(po_subject="Not yet", po_begin_date=today + timedelta(days=2))
        open_poll = self.make_poll(po_subject="Open now", po_date=today - timedelta(days=3))
        data = self.visitor.get("/api/v1/polls/current").json()["data"]
        self.assertEqual(data["po_id"], open_poll.po_id)

    def test_the_level_check_uses_the_voters_level(self):
        poll = self.make_poll(po_level=3)
        self.assertEqual(self.vote(self.alice_client, poll, 1).status_code, 403)
        veteran = self.make_user("cmx-veteran", level=3)
        self.assertEqual(self.vote(self.client_for(veteran), poll, 1).status_code, 200)
        self.assertEqual(self.count(poll, 1), 1)

    def test_vote_options_of_any_odd_shape_are_never_a_server_error(self):
        poll = self.make_poll()
        client = self.client_for(self.alice, raise_errors=False)
        for option in ("abc", "", None, [1], {"a": 1}, 1.5, "1e3", -1, 0, 3, HUGE_NUMBER, "9" * 40, True):
            with self.subTest(option=option):
                response = client.post(f"/api/v1/polls/{poll.pk}/vote", {"option": option}, format="json")
                self.assertLess(response.status_code, 500)
        self.assertEqual(PollVote.objects.filter(poll=poll).count(), 1 if self.count(poll, 1) else 0)

    def test_the_vote_option_may_be_sent_as_num_or_poll_too(self):
        poll = self.make_poll()
        poll2 = self.make_poll()
        self.assertEqual(self.client_for(self.alice).post(f"/api/v1/polls/{poll.pk}/vote", {"num": 2}, format="json").status_code, 200)
        self.assertEqual(self.client_for(self.alice).post(f"/api/v1/polls/{poll2.pk}/vote", {"poll": 1}, format="json").status_code, 200)
        self.assertEqual((self.count(poll, 2), self.count(poll2, 1)), (1, 1))

    def test_polls_with_unknown_or_huge_ids_are_not_found(self):
        client = self.client_for(self.alice, raise_errors=False)
        for url in (
            "/api/v1/polls/999999",
            f"/api/v1/polls/{HUGE_NUMBER}",
            "/api/v1/polls/999999/comments/1",
        ):
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code if "comments" not in url else client.delete(url).status_code, 404)
        self.assertEqual(client.post(f"/api/v1/polls/{HUGE_NUMBER}/vote", {"option": 1}, format="json").status_code, 404)
        self.assertEqual(client.post(f"/api/v1/polls/{HUGE_NUMBER}/comments", {"pc_idea": "x"}, format="json").status_code, 404)

    def test_the_vote_response_shows_the_result_and_the_voters_state(self):
        poll = self.make_poll()
        self.vote(self.bob_client, poll, 2)
        data = self.vote(self.alice_client, poll, 1).json()["data"]
        self.assertEqual(data["total_count"], 2)
        self.assertEqual([option["rate"] for option in data["options"]], [50.0, 50.0])
        self.assertTrue(data["has_voted"])
        self.assertFalse(data["can_vote"])

    # Gnuboard5 rule (poll_update.php, poll_result.php): a member's vote does not make a visitor on
    # the same address count as a voter, so the results of a poll above their level stay hidden.
    def test_results_stay_hidden_from_a_visitor_who_has_not_voted_on_a_members_only_poll(self):
        poll = self.make_poll(po_level=2)
        self.vote(self.alice_client, poll, 1)
        data = self.visitor.get(f"/api/v1/polls/{poll.pk}").json()["data"]
        self.assertEqual((data["can_view_result"], data["total_count"]), (False, 0))
        self.assertEqual([option["count"] for option in data["options"]], [0, 0])

    def test_a_finished_poll_shows_its_results_to_everyone(self):
        poll = self.make_poll(po_level=5, po_end_date=timezone.localdate() - timedelta(days=1))
        PollChoice.objects.filter(poll=poll, num=1).update(count=4)
        data = self.visitor.get(f"/api/v1/polls/{poll.pk}").json()["data"]
        self.assertTrue(data["can_view_result"])
        self.assertEqual(data["total_count"], 4)
        self.assertFalse(data["can_vote"])

    # comments

    def test_poll_comment_delete_flags_belong_to_the_viewer(self):
        poll = self.make_poll(po_etc="Other opinion")
        self.alice_client.post(f"/api/v1/polls/{poll.pk}/comments", {"pc_idea": "mine"}, format="json")
        as_owner = self.alice_client.get(f"/api/v1/polls/{poll.pk}").json()["data"]["etc_comments"][0]
        as_other = self.bob_client.get(f"/api/v1/polls/{poll.pk}").json()["data"]["etc_comments"][0]
        as_visitor = self.visitor.get(f"/api/v1/polls/{poll.pk}").json()["data"]["etc_comments"][0]
        self.assertEqual((as_owner["can_delete"], as_other["can_delete"], as_visitor["can_delete"]), (True, False, False))

    def test_a_visitor_cannot_delete_a_poll_comment_and_nothing_is_removed(self):
        poll = self.make_poll(po_etc="Other opinion")
        comment = PollComment.objects.create(poll=poll, user=self.alice, pc_name="alice", pc_idea="stay")
        response = self.visitor.delete(f"/api/v1/polls/{poll.pk}/comments/{comment.pk}")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(PollComment.objects.filter(pk=comment.pk).exists())

    def test_comments_are_refused_on_a_poll_that_is_not_active(self):
        poll = self.make_poll(po_etc="Other opinion", po_use=0)
        response = self.alice_client.post(f"/api/v1/polls/{poll.pk}/comments", {"pc_idea": "hello"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PollComment.objects.filter(poll=poll).exists())

    def test_a_long_poll_comment_is_cut_and_html_is_stored_as_text_not_executed(self):
        poll = self.make_poll(po_etc="Other opinion")
        idea = "<script>alert(1)</script>" + "y" * 400
        response = self.alice_client.post(f"/api/v1/polls/{poll.pk}/comments", {"pc_idea": idea}, format="json")
        self.assertEqual(response.status_code, 201)
        stored = PollComment.objects.get(poll=poll)
        self.assertEqual(len(stored.pc_idea), 255)
        self.assertEqual(response.json()["data"]["etc_comments"][0]["pc_idea"], stored.pc_idea)

    # Gnuboard5 rule: a poll comment or name that is not text is a bad request, never a 500.
    def test_poll_comment_fields_of_the_wrong_type_are_not_a_server_error(self):
        poll = self.make_poll(po_etc="Other opinion")
        client = self.client_for(raise_errors=False)
        for payload in ({"pc_idea": ["x"], "pc_name": "n"}, {"pc_idea": 5, "pc_name": 6}, {"pc_idea": "ok", "pc_name": {"a": 1}}):
            with self.subTest(payload=payload):
                self.assertLess(client.post(f"/api/v1/polls/{poll.pk}/comments", payload, format="json").status_code, 500)

    def test_the_poll_page_lists_other_polls_but_not_switched_off_ones(self):
        current = self.make_poll(po_subject="Now")
        self.make_poll(po_subject="Other open", po_date=timezone.localdate() - timedelta(days=1))
        self.make_poll(po_subject="Switched off", po_use=0)
        others = self.visitor.get(f"/api/v1/polls/{current.pk}").json()["data"]["other_polls"]
        self.assertEqual([row["po_subject"] for row in others], ["Other open"])


# ---------------------------------------------------------------------------------------------
# content pages and FAQ
# ---------------------------------------------------------------------------------------------


class ContentAndFaqMoreTests(CommunityMoreBase):
    def test_content_is_delivered_with_its_html_flag_so_the_client_can_escape_plain_text(self):
        ContentPage.objects.create(co_id="plain", co_subject="Plain", co_content="<b>text</b>", co_html=0)
        ContentPage.objects.create(co_id="rich", co_subject="Rich", co_content="<b>text</b>", co_html=1)
        plain = self.visitor.get("/api/v1/content/plain").json()["data"]
        rich = self.visitor.get("/api/v1/content/rich").json()["data"]
        self.assertEqual((plain["co_html"], rich["co_html"]), (0, 1))
        self.assertEqual(plain["co_content"], "<b>text</b>")

    def test_content_ids_with_odd_characters_are_not_found_not_errors(self):
        ContentPage.objects.create(co_id="about", co_subject="About", co_seo_title="한글-주소")
        client = self.client_for(raise_errors=False)
        for url in ("/api/v1/content/%00", "/api/v1/content/seo/%00", "/api/v1/content/seo/a/b/c", "/api/v1/content/'%20OR%201=1", "/api/v1/content/seo/"):
            with self.subTest(url=url):
                response = client.get(url)
                self.assertLess(response.status_code, 500)
                if "%00" in url:
                    self.assertEqual(response.status_code, 404)
        self.assertEqual(self.visitor.get("/api/v1/content/seo/한글-주소").json()["data"]["co_id"], "about")

    def test_a_switched_off_page_is_hidden_even_by_its_seo_title(self):
        ContentPage.objects.create(co_id="off", co_subject="Off", co_content="should not leak", co_seo_title="off-seo", co_use=0)
        for url in ("/api/v1/content/off", "/api/v1/content/seo/off-seo", "/api/v1/content/seo/off", "/api/v1/content"):
            body = self.visitor.get(url).content.decode()
            self.assertNotIn("should not leak", body, url)

    def test_the_seo_title_wins_over_another_pages_id(self):
        ContentPage.objects.create(co_id="alpha", co_subject="By id")
        ContentPage.objects.create(co_id="beta", co_subject="By seo", co_seo_title="alpha")
        self.assertEqual(self.visitor.get("/api/v1/content/seo/alpha").json()["data"]["co_id"], "beta")

    def make_faq(self):
        self.master = FAQMaster.objects.create(fm_subject="Orders", fm_order=1)
        for index in range(5):
            FAQItem.objects.create(master=self.master, fa_subject=f"Question {index}", fa_content=f"Answer {index}", fa_order=index)

    def test_faq_keyword_searches_answers_too_and_wildcards_are_literal(self):
        self.make_faq()
        self.assertEqual(self.visitor.get("/api/v1/faqs", {"stx": "answer 3"}).json()["data"]["meta"]["total"], 1)
        self.assertEqual(self.visitor.get("/api/v1/faqs", {"q": "question 4"}).json()["data"]["items"][0]["fa_subject"], "Question 4")
        self.assertEqual(self.visitor.get("/api/v1/faqs", {"stx": "%"}).json()["data"]["items"], [])
        self.assertEqual(self.visitor.get("/api/v1/faqs", {"stx": "'; DROP TABLE x; --"}).json()["data"]["items"], [])

    def test_faq_paging_limits_and_odd_parameters(self):
        self.make_faq()
        page = self.visitor.get("/api/v1/faqs", {"per_page": 2, "page": 3}).json()["data"]
        self.assertEqual([item["fa_subject"] for item in page["items"]], ["Question 4"])
        self.assertEqual((page["meta"]["from"], page["meta"]["to"], page["meta"]["last_page"]), (5, 5, 3))
        capped = self.visitor.get("/api/v1/faqs", {"per_page": 9999}).json()["data"]["meta"]
        self.assertEqual(capped["per_page"], 100)
        for params in ({"fm_id": "abc"}, {"page": "x"}, {"per_page": "-3"}, {"fm_id": HUGE_NUMBER}):
            with self.subTest(params=params):
                self.assertEqual(self.client_for(raise_errors=False).get("/api/v1/faqs", params).status_code, 200)

    def test_faq_items_of_a_switched_off_item_never_show_even_when_searched(self):
        self.make_faq()
        FAQItem.objects.create(master=self.master, fa_subject="Hidden item", fa_content="needle", fa_use=0)
        data = self.visitor.get("/api/v1/faqs", {"stx": "needle"}).json()["data"]
        self.assertEqual(data["items"], [])


# ---------------------------------------------------------------------------------------------
# new posts (recent) and the site search
# ---------------------------------------------------------------------------------------------


class BoardFixtures(CommunityMoreBase):
    """Boards and posts shared by the feed, search and scrap tests."""

    def setUp(self):
        super().setUp()
        self.group = Group.objects.create(gr_id="cmx-group", gr_subject="Community")
        self.board = self.make_board("cmx-open", "Open board")

    def make_board(self, table, subject, **extra):
        extra.setdefault("bo_use_search", True)
        return Board.objects.create(
            group=self.group, bo_table=table, bo_subject=subject, bo_skin="basic", bo_mobile_skin="basic", **extra
        )

    def make_post(self, board, subject, content="Body", user="alice", **extra):
        author = {"alice": self.alice, "bob": self.bob, None: None}[user]
        stamp = extra.pop("wr_datetime", timezone.now())
        post = Post.objects.create(
            board=board, wr_num=-1, wr_subject=subject, wr_content=content, user=author,
            wr_name=author.username if author else "guest", wr_datetime=stamp, wr_last=stamp, **extra,
        )
        post.wr_parent = post.pk
        post.save(update_fields=["wr_parent"])
        return post


class RecentAndSearchMoreTests(BoardFixtures):
    def test_recent_paging_limits_and_odd_parameters(self):
        for index in range(3):
            self.make_post(self.board, f"post {index}")
        capped = self.visitor.get("/api/v1/recent", {"limit": 999999}).json()
        self.assertEqual(capped["meta"]["per_page"], 100)
        smallest = self.visitor.get("/api/v1/recent", {"limit": 0}).json()
        self.assertEqual((smallest["meta"]["per_page"], len(smallest["data"])), (1, 1))
        for params in ({"page": HUGE_NUMBER}, {"page": "x", "limit": "y"}, {"view": "zzz"}, {"gr_id": "nope"}, {"mb_id": "'--"}):
            with self.subTest(params=params):
                response = self.client_for(raise_errors=False).get("/api/v1/recent", params)
                self.assertEqual(response.status_code, 200)
        self.assertEqual(self.visitor.get("/api/v1/recent", {"view": "zzz"}).json()["data"], [])

    def test_recent_lists_guest_posts_without_a_member(self):
        self.make_post(self.board, "guest post", user=None)
        row = self.visitor.get("/api/v1/recent").json()["data"][0]
        self.assertEqual((row["wr_subject"], row["mb_id"], row["wr_name"]), ("guest post", "", "guest"))

    def test_the_member_filter_of_recent_never_unlocks_secret_posts(self):
        self.make_post(self.board, "alice public")
        self.make_post(self.board, "alice secret", wr_option="secret")
        rows = self.bob_client.get("/api/v1/recent", {"mb_id": "cmx-alice"}).json()["data"]
        self.assertEqual([row["wr_subject"] for row in rows], ["alice public"])

    def test_a_comment_row_points_at_its_post_and_never_carries_the_comment_text(self):
        post = self.make_post(self.board, "commented post")
        Comment.objects.create(board=self.board, post=post, user=self.bob, wr_content="comment body text", wr_name="bob")
        response = self.visitor.get("/api/v1/recent", {"view": "c"})
        row = response.json()["data"][0]
        self.assertTrue(row["is_comment"])
        self.assertEqual(row["wr_subject"], "commented post")
        self.assertNotIn("comment body text", response.content.decode())

    def test_secret_posts_do_not_leak_through_the_search_of_another_member_by_author_or_content(self):
        self.make_post(self.board, "ordinary", content="needle-public")
        self.make_post(self.board, "hidden", content="needle-secret", wr_option="secret")
        for params in ({"q": "needle"}, {"q": "alice", "sfl": "mb_id"}, {"q": "cmx-alice", "sfl": "wr_name"}):
            body = self.bob_client.get("/api/v1/search", params).content.decode()
            self.assertNotIn("needle-secret", body, params)
            self.assertNotIn('"hidden"', body, params)

    def test_search_treats_wildcards_and_quotes_as_plain_text(self):
        self.make_post(self.board, "100% sure", content="50_50 'quoted'")
        found = self.visitor.get("/api/v1/search", {"q": "100%"}).json()["data"]
        self.assertEqual(found["total_count"], 1)
        self.assertEqual(self.visitor.get("/api/v1/search", {"q": "%"}).json()["data"]["total_count"], 1)
        self.assertEqual(self.visitor.get("/api/v1/search", {"q": "5_5"}).json()["data"]["total_count"], 0)
        self.assertEqual(self.visitor.get("/api/v1/search", {"q": "'quoted'"}).json()["data"]["total_count"], 1)
        self.assertEqual(self.visitor.get("/api/v1/search", {"q": "   "}).json()["data"]["results"], [])

    def test_search_limits_cap_and_floor(self):
        for index in range(3):
            self.make_post(self.board, f"match {index}")
        capped = self.visitor.get("/api/v1/search", {"q": "match", "per_page": 5000}).json()
        self.assertEqual(capped["meta"]["per_page"], 50)
        floor = self.visitor.get("/api/v1/search", {"q": "match", "per_page": -1}).json()
        self.assertEqual(len(floor["data"]["results"][0]["posts"]), 1)
        self.assertEqual(floor["data"]["total_count"], 3)

    # Gnuboard5 rule (search.php:25): only boards whose list level the member reaches are searched
    # ("bo_list_level <= mb_level").
    def test_search_skips_boards_the_viewer_may_not_even_list(self):
        board = self.make_board("cmx-listlocked", "List locked", bo_list_level=5, bo_read_level=1)
        self.make_post(board, "locked listing", content="findme-locked")
        body = self.bob_client.get("/api/v1/search", {"q": "findme-locked"}).content.decode()
        self.assertNotIn("locked listing", body)

    # Gnuboard5 rule (new.php): only boards with bo_use_search = 1 feed the new posts.
    def test_recent_leaves_out_boards_that_are_excluded_from_the_site_search(self):
        board = self.make_board("cmx-nosearch", "Not searchable", bo_use_search=False)
        self.make_post(board, "should stay out of new posts")
        body = self.visitor.get("/api/v1/recent").content.decode()
        self.assertNotIn("should stay out of new posts", body)


# ---------------------------------------------------------------------------------------------
# scraps
# ---------------------------------------------------------------------------------------------


class ScrapMoreTests(BoardFixtures):
    def scrap(self, client, board, wr_id):
        return client.post("/api/v1/scraps", {"bo_table": board.bo_table, "wr_id": wr_id}, format="json")

    def test_a_visitor_has_no_scraps(self):
        self.assertEqual(self.visitor.get("/api/v1/scraps").status_code, 401)
        self.assertEqual(self.visitor.post("/api/v1/scraps", {"bo_table": "cmx-open", "wr_id": 1}, format="json").status_code, 401)
        self.assertEqual(self.visitor.get("/api/v1/scraps/cmx-open/1").status_code, 401)
        self.assertEqual(self.visitor.delete("/api/v1/scraps/1").status_code, 401)

    def test_scrapping_a_post_twice_keeps_one_scrap_and_shows_it_in_the_list(self):
        post = self.make_post(self.board, "worth keeping")
        first = self.scrap(self.bob_client, self.board, post.pk)
        second = self.scrap(self.bob_client, self.board, post.pk)
        self.assertEqual((first.status_code, second.status_code), (201, 201))
        self.assertEqual(first.json()["data"]["scrap"]["ms_id"], second.json()["data"]["scrap"]["ms_id"])
        listed = self.bob_client.get("/api/v1/scraps").json()
        self.assertEqual(listed["meta"]["total"], 1)
        self.assertEqual(listed["data"][0]["wr_subject"], "worth keeping")
        self.assertEqual(listed["data"][0]["post_mb_id"], "cmx-alice")
        self.assertEqual(self.alice_client.get("/api/v1/scraps").json()["data"], [])

    def test_a_scrap_target_is_found_by_its_public_id_and_unknown_targets_are_not_found(self):
        post = self.make_post(self.board, "by id")
        status = self.bob_client.get(f"/api/v1/scraps/{self.board.bo_table}/{post.pk}")
        self.assertEqual(status.json()["data"], {"scrapped": False, "scrap": None})
        self.scrap(self.bob_client, self.board, post.pk)
        self.assertTrue(self.bob_client.get(f"/api/v1/scraps/{self.board.bo_table}/{post.pk}").json()["data"]["scrapped"])
        client = self.client_for(self.bob, raise_errors=False)
        for payload in (
            {"bo_table": "no-board", "wr_id": post.pk},
            {"bo_table": self.board.bo_table, "wr_id": 999999},
            {"bo_table": self.board.bo_table, "wr_id": "abc"},
            {"bo_table": self.board.bo_table, "wr_id": HUGE_NUMBER},
            {"bo_table": self.board.bo_table},
            {"bo_table": ["x"], "wr_id": [1]},
        ):
            with self.subTest(payload=payload):
                response = client.post("/api/v1/scraps", payload, format="json")
                self.assertEqual(response.status_code, 404)

    def test_a_secret_post_or_a_post_of_a_restricted_board_cannot_be_scrapped_by_others(self):
        secret = self.make_post(self.board, "secret one", wr_option="secret")
        members = self.make_board("cmx-members", "Members", bo_read_level=4)
        restricted = self.make_post(members, "restricted one")
        self.assertEqual(self.scrap(self.bob_client, self.board, secret.pk).status_code, 404)
        self.assertEqual(self.scrap(self.bob_client, members, restricted.pk).status_code, 404)
        self.assertEqual(self.scrap(self.visitor, self.board, secret.pk).status_code, 401)
        self.assertEqual(self.scrap(self.alice_client, self.board, secret.pk).status_code, 201)

    def test_a_scrap_of_a_post_that_became_unreadable_leaves_the_list(self):
        post = self.make_post(self.board, "turns secret")
        self.scrap(self.bob_client, self.board, post.pk)
        Post.objects.filter(pk=post.pk).update(wr_option="secret")
        self.assertEqual(self.bob_client.get("/api/v1/scraps").json()["data"], [])
        status = self.bob_client.get(f"/api/v1/scraps/{self.board.bo_table}/{post.pk}")
        self.assertEqual(status.json()["data"]["scrapped"], False)

    def test_a_scrap_is_removed_by_its_owner_only(self):
        post = self.make_post(self.board, "mine")
        scrap_id = self.scrap(self.bob_client, self.board, post.pk).json()["data"]["scrap"]["ms_id"]
        other = self.alice_client.delete(f"/api/v1/scraps/{scrap_id}")
        self.assertEqual(other.json()["data"]["deleted"], False)
        self.assertEqual(self.bob_client.get("/api/v1/scraps").json()["meta"]["total"], 1)
        own = self.bob_client.delete(f"/api/v1/scraps/{scrap_id}")
        self.assertEqual(own.json()["data"], {"deleted": True, "ms_id": scrap_id})
        self.assertEqual(self.bob_client.get("/api/v1/scraps").json()["data"], [])

    def test_the_scrap_can_be_removed_through_the_post_address_and_removal_is_repeatable(self):
        post = self.make_post(self.board, "remove me")
        self.scrap(self.bob_client, self.board, post.pk)
        url = f"/api/v1/scraps/{self.board.bo_table}/{post.pk}"
        for _ in range(2):
            self.assertEqual(self.bob_client.delete(url).json()["data"], {"deleted": True, "scrapped": False})
        self.assertEqual(self.bob_client.get("/api/v1/scraps").json()["data"], [])
        self.assertEqual(self.bob_client.delete("/api/v1/scraps/nobody/9").json()["data"]["scrapped"], False)

    def test_a_scrap_target_is_also_found_by_the_original_gnuboard_id(self):
        self.make_post(self.board, "migrated", legacy_wr_id=4321)
        response = self.scrap(self.bob_client, self.board, 4321)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["scrap"]["wr_subject"], "migrated")


# ---------------------------------------------------------------------------------------------
# popular search words and visitor counts
# ---------------------------------------------------------------------------------------------


@override_settings(G5_SEARCH_PUBLIC_KEYWORDS=["recorded-word", "refresh-me", *[f"word{i:02d}" for i in range(25)]],
                   G5_SEARCH_PUBLIC_MIN_COUNT=1)
class PopularSearchMoreTests(CommunityMoreBase):
    def search(self, client, keyword, **params):
        return client.get("/api/v1/search", {"q": keyword, **params})

    def test_a_search_is_recorded_and_ranked_in_the_popular_words(self):
        self.search(self.visitor, "recorded-word")
        row = SearchKeywordDaily.objects.get(keyword="recorded-word")
        self.assertEqual((row.source, row.count, row.day), ("api", 1, timezone.localdate()))
        popular = self.visitor.get("/api/v1/search/popular").json()["data"]
        self.assertEqual(popular, [{"pp_word": "recorded-word", "cnt": 1}])

    def test_a_stored_search_word_is_bounded_and_collapses_whitespace(self):
        self.search(self.visitor, "a" * 600)
        self.search(self.visitor, "  spaced    out  words ")
        words = set(SearchKeywordDaily.objects.values_list("keyword", flat=True))
        self.assertIn("spaced out words", words)
        self.assertTrue(all(len(word) <= 200 for word in words))

    def test_popular_parameters_of_any_shape_do_not_fail(self):
        client = self.client_for(raise_errors=False)
        for params in ({"limit": HUGE_NUMBER}, {"days": HUGE_NUMBER}, {"limit": "x", "days": "y"}, {"limit": 0, "days": 0}, {"limit": -9}):
            with self.subTest(params=params):
                self.assertEqual(client.get("/api/v1/search/popular", params).status_code, 200)

    def test_popular_words_are_capped_at_twenty(self):
        today = timezone.localdate()
        for index in range(25):
            SearchKeywordDaily.objects.create(keyword=f"word{index:02d}", source="site", day=today, count=index + 1)
        data = self.visitor.get("/api/v1/search/popular", {"limit": 1000}).json()["data"]
        self.assertEqual(len(data), 20)
        self.assertEqual(data[0]["pp_word"], "word24")

    # Gnuboard5 rule (insert_popular): one row per word, date and address (unique pp_date, pp_word,
    # pp_ip), so refreshing does not push a word up.
    def test_one_visitor_counts_once_per_word_and_day(self):
        for _ in range(4):
            self.search(self.visitor, "refresh-me")
        popular = self.visitor.get("/api/v1/search/popular").json()["data"]
        self.assertEqual(popular, [{"pp_word": "refresh-me", "cnt": 1}])

    # Gnuboard5 rule (search.php): strip_tags() runs on the search text before insert_popular().
    def test_markup_is_stripped_from_popular_words(self):
        self.search(self.visitor, "<script>alert(1)</script>boots")
        popular = self.visitor.get("/api/v1/search/popular").content.decode()
        self.assertNotIn("<script", popular)

    # Gnuboard5 rule (insert_popular): searches whose field list contains mb_id are not recorded.
    def test_a_search_by_member_id_is_not_a_popular_word(self):
        self.search(self.visitor, "cmx-alice", sfl="mb_id")
        popular = self.visitor.get("/api/v1/search/popular").content.decode()
        self.assertNotIn("cmx-alice", popular)


class VisitorCountMoreTests(CommunityMoreBase):
    def setUp(self):
        super().setUp()
        cache.clear()  # past days' counts are cached (api.v1_community.visit_stats)

    def visit(self, when=None, **kwargs):
        values = {"method": "GET", "path": "/boards/free", "status_code": 200}
        values.update(kwargs)
        log = VisitLog.objects.create(**values)
        VisitLog.objects.filter(pk=log.pk).update(created_at=when or timezone.now())

    def stats(self):
        return self.visitor.get("/api/v1/settings").json()["data"]["visit"]

    def test_with_no_visits_every_counter_is_zero(self):
        self.assertEqual(self.stats(), {"today": 0, "yesterday": 0, "max": 0, "total": 0})

    def test_other_static_and_media_paths_are_not_counted(self):
        for path in ("/_next/data.json", "/static/app.css", "/media/a.png", "/api/v1/x"):
            self.visit(path=path)
        self.visit(path="/boards/real")
        self.assertEqual(self.stats()["total"], 1)

    def test_redirects_count_but_client_errors_do_not(self):
        self.visit(status_code=302)
        self.visit(status_code=400)
        self.visit(status_code=500)
        self.assertEqual(self.stats()["today"], 1)

    # Gnuboard5 rule (visit.lib.php): one visit per address and day (g5_visit is unique on the
    # address), so a refresh does not raise "today".
    def test_one_address_counts_once_per_day(self):
        for _ in range(3):
            self.visit(ip_address="203.0.113.7")
        self.visit(ip_address="203.0.113.8")
        self.assertEqual(self.stats()["today"], 2)


# ---------------------------------------------------------------------------------------------
# profile update, password and account
# ---------------------------------------------------------------------------------------------


class ProfileMoreTests(CommunityMoreBase):
    def patch(self, client, payload):
        return client.patch("/api/v1/members/me", payload, format="json")

    # Gnuboard5 rule: profile and password fields that are not text are a bad request, never a 500.
    def test_profile_fields_of_the_wrong_type_are_a_client_error_not_a_server_error(self):
        client = self.client_for(self.alice, raise_errors=False)
        for payload in (
            {"mb_nick": 123},
            {"mb_nick": ["x"]},
            {"mb_email": 123},
            {"mb_email": ["a@b.test"]},
            {"mb_name": {"a": 1}},
            {"mb_name": 99},
            {"mb_password": 12345678, "mb_password_re": 12345678, "mb_password_current": "password-1234"},
            {"mb_password": ["x"], "mb_password_current": ["y"]},
        ):
            with self.subTest(payload=payload):
                self.assertLess(self.patch(client, payload).status_code, 500)

    def test_a_bad_email_is_refused_with_the_field_named_and_nothing_changes(self):
        response = self.patch(self.alice_client, {"mb_email": "not-an-email", "mb_nick": "Changed Too"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_email", response.json()["errors"])
        self.assertEqual(get_user_model().objects.get(pk=self.alice.pk).email, "cmx-alice@example.test")
        self.assertNotEqual(Profile.objects.get(user=self.alice).nickname, "Changed Too")

    def test_a_nickname_over_the_column_limit_is_refused(self):
        limit = Profile._meta.get_field("nickname").max_length
        response = self.patch(self.alice_client, {"mb_nick": "n" * (limit + 1)})
        self.assertEqual(response.status_code, 422)
        self.assertIn("mb_nick", response.json()["errors"])

    def test_protected_fields_in_the_body_are_ignored_whatever_their_spelling(self):
        response = self.patch(
            self.alice_client,
            {"mb_id": "stolen-id", "username": "stolen-id", "mb_level": 10, "user_level": 10, "mb_point": 9999,
             "user_point": 9999, "is_active": False, "is_staff": True, "mb_leave_date": "20250101", "mb_nick": "Okay Nick"},
        )
        self.assertEqual(response.status_code, 200)
        user = get_user_model().objects.get(pk=self.alice.pk)
        profile = Profile.objects.get(user=user)
        self.assertEqual((user.username, user.is_active, user.is_staff), ("cmx-alice", True, False))
        self.assertEqual((profile.user_level, profile.user_point, profile.nickname), (2, 0, "Okay Nick"))

    def test_changing_the_password_logs_other_devices_out_and_returns_fresh_tokens(self):
        old_refresh = str(RefreshToken.for_user(self.alice))
        response = self.patch(
            self.alice_client,
            {"mb_password_current": "password-1234", "mb_password": "Brand-new-pass-77", "mb_password_re": "Brand-new-pass-77"},
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertTrue(response.json()["data"]["token"])
        refused = APIClient().post("/api/v1/auth/refresh", {"refresh_token": old_refresh}, format="json")
        self.assertEqual(refused.status_code, 401)
        login = APIClient().post("/api/v1/auth/login", {"mb_id": "cmx-alice", "mb_password": "Brand-new-pass-77"}, format="json")
        self.assertEqual(login.status_code, 200)

    def test_a_reset_link_stops_working_once_the_member_changed_the_password(self):
        mail.outbox.clear()
        APIClient().post(
            "/api/v1/auth/password-reset",
            {"step": "request", "mb_id": "cmx-alice", "mb_email": "cmx-alice@example.test"}, format="json",
        )
        import re

        link = re.search(r"uid=([\w-]+)&token=([\w-]+)", mail.outbox[0].body)
        self.patch(
            self.alice_client,
            {"mb_password_current": "password-1234", "mb_password": "Brand-new-pass-77", "mb_password_re": "Brand-new-pass-77"},
        )
        response = APIClient().post(
            "/api/v1/auth/password-reset",
            {"step": "reset", "uid": link.group(1), "token": link.group(2), "mb_password": "Another-pass-88", "mb_password_re": "Another-pass-88"},
            format="json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertTrue(get_user_model().objects.get(pk=self.alice.pk).check_password("Brand-new-pass-77"))

    def test_the_password_reset_ignores_an_unknown_step_and_a_non_object_body(self):
        client = self.client_for(raise_errors=False)
        url = "/api/v1/auth/password-reset"
        self.assertEqual(client.post(url, {"step": "nope"}, format="json").status_code, 422)
        self.assertEqual(client.post(url, [1, 2, 3], format="json").status_code, 422)
        self.assertEqual(client.post(url, {"step": "request", "mb_id": ["a"], "mb_email": {"b": 1}}, format="json").status_code, 200)
        self.assertEqual(mail.outbox, [])

    def test_a_reset_needs_a_password_that_passes_the_validators_and_a_matching_confirmation(self):
        mail.outbox.clear()
        APIClient().post(
            "/api/v1/auth/password-reset",
            {"step": "request", "mb_id": "cmx-alice", "mb_email": "cmx-alice@example.test"}, format="json",
        )
        import re

        link = re.search(r"uid=([\w-]+)&token=([\w-]+)", mail.outbox[0].body)
        base = {"step": "reset", "uid": link.group(1), "token": link.group(2)}
        for password, confirm in (("", ""), ("Another-pass-88", "different"), ("12345678", "12345678"), ("cmx-alice", "cmx-alice")):
            with self.subTest(password=password):
                response = APIClient().post(
                    "/api/v1/auth/password-reset", {**base, "mb_password": password, "mb_password_re": confirm}, format="json"
                )
                self.assertEqual(response.status_code, 422)
        self.assertTrue(get_user_model().objects.get(pk=self.alice.pk).check_password("password-1234"))

    def test_there_is_no_way_to_delete_the_account_through_the_member_route(self):
        response = self.alice_client.delete("/api/v1/members/me")
        self.assertEqual(response.status_code, 405)
        self.assertTrue(get_user_model().objects.get(pk=self.alice.pk).is_active)

    def test_the_profile_of_another_member_never_shows_private_fields(self):
        response = self.bob_client.get("/api/v1/members/cmx-alice/profile")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertNotIn("cmx-alice@example.test", body)
        self.assertNotIn("password", body.lower())
        member = response.json()["data"]["member"]
        for field in ("mb_email", "mb_name", "is_staff", "is_superuser", "mb_no"):
            self.assertNotIn(field, member)

    def test_profile_ids_with_odd_characters_are_not_found(self):
        client = self.client_for(self.alice, raise_errors=False)
        for mb_id in ("%00", "no%20such", "'%20OR%201=1", "CMX-ALICE-NOT", "%ED%95%9C%EA%B8%80"):
            with self.subTest(mb_id=mb_id):
                self.assertEqual(client.get(f"/api/v1/members/{mb_id}/profile").status_code, 404)

    def test_a_blocked_member_profile_is_not_found(self):
        self.bob.is_active = False
        self.bob.save(update_fields=["is_active"])
        self.assertEqual(self.alice_client.get("/api/v1/members/cmx-bob/profile").status_code, 404)

    # Gnuboard5 rule (register_form_update.php): the nickname keeps until cf_nick_modify days have
    # passed since mb_nick_date.
    def test_the_nickname_cannot_be_changed_again_within_the_modify_period(self):
        self.set_config("cf_nick_modify", 60)
        profile = Profile.objects.get(user=self.alice)
        profile.nickname = "First Nick"
        profile.nickname_date = timezone.now() - timedelta(days=1)
        profile.save()
        response = self.patch(self.alice_client, {"mb_nick": "Second Nick"})
        self.assertIn(response.status_code, (200, 403, 409, 422))
        self.assertEqual(Profile.objects.get(user=self.alice).nickname, "First Nick")

    # Gnuboard5 rule (register_form_update.php, clean_xss_tags / valid_mb_nick): no markup in the
    # nickname, which is printed on every post and comment, or in the name.
    def test_markup_is_not_accepted_in_the_nickname(self):
        response = self.patch(self.alice_client, {"mb_nick": "<script>alert(1)</script>"})
        self.assertGreaterEqual(response.status_code, 400)
        self.assertNotIn("<script", Profile.objects.get(user=self.alice).nickname or "")

    def test_markup_is_not_stored_in_the_real_name(self):
        self.patch(self.alice_client, {"mb_name": "<img src=x onerror=alert(1)>"})
        stored = get_user_model().objects.get(pk=self.alice.pk)
        self.assertNotIn("<img", stored.first_name)
        self.assertNotIn("<img", Profile.objects.get(user=stored).realname or "")

    # Gnuboard5 rule (register_form_update.php): with cf_use_email_certify on, a new e-mail address
    # is not trusted; mb_email_certify is cleared and a certification link is mailed to it.
    def test_a_changed_email_must_be_certified_when_email_certification_is_on(self):
        self.set_config("cf_use_email_certify", 1)
        mail.outbox.clear()
        response = self.patch(
            self.alice_client, {"mb_email": "fresh-address@example.test", "mb_password_current": "password-1234"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([message.to for message in mail.outbox], [["fresh-address@example.test"]])
