"""Settings, origin and member input helpers shared by the auth and member API modules."""

import ipaddress
import re
import urllib.parse

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.utils.html import strip_tags

from gnu_jango.config.models import Config
from gnu_jango.users.models import Profile

NICKNAME_MARKUP_CHARACTERS = set("<>\"'&\\")
EMAIL_INVALID_MESSAGE = "올바른 이메일 주소를 입력해주세요."
RESERVED_ID_MESSAGE = "이미 예약된 단어로 사용할 수 없는 회원아이디 입니다."
RESERVED_NICK_MESSAGE = "이미 예약된 단어로 사용할 수 없는 닉네임 입니다."
NICKNAME_INVALID_MESSAGE = "닉네임에 사용할 수 없는 문자가 포함되어 있습니다."

def _config_value(name, default=""):
    try:
        value = Config.objects.filter(name=name).values_list("value", flat=True).first()
    except Exception:
        return default
    if value is None:
        return default
    return str(value)


def _setting_value(name, default=""):
    value = getattr(settings, name, default)
    if value is None:
        return default
    return str(value).strip()


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "y"}


def _current_origin(request):
    return f"{request.scheme}://{request.get_host()}"


def _normalize_origin(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urllib.parse.urlparse(raw)
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{parsed.scheme.lower()}://{host}{':' + str(port) if port else ''}"


def _is_loopback_host(hostname):
    if not hostname:
        return False
    hostname = hostname.lower().strip("[]")
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        # a DNS name such as 127.evil.example is not loopback
        return False


def _iter_configured_origins(value):
    if isinstance(value, str):
        values = value.replace("|", ",").split(",")
    else:
        values = value or []
    for item in values:
        origin = _normalize_origin(item)
        if origin:
            yield origin


def _form_text(data, *keys):
    """The first non-empty request field of keys as text, and whether a value of another type (number,
    list, object, boolean) was sent instead: a JSON body is not limited to strings."""
    for key in keys:
        value = data.get(key)
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            return "", True
        return value, False
    return "", False


def _has_control_character(value):
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _strip_markup(value):
    """clean_xss_tags(): tags are removed and no stray angle bracket is kept."""
    return strip_tags(value).replace("<", "").replace(">", "").strip()


def _prohibited_words():
    """cf_prohibit_id: the reserved words, one list for ids and nicknames (comma or line separated)."""
    raw = _config_value("cf_prohibit_id", "")
    return {word.strip().lower() for word in re.split(r"[,\r\n]", raw) if word.strip()}


def reserved_member_id_error(mb_id):
    """reserve_mb_id (lib/register.lib.php): an id on the cf_prohibit_id list, in any case. Gnuboard5
    matches the id anywhere in the list text; the port matches whole words, so "min" stays free when
    "admin" is reserved."""
    return RESERVED_ID_MESSAGE if mb_id and mb_id.strip().lower() in _prohibited_words() else ""


def reserved_nickname_error(nickname):
    """reserve_mb_nick (lib/register.lib.php): the same list as the ids."""
    return RESERVED_NICK_MESSAGE if nickname and nickname.strip().lower() in _prohibited_words() else ""


def nickname_rule_error(nickname):
    """register_form_update.php rules for a nickname, at signup and on a change: the column limit, no
    markup (the nickname is printed on every post; valid_mb_nick allows letters and digits only, the
    port keeps the spaces and dashes its members already use but refuses markup characters) and no
    reserved word."""
    limit = Profile._meta.get_field("nickname").max_length
    if limit and len(nickname) > limit:
        return f"닉네임은 {limit}자 이하로 입력해주세요."
    if NICKNAME_MARKUP_CHARACTERS.intersection(nickname) or _has_control_character(nickname):
        return NICKNAME_INVALID_MESSAGE
    return reserved_nickname_error(nickname)


def prohibited_email_error(email):
    """prohibit_mb_email (lib/register.lib.php): a domain on the cf_prohibit_email list, one per line."""
    domain = email.rsplit("@", 1)[-1].strip() if "@" in email else ""
    if not domain:
        return ""
    blocked = {line.strip().lower() for line in _config_value("cf_prohibit_email", "").splitlines() if line.strip()}
    return f"{domain} 메일은 사용할 수 없습니다." if domain.lower() in blocked else ""


def email_rule_error(email, *, check_prohibited=True):
    """valid_mb_email and prohibit_mb_email: a well-formed address (Django's validator also refuses line
    breaks, so no header can ride into the certify mail) on a domain that is not barred."""
    try:
        validate_email(email)
    except DjangoValidationError:
        return EMAIL_INVALID_MESSAGE
    return prohibited_email_error(email) if check_prohibited else ""
