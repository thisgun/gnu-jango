import hashlib
import logging
import re
from dataclasses import dataclass
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Max

from gnu_jango.api.access import readable_post_queryset
from gnu_jango.api.v1_board import _excerpt_post_ids
from gnu_jango.api.v1_community import _searchable_boards
from gnu_jango.bbs.models import Board, Post
from gnu_jango.bbs.utils import get_pretty_url
from gnu_jango.config import config as site_config

from .parser import parse_manual_html
from .ranking import bm25_scores
from .tokenizer import tokenize

logger = logging.getLogger(__name__)
_REVISION_PREFIX = "docs-ask:revision:v1:"
_MEMORY_INDEX = {}
_MAX_SNIPPET_LENGTH = 360


@dataclass(frozen=True)
class SearchDocument:
    board_id: int
    post_id: int
    bo_table: str
    book: str
    part: str
    chapter: str
    section: str
    anchor: str
    text: str
    terms: tuple[str, ...]
    url: str


@dataclass(frozen=True)
class SearchIndex:
    fingerprint: tuple
    documents: tuple[SearchDocument, ...]
    posts_by_board: dict


def docs_group_id():
    try:
        configured = site_config.get_all().get("cf_docs_group")
    except Exception:
        logger.warning("Could not read the handbook group setting.", exc_info=True)
        configured = ""
    return str(configured or getattr(settings, "G5_DEFAULT_DOCS_GROUP", "") or "").strip()


def _revision_key(group_id):
    digest = hashlib.sha256(group_id.encode("utf-8")).hexdigest()[:24]
    return f"{_REVISION_PREFIX}{digest}"


def index_revision(group_id):
    try:
        return int(cache.get(_revision_key(group_id), 0) or 0)
    except Exception:
        logger.warning("Could not read the handbook search revision from cache.", exc_info=True)
        return 0


def bump_index_revision(group_id):
    """Invalidate warm workers after a committed chapter save or delete."""
    if not group_id:
        return
    _MEMORY_INDEX.pop(group_id, None)
    key = _revision_key(group_id)
    try:
        if not cache.add(key, 1, timeout=None):
            cache.incr(key)
    except Exception:
        logger.warning("Could not bump the handbook search revision.", exc_info=True)


def _book_label(subject, table):
    subject = (subject or "").strip() or table
    match = re.match(r"^.+?\s*·\s*(.+)$", subject)
    return (match.group(1) if match else subject).strip()


def _weighted_terms(post, paragraph):
    body_terms = tokenize(paragraph.text)
    chapter_terms = tokenize(post.wr_subject or "")
    section_terms = tokenize(paragraph.section)
    part_terms = tokenize(post.ca_name or "")
    book_terms = tokenize(post.board.bo_subject or "")
    # Repeating the small metadata fields makes their matches count more than body-only matches.
    return tuple(
        body_terms
        + chapter_terms * 3
        + section_terms * 2
        + part_terms * 2
        + book_terms
    )


def _corpus_fingerprint(group_id, boards, posts_queryset):
    stats = posts_queryset.aggregate(
        count=Count("pk"),
        last_id=Max("pk"),
        last_updated=Max("wr_last"),
        last_created=Max("wr_datetime"),
    )
    board_state = tuple(
        (
            board.pk,
            board.bo_table,
            board.bo_subject,
            board.bo_order,
            board.bo_category_list,
            board.bo_list_level,
            board.bo_read_level,
            board.bo_read_point,
            board.bo_use_search,
        )
        for board in boards
    )
    return group_id, board_state, tuple(sorted(stats.items())), index_revision(group_id)


def get_search_index(group_id=None):
    group_id = str(group_id or docs_group_id()).strip()
    if not group_id:
        return SearchIndex((), (), {})

    boards = list(
        Board.objects.filter(group__gr_id=group_id, bo_use_search=True)
        .order_by("bo_order", "bo_subject", "pk")
    )
    board_ids = [board.pk for board in boards]
    posts_queryset = Post.objects.filter(board_id__in=board_ids, wr_reply="")
    fingerprint = _corpus_fingerprint(group_id, boards, posts_queryset)
    cached = _MEMORY_INDEX.get(group_id)
    if cached and cached.fingerprint == fingerprint:
        return cached

    posts = list(
        posts_queryset.select_related("board", "board__group")
        .order_by("board__bo_order", "board__bo_subject", "wr_num", "pk")
    )
    posts_by_board = {}
    documents = []
    for post in posts:
        posts_by_board.setdefault(post.board_id, []).append(post)
        for paragraph in parse_manual_html(post.wr_content):
            terms = _weighted_terms(post, paragraph)
            if not terms:
                continue
            anchor = paragraph.anchor
            url = get_pretty_url(post.board.bo_table, post.legacy_wr_id or post.pk)
            if anchor:
                url = f"{url}#{quote(anchor, safe='-')}"
            documents.append(
                SearchDocument(
                    board_id=post.board_id,
                    post_id=post.pk,
                    bo_table=post.board.bo_table,
                    book=_book_label(post.board.bo_subject, post.board.bo_table),
                    part=(post.ca_name or "").strip(),
                    chapter=(post.wr_subject or "").strip(),
                    section=paragraph.section,
                    anchor=anchor,
                    text=paragraph.text,
                    terms=terms,
                    url=url,
                )
            )

    index = SearchIndex(fingerprint, tuple(documents), posts_by_board)
    # One active manual per worker keeps serverless memory bounded when sites change their group.
    _MEMORY_INDEX.clear()
    _MEMORY_INDEX[group_id] = index
    return index


def _query_highlights(snippet, query_terms):
    lower = snippet.lower()
    spans = []
    for term in set(query_terms):
        if len(term) < 2:
            continue
        start = 0
        while True:
            found = lower.find(term.lower(), start)
            if found < 0:
                break
            spans.append((found, found + len(term)))
            start = found + 1
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    # The browser's String.slice uses UTF-16 offsets; return those so Korean and emoji align.
    def offset(value):
        return len(snippet[:value].encode("utf-16-le")) // 2

    return [[offset(start), offset(end)] for start, end in merged[:30]]


def _snippet(text, query_terms):
    if len(text) <= _MAX_SNIPPET_LENGTH:
        return text
    lower = text.lower()
    positions = [lower.find(term.lower()) for term in query_terms if len(term) >= 2 and lower.find(term.lower()) >= 0]
    center = min(positions) if positions else 0
    start = max(0, min(center - 90, len(text) - _MAX_SNIPPET_LENGTH))
    end = start + _MAX_SNIPPET_LENGTH
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def _visible_post_ids(request, index):
    searchable = _searchable_boards(request).filter(group__gr_id=docs_group_id())
    allowed_board_ids = set(searchable.values_list("pk", flat=True))
    visible_ids = set()
    for board_id, posts in index.posts_by_board.items():
        if board_id not in allowed_board_ids or not posts:
            continue
        board = posts[0].board
        excerptable = _excerpt_post_ids(request, board, posts)
        # The existing search deliberately substitutes a fixed label for secret-post bodies.
        # Question search needs body paragraphs, so it omits secret posts completely.
        visible_ids.update(
            post.pk
            for post in posts
            if post.pk in excerptable and "secret" not in (post.wr_option or "")
        )
    return visible_ids


def search_documents(request, query, *, limit=5):
    terms = tokenize(query)
    if not terms:
        return []
    index = get_search_index()
    visible_ids = _visible_post_ids(request, index)
    candidates = [doc for doc in index.documents if doc.post_id in visible_ids]
    if not candidates:
        return []
    scores = bm25_scores([doc.terms for doc in candidates], terms)
    # Keep one result per chapter. Paragraph-level ranking otherwise lets a long
    # chapter occupy several of the first slots and hides other relevant chapters.
    chapter_matches = {}
    for position, (doc, score) in enumerate(zip(candidates, scores)):
        if score <= 0:
            continue
        matches = chapter_matches.setdefault(doc.post_id, [])
        matches.append((score, position, doc))
    ranked = []
    for matches in chapter_matches.values():
        matches.sort(key=lambda row: (-row[0], row[1]))
        best_score, position, doc = matches[0]
        supporting_score = sum(item[0] for item in matches[1:3])
        ranked.append((position, doc, best_score + min(best_score * 0.3, supporting_score * 0.2)))
    ranked.sort(key=lambda row: (-row[2], row[0]))
    results = []
    for _, doc, score in ranked:
        snippet = _snippet(doc.text, terms)
        results.append(
            {
                "bo_table": doc.bo_table,
                "wr_id": doc.post_id,
                "book": doc.book,
                "part": doc.part,
                "chapter": doc.chapter,
                "section": doc.section,
                "anchor": doc.anchor,
                "url": doc.url,
                "snippet": snippet,
                "highlights": _query_highlights(snippet, terms),
                "score": round(score, 6),
            }
        )
        if len(results) >= limit:
            break
    return results


def clear_memory_cache():
    _MEMORY_INDEX.clear()
