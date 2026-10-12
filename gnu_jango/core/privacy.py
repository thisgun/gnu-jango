from ipaddress import ip_address, ip_network

from django.conf import settings


BOT_USER_AGENT_MARKERS = (
    "bot",
    "crawl",
    "spider",
    "slurp",
    "bingpreview",
    "facebookexternalhit",
    "preview",
    "monitoring",
)


def normalize_ip_address(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("[") and "]" in text:
        text = text[1 : text.index("]")]
    elif text.count(":") == 1 and "." in text:
        text = text.rsplit(":", 1)[0]
    try:
        return str(ip_address(text))
    except ValueError:
        return None


def anonymize_ip_address(value):
    normalized = normalize_ip_address(value)
    if not normalized:
        return None
    ip = ip_address(normalized)
    prefix = 24 if ip.version == 4 else 64
    return str(ip_network(f"{ip}/{prefix}", strict=False).network_address)


def ip_address_for_storage(value):
    if getattr(settings, "ADMIN_VISIT_LOG_MASK_IP", True):
        return anonymize_ip_address(value)
    return normalize_ip_address(value)


def is_bot_user_agent(user_agent):
    normalized = str(user_agent or "").lower()
    return any(marker in normalized for marker in BOT_USER_AGENT_MARKERS)


def should_skip_user_agent(user_agent):
    return bool(getattr(settings, "ADMIN_VISIT_LOG_EXCLUDE_BOTS", True) and is_bot_user_agent(user_agent))
