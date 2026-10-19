"""Each site's own navigation reaches the static export at run time.

The theme export is built once (on whatever machine runs the build) and served by every installation,
so menus baked into it point at the build machine's boards (e.g. /notice, /board) and give 404s on
other sites. Django therefore puts the site's menus and its public boards into the page's runtime
config; the header uses them instead of anything built in.
"""

import json
import re

from rest_framework.test import APIClient

from gnu_jango.bbs.models import Board, Group
from gnu_jango.config import config as site_config
from gnu_jango.config.models import Config
from gnu_jango.core.models import Site_menu
from gnu_jango.core.test_nextjs_theme_selection import ThemeFixture


def runtime_config(html):
    match = re.search(r"window\.__G5_NEXTJS25_CONFIG__ = (\{.*?\});</script>", html)
    return json.loads(match.group(1)) if match else {}


class RuntimeNavigationTests(ThemeFixture):
    def setUp(self):
        super().setUp()
        self.activate("nextjs_default")
        self.community = Group.objects.create(gr_id="community", gr_subject="커뮤니티", gr_order=1)

    def board(self, table, subject, *, group=None, order=0, list_level=1):
        return Board.objects.create(
            group=group or self.community, bo_table=table, bo_subject=subject, bo_order=order, bo_list_level=list_level
        )

    def page_config(self):
        return runtime_config(self.client.get("/").content.decode())

    def test_the_page_carries_the_sites_own_menus(self):
        Site_menu.objects.create(me_code="10", me_name="공지", me_link="/공지사항", me_use=1, me_order=1)
        Site_menu.objects.create(me_code="1010", me_name="이벤트", me_link="/event", me_use=1, me_order=1)
        Site_menu.objects.create(me_code="20", me_name="숨김", me_link="/hidden", me_use=0, me_order=2)

        menus = self.page_config()["menus"]

        self.assertEqual([menu["me_name"] for menu in menus], ["공지"])
        self.assertEqual(menus[0]["me_link"], "/공지사항")
        self.assertEqual([child["me_name"] for child in menus[0]["children"]], ["이벤트"])
        self.assertIsInstance(menus[0]["me_id"], int)

    def test_a_site_without_menus_gets_an_empty_list_and_its_public_boards(self):
        self.board("자유게시판", "자유게시판", order=2)
        self.board("공지사항", "공지사항", order=1)
        self.board("staff", "운영진", list_level=5)
        manual = Group.objects.create(gr_id="manual", gr_subject="매뉴얼", gr_order=0)
        self.board("hb_start", "처음 따라하기", group=manual)
        Config.objects.update_or_create(name="cf_docs_group", defaults={"value": "manual"})
        site_config.clear()

        config = self.page_config()

        self.assertEqual(config["menus"], [])
        self.assertEqual(
            config["navBoards"],
            [{"bo_table": "공지사항", "bo_subject": "공지사항"}, {"bo_table": "자유게시판", "bo_subject": "자유게시판"}],
        )

    def test_the_board_list_stays_short(self):
        for index in range(12):
            self.board(f"b{index:02d}", f"게시판 {index}", order=index)

        self.assertEqual(len(self.page_config()["navBoards"]), 8)

    def test_the_menus_api_uses_the_same_shape(self):
        Site_menu.objects.create(me_code="10", me_name="공지", me_link="/공지사항", me_use=1)

        data = APIClient().get("/api/v1/menus").json()["data"]

        self.assertEqual(data[0]["me_name"], "공지")
        self.assertIsInstance(data[0]["me_id"], int)
