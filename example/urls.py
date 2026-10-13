"""gnu_jango URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from gnu_jango.api import v1_auth
from gnu_jango.core import views as core_views
from gnu_jango.config import theme_admin
from gnu_jango.config import sample_data_admin
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

NEXTJS25_ADMIN_ROUTE_PATTERN = (
    r"admin/(?:"
    r"boards(?:/[^/]+)?|"
    r"members(?:/[^/]+)?|"
    r"qas(?:/[^/]+)?|"
    r"settings|"
    r"shop(?:/(?:categories|orders(?:/[^/]+)?|products(?:/[^/]+)?))?"
    r")"
)

urlpatterns = [
    path("admin", core_views.nextjs25_root_theme, {"template_path": "admin"}, name="nextjs25_admin_root"),
    path("admin.txt", core_views.nextjs25_root_text_payload, {"template_path": "admin"}, name="nextjs25_admin_root_text"),
    re_path(
        rf"^(?P<template_path>{NEXTJS25_ADMIN_ROUTE_PATTERN})\.txt$",
        core_views.nextjs25_root_text_payload,
        name="nextjs25_admin_text_payload",
    ),
    re_path(
        rf"^(?P<template_path>{NEXTJS25_ADMIN_ROUTE_PATTERN})/?$",
        core_views.nextjs25_root_theme,
        name="nextjs25_admin_theme",
    ),
    path(
        "admin/theme/",
        admin.site.admin_view(theme_admin.theme_settings),
        name="admin-theme-settings",
    ),
    path(
        "admin/sample-data/",
        admin.site.admin_view(sample_data_admin.sample_data_settings),
        name="admin-sample-data",
    ),
    path(
        "admin/theme/<slug:theme_name>/preview/",
        admin.site.admin_view(theme_admin.theme_preview),
        name="admin-theme-preview",
    ),
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="api-schema"), name="api-redoc"),
    path("api/", include("gnu_jango.api.urls")),
    # The Expo app (dday-app) opens the social login at the site root, as the PHP site served it;
    # these are the same views as /api/social/*.php and must come before the legacy *.php redirects.
    path("social/start.php", v1_auth.social_start_view, name="social-start-root"),
    path("social/finish.php", v1_auth.social_callback_view, name="social-finish-root"),
    path("api-auth/", include("rest_framework.urls", namespace="rest_framework")),
    path("", include("gnu_jango.editor.urls")),
    path("", include("gnu_jango.core.urls")),
]

urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG and "debug_toolbar" in settings.INSTALLED_APPS:
    try:
        import debug_toolbar
    except ImportError:
        pass
    else:
        urlpatterns += [
            path("__debug__/", include(debug_toolbar.urls)),
        ]

handler400 = "gnu_jango.core.views.error_400"
handler403 = "gnu_jango.core.views.error_403"
handler404 = "gnu_jango.core.views.error_404"
handler500 = "gnu_jango.core.views.error_500"
