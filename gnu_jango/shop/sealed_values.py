"""Small secrets kept at rest without a crypto dependency: a value is encrypted with an
HMAC-SHA256 keystream (counter mode, random nonce) under a key derived from SECRET_KEY, and
authenticated with a separate HMAC tag. Used for the cash receipt identification number a manual
request keeps until the admin issues the receipt, so it does not show in payment log screens or
searches. A value sealed under a rotated SECRET_KEY no longer opens (unseal returns "")."""

import base64
import hashlib
import hmac
import secrets

from django.utils.crypto import constant_time_compare, salted_hmac

NONCE_BYTES = 16
TAG_BYTES = 16
PREFIX = "sv1:"


def _key(purpose, salt):
    return salted_hmac(f"gnu_jango.shop.sealed_values.{salt}", purpose, algorithm="sha256").digest()


def _keystream(salt, nonce, length):
    key = _key("keystream", salt)
    blocks = []
    for counter in range((length + 31) // 32):
        blocks.append(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
    return b"".join(blocks)[:length]


def _tag(salt, nonce, body):
    return hmac.new(_key("tag", salt), nonce + body, hashlib.sha256).digest()[:TAG_BYTES]


def seal(value, *, salt):
    data = str(value or "").encode("utf-8")
    nonce = secrets.token_bytes(NONCE_BYTES)
    body = bytes(a ^ b for a, b in zip(data, _keystream(salt, nonce, len(data))))
    return PREFIX + base64.urlsafe_b64encode(nonce + _tag(salt, nonce, body) + body).decode("ascii")


def unseal(token, *, salt):
    token = str(token or "")
    if not token.startswith(PREFIX):
        return ""
    try:
        raw = base64.urlsafe_b64decode(token[len(PREFIX) :].encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return ""
    nonce, tag, body = raw[:NONCE_BYTES], raw[NONCE_BYTES : NONCE_BYTES + TAG_BYTES], raw[NONCE_BYTES + TAG_BYTES :]
    if len(nonce) != NONCE_BYTES or not constant_time_compare(tag, _tag(salt, nonce, body)):
        return ""
    data = bytes(a ^ b for a, b in zip(body, _keystream(salt, nonce, len(body))))
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return ""
