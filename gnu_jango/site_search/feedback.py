from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import salted_hmac

from gnu_jango.core.privacy import is_bot_user_agent
from gnu_jango.utils.lib import get_client_ip

from .models import SearchClickDaily

TOKEN_SALT = "site-search-click-v1"


def query_hash(query):
    return salted_hmac("site-search-query", " ".join(query.lower().split()), algorithm="sha256").hexdigest()


def click_token(query, document_id):
    if not getattr(settings, "G5_SEARCH_CLICK_LOG_ENABLED", True):
        return ""
    return signing.dumps({"q": query_hash(query), "d": document_id}, salt=TOKEN_SALT, compress=True)


def record_click(request, token):
    from .service import visible_documents

    payload = signing.loads(token, salt=TOKEN_SALT, max_age=900)
    if not isinstance(payload, dict) or not isinstance(payload.get("d"), int) or not isinstance(payload.get("q"), str):
        raise signing.BadSignature("Invalid search result")
    if len(payload["q"]) != 64:
        raise signing.BadSignature("Invalid query digest")
    docs, _ = visible_documents(request)
    document = docs.filter(pk=payload["d"]).first()
    if document is None:
        return None
    if (not getattr(settings, "G5_SEARCH_CLICK_LOG_ENABLED", True) or request.headers.get("DNT") == "1"
            or is_bot_user_agent(request.headers.get("User-Agent", ""))):
        return False
    user = getattr(request, "user", None)
    identity = f"user:{user.pk}" if getattr(user, "is_authenticated", False) else f"ip:{get_client_ip(request)}"
    day = timezone.localdate()
    digest = salted_hmac(TOKEN_SALT, f'{day}:{payload["q"]}:{document.pk}:{identity}', algorithm="sha256").hexdigest()
    # Only an HMAC is put in shared cache; no address/member id is persisted.
    if not cache.add(f"site-search-click:{digest}", True, int(timedelta(days=1).total_seconds())):
        return False
    with transaction.atomic():
        row, _ = SearchClickDaily.objects.get_or_create(query_hash=payload["q"], document=document, day=day)
        SearchClickDaily.objects.filter(pk=row.pk).update(count=F("count") + 1)
    return True
