import os
import re
import locale
from importlib import import_module
from django.contrib.auth.hashers import (
    make_password,
    check_password as hashers_check_password,
)
from urllib.parse import urlparse, urlunparse
from django.conf import settings

from django.http import HttpRequest, QueryDict
from django.utils.html import escape
from django_user_agents.utils import get_user_agent

from gnu_jango import defaults
from gnu_jango.config import config
from django.middleware.csrf import CsrfViewMiddleware

# def save_object_to_text_file(obj):
#     file_path = 
#     with open(file_path, 'w') as file:
#         file.write(str(obj))
        
class Create_Object:
    def __init__(self, d=None):
        if d is not None:
            for key, value in d.items():
                setattr(self, key, value)


def import_module_attr(path):
    package, module = path.rsplit(".", 1)
    return getattr(import_module(package), module)


def check_device(request=None, board=[]):
    pass


# https://stackoverflow.com/questions/29454296/django-check-csrf-token-manually
def check_csrf(request, csrf_token):
    request.csrf_processing_done = False
    request.META[settings.CSRF_HEADER_NAME] = csrf_token
    reason = CsrfViewMiddleware().process_view(request, None, (), {})
    if reason is not None:
        return reason

    return ""


def is_mobile(request=None, is_real=False):
    if request is None:
        request = HttpRequest()
    user_agent = get_user_agent(request)
    return bool(user_agent.is_mobile or user_agent.is_tablet)


def number_format(num, places=0):
    return locale.format_string("%.*f", (places, num), True)


def get_text(str, html=0, restore=False):
    return escape(str)


def get_levels_choices(start=1, end=10):
    return list((i, i) for i in range(start, end + 1))


def get_user_skin_static_path(request=None):
    path = get_user_skin_path(request)

    return path.replace(defaults.SKIN_DIR + "/", "")


# https://stackoverflow.com/questions/2506379/add-params-to-given-url-in-python
def get_params_merge_url(params=None, url=""):
    if not url:
        return ""

    parsed_url = urlparse(url)
    merged = QueryDict(parsed_url.query, mutable=True)
    for key, value in (params or {}).items():
        if isinstance(value, (list, tuple)):
            merged.setlist(key, [str(item) for item in value])
        else:
            merged[key] = value

    return urlunparse(parsed_url._replace(query=merged.urlencode()))


def get_user_skin_path(request=None):
    if is_mobile(request):
        return (
            get_skin_path(defaults.USER_SKIN_DIR, getattr(config, "cf_mobile_user_skin", "basic"), request)
            + "/"
        )
    else:
        return get_skin_path(defaults.USER_SKIN_DIR, getattr(config, "cf_user_skin", "basic"), request) + "/"


def get_skin_path(dir, skin, request=None):

    skin_path = ""
    output = re.search("^theme/(.+)$", skin, flags=re.IGNORECASE)
    if output is not None:  # 테마에 포함된 스킨이라면
        theme_path = "theme/" + getattr(config, "cf_theme", "basic")
        if is_mobile(request):
            skin_path = "/".join(
                [
                    theme_path,
                    defaults.MOBILE_DIR,
                    defaults.SKIN_DIR,
                    dir,
                    output.group(1),
                ]
            )
            # skin_path = (
            #     theme_path
            #     + "/"
            #     + defaults.MOBILE_DIR
            #     + "/"
            #     + defaults.SKIN_DIR
            #     + "/"
            #     + dir
            #     + "/"
            #     + output.group(1)
            # )
            if not os.path.isdir(skin_path):
                skin_path = "/".join([theme_path, defaults.MOBILE_DIR, dir, output.group(1)])
                # skin_path = (
                #     theme_path
                #     + "/"
                #     + defaults.MOBILE_DIR
                #     + "/"
                #     + dir
                #     + "/"
                #     + output.group(1)
                # )
        else:
            skin_path = "/".join([theme_path, defaults.MOBILE_DIR, dir, output.group(1)])
            # skin_path = (
            #     theme_path
            #     + "/"
            #     + defaults.MOBILE_DIR
            #     + "/"
            #     + dir
            #     + "/"
            #     + output.group(1)
            # )
    else:
        if is_mobile(request):
            skin_path = defaults.MOBILE_SKIN_DIR + "/" + dir + "/" + skin
        else:
            skin_path = defaults.SKIN_DIR + "/" + dir + "/" + skin

    return skin_path


def get_skin_dir(skin, skin_path=defaults.SKIN_PATH):
    directory = skin_path + skin
    # root, dirs, files = os.walk(directory)
    # return [x[0] for x in os.walk(directory)]

    # https://stackoverflow.com/questions/1720421/how-do-i-concatenate-two-lists-in-python
    # https://stackoverflow.com/questions/141291/how-to-list-only-top-level-directories-in-python
    return [
        (name, name)
        for name in os.listdir(directory)
        if os.path.isdir(os.path.join(directory, name))
    ]


def get_template_theme_path():
    return defaults.THEME_DIR + "/" + getattr(config, "cf_theme", "basic")


def get_template_theme_mobile_path():
    return get_template_theme_path() + "/" + defaults.MOBILE_DIR


def get_template_replace_path(str_path):
    return re.sub("^skin/", "", str_path)


# https://velog.io/@kyleee/TIL61-Django-auth
def check_password(str_pass, hash):

    # password = get_encrypt_string(str_pass)
    # return password == hash
    # https://github.com/django/django/blob/41329b9852fcae586bd20aa9f3e591dde94cc925/django/contrib/auth/hashers.py#L134-L152

    return hashers_check_password(str_pass, hash)


def get_encrypt_string(str):
    encrypt = make_password(str)

    return encrypt


def get_client_ip(request):
    """The visitor's IP address.

    X-Forwarded-For is written by the client too, so it is only trusted for the number of reverse
    proxies in front of the site (settings.TRUSTED_PROXY_COUNT): with N proxies the client address
    is the N-th entry from the right. Without proxies REMOTE_ADDR is used and the header ignored.
    """
    proxies = int(getattr(settings, "TRUSTED_PROXY_COUNT", 0) or 0)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR") or ""
    if proxies > 0 and forwarded:
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if len(hops) >= proxies:
            return hops[-proxies]
    return request.META.get("REMOTE_ADDR")


def cut_str(str, int_len, suffix="…"):
    str_len = len(str)

    if str_len > int_len:
        return str[:int_len] + suffix
    else:
        return str


# https://stackoverflow.com/questions/33792694/base-convert-in-python-given-a-string
def to_base(n, bse):
    digs = "0123456789abcdefghijklmnopqrstuvwxyz"
    if not 2 <= bse <= len(digs):
        raise ValueError("base must be between 2 and 36")
    if n == 0:
        return "0"
    sign = "-" if n < 0 else ""
    n = abs(n)
    tmp = []
    while n:
        n, i = divmod(n, bse)
        tmp.append(digs[i])
    return sign + "".join(tmp[::-1])


def chng_frm_base(s, frm_bse, to_bse):
    if to_bse < 2 or to_bse > 36 or frm_bse < 2 or frm_bse > 36:
        raise ValueError("bases must be between 2-36")
    try:
        return to_base(int(s, frm_bse), to_bse)
    except ValueError:
        try:
            n = int("".join([ch for ch in s if ch.isdigit()]), frm_bse)
            return to_base(n, to_bse)
        except ValueError:
            return 0


def search_font(stx, content):

    # 문자앞에 \ 를 붙입니다.
    if not stx.strip() and stx != "0":
        return content

    # 검색어 전체를 공란으로 나눈다
    s = stx.split(" ")

    # "/(검색1|검색2)/i" 와 같은 패턴을 만듬
    pattern = ""
    bar = ""
    for m in s:
        if m.strip() == "":
            continue

        tmp_str = re.sub(r"([\.\\+\*\?\[\^\]\($\)])", r"\\\1", m)
        tmp_str = tmp_str.replace("/", r"\/").replace("|", r"\|")
        pattern += (bar + tmp_str) + "(?![^<]*>)"
        bar = "|"

    # m = 0
    # while ( m < len(s) ) :
    #     if (s[m].strip() == '') :
    #         continue;

    #     tmp_str = re.sub(r'([\.\\+\*\?\[\^\]\($\)])', r'\\\1', s[m]);
    #     tmp_str = str_replace(src, dst, tmp_str);
    #     pattern += (bar + tmp_str) + "(?![^<]*>)";
    #     bar = "|";
    #     m+=1;

    replace = '<b class="sch_word">\\1</b>'
    return re.sub(r"(" + pattern + ")", replace, content, flags=re.IGNORECASE)


def is_use_email_certify(request=None):
    if config.cf_use_email_certify:
        if config.cf_social_login_use:
            return 0

    return config.cf_use_email_certify


# https://stackoverflow.com/questions/7060940/append-a-querystring-to-url-in-django
def get_url_merge_params(request, url, params=""):

    q = QueryDict(mutable=True)
    q["filter"] = "other"
    q["sort"] = "newest"
    q.setlist("values", [1, 2, "c"])
    query_string = q.urlencode()

    return url
