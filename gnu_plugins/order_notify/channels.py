"""Where 주문 알림 sends: a Discord or Slack incoming webhook and a Telegram bot. The only module
that talks to them.

A channel is configured by the environment variables in CHANNEL_ENV (or Django settings of the same
names) and nowhere else: a webhook URL or bot token lets anyone post to the channel, so it is kept out
of the admin and the Config table. A value that does not look like the service's own address is
ignored, so a typo never sends order details to another host, and requests never follow a redirect.

- Discord: POST {content, allowed_mentions} to https://discord.com/api/webhooks/...; allowed_mentions
  with no "parse" keeps "@everyone" in a customer's name from pinging the channel.
- Slack: POST {text} to https://hooks.slack.com/services/...; &, < and > are escaped as Slack asks.
- Telegram: POST {chat_id, text} to https://api.telegram.org/bot<token>/sendMessage, without
  parse_mode, so the text is shown as typed.
"""

import json
import re
from dataclasses import dataclass
from http import client as http_client
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlsplit

from decouple import config as env_config
from django.conf import settings
from django.views.decorators.debug import sensitive_variables

DISCORD = "discord"
SLACK = "slack"
TELEGRAM = "telegram"
CHANNELS = (DISCORD, SLACK, TELEGRAM)
CHANNEL_LABELS = {DISCORD: "Discord", SLACK: "Slack", TELEGRAM: "Telegram"}
CHANNEL_ENV = {
    DISCORD: ("ORDER_NOTIFY_DISCORD_WEBHOOK_URL",),
    SLACK: ("ORDER_NOTIFY_SLACK_WEBHOOK_URL",),
    TELEGRAM: ("ORDER_NOTIFY_TELEGRAM_BOT_TOKEN", "ORDER_NOTIFY_TELEGRAM_CHAT_ID"),
}

DISCORD_HOSTS = {"discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com"}
SLACK_HOSTS = {"hooks.slack.com"}
TELEGRAM_API = "https://api.telegram.org"
TELEGRAM_TOKEN = re.compile(r"^[0-9]{5,20}:[A-Za-z0-9_-]{30,64}$")
TELEGRAM_CHAT = re.compile(r"^(-?[0-9]{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$")

# A webhook answers in well under a second; the send runs after the order is saved but still inside
# the customer's (or the PG's) request, so it must not hold it up for long.
TIMEOUT_SECONDS = 3
MAX_RESPONSE_BYTES = 64 * 1024
MAX_ERROR_LENGTH = 200
USER_AGENT = "gnu-jango-order-notify/1.0"


class ChannelError(Exception):
    """A message the channel did not take; ``retry`` is False when sending it again cannot help."""

    def __init__(self, message, *, retry=True):
        super().__init__(message)
        self.retry = retry


@dataclass(frozen=True)
class Target:
    url: str
    payload: dict


def _value(name):
    if hasattr(settings, name):
        return str(getattr(settings, name) or "").strip()
    return str(env_config(name, default="") or "").strip()


def _webhook_url(url, hosts, path_prefix):
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.hostname in hosts
        and port is None
        and "@" not in parts.netloc
        and parts.path.startswith(path_prefix)
        and len(parts.path) > len(path_prefix)
    )


def _slack_text(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@sensitive_variables("url", "token")
def _target(channel, text):
    """The request for ``channel``, or None when it is not configured (or configured wrongly)."""
    if channel == DISCORD:
        url = _value("ORDER_NOTIFY_DISCORD_WEBHOOK_URL")
        if _webhook_url(url, DISCORD_HOSTS, "/api/webhooks/"):
            return Target(url, {"content": text, "allowed_mentions": {"parse": []}})
    elif channel == SLACK:
        url = _value("ORDER_NOTIFY_SLACK_WEBHOOK_URL")
        if _webhook_url(url, SLACK_HOSTS, "/services/"):
            return Target(url, {"text": _slack_text(text)})
    elif channel == TELEGRAM:
        token = _value("ORDER_NOTIFY_TELEGRAM_BOT_TOKEN")
        chat_id = _value("ORDER_NOTIFY_TELEGRAM_CHAT_ID")
        if TELEGRAM_TOKEN.match(token) and TELEGRAM_CHAT.match(chat_id):
            return Target(
                f"{TELEGRAM_API}/bot{token}/sendMessage",
                {"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            )
    return None


def configured():
    """The channels whose settings are present and valid, in CHANNELS order."""
    return tuple(channel for channel in CHANNELS if _target(channel, "") is not None)


def misconfigured():
    """The channels that have a value in the environment that is not valid (a typo, a wrong host)."""
    return tuple(
        channel
        for channel in CHANNELS
        if any(_value(name) for name in CHANNEL_ENV[channel]) and _target(channel, "") is None
    )


class _NoRedirect(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # urllib then raises HTTPError for the 3xx


_opener = urllib_request.build_opener(_NoRedirect)


def _open(request):
    with _opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        response.read(MAX_RESPONSE_BYTES)


def _reason(exc):
    reason = getattr(exc, "reason", None) or exc
    return f"{type(exc).__name__}: {reason}"[:MAX_ERROR_LENGTH]


@sensitive_variables("target", "request")
def send(channel, text):
    """Post ``text`` to ``channel``; raises ChannelError. Error texts never carry the URL or token."""
    target = _target(channel, text)
    if target is None:
        raise ChannelError("채널 설정이 없거나 형식이 맞지 않습니다.", retry=False)
    request = urllib_request.Request(
        target.url,
        data=json.dumps(target.payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        _open(request)
    except urllib_error.HTTPError as exc:
        # 429 (rate limit) and 5xx pass; another 4xx means a revoked webhook or a wrong chat.
        raise ChannelError(f"HTTP {exc.code}", retry=exc.code == 429 or exc.code >= 500) from None
    except (urllib_error.URLError, OSError, http_client.HTTPException, ValueError) as exc:
        # HTTPException: a cut-off or malformed answer (IncompleteRead, BadStatusLine)
        raise ChannelError(_reason(exc)) from None
