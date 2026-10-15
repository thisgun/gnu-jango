"""A small sample manual for the handbook theme: one board group, seven books, 37 chapters.

The handbook theme maps gnuboard data onto a manual — a board group is the manual, each board in it
a book (its subject "hint · name" gives a small hint and the book name), each board category a part
(in the order of bo_category_list) and each post a chapter. This module builds that structure for
demos and QA; real manuals are written on the boards in the admin.

It only ever touches the group, boards and posts it created (group "manual", tables hb_*) and
refuses to reuse a table name that already belongs to something else.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.db import transaction
from django.utils import timezone

from gnu_jango.bbs.models import Board, Group, Post
from gnu_jango.bbs.utils import get_next_num

from .models import Config
from .handbook_content import LEGACY_SAMPLE_MARKER, chapter_body

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
        "hb_board",
        "커뮤니티 운영 · 게시판 관리",
        (
            ("시작", ("게시판과 그룹 이해", "게시판 만들기")),
            ("글 관리", ("분류와 메뉴 구성", "글과 댓글 관리")),
            ("안전 운영", ("비밀글과 첨부파일 관리",)),
        ),
    ),
    Book(
        "hb_member",
        "커뮤니티 운영 · 회원과 권한",
        (
            ("계정", ("회원가입과 로그인", "회원 등급과 접근 권한")),
            ("방문자 참여", ("비회원 글쓰기와 댓글",)),
            ("스팸과 보안", ("스팸과 자동등록방지", "계정과 개인정보 보호")),
        ),
    ),
    Book(
        "hb_shop",
        "쇼핑몰 운영 · 상품과 주문",
        (
            ("상품", ("쇼핑몰 설정 시작하기", "상품과 분류 등록하기")),
            ("주문", ("장바구니와 주문 흐름", "배송과 주문 상태 관리")),
            ("결제", ("결제 설정과 테스트", "가상계좌 운영 점검")),
        ),
    ),
    Book(
        "hb_dev",
        "개발과 배포 · 개발자 안내서",
        (
            ("개발 준비", ("개발 환경", "폴더 구조")),
            ("화면 만들기", ("서버 컴포넌트와 클라이언트 컴포넌트", "슬롯 끼우기", "스타일 바꾸기")),
            ("데이터 다루기", ("API 부르기", "게시판 데이터")),
        ),
    ),
    Book(
        "hb_deploy",
        "개발과 배포 · 서버에 올리기",
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
    return chapter_body(title)


def _book_table_names():
    return [book.table for book in BOOKS]


def sample_status():
    """Return the stored and expected size of the generated handbook sample."""
    group = Group.objects.filter(gr_id=GROUP_ID).first()
    boards = Board.objects.filter(group=group, bo_table__in=_book_table_names()) if group else Board.objects.none()
    return {
        "books": boards.count(),
        "chapters": Post.objects.filter(board__in=boards).count(),
        "expected_books": len(BOOKS),
        "expected_chapters": sum(len(titles) for book in BOOKS for _part, titles in book.parts),
    }


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
    existing_posts = list(Post.objects.filter(board=board))
    chapters = [(part, title) for part, titles in book.parts for title in titles]
    existing_titles = {post.wr_subject for post in existing_posts}
    missing = [(part, title) for part, title in chapters if title not in existing_titles]
    updated = 0
    for post in existing_posts:
        # Refresh only the previous repeated placeholder. Preserve administrator-authored text.
        if LEGACY_SAMPLE_MARKER in (post.wr_content or ""):
            post.wr_content = _chapter_body(post.wr_subject)
            post.save(update_fields=("wr_content",))
            updated += 1

    # A new post gets the smallest wr_num so that the newest comes first on a board list. A book is
    # read from its first chapter, so the chapters are written last to first.
    if not existing_posts:
        to_create = [(part, title, None) for part, title in reversed(missing)]
    else:
        # Append missing sample chapters after existing content without reordering edited chapters.
        last_num = max(post.wr_num for post in existing_posts)
        to_create = [(part, title, last_num + index + 1) for index, (part, title) in enumerate(missing)]

    for index, (part, title, wr_num) in enumerate(to_create):
        stamp = created_at - timedelta(minutes=index)
        if wr_num is None:
            wr_num = get_next_num(board_id=board.pk)
        post = Post.objects.create(
            board=board,
            wr_num=wr_num,
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
    return len(missing), updated


def _clear_config_cache():
    from . import config as site_config

    site_config.clear()


@transaction.atomic
def ensure_samples(*, stable_dates=False):
    """Create the sample manual (or complete it) and point the theme at it. Safe to run again."""
    group = _group()
    _check_tables_are_free(group)
    now = (
        datetime(2026, 10, 1, 12, 0, tzinfo=datetime_timezone.utc)
        if stable_dates
        else timezone.now()
    )
    created = 0
    updated = 0
    for order, book in enumerate(BOOKS, start=1):
        board = _board(group, order, book)
        created_count, updated_count = _chapters(board, book, now)
        created += created_count
        updated += updated_count
    Config.objects.update_or_create(name=DOCS_GROUP_KEY, defaults={"value": GROUP_ID})
    _clear_config_cache()
    return {
        "group": GROUP_ID,
        "books": len(BOOKS),
        "chapters_created": created,
        "chapters_updated": updated,
    }


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
