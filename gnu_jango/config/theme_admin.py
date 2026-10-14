import re
from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _

from . import config as site_config
from . import signals
from .models import Config


THEME_PRESENTATION = {
    "basic": {
        "title": "기본 테마",
        "description": "GNUboard 기본 템플릿으로 구성된 클래식 테마입니다.",
    },
    "nextjs25": {
        "title": "Next.js 25",
        "description": "기존 Next.js 테마 디렉터리와 호환되는 테마입니다.",
    },
    "nextjs_default": {
        "title": "Next.js Default",
        "description": "커뮤니티와 쇼핑 화면을 제공하는 Next.js 기본 테마입니다.",
    },
    "handbook": {
        "title": "Handbook (매뉴얼)",
        "description": "게시판 그룹을 책으로, 글을 장으로 보여 주는 문서·매뉴얼 사이트용 Next.js 테마입니다.",
    },
}
THEME_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
THEME_PREVIEW_FILES = (
    "screenshot.png",
    "screenshot.jpg",
    "preview.png",
    "preview.jpg",
    "og-default.png",
)


def _require_superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied


def _installed_themes():
    theme_root = (Path(settings.TEMPLATES_DIR) / "theme").resolve()
    if not theme_root.is_dir():
        return []

    active_theme = str(getattr(site_config, "cf_theme", "basic") or "basic")
    themes = []
    for theme_dir in sorted(theme_root.iterdir(), key=lambda path: path.name.casefold()):
        if not THEME_NAME_PATTERN.fullmatch(theme_dir.name) or not theme_dir.is_dir():
            continue
        resolved_dir = theme_dir.resolve()
        if resolved_dir.parent != theme_root or not (resolved_dir / "index.html").is_file():
            continue

        presentation = THEME_PRESENTATION.get(
            theme_dir.name,
            {
                "title": theme_dir.name.replace("_", " ").replace("-", " ").title(),
                "description": "설치된 테마입니다.",
            },
        )
        preview_file = next(
            (filename for filename in THEME_PREVIEW_FILES if (resolved_dir / filename).is_file()),
            None,
        )
        themes.append(
            {
                "name": theme_dir.name,
                "title": presentation["title"],
                "description": presentation["description"],
                "is_active": theme_dir.name == active_theme,
                "preview_url": (
                    reverse("admin-theme-preview", args=[theme_dir.name]) if preview_file else ""
                ),
                "preview_variant": theme_dir.name.replace("_", "-").replace(".", "-"),
            }
        )
    return themes


def theme_settings(request):
    _require_superuser(request)
    themes = _installed_themes()
    allowed_names = {theme["name"] for theme in themes}

    if request.method == "POST":
        selected_theme = request.POST.get("theme", "")
        if selected_theme not in allowed_names:
            messages.error(request, _("선택할 수 없는 테마입니다."))
        else:
            Config.objects.update_or_create(
                name="cf_theme",
                defaults={"value": selected_theme},
            )
            site_config.clear()
            signals.config_done.send(sender=Config)
            messages.success(
                request,
                _("%(theme)s 테마를 적용했습니다.") % {"theme": selected_theme},
            )
        return HttpResponseRedirect(reverse("admin-theme-settings"))

    context = {
        **admin.site.each_context(request),
        "title": _("테마 설정"),
        "themes": themes,
    }
    request.current_app = admin.site.name
    return TemplateResponse(request, "admin/config/theme_settings.html", context)


def theme_preview(request, theme_name):
    _require_superuser(request)
    if not THEME_NAME_PATTERN.fullmatch(theme_name):
        raise Http404

    theme_root = (Path(settings.TEMPLATES_DIR) / "theme").resolve()
    theme_dir = (theme_root / theme_name).resolve()
    if theme_dir.parent != theme_root or not (theme_dir / "index.html").is_file():
        raise Http404

    for filename in THEME_PREVIEW_FILES:
        preview_path = theme_dir / filename
        if preview_path.is_file():
            content_type = "image/png" if preview_path.suffix == ".png" else "image/jpeg"
            return FileResponse(preview_path.open("rb"), content_type=content_type)
    raise Http404
