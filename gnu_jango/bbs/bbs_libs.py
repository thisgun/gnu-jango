import logging
import re

from collections import OrderedDict, defaultdict

from django.core.exceptions import SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from gnu_jango.config import config
from gnu_jango import defaults
from gnu_jango.utils.users import get_user_nickname

from .models import Comment, Post, Post_file
from .utils import get_next_num

logger = logging.getLogger(__name__)


def copy_post_file_content(field_file, copy_file_name):
    file_name = getattr(field_file, "name", "")
    storage = getattr(field_file, "storage", None)

    if not file_name or not storage:
        return None

    try:
        if not storage.exists(file_name):
            return None

        field_file.open("rb")
        try:
            return ContentFile(field_file.read(), name=copy_file_name)
        finally:
            field_file.close()
    except (OSError, SuspiciousFileOperation) as exc:
        logger.warning("Failed to copy post file '%s': %s", file_name, exc)
        return None


def copy_concrete_field_values(instance, exclude=None):
    excluded_fields = set(exclude or ())
    values = {}

    for field in instance._meta.concrete_fields:
        if (
            field.primary_key
            or getattr(field, "generated", False)
            or field.name in excluded_fields
            or field.attname in excluded_fields
        ):
            continue

        values[field.attname] = getattr(instance, field.attname)

    return values


def build_post_copy(row, move_board_id, next_wr_num, wr_good, wr_nogood, wr_content):
    values = copy_concrete_field_values(
        row,
        exclude={
            "board",
            "board_id",
            "wr_num",
            "wr_good",
            "wr_nogood",
            "wr_content",
        },
    )
    values.update(
        board_id=move_board_id,
        wr_num=next_wr_num,
        wr_good=wr_good,
        wr_nogood=wr_nogood,
        wr_content=wr_content,
    )
    return Post(**values)


def build_post_file_copy(source_file, move_board_id, insert_id, new_file):
    values = copy_concrete_field_values(
        source_file,
        exclude={
            "board",
            "board_id",
            "post",
            "post_id",
            "bf_file",
        },
    )
    values.update(
        board_id=move_board_id,
        post_id=insert_id,
        bf_file=new_file,
    )
    return Post_file(**values)


def build_comment_copy(source_comment, new_post_id, new_board_id, order_num, parent):
    values = copy_concrete_field_values(
        source_comment,
        exclude={
            "board",
            "board_id",
            "post",
            "post_id",
            "order_num",
            "parent",
        },
    )
    values.update(
        board_id=new_board_id,
        post_id=new_post_id,
        order_num=order_num,
        parent=parent,
    )
    return Comment(**values)


class Board_Move_update:
    def __init__(self, user, board, sw):
        self.user = user
        self.board = board
        self.sw = sw
        self.count_write = 0
        self.count_comment = 0
        self.insert_ids = defaultdict(dict)
        self.kk = 0

    def check_get_list(self, post_id, board_id):
        return Post.objects.filter(board_id__exact=board_id, wr_parent__exact=post_id)

    def check_move_update(self, post, board_id, move_board_id):

        with transaction.atomic():
            post_id = post.pk
            insert_id = self.update_loop_insert(post, move_board_id)

            if insert_id:
                self.update_reply(post_id, board_id, insert_id, move_board_id)
                self.count_write += 1

        move_array = OrderedDict([("count_write", 0), ("count_comment", 0)])
        move_array["count_write"] = self.count_write
        move_array["count_comment"] = self.count_comment
        move_array["insert_ids"] = self.insert_ids

        return move_array

    def update_reply(self, post_id, board_id, parent_id, move_board_id):

        user = self.user

        rows = self.check_get_list(post_id, board_id)

        if not rows:
            return False

        for row in rows:
            original_reply_id = row.pk

            insert_id = self.update_loop_insert(row, move_board_id)
            if insert_id:

                self.update_reply(original_reply_id, board_id, insert_id, move_board_id)

                # 답변글이라면 wr_parent 업데이트
                reply_post = Post.objects.filter(pk=insert_id)
                if reply_post:
                    reply_post.update(wr_parent=parent_id)
                    self.count_write += 1

    def update_loop_insert(self, row, move_board_id):

        user = self.user
        board = self.board
        sw = self.sw

        board_id = board.id

        nick = get_user_nickname(user, config.cf_cut_name)
        wr_content = row.wr_content or ""

        if config.cf_use_copy_log:
            if "html" in row.wr_option:
                log_tag1 = '<div class="content_%s">' % self.sw
                log_tag2 = "</div>"
            else:
                log_tag1 = "\n"
                log_tag2 = ""

            sw_str = _("복사") if self.sw == "copy" else _("이동")
            wr_content += (
                "\n"
                + log_tag1
                + "["
                + _("이 게시물은 %s님에 의해 %s %s 에서 %s 됨")
                % (nick, defaults.TIME_YMDHIS, board.bo_subject, sw_str)
                + "]"
                + log_tag2
            )

        # 게시글 추천, 비추천수
        wr_good = 0
        wr_nogood = 0

        if sw == "move":
            wr_good = row.wr_good
            wr_nogood = row.wr_nogood

        next_wr_num = get_next_num(board_id=move_board_id)
        original_pk = row.pk

        post = build_post_copy(
            row,
            move_board_id,
            next_wr_num,
            wr_good,
            wr_nogood,
            wr_content,
        )

        post.save()

        insert_id = post.pk

        if insert_id:

            # 게시물에 태그 데이터가 있다면 태그 데이터 복사

            # 코멘트 데이터 복사
            comment_copy(insert_id, original_pk, move_board_id)

            # 파일이동처리
            file_rows = Post_file.objects.filter(board=board, post_id__exact=original_pk).order_by(
                "bf_no", "-pk"
            )
            for source_file in file_rows:
                if not source_file.bf_file:
                    continue

                copy_file_name = source_file.bf_file.name

                if board_id == move_board_id:
                    m = re.match(r"_copy(\d+)?_(\d+)_", copy_file_name)
                    if m:
                        number = 0 if m is None else m[1]
                        replace_str = "_copy%s_%s_" % ((int(number) + 1), insert_id)
                        copy_file_name = re.sub(r"_copy(\d+)?_(\d+)_", replace_str, copy_file_name)
                    else:
                        copy_file_name = "%s_copy_%s_%s" % (
                            original_pk,
                            insert_id,
                            source_file.bf_file,
                        )

                new_file = copy_post_file_content(source_file.bf_file, copy_file_name)

                insert_file = build_post_file_copy(
                    source_file,
                    move_board_id,
                    insert_id,
                    new_file,
                )
                insert_file.save()

            # 메타데이터 복사

            if sw == "move":
                # 스크랩 이동

                # 추천데이터 (좋아요 싫어요) 이동
                pass

        self.insert_ids[self.kk]["post_id"] = post.pk

        self.kk += 1

        return insert_id

    # 원글 삭제
    def sql_delete(self, post_id, board_id):
        pass


# 댓글 복사
def comment_copy(new_post_id, before_post_id, new_board_id, before_board_id=0):

    rows = Comment.objects.filter(post_id__exact=before_post_id).order_by(
        "parent",
        "order_num",
    )
    before_parent_arr = {}

    for source_comment in rows:
        save_post_id = source_comment.pk
        parent = source_comment.parent

        if parent > 0:
            key = "id_%s" % parent

            if key in before_parent_arr:
                parent = before_parent_arr[key]

        comment = build_comment_copy(
            source_comment,
            new_post_id,
            new_board_id,
            get_next_num(True, board_id=new_board_id),
            parent,
        )
        comment.save()

        if comment.pk:
            save_key = "id_%s" % save_post_id
            before_parent_arr[save_key] = comment.pk
