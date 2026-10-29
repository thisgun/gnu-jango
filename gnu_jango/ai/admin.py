import logging

from django.contrib import admin, messages
from unfold.admin import ModelAdmin

from . import conf, indexing, review_summaries
from .client import get_chat_provider, get_provider, semantic_search_enabled
from .models import Embedding, ReviewSummary
from .store import summary

logger = logging.getLogger(__name__)


def _pending(report, done_key):
    return report[done_key] + report["deferred"] + report["pruned"]


def embedding_backlog_message():
    """A warning while ``build_embeddings`` has work left (counted with a dry run, no endpoint call)."""
    if not semantic_search_enabled():
        return None
    provider = get_provider()
    try:
        backlog = {kind: _pending(indexing.build(kind, provider, dry_run=True), "would_embed") for kind in indexing.KINDS}
    except Exception:  # The status line must never break the admin page.
        logger.warning("Could not count the pending embeddings.", exc_info=True)
        return None
    waiting = ", ".join(f"{kind} {count}개" for kind, count in backlog.items() if count)
    if not waiting:
        return None
    return f"갱신 대기: {waiting}. 검색과 비슷한 상품에 아직 반영되지 않았습니다. manage.py build_embeddings 를 실행하세요."


def review_summary_backlog_message():
    """A warning while ``summarize_reviews`` has work left (counted with a dry run, no model call)."""
    provider = get_chat_provider()
    if provider is None:
        return None
    try:
        waiting = _pending(review_summaries.summarize(provider, dry_run=True), "would_summarize")
    except Exception:  # The status line must never break the admin page.
        logger.warning("Could not count the pending review summaries.", exc_info=True)
        return None
    if not waiting:
        return None
    return f"요약 대기: {waiting}개 상품. 후기가 바뀐 상품의 요약이 아직 예전 내용입니다. manage.py summarize_reviews 를 실행하세요."


def status_message():
    """One line for operators: on/off, the active model and the stored counts."""
    provider = get_provider()
    counts = ", ".join(f"{row['kind']} {row['count']}개 ({row['model']}, {row['dimensions']}차원)" for row in summary())
    if not semantic_search_enabled():
        state = "의미 검색이 꺼져 있습니다 (G5_AI_SEMANTIC_SEARCH, G5_AI_BASE_URL, G5_AI_EMBEDDING_MODEL)."
    else:
        state = f"의미 검색 사용 중: {provider.model} ({provider.dimensions}차원)."
    return f"{state} 저장된 임베딩: {counts or '없음'}. 갱신은 manage.py build_embeddings 로 합니다."


@admin.register(Embedding)
class EmbeddingAdmin(ModelAdmin):
    list_display = ("kind", "object_id", "board_id", "model", "dimensions", "updated_at")
    list_filter = ("kind", "model", "dimensions")
    search_fields = ("=object_id",)
    fields = ("kind", "object_id", "board_id", "model", "dimensions", "text_hash", "updated_at")
    readonly_fields = fields

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        # The vector itself is large and not shown; keep it out of the list query.
        return super().get_queryset(request).defer("embedding")

    def changelist_view(self, request, extra_context=None):
        self.message_user(request, status_message(), messages.INFO)
        # Counted on the plain list only: the count reads every source row, too much for each sort/page click.
        backlog = None if request.GET else embedding_backlog_message()
        if backlog:
            self.message_user(request, backlog, messages.WARNING)
        return super().changelist_view(request, extra_context)


def review_summary_status_message():
    provider = get_chat_provider()
    shown = "표시 중" if conf.review_summaries_requested() else "꺼짐 (G5_AI_REVIEW_SUMMARIES)"
    model = provider.model if provider else "설정 안 됨 (G5_AI_BASE_URL, G5_AI_CHAT_MODEL)"
    return (
        f"상품 화면 표시: {shown}. 채팅 모델: {model}. 승인된 후기가 {conf.review_summary_min_reviews()}개 이상인 "
        "판매 상품만 요약하며 갱신은 manage.py summarize_reviews 로 합니다. 잘못된 요약은 '숨김'으로 가립니다."
    )


@admin.register(ReviewSummary)
class ReviewSummaryAdmin(ModelAdmin):
    """Read-only except ``is_hidden``: an operator can hide a wrong or unfair summary from the page."""

    list_display = ("product_id", "review_count", "is_hidden", "model", "updated_at")
    list_filter = ("is_hidden", "model")
    list_editable = ("is_hidden",)
    search_fields = ("=product_id", "summary")
    fields = ("product_id", "summary", "is_hidden", "review_count", "model", "source_hash", "updated_at")
    readonly_fields = ("product_id", "summary", "review_count", "model", "source_hash", "updated_at")

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # A deleted summary is written again on the next run; hide it instead.
        return False

    def changelist_view(self, request, extra_context=None):
        self.message_user(request, review_summary_status_message(), messages.INFO)
        # Counted on the plain list only: one review query per product, too much for each sort/page click.
        backlog = None if request.GET else review_summary_backlog_message()
        if backlog:
            self.message_user(request, backlog, messages.WARNING)
        return super().changelist_view(request, extra_context)
