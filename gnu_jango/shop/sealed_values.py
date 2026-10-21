"""Small secrets kept at rest without a crypto dependency: a value is encrypted with an
HMAC-SHA256 keystream (counter mode, random nonce) under a key derived from SECRET_KEY, and
authenticated with a separate HMAC tag. Used for the cash receipt identification number a manual
request keeps until the admin issues the receipt, so it does not show in payment log screens or
searches.

The tag also covers a ``context`` (the order id), so a sealed value copied onto another row does
not open there. Values sealed under a key that is now listed in SECRET_KEY_FALLBACKS still open,
so a key rotation done the Django way keeps pending values readable; a value whose key is gone,
or that was altered, opens to ""."""

import base64
import hashlib
import hmac
import secrets

from django.conf import settings
from django.utils.crypto import constant_time_compare, salted_hmac

NONCE_BYTES = 16
TAG_BYTES = 16
PREFIX = "sv2:"


def _key(purpose, salt, secret):
    return salted_hmac(f"gnu_jango.shop.sealed_values.{salt}", purpose, secret=secret, algorithm="sha256").digest()


def _secrets():
    """The current SECRET_KEY first, then the rotated-out keys still accepted for reading."""
    return [settings.SECRET_KEY, *getattr(settings, "SECRET_KEY_FALLBACKS", ())]


def _keystream(salt, secret, nonce, length):
    key = _key("keystream", salt, secret)
    blocks = []
    for counter in range((length + 31) // 32):
        blocks.append(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
    return b"".join(blocks)[:length]


def _tag(salt, secret, context, nonce, body):
    bound = str(context or "").encode("utf-8")
    message = len(bound).to_bytes(4, "big") + bound + nonce + body
    return hmac.new(_key("tag", salt, secret), message, hashlib.sha256).digest()[:TAG_BYTES]


def _xor(data, stream):
    return bytes(a ^ b for a, b in zip(data, stream))


def seal(value, *, salt, context=""):
    """``value`` sealed for ``context`` (e.g. the order id it belongs to) under SECRET_KEY."""
    secret = settings.SECRET_KEY
    data = str(value or "").encode("utf-8")
    nonce = secrets.token_bytes(NONCE_BYTES)
    body = _xor(data, _keystream(salt, secret, nonce, len(data)))
    tag = _tag(salt, secret, context, nonce, body)
    return PREFIX + base64.urlsafe_b64encode(nonce + tag + body).decode("ascii")


def unseal(token, *, salt, context=""):
    """The sealed value, or "" when the token is altered, belongs to another context or was
    sealed under a key that is neither SECRET_KEY nor in SECRET_KEY_FALLBACKS."""
    token = str(token or "")
    if not token.startswith(PREFIX):
        return ""
    try:
        raw = base64.urlsafe_b64decode(token[len(PREFIX) :].encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return ""
    nonce, tag, body = raw[:NONCE_BYTES], raw[NONCE_BYTES : NONCE_BYTES + TAG_BYTES], raw[NONCE_BYTES + TAG_BYTES :]
    if len(nonce) != NONCE_BYTES:
        return ""
    for secret in _secrets():
        if constant_time_compare(tag, _tag(salt, secret, context, nonce, body)):
            try:
                return _xor(body, _keystream(salt, secret, nonce, len(body))).decode("utf-8")
            except UnicodeDecodeError:
                return ""
    return ""
