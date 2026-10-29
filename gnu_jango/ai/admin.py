from django.contrib import admin, messages
from unfold.admin import ModelAdmin

from .client import get_provider, semantic_search_enabled
from .models import Embedding
from .store import summary


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
        return super().changelist_view(request, extra_context)
