from django import template
from urllib.parse import urlencode

from gnu_jango.utils.lib import get_params_merge_url

# https://stackoverflow.com/questions/51375759/django-url-template-with-query-parameters
register = template.Library()


@register.simple_tag
def urlparams(*_, **kwargs):
    safe_args = {k: v for k, v in kwargs.items() if v is not None}
    if safe_args:
        return "?{}".format(urlencode(safe_args))
    return ""


@register.simple_tag
def add_params_url(*_, **kwargs):

    if "page_link" in kwargs:
        url = kwargs.pop("page_link", "")

    safe_args = {k: v for k, v in kwargs.items() if v is not None}

    return get_params_merge_url(safe_args, url)
