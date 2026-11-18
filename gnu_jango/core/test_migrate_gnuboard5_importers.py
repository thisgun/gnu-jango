"""migrate_gnuboard5 run against a fake Gnuboard5/YoungCart source: the member data a migrated site
shows (social logins, 1:1 inquiries, wishlists, scraps, votes, popups, menus) keeps working, and
nothing grants more admin access than the source did."""

import tempfile
from contextlib import nullcontext
from io import StringIO
from pathlib import Path
from unittest import skipUnless
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from gnu_jango.api.v1_auth import _social_identity_owner
from gnu_jango.bbs.models import Post, Post_good, Post_scrap
from gnu_jango.config.models import Config
from gnu_jango.core.management.commands import migrate_gnuboard5
from gnu_jango.core.management.commands.migrate_gnuboard5 import Command
from gnu_jango.core.models import ContentPage, New_win, Site_menu
from gnu_jango.core.test_auth_api_more import EXCHANGE_URL, SOCIAL_SETTINGS, USERINFO, SocialFlowBase, query_of
from gnu_jango.shop.models import (
    GeneralInquiry,
    ShopCategory,
    ShopPersonalPay,
    ShopProduct,
    ShopQA,
    ShopReview,
    ShopWishlist,
)

CONFIG = {
    "table_prefix": "g5_",
    "shop_prefix": "g5_shop_",
    "tables": {
        "config_table": "g5_config",
        "member_table": "g5_member",
        "group_table": "g5_group",
        "board_table": "g5_board",
        "write_prefix": "g5_write_",
        "g5_shop_item_table": "g5_shop_item",
        "g5_shop_item_qa_table": "g5_shop_item_qa",
        "g5_shop_item_use_table": "g5_shop_item_use",
        "g5_shop_category_table": "g5_shop_category",
        "g5_shop_personalpay_table": "g5_shop_personalpay",
        "content_table": "g5_content",
        "faq_master_table": "g5_faq_master",
        "faq_table": "g5_faq",
        "social_profile_table": "g5_member_social_profiles",
        "qa_content_table": "g5_qa_content",
        "g5_shop_wish_table": "g5_shop_wish",
        "scrap_table": "g5_scrap",
        "board_good_table": "g5_board_good",
        "new_win_table": "g5_new_win",
        "menu_table": "g5_menu",
        "auth_table": "g5_auth",
    },
}
MEMBERS = {"member", "group", "board", "board_posts"}
NEW_TABLES = {"member_social", "qa_content", "shop_wish", "scrap", "board_good", "new_win", "menu", "auth"}

# the identifier HybridAuth stored for each provider is the id Django's _social_userinfo reads back
PROVIDER_IDS = {
    "naver": USERINFO["naver"]["response"]["id"],
    "kakao": str(USERINFO["kakao"]["id"]),
    "google": USERINFO["google"]["sub"],
    "facebook": USERINFO["facebook"]["id"],
    "twitter": USERINFO["twitter"]["data"]["id"],
    "payco": USERINFO["payco"]["data"]["member"]["idNo"],
}


def member(mb_id, level=2, **fields):
    return {"mb_id": mb_id, "mb_password": "", "mb_name": mb_id, "mb_nick": mb_id, "mb_email": f"{mb_id}@example.test",
            "mb_level": level, "mb_datetime": "2020-01-01 00:00:00", **fields}


def post(wr_id, mb_id="writer", **fields):
    return {"wr_id": wr_id, "wr_num": -wr_id, "wr_parent": wr_id, "wr_is_comment": 0, "wr_subject": f"글 {wr_id}",
            "wr_content": "본문", "mb_id": mb_id, "wr_datetime": "2024-01-01 00:00:00", **fields}


def qa(qa_id, qa_type=0, qa_parent=None, qa_related=None, **fields):
    return {"qa_id": qa_id, "qa_num": -qa_id, "qa_parent": qa_parent or qa_id, "qa_related": qa_related or qa_id,
            "mb_id": "asker", "qa_name": "묻는이", "qa_email": "asker@example.test", "qa_hp": "010-1234-5678",
            "qa_type": qa_type, "qa_category": "회원", "qa_html": 0, "qa_subject": f"문의 {qa_id}",
            "qa_content": f"내용 {qa_id}", "qa_status": 0, "qa_file1": "", "qa_source1": "", "qa_file2": "",
            "qa_source2": "", "qa_datetime": "2024-01-10 14:58:25", **fields}


def source():
    return {
        "g5_config": [{"cf_admin": "admin"}],
        "g5_member": [member("admin", 10), member("subadmin", 10), member("asker"), member("writer"), member("voter")],
        "g5_group": [{"gr_id": "community", "gr_subject": "커뮤니티"}],
        "g5_board": [{"bo_table": "free", "gr_id": "community", "bo_subject": "자유", "bo_use_good": 1, "bo_use_nogood": 1}],
        "g5_write_free": [post(7), post(8)],
        "g5_shop_item": [
            {"it_id": "OLD", "it_name": "OLD", "it_use": "1", "it_time": "2019-03-01 09:00:00"},
            {"it_id": "NEW", "it_name": "NEW", "it_use": "1", "it_time": "2025-06-05 16:49:12"},
        ],
        "g5_shop_item_qa": [{"iq_id": 1, "it_id": "OLD", "mb_id": "asker", "iq_subject": "상품 문의", "iq_question": "언제 와요"}],
        "g5_member_social_profiles": [
            {"mp_no": index, "mb_id": "asker", "provider": provider, "identifier": identifier,
             "mp_register_day": "2017-11-27 16:42:25", "mp_latest_day": "2017-11-27 16:42:25"}
            for index, (provider, identifier) in enumerate(PROVIDER_IDS.items(), start=1)
        ] + [
            {"mp_no": 90, "mb_id": "gone", "provider": "kakao", "identifier": "999"},
            {"mp_no": 91, "mb_id": "asker", "provider": "myspace", "identifier": "m-1"},
        ],
        "g5_qa_content": [
            qa(11, qa_status=1),
            qa(12, qa_type=1, qa_parent=11, qa_related=11, mb_id="admin", qa_subject="답변드립니다", qa_content="탈퇴는 이렇게"),
            # a follow-up question (추가 질문) points at the question it follows
            qa(13, qa_related=11),
            qa(14, qa_status=1, qa_file1="missing.txt", qa_source1="보낸파일.txt"),
        ],
        "g5_shop_wish": [{"wi_id": 5, "mb_id": "asker", "it_id": "NEW", "wi_time": "2024-02-02 10:00:00", "wi_ip": ""}],
        "g5_scrap": [{"ms_id": 20, "mb_id": "asker", "bo_table": "free", "wr_id": "7", "ms_datetime": "2024-03-03 08:00:00"}],
        "g5_board_good": [
            {"bg_id": 1, "bo_table": "free", "wr_id": 7, "mb_id": "voter", "bg_flag": "good", "bg_datetime": "2024-04-04 00:00:00"},
            {"bg_id": 2, "bo_table": "free", "wr_id": 8, "mb_id": "voter", "bg_flag": "nogood", "bg_datetime": "2024-04-04 00:00:00"},
        ],
        "g5_new_win": [{"nw_id": 2, "nw_device": "pc", "nw_division": "both", "nw_begin_time": "2022-04-28 00:00:00",
                        "nw_end_time": "2022-05-05 23:59:59", "nw_disable_hours": 24, "nw_left": 10, "nw_top": 20,
                        "nw_height": 500, "nw_width": 420, "nw_subject": "무이자 안내", "nw_content": "<p>안내</p>",
                        "nw_content_html": 1}],
        "g5_menu": [{"me_id": 346, "me_code": "50", "me_name": "사이트 안내", "me_link": "/content/company",
                     "me_target": "blank", "me_order": 4, "me_use": 1, "me_mobile_use": 0}],
        "g5_auth": [{"mb_id": "subadmin", "au_menu": "200100", "au_auth": "r,w"},
                    {"mb_id": "subadmin", "au_menu": "400400", "au_auth": "r"}],
    }


def run_import(tables, selected, source_root="missing-source"):
    out = StringIO()
    command = Command(stdout=out)
    command.source_root = Path(source_root)
    with (
        patch.object(migrate_gnuboard5, "fetch_rows", lambda cursor, table, limit=None: [dict(row) for row in tables[table]][:limit]),
        patch.object(migrate_gnuboard5, "table_exists", lambda cursor, table: table in tables),
    ):
        imported = command.import_selected(None, CONFIG, set(selected), None)
    return imported, out.getvalue()


def apply_command(tables, selected, *options):
    """manage.py migrate_gnuboard5 --apply, as the operator runs it, against the fake source."""
    out = StringIO()
    config = {**CONFIG, "host": "mysql.invalid", "database": "g5", "user": "g5", "password": ""}
    with (
        patch.object(migrate_gnuboard5, "parse_php_config", lambda path: config),
        patch.object(migrate_gnuboard5, "mysql_connection", lambda config: nullcontext(MagicMock())),
        patch.object(migrate_gnuboard5, "count_table", lambda cursor, table: len(tables[table])),
        patch.object(migrate_gnuboard5, "fetch_rows", lambda cursor, table, limit=None: [dict(row) for row in tables[table]][:limit]),
        patch.object(migrate_gnuboard5, "table_exists", lambda cursor, table: table in tables),
    ):
        call_command(
            "migrate_gnuboard5", "--apply", *options, "--source-root", "missing-source", "--only", *sorted(selected), stdout=out
        )
    return out.getvalue()


def counts():
    return {
        "social": Config.objects.filter(name__startswith="social_id_").count(),
        "inquiries": GeneralInquiry.objects.filter(legacy_qa_id__isnull=False).count(),
        "qa_meta": Config.objects.filter(name__startswith="qa_meta_").count(),
        "wish": ShopWishlist.objects.count(),
        "scrap": Post_scrap.objects.count(),
        "good": Post_good.objects.count(),
        "new_win": New_win.objects.count(),
        "menu": Site_menu.objects.count(),
    }


@override_settings(**SOCIAL_SETTINGS)
class Gnuboard5SocialLinkImportTests(SocialFlowBase):
    def test_a_member_who_signed_up_with_any_provider_logs_into_their_imported_account(self):
        _, output = run_import(source(), MEMBERS | {"member_social"})

        asker = get_user_model().objects.get(username="asker")
        for provider in PROVIDER_IDS:
            client = APIClient()
            state, _ = self.begin(client, provider=provider, redirect="/after")
            with self.provider_http(provider):
                response = self.callback(client, state)
            self.assertEqual(response.status_code, 302, provider)
            ticket = query_of(response["Location"]).get("ticket")
            self.assertTrue(ticket, f"{provider}: {response['Location']}")
            exchange = client.post(EXCHANGE_URL, {"ticket": ticket}, format="json")
            self.assertEqual(exchange.status_code, 200, (provider, exchange.content[:200]))
            self.assertEqual(exchange.json()["data"]["member"]["mb_id"], asker.username, provider)
        self.assertIn("member_social: skipped 2 row(s)", output)


class Gnuboard5MemberDataImportTests(TestCase):
    def setUp(self):
        self.imported, self.output = run_import(source(), MEMBERS | {"shop_item", "shop_qna"} | NEW_TABLES)
        User = get_user_model()
        self.asker = User.objects.get(username="asker")
        self.voter = User.objects.get(username="voter")

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_a_second_apply_adds_nothing(self):
        first = counts()
        self.assertEqual(first, {"social": 6, "inquiries": 3, "qa_meta": 2, "wish": 1, "scrap": 1, "good": 2, "new_win": 1, "menu": 1})

        run_import(source(), MEMBERS | {"shop_item", "shop_qna"} | NEW_TABLES)

        self.assertEqual(counts(), first)

    def test_a_member_sees_their_inquiry_with_its_answer_and_follow_up(self):
        response = self.client_for(self.asker).get("/api/v1/qas")

        self.assertEqual(response.status_code, 200, response.content[:300])
        rows = {row["qa_subject"]: row for row in response.json()["data"]}
        self.assertEqual(set(rows), {"문의 11", "문의 13", "문의 14"})
        answered = rows["문의 11"]
        self.assertEqual((answered["qa_status"], answered["qa_email"], answered["qa_hp"]), (1, "asker@example.test", "010-1234-5678"))
        self.assertEqual((answered["answer"]["qa_subject"], answered["answer"]["qa_content"]), ("답변드립니다", "탈퇴는 이렇게"))
        self.assertEqual([row["qa_subject"] for row in answered["related_questions"]], ["문의 13"])
        self.assertEqual(rows["문의 13"]["qa_status"], 0)
        # the product question imported with its own source id is still there, apart from the 1:1 ones
        self.assertEqual(ShopQA.objects.filter(product_id="OLD").count(), 1)

    def test_an_inquiry_whose_answer_or_file_is_missing_is_reported(self):
        self.assertIn("qa_content: 1 inquiry(ies) marked answered in the source have no answer row: qa_id 14", self.output)
        self.assertIn("qa_content: 1 attachment(s) missing from the source", self.output)

    def test_a_member_sees_their_wishlist_and_scrap(self):
        wishlist = self.client_for(self.asker).get("/api/v1/shop/wishlist").json()["data"]
        scraps = self.client_for(self.asker).get("/api/v1/scraps").json()["data"]

        self.assertEqual([row["it_id"] for row in wishlist], ["NEW"])
        self.assertEqual(len(scraps), 1)
        self.assertEqual(Post_scrap.objects.get().post, Post.objects.get(legacy_wr_id=7))

    def test_a_member_cannot_vote_again_on_a_post_they_voted_on_in_gnuboard(self):
        post = Post.objects.get(legacy_wr_id=7)

        response = self.client_for(self.voter).post(f"/api/v1/posts/free/{post.pk}/nogood")

        self.assertEqual(response.status_code, 403, response.content[:300])
        self.assertEqual(response.json()["code"], "already_voted")
        self.assertEqual(Post_good.objects.get(post__legacy_wr_id=8).bg_flag, "nogood")

    def test_popups_and_menus_keep_their_source_settings(self):
        popup = New_win.objects.get(pk=2)
        menu = Site_menu.objects.get(pk=346)

        self.assertEqual(
            (popup.nw_device, popup.nw_division, popup.nw_disable_hours, popup.nw_width, popup.nw_content_html),
            ("pc", "both", 24, 420, 1),
        )
        self.assertEqual((menu.me_code, menu.me_link, menu.me_target, menu.me_order, menu.me_mobile_use), ("50", "/content/company", "blank", 4, 0))

    def test_only_the_source_super_admin_gets_django_admin_access(self):
        User = get_user_model()

        self.assertEqual(User.objects.filter(is_superuser=True).get().username, "admin")
        self.assertFalse(User.objects.filter(is_staff=True).exclude(username="admin").exists())
        # Gnuboard's per-menu r/w/d grants are not turned into Django permissions; the run says so
        self.assertEqual(self.imported["auth"], 0)
        self.assertIn("auth: 2 admin menu grant(s) for 1 member(s) were not imported", self.output)
        self.assertIn("subadmin: 200100(r,w) 400400(r)", self.output)

    def test_new_arrivals_follow_the_source_registration_time(self):
        self.assertEqual(list(ShopProduct.objects.exclude(pk="__general_qa__").values_list("it_id", flat=True)), ["NEW", "OLD"])
        self.assertEqual(ShopProduct.objects.get(pk="OLD").created_at.year, 2019)


class Gnuboard5ProductImageReportTests(TestCase):
    def test_a_product_image_missing_from_the_source_is_reported(self):
        tables = {"g5_shop_item": [{"it_id": "NOIMG", "it_name": "NOIMG", "it_img1": "NOIMG/gone.jpg"}]}
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "data" / "item").mkdir(parents=True)
            _, output = run_import(tables, {"shop_item"}, source_root=root)

        self.assertEqual(ShopProduct.objects.get(pk="NOIMG").images, [])
        self.assertIn("shop_item: 1 product(s) list image files missing from the source: NOIMG", output)


class Gnuboard5InquiryTextImportTests(TestCase):
    def test_an_inquiry_written_in_the_html_editor_reads_as_plain_text(self):
        tables = source()
        tables["g5_qa_content"] = [
            qa(21, qa_html=1, qa_status=1,
               qa_content="<p>첫 줄</p><p>둘째&nbsp;줄<br>셋째 &amp; 넷째 &lt;b&gt;</p>\r\n\r\n\r\n<div>끝</div>"),
            qa(22, qa_type=1, qa_parent=21, qa_related=21, mb_id="admin", qa_html=2,
               qa_subject="<script>alert('hi')</script>", qa_content="<p>답변<br/>드립니다</p>"),
            qa(23, qa_content="<b>그대로</b> 1 < 2\n둘째 줄"),
        ]
        run_import(tables, MEMBERS | NEW_TABLES)
        client = APIClient()
        client.force_authenticate(user=get_user_model().objects.get(username="asker"))

        rows = {row["qa_subject"]: row for row in client.get("/api/v1/qas").json()["data"]}

        html_inquiry = rows["문의 21"]
        self.assertEqual(html_inquiry["qa_content"], "첫 줄\n둘째 줄\n셋째 & 넷째 <b>\n\n끝")
        self.assertEqual(html_inquiry["answer"]["qa_content"], "답변\n드립니다")
        # Gnuboard prints a subject as text (get_text), never as HTML, so it stays as typed
        self.assertEqual(html_inquiry["answer"]["qa_subject"], "<script>alert('hi')</script>")
        self.assertEqual((html_inquiry["qa_html"], html_inquiry["answer"]["qa_html"]), (0, 0))
        self.assertEqual(rows["문의 23"]["qa_content"], "<b>그대로</b> 1 < 2\n둘째 줄")


    def test_lists_headings_and_table_rows_keep_their_line_breaks(self):
        tables = source()
        tables["g5_qa_content"] = [
            qa(31, qa_html=1, qa_content="<h2>배송</h2><ul><li>하나</li><li>둘</li></ul><table><tr><td>칸</td></tr><tr><td>칸2</td></tr></table>"),
        ]
        run_import(tables, MEMBERS | NEW_TABLES)

        self.assertEqual(GeneralInquiry.objects.get(legacy_qa_id=31).iq_question, "배송\n하나\n둘\n칸\n칸2")


class Gnuboard5RerunTests(TestCase):
    def test_an_answer_written_in_django_survives_a_rerun(self):
        selected = MEMBERS | NEW_TABLES
        run_import(source(), selected)
        unanswered = GeneralInquiry.objects.get(legacy_qa_id=13)
        unanswered.iq_answer = "장고에서 답변함"
        unanswered.save()

        run_import(source(), selected)

        self.assertEqual(GeneralInquiry.objects.get(legacy_qa_id=13).iq_answer, "장고에서 답변함")
        self.assertEqual(GeneralInquiry.objects.get(legacy_qa_id=11).iq_answer, "탈퇴는 이렇게")

    def test_a_newer_source_keeps_its_new_product_question_apart_from_the_inquiries(self):
        selected = MEMBERS | {"shop_item", "shop_qna"} | NEW_TABLES
        run_import(source(), selected)
        newer = source()
        # the newer dump's next product question has the id Django gave an imported 1:1 inquiry
        newer["g5_shop_item_qa"].append(
            {"iq_id": GeneralInquiry.objects.get(legacy_qa_id=13).pk, "it_id": "NEW", "mb_id": "writer",
             "iq_subject": "새 상품 문의", "iq_question": "재입고 되나요", "iq_answer": "다음 주", "iq_secret": 0}
        )

        run_import(newer, selected)

        inquiry = GeneralInquiry.objects.get(legacy_qa_id=13)
        self.assertEqual((inquiry.iq_subject, inquiry.iq_answer), ("문의 13", ""))
        self.assertEqual(
            list(ShopQA.objects.filter(product_id="NEW").values_list("iq_subject", "iq_answer")), [("새 상품 문의", "다음 주")]
        )
        self.assertEqual(ShopQA.objects.filter(product_id="OLD").count(), 1)

    def test_apply_refuses_a_target_that_holds_an_earlier_import(self):
        first = apply_command(source(), MEMBERS | NEW_TABLES)

        with self.assertRaisesMessage(CommandError, "already holds rows from an earlier migrate_gnuboard5 run"):
            apply_command(source(), MEMBERS | NEW_TABLES)
        self.assertIn("Imported 3 qa_content row(s).", first)

    def test_a_member_only_rerun_cannot_unblock_a_member_blocked_in_django(self):
        tables = source()
        tables["g5_member"][3]["mb_password"] = "*" + "A" * 40
        apply_command(tables, {"member"})
        User = get_user_model()
        User.objects.filter(username="writer").update(is_active=False)

        with self.assertRaisesMessage(CommandError, "--allow-rerun"):
            apply_command(tables, {"member"})
        self.assertFalse(User.objects.get(username="writer").is_active)

    def test_allow_rerun_applies_the_same_dump_again(self):
        apply_command(source(), MEMBERS | NEW_TABLES)

        second = apply_command(source(), MEMBERS | NEW_TABLES, "--allow-rerun")

        self.assertIn("already holds rows from an earlier migrate_gnuboard5 run", second)
        self.assertIn("Imported 3 qa_content row(s).", second)
        self.assertEqual(counts()["inquiries"], 3)


class Gnuboard5OverLongValueTests(TestCase):
    """PostgreSQL refuses a value longer than its varchar(n) and the whole apply rolls back. SQLite
    stores it, so these check what is stored."""

    def test_a_faq_subject_written_in_the_editor_comes_in_whole(self):
        subject = '<p><span style="color: rgb(224, 62, 45);">' + "주문한 상품은 언제 받을 수 있나요? " * 12 + "</span></p>"
        tables = {
            "g5_faq_master": [{"fm_id": 1, "fm_subject": "배송"}],
            "g5_faq": [{"fa_id": 3, "fm_id": 1, "fa_subject": subject, "fa_content": "<p>이틀</p>"}],
        }
        run_import(tables, {"faq_master", "faq"})

        items = APIClient().get("/api/v1/faqs").json()["data"]["items"]

        self.assertGreater(len(subject), 255)
        self.assertEqual([item["fa_subject"] for item in items], [subject])

    def test_source_text_longer_than_its_django_field_is_cut_to_fit(self):
        long_text = "가" * 300
        long_email = "a" * 250 + "@example.test"
        tables = source()
        tables["g5_member"].append(member("longmail", mb_email=long_email))
        tables["g5_shop_category"] = [{"ca_id": "10", "ca_name": "분류", "ca_skin": long_text}]
        tables["g5_content"] = [{"co_id": "company", "co_subject": "회사", "co_skin": long_text, "co_mobile_skin": long_text}]
        tables["g5_shop_item_use"] = [
            {"is_id": 4, "it_id": "OLD", "mb_id": "m" * 200, "is_name": long_text, "is_subject": "후기", "is_content": "좋아요"}
        ]
        tables["g5_shop_item_qa"] = [
            {"iq_id": 1, "it_id": "OLD", "mb_id": "m" * 200, "iq_name": long_text, "iq_subject": "문의", "iq_question": "언제",
             "iq_email": long_email, "iq_hp": "0" * 255}
        ]
        tables["g5_shop_personalpay"] = [{"pp_id": 1, "pp_name": "개인결제", "pp_email": long_email}]

        run_import(tables, MEMBERS | {"shop_category", "content", "shop_item", "shop_review", "shop_qna", "shop_personalpay"})

        for model in (get_user_model(), ShopCategory, ContentPage, ShopReview, ShopQA, ShopPersonalPay):
            for row in model.objects.values():
                for field in model._meta.concrete_fields:
                    value = row[field.attname]
                    if field.max_length and isinstance(value, str):
                        self.assertLessEqual(len(value), field.max_length, f"{model.__name__}.{field.name}")
        self.assertEqual(ShopCategory.objects.get().ca_skin, long_text[:100])
        self.assertEqual(ShopReview.objects.get().is_name, long_text[:150])
        # a cut address is someone else's, so an address too long for the field is dropped
        self.assertEqual(ShopQA.objects.get(product_id="OLD").iq_email, "")
        self.assertEqual(ShopPersonalPay.objects.get().pp_email, "")
        self.assertEqual(get_user_model().objects.get(username="longmail").email, "longmail@legacy.local")


class Gnuboard5SourceConflictReportTests(TestCase):
    def test_an_identity_linked_to_two_members_goes_to_the_one_gnuboard_logs_in(self):
        tables = source()
        tables["g5_member_social_profiles"] = [
            {"mp_no": 1, "mb_id": "writer", "provider": "kakao", "identifier": "777"},
            {"mp_no": 2, "mb_id": "asker", "provider": "kakao", "identifier": "777"},
            {"mp_no": 3, "mb_id": "voter", "provider": "naver", "identifier": "n-1"},
        ]

        _, output = run_import(tables, MEMBERS | {"member_social"})

        # social_get_data(): ... where provider and identifier ... order by mb_id desc
        self.assertEqual(_social_identity_owner("kakao", "777").username, "writer")
        self.assertEqual(_social_identity_owner("naver", "n-1").username, "voter")
        self.assertIn("member_social: 1 identity(ies) are linked to more than one member", output)
        self.assertIn("kakao 777: writer (not asker)", output)

    def test_an_inactive_source_super_admin_is_reported(self):
        tables = source()
        tables["g5_member"][0]["mb_intercept_date"] = "20240101"

        _, output = run_import(tables, {"member"})

        self.assertIn("member: the source super admin (cf_admin 'admin') is left or blocked", output)


@skipUnless(connection.vendor == "postgresql", "PostgreSQL id sequences; SQLite takes the id after the largest")
class Gnuboard5IdSequenceTests(TestCase):
    """Menus come in under their source ids (me_id); the next one added in the Django admin draws on
    the same id sequence."""

    def set_menu_sequence(self, value, is_called):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT setval(pg_get_serial_sequence(%s, %s), %s, %s)",
                [Site_menu._meta.db_table, Site_menu._meta.pk.column, value, is_called],
            )

    def add_menu(self):
        return Site_menu.objects.create(me_code="60", me_name="새 메뉴", me_link="/new")

    def test_a_menu_added_after_the_import_gets_a_free_id(self):
        self.set_menu_sequence(1, False)

        run_import(source(), {"menu"})

        self.assertGreater(self.add_menu().pk, 346)

    def test_an_id_handed_out_before_the_import_is_never_handed_out_again(self):
        # ids up to 500 were used on this database and the newest rows deleted since
        self.set_menu_sequence(500, True)

        run_import(source(), {"menu"})

        self.assertGreater(self.add_menu().pk, 500)
