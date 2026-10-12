from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.urls import re_path
from django.views.decorators.cache import never_cache


def legacy_ckeditor_removed(request):
    return JsonResponse(
        {
            "uploaded": "0",
            "error": {
                "message": "CKEditor 4 has been retired. Use the configured TUI editor instead.",
            },
        },
        status=410,
    )


urlpatterns = [
    re_path(r"^ckeditor/upload/", staff_member_required(legacy_ckeditor_removed), name="ckeditor_upload"),
    re_path(
        r"^ckeditor/browse/",
        never_cache(staff_member_required(legacy_ckeditor_removed)),
        name="ckeditor_browse",
    ),
]
