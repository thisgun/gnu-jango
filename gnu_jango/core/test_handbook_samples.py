"""The handbook (manual) theme reads books from a board group and chapters from a board's posts.

cf_docs_group names that group in /api/v1/settings; ensure_handbook_samples builds a small manual
(a group, several boards as books, their categories as parts, posts as chapters) for demos and QA.
"""

import io
import re

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from gnu_jango.bbs.models import Board, Group, Post
from gnu_jango.config import config as site_config
from gnu_jango.config import handbook_samples as samples
from gnu_jango.config.handbook_audit_content import AUDIT_LINK_MARKER, AUDIT_LINK_TITLES
from gnu_jango.config.handbook_commerce_content import COMMERCE_LINK_MARKER, COMMERCE_LINK_TITLES
from gnu_jango.config.handbook_content import GUIDES
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

    def test_there_is_enough_to_look_at(self):
        samples.ensure_samples()

        self.assertGreaterEqual(sum(len(self.chapters(book.table)) for book in samples.BOOKS), 20)

    def test_order_restore_chapter_marks_tracking_number_as_protected(self):
        body = samples.chapter_body("이전 상태 복원과 복원할 수 없는 항목")

        self.assertIn("운송장 번호", body)
        self.assertIn("od_tno", body)
        self.assertNotIn("메모·송장·희망", body)

    def test_the_audit_book_has_operator_and_developer_parts(self):
        samples.ensure_samples()

        book = Board.objects.get(bo_table="hb_audit")
        chapters = self.chapters("hb_audit")

        self.assertEqual(book.bo_subject, "운영 지원 · 감사 로그와 변경 이력")
        self.assertEqual(book.bo_category_list.split("|"), ["운영자용", "개발·운영용"])
        self.assertEqual(len(chapters), 12)
        self.assertEqual(chapters[0]["ca_name"], "운영자용")
        self.assertEqual(chapters[7]["ca_name"], "개발·운영용")

    def test_the_audit_book_points_to_related_shop_member_and_dev_guides(self):
        samples.ensure_samples()
        book = Board.objects.get(bo_table="hb_audit")
        chapter = Post.objects.get(board=book, wr_subject="관리자에서 변경 이력 찾기")
        detail = APIClient().get(f"{API}/posts/hb_audit/{chapter.pk}").json()["data"]

        self.assertIn('href="/bbs/hb_shop"', detail["wr_content"])
        self.assertIn('href="/bbs/hb_member"', detail["wr_content"])
        self.assertIn('href="/bbs/hb_dev"', detail["wr_content"])

    def test_audit_link_is_appended_without_replacing_admin_text(self):
        samples.ensure_samples()
        target = Post.objects.get(wr_subject="상품과 분류 등록하기")
        target.wr_content = "<p>admin-sentinel-401</p>"
        target.save(update_fields=("wr_content",))

        samples.ensure_samples()

        target.refresh_from_db()
        self.assertIn("admin-sentinel-401", target.wr_content)
        self.assertIn("/bbs/hb_audit", target.wr_content)
        self.assertEqual(target.wr_content.count(AUDIT_LINK_MARKER), 1)

    def test_audit_chapters_are_searchable_after_reindex(self):
        samples.ensure_samples()
        call_command("rebuild_search_index", stdout=io.StringIO())

        response = APIClient().get(
            f"{API}/search/unified",
            {"q": "감사", "type": "document", "limit": 10},
        )

        self.assertEqual(response.status_code, 200)
        results = response.json()["data"]["results"]
        self.assertTrue(results, results)
        self.assertTrue(any("감사 로그란 무엇인가" in item.get("title", "") for item in results), results)

    def test_related_existing_chapters_link_to_the_audit_book_once(self):
        samples.ensure_samples()

        for title in AUDIT_LINK_TITLES:
            with self.subTest(title=title):
                target = Post.objects.get(wr_subject=title)
                self.assertIn("/bbs/hb_audit", target.wr_content)
                self.assertEqual(target.wr_content.count(AUDIT_LINK_MARKER), 1)

        samples.ensure_samples()
        for title in AUDIT_LINK_TITLES:
            with self.subTest(title=title):
                target = Post.objects.get(wr_subject=title)
                self.assertEqual(target.wr_content.count(AUDIT_LINK_MARKER), 1)

    def test_the_commerce_book_covers_alerts_returns_tracking_and_subscriptions(self):
        samples.ensure_samples()

        book = Board.objects.get(bo_table="hb_commerce")
        titles = [post["wr_subject"] for post in self.chapters("hb_commerce")]

        self.assertEqual(book.bo_subject, "쇼핑몰 운영 · 알림·반품·배송조회·정기구독")
        self.assertEqual(book.bo_category_list.split("|"), ["먼저 읽기", "고객 알림", "주문 이후", "정기구독", "개발·운영용"])
        self.assertEqual(len(titles), 9)
        for title in titles:
            with self.subTest(title=title):
                self.assertIn(title, GUIDES)
                body = Post.objects.get(board=book, wr_subject=title).wr_content
                self.assertGreaterEqual(len(re.findall(r"<h2[ >]", body)), 2)

    def test_a_deployed_manual_gets_the_commerce_book_without_touching_edited_chapters(self):
        samples.ensure_samples()
        Post.objects.filter(board__bo_table="hb_commerce").delete()
        Board.objects.filter(bo_table="hb_commerce").delete()
        edited = Post.objects.get(wr_subject="배송과 주문 상태 관리")
        edited.wr_content = "<p>admin-sentinel-501</p>"
        edited.save(update_fields=("wr_content",))

        result = samples.ensure_samples()

        self.assertEqual(result["chapters_created"], 9)
        self.assertEqual(result["chapters_updated"], 0)
        edited.refresh_from_db()
        self.assertIn("admin-sentinel-501", edited.wr_content)
        self.assertIn('href="/bbs/hb_commerce"', edited.wr_content)

    def test_related_shop_chapters_link_to_the_commerce_book_once(self):
        samples.ensure_samples()
        samples.ensure_samples()

        for title in COMMERCE_LINK_TITLES:
            with self.subTest(title=title):
                target = Post.objects.get(wr_subject=title)
                self.assertIn('href="/bbs/hb_commerce"', target.wr_content)
                self.assertEqual(target.wr_content.count(COMMERCE_LINK_MARKER), 1)

    def test_commerce_chapters_are_searchable_after_reindex(self):
        samples.ensure_samples()
        call_command("rebuild_search_index", stdout=io.StringIO())

        response = APIClient().get(f"{API}/search/unified", {"q": "정기구독", "type": "document", "limit": 10})

        self.assertEqual(response.status_code, 200)
        results = response.json()["data"]["results"]
        self.assertTrue(any("정기구독" in item.get("title", "") for item in results), results)

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

    def test_running_it_again_keeps_board_settings_an_admin_changed(self):
        # The admin "sample data" page runs this on live sites, so it must not undo admin choices.
        samples.ensure_samples()
        board = Board.objects.get(bo_table=samples.BOOKS[0].table)
        board.bo_subject = "우리 회사 시작 안내"
        board.bo_read_level = 3
        board.save(update_fields=("bo_subject", "bo_read_level"))

        samples.ensure_samples()

        board.refresh_from_db()
        self.assertEqual((board.bo_subject, board.bo_read_level), ("우리 회사 시작 안내", 3))

    def test_running_it_again_keeps_a_docs_group_an_admin_chose(self):
        samples.ensure_samples()
        Config.objects.update_or_create(name="cf_docs_group", defaults={"value": "company-docs"})

        samples.ensure_samples()

        self.assertEqual(Config.objects.get(name="cf_docs_group").value, "company-docs")

    def test_refresh_rewrites_sample_chapters_but_not_admin_chapters(self):
        samples.ensure_samples()
        board = Board.objects.get(bo_table=samples.BOOKS[0].table)
        stale = Post.objects.filter(board=board).exclude(wr_subject="").first()
        stale.wr_content = "<p>py -3.13 -m venv .venv (예전 샘플)</p>"
        stale.save(update_fields=("wr_content",))
        own = Post.objects.create(
            board=board, wr_num=0, wr_parent=0, wr_subject="관리자가 쓴 장",
            wr_content="<p>admin-sentinel-301</p>", wr_name="관리자", wr_datetime=stale.wr_datetime,
        )

        call_command("ensure_handbook_samples", stdout=io.StringIO())
        stale.refresh_from_db()
        self.assertIn("3.13", stale.wr_content)  # a plain run never touches existing bodies

        call_command("ensure_handbook_samples", "--refresh", stdout=io.StringIO())
        stale.refresh_from_db()
        own.refresh_from_db()
        self.assertEqual(stale.wr_content, samples.chapter_body(stale.wr_subject))
        self.assertEqual(own.wr_content, "<p>admin-sentinel-301</p>")
