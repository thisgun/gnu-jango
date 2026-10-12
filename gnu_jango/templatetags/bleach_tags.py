import bleach

from django import template
from django.utils.safestring import mark_safe

from gnu_jango.utils.sanitize import sanitize_html


register = template.Library()


@register.filter(name="bleach")
def bleach_value(value, tags=None):
    if value is None:
        return None

    allowed_tags = tags.split(",") if tags is not None else None
    bleached_value = sanitize_html(value, tags=allowed_tags)
    return mark_safe(bleached_value)


@register.filter
def bleach_linkify(value):
    """
    Convert URL-like strings in an HTML fragment to links

    This function converts strings that look like URLs, domain names and email
    addresses in text that may be an HTML fragment to links, while preserving:

        1. links already in the string
        2. urls found in attributes
        3. email addresses
    """
    if value is None:
        return None

    linkified_value = bleach.linkify(value, parse_email=True)
    return mark_safe(sanitize_html(linkified_value))
