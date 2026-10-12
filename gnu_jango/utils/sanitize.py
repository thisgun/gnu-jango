import bleach
import re

try:
    from bleach.css_sanitizer import CSSSanitizer
except ImportError:
    pass

from django.conf import settings
from urllib.parse import urlparse

# https://github.com/marksweb/django-bleach


GFM_ALLOWED_TAGS = [
    "a",
    "b",
    "blockquote",
    "br",
    "code",
    "del",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "iframe",
    "img",
    "input",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
]


GLOBAL_ALLOWED_ATTRIBUTES = {"style", "title"}

TAG_ALLOWED_ATTRIBUTES = {
    "a": {"href", "rel", "target"},
    "code": {"class"},
    "iframe": {"allow", "allowfullscreen", "frameborder", "height", "src", "width"},
    "img": {"alt", "height", "src", "width"},
    "input": {"checked", "disabled", "type"},
    "td": {"align"},
    "th": {"align"},
}


def allow_attributes(tag, name, value):
    if tag == "iframe" and name == "src":

        safe_domains = [
            "www.youtube(?:-nocookie)?.com",
            "serviceapi.rmcnmv.naver.com",
            "videofarm.daum.net",
            "player.vimeo.com",
            "www.google.com",
            "maps.google.com",
            "play.afreeca.com",
            "v.nate.com",
            "www.microsoft.com/showcase/video.aspx",
            "w.soundcloud.com",
            "www.facebook.com",
            "kakaotv.daum.net",
            "v.afree.ca",
            "play-tv.kakao.com",
        ]

        safeiframe = "|".join(safe_domains)

        # safeiframe = re.escape(safeiframe)

        # https://stackoverflow.com/questions/280435/escaping-regex-string

        p = urlparse(value)

        if re.match("(" + safeiframe + ")$", p.netloc):

            return True
        else:
            return False

        # return re.match("%^(https?:)?//(" + safeiframe + ")%", p.netloc)

        # return (not p.netloc) or p.netloc == "youtube.com"
    if name in GLOBAL_ALLOWED_ATTRIBUTES:
        return True

    if name in TAG_ALLOWED_ATTRIBUTES.get(tag, set()):
        return True

    return False


def get_bleach_default_options(tags=None):
    bleach_args = {}
    bleach_settings = {
        "BLEACH_ALLOWED_TAGS": "tags",
        # "BLEACH_ALLOWED_ATTRIBUTES": "attributes",
        "BLEACH_ALLOWED_STYLES": "css_sanitizer",
        "BLEACH_STRIP_TAGS": "strip",
        "BLEACH_STRIP_COMMENTS": "strip_comments",
        "BLEACH_ALLOWED_PROTOCOLS": "protocols",
    }

    for setting, kwarg in bleach_settings.items():
        if hasattr(settings, setting):
            attr = getattr(settings, setting)

            # 파이썬 3.9 버전 이하에는 css_sanitizer 가 설치되지 않는다.
            try:
                if setting == "BLEACH_ALLOWED_STYLES":
                    attr = CSSSanitizer(allowed_css_properties=attr)
            except Exception:
                continue

            bleach_args[kwarg] = attr

    # bleach_args["attributes"] = {"iframe": allow_src}

    bleach_args["attributes"] = allow_attributes
    if tags is not None:
        bleach_args["tags"] = tags

    return bleach_args


def get_gfm_bleach_options():
    base_tags = getattr(settings, "BLEACH_ALLOWED_TAGS", [])
    tags = sorted(set(base_tags) | set(GFM_ALLOWED_TAGS))
    return get_bleach_default_options(tags=tags)


def sanitize_html(value, tags=None):
    if value is None:
        return ""

    return bleach.clean(value, **get_bleach_default_options(tags=tags))


def sanitize_gfm_html(value):
    if value is None:
        return ""

    return bleach.clean(value, **get_gfm_bleach_options())
