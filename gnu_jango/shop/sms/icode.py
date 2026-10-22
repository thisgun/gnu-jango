"""iCode (아이코드) SMS gateway, after youngcart's lib/icode.sms.lib.php and lib/icode.lms.lib.php.

Two protocols exist and both are raw TCP sockets, not HTTP:

* the token ("JSON") version that iCode issues today: the packet is ``"06" + 4-digit length +
  JSON {key, tel, cb, msg, title, date}`` sent to ICODE_JSON_SOCKET_HOST:ICODE_JSON_SOCKET_PORT
  (211.172.232.124:9201 in extend/sms5.extend.php). One protocol carries SMS (up to 90 bytes)
  and LMS (up to 2000 bytes, with a title). The reply starts with ``"0225  00" + tel padded to
  12`` followed by an 11-character message id; any other code in bytes 6-8 is a refusal.
* the legacy ID/password version (``"01144 "`` fixed-width EUC-KR packets, SMS only here).

Credentials only come from the server environment (Django settings read from env vars) and are
never stored in Config rows or shown in the admin. The functions return an ``ICodeSendResult``
and do not raise for gateway or network failures; only a missing configuration raises
``ICodeConfigurationError`` so callers can tell "not set up" apart from "refused".
"""

from dataclasses import dataclass
import json
import re
import socket

from django.conf import settings

ICODE_JSON_DEFAULT_HOST = "211.172.232.124"
ICODE_JSON_DEFAULT_PORT = 9201
SMS_MAX_BYTES = 90  # token version: up to 90 bytes is an SMS
LEGACY_SMS_MAX_BYTES = 80  # icode.sms.lib.php cut_char($msg, 80)
LMS_MAX_BYTES = 2000  # G5_ICODE_JSON_MAX_LENGTH
LMS_SUBJECT_MAX_BYTES = 30
# tight: the texts go out on the request thread (see shop/sms/service.py)
CONNECT_TIMEOUT_SECONDS = 2
READ_TIMEOUT_SECONDS = 3
TOKEN_RESPONSE_LENGTH = 31  # "0225  00" + tel(12) + message id(11)
LEGACY_RESPONSE_LENGTH = 29
MAX_PACKET_BODY = 9999  # the length field has four digits


class ICodeConfigurationError(RuntimeError):
    """Raised when the iCode environment configuration is incomplete."""


@dataclass(frozen=True)
class ICodeSendResult:
    status: str  # accepted | rejected | unknown
    provider_code: str = ""
    error_text: str = ""
    message_type: str = "SMS"


def provider_enabled():
    """G5_SMS_PROVIDER: empty or ``icode`` lets iCode send; anything else (``disabled``) stops it."""
    return str(getattr(settings, "G5_SMS_PROVIDER", "") or "").strip().lower() in {"", "icode"}


def token_key():
    return str(getattr(settings, "G5_ICODE_TOKEN_KEY", "") or "").strip()


def _legacy_values():
    return (
        str(getattr(settings, "G5_ICODE_ID", "") or "").strip(),
        str(getattr(settings, "G5_ICODE_PASSWORD", "") or "").strip(),
        str(getattr(settings, "G5_ICODE_SERVER", "") or "").strip(),
    )


def credential_status():
    """Which iCode credentials the environment provides, as booleans only (never the values)."""
    has_token = bool(token_key())
    has_legacy = all(_legacy_values())
    mode = "token" if has_token else "legacy" if has_legacy else "missing"
    enabled = provider_enabled()
    return {
        "provider_enabled": enabled,
        "has_token": has_token,
        "has_legacy": has_legacy,
        "mode": mode,
        "ready": enabled and mode != "missing",
    }


# --- message helpers ------------------------------------------------------------------------


def message_bytes(text):
    """The byte count iCode bills by: 1 for ASCII, 2 for anything else (youngcart byte_check)."""
    return sum(1 if ord(character) < 0x80 else 2 for character in str(text or ""))


def cut_to_bytes(text, limit):
    """``text`` shortened to ``limit`` bytes without splitting a character (CutCharUtf8)."""
    total = 0
    kept = []
    for character in str(text or ""):
        size = 1 if ord(character) < 0x80 else 2
        if total + size > limit:
            break
        kept.append(character)
        total += size
    return "".join(kept)


def normalize_newlines(text):
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def _phone_digits(value):
    digits = re.sub(r"\D+", "", str(value or ""))
    if not re.fullmatch(r"01[0-9]{8,9}", digits):
        raise ValueError("iCode SMS requires a valid South Korean mobile number.")
    return digits


def _callback_digits(value):
    digits = re.sub(r"\D+", "", str(value or ""))
    if not 8 <= len(digits) <= 11:
        raise ValueError("A valid registered callback number is required.")
    return digits


def normalize_mobile(value):
    """Digits of a Korean mobile number, or "" when ``value`` is not one."""
    try:
        return _phone_digits(value)
    except ValueError:
        return ""


def _recv_until(connection, length, *, stop_early=None):
    response = bytearray()
    while len(response) < length:
        chunk = connection.recv(length - len(response))
        if not chunk:
            break
        response.extend(chunk)
        if b"\n" in chunk or (stop_early and stop_early(response)):
            break
    return bytes(response)


def _exchange(server, port, packet, read_response):
    """Send one packet and read the reply. Returns (response, failure_result)."""
    submitted = False
    try:
        with socket.create_connection((server, port), timeout=CONNECT_TIMEOUT_SECONDS) as connection:
            connection.settimeout(READ_TIMEOUT_SECONDS)
            submitted = True
            connection.sendall(packet)
            return read_response(connection), None
    except (TimeoutError, socket.timeout):
        if submitted:
            return b"", ICodeSendResult("unknown", "timeout", "Timed out waiting for the iCode response.")
        return b"", ICodeSendResult("rejected", "connect_timeout", "Could not connect to the iCode server.")
    except OSError as exc:
        return b"", ICodeSendResult(
            "unknown" if submitted else "rejected",
            "socket_error",
            f"iCode socket error: {type(exc).__name__}.",
        )


# --- token (JSON) protocol ------------------------------------------------------------------


def _json_server():
    server = str(getattr(settings, "G5_ICODE_JSON_SERVER", "") or "").strip() or ICODE_JSON_DEFAULT_HOST
    try:
        port = int(getattr(settings, "G5_ICODE_JSON_PORT", 0) or ICODE_JSON_DEFAULT_PORT)
    except (TypeError, ValueError):
        port = 0
    if not 1 <= port <= 65535:
        raise ICodeConfigurationError("G5_ICODE_JSON_PORT must be a valid port number.")
    return server, port


def _lms_subject(subject, message):
    # icode.lms.lib.php: no line breaks, and "<" / ">" make some carriers drop the message
    text = " ".join(str(subject or "").split()) or " ".join(message.split())
    return cut_to_bytes(text.replace("<", "[").replace(">", "]"), LMS_SUBJECT_MAX_BYTES).strip()


def build_token_packet(key, recipient, callback, message, *, subject="", allow_lms=False):
    """The ``06`` packet and its message type ("SMS" / "LMS")."""
    recipient = _phone_digits(recipient)
    callback = _callback_digits(callback)
    message = normalize_newlines(message)
    if allow_lms and message_bytes(message) > SMS_MAX_BYTES:
        message_type = "LMS"
        message = cut_to_bytes(message, LMS_MAX_BYTES)
        title = _lms_subject(subject, message)
    else:
        message_type = "SMS"
        message = cut_to_bytes(message, SMS_MAX_BYTES)
        title = ""
    payload = {"key": key, "tel": recipient, "cb": callback.ljust(11), "msg": message, "title": title, "date": ""}
    # PHP json_encode: ASCII only (\uXXXX), no spaces, "/" escaped
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("/", "\\/").encode("ascii")
    if len(body) > MAX_PACKET_BODY:
        raise ValueError("The iCode message is too long.")
    return b"06" + str(len(body)).zfill(4).encode("ascii") + body, message_type


def _token_reply_finished(response):
    # a refusal can be shorter than a success reply; stop once its code is known
    return len(response) >= 8 and response[6:8] != b"00"


def send_token_message(recipient, callback, message, *, subject="", allow_lms=False):
    key = token_key()
    if not key:
        raise ICodeConfigurationError("Set G5_ICODE_TOKEN_KEY to use the iCode token API.")
    server, port = _json_server()
    try:
        recipient_digits = _phone_digits(recipient)
        packet, message_type = build_token_packet(
            key, recipient_digits, callback, message, subject=subject, allow_lms=allow_lms
        )
    except ValueError as exc:
        return ICodeSendResult("rejected", "invalid_request", str(exc))

    response, failure = _exchange(
        server,
        port,
        packet,
        lambda connection: _recv_until(connection, TOKEN_RESPONSE_LENGTH, stop_early=_token_reply_finished),
    )
    if failure:
        return ICodeSendResult(failure.status, failure.provider_code, failure.error_text, message_type)

    expected_prefix = b"0225  00" + recipient_digits.ljust(12).encode("ascii")
    if response.startswith(expected_prefix):
        provider_code = response[20:TOKEN_RESPONSE_LENGTH].decode("ascii", errors="replace").strip()
        return ICodeSendResult("accepted", provider_code or "accepted", "", message_type)
    if response.startswith(b"0225") and len(response) >= 8:
        provider_code = response[6:8].decode("ascii", errors="replace").strip()
        return ICodeSendResult(
            "rejected", provider_code or "gateway_error", "iCode rejected the message.", message_type
        )
    return ICodeSendResult("unknown", "invalid_response", "iCode returned an unrecognized response.", message_type)


# --- legacy ID/password protocol ------------------------------------------------------------


def _configuration():
    if not provider_enabled():
        raise ICodeConfigurationError("G5_SMS_PROVIDER disables iCode on this server.")

    account_id, password, server = _legacy_values()
    try:
        port = int(getattr(settings, "G5_ICODE_PORT", 0) or 0)
    except (TypeError, ValueError):
        port = 0
    if not account_id or not password or not server or not 1 <= port <= 65535:
        raise ICodeConfigurationError(
            "Set G5_ICODE_ID, G5_ICODE_PASSWORD, G5_ICODE_SERVER, and a valid G5_ICODE_PORT."
        )
    if not account_id.isascii() or not password.isascii() or len(account_id) > 10 or len(password) > 10:
        raise ICodeConfigurationError("The configured iCode account ID and password must fit the legacy 10-byte fields.")
    return account_id, password, server, port


def _field(value, width):
    raw = str(value).encode("ascii")
    if len(raw) > width:
        raise ValueError("An iCode message field exceeds its protocol width.")
    return raw.ljust(width, b" ")


def _message_field(message):
    raw = str(message or "").encode("euc_kr", errors="replace")[:LEGACY_SMS_MAX_BYTES]
    raw = raw.decode("euc_kr", errors="ignore").encode("euc_kr")
    return raw.ljust(LEGACY_SMS_MAX_BYTES, b" ")


def _build_packet(account_id, password, recipient, callback, message):
    recipient = _phone_digits(recipient)
    callback = _callback_digits(callback)
    return b"01144 " + b"".join(
        (
            _field(account_id, 10),
            _field(password, 10),
            _field(recipient, 11),
            _field(callback, 11),
            _field(account_id, 10),
            b" " * 12,
            _message_field(message),
        )
    )


def _read_response(connection):
    return _recv_until(connection, LEGACY_RESPONSE_LENGTH)


def send_sms(recipient, callback, message):
    """Legacy ID/password SMS (80 bytes, EUC-KR)."""
    account_id, password, server, port = _configuration()
    try:
        recipient_digits = _phone_digits(recipient)
        packet = _build_packet(account_id, password, recipient_digits, callback, normalize_newlines(message))
    except ValueError as exc:
        return ICodeSendResult("rejected", "invalid_request", str(exc))

    response, failure = _exchange(server, port, packet, _read_response)
    if failure:
        return failure

    expected_prefix = b"0223  00" + recipient_digits.ljust(11).encode("ascii")
    if response.startswith(expected_prefix):
        provider_code = response[19:29].decode("ascii", errors="replace").strip()
        if provider_code and not provider_code.startswith("Error"):
            return ICodeSendResult("accepted", provider_code)
        return ICodeSendResult("rejected", provider_code or "empty_result", "iCode rejected the message.")

    if response.startswith(b"0223"):
        provider_code = response[6:8].decode("ascii", errors="replace").strip()
        return ICodeSendResult("rejected", provider_code or "gateway_error", "iCode rejected the message.")
    return ICodeSendResult("unknown", "invalid_response", "iCode returned an unrecognized response.")


def send_message(recipient, callback, message, *, subject="", allow_lms=False):
    """Send through the token API when a token is set, else through the legacy ID/password API."""
    if not provider_enabled():
        raise ICodeConfigurationError("G5_SMS_PROVIDER disables iCode on this server.")
    if token_key():
        return send_token_message(recipient, callback, message, subject=subject, allow_lms=allow_lms)
    return send_sms(recipient, callback, message)
