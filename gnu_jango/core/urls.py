from django.urls import path, re_path

from . import views
from .admin_view import add_menu_form

urlpatterns = [
    path("", views.index, name="index"),
    path("_next/static/<path:path>", views.nextjs25_static, name="nextjs25_static"),
    path("icon-192.png", views.nextjs25_public_asset, {"path": "icon-192.png"}, name="nextjs25_icon_192"),
    path("icon-512.png", views.nextjs25_public_asset, {"path": "icon-512.png"}, name="nextjs25_icon_512"),
    path("img/logo.png", views.nextjs25_public_asset, {"path": "img/logo.png"}, name="nextjs25_logo"),
    path("img/shop-logo.png", views.nextjs25_public_asset, {"path": "img/shop-logo.png"}, name="nextjs25_shop_logo"),
    path("manifest.json", views.nextjs25_public_asset, {"path": "manifest.json"}, name="nextjs25_manifest"),
    path(
        "manifest.webmanifest",
        views.nextjs25_public_asset,
        {"path": "manifest.webmanifest"},
        name="nextjs25_webmanifest",
    ),
    path("og-default.png", views.nextjs25_public_asset, {"path": "og-default.png"}, name="nextjs25_og"),
    path("robots.txt", views.nextjs25_public_asset, {"path": "robots.txt"}, name="nextjs25_robots"),
    path("sitemap-posts.xml", views.nextjs25_public_asset, {"path": "sitemap-posts.xml"}, name="nextjs25_sitemap_posts"),
    path("sitemap.xml", views.nextjs25_public_asset, {"path": "sitemap.xml"}, name="nextjs25_sitemap"),
    path("sw.js", views.nextjs25_public_asset, {"path": "sw.js"}, name="nextjs25_service_worker"),
    re_path(r"^(?P<path>sample-data/[\w.-]+)$", views.nextjs25_public_asset, name="nextjs25_sample_data"),
    path("data/<str:area>/<path:path>", views.legacy_data_asset, name="legacy_data_asset"),
    path("index.txt", views.nextjs25_root_text_payload, {"template_path": "index"}, name="nextjs25_index_text"),
    path("rss/<str:bo_table>", views.nextjs25_board_rss, name="nextjs25_board_rss"),
    path("mobile", views.legacy_mobile_route, {"legacy_path": ""}, name="legacy_mobile_root"),
    path("mobile/", views.legacy_mobile_route, {"legacy_path": ""}, name="legacy_mobile_root_slash"),
    re_path(r"^mobile/(?P<legacy_path>.+?)/?$", views.legacy_mobile_route, name="legacy_mobile_route"),
    re_path(r"^bbs/(?P<legacy_path>.+\.php)$", views.legacy_bbs_php_route, name="legacy_bbs_php_route"),
    re_path(r"^shop/(?P<legacy_path>.+\.php)$", views.legacy_shop_php_route, name="legacy_shop_php_route"),
    # Board pages: /bbs (list of boards), /bbs/<bo_table>, /bbs/<bo_table>/<wr_id|seo-title|write>.
    # The bbs/*.php pattern above keeps the Gnuboard5 file addresses working.
    path("bbs.txt", views.nextjs25_root_text_payload, {"template_path": "boards"}, name="nextjs25_bbs_index_text"),
    re_path(r"^bbs/?$", views.nextjs25_root_theme, {"template_path": "boards"}, name="nextjs25_bbs_index"),
    re_path(
        r"^bbs/(?P<bo_table>[^/]+)(?:/(?P<board_path>[^/]+))?\.txt$",
        views.nextjs25_board_text_payload,
        name="nextjs25_board_text_payload",
    ),
    re_path(r"^bbs/(?P<bo_table>[^/]+)/(?P<board_path>[^/]+)/?$", views.nextjs25_board_theme, name="nextjs25_board_theme_path"),
    re_path(r"^bbs/(?P<bo_table>[^/]+)/?$", views.nextjs25_board_theme, name="nextjs25_board_theme"),
    re_path(
        r"^(?P<template_path>(?:login(?:/social-callback)?|register(?:/result)?|forgot-password|email-certify|boards(?:/.*)?|content/[^/]+|members/[^/]+|mypage(?:/.*)?|shop(?:/.*)?|faq|polls|recent|search|baby|offline))\.txt$",
        views.nextjs25_root_text_payload,
        name="nextjs25_root_text_payload",
    ),
    path("shop/products", views.nextjs25_shop_products_canonical_redirect, name="nextjs25_shop_products_canonical"),
    path("shop/products/", views.nextjs25_shop_products_canonical_redirect, name="nextjs25_shop_products_canonical_slash"),
    re_path(
        r"^shop/products/(?P<product_path>.+?)/?$",
        views.nextjs25_shop_products_canonical_redirect,
        name="nextjs25_shop_product_canonical",
    ),
    re_path(
        r"^shop/categories/(?P<category_path>.+?)/?$",
        views.nextjs25_shop_categories_canonical_redirect,
        name="nextjs25_shop_category_canonical",
    ),
    re_path(r"^boards/?$", views.nextjs25_boards_canonical_redirect, name="nextjs25_boards_index_canonical"),
    re_path(
        r"^boards/(?P<board_path>.+?)/?$",
        views.nextjs25_boards_canonical_redirect,
        name="nextjs25_board_canonical",
    ),
    re_path(
        r"^(?P<template_path>(?:login(?:/social-callback)?|register(?:/result)?|forgot-password|email-certify|boards(?:/.*)?|content/[^/]+|members/[^/]+|mypage(?:/.*)?|shop(?:/.*)?|faq|polls|recent|search|baby|offline))/?$",
        views.nextjs25_root_theme,
        name="nextjs25_root_theme",
    ),
    path("nextjs25/", views.nextjs25_theme, name="nextjs25_theme"),
    path("nextjs25/<path:template_path>", views.nextjs25_theme, name="nextjs25_theme_path"),
    path("nextjs_default/", views.nextjs25_theme, name="nextjs_default_theme"),
    path("nextjs_default/<path:template_path>", views.nextjs25_theme, name="nextjs_default_theme_path"),
    re_path(
        r"^(?P<bo_table>(?!(?:admin|api|api-auth|_next|media|static|nextjs25|nextjs_default|bbs|user|users|editor|adm|__debug__)$)[^/]+)(?:/(?P<board_path>[^/]+))?\.txt$",
        views.nextjs25_board_text_payload,
        name="nextjs25_short_board_text_payload",
    ),
    # The old short board addresses redirect to /bbs/... (permanently).
    re_path(
        r"^(?P<bo_table>(?!(?:admin|api|api-auth|_next|media|static|nextjs25|nextjs_default|bbs|user|users|editor|adm|__debug__)$)[^/]+)/(?P<board_path>[^/]+)/?$",
        views.nextjs25_short_board_redirect,
        name="nextjs25_short_board_redirect_path",
    ),
    re_path(
        r"^(?P<bo_table>(?!(?:admin|api|api-auth|_next|media|static|nextjs25|nextjs_default|bbs|user|users|editor|adm|__debug__)$)[^/]+)/?$",
        views.nextjs25_short_board_redirect,
        name="nextjs25_short_board_redirect",
    ),
    path("adm/_ajax_/add_menu/", add_menu_form, name="add_menu_form"),
]
