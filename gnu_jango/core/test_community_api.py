"""Behaviour of the community endpoints of the v1 API (gnu_jango/api/v1_community.py).

Covers memos, notifications, polls, 1:1 inquiries (qas), content pages, FAQs, the recent feed
and the site search. The tests assert response content, database changes and access control
rather than status codes alone.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.bbs.models import Board, Comment, Group, Post
from gnu_jango.config.models import Config
from gnu_jango.core.models import (
    ContentPage,
    FAQItem,
    FAQMaster,
    Notification,
    Poll,
    PollChoice,
    PollComment,
    PollVote,
    SearchKeywordDaily,
)
from gnu_jango.shop.models import ShopProduct, ShopQA
from gnu_jango.users.models import Profile, User_Memo

GENERAL_QA_PRODUCT_ID = "__general_qa__"


class CommunityApiBase(TestCase):
    def make_user(self, username, level=2, **extra):
        user = get_user_model().objects.create_user(
            username=username, email=f"{username}@example.test", password="password-1234", **extra
        )
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.user_level = level
        profile.save()
        # Reload so the cached profile on the instance carries the new level.
        return get_user_model().objects.get(pk=user.pk)

    def client_for(self, user=None):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user=user)
        return client

    def setUp(self):
        self.alice = self.make_user("cm-alice")
        self.bob = self.make_user("cm-bob")
        self.staff = self.make_user("cm-staff", level=2, is_staff=True)
        self.alice_client = self.client_for(self.alice)
        self.bob_client = self.client_for(self.bob)
        self.staff_client = self.client_for(self.staff)
        self.visitor = self.client_for()


class MemoTests(CommunityApiBase):
    def send(self, client, receiver, text="Hello there"):
        return client.post("/api/v1/memos", {"me_recv_mb_id": receiver.username, "me_memo": text}, format="json")

    def test_a_visitor_has_no_memos(self):
        self.assertEqual(self.visitor.get("/api/v1/memos").status_code, 401)
        self.assertEqual(self.send(self.visitor, self.bob).status_code, 401)

    def test_sending_a_memo_stores_a_received_copy_and_a_sent_copy(self):
        response = self.send(self.alice_client, self.bob, "  See you at noon  ")
        self.assertEqual(response.status_code, 201, response.content[:300])
        data = response.json()["data"]
        self.assertEqual(data["me_recv_mb_id"], "cm-bob")
        self.assertEqual(data["me_send_mb_id"], "cm-alice")
        self.assertEqual(data["me_memo"], "See you at noon")
        self.assertEqual(data["me_type"], "recv")
        self.assertEqual(data["me_read_datetime"], "0000-00-00 00:00:00")

        received = User_Memo.objects.get(user=self.bob)
        sent = User_Memo.objects.get(user=self.alice)
        self.assertEqual((received.me_type, received.me_send_id, received.me_memo), ("recv", self.alice.pk, "See you at noon"))
        self.assertEqual((sent.me_type, sent.me_recv_user_id, sent.me_send_id), ("send", self.bob.pk, received.pk))
        self.assertIsNone(received.me_read_datetime)
        self.assertEqual(data["send_me_id"], sent.pk)

    def test_a_memo_to_an_unknown_member_or_without_text_is_refused_and_stores_nothing(self):
        missing = self.alice_client.post("/api/v1/memos", {"me_recv_mb_id": "nobody-here", "me_memo": "Hi"}, format="json")
        self.assertEqual(missing.status_code, 404)
        blank = self.send(self.alice_client, self.bob, "   ")
        self.assertEqual(blank.status_code, 422)
        self.assertIn("me_memo", blank.json()["errors"])
        self.assertEqual(User_Memo.objects.count(), 0)

    def test_lists_are_split_by_type_and_never_show_other_members_memos(self):
        self.send(self.alice_client, self.bob, "from alice")
        self.send(self.bob_client, self.alice, "from bob")
        self.send(self.staff_client, self.bob, "staff to bob")

        received = self.bob_client.get("/api/v1/memos").json()
        self.assertEqual(sorted(m["me_memo"] for m in received["data"]), ["from alice", "staff to bob"])
        self.assertEqual(received["meta"]["total"], 2)
        sent = self.bob_client.get("/api/v1/memos", {"type": "send"}).json()
        self.assertEqual([m["me_memo"] for m in sent["data"]], ["from bob"])
        self.assertEqual(sent["data"][0]["me_recv_mb_id"], "cm-alice")
        self.assertEqual(self.staff_client.get("/api/v1/memos").json()["data"], [])

    def test_memo_list_is_paginated(self):
        for index in range(3):
            self.send(self.alice_client, self.bob, f"memo {index}")
        response = self.bob_client.get("/api/v1/memos", {"per_page": 2, "page": 2}).json()
        self.assertEqual(len(response["data"]), 1)
        self.assertEqual(response["meta"]["total"], 3)
        self.assertEqual(response["meta"]["last_page"], 2)

    def test_reading_a_received_memo_marks_it_read_once(self):
        self.send(self.alice_client, self.bob, "read me")
        memo = User_Memo.objects.get(user=self.bob)
        first = self.bob_client.get(f"/api/v1/memos/{memo.pk}")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["data"]["me_memo"], "read me")
        memo.refresh_from_db()
        self.assertIsNotNone(memo.me_read_datetime)
        stamped = memo.me_read_datetime
        self.bob_client.get(f"/api/v1/memos/{memo.pk}")
        memo.refresh_from_db()
        self.assertEqual(memo.me_read_datetime, stamped)

    def test_reading_a_sent_memo_does_not_mark_it_read(self):
        self.send(self.alice_client, self.bob, "outgoing")
        sent = User_Memo.objects.get(user=self.alice)
        response = self.alice_client.get(f"/api/v1/memos/{sent.pk}")
        self.assertEqual(response.json()["data"]["me_type"], "send")
        sent.refresh_from_db()
        self.assertIsNone(sent.me_read_datetime)

    def test_a_member_cannot_read_or_delete_another_members_memo(self):
        self.send(self.alice_client, self.bob, "private")
        memo = User_Memo.objects.get(user=self.bob)
        sent = User_Memo.objects.get(user=self.alice)
        for client in (self.staff_client, self.visitor):
            self.assertIn(client.get(f"/api/v1/memos/{memo.pk}").status_code, (401, 404))
        read = self.staff_client.get(f"/api/v1/memos/{memo.pk}")
        self.assertEqual(read.status_code, 404)
        self.assertNotIn("private", read.content.decode())
        # The sender cannot reach the receiver's copy, and the receiver cannot reach the sender's copy.
        self.assertEqual(self.alice_client.get(f"/api/v1/memos/{memo.pk}").status_code, 404)
        self.assertEqual(self.bob_client.get(f"/api/v1/memos/{sent.pk}").status_code, 404)
        self.assertEqual(self.staff_client.delete(f"/api/v1/memos/{memo.pk}").status_code, 404)
        self.assertEqual(self.bob_client.delete(f"/api/v1/memos/{sent.pk}").status_code, 404)
        memo.refresh_from_db()
        self.assertIsNone(memo.me_read_datetime)
        self.assertEqual(User_Memo.objects.count(), 2)

    def test_deleting_a_memo_removes_only_the_members_own_copy(self):
        self.send(self.alice_client, self.bob, "bye")
        memo = User_Memo.objects.get(user=self.bob)
        response = self.bob_client.delete(f"/api/v1/memos/{memo.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], {"deleted": True, "me_id": memo.pk})
        self.assertFalse(User_Memo.objects.filter(pk=memo.pk).exists())
        self.assertTrue(User_Memo.objects.filter(user=self.alice, me_type="send").exists())
        self.assertEqual(self.bob_client.get(f"/api/v1/memos/{memo.pk}").status_code, 404)


class NotificationTests(CommunityApiBase):
    def make(self, user, **extra):
        return Notification.objects.create(user=user, nt_title="Title", **extra)

    def test_a_visitor_has_no_notifications(self):
        self.assertEqual(self.visitor.get("/api/v1/notifications").status_code, 401)
        self.assertEqual(self.visitor.post("/api/v1/notifications/read-all").status_code, 401)
        self.assertEqual(self.visitor.delete("/api/v1/notifications").status_code, 401)

    def test_a_member_can_create_and_list_a_notification(self):
        created = self.alice_client.post(
            "/api/v1/notifications",
            {"nt_type": "order", "title": "Shipped", "body": "On its way", "nt_data": {"order": 7}},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content[:300])
        row = Notification.objects.get(user=self.alice)
        self.assertEqual((row.nt_type, row.nt_title, row.nt_body, row.nt_data), ("order", "Shipped", "On its way", {"order": 7}))
        self.assertIsNone(row.nt_read_at)

        listed = self.alice_client.get("/api/v1/notifications").json()
        self.assertEqual(len(listed["data"]), 1)
        self.assertEqual(listed["data"][0]["nt_title"], "Shipped")
        self.assertFalse(listed["data"][0]["is_read"])

    def test_nt_data_that_is_not_an_object_is_stored_as_empty(self):
        self.alice_client.post("/api/v1/notifications", {"title": "x", "nt_data": "not-a-dict"}, format="json")
        self.assertEqual(Notification.objects.get(user=self.alice).nt_data, {})

    def test_members_only_see_their_own_notifications(self):
        self.make(self.alice, nt_body="for alice")
        self.make(self.bob, nt_body="for bob")
        bodies = [row["nt_body"] for row in self.alice_client.get("/api/v1/notifications").json()["data"]]
        self.assertEqual(bodies, ["for alice"])

    def test_unread_only_filter_and_read_all_only_touch_the_callers_notifications(self):
        self.make(self.alice, nt_body="unread")
        self.make(self.alice, nt_body="old", nt_read_at=timezone.now() - timedelta(days=1))
        self.make(self.bob, nt_body="bob unread")

        unread = self.alice_client.get("/api/v1/notifications", {"unread_only": "1"}).json()["data"]
        self.assertEqual([row["nt_body"] for row in unread], ["unread"])

        response = self.alice_client.post("/api/v1/notifications/read-all")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["read_at"])
        self.assertFalse(Notification.objects.filter(user=self.alice, nt_read_at__isnull=True).exists())
        self.assertTrue(Notification.objects.get(user=self.bob).nt_read_at is None)
        self.assertEqual(self.alice_client.get("/api/v1/notifications", {"unread_only": "true"}).json()["data"], [])

    def test_read_all_keeps_the_original_read_time_of_read_notifications(self):
        read_at = timezone.now() - timedelta(days=3)
        row = self.make(self.alice, nt_read_at=read_at)
        self.alice_client.post("/api/v1/notifications/read-all")
        row.refresh_from_db()
        self.assertEqual(row.nt_read_at, read_at)

    def test_delete_clears_only_the_callers_notifications(self):
        self.make(self.alice)
        self.make(self.alice)
        self.make(self.bob)
        response = self.alice_client.delete("/api/v1/notifications")
        self.assertEqual(response.json()["data"], {"deleted": 2})
        self.assertFalse(Notification.objects.filter(user=self.alice).exists())
        self.assertEqual(Notification.objects.filter(user=self.bob).count(), 1)

    def test_notification_list_is_paginated(self):
        for _ in range(3):
            self.make(self.alice)
        response = self.alice_client.get("/api/v1/notifications", {"per_page": 2}).json()
        self.assertEqual(len(response["data"]), 2)
        self.assertEqual(response["meta"]["total"], 3)


class PollTests(CommunityApiBase):
    def make_poll(self, **extra):
        extra.setdefault("po_etc", "Anything else?")  # other opinions enabled, as comments need
        poll = Poll.objects.create(po_subject=extra.pop("po_subject", "Favourite colour"), **extra)
        PollChoice.objects.create(poll=poll, num=1, content="Red")
        PollChoice.objects.create(poll=poll, num=2, content="Blue")
        return poll

    def vote(self, client, poll, option=1):
        return client.post(f"/api/v1/polls/{poll.pk}/vote", {"option": option}, format="json")

    def count(self, poll, num):
        return PollChoice.objects.get(poll=poll, num=num).count

    def test_current_poll_is_the_newest_active_one(self):
        today = timezone.localdate()
        self.make_poll(po_subject="old", po_date=today - timedelta(days=5))
        self.make_poll(po_subject="disabled", po_use=0)
        self.make_poll(po_subject="expired", po_end_date=today - timedelta(days=1))
        self.make_poll(po_subject="future", po_begin_date=today + timedelta(days=1))
        newest = self.make_poll(po_subject="newest", po_date=today)
        data = self.visitor.get("/api/v1/polls/current").json()["data"]
        self.assertEqual(data["po_id"], newest.pk)
        self.assertEqual([option["content"] for option in data["options"]], ["Red", "Blue"])
        self.assertTrue(data["is_active"])
        self.assertTrue(data["can_vote"])

    def test_there_is_no_current_poll_when_none_is_active(self):
        self.make_poll(po_use=0)
        self.assertEqual(self.visitor.get("/api/v1/polls/current").status_code, 404)

    def test_poll_detail_reports_unknown_polls_and_inactive_polls(self):
        self.assertEqual(self.visitor.get("/api/v1/polls/9999").status_code, 404)
        closed = self.make_poll(po_use=0)
        data = self.visitor.get(f"/api/v1/polls/{closed.pk}").json()["data"]
        self.assertFalse(data["is_active"])
        self.assertFalse(data["can_vote"])
        self.assertTrue(data["can_view_result"])

    def test_poll_detail_lists_other_polls_and_marks_the_viewed_one(self):
        first = self.make_poll(po_subject="first")
        second = self.make_poll(po_subject="second")
        data = self.visitor.get(f"/api/v1/polls/{first.pk}").json()["data"]
        self.assertEqual([item["po_id"] for item in data["other_polls"]], [second.pk])

    def test_a_member_vote_is_counted_and_recorded(self):
        poll = self.make_poll()
        response = self.vote(self.alice_client, poll, 2)
        self.assertEqual(response.status_code, 200, response.content[:300])
        data = response.json()["data"]
        self.assertTrue(data["has_voted"])
        self.assertFalse(data["can_vote"])
        self.assertEqual(data["total_count"], 1)
        blue = next(option for option in data["options"] if option["num"] == 2)
        self.assertEqual((blue["count"], blue["rate"]), (1, 100))
        self.assertEqual(self.count(poll, 1), 0)
        self.assertEqual(self.count(poll, 2), 1)
        vote = PollVote.objects.get(poll=poll)
        self.assertEqual((vote.user_id, vote.choice.num), (self.alice.pk, 2))

    def test_a_second_vote_by_the_same_member_is_refused_and_not_counted(self):
        poll = self.make_poll()
        self.vote(self.alice_client, poll, 1)
        again = self.vote(self.alice_client, poll, 2)
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["errors"], {"poll_already_voted": "You have already voted."})
        self.assertEqual(PollVote.objects.filter(poll=poll).count(), 1)
        self.assertEqual((self.count(poll, 1), self.count(poll, 2)), (1, 0))

    def test_different_members_can_each_vote_and_percentages_add_up(self):
        poll = self.make_poll()
        self.vote(self.alice_client, poll, 1)
        self.vote(self.bob_client, poll, 1)
        data = self.vote(self.staff_client, poll, 2).json()["data"]
        self.assertEqual(data["total_count"], 3)
        rates = {option["num"]: option["rate"] for option in data["options"]}
        self.assertEqual(rates, {1: 66.7, 2: 33.3})

    def test_the_vote_state_belongs_to_the_voter(self):
        poll = self.make_poll()
        self.vote(self.alice_client, poll, 1)
        self.assertTrue(self.alice_client.get(f"/api/v1/polls/{poll.pk}").json()["data"]["has_voted"])
        bob_view = self.bob_client.get(f"/api/v1/polls/{poll.pk}").json()["data"]
        self.assertFalse(bob_view["has_voted"])
        self.assertTrue(bob_view["can_vote"])

    def test_a_visitor_cannot_vote_on_a_members_only_poll(self):
        poll = self.make_poll(po_level=2)
        response = self.vote(self.visitor, poll)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["errors"], {"poll_forbidden": "You do not have permission to vote."})
        self.assertFalse(PollVote.objects.exists())
        self.assertEqual(self.count(poll, 1), 0)
        view = self.visitor.get(f"/api/v1/polls/{poll.pk}").json()["data"]
        self.assertFalse(view["can_vote"])
        self.assertFalse(view["can_view_result"])

    def test_a_member_below_the_poll_level_cannot_vote(self):
        poll = self.make_poll(po_level=5)
        self.assertEqual(self.vote(self.alice_client, poll).status_code, 403)
        self.assertFalse(PollVote.objects.exists())
        high = self.make_user("cm-high", level=5)
        self.assertEqual(self.vote(self.client_for(high), poll).status_code, 200)
        self.assertEqual(PollVote.objects.filter(poll=poll, user=high).count(), 1)

    def test_a_visitor_can_vote_once_on_an_open_poll(self):
        poll = self.make_poll()
        client = self.client_for()
        first = self.vote(client, poll, 1)
        self.assertEqual(first.status_code, 200, first.content[:300])
        self.assertIsNone(PollVote.objects.get(poll=poll).user)
        second = self.vote(client, poll, 2)
        self.assertEqual(second.status_code, 409)
        self.assertEqual((self.count(poll, 1), self.count(poll, 2)), (1, 0))
        self.assertTrue(client.get(f"/api/v1/polls/{poll.pk}").json()["data"]["has_voted"])

    def test_voting_needs_a_valid_option_on_an_active_poll(self):
        poll = self.make_poll()
        missing = self.alice_client.post(f"/api/v1/polls/{poll.pk}/vote", {}, format="json")
        self.assertEqual(missing.status_code, 422)
        self.assertIn("option", missing.json()["errors"])
        unknown = self.vote(self.alice_client, poll, 9)
        self.assertEqual(unknown.status_code, 422)
        self.assertEqual(self.vote(self.alice_client, Poll(po_id=9999)).status_code, 404)
        self.assertFalse(PollVote.objects.exists())

        closed = self.make_poll(po_use=0)
        expired = self.make_poll(po_end_date=timezone.localdate() - timedelta(days=1))
        for inactive in (closed, expired):
            self.assertEqual(self.vote(self.alice_client, inactive).status_code, 403)
        self.assertFalse(PollVote.objects.exists())

    def test_a_vote_for_a_choice_of_another_poll_does_not_count(self):
        poll = self.make_poll()
        other = Poll.objects.create(po_subject="other")
        PollChoice.objects.create(poll=other, num=1, content="Only")
        self.vote(self.alice_client, poll, 2)
        self.assertEqual(PollChoice.objects.get(poll=other, num=1).count, 0)

    def test_poll_comments_are_posted_under_the_member_name_and_listed(self):
        poll = self.make_poll()
        response = self.alice_client.post(f"/api/v1/polls/{poll.pk}/comments", {"pc_idea": "  Love red  "}, format="json")
        self.assertEqual(response.status_code, 201, response.content[:300])
        comment = PollComment.objects.get(poll=poll)
        self.assertEqual((comment.user_id, comment.pc_idea), (self.alice.pk, "Love red"))
        self.assertTrue(comment.pc_name)
        shown = response.json()["data"]["etc_comments"]
        self.assertEqual([item["pc_idea"] for item in shown], ["Love red"])
        self.assertEqual(shown[0]["mb_id"], "cm-alice")
        self.assertTrue(shown[0]["can_delete"])
        bob_view = self.bob_client.get(f"/api/v1/polls/{poll.pk}").json()["data"]["etc_comments"]
        self.assertFalse(bob_view[0]["can_delete"])

    def test_a_visitor_comment_needs_a_name_and_a_member_comment_ignores_a_posted_name(self):
        poll = self.make_poll()
        nameless = self.visitor.post(f"/api/v1/polls/{poll.pk}/comments", {"pc_idea": "hi"}, format="json")
        self.assertEqual(nameless.status_code, 422)
        self.assertIn("pc_name", nameless.json()["errors"])
        named = self.visitor.post(f"/api/v1/polls/{poll.pk}/comments", {"pc_idea": "hi", "pc_name": "Guest"}, format="json")
        self.assertEqual(named.status_code, 201)
        comment = PollComment.objects.get(poll=poll)
        self.assertEqual((comment.pc_name, comment.user_id), ("Guest", None))

        spoofed = self.alice_client.post(
            f"/api/v1/polls/{poll.pk}/comments", {"pc_idea": "hello", "pc_name": "Administrator"}, format="json"
        )
        self.assertEqual(spoofed.status_code, 201)
        self.assertNotEqual(PollComment.objects.get(user=self.alice).pc_name, "Administrator")

    def test_poll_comment_validation_and_limits(self):
        poll = self.make_poll()
        empty = self.alice_client.post(f"/api/v1/polls/{poll.pk}/comments", {"pc_idea": "   "}, format="json")
        self.assertEqual(empty.status_code, 422)
        self.alice_client.post(f"/api/v1/polls/{poll.pk}/comments", {"pc_idea": "x" * 400}, format="json")
        self.assertEqual(len(PollComment.objects.get().pc_idea), 255)
        self.assertEqual(self.alice_client.post("/api/v1/polls/9999/comments", {"pc_idea": "a"}, format="json").status_code, 404)
        closed = self.make_poll(po_use=0)
        refused = self.alice_client.post(f"/api/v1/polls/{closed.pk}/comments", {"pc_idea": "late"}, format="json")
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(PollComment.objects.count(), 1)

    def test_only_the_author_or_a_superuser_can_delete_a_poll_comment(self):
        poll = self.make_poll()
        comment = PollComment.objects.create(poll=poll, user=self.alice, pc_name="alice", pc_idea="mine")
        url = f"/api/v1/polls/{poll.pk}/comments/{comment.pk}"
        for client in (self.visitor, self.bob_client, self.staff_client):
            self.assertEqual(client.delete(url).status_code, 403)
        self.assertTrue(PollComment.objects.filter(pk=comment.pk).exists())
        self.assertEqual(self.alice_client.delete(url).status_code, 200)
        self.assertFalse(PollComment.objects.filter(pk=comment.pk).exists())

        second = PollComment.objects.create(poll=poll, user=self.alice, pc_name="alice", pc_idea="again")
        admin = self.client_for(get_user_model().objects.create_superuser("cm-root", "cm-root@example.test", "password-1234"))
        response = admin.delete(f"/api/v1/polls/{poll.pk}/comments/{second.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["etc_comments"], [])

    def test_a_poll_comment_cannot_be_deleted_through_another_polls_address(self):
        poll = self.make_poll()
        other = self.make_poll(po_subject="other")
        comment = PollComment.objects.create(poll=poll, user=self.alice, pc_name="alice", pc_idea="mine")
        response = self.alice_client.delete(f"/api/v1/polls/{other.pk}/comments/{comment.pk}")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(PollComment.objects.filter(pk=comment.pk).exists())


class QaTests(CommunityApiBase):
    def create(self, client, subject="Where is my order", content="It has not arrived", **extra):
        return client.post("/api/v1/qas", {"qa_subject": subject, "qa_content": content, **extra}, format="json")

    def make_item(self, client=None, **extra):
        response = self.create(client or self.alice_client, **extra)
        self.assertEqual(response.status_code, 201, response.content[:300])
        return ShopQA.objects.get(pk=response.json()["data"]["qa_id"])

    def test_config_is_public(self):
        data = self.visitor.get("/api/v1/qas/config").json()["data"]
        self.assertEqual(data["qa_title"], "1:1 Q&A")
        self.assertEqual(data["categories"], ["general"])

    def test_a_visitor_cannot_list_or_ask(self):
        self.assertEqual(self.visitor.get("/api/v1/qas").status_code, 401)
        self.assertEqual(self.create(self.visitor).status_code, 401)
        self.assertFalse(ShopQA.objects.exists())

    def test_creating_an_inquiry_stores_it_for_the_member(self):
        response = self.create(self.alice_client, "  Subject  ", "  Body text  ", qa_hp="010-1234-5678")
        self.assertEqual(response.status_code, 201, response.content[:300])
        data = response.json()["data"]
        self.assertEqual((data["qa_subject"], data["qa_content"], data["qa_status"]), ("Subject", "Body text", 0))
        self.assertEqual(data["mb_id"], "cm-alice")
        self.assertEqual(data["qa_email"], "cm-alice@example.test")
        self.assertTrue(data["can_edit"])
        self.assertTrue(data["can_delete"])
        self.assertIsNone(data["answer"])
        item = ShopQA.objects.get(pk=data["qa_id"])
        self.assertEqual((item.user_id, item.product_id, item.iq_hp), (self.alice.pk, GENERAL_QA_PRODUCT_ID, "010-1234-5678"))

    def test_an_inquiry_needs_a_subject_and_a_content(self):
        response = self.create(self.alice_client, "  ", "")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["errors"], {"qa_subject": "Subject is required.", "qa_content": "Content is required."})
        self.assertEqual(self.create(self.alice_client, "Only subject", "").status_code, 422)
        self.assertFalse(ShopQA.objects.exists())

    def test_members_only_list_their_own_inquiries(self):
        self.make_item(self.alice_client, subject="alice question")
        self.make_item(self.bob_client, subject="bob question")
        product = ShopProduct.objects.create(it_id="cm-product", it_name="Widget")
        ShopQA.objects.create(product=product, user=self.alice, mb_id="cm-alice", iq_subject="product question", iq_question="about a product")

        listed = self.alice_client.get("/api/v1/qas").json()
        self.assertEqual([row["qa_subject"] for row in listed["data"]], ["alice question"])
        self.assertEqual(listed["meta"]["total"], 1)

    def test_the_admin_scope_is_for_staff_only(self):
        self.make_item(self.alice_client, subject="alice question")
        self.make_item(self.bob_client, subject="bob question")
        denied = self.alice_client.get("/api/v1/qas", {"scope": "admin"})
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn("bob question", denied.content.decode())
        subjects = {row["qa_subject"] for row in self.staff_client.get("/api/v1/qas", {"scope": "admin"}).json()["data"]}
        self.assertEqual(subjects, {"alice question", "bob question"})

    def test_the_list_can_be_filtered_by_answer_status_and_keyword(self):
        answered = self.make_item(subject="shipping delay", content="when")
        self.make_item(subject="refund request", content="shipping fee back")
        ShopQA.objects.filter(pk=answered.pk).update(iq_answer="soon")

        waiting = self.alice_client.get("/api/v1/qas", {"status": 0}).json()["data"]
        self.assertEqual([row["qa_subject"] for row in waiting], ["refund request"])
        done = self.alice_client.get("/api/v1/qas", {"status": 1}).json()["data"]
        self.assertEqual([row["qa_subject"] for row in done], ["shipping delay"])
        by_subject = self.alice_client.get("/api/v1/qas", {"stx": "shipping"}).json()["data"]
        self.assertEqual([row["qa_subject"] for row in by_subject], ["shipping delay"])
        by_content = self.alice_client.get("/api/v1/qas", {"stx": "shipping", "sfl": "qa_content"}).json()["data"]
        self.assertEqual([row["qa_subject"] for row in by_content], ["refund request"])

    def test_a_member_cannot_read_another_members_inquiry(self):
        item = self.make_item(self.alice_client, content="my private details")
        for method in ("get", "patch", "delete"):
            response = getattr(self.bob_client, method)(f"/api/v1/qas/{item.pk}")
            self.assertEqual(response.status_code, 403, method)
            self.assertNotIn("my private details", response.content.decode())
        self.assertEqual(self.visitor.get(f"/api/v1/qas/{item.pk}").status_code, 401)
        self.assertTrue(ShopQA.objects.filter(pk=item.pk).exists())

    def test_a_product_question_is_not_reachable_through_the_inquiry_endpoint(self):
        product = ShopProduct.objects.create(it_id="cm-product", it_name="Widget")
        row = ShopQA.objects.create(product=product, user=self.alice, mb_id="cm-alice", iq_subject="about", iq_question="q")
        self.assertEqual(self.alice_client.get(f"/api/v1/qas/{row.pk}").status_code, 404)
        self.assertEqual(self.alice_client.delete(f"/api/v1/qas/{row.pk}").status_code, 404)
        self.assertTrue(ShopQA.objects.filter(pk=row.pk).exists())

    def test_the_owner_and_staff_can_read_an_inquiry(self):
        item = self.make_item(content="Read me")
        self.assertEqual(self.alice_client.get(f"/api/v1/qas/{item.pk}").json()["data"]["qa_content"], "Read me")
        self.assertEqual(self.staff_client.get(f"/api/v1/qas/{item.pk}").json()["data"]["qa_content"], "Read me")

    def test_the_owner_can_edit_an_unanswered_inquiry(self):
        item = self.make_item()
        response = self.alice_client.patch(f"/api/v1/qas/{item.pk}", {"qa_subject": "New subject", "qa_content": "New body"}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        item.refresh_from_db()
        self.assertEqual((item.iq_subject, item.iq_question), ("New subject", "New body"))
        self.assertEqual(response.json()["data"]["qa_subject"], "New subject")

    def test_a_member_cannot_edit_or_delete_an_answered_inquiry(self):
        item = self.make_item(subject="Original", content="Original body")
        ShopQA.objects.filter(pk=item.pk).update(iq_answer="Handled")
        edit = self.alice_client.patch(f"/api/v1/qas/{item.pk}", {"qa_subject": "Changed"}, format="json")
        self.assertEqual(edit.status_code, 403)
        self.assertEqual(edit.json()["errors"], {"answered_qa_locked": "Answered Q&A items cannot be edited by the member."})
        delete = self.alice_client.delete(f"/api/v1/qas/{item.pk}")
        self.assertEqual(delete.status_code, 403)
        item.refresh_from_db()
        self.assertEqual((item.iq_subject, item.iq_answer), ("Original", "Handled"))
        view = self.alice_client.get(f"/api/v1/qas/{item.pk}").json()["data"]
        self.assertFalse(view["can_edit"])
        self.assertFalse(view["can_delete"])

    def test_staff_can_still_edit_and_delete_an_answered_inquiry(self):
        item = self.make_item(subject="Original")
        ShopQA.objects.filter(pk=item.pk).update(iq_answer="Handled")
        edit = self.staff_client.patch(f"/api/v1/qas/{item.pk}", {"qa_subject": "Fixed typo"}, format="json")
        self.assertEqual(edit.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.iq_subject, "Fixed typo")
        self.assertEqual(self.staff_client.delete(f"/api/v1/qas/{item.pk}").status_code, 200)
        self.assertFalse(ShopQA.objects.filter(pk=item.pk).exists())

    def test_the_owner_can_delete_an_unanswered_inquiry_and_its_metadata_goes_too(self):
        item = self.make_item()
        Config.objects.create(name=f"qa_meta_{item.pk}", value="{}")
        response = self.alice_client.delete(f"/api/v1/qas/{item.pk}")
        self.assertEqual(response.json()["data"], {"deleted": True, "qa_id": item.pk})
        self.assertFalse(ShopQA.objects.filter(pk=item.pk).exists())
        self.assertFalse(Config.objects.filter(name=f"qa_meta_{item.pk}").exists())
        self.assertEqual(self.alice_client.get(f"/api/v1/qas/{item.pk}").status_code, 404)

    def test_only_staff_can_answer_an_inquiry(self):
        item = self.make_item()
        for client in (self.alice_client, self.bob_client):
            self.assertEqual(client.post(f"/api/v1/qas/{item.pk}/answer", {"qa_content": "I answer myself"}, format="json").status_code, 403)
        self.assertEqual(self.visitor.post(f"/api/v1/qas/{item.pk}/answer", {"qa_content": "x"}, format="json").status_code, 401)
        item.refresh_from_db()
        self.assertEqual(item.iq_answer, "")

    def test_staff_answer_is_stored_and_shown_to_the_member(self):
        item = self.make_item(subject="Where is it")
        response = self.staff_client.post(f"/api/v1/qas/{item.pk}/answer", {"qa_content": "  Shipped today  "}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        item.refresh_from_db()
        self.assertEqual(item.iq_answer, "Shipped today")

        view = self.alice_client.get(f"/api/v1/qas/{item.pk}").json()["data"]
        self.assertEqual(view["qa_status"], 1)
        self.assertEqual(view["answer"]["qa_content"], "Shipped today")
        self.assertEqual(view["answer"]["qa_subject"], "RE: Where is it")
        self.assertFalse(view["can_edit"])
        listed = self.alice_client.get("/api/v1/qas", {"status": 1}).json()["data"]
        self.assertEqual([row["qa_id"] for row in listed], [item.pk])

    def test_staff_can_choose_the_answer_subject_and_must_give_a_content(self):
        item = self.make_item()
        empty = self.staff_client.post(f"/api/v1/qas/{item.pk}/answer", {"qa_content": "  "}, format="json")
        self.assertEqual(empty.status_code, 422)
        item.refresh_from_db()
        self.assertEqual(item.iq_answer, "")
        self.staff_client.post(f"/api/v1/qas/{item.pk}/answer", {"qa_content": "Done", "qa_subject": "Resolved"}, format="json")
        self.assertEqual(self.alice_client.get(f"/api/v1/qas/{item.pk}").json()["data"]["answer"]["qa_subject"], "Resolved")
        self.assertEqual(self.staff_client.post("/api/v1/qas/9999/answer", {"qa_content": "x"}, format="json").status_code, 404)

    def test_deleting_an_answered_inquiry_removes_the_answer_metadata(self):
        item = self.make_item()
        self.staff_client.post(f"/api/v1/qas/{item.pk}/answer", {"qa_content": "Done"}, format="json")
        self.assertTrue(Config.objects.filter(name=f"qa_meta_{item.pk}").exists())
        self.staff_client.delete(f"/api/v1/qas/{item.pk}")
        self.assertFalse(Config.objects.filter(name=f"qa_meta_{item.pk}").exists())

    def test_a_follow_up_question_is_linked_to_the_original_and_only_by_its_owner(self):
        original = self.make_item(subject="First")
        follow_up = self.create(self.alice_client, "Second", "More details", qa_reply_to=original.pk)
        self.assertEqual(follow_up.status_code, 201, follow_up.content[:300])
        follow_data = follow_up.json()["data"]
        self.assertEqual(follow_data["qa_related"], original.pk)
        self.assertEqual([row["qa_id"] for row in follow_data["related_questions"]], [])
        shown = self.alice_client.get(f"/api/v1/qas/{original.pk}").json()["data"]
        self.assertEqual([row["qa_id"] for row in shown["related_questions"]], [follow_data["qa_id"]])

        stranger = self.create(self.bob_client, "Hijack", "Not mine", qa_reply_to=original.pk)
        self.assertEqual(stranger.status_code, 403)
        self.assertEqual(self.create(self.alice_client, "Ghost", "x", qa_reply_to=9999).status_code, 404)
        self.assertEqual(ShopQA.objects.filter(product_id=GENERAL_QA_PRODUCT_ID).count(), 2)

    def test_an_oversized_related_question_config_id_is_ignored(self):
        item = self.make_item()
        Config.objects.create(name=f"qa_meta_{'9' * 42}", value=f'{{"related": {item.pk}}}')

        response = self.alice_client.get(f"/api/v1/qas/{item.pk}")

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["data"]["related_questions"], [])


class ContentAndFaqTests(CommunityApiBase):
    def test_content_list_shows_only_enabled_pages_in_order(self):
        ContentPage.objects.create(co_id="terms", co_subject="Terms", co_content="<p>terms</p>", co_order=2)
        ContentPage.objects.create(co_id="about", co_subject="About", co_order=1)
        ContentPage.objects.create(co_id="hidden", co_subject="Hidden", co_use=0)
        data = self.visitor.get("/api/v1/content").json()["data"]
        self.assertEqual([page["co_id"] for page in data], ["about", "terms"])
        self.assertEqual(data[1]["co_content"], "<p>terms</p>")

    def test_content_detail_by_id(self):
        ContentPage.objects.create(co_id="privacy", co_subject="Privacy", co_content="Policy text")
        ContentPage.objects.create(co_id="hidden", co_subject="Hidden", co_content="secret page", co_use=0)
        data = self.visitor.get("/api/v1/content/privacy").json()["data"]
        self.assertEqual((data["co_subject"], data["co_content"]), ("Privacy", "Policy text"))
        self.assertEqual(self.visitor.get("/api/v1/content/missing").status_code, 404)
        hidden = self.visitor.get("/api/v1/content/hidden")
        self.assertEqual(hidden.status_code, 404)
        self.assertNotIn("secret page", hidden.content.decode())

    def test_content_by_seo_title_falls_back_to_the_id(self):
        ContentPage.objects.create(co_id="c1", co_subject="Company", co_seo_title="company-info", co_content="About us")
        ContentPage.objects.create(co_id="c2", co_subject="Off", co_seo_title="off-page", co_use=0)
        self.assertEqual(self.visitor.get("/api/v1/content/seo/company-info").json()["data"]["co_id"], "c1")
        self.assertEqual(self.visitor.get("/api/v1/content/seo/c1").json()["data"]["co_subject"], "Company")
        self.assertEqual(self.visitor.get("/api/v1/content/seo/off-page").status_code, 404)
        self.assertEqual(self.visitor.get("/api/v1/content/seo/unknown").status_code, 404)

    def make_faq(self):
        self.shipping = FAQMaster.objects.create(fm_subject="Shipping", fm_order=1)
        self.payment = FAQMaster.objects.create(fm_subject="Payment", fm_order=2)
        self.off = FAQMaster.objects.create(fm_subject="Retired", fm_order=3, fm_use=0)
        FAQItem.objects.create(master=self.shipping, fa_subject="How long?", fa_content="Two days", fa_order=2)
        FAQItem.objects.create(master=self.shipping, fa_subject="Cost?", fa_content="Free over 50", fa_order=1)
        FAQItem.objects.create(master=self.shipping, fa_subject="Disabled", fa_content="no", fa_use=0)
        FAQItem.objects.create(master=self.payment, fa_subject="Cards?", fa_content="All major cards")
        FAQItem.objects.create(master=self.off, fa_subject="Old question", fa_content="Old answer")

    def test_faq_defaults_to_the_first_category_and_hides_disabled_rows(self):
        self.make_faq()
        data = self.visitor.get("/api/v1/faqs").json()["data"]
        self.assertEqual([master["fm_subject"] for master in data["masters"]], ["Shipping", "Payment"])
        self.assertEqual(data["current"]["fm_id"], self.shipping.pk)
        self.assertEqual([item["fa_subject"] for item in data["items"]], ["Cost?", "How long?"])
        self.assertEqual(data["meta"]["total"], 2)
        self.assertEqual((data["meta"]["from"], data["meta"]["to"]), (1, 2))

    def test_faq_category_and_keyword_filters(self):
        self.make_faq()
        payment = self.visitor.get("/api/v1/faqs", {"fm_id": self.payment.pk}).json()["data"]
        self.assertEqual([item["fa_subject"] for item in payment["items"]], ["Cards?"])
        found = self.visitor.get("/api/v1/faqs", {"stx": "free"}).json()["data"]
        self.assertEqual([item["fa_subject"] for item in found["items"]], ["Cost?"])
        none = self.visitor.get("/api/v1/faqs", {"stx": "zzz"}).json()["data"]
        self.assertEqual(none["items"], [])
        self.assertEqual((none["meta"]["total"], none["meta"]["from"], none["meta"]["to"]), (0, None, None))

    def test_faq_without_any_category_is_empty(self):
        data = self.visitor.get("/api/v1/faqs").json()["data"]
        self.assertEqual((data["masters"], data["current"], data["items"]), ([], None, []))


class RecentAndSearchTests(CommunityApiBase):
    def setUp(self):
        super().setUp()
        self.group = Group.objects.create(gr_id="cm-group", gr_subject="Community")
        self.other_group = Group.objects.create(gr_id="cm-other", gr_subject="Elsewhere")
        self.board = self.make_board("cm-open", self.group, "Open board")
        self.other_board = self.make_board("cm-side", self.other_group, "Side board")
        self.members_board = self.make_board("cm-members", self.group, "Members board", bo_read_level=3)

    def make_board(self, table, group, subject, **extra):
        # Only boards in the site search feed the search and the new posts (search.php:25, new.php);
        # Gnuboard5's board form ticks bo_use_search for a new board, the model default does not.
        extra.setdefault("bo_use_search", True)
        return Board.objects.create(group=group, bo_table=table, bo_subject=subject, bo_skin="basic", bo_mobile_skin="basic", **extra)

    def make_post(self, board, subject, content="Body", user=None, **extra):
        user = user or self.alice
        stamp = extra.pop("wr_datetime", timezone.now())
        post = Post.objects.create(
            board=board, wr_num=-1, wr_subject=subject, wr_content=content, user=user,
            wr_name=user.username, wr_datetime=stamp, wr_last=stamp, **extra,
        )
        post.wr_parent = post.pk
        post.save(update_fields=["wr_parent"])
        return post

    def make_comment(self, post, text="A comment", user=None, **extra):
        user = user or self.bob
        stamp = extra.pop("wr_datetime", timezone.now())
        return Comment.objects.create(
            board=post.board, post=post, user=user, wr_content=text, wr_name=user.username,
            wr_datetime=stamp, wr_last=stamp, **extra,
        )

    # recent

    def test_recent_lists_the_newest_posts_first_with_board_and_group_details(self):
        now = timezone.now()
        old = self.make_post(self.board, "older", wr_datetime=now - timedelta(hours=2))
        new = self.make_post(self.other_board, "newer", wr_datetime=now)
        data = self.visitor.get("/api/v1/recent", {"view": "w"}).json()
        self.assertEqual([row["wr_subject"] for row in data["data"]], ["newer", "older"])
        first = data["data"][0]
        self.assertEqual((first["bo_table"], first["gr_id"], first["gr_subject"], first["is_comment"]), ("cm-side", "cm-other", "Elsewhere", False))
        self.assertEqual(first["href"], f"/bbs/cm-side/{new.pk}")
        self.assertEqual(first["mb_id"], "cm-alice")
        self.assertEqual(data["meta"]["total"], 2)
        self.assertIn(old.pk, [row["wr_id"] for row in data["data"]])

    def test_recent_can_show_comments_and_filter_by_view(self):
        post = self.make_post(self.board, "A post")
        self.make_comment(post, "Reply text")
        comments = self.visitor.get("/api/v1/recent", {"view": "c"}).json()["data"]
        self.assertEqual(len(comments), 1)
        self.assertTrue(comments[0]["is_comment"])
        self.assertEqual((comments[0]["wr_subject"], comments[0]["wr_parent"], comments[0]["mb_id"]), ("A post", post.pk, "cm-bob"))
        both = self.visitor.get("/api/v1/recent").json()["data"]
        self.assertEqual(sorted(row["is_comment"] for row in both), [False, True])

    def test_recent_filters_by_group_and_member(self):
        self.make_post(self.board, "in group", user=self.alice)
        self.make_post(self.other_board, "in other group", user=self.bob)
        by_group = self.visitor.get("/api/v1/recent", {"gr_id": "cm-other"}).json()["data"]
        self.assertEqual([row["wr_subject"] for row in by_group], ["in other group"])
        by_member = self.visitor.get("/api/v1/recent", {"mb_id": "cm-alice"}).json()["data"]
        self.assertEqual([row["wr_subject"] for row in by_member], ["in group"])

    def test_recent_is_paginated(self):
        for index in range(3):
            self.make_post(self.board, f"post {index}", wr_datetime=timezone.now() - timedelta(minutes=index))
        page = self.visitor.get("/api/v1/recent", {"limit": 2, "page": 2}).json()
        self.assertEqual([row["wr_subject"] for row in page["data"]], ["post 2"])
        self.assertEqual((page["meta"]["total"], page["meta"]["last_page"]), (3, 2))

    def test_recent_hides_secret_posts_and_posts_in_boards_the_viewer_cannot_read(self):
        self.make_post(self.board, "public post")
        self.make_post(self.board, "secret post", content="hidden words", wr_option="secret")
        self.make_post(self.members_board, "members only post", content="members words")
        for client in (self.visitor, self.bob_client):
            body = client.get("/api/v1/recent").content.decode()
            self.assertIn("public post", body)
            self.assertNotIn("secret post", body)
            self.assertNotIn("members only post", body)
        # The author still sees their own secret post; a high level member sees the restricted board.
        own = self.alice_client.get("/api/v1/recent").json()["data"]
        self.assertIn("secret post", [row["wr_subject"] for row in own])
        high = self.client_for(self.make_user("cm-high", level=3))
        self.assertIn("members only post", [row["wr_subject"] for row in high.get("/api/v1/recent").json()["data"]])

    def test_recent_comments_of_unreadable_posts_do_not_leak(self):
        secret = self.make_post(self.board, "secret thread", wr_option="secret")
        restricted = self.make_post(self.members_board, "restricted thread")
        self.make_comment(secret, "comment on secret")
        self.make_comment(restricted, "comment on restricted")
        for client in (self.visitor, self.bob_client):
            body = client.get("/api/v1/recent", {"view": "c"}).content.decode()
            self.assertNotIn("secret thread", body)
            self.assertNotIn("restricted thread", body)
            self.assertEqual(client.get("/api/v1/recent", {"view": "c"}).json()["data"], [])

    def test_recent_groups_lists_each_group_with_boards_once(self):
        Group.objects.create(gr_id="cm-empty", gr_subject="No boards")
        data = self.visitor.get("/api/v1/recent/groups").json()["data"]
        self.assertEqual(data, [{"gr_id": "cm-group", "gr_subject": "Community"}, {"gr_id": "cm-other", "gr_subject": "Elsewhere"}])

    # search

    def search(self, client, keyword, **params):
        return client.get("/api/v1/search", {"q": keyword, **params}).json()

    def test_search_finds_posts_grouped_by_board(self):
        self.make_post(self.board, "Quokka facts", content="plain")
        self.make_post(self.board, "Other title", content="mentions a quokka inside")
        self.make_post(self.other_board, "Unrelated", content="nothing")
        self.make_post(self.other_board, "QUOKKA upper", content="x")
        data = self.search(self.visitor, "quokka")["data"]
        self.assertEqual(data["keyword"], "quokka")
        self.assertEqual(data["total_count"], 3)
        by_board = {group["bo_table"]: group for group in data["results"]}
        self.assertEqual(set(by_board), {"cm-open", "cm-side"})
        self.assertEqual(by_board["cm-open"]["count"], 2)
        self.assertEqual(by_board["cm-open"]["bo_subject"], "Open board")
        self.assertEqual(sorted(post["wr_subject"] for post in by_board["cm-open"]["posts"]), ["Other title", "Quokka facts"])

    def test_search_without_a_keyword_or_match_returns_nothing(self):
        self.make_post(self.board, "Something")
        self.assertEqual(self.search(self.visitor, "   ")["data"], {"keyword": "", "total_count": 0, "results": []})
        self.assertEqual(self.search(self.visitor, "zzzz")["data"]["results"], [])

    def test_search_can_be_limited_to_a_board_and_to_fields(self):
        self.make_post(self.board, "Needle title", content="x")
        self.make_post(self.other_board, "Needle elsewhere", content="x")
        self.make_post(self.board, "Plain", content="needle in body")
        only_board = self.search(self.visitor, "needle", bo_table="cm-side")["data"]
        self.assertEqual([group["bo_table"] for group in only_board["results"]], ["cm-side"])
        subject_only = self.search(self.visitor, "needle", sfl="wr_subject", bo_table="cm-open")["data"]
        self.assertEqual([post["wr_subject"] for post in subject_only["results"][0]["posts"]], ["Needle title"])
        content_only = self.search(self.visitor, "needle", sfl="wr_content", bo_table="cm-open")["data"]
        self.assertEqual([post["wr_subject"] for post in content_only["results"][0]["posts"]], ["Plain"])
        by_member = self.search(self.visitor, "cm-alice", sfl="mb_id")["data"]
        self.assertEqual(by_member["total_count"], 3)

    def test_search_caps_the_posts_returned_per_board_but_counts_all(self):
        for index in range(4):
            self.make_post(self.board, f"match {index}", wr_datetime=timezone.now() - timedelta(minutes=index))
        group = self.search(self.visitor, "match", per_page=2)["data"]["results"][0]
        self.assertEqual(group["count"], 4)
        self.assertEqual([post["wr_subject"] for post in group["posts"]], ["match 0", "match 1"])

    def test_search_does_not_leak_secret_posts(self):
        self.make_post(self.board, "Visible zebra")
        self.make_post(self.board, "Hidden zebra", content="zebra secret body", wr_option="secret")
        for client in (self.visitor, self.bob_client):
            result = self.search(client, "zebra")
            body = str(result)
            self.assertNotIn("Hidden zebra", body)
            self.assertNotIn("zebra secret body", body)
            self.assertEqual(result["data"]["total_count"], 1)
        # A body-only match must not reveal that a secret post exists either.
        probe = self.search(self.visitor, "secret body")
        self.assertEqual(probe["data"]["total_count"], 0)
        self.assertEqual(self.search(self.alice_client, "zebra")["data"]["total_count"], 2)
        admin = self.client_for(get_user_model().objects.create_superuser("cm-root", "cm-root@example.test", "password-1234"))
        self.assertEqual(self.search(admin, "zebra")["data"]["total_count"], 2)

    def test_search_does_not_leak_posts_of_boards_above_the_viewers_read_level(self):
        self.make_post(self.members_board, "Members koala", content="members koala body", user=self.bob)
        for client in (self.visitor, self.alice_client):
            result = self.search(client, "koala")
            self.assertEqual(result["data"]["results"], [])
            self.assertNotIn("members koala body", str(result))
        high = self.client_for(self.make_user("cm-high", level=3))
        self.assertEqual(self.search(high, "koala")["data"]["total_count"], 1)

    # popular searches

    def add_keyword(self, keyword, count, days_ago=0, source="site"):
        SearchKeywordDaily.objects.create(
            keyword=keyword, count=count, source=source, day=timezone.localdate() - timedelta(days=days_ago)
        )

    @override_settings(G5_SEARCH_PUBLIC_KEYWORDS=["alpha", "beta", "gamma"], G5_SEARCH_PUBLIC_MIN_COUNT=1)
    def test_popular_searches_are_summed_over_the_window_and_ranked(self):
        self.add_keyword("alpha", 3)
        self.add_keyword("alpha", 4, days_ago=1, source="shop")
        self.add_keyword("beta", 5)
        self.add_keyword("gamma", 1)
        self.add_keyword("stale", 100, days_ago=10)
        self.add_keyword("admin-only", 100, source="admin")
        self.add_keyword("", 50)
        data = self.visitor.get("/api/v1/search/popular").json()["data"]
        self.assertEqual(data, [{"pp_word": "alpha", "cnt": 7}, {"pp_word": "beta", "cnt": 5}, {"pp_word": "gamma", "cnt": 1}])

    @override_settings(G5_SEARCH_PUBLIC_KEYWORDS=["recent", "older", "third"], G5_SEARCH_PUBLIC_MIN_COUNT=1)
    def test_popular_searches_honour_limit_and_days(self):
        self.add_keyword("recent", 1)
        self.add_keyword("older", 9, days_ago=5)
        self.add_keyword("third", 2)
        limited = self.visitor.get("/api/v1/search/popular", {"limit": 1, "days": 7}).json()["data"]
        self.assertEqual(limited, [{"pp_word": "older", "cnt": 9}])
        short = self.visitor.get("/api/v1/search/popular", {"days": 1}).json()["data"]
        self.assertEqual([row["pp_word"] for row in short], ["third", "recent"])
        self.assertEqual(self.visitor.get("/api/v1/search/popular", {"limit": "abc", "days": "-4"}).status_code, 200)


class CommunityReviewFixTests(CommunityApiBase):
    """Fixes for gaps the community tests found."""

    def make_poll(self, **extra):
        poll = Poll.objects.create(po_subject=extra.pop("po_subject", "Lunch"), **extra)
        PollChoice.objects.create(poll=poll, num=1, content="Rice", count=extra.pop("count", 0))
        PollChoice.objects.create(poll=poll, num=2, content="Noodles")
        return poll

    def test_voting_gives_the_polls_points_once(self):
        poll = self.make_poll(po_point=10)
        self.assertEqual(self.alice_client.post(f"/api/v1/polls/{poll.pk}/vote", {"option": 1}, format="json").status_code, 200)
        self.alice_client.post(f"/api/v1/polls/{poll.pk}/vote", {"option": 2}, format="json")
        self.assertEqual(Profile.objects.get(user=self.alice).user_point, 10)

    def test_results_are_hidden_from_those_who_may_not_see_them(self):
        poll = self.make_poll(po_level=5)
        PollChoice.objects.filter(poll=poll, num=1).update(count=7)
        data = self.visitor.get(f"/api/v1/polls/{poll.pk}").json()["data"]
        self.assertFalse(data["can_view_result"])
        self.assertEqual(data["total_count"], 0)
        self.assertEqual([option["count"] for option in data["options"]], [0, 0])

    def test_an_unknown_or_retired_faq_category_shows_the_first_category_only(self):
        first = FAQMaster.objects.create(fm_subject="Shipping", fm_order=1)
        retired = FAQMaster.objects.create(fm_subject="Retired", fm_order=2, fm_use=0)
        FAQItem.objects.create(master=first, fa_subject="Shown question")
        FAQItem.objects.create(master=retired, fa_subject="Hidden faq")
        for fm_id in (retired.pk, 99999):
            body = self.visitor.get("/api/v1/faqs", {"fm_id": fm_id}).content.decode()
            self.assertNotIn("Hidden faq", body)
            self.assertIn("Shown question", body)

    def test_a_memo_to_a_deactivated_member_is_refused(self):
        sleeper = self.make_user("cm-sleeper", is_active=False)
        response = self.alice_client.post("/api/v1/memos", {"me_recv_mb_id": sleeper.username, "me_memo": "hi"}, format="json")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(User_Memo.objects.filter(me_recv_user_id=sleeper.pk).exists())

    def test_a_forged_forwarded_for_header_does_not_buy_extra_votes(self):
        poll = self.make_poll()
        codes = [
            self.client_for().post(f"/api/v1/polls/{poll.pk}/vote", {"option": 1}, format="json", HTTP_X_FORWARDED_FOR=f"10.0.0.{i}").status_code
            for i in range(3)
        ]
        self.assertEqual(codes.count(200), 1)
        self.assertEqual(PollChoice.objects.get(poll=poll, num=1).count, 1)


class PollCommentRuleTests(CommunityApiBase):
    """Gnuboard5 poll_etc_update.php: other opinions must be enabled and the level high enough."""

    def test_comments_are_refused_when_other_opinions_are_off(self):
        poll = Poll.objects.create(po_subject="No opinions", po_etc="")
        response = self.alice_client.post(f"/api/v1/polls/{poll.pk}/comments", {"pc_idea": "Hi"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PollComment.objects.filter(poll=poll).exists())
        self.assertFalse(self.alice_client.get(f"/api/v1/polls/{poll.pk}").json()["data"]["can_comment"])

    def test_comments_below_the_polls_level_are_refused(self):
        poll = Poll.objects.create(po_subject="Members", po_etc="Other?", po_level=5)
        response = self.alice_client.post(f"/api/v1/polls/{poll.pk}/comments", {"pc_idea": "Hi"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PollComment.objects.filter(poll=poll).exists())
