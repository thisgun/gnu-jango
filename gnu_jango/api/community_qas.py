"""1:1 inquiries of the community API."""

import json
import os
import re
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename
from rest_framework import status as drf_status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import api_view, authentication_classes, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from .authentication import SessionJWTAuthentication as JWTAuthentication

from gnu_jango.bbs.models import validate_upload_file_content
from gnu_jango.config.models import Config
from gnu_jango.shop.models import ShopQA

from .response import api_error, api_response
from .v1_auth import _auth_user_from_request
from .v1_board import _datetime

from .community_common import (
    GENERAL_QA_PRODUCT_ID,
    QA_META_CONFIG_PREFIX,
    _filter_qa_queryset,
    _general_qa_product,
    _paginate,
    _require_user,
    _safe_int,
    _text,
)


QA_SUBJECT_MAX_LENGTH = 255  # qawrite_update.php: substr(trim($_POST['qa_subject']), 0, 255)
QA_CONTENT_MAX_LENGTH = 65536  # qawrite_update.php: substr(trim($_POST['qa_content']), 0, 65536)
QA_SUBJECT_REQUIRED_MESSAGE = "제목을 입력하세요."
QA_CONTENT_REQUIRED_MESSAGE = "내용을 입력하세요."
QA_DISALLOWED_EXTENSION_MESSAGE = "허용되지 않는 파일 확장자입니다."


def _qa_subject_value(value):
    return _text(value).strip()[:QA_SUBJECT_MAX_LENGTH].strip()


def _qa_content_value(value):
    return _text(value).strip()[:QA_CONTENT_MAX_LENGTH]


def _qa_required_error(subject, content):
    """qawrite_update.php: a blank subject or content is refused, both named at once."""
    if subject and content:
        return None
    # The field messages keep the wording the frontend and existing clients already get; the
    # top-level message is the Gnuboard5 alert.
    details = {
        "qa_subject": "" if subject else "Subject is required.",
        "qa_content": "" if content else "Content is required.",
    }
    alerts = [message for ok, message in ((subject, QA_SUBJECT_REQUIRED_MESSAGE), (content, QA_CONTENT_REQUIRED_MESSAGE)) if not ok]
    return api_error(
        " ".join(alerts),
        status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="validation_error",
        details=details,
    )


def _qa_config_payload():
    return {
        "qa_title": "1:1 Q&A",
        "qa_category": "general",
        "categories": ["general"],
        "qa_use_email": 1,
        "qa_req_email": 0,
        "qa_use_hp": 1,
        "qa_req_hp": 0,
        "qa_use_sms": 0,
        "qa_subject_len": 255,
        "qa_page_rows": 10,
        "qa_mobile_page_rows": 10,
        "qa_insert_content": "",
        "qa_content_head": "",
        "qa_content_tail": "",
        "qa_mobile_content_head": "",
        "qa_mobile_content_tail": "",
    }


def _qa_can_manage(user, item):
    return bool(user and (user.is_staff or user.is_superuser or item.user_id == user.id))


def _qa_meta_config_name(qa_id):
    return f"{QA_META_CONFIG_PREFIX}{qa_id}"[:50]


def _qa_empty_meta():
    return {"files": [{}, {}], "parent": 0, "related": 0, "answer_subject": ""}


def _qa_normalize_meta(value):
    meta = value if isinstance(value, dict) else {}
    files = meta.get("files")
    if not isinstance(files, list):
        files = []
    normalized_files = []
    for file_meta in files[:2]:
        normalized_files.append(file_meta if isinstance(file_meta, dict) else {})
    while len(normalized_files) < 2:
        normalized_files.append({})
    return {
        "files": normalized_files,
        "parent": _safe_int(meta.get("parent"), 0),
        "related": _safe_int(meta.get("related"), 0),
        "answer_subject": str(meta.get("answer_subject") or ""),
    }


def _qa_load_meta(qa_id):
    raw = Config.objects.filter(name=_qa_meta_config_name(qa_id)).values_list("value", flat=True).first()
    if not raw:
        return _qa_empty_meta()
    try:
        return _qa_normalize_meta(json.loads(raw))
    except (TypeError, ValueError):
        return _qa_empty_meta()


def _qa_save_meta(qa_id, meta):
    Config.objects.update_or_create(
        name=_qa_meta_config_name(qa_id),
        defaults={"value": json.dumps(_qa_normalize_meta(meta), ensure_ascii=False)},
    )


def _qa_delete_file(path):
    if not path:
        return
    try:
        if default_storage.exists(path):
            default_storage.delete(path)
    except OSError:
        pass


def _qa_delete_meta(qa_id):
    meta = _qa_load_meta(qa_id)
    for file_meta in meta.get("files", []):
        _qa_delete_file(file_meta.get("path", ""))
    Config.objects.filter(name=_qa_meta_config_name(qa_id)).delete()


def _qa_file_slot(meta, slot):
    files = meta.get("files") if isinstance(meta, dict) else []
    file_meta = files[slot - 1] if isinstance(files, list) and len(files) >= slot else {}
    if not isinstance(file_meta, dict):
        return {"path": "", "name": "", "url": ""}
    path = str(file_meta.get("path") or "")
    name = str(file_meta.get("name") or "")
    url = str(file_meta.get("url") or "")
    if path and not url:
        url = default_storage.url(path)
    return {"path": path, "name": name, "url": url}


def _qa_uploaded_file(request, slot):
    for key in (f"bf_file[{slot}]", f"bf_file_{slot}", f"qa_file{slot}", f"file{slot}"):
        uploaded = request.FILES.get(key)
        if uploaded:
            return uploaded
    return None


def _qa_delete_file_requested(data, slot):
    for key in (f"bf_file_del[{slot}]", f"bf_file_del_{slot}", f"qa_file{slot}_del", f"delete_file{slot}"):
        value = data.get(key)
        if str(value).strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


# Script and markup types never stored, in any position of a multi-part name (a.php.jpg, a.svg.)
QA_ACTIVE_EXTENSION_RE = re.compile(
    r"\.(?:php\d?|phtml|pht|phtm|phar|inc|html?|xhtml|xht|shtml|svgz?|xml|xsl|xslt|mht|mhtml|htc|"
    r"js|mjs|cgi|pl|py|rb|sh|bat|cmd|exe|com|jsp|jspx|asp|aspx|ashx|war|jar|htaccess)(?:[. :]|$)",
    re.IGNORECASE,
)


def _qa_validate_upload(uploaded):
    """qawrite_update.php refuses active content ("허용되지 않는 파일 확장자입니다.") but takes other
    documents (.hwp, .txt, .pptx, ...); known types must also look like what they claim to be."""
    name = str(getattr(uploaded, "name", "") or "")
    base = name.replace("\\", "/").rsplit("/", 1)[-1].rstrip(" .")
    if not base or re.search(r"[\x00-\x1f\x7f]", base) or QA_ACTIVE_EXTENSION_RE.search(base) or base.startswith("."):
        raise DjangoValidationError(QA_DISALLOWED_EXTENSION_MESSAGE)
    validate_upload_file_content(uploaded)


def _qa_apply_attachments(item, request, meta=None):
    meta = _qa_normalize_meta(meta or _qa_load_meta(item.pk))
    data = _qa_request_data(request)
    files = meta["files"]
    changed = False

    for slot in (1, 2):
        index = slot - 1
        if _qa_delete_file_requested(data, slot):
            _qa_delete_file(files[index].get("path", ""))
            files[index] = {}
            changed = True

        uploaded = _qa_uploaded_file(request, slot)
        if not uploaded:
            continue

        _qa_validate_upload(uploaded)
        _qa_delete_file(files[index].get("path", ""))
        original_name = os.path.basename(getattr(uploaded, "name", "") or f"qa-file-{slot}")
        safe_name = get_valid_filename(original_name) or f"qa-file-{slot}"
        path = default_storage.save(
            os.path.join("shop", "qas", str(item.pk), f"{uuid.uuid4().hex}_{safe_name}"),
            uploaded,
        )
        files[index] = {"path": path, "name": original_name, "url": default_storage.url(path)}
        changed = True

    if changed or meta.get("parent") or meta.get("related"):
        meta["files"] = files
        _qa_save_meta(item.pk, meta)
    return meta


def _qa_related_questions(item, request, meta):
    related_id = _safe_int(meta.get("related"), 0) or item.pk
    related_ids = []
    for name, value in Config.objects.filter(name__startswith=QA_META_CONFIG_PREFIX).values_list("name", "value"):
        qa_id = _safe_int(name[len(QA_META_CONFIG_PREFIX) :], -1)
        if qa_id < 1:
            continue
        try:
            row_meta = _qa_normalize_meta(json.loads(value))
        except (TypeError, ValueError):
            continue
        if qa_id != item.pk and _safe_int(row_meta.get("related"), 0) == related_id:
            related_ids.append(qa_id)

    if not related_ids:
        return []
    queryset = (
        ShopQA.objects.select_related("product", "user")
        .filter(pk__in=related_ids, product_id=GENERAL_QA_PRODUCT_ID)
        .order_by("iq_time", "pk")
    )
    return [_qa_payload(row, request, include_related=False) for row in queryset]


def _qa_answer_payload(item, request):
    user = _auth_user_from_request(request)
    can_manage = bool(user and (user.is_staff or user.is_superuser))
    meta = _qa_load_meta(item.pk)
    return {
        "qa_id": item.pk,
        "qa_num": item.pk,
        "qa_parent": item.pk,
        "qa_related": 0,
        "mb_id": "admin" if item.iq_answer else "",
        "qa_name": "Admin" if item.iq_answer else "",
        "qa_email": "",
        "qa_hp": "",
        "qa_type": 1,
        "qa_category": "general",
        "qa_email_recv": 0,
        "qa_sms_recv": 0,
        "qa_html": 0,
        "qa_subject": meta.get("answer_subject") or "RE: %s" % (item.iq_subject or ""),
        "qa_content": item.iq_answer or "",
        "qa_status": 1 if item.iq_answer else 0,
        "qa_file1": "",
        "qa_source1": "",
        "qa_file2": "",
        "qa_source2": "",
        "qa_file1_url": "",
        "qa_file2_url": "",
        "qa_datetime": _datetime(item.iq_time),
        "can_edit": can_manage,
        "can_delete": can_manage,
        "answer": None,
        "related_questions": [],
    }


def _qa_payload(item, request, include_related=True):
    user = _auth_user_from_request(request)
    can_manage = _qa_can_manage(user, item)
    can_change = bool(can_manage and (user.is_staff or user.is_superuser or not item.iq_answer))
    meta = _qa_load_meta(item.pk)
    file1 = _qa_file_slot(meta, 1)
    file2 = _qa_file_slot(meta, 2)
    return {
        "qa_id": item.pk,
        "qa_num": item.pk,
        "qa_parent": meta.get("parent", 0),
        "qa_related": meta.get("related", 0),
        "mb_id": item.mb_id or (item.user.get_username() if item.user_id else ""),
        "qa_name": item.iq_name or item.mb_nick or item.mb_id,
        "qa_email": item.iq_email or "",
        "qa_hp": item.iq_hp or "",
        "qa_type": 0,
        "qa_category": "general",
        "qa_email_recv": 1 if item.iq_email else 0,
        "qa_sms_recv": 0,
        "qa_html": 0,
        "qa_subject": item.iq_subject or "",
        "qa_content": item.iq_question or "",
        "qa_status": 1 if item.iq_answer else 0,
        "qa_file1": file1["path"],
        "qa_source1": file1["name"],
        "qa_file2": file2["path"],
        "qa_source2": file2["name"],
        "qa_file1_url": file1["url"],
        "qa_file2_url": file2["url"],
        "qa_datetime": _datetime(item.iq_time),
        # Same rule as PATCH: staff may still edit an answered inquiry, its owner may not.
        "can_edit": can_change,
        "can_delete": can_change,
        "answer": _qa_answer_payload(item, request) if item.iq_answer else None,
        "related_questions": _qa_related_questions(item, request, meta) if include_related else [],
    }


def _qa_queryset_for_user(request):
    user, error = _require_user(request)
    if error:
        return None, None, error

    queryset = ShopQA.objects.select_related("product", "user").filter(product_id=GENERAL_QA_PRODUCT_ID)
    if request.query_params.get("scope") == "admin":
        if not (user.is_staff or user.is_superuser):
            return None, None, api_error(
                "Permission denied.",
                status=drf_status.HTTP_403_FORBIDDEN,
                code="permission_denied",
            )
    else:
        queryset = queryset.filter(user=user)
    return user, queryset, None


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def qas_config_view(request):
    return api_response(data=_qa_config_payload())


def _qa_request_data(request):
    return request.data if hasattr(request.data, "get") else {}


def _qa_item_for_request(request, qa_id):
    user, error = _require_user(request)
    if error:
        return None, None, error

    item = (
        ShopQA.objects.select_related("product", "user")
        .filter(pk=qa_id, product_id=GENERAL_QA_PRODUCT_ID)
        .first()
    )
    if not item:
        return None, None, api_error("Q&A not found.", status=drf_status.HTTP_404_NOT_FOUND, code="qa_not_found")
    if not (user.is_staff or user.is_superuser or item.user_id == user.id):
        return None, None, api_error(
            "Permission denied.",
            status=drf_status.HTTP_403_FORBIDDEN,
            code="permission_denied",
        )
    return user, item, None


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([JSONParser, FormParser, MultiPartParser])
def qas_view(request):
    if request.method == "GET":
        _, queryset, error = _qa_queryset_for_user(request)
        if error:
            return error
        queryset = _filter_qa_queryset(request, queryset)
        page, meta = _paginate(request, queryset, default_per_page=10, max_per_page=100)
        return api_response(data=[_qa_payload(item, request) for item in page], meta=meta)

    user, error = _require_user(request)
    if error:
        return error

    data = _qa_request_data(request)
    subject = _qa_subject_value(data.get("qa_subject"))
    content = _qa_content_value(data.get("qa_content"))
    required_error = _qa_required_error(subject, content)
    if required_error:
        return required_error

    reply_to = _safe_int(data.get("qa_reply_to"), 0)
    related_id = 0
    if reply_to:
        parent_item = (
            ShopQA.objects.select_related("product", "user")
            .filter(pk=reply_to, product_id=GENERAL_QA_PRODUCT_ID)
            .first()
        )
        if not parent_item:
            return api_error("Q&A not found.", status=drf_status.HTTP_404_NOT_FOUND, code="qa_not_found")
        if not (user.is_staff or user.is_superuser or parent_item.user_id == user.id):
            return api_error(
                "Permission denied.",
                status=drf_status.HTTP_403_FORBIDDEN,
                code="permission_denied",
            )
        parent_meta = _qa_load_meta(parent_item.pk)
        related_id = _safe_int(parent_meta.get("related"), 0) or parent_item.pk

    profile = getattr(user, "profile", None)
    item = ShopQA.objects.create(
        product=_general_qa_product(),
        user=user,
        mb_id=user.get_username(),
        mb_nick=getattr(profile, "nickname", "") or user.get_username(),
        iq_name=getattr(profile, "realname", "") or user.get_full_name() or user.get_username(),
        iq_subject=subject,
        iq_question=content,
        iq_email=str(data.get("qa_email") or user.email or ""),
        iq_hp=str(data.get("qa_hp") or ""),
    )
    meta = _qa_empty_meta()
    if reply_to:
        meta["parent"] = item.pk
        meta["related"] = related_id
    try:
        _qa_apply_attachments(item, request, meta)
    except DjangoValidationError as exc:
        item.delete()
        return api_error(
            "Invalid upload.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="invalid_upload",
            details={"file": [str(message) for message in exc.messages]},
        )
    return api_response(data=_qa_payload(item, request), status=drf_status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([JSONParser, FormParser, MultiPartParser])
def qa_detail_view(request, qa_id):
    user, item, error = _qa_item_for_request(request, qa_id)
    if error:
        return error

    if request.method == "DELETE":
        if not (user.is_staff or user.is_superuser or not item.iq_answer):
            return api_error(
                "Answered Q&A items cannot be deleted by the member.",
                status=drf_status.HTTP_403_FORBIDDEN,
                code="answered_qa_locked",
            )
        _qa_delete_meta(item.pk)
        item.delete()
        return api_response(data={"deleted": True, "qa_id": qa_id})

    if request.method == "PATCH":
        if not (user.is_staff or user.is_superuser or not item.iq_answer):
            return api_error(
                "Answered Q&A items cannot be edited by the member.",
                status=drf_status.HTTP_403_FORBIDDEN,
                code="answered_qa_locked",
            )
        data = _qa_request_data(request)
        # Only the fields sent are checked, so an attachment-only edit of an old row still works.
        subject = _qa_subject_value(data.get("qa_subject")) if "qa_subject" in data else None
        content = _qa_content_value(data.get("qa_content")) if "qa_content" in data else None
        required_error = _qa_required_error(subject != "", content != "")
        if required_error:
            return required_error
        if subject is not None:
            item.iq_subject = subject
        if content is not None:
            item.iq_question = content
        if "qa_email" in data:
            item.iq_email = str(data.get("qa_email") or "")
        if "qa_hp" in data:
            item.iq_hp = str(data.get("qa_hp") or "")
        item.save()
        try:
            _qa_apply_attachments(item, request)
        except DjangoValidationError as exc:
            return api_error(
                "Invalid upload.",
                status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="invalid_upload",
                details={"file": [str(message) for message in exc.messages]},
            )

    return api_response(data=_qa_payload(item, request))


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([JSONParser, FormParser, MultiPartParser])
def qa_answer_view(request, qa_id):
    user, item, error = _qa_item_for_request(request, qa_id)
    if error:
        return error
    if not (user.is_staff or user.is_superuser):
        return api_error("Permission denied.", status=drf_status.HTTP_403_FORBIDDEN, code="permission_denied")

    data = _qa_request_data(request)
    content = str(data.get("qa_content") or "").strip()
    if not content:
        return api_error(
            "Validation failed.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            details={"qa_content": "Answer content is required."},
        )
    item.iq_answer = content
    item.save(update_fields=["iq_answer"])
    subject = str(data.get("qa_subject") or "").strip() or "RE: %s" % (item.iq_subject or "")
    meta = _qa_load_meta(item.pk)
    meta["answer_subject"] = subject
    _qa_save_meta(item.pk, meta)
    return api_response(data=_qa_payload(item, request))
