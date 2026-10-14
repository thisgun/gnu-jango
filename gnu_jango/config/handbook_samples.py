"""A small sample manual for the handbook theme: one board group, four books, ~20 chapters.

The handbook theme maps gnuboard data onto a manual — a board group is the manual, each board in it
a book (its subject "hint · name" gives a small hint and the book name), each board category a part
(in the order of bo_category_list) and each post a chapter. This module builds that structure for
demos and QA; real manuals are written on the boards in the admin.

It only ever touches the group, boards and posts it created (group "manual", tables hb_*) and
refuses to reuse a table name that already belongs to something else.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from gnu_jango.bbs.models import Board, Group, Post
from gnu_jango.bbs.utils import get_next_num

from .models import Config

GROUP_ID = "manual"
GROUP_SUBJECT = "매뉴얼"
DOCS_GROUP_KEY = "cf_docs_group"


class HandbookSampleError(Exception):
    pass


@dataclass(frozen=True)
class Book:
    table: str
    subject: str
    #: (part, chapter titles). The part is the post category; "" means chapters without one.
    parts: tuple


BOOKS = (
    Book(
        "hb_start",
        "시작하기 · 처음 따라하기",
        (
            ("시작 전", ("이 안내서가 하는 일", "필요한 것")),
            ("따라하기", ("설치하기", "첫 화면 열기", "글 써 보기")),
            ("내 것으로 만들기", ("이름과 색 바꾸기",)),
        ),
    ),
    Book(
        "hb_dev",
        "개발·배포 · 개발자 안내서",
        (
            ("개발 준비", ("개발 환경", "폴더 구조")),
            ("화면 만들기", ("서버 컴포넌트와 클라이언트 컴포넌트", "슬롯 끼우기", "스타일 바꾸기")),
            ("데이터 다루기", ("API 부르기", "게시판 데이터")),
        ),
    ),
    Book(
        "hb_deploy",
        "개발·배포 · 서버에 올리기",
        (
            ("준비", ("서버 요구사항", "환경 변수")),
            ("올리기", ("빌드하기", "정적 파일 올리기")),
            ("막혔을 때", ("자주 만나는 오류",)),
        ),
    ),
    Book(
        "hb_ref",
        "부록 · 용어와 참고",
        (("", ("용어 사전", "단축키", "변경 기록")),),
    ),
)


def _chapter_body(title):
    """A chapter with the shapes the reading screen styles: intro, headings, list, code, table."""
    return (
        f"<p><strong>{title}</strong>에서 다루는 내용을 먼저 짧게 정리합니다. 아래 순서대로 읽으면 됩니다.</p>"
        "<h2>먼저 알아 둘 것</h2>"
        "<p>이 장은 예시를 위한 샘플 글입니다. 실제 매뉴얼은 관리자에서 게시판에 글을 써서 채웁니다.</p>"
        "<ul><li>한 번에 한 가지씩 따라 하세요.</li><li>막히면 <code>막혔을 때</code> 부를 확인하세요.</li></ul>"
        "<h2>따라 해 보기</h2>"
        "<h3>1단계</h3>"
        "<p>명령을 실행합니다.</p>"
        "<pre><code>npm run build:theme:handbook\n</code></pre>"
        "<h3>2단계</h3>"
        "<p>결과를 확인합니다.</p>"
        "<table><thead><tr><th>확인할 것</th><th>기대하는 모습</th></tr></thead>"
        "<tbody><tr><td>왼쪽 목차</td><td>현재 장이 강조됩니다</td></tr>"
        "<tr><td>오른쪽 목차</td><td>이 장의 제목이 나열됩니다</td></tr></tbody></table>"
        "<h2>정리</h2>"
        "<p>다음 장으로 넘어가기 전에 위 내용을 한 번 더 확인하세요.</p>"
    )


def _book_table_names():
    return [book.table for book in BOOKS]


def _group():
    group = Group.objects.filter(gr_id=GROUP_ID).first()
    return group or Group.objects.create(gr_id=GROUP_ID, gr_subject=GROUP_SUBJECT)


def _check_tables_are_free(group):
    for table in _book_table_names():
        existing = Board.objects.filter(bo_table=table).first()
        if existing and existing.group_id != group.pk:
            raise HandbookSampleError(f"{table} 게시판이 이미 있고 매뉴얼 그룹의 것이 아닙니다.")


def _board(group, order, book):
    categories = "|".join(part for part, _ in book.parts if part)
    values = {
        "group": group,
        "bo_subject": book.subject,
        "bo_mobile_subject": book.subject,
        "bo_order": order,
        "bo_use_category": bool(categories),
        "bo_category_list": categories,
        "bo_list_level": 1,
        "bo_read_level": 1,
        "bo_write_level": 10,
        "bo_reply_level": 10,
        "bo_comment_level": 1,
        "bo_skin": "basic",
        "bo_mobile_skin": "basic",
        "bo_page_rows": 100,
        "bo_mobile_page_rows": 100,
        "bo_use_search": True,
    }
    board, _created = Board.objects.update_or_create(bo_table=book.table, defaults=values)
    return board


def _chapters(board, book, created_at):
    if Post.objects.filter(board=board).exists():
        return 0
    chapters = [(part, title) for part, titles in book.parts for title in titles]
    # A new post gets the smallest wr_num so that the newest comes first on a board list. A book is
    # read from its first chapter, so the chapters are written last to first.
    for index, (part, title) in enumerate(reversed(chapters)):
        stamp = created_at - timedelta(minutes=index)
        post = Post.objects.create(
            board=board,
            wr_num=get_next_num(board_id=board.pk),
            wr_parent=0,
            wr_subject=title,
            wr_content=_chapter_body(title),
            wr_option="html1",
            ca_name=part,
            wr_name="매뉴얼 편집자",
            wr_datetime=stamp,
            wr_last=stamp,
        )
        Post.objects.filter(pk=post.pk).update(wr_parent=post.pk)
    return len(chapters)


def _clear_config_cache():
    from . import config as site_config

    site_config.clear()


@transaction.atomic
def ensure_samples():
    """Create the sample manual (or complete it) and point the theme at it. Safe to run again."""
    group = _group()
    _check_tables_are_free(group)
    now = timezone.now()
    created = 0
    for order, book in enumerate(BOOKS, start=1):
        board = _board(group, order, book)
        created += _chapters(board, book, now)
    Config.objects.update_or_create(name=DOCS_GROUP_KEY, defaults={"value": GROUP_ID})
    _clear_config_cache()
    return {"group": GROUP_ID, "books": len(BOOKS), "chapters_created": created}


@transaction.atomic
def remove_samples():
    """Delete what ensure_samples made: its posts, boards and group. Nothing else."""
    group = Group.objects.filter(gr_id=GROUP_ID).first()
    removed = {"posts": 0, "boards": 0, "groups": 0}
    if group:
        boards = Board.objects.filter(group=group, bo_table__in=_book_table_names())
        removed["posts"] = Post.objects.filter(board__in=boards).count()
        Post.objects.filter(board__in=boards).delete()
        removed["boards"] = boards.count()
        boards.delete()
        if not Board.objects.filter(group=group).exists():
            group.delete()
            removed["groups"] = 1
    Config.objects.filter(name=DOCS_GROUP_KEY, value=GROUP_ID).delete()
    _clear_config_cache()
    return removed
