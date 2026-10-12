from django.contrib import messages
from django.http import HttpResponse
from django.template import loader
from django.utils.translation import gettext_lazy as _

# https://stackoverflow.com/questions/2747554/equivalent-of-php-echo-something-exit-with-python-django
# https://stackoverflow.com/questions/39770562/making-djangos-messages-appear-in-javascript-alert-rather-than-html
# https://stackoverflow.com/questions/4362761/how-can-i-determine-if-the-document-referrer-is-from-my-own-site

# def alert(msg, url='', **kwargs):
def alert(msg, url="", **kwargs):
    template = loader.get_template("common/alert_message.html")

    request = kwargs.get("request", None)
    kwargs_url = kwargs.get("url", "")
    kwargs_msg = kwargs.get("msg", "")

    # msg = ''
    if kwargs_msg:
        msg = kwargs_msg

    # url = ''
    if kwargs_url:
        url = kwargs_url

    if request and msg:
        messages.error(request, msg)

    context = {
        "msg": msg,
        "url": url.replace("&amp;", "&"),
    }
    return HttpResponse(template.render(context, request))


def confirm(msg, url1="", url2="", url3="", **kwargs):

    request = kwargs.get("request", None)

    if not msg:
        return alert(_("올바른 방법으로 이용해 주십시오."))

    if not url1.strip():
        return alert(_("url1 를 지정해 주세요."))

    # if not url1.strip() or not url2.strip():
    #     return alert(_("url1 과 url2 를 지정해 주세요."))

    if not url3:
        url3 = request.META.get("HTTP_REFERER", "")

    msg = msg.replace("\\n", "<br>")

    context = {
        "msg": msg,
        "url1": url1,
        "url2": url2,
        "url3": url3,
    }

    template = loader.get_template("common/confirm_message.html")

    return HttpResponse(template.render(context, request))


def alert_close(msg, error=True, **kwargs):
    template = loader.get_template("common/alert_close_message.html")

    request = kwargs.get("request", None)
    # kwargs_url = kwargs.get('url', '')
    kwargs_msg = kwargs.get("msg", "")

    # msg = ''
    if kwargs_msg:
        msg = kwargs_msg

    # # url = ''
    # if(kwargs_url):
    #     url = kwargs_url

    if request and msg:
        messages.error(request, msg)

    context = {
        "msg": msg,
        "error": error,
    }
    return HttpResponse(template.render(context, request))
