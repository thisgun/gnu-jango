from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _

from . import sample_data


def _require_superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied


def sample_data_settings(request):
    _require_superuser(request)

    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "add":
                manifest = sample_data.create_sample_data()
                counts = sample_data.managed_counts(manifest)
                messages.success(
                    request,
                    _("샘플 데이터를 추가했습니다. 게시글 %(posts)s개, 댓글 %(comments)s개, 상품 %(products)s개, FAQ %(faqs)s개를 만들었습니다.")
                    % counts,
                )
            elif action == "ensure_shop":
                result = sample_data.ensure_shop_sample_data()
                messages.success(
                    request,
                    _("쇼핑몰 샘플 상품 %(products)s개를 준비했습니다. 추가 %(created)s개, 노출 보정 %(updated)s개입니다.") % result,
                )
            elif action == "repair_product_types":
                repaired = sample_data.repair_sample_product_types()
                if repaired:
                    messages.success(
                        request,
                        _("샘플 상품 %(products)s개의 쇼핑몰 노출 분류를 보정했습니다.")
                        % {"products": repaired},
                    )
                else:
                    messages.info(request, _("보정할 샘플 상품이 없습니다."))
            elif action == "delete":
                if request.POST.get("confirmation", "").strip() != "삭제":
                    messages.error(request, _("삭제하려면 확인란에 ‘삭제’를 입력해 주세요."))
                else:
                    result = sample_data.remove_sample_data()
                    if result["retained"]:
                        messages.warning(
                            request,
                            _("샘플 데이터 %(deleted)s개를 정리했습니다. 댓글·주문 등 실제 기록이 연결된 %(retained)s개 항목은 보존했습니다.")
                            % result,
                        )
                    else:
                        messages.success(request, _("관리 페이지에서 생성한 샘플 데이터를 정리했습니다."))
            else:
                messages.error(request, _("요청한 작업을 확인할 수 없습니다."))
        except sample_data.SampleDataError as exc:
            messages.error(request, str(exc))
        return HttpResponseRedirect(reverse("admin-sample-data"))

    status = sample_data.get_status()
    context = {
        **admin.site.each_context(request),
        "title": _("샘플 데이터"),
        **status,
    }
    request.current_app = admin.site.name
    return TemplateResponse(request, "admin/config/sample_data_settings.html", context)
