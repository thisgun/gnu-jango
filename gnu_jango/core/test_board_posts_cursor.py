"""Keyset (cursor) paging of GET /api/v1/boards/{bo_table}/posts for infinite scroll."""

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from gnu_jango.bbs.models import Board, Group, Post
from gnu_jango.core.contract_testing import ContractAssertions

BOARD_POSTS = "/api/v1/boards/{bo_table}/posts"
URL = "/api/v1/boards/cursor-board/posts"


class CursorPagingTests(ContractAssertions, TestCase):
    @classmethod
    def setUpTestData(cls):
        group = Group.objects.create(gr_id="cursor-group", gr_subject="Cursor", gr_admin="")
        cls.board = Board.objects.create(
            group=group,
            bo_subject="Cursor board",
            bo_table="cursor-board",
            bo_skin="basic",
            bo_mobile_skin="basic",
            bo_list_level=1,
            bo_read_level=1,
            bo_page_rows=3,
            bo_use_category=1,
            bo_category_list="a|b",
        )
        # Gnuboard numbering: newer threads get a smaller (more negative) wr_num and list first.
        for number in range(1, 8):
            root = cls.post(wr_num=-number, ca_name="a" if number % 2 else "b")
            if number == 3:
                cls.post(wr_num=-number, wr_reply="A", wr_parent=root.pk)
                cls.post(wr_num=-number, wr_reply="AA", wr_parent=root.pk)
                cls.post(wr_num=-number, wr_reply="B", wr_parent=root.pk)

    @classmethod
    def post(cls, **fields):
        now = timezone.now()
        defaults = {
            "board": cls.board,
            "wr_subject": f"Post {fields['wr_num']} {fields.get('wr_reply', '')}".strip(),
            "wr_content": "<p>body</p>",
            "wr_name": "guest",
            "wr_ip": "203.0.113.7",
            "wr_datetime": now,
            "wr_last": now,
        }
        defaults.update(fields)
        post = Post.objects.create(**defaults)
        if not post.wr_parent:
            post.wr_parent = post.pk
            post.save(update_fields=["wr_parent"])
        return post

    def setUp(self):
        cache.clear()

    def ids(self, response):
        return [row["id"] for row in response.json()["data"]]

    def walk_pages(self, **params):
        ids, page = [], 1
        while True:
            response = self.client.get(URL, {"page": page, **params})
            ids += [row["id"] for row in response.json()["data"] if not row["is_notice"]]
            if page >= response.json()["meta"]["last_page"]:
                return ids
            page += 1

    def walk_cursor(self, **params):
        first = self.client.get(URL, {"page": 1, **params})
        ids = [row["id"] for row in first.json()["data"] if not row["is_notice"]]
        cursor = first.json()["meta"]["next_cursor"]
        while cursor:
            response = self.client.get(URL, {"cursor": cursor, **params})
            self.assertMatchesContract(response, BOARD_POSTS)
            ids += self.ids(response)
            cursor = response.json()["meta"]["next_cursor"]
        return ids

    def test_cursor_paging_returns_every_post_once_in_page_order(self):
        by_page = self.walk_pages()

        self.assertEqual(self.walk_cursor(), by_page)
        self.assertEqual(len(by_page), len(set(by_page)))
        self.assertEqual(len(by_page), Post.objects.filter(board=self.board).count())

    def test_replies_stay_in_thread_order_across_cursor_boundaries(self):
        ids = self.walk_cursor()
        replies = list(
            Post.objects.filter(board=self.board, wr_num=-3).order_by("wr_reply").values_list("wr_reply", "pk")
        )
        thread = [pk for _reply, pk in replies]  # "" root, then "A", "AA", "B"

        self.assertEqual([ids.index(pk) for pk in thread], sorted(ids.index(pk) for pk in thread))
        self.assertEqual(ids.index(thread[-1]) - ids.index(thread[0]), 3)

    def test_a_category_filter_is_kept_by_the_cursor(self):
        self.assertEqual(self.walk_cursor(sca="a"), self.walk_pages(sca="a"))

    def test_a_new_post_does_not_repeat_rows_on_the_next_cursor_page(self):
        first = self.client.get(URL, {"page": 1})
        seen = [row["id"] for row in first.json()["data"]]
        self.post(wr_num=-100)  # a new thread lists first and would shift page 2 by one row

        by_cursor = self.client.get(URL, {"cursor": first.json()["meta"]["next_cursor"]})
        by_page = self.client.get(URL, {"page": 2})

        self.assertFalse(set(self.ids(by_cursor)) & set(seen))
        self.assertTrue(set(self.ids(by_page)) & set(seen))

    def test_cursor_meta_has_no_totals_and_ends_with_a_null_cursor(self):
        response = self.client.get(URL, {"cursor": "", "per_page": 100})

        meta = response.json()["meta"]
        self.assertEqual(set(meta), {"per_page", "has_more", "next_cursor"})
        self.assertFalse(meta["has_more"])
        self.assertIsNone(meta["next_cursor"])
        self.assertMatchesContract(response, BOARD_POSTS)

    def test_notices_are_left_to_the_numbered_first_page(self):
        notice = self.post(wr_num=-200, is_notice=True)

        first = self.client.get(URL, {"page": 1})
        by_cursor = self.client.get(URL, {"cursor": ""})

        self.assertIn(notice.pk, self.ids(first))
        self.assertNotIn(notice.pk, self.ids(by_cursor))

    def test_no_cursor_while_notices_still_spill_onto_later_pages(self):
        for number in range(201, 205):
            self.post(wr_num=-number, is_notice=True)

        meta = self.client.get(URL, {"page": 1}).json()["meta"]

        self.assertGreater(meta["total_notice_count"], meta["per_page"])
        self.assertIsNone(meta["next_cursor"])

    def test_searching_keeps_numbered_paging(self):
        page = self.client.get(URL, {"page": 1, "stx": "Post"})
        with_cursor = self.client.get(URL, {"cursor": "", "stx": "Post"})

        self.assertIsNone(page.json()["meta"]["next_cursor"])
        self.assertEqual(with_cursor.status_code, 400)
        self.assertEqual(with_cursor.json()["code"], "cursor_unsupported")

    def test_a_malformed_cursor_is_rejected(self):
        for cursor in ("not-base64!", "WzEsMl0", "WyJ4IiwwLCIiLDAsMV0"):  # garbage, [1,2], ["x",0,"",0,1]
            with self.subTest(cursor=cursor):
                response = self.client.get(URL, {"cursor": cursor})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], "invalid_cursor")

    def test_the_last_numbered_page_has_no_cursor(self):
        last_page = self.client.get(URL, {"page": 1}).json()["meta"]["last_page"]

        meta = self.client.get(URL, {"page": last_page}).json()["meta"]

        self.assertIsNone(meta["next_cursor"])
