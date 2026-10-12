from dataclasses import dataclass
import re
import socket

from django.conf import settings


class ICodeConfigurationError(RuntimeError):
    """Raised when the iCode environment configuration is incomplete."""


@dataclass(frozen=True)
class ICodeSendResult:
    status: str
    provider_code: str = ""
    error_text: str = ""


def _configuration():
    if getattr(settings, "G5_SMS_PROVIDER", "") != "icode":
        raise ICodeConfigurationError("G5_SMS_PROVIDER must be set to icode.")

    account_id = str(getattr(settings, "G5_ICODE_ID", "") or "").strip()
    password = str(getattr(settings, "G5_ICODE_PASSWORD", "") or "").strip()
    server = str(getattr(settings, "G5_ICODE_SERVER", "") or "").strip()
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


def _field(value, width):
    raw = str(value).encode("ascii")
    if len(raw) > width:
        raise ValueError("An iCode message field exceeds its protocol width.")
    return raw.ljust(width, b" ")


def _message_field(message):
    raw = str(message or "").encode("euc_kr", errors="replace")[:80]
    raw = raw.decode("euc_kr", errors="ignore").encode("euc_kr")
    return raw.ljust(80, b" ")


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
    response = bytearray()
    while len(response) < 29:
        chunk = connection.recv(29 - len(response))
        if not chunk:
            break
        response.extend(chunk)
    return bytes(response)


def send_sms(recipient, callback, message):
    account_id, password, server, port = _configuration()
    try:
        recipient_digits = _phone_digits(recipient)
        packet = _build_packet(account_id, password, recipient_digits, callback, message)
    except ValueError as exc:
        return ICodeSendResult("rejected", "invalid_request", str(exc))

    submitted = False
    try:
        with socket.create_connection((server, port), timeout=3) as connection:
            connection.settimeout(8)
            submitted = True
            connection.sendall(packet)
            response = _read_response(connection)
    except (TimeoutError, socket.timeout):
        if submitted:
            return ICodeSendResult("unknown", "timeout", "Timed out waiting for the iCode response.")
        return ICodeSendResult("rejected", "connect_timeout", "Could not connect to the iCode server.")
    except OSError as exc:
        return ICodeSendResult(
            "unknown" if submitted else "rejected",
            "socket_error",
            f"iCode socket error: {type(exc).__name__}.",
        )

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
