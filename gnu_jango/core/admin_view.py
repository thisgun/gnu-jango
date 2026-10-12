from django.shortcuts import render

from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_POST

from gnu_jango.bbs.models import Group, Board


from django.utils.translation import gettext_lazy as _
from gnu_jango.bbs.utils import get_pretty_url


@staff_member_required
@require_POST
def add_menu_form(request):

    type = request.POST.get("type")
    result = None

    if type == "group":
        result = Group.objects.all().order_by("gr_order", "pk")
        bbs_subject_title = _("제목")
    elif type == "board":
        result = Board.objects.all().order_by("bo_order", "bo_table")
        bbs_subject_title = _("게시판제목")
    else:
        bbs_subject_title = ""

    result_list = []

    if result:
        for row in result:
            row.link = get_pretty_url(row.bo_table) if type == "board" else ""
            result_list.append(row)

    context = {"result_list": result_list, "bbs_subject_title": bbs_subject_title, "type": type}

    return render(request, "admin/site_menu/menu_form_search.html", context)
