"""Response contracts of the board read endpoints (``gnu_jango/api/v1_board.py``).

- ``GET /api/v1/boards`` and ``GET /api/v1/boards/{bo_table}``: ``_board_payload``
- ``GET /api/v1/boards/{bo_table}/posts``: ``_post_payload(list_view=True)`` rows and the
  ``_paginate_board_posts`` meta
- ``GET /api/v1/posts/{bo_table}/{wr_id}``: ``_post_payload(detail=True)``

Gnuboard5 flags are sent as 0/1 integers (``_bool_int``), the ``is_*``/``can_*`` keys as booleans.
"""

from drf_spectacular.utils import PolymorphicProxySerializer
from rest_framework import serializers

from . import PageMetaSerializer

# Named enum component (SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"]); "" is the BlankEnum.
POST_ADMIN_ROLES = ["super", "group", "board", ""]


class BoardSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    bo_table = serializers.CharField()
    gr_id = serializers.CharField(allow_blank=True)
    group_id = serializers.IntegerField()
    bo_subject = serializers.CharField(allow_blank=True)
    bo_mobile_subject = serializers.CharField(allow_blank=True)
    bo_device = serializers.CharField()
    bo_admin = serializers.CharField(allow_blank=True)
    # Group.gr_admin is copied as stored, so a NULL column comes out as null (bo_admin is coerced to "").
    gr_admin = serializers.CharField(allow_blank=True, allow_null=True)
    bo_category_list = serializers.CharField(allow_blank=True)
    bo_list_level = serializers.IntegerField()
    bo_read_level = serializers.IntegerField()
    bo_write_level = serializers.IntegerField()
    bo_reply_level = serializers.IntegerField()
    bo_comment_level = serializers.IntegerField()
    bo_upload_level = serializers.IntegerField()
    bo_download_level = serializers.IntegerField()
    bo_html_level = serializers.IntegerField()
    bo_link_level = serializers.IntegerField()
    bo_count_delete = serializers.IntegerField()
    bo_count_modify = serializers.IntegerField()
    bo_read_point = serializers.IntegerField()
    bo_write_point = serializers.IntegerField()
    bo_comment_point = serializers.IntegerField()
    bo_download_point = serializers.IntegerField()
    bo_use_category = serializers.IntegerField()
    bo_use_sideview = serializers.IntegerField()
    bo_use_file_content = serializers.IntegerField()
    bo_use_secret = serializers.IntegerField()
    bo_use_captcha = serializers.IntegerField()
    bo_use_dhtml_editor = serializers.IntegerField()
    bo_use_rss_view = serializers.IntegerField()
    bo_use_good = serializers.IntegerField()
    bo_use_nogood = serializers.IntegerField()
    bo_use_name = serializers.IntegerField()
    bo_use_signature = serializers.IntegerField()
    bo_use_ip_view = serializers.IntegerField()
    bo_use_list_view = serializers.IntegerField()
    bo_use_list_file = serializers.IntegerField()
    bo_use_list_content = serializers.IntegerField()
    bo_use_email = serializers.IntegerField()
    bo_page_rows = serializers.IntegerField()
    bo_mobile_page_rows = serializers.IntegerField()
    bo_subject_len = serializers.IntegerField()
    bo_mobile_subject_len = serializers.IntegerField()
    bo_new = serializers.IntegerField()
    bo_hot = serializers.IntegerField()
    bo_image_width = serializers.IntegerField()
    bo_skin = serializers.CharField(allow_blank=True)
    bo_mobile_skin = serializers.CharField(allow_blank=True)
    bo_content_head = serializers.CharField(allow_blank=True)
    bo_content_tail = serializers.CharField(allow_blank=True)
    bo_mobile_content_head = serializers.CharField(allow_blank=True)
    bo_mobile_content_tail = serializers.CharField(allow_blank=True)
    bo_gallery_cols = serializers.IntegerField()
    bo_gallery_width = serializers.IntegerField()
    bo_gallery_height = serializers.IntegerField()
    bo_mobile_gallery_width = serializers.IntegerField()
    bo_mobile_gallery_height = serializers.IntegerField()
    bo_upload_size = serializers.IntegerField()
    bo_reply_order = serializers.IntegerField()
    bo_use_search = serializers.IntegerField()
    bo_order = serializers.IntegerField()
    # Live counts (same values as post_count / comment_count), not the stored Board columns.
    bo_count_write = serializers.IntegerField()
    bo_count_comment = serializers.IntegerField()
    bo_write_min = serializers.IntegerField()
    bo_write_max = serializers.IntegerField()
    bo_comment_min = serializers.IntegerField()
    bo_comment_max = serializers.IntegerField()
    bo_notice = serializers.CharField(allow_blank=True)
    bo_upload_count = serializers.IntegerField()
    # Alias of bo_content_head.
    bo_content = serializers.CharField(allow_blank=True)
    post_count = serializers.IntegerField()
    comment_count = serializers.IntegerField()


class PostAuthorSerializer(serializers.Serializer):
    """``_member_payload_for_author``: blank strings for a guest."""

    mb_id = serializers.CharField(allow_blank=True)
    mb_nick = serializers.CharField(allow_blank=True)
    mb_icon_path = serializers.CharField(allow_blank=True)


class BoardPostSerializer(serializers.Serializer):
    """The keys every ``_post_payload`` row has (list rows and the detail)."""

    id = serializers.IntegerField()
    # legacy_wr_id for imported posts, else the primary key.
    wr_id = serializers.IntegerField()
    bo_table = serializers.CharField()
    bo_subject = serializers.CharField(allow_blank=True)
    wr_num = serializers.IntegerField()
    wr_reply = serializers.CharField(allow_blank=True)
    wr_parent = serializers.IntegerField()
    wr_is_comment = serializers.IntegerField()
    wr_comment = serializers.IntegerField()
    wr_comment_reply = serializers.CharField(allow_blank=True)
    ca_name = serializers.CharField(allow_blank=True)
    wr_option = serializers.CharField(allow_blank=True)
    wr_subject = serializers.CharField(allow_blank=True)
    # Blank in list rows.
    wr_content = serializers.CharField(allow_blank=True)
    content = serializers.CharField(allow_blank=True)
    wr_seo_title = serializers.CharField(allow_blank=True)
    wr_slug = serializers.CharField(allow_blank=True)
    # Blank in list rows.
    wr_link1 = serializers.CharField(allow_blank=True)
    wr_link2 = serializers.CharField(allow_blank=True)
    wr_link1_hit = serializers.IntegerField()
    wr_link2_hit = serializers.IntegerField()
    wr_hit = serializers.IntegerField()
    wr_good = serializers.IntegerField()
    wr_nogood = serializers.IntegerField()
    wr_name = serializers.CharField(allow_blank=True)
    # Only the author and board administrators get the address; blank for everyone else.
    wr_email = serializers.CharField(allow_blank=True)
    wr_homepage = serializers.CharField(allow_blank=True)
    wr_datetime = serializers.DateTimeField()
    wr_last = serializers.DateTimeField()
    # Masked (bo_use_ip_view) or blank unless the viewer may see it in full.
    wr_ip = serializers.CharField(allow_blank=True)
    mb_id = serializers.CharField(allow_blank=True)
    mb_nick = serializers.CharField(allow_blank=True)
    mb_icon_path = serializers.CharField(allow_blank=True)
    member = PostAuthorSerializer()
    thumbnail = serializers.CharField(allow_blank=True)
    is_notice = serializers.BooleanField()
    is_new = serializers.BooleanField()
    is_hot = serializers.BooleanField()
    is_secret = serializers.BooleanField()
    bo_use_good = serializers.IntegerField()
    bo_use_nogood = serializers.IntegerField()
    can_manage = serializers.BooleanField()
    # "super", "group", "board" or "" (the viewer's role on this board).
    # v1_board._admin_role: the viewer's admin standing on this board, "" for none.
    admin_role = serializers.ChoiceField(choices=POST_ADMIN_ROLES, allow_blank=True)
    is_scrapped = serializers.BooleanField()
    scrap_id = serializers.IntegerField()


class BoardPostListItemSerializer(BoardPostSerializer):
    # Only with ?with=excerpt, on non-secret posts the viewer may read.
    wr_excerpt = serializers.CharField(allow_blank=True, required=False)


class PostFileSerializer(serializers.Serializer):
    """``_file_payload``."""

    bf_no = serializers.IntegerField()
    bo_table = serializers.CharField(allow_blank=True)
    wr_id = serializers.IntegerField()
    bf_source = serializers.CharField(allow_blank=True)
    bf_file = serializers.CharField(allow_blank=True)
    bf_download = serializers.IntegerField()
    bf_content = serializers.CharField(allow_blank=True)
    bf_fileurl = serializers.CharField(allow_blank=True)
    bf_thumburl = serializers.CharField(allow_blank=True)
    bf_storage = serializers.CharField(allow_blank=True)
    bf_filesize = serializers.IntegerField()
    bf_width = serializers.IntegerField()
    bf_height = serializers.IntegerField()
    bf_type = serializers.IntegerField()
    bf_datetime = serializers.DateTimeField()
    bf_url = serializers.CharField(allow_blank=True)
    bf_download_url = serializers.CharField(allow_blank=True)
    bf_download_available = serializers.BooleanField()


class PostCommentSerializer(serializers.Serializer):
    """``_comment_payload``: a secret comment the viewer may not read carries a placeholder text."""

    id = serializers.IntegerField()
    wr_id = serializers.IntegerField()
    bo_table = serializers.CharField(allow_blank=True)
    wr_parent = serializers.IntegerField()
    wr_is_comment = serializers.IntegerField()
    wr_comment = serializers.IntegerField()
    wr_comment_reply = serializers.CharField(allow_blank=True)
    wr_content = serializers.CharField(allow_blank=True)
    content = serializers.CharField(allow_blank=True)
    wr_name = serializers.CharField(allow_blank=True)
    mb_id = serializers.CharField(allow_blank=True)
    mb_nick = serializers.CharField(allow_blank=True)
    member = PostAuthorSerializer()
    wr_datetime = serializers.DateTimeField()
    wr_last = serializers.DateTimeField()
    wr_ip = serializers.CharField(allow_blank=True)
    wr_option = serializers.CharField(allow_blank=True)


class PostNavSerializer(serializers.Serializer):
    wr_id = serializers.IntegerField()
    wr_subject = serializers.CharField(allow_blank=True)
    wr_seo_title = serializers.CharField(allow_blank=True)


class PostDetailSerializer(BoardPostSerializer):
    files = PostFileSerializer(many=True)
    comments = PostCommentSerializer(many=True)
    # The neighbouring posts the viewer may read; null at either end of the board.
    prev_post = PostNavSerializer(allow_null=True)
    next_post = PostNavSerializer(allow_null=True)



class BoardPostsPageMetaSerializer(PageMetaSerializer):
    """``_paginate_board_posts``: PageMeta, its aliases and the notice counts.

    ``total`` counts notices and regular posts; ``last_page`` counts regular posts only, since
    notices are shown above each page rather than taking rows of it.
    """

    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    # Notices on this page / on the whole board.
    notice_count = serializers.IntegerField()
    total_notice_count = serializers.IntegerField()
    # Continue this list with ?cursor=<next_cursor> (null while searching, on the last page, or
    # while notices still spill onto later pages).
    next_cursor = serializers.CharField(allow_null=True)


class BoardPostsCursorMetaSerializer(serializers.Serializer):
    """``?cursor=`` mode (``_cursor_posts_response``): no totals, only where to continue."""

    per_page = serializers.IntegerField()
    has_more = serializers.BooleanField()
    next_cursor = serializers.CharField(allow_null=True)


BoardPostsMeta = PolymorphicProxySerializer(
    component_name="BoardPostsMeta",
    serializers=[BoardPostsPageMetaSerializer, BoardPostsCursorMetaSerializer],
    resource_type_field_name=None,
)
