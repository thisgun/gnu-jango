from rest_framework import status as drf_status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle

from .authentication import SessionJWTAuthentication as JWTAuthentication
from .response import api_error, api_response
from gnu_jango.docs_search.llm import generate_answer, llm_is_enabled
from gnu_jango.docs_search.service import docs_group_id, search_documents


class DocsAnswerRateThrottle(SimpleRateThrottle):
    """A second, tighter budget for answer=1 requests: each one may hold a worker until the
    configured model answers (up to G5_DOCS_LLM_TIMEOUT), while plain search returns at once."""

    scope = "docs-ask-answer"

    def get_cache_key(self, request, view):
        if request.query_params.get("answer") != "1":
            return None
        user = getattr(request, "user", None)
        ident = user.pk if getattr(user, "is_authenticated", False) else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


def _query_error(query):
    if len(query) < 2:
        return "질문은 두 글자 이상 입력해 주세요."
    if len(query) > 200:
        return "질문은 200자 이내로 입력해 주세요."
    return ""


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@throttle_classes([ScopedRateThrottle, DocsAnswerRateThrottle])
def docs_ask_view(request):
    query = str(request.query_params.get("q") or "").strip()
    error = _query_error(query)
    if error:
        return api_error(
            error,
            status=drf_status.HTTP_400_BAD_REQUEST,
            code="invalid_query",
            details={"q": error},
        )

    try:
        limit = min(max(int(request.query_params.get("limit", 5)), 1), 10)
    except (TypeError, ValueError):
        limit = 5
    results = search_documents(request, query, limit=limit) if docs_group_id() else []
    answer = None
    answer_reason = None
    if request.query_params.get("answer") == "1":
        answer, answer_reason = generate_answer(query, results)
    data = {
        "query": query,
        "results": results,
        "answer": answer,
        "answer_enabled": llm_is_enabled(),
    }
    if answer_reason:
        data["answer_reason"] = answer_reason
    return api_response(data=data)


docs_ask_view.cls.throttle_scope = "docs-ask"
