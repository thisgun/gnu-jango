"""The handbook (manual) theme reads books from a board group and chapters from a board's posts.

cf_docs_group names that group in /api/v1/settings; ensure_handbook_samples builds a small manual
(a group, four boards as books, their categories as parts, posts as chapters) for demos and QA.
"""

import io
import re

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from gnu_jango.bbs.models import Board, Group, Post
from gnu_jango.config import config as site_config
from gnu_jango.config import handbook_samples as samples
from gnu_jango.config.models import Config

API = "/api/v1"


class DocsGroupSettingTests(TestCase):
    def setUp(self):
        site_config.clear()
        self.addCleanup(site_config.clear)

    def settings(self):
        return APIClient().get(f"{API}/settings").json()["data"]

    def test_the_setting_is_empty_until_a_group_is_chosen(self):
        self.assertEqual(self.settings()["cf_docs_group"], "")

    def test_the_chosen_group_is_returned_to_the_theme(self):
        Config.objects.update_or_create(name="cf_docs_group", defaults={"value": "manual"})
        site_config.clear()

        self.assertEqual(self.settings()["cf_docs_group"], "manual")


class HandbookSamplesTests(TestCase):
    def setUp(self):
        site_config.clear()
        self.addCleanup(site_config.clear)

    def books(self):
        response = APIClient().get(f"{API}/boards", {"group": samples.GROUP_ID})
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    def chapters(self, table):
        response = APIClient().get(f"{API}/boards/{table}/posts", {"per_page": 100})
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    def test_the_manual_is_a_group_of_ordered_books_with_parts(self):
        samples.ensure_samples()

        books = self.books()

        self.assertEqual([book["bo_table"] for book in books], [book.table for book in samples.BOOKS])
        self.assertEqual([int(book["bo_order"]) for book in books], sorted(int(book["bo_order"]) for book in books))
        first = books[0]
        self.assertTrue(first["bo_use_category"])
        self.assertEqual(first["bo_category_list"].split("|"), [part for part, _ in samples.BOOKS[0].parts if part])

    def test_chapters_come_back_in_reading_order_with_their_part(self):
        samples.ensure_samples()

        for book in samples.BOOKS:
            with self.subTest(book=book.table):
                titles = [post["wr_subject"] for post in self.chapters(book.table)]
                self.assertEqual(titles, [title for _, chapters in book.parts for title in chapters])

        first = self.chapters(samples.BOOKS[0].table)[0]
        self.assertEqual(first["ca_name"], samples.BOOKS[0].parts[0][0])

    def test_a_chapter_has_headings_for_the_page_contents_list(self):
        samples.ensure_samples()
        post = self.chapters(samples.BOOKS[0].table)[0]
        detail = APIClient().get(f"{API}/posts/{samples.BOOKS[0].table}/{post['wr_id']}").json()["data"]

        self.assertGreaterEqual(len(re.findall(r"<h2[ >]", detail["wr_content"])), 2)
        self.assertIn("<h3", detail["wr_content"])

    def test_there_is_enough_to_look_at(self):
        samples.ensure_samples()

        self.assertGreaterEqual(sum(len(self.chapters(book.table)) for book in samples.BOOKS), 20)

    def test_running_it_again_adds_nothing(self):
        samples.ensure_samples()
        before = (Board.objects.count(), Post.objects.count(), Group.objects.count())

        samples.ensure_samples()

        self.assertEqual((Board.objects.count(), Post.objects.count(), Group.objects.count()), before)

    def test_it_points_the_theme_at_the_group(self):
        samples.ensure_samples()
        site_config.clear()

        self.assertEqual(APIClient().get(f"{API}/settings").json()["data"]["cf_docs_group"], samples.GROUP_ID)

    def test_it_does_not_take_over_a_board_that_already_has_the_name(self):
        other = Group.objects.create(gr_id="community", gr_subject="Community")
        Board.objects.create(group=other, bo_table=samples.BOOKS[0].table, bo_subject="Mine")

        with self.assertRaises(samples.HandbookSampleError):
            samples.ensure_samples()

        self.assertEqual(Board.objects.get(bo_table=samples.BOOKS[0].table).bo_subject, "Mine")

    def test_removing_it_leaves_other_boards_alone(self):
        other = Group.objects.create(gr_id="community", gr_subject="Community")
        keep = Board.objects.create(group=other, bo_table="free", bo_subject="Free")
        samples.ensure_samples()

        samples.remove_samples()

        self.assertFalse(Group.objects.filter(gr_id=samples.GROUP_ID).exists())
        self.assertFalse(Board.objects.filter(bo_table__in=[book.table for book in samples.BOOKS]).exists())
        self.assertFalse(Post.objects.filter(board__bo_table__in=[book.table for book in samples.BOOKS]).exists())
        self.assertTrue(Board.objects.filter(pk=keep.pk).exists())
        site_config.clear()
        self.assertEqual(APIClient().get(f"{API}/settings").json()["data"]["cf_docs_group"], "")

    def test_the_management_command_creates_and_removes(self):
        out = io.StringIO()

        call_command("ensure_handbook_samples", stdout=out)
        self.assertTrue(Group.objects.filter(gr_id=samples.GROUP_ID).exists())

        call_command("ensure_handbook_samples", "--remove", stdout=out)
        self.assertFalse(Group.objects.filter(gr_id=samples.GROUP_ID).exists())
