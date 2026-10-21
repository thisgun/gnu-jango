from django.conf import settings
from django.core import signing
from django.utils.cache import patch_cache_control
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.throttling import SimpleRateThrottle

from gnu_jango.site_search.feedback import record_click
from gnu_jango.site_search.indexing import unready_kinds
from gnu_jango.site_search.service import CANDIDATE_LIMIT, ranked_results
from gnu_jango.utils.lib import get_client_ip

from .authentication import SessionJWTAuthentication
from .response import api_error, api_response


class SearchThrottle(SimpleRateThrottle):
    scope = "site-search"

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        identity = user.pk if getattr(user, "is_authenticated", False) else get_client_ip(request)
        return self.cache_format % {"scope": self.scope, "ident": identity}


class ClickThrottle(SearchThrottle):
    scope = "search-click"


def _integer(value, default, maximum):
    try:
        return min(max(int(value), 1), maximum)
    except (TypeError, ValueError):
        return default


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([SessionJWTAuthentication, BasicAuthentication])
@throttle_classes([SearchThrottle])
def unified_search_view(request):
    query = str(request.query_params.get("q") or "").strip()
    if not 2 <= len(query) <= 200 or "\x00" in query:
        return api_error("검색어는 2~200자로 입력해 주세요.", code="invalid_query")
    result_type = request.query_params.get("type", "all")
    if result_type not in {"all", "post", "product", "document"}:
        return api_error("지원하지 않는 검색 종류입니다.", code="invalid_type")
    bo_table = str(request.query_params.get("bo_table") or "").strip()
    if "\x00" in bo_table or len(bo_table) > 100:
        return api_error("유효한 게시판 ID가 필요합니다.", code="invalid_board")
    kinds = {"all": ["post", "product", "page"], "post": ["post"], "product": ["product"], "document": ["post", "page"]}[result_type]
    missing = unready_kinds(kinds)
    if not getattr(settings, "G5_SEARCH_ENABLED", True) or missing:
        return api_error("통합 검색을 준비 중입니다. 기존 게시판 검색을 이용해 주세요.",
                         status=503, code="search_index_not_ready", details={"kinds": missing})
    limit = _integer(request.query_params.get("limit"), 20, 50)
    page = _integer(request.query_params.get("page"), 1, CANDIDATE_LIMIT)
    results, meta = ranked_results(request, query, result_type=result_type, bo_table=bo_table, page=page, limit=limit)
    response = api_response(data={"query": query, "results": results}, meta=meta)
    patch_cache_control(response, private=True, no_store=True)
    return response


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([SessionJWTAuthentication, BasicAuthentication])
@throttle_classes([ClickThrottle])
def search_click_view(request):
    token = request.data.get("token") if isinstance(request.data, dict) else None
    if not isinstance(token, str) or len(token) > 1024:
        return api_error("유효한 검색 결과가 필요합니다.", code="invalid_result")
    try:
        recorded = record_click(request, token)
    except (signing.BadSignature, ValueError, TypeError):
        return api_error("검색 결과가 만료되었거나 유효하지 않습니다.", code="invalid_result")
    if recorded is None:
        return api_error("검색 결과를 찾을 수 없습니다.", status=404, code="result_not_found")
    return api_response(data={"recorded": recorded})
