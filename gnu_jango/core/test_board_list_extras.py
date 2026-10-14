"""Board list extras the theme's list screen asks for: category counts and gallery excerpts."""

from django.core.cache import cache
from django.test import override_settings

from gnu_jango.config.models import Config
from gnu_jango.core.test_board_api_more import API, BoardApiTestCase
from gnu_jango.users import point_ledger


class BoardCategoryCountsTests(BoardApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.sorted_board = cls.make_board("cat-board", bo_use_category=True, bo_category_list="News|Q&A")
        cls.make_post(cls.sorted_board, cls.owner, ca_name="News")
        cls.make_post(cls.sorted_board, cls.owner, ca_name="News")
        cls.make_post(cls.sorted_board, cls.other, ca_name="Q&A")
        cls.make_post(cls.sorted_board, cls.other, ca_name="")

    def setUp(self):
        cache.clear()

    def counts(self, board=None, user=None):
        return self.api(user).get(f"{API}/boards/{(board or self.sorted_board).bo_table}/category-counts")

    def test_counts_are_off_unless_enabled(self):
        response = self.counts()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], {"counts": None, "reason": "disabled"})

    @override_settings(BOARD_CATEGORY_COUNTS=True)
    def test_enabled_counts_skip_uncategorised_posts(self):
        response = self.counts()

        self.assertEqual(response.json()["data"], {"counts": {"News": 2, "Q&A": 1}, "reason": None})

    @override_settings(BOARD_CATEGORY_COUNTS=True)
    def test_boards_without_categories_report_why(self):
        self.assertEqual(self.counts(self.board).json()["data"], {"counts": None, "reason": "no_category"})

    @override_settings(BOARD_CATEGORY_COUNTS=True, BOARD_CATEGORY_COUNTS_MAX_POSTS=2)
    def test_large_boards_are_not_counted(self):
        type(self.sorted_board).objects.filter(pk=self.sorted_board.pk).update(bo_count_write=3)

        self.assertEqual(self.counts().json()["data"], {"counts": None, "reason": "too_many_posts"})

    @override_settings(BOARD_CATEGORY_COUNTS=True)
    def test_visitors_who_cannot_list_the_board_are_refused(self):
        type(self.sorted_board).objects.filter(pk=self.sorted_board.pk).update(bo_list_level=2)

        self.assertEqual(self.counts().status_code, 403)
        self.assertEqual(self.counts(user=self.owner).status_code, 200)

    def test_unknown_board_is_not_found(self):
        response = self.api().get(f"{API}/boards/no-such-board/category-counts")

        self.assertEqual(response.status_code, 404)


class BoardListExcerptTests(BoardApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gallery = cls.make_board("excerpt-gallery")
        cls.pictured = cls.make_post(
            cls.gallery,
            cls.owner,
            wr_content="<p>First line</p><p>Second&nbsp;line {이미지:0} &amp; more</p>" + "x" * 100,
        )
        cls.secret = cls.make_post(cls.gallery, cls.owner, wr_content="hidden words", wr_option="secret")

    def excerpts(self, board=None, user=None, **query):
        response = self.api(user).get(f"{API}/boards/{(board or self.gallery).bo_table}/posts", query)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return {row["wr_id"]: row.get("wr_excerpt") for row in response.json()["data"]}

    def test_excerpt_is_plain_text_cut_to_seventy_characters(self):
        excerpt = self.excerpts(**{"with": "excerpt"})[self.pictured.pk]

        self.assertTrue(excerpt.startswith("First line Second line & more xxx"))
        self.assertTrue(excerpt.endswith("…"))
        self.assertEqual(len(excerpt), 71)

    def test_excerpt_is_only_sent_when_asked_for(self):
        self.assertIsNone(self.excerpts()[self.pictured.pk])

    def test_secret_posts_never_carry_an_excerpt(self):
        self.assertIsNone(self.excerpts(**{"with": "excerpt"})[self.secret.pk])

    def test_secret_posts_carry_no_excerpt_even_for_their_author(self):
        # The card shows a lock; its body stays in the post view (site search says "비밀글입니다." too).
        self.assertIsNone(self.excerpts(user=self.owner, **{"with": "excerpt"})[self.secret.pk])

    def test_listable_but_unreadable_boards_send_no_excerpt(self):
        type(self.gallery).objects.filter(pk=self.gallery.pk).update(bo_read_level=2)

        self.assertIsNone(self.excerpts(**{"with": "excerpt"})[self.pictured.pk])
        self.assertIsNotNone(self.excerpts(user=self.other, **{"with": "excerpt"})[self.pictured.pk])

    def test_read_point_boards_send_excerpts_only_to_authors_and_payers(self):
        Config.objects.update_or_create(name="cf_use_point", defaults={"value": "1"})
        type(self.gallery).objects.filter(pk=self.gallery.pk).update(bo_read_point=-5)

        self.assertIsNone(self.excerpts(**{"with": "excerpt"})[self.pictured.pk])
        self.assertIsNone(self.excerpts(user=self.other, **{"with": "excerpt"})[self.pictured.pk])
        self.assertIsNotNone(self.excerpts(user=self.owner, **{"with": "excerpt"})[self.pictured.pk])

        point_ledger.insert_point(self.other, 100, "seed", "@passive", 0, "seed")
        point_ledger.insert_point(
            self.other, -5, "read", self.gallery.bo_table, point_ledger.post_point_id(self.pictured), "읽기"
        )
        self.assertIsNotNone(self.excerpts(user=self.other, **{"with": "excerpt"})[self.pictured.pk])
