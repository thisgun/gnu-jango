"""The handbook (manual) theme reads books from a board group and chapters from a board's posts.

cf_docs_group names that group in /api/v1/settings; ensure_handbook_samples builds a small manual
(a group, several boards as books, their categories as parts, posts as chapters) for demos and QA.
"""

import io
import json
import re
import time

from django.core.management import CommandError, call_command
from django.test import TestCase
from rest_framework.test import APIClient

from gnu_jango.bbs.models import Board, Group, Post
from gnu_jango.config import config as site_config
from gnu_jango.config import handbook_samples as samples
from gnu_jango.config.handbook_audit_content import AUDIT_LINK_MARKER, AUDIT_LINK_TITLES
from gnu_jango.config.handbook_commerce_content import COMMERCE_LINK_MARKER, COMMERCE_LINK_TITLES
from gnu_jango.config.handbook_content import GUIDES
from gnu_jango.config.handbook_plugin_content import PLUGIN_LINK_HTML, PLUGIN_LINK_MARKER, PLUGIN_LINK_TITLES
from gnu_jango.config.handbook_shop_data_content import SHOP_DATA_LINK_MARKER, SHOP_DATA_LINK_TITLES
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

    def test_the_plugin_book_has_operator_and_developer_parts(self):
        samples.ensure_samples()

        book = Board.objects.get(bo_table="hb_plugins")
        titles = [post["wr_subject"] for post in self.chapters("hb_plugins")]

        self.assertEqual(book.bo_subject, "확장 기능 · 플러그인과 출석체크")
        self.assertEqual(book.bo_category_list.split("|"), ["먼저 읽기", "운영자용", "개발자용"])
        self.assertEqual(len(titles), 8)
        for title in titles:
            with self.subTest(title=title):
                self.assertIn(title, GUIDES)
                body = Post.objects.get(board=book, wr_subject=title).wr_content
                self.assertGreaterEqual(len(re.findall(r"<h2[ >]", body)), 2)

    def test_plugin_chapters_match_the_example_plugin(self):
        from gnu_plugins.attendance.plugin import PLUGIN

        body = samples.chapter_body("출석체크 플러그인 운영하기")

        for setting in PLUGIN.settings:
            with self.subTest(setting=setting.name):
                self.assertIn(setting.name, body)
                self.assertIn(setting.label, body)
        self.assertIn("2~30자", samples.chapter_body("플러그인 만들기"))

    def test_the_order_notify_chapter_matches_the_plugin(self):
        from gnu_plugins.order_notify.channels import CHANNEL_ENV
        from gnu_plugins.order_notify.plugin import PLUGIN

        body = samples.chapter_body("주문 알림 플러그인 운영하기")

        for setting in PLUGIN.settings:
            with self.subTest(setting=setting.name):
                self.assertIn(setting.name, body)
                self.assertIn(setting.label, body)
        for name in (name for names in CHANNEL_ENV.values() for name in names):
            with self.subTest(env=name):
                self.assertIn(name, body)
        for job in PLUGIN.jobs:
            self.assertIn(job.command, body)

    def test_the_level_up_chapter_matches_the_plugin(self):
        from gnu_plugins.level_up.models import LevelRule
        from gnu_plugins.level_up.plugin import PLUGIN

        body = samples.chapter_body("자동 등업 플러그인 운영하기")

        for setting in PLUGIN.settings:
            with self.subTest(setting=setting.name):
                self.assertIn(setting.name, body)
                self.assertIn(setting.label, body)
        for name in ("min_points", "min_posts", "min_comments", "min_days", "min_attendance", "level"):
            with self.subTest(field=name):
                self.assertIn(str(LevelRule._meta.get_field(name).verbose_name), body)
        self.assertIn(PLUGIN.jobs[0].command, body)
        hook_chapter = samples.chapter_body("hook으로 코어 동작에 끼어들기")
        for hook in ("member.joined", "bbs.post.created", "bbs.comment.created", "level_up.promoted"):
            self.assertIn(hook, hook_chapter)

    def test_a_deployed_manual_gets_the_plugin_book_without_touching_edited_chapters(self):
        samples.ensure_samples()
        Post.objects.filter(board__bo_table="hb_plugins").delete()
        Board.objects.filter(bo_table="hb_plugins").delete()
        edited = Post.objects.get(wr_subject="환경 변수")
        edited.wr_content = "<p>admin-sentinel-602</p>"
        edited.save(update_fields=("wr_content",))

        result = samples.ensure_samples()

        self.assertEqual(result["chapters_created"], 8)
        self.assertEqual(result["chapters_updated"], 0)
        edited.refresh_from_db()
        self.assertIn("admin-sentinel-602", edited.wr_content)
        self.assertIn('href="/bbs/hb_plugins"', edited.wr_content)

    def test_related_dev_chapters_link_to_the_plugin_book_once(self):
        samples.ensure_samples()
        samples.ensure_samples()

        for title in PLUGIN_LINK_TITLES:
            with self.subTest(title=title):
                target = Post.objects.get(wr_subject=title)
                self.assertIn('href="/bbs/hb_plugins"', target.wr_content)
                self.assertEqual(target.wr_content.count(PLUGIN_LINK_MARKER), 1)

    def test_plugin_chapters_are_searchable_after_reindex(self):
        samples.ensure_samples()
        call_command("rebuild_search_index", stdout=io.StringIO())

        response = APIClient().get(f"{API}/search/unified", {"q": "출석체크", "type": "document", "limit": 10})

        self.assertEqual(response.status_code, 200)
        results = response.json()["data"]["results"]
        self.assertTrue(any("출석체크" in item.get("title", "") for item in results), results)

    def test_the_shop_data_book_covers_segments_forecast_abuse_and_bought_together(self):
        samples.ensure_samples()

        book = Board.objects.get(bo_table="hb_shopdata")
        titles = [post["wr_subject"] for post in self.chapters("hb_shopdata")]

        self.assertEqual(book.bo_subject, "쇼핑몰 운영 · 고객 분석·재고 예측·이상 활동")
        self.assertEqual(book.bo_category_list.split("|"), ["먼저 읽기", "고객", "상품과 재고", "점검", "개발·운영용"])
        self.assertEqual(len(titles), 6)
        for title in titles:
            with self.subTest(title=title):
                self.assertIn(title, GUIDES)
                body = Post.objects.get(board=book, wr_subject=title).wr_content
                self.assertGreaterEqual(len(re.findall(r"<h2[ >]", body)), 2)

    def test_a_deployed_manual_gets_the_shop_data_book_without_touching_edited_chapters(self):
        samples.ensure_samples()
        Post.objects.filter(board__bo_table="hb_shopdata").delete()
        Board.objects.filter(bo_table="hb_shopdata").delete()
        edited = Post.objects.get(wr_subject="상품과 분류 등록하기")
        edited.wr_content = "<p>admin-sentinel-703</p>"
        edited.save(update_fields=("wr_content",))

        result = samples.ensure_samples()

        self.assertEqual(result["chapters_created"], 6)
        self.assertEqual(result["chapters_updated"], 0)
        edited.refresh_from_db()
        self.assertIn("admin-sentinel-703", edited.wr_content)
        self.assertIn('href="/bbs/hb_shopdata"', edited.wr_content)

    def test_related_shop_chapters_link_to_the_shop_data_book_once(self):
        samples.ensure_samples()
        samples.ensure_samples()

        for title in SHOP_DATA_LINK_TITLES:
            with self.subTest(title=title):
                target = Post.objects.get(wr_subject=title)
                self.assertIn('href="/bbs/hb_shopdata"', target.wr_content)
                self.assertEqual(target.wr_content.count(SHOP_DATA_LINK_MARKER), 1)

    def test_shop_data_chapters_are_searchable_after_reindex(self):
        samples.ensure_samples()
        call_command("rebuild_search_index", stdout=io.StringIO())

        response = APIClient().get(f"{API}/search/unified", {"q": "재고 소진", "type": "document", "limit": 10})

        self.assertEqual(response.status_code, 200)
        results = response.json()["data"]["results"]
        self.assertTrue(any("재고 소진" in item.get("title", "") for item in results), results)

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
        self.assertEqual(stale.wr_content, samples.sign(samples.chapter_body(stale.wr_subject)))
        self.assertEqual(own.wr_content, "<p>admin-sentinel-301</p>")

    def test_new_chapters_are_signed_and_stay_unedited_after_the_see_also_links(self):
        samples.ensure_samples()

        for post in Post.objects.filter(board__bo_table__in=[book.table for book in samples.BOOKS]):
            with self.subTest(title=post.wr_subject):
                self.assertTrue(samples.is_unedited(post.wr_content))
        linked = Post.objects.get(wr_subject=PLUGIN_LINK_TITLES[0])
        self.assertIn(PLUGIN_LINK_MARKER, linked.wr_content)

    def test_update_unedited_rewrites_only_chapters_nobody_touched(self):
        samples.ensure_samples()
        untouched = Post.objects.get(wr_subject="플러그인 만들기")
        edited = Post.objects.get(wr_subject="출석체크 플러그인 운영하기")
        linked = Post.objects.get(wr_subject=PLUGIN_LINK_TITLES[0])
        # Deployed with older sample text; one chapter later edited by an administrator.
        Post.objects.filter(pk=untouched.pk).update(wr_content=samples.sign("<p>old sample text</p>"))
        Post.objects.filter(pk=edited.pk).update(wr_content=edited.wr_content.replace("</p>", " 운영자 메모</p>", 1))
        Post.objects.filter(pk=linked.pk).update(
            wr_content=samples.sign("<p>old linked text</p>" + samples._link_block(PLUGIN_LINK_HTML, PLUGIN_LINK_MARKER))
        )

        out = io.StringIO()
        call_command("ensure_handbook_samples", "--update-unedited", stdout=out)
        result = json.loads(out.getvalue())

        untouched.refresh_from_db()
        edited.refresh_from_db()
        linked.refresh_from_db()
        self.assertEqual(result["chapters_updated"], 2)
        self.assertEqual(result["chapters_kept"], ["출석체크 플러그인 운영하기"])
        self.assertEqual(untouched.wr_content, samples.sign(samples.chapter_body("플러그인 만들기")))
        self.assertIn("운영자 메모", edited.wr_content)
        self.assertNotIn("old linked text", linked.wr_content)
        self.assertEqual(linked.wr_content.count(PLUGIN_LINK_MARKER), 1)
        self.assertTrue(samples.is_unedited(linked.wr_content))

    def test_update_unedited_signs_unsigned_chapters_that_match_the_current_text(self):
        samples.ensure_samples()
        current = Post.objects.get(wr_subject="플러그인 만들기")
        older = Post.objects.get(wr_subject="테마 슬롯에 위젯 넣기")
        # Made before signatures existed: one still matches the sample text, one is older text.
        Post.objects.filter(pk=current.pk).update(wr_content=samples.chapter_body("플러그인 만들기"))
        Post.objects.filter(pk=older.pk).update(wr_content="<p>older unsigned text</p>")

        result = samples.ensure_samples(update_unedited=True)

        current.refresh_from_db()
        older.refresh_from_db()
        self.assertEqual(result["chapters_signed"], 1)
        self.assertIn("테마 슬롯에 위젯 넣기", result["chapters_kept"])
        self.assertTrue(samples.is_unedited(current.wr_content))
        self.assertEqual(older.wr_content, "<p>older unsigned text</p>")

    def test_refresh_chapter_rewrites_only_the_named_chapter(self):
        samples.ensure_samples()
        named = Post.objects.get(board__bo_table="hb_start", wr_subject="글 써 보기")
        other = Post.objects.get(board__bo_table="hb_start", wr_subject="첫 화면 열기")
        Post.objects.filter(pk__in=(named.pk, other.pk)).update(wr_content="<p>older sample text</p>")

        call_command("ensure_handbook_samples", "--refresh-chapter", "글 써 보기", stdout=io.StringIO())

        named.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(named.wr_content, samples.sign(samples.chapter_body("글 써 보기")))
        self.assertTrue(samples.is_unedited(named.wr_content))
        self.assertEqual(other.wr_content, "<p>older sample text</p>")

    def test_refresh_chapter_rejects_a_title_that_is_not_a_sample_chapter(self):
        with self.assertRaises(CommandError):
            call_command("ensure_handbook_samples", "--refresh-chapter", "없는 장", stdout=io.StringIO())

    def test_refresh_and_refresh_chapter_cannot_be_combined(self):
        with self.assertRaises(CommandError):
            call_command(
                "ensure_handbook_samples", "--refresh", "--refresh-chapter", "글 써 보기", stdout=io.StringIO()
            )

    def test_refresh_and_update_unedited_cannot_be_combined(self):
        with self.assertRaises(CommandError):
            call_command("ensure_handbook_samples", "--refresh", "--update-unedited", stdout=io.StringIO())


def test_a_signature_counts_only_at_the_very_end_and_as_a_full_digest():
    signed = samples.sign("<p>text</p>")

    assert samples.is_unedited(signed)
    assert samples.is_unedited(signed + "\n\n  ")
    assert samples._unsigned(signed) == "<p>text</p>"
    assert not samples.is_unedited(signed.replace("<p>text", "<p>texts"))
    assert not samples.is_unedited(signed + "\n<p>added below</p>")
    assert not samples.is_unedited("<p>text</p>\n<!-- hb-sample:abc -->")


def test_a_body_with_a_long_run_of_spaces_is_read_quickly():
    content = "<p>x</p><!-- hb-sample:" + " " * 200_000 + "x"
    started = time.perf_counter()

    assert not samples.is_unedited(content)
    assert samples._unsigned(content) == content

    assert time.perf_counter() - started < 1
