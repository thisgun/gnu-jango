"""Site search results: no full bodies, a plain-text preview around the keyword, and paging.

Mirrors the reference API (api/v1/search.php): the list payload carries no body, the preview
follows the same read rules as board list excerpts (read points included), secret posts only
say that they are secret, title matches come first and `page` walks one board's matches.
"""

from gnu_jango.config.models import Config
from gnu_jango.core.test_board_api_more import API, BoardApiTestCase
from gnu_jango.users import point_ledger

SECRET_PREVIEW = "비밀글입니다."


class SearchPreviewTests(BoardApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.searchable = cls.make_board("search-preview")
        cls.long_post = cls.make_post(
            cls.searchable,
            cls.owner,
            wr_subject="Long article",
            wr_content="<p>" + "a" * 300 + " platypus &amp; friends " + "b" * 300 + "</p>",
        )
        cls.titled = cls.make_post(
            cls.searchable,
            cls.owner,
            wr_subject="All about platypus",
            wr_content="<p>Short body</p>",
        )

    def search(self, user=None, **params):
        response = self.api(user).get(f"{API}/search", params)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()

    def posts(self, user=None, **params):
        data = self.search(user, **params)["data"]
        return [post for group in data["results"] for post in group["posts"]]

    def found(self, target, user=None, **params):
        return next(post for post in self.posts(user, q="platypus", **params) if post["wr_id"] == target.pk)

    def test_results_never_carry_the_full_body(self):
        result = self.found(self.long_post)

        self.assertEqual(result["wr_content"], "")
        self.assertEqual(result["content"], "")

    def test_preview_is_plain_text_around_the_keyword(self):
        preview = self.found(self.long_post)["wr_content_preview"]

        self.assertTrue(preview.startswith("..."))
        self.assertTrue(preview.endswith("..."))
        self.assertIn("platypus & friends", preview)
        self.assertNotIn("<", preview)
        self.assertEqual(len(preview), 220 + 6)

    def test_preview_starts_at_the_beginning_when_only_the_title_matches(self):
        self.assertEqual(self.found(self.titled)["wr_content_preview"], "Short body")

    def test_title_matches_come_first(self):
        found = self.posts(q="platypus", bo_table=self.searchable.bo_table)

        self.assertEqual([post["wr_id"] for post in found][:2], [self.titled.pk, self.long_post.pk])

    def test_page_walks_one_boards_matches(self):
        first = self.search(q="platypus", bo_table=self.searchable.bo_table, per_page=1)
        second = self.search(q="platypus", bo_table=self.searchable.bo_table, per_page=1, page=2)

        self.assertEqual([p["wr_id"] for g in first["data"]["results"] for p in g["posts"]], [self.titled.pk])
        self.assertEqual([p["wr_id"] for g in second["data"]["results"] for p in g["posts"]], [self.long_post.pk])
        self.assertEqual(second["data"]["results"][0]["count"], 2)
        self.assertEqual(second["meta"]["current_page"], 2)

    def test_secret_posts_only_say_they_are_secret(self):
        secret = self.make_post(self.searchable, self.owner, wr_subject="platypus diary", wr_option="secret")

        self.assertEqual(self.found(secret, user=self.owner)["wr_content_preview"], SECRET_PREVIEW)
        self.assertNotIn(secret.pk, [post["wr_id"] for post in self.posts(user=self.other, q="platypus")])

    def test_page_is_ignored_without_a_board(self):
        first = self.search(q="platypus", per_page=1)
        second = self.search(q="platypus", per_page=1, page=2)

        self.assertEqual(first["data"], second["data"])
        self.assertEqual(second["meta"]["current_page"], 1)

    def test_read_point_boards_match_body_text_only_for_the_author(self):
        Config.objects.update_or_create(name="cf_use_point", defaults={"value": "1"})
        type(self.searchable).objects.filter(pk=self.searchable.pk).update(bo_read_point=-5)
        hidden = self.make_post(self.searchable, self.owner, wr_subject="Plain title", wr_content="secret ingredient: wombat")

        self.assertNotIn(hidden.pk, [post["wr_id"] for post in self.posts(q="wombat")])
        self.assertNotIn(hidden.pk, [post["wr_id"] for post in self.posts(user=self.other, q="wombat")])
        self.assertIn(hidden.pk, [post["wr_id"] for post in self.posts(user=self.owner, q="wombat")])

    def test_read_point_boards_preview_only_for_authors_and_payers(self):
        Config.objects.update_or_create(name="cf_use_point", defaults={"value": "1"})
        type(self.searchable).objects.filter(pk=self.searchable.pk).update(bo_read_point=-5)

        # A title hit is still listed, without a preview, for readers who have not paid.
        self.assertEqual(self.found(self.titled)["wr_content_preview"], "")
        self.assertEqual(self.found(self.titled, user=self.other)["wr_content_preview"], "")
        self.assertIn("platypus", self.found(self.long_post, user=self.owner)["wr_content_preview"])

        point_ledger.insert_point(self.other, 100, "seed", "@passive", 0, "seed")
        point_ledger.insert_point(
            self.other, -5, "read", self.searchable.bo_table, point_ledger.post_point_id(self.long_post), "읽기"
        )
        self.assertIn("platypus", self.found(self.long_post, user=self.other)["wr_content_preview"])
