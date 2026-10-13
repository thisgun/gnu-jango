from datetime import timedelta

from django import template
from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from gnu_jango.core.models import MailCampaign, MailSendLog, SearchKeyword, VisitLog
from gnu_jango.api.community_common import GENERAL_QA_PRODUCT_ID
from gnu_jango.shop.models import ShopOrder, ShopOrderData, ShopPersonalPay, ShopQA
from gnu_jango.users.models import Profile, User_Memo, User_Point
from gnu_jango.utils.admin_display import format_number, money_sum

register = template.Library()
User = get_user_model()

ADMIN_OPS_SUMMARY_CACHE_KEY = "admin_ops_summary"
ADMIN_OPS_SUMMARY_TTL = 60  # seconds


def local_datetime(value):
    if not value:
        return "-"
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")


def order_tone(order):
    if order.od_misu and order.od_misu > 0:
        return "warning"
    if order.od_cancel_price and order.od_cancel_price > 0:
        return "danger"
    if order.od_receipt_price and order.od_receipt_price > 0:
        return "success"
    return "neutral"


def order_row(order):
    return {
        "id": order.od_id,
        "name": order.od_name or "-",
        "status": order.od_status or "-",
        "settle_case": order.od_settle_case or "-",
        "pg": order.od_pg or "-",
        "receipt": format_number(order.od_receipt_price),
        "outstanding": format_number(order.od_misu),
        "time": local_datetime(order.od_datetime),
        "tone": order_tone(order),
    }


def member_tone(user):
    if not user.is_active:
        return "danger"
    if user.is_superuser or user.is_staff:
        return "info"
    return "success"


def member_status(user):
    if not user.is_active:
        return _("Inactive")
    if user.is_superuser:
        return _("Superuser")
    if user.is_staff:
        return _("Staff")
    return _("Active member")


def member_row(user):
    try:
        profile = user.profile
    except Profile.DoesNotExist:
        profile = None
    return {
        "id": user.pk,
        "username": user.get_username(),
        "nickname": getattr(profile, "nickname", "") or user.get_username(),
        "email": user.email or "-",
        "level": format_number(getattr(profile, "user_level", 0)),
        "point": format_number(getattr(profile, "user_point", 0)),
        "joined": local_datetime(user.date_joined),
        "status": member_status(user),
        "tone": member_tone(user),
    }


def point_tone(point):
    if point.po_expired:
        return "danger"
    if point.po_point and point.po_point < 0:
        return "warning"
    if point.po_point and point.po_point > 0:
        return "success"
    return "neutral"


def point_row(point):
    username = point.user.get_username() if point.user_id and point.user else "-"
    return {
        "id": point.pk,
        "username": username,
        "content": point.po_content or "-",
        "point": format_number(point.po_point),
        "balance": format_number(point.po_mb_point),
        "time": local_datetime(point.po_datetime),
        "tone": point_tone(point),
    }


def memo_row(memo):
    username = memo.user.get_username() if memo.user_id and memo.user else "-"
    return {
        "id": memo.pk,
        "username": username,
        "type": memo.me_type or "-",
        "status": _("Read") if memo.me_read_datetime else _("Unread"),
        "time": local_datetime(memo.me_send_datetime),
        "tone": "success" if memo.me_read_datetime else "warning",
    }


def queue_item(label, value, hint, url, tone, icon):
    return {
        "label": label,
        "value": format_number(value),
        "hint": hint,
        "url": url,
        "tone": tone,
        "icon": icon,
    }


def safety_item(label, value, hint, url, tone, icon):
    return {
        "label": label,
        "value": format_number(value),
        "hint": hint,
        "url": url,
        "tone": tone,
        "icon": icon,
    }


@register.simple_tag
def admin_ops_summary():
    # The dashboard summary runs ~30 aggregate queries; cache it briefly so a
    # busy admin index does not re-run them on every page load. The data is
    # global (not per-user), so a single shared key is correct.
    cached = cache.get(ADMIN_OPS_SUMMARY_CACHE_KEY)
    if cached is None:
        cached = _build_admin_ops_summary()
        cache.set(ADMIN_OPS_SUMMARY_CACHE_KEY, cached, ADMIN_OPS_SUMMARY_TTL)
    return cached


def _build_admin_ops_summary():
    today = timezone.localdate()
    now = timezone.now()
    orders = ShopOrder.objects.all()
    today_orders = orders.filter(od_datetime__date=today)
    outstanding_orders = orders.filter(od_misu__gt=0)
    pending_shipping = orders.filter(od_receipt_price__gt=0, od_cancel_price__lte=0).filter(od_invoice="")
    cash_receipt_orders = orders.exclude(od_cash_no="")
    raw_logs = ShopOrderData.objects.all()
    personal_pays = ShopPersonalPay.objects.all()
    pending_personal_pays = personal_pays.filter(active=True, pp_receipt_price__lte=0)
    visits = VisitLog.objects.all()
    today_visits = visits.filter(created_at__date=today)
    admin_visits = today_visits.filter(is_staff_area=True)
    search_keywords = SearchKeyword.objects.all()
    today_search_keywords = search_keywords.filter(last_searched_at__date=today)
    mail_campaigns = MailCampaign.objects.all()
    today_mail_campaigns = mail_campaigns.filter(created_at__date=today)
    failed_mail_logs = MailSendLog.objects.filter(status="failed")
    members = User.objects.select_related("profile").all()
    today_members = members.filter(date_joined__date=today)
    active_members = members.filter(is_active=True)
    blocked_members = members.filter(is_active=False)
    staff_members = members.filter(is_staff=True)
    superusers = members.filter(is_superuser=True)
    groups = Group.objects.prefetch_related("permissions").all()
    staff_without_group = staff_members.filter(is_superuser=False, groups__isnull=True).distinct()
    recent_admin_actions = LogEntry.objects.select_related("user", "content_type").order_by("-action_time")
    recent_delete_actions = recent_admin_actions.filter(action_flag=DELETION)
    outstanding_tokens = OutstandingToken.objects.all()
    blacklisted_tokens = BlacklistedToken.objects.all()
    points = User_Point.objects.select_related("user").all()
    expired_points = points.filter(po_expired__gt=0)
    point_expiration_attention = points.filter(
        Q(po_expired__gt=0)
        | Q(
            po_expired=0,
            po_expire_date__isnull=False,
            po_expire_date__lte=now + timedelta(days=7),
        )
    )
    unread_memos = User_Memo.objects.select_related("user").filter(me_type="recv", me_read_datetime__isnull=True)
    waiting_inquiries = ShopQA.objects.filter(product_id=GENERAL_QA_PRODUCT_ID, iq_answer="")

    return {
        "metrics": [
            {
                "label": _("Today orders"),
                "value": format_number(today_orders.count()),
                "hint": _("%(amount)s received") % {"amount": format_number(money_sum(today_orders, "od_receipt_price"))},
                "url": "/admin/shop/shoporder/?od_datetime__day=%s" % today.day,
                "tone": "info",
            },
            {
                "label": _("Outstanding"),
                "value": format_number(outstanding_orders.count()),
                "hint": _("%(amount)s unpaid") % {"amount": format_number(money_sum(outstanding_orders, "od_misu"))},
                "url": "/admin/shop/shoporder/?receipt_state=outstanding",
                "tone": "warning",
            },
            {
                "label": _("Shipping queue"),
                "value": format_number(pending_shipping.count()),
                "hint": _("Paid orders without invoice"),
                "url": "/admin/shop/shoporder/?shipping_state=waiting_invoice",
                "tone": "neutral",
            },
            {
                "label": _("Cash receipts"),
                "value": format_number(cash_receipt_orders.count()),
                "hint": _("%(amount)s issued") % {"amount": format_number(money_sum(cash_receipt_orders, "od_receipt_price"))},
                "url": "/admin/shop/shoporder/?receipt_state=cash",
                "tone": "success",
            },
            {
                "label": _("Personal pay due"),
                "value": format_number(pending_personal_pays.count()),
                "hint": _("%(amount)s requested") % {"amount": format_number(money_sum(pending_personal_pays, "pp_price"))},
                "url": "/admin/shop/shoppersonalpay/",
                "tone": "warning",
            },
            {
                "label": _("Today members"),
                "value": format_number(today_members.count()),
                "hint": _("%(count)s active members") % {"count": format_number(active_members.count())},
                "url": "/admin/auth/user/",
                "tone": "info",
            },
            {
                "label": _("Unread memos"),
                "value": format_number(unread_memos.count()),
                "hint": _("%(count)s point logs") % {"count": format_number(points.count())},
                "url": "/admin/users/user_memo/?memo_state=unread",
                "tone": "warning" if unread_memos.exists() else "success",
            },
            {
                "label": _("Today visits"),
                "value": format_number(today_visits.count()),
                "hint": _("%(count)s admin visits") % {"count": format_number(admin_visits.count())},
                "url": "/admin/core/visitlog/reports/",
                "tone": "info",
            },
            {
                "label": _("Search keywords"),
                "value": format_number(search_keywords.count()),
                "hint": _("%(count)s searched today") % {"count": format_number(today_search_keywords.count())},
                "url": "/admin/core/searchkeyword/reports/",
                "tone": "neutral",
            },
        ],
        "action_queue": [
            queue_item(
                _("Outstanding orders"),
                outstanding_orders.count(),
                _("%(amount)s unpaid") % {"amount": format_number(money_sum(outstanding_orders, "od_misu"))},
                "/admin/shop/shoporder/?receipt_state=outstanding",
                "warning" if outstanding_orders.exists() else "success",
                "priority_high",
            ),
            queue_item(
                _("Shipping follow-up"),
                pending_shipping.count(),
                _("Paid orders without invoice"),
                "/admin/shop/shoporder/?shipping_state=waiting_invoice",
                "warning" if pending_shipping.exists() else "success",
                "local_shipping",
            ),
            queue_item(
                _("Personal pay due"),
                pending_personal_pays.count(),
                _("%(amount)s requested") % {"amount": format_number(money_sum(pending_personal_pays, "pp_price"))},
                "/admin/shop/shoppersonalpay/?personal_pay_state=due",
                "warning" if pending_personal_pays.exists() else "success",
                "payments",
            ),
            queue_item(
                "답변 대기 1:1 문의",
                waiting_inquiries.count(),
                "답변하지 않은 1:1 문의",
                "/admin/shop/generalinquiry/?answer_status=pending",
                "warning" if waiting_inquiries.exists() else "success",
                "support_agent",
            ),
            queue_item(
                _("Unread memos"),
                unread_memos.count(),
                _("Member messages waiting for review"),
                "/admin/users/user_memo/?memo_state=unread",
                "warning" if unread_memos.exists() else "success",
                "mail",
            ),
            queue_item(
                _("Blocked members"),
                blocked_members.count(),
                _("Inactive accounts that may need review"),
                "/admin/auth/user/?is_active__exact=0",
                "danger" if blocked_members.exists() else "success",
                "block",
            ),
            queue_item(
                _("Point expirations"),
                point_expiration_attention.count(),
                _("%(count)s already expired") % {"count": format_number(expired_points.count())},
                "/admin/users/user_point/?point_state=expiration_attention",
                "warning" if point_expiration_attention.exists() else "success",
                "hourglass_bottom",
            ),
        ],
        "member_metrics": [
            {
                "label": _("Total members"),
                "value": format_number(members.count()),
                "hint": _("%(count)s joined today") % {"count": format_number(today_members.count())},
                "url": "/admin/auth/user/",
                "tone": "info",
            },
            {
                "label": _("Active members"),
                "value": format_number(active_members.count()),
                "hint": _("%(count)s blocked") % {"count": format_number(blocked_members.count())},
                "url": "/admin/auth/user/?is_active__exact=1",
                "tone": "success",
            },
            {
                "label": _("Staff members"),
                "value": format_number(staff_members.count()),
                "hint": _("Admin access accounts"),
                "url": "/admin/auth/user/?is_staff__exact=1",
                "tone": "neutral",
            },
            {
                "label": _("Point ledger"),
                "value": format_number(points.count()),
                "hint": _("%(amount)s current points") % {"amount": format_number(money_sum(Profile.objects.all(), "user_point"))},
                "url": "/admin/users/user_point/",
                "tone": "info",
            },
        ],
        "traffic_metrics": [
            {
                "label": _("Today visits"),
                "value": format_number(today_visits.count()),
                "hint": _("%(count)s unique IPs") % {
                    "count": format_number(today_visits.exclude(ip_address__isnull=True).values("ip_address").distinct().count())
                },
                "url": "/admin/core/visitlog/reports/",
                "tone": "info",
            },
            {
                "label": _("Mobile visits"),
                "value": format_number(today_visits.filter(device="mobile").count()),
                "hint": _("Mobile traffic today"),
                "url": "/admin/core/visitlog/?device__exact=mobile",
                "tone": "neutral",
            },
            {
                "label": _("Search keywords"),
                "value": format_number(search_keywords.count()),
                "hint": _("%(count)s searched today") % {"count": format_number(today_search_keywords.count())},
                "url": "/admin/core/searchkeyword/reports/",
                "tone": "success" if search_keywords.exists() else "neutral",
            },
            {
                "label": _("Mail tools"),
                "value": format_number(today_mail_campaigns.count()),
                "hint": _("%(count)s failed sends") % {"count": format_number(failed_mail_logs.count())},
                "url": "/admin/core/notification/mail-tools/",
                "tone": "warning" if failed_mail_logs.exists() else "info",
            },
            {
                "label": "메일 캠페인",
                "value": format_number(mail_campaigns.count()),
                "hint": _("%(count)s members with email") % {
                    "count": format_number(members.exclude(email="").exclude(email__isnull=True).count())
                },
                "url": "/admin/core/mailcampaign/",
                "tone": "success" if mail_campaigns.exists() else "neutral",
            },
        ],
        "governance_metrics": [
            {
                "label": _("Super admins"),
                "value": format_number(superusers.count()),
                "hint": _("Full-access accounts"),
                "url": "/admin/auth/user/?is_superuser__exact=1",
                "tone": "danger" if superusers.count() > 1 else "success",
            },
            {
                "label": _("Staff accounts"),
                "value": format_number(staff_members.count()),
                "hint": _("%(count)s without group") % {"count": format_number(staff_without_group.count())},
                "url": "/admin/auth/user/?is_staff__exact=1",
                "tone": "warning" if staff_without_group.exists() else "info",
            },
            {
                "label": _("Permission groups"),
                "value": format_number(groups.count()),
                "hint": _("Role-based admin access"),
                "url": "/admin/auth/group/",
                "tone": "success" if groups.exists() else "warning",
            },
            {
                "label": _("Recent admin actions"),
                "value": format_number(recent_admin_actions.count()),
                "hint": _("%(count)s delete logs") % {"count": format_number(recent_delete_actions.count())},
                "url": "#recent-actions-module",
                "tone": "warning" if recent_delete_actions.exists() else "neutral",
            },
        ],
        "safety_checks": [
            safety_item(
                _("Group missing staff"),
                staff_without_group.count(),
                _("Assign every non-superuser staff account to an operations role."),
                "/admin/auth/user/?is_staff__exact=1",
                "warning" if staff_without_group.exists() else "success",
                "admin_panel_settings",
            ),
            safety_item(
                _("Permission groups"),
                groups.count(),
                _("Use groups for shop, community, support, and operations roles."),
                "/admin/auth/group/",
                "success" if groups.exists() else "warning",
                "groups",
            ),
            safety_item(
                _("Admin delete log"),
                recent_delete_actions.count(),
                _("Review destructive actions before closing daily operations."),
                "#recent-actions-module",
                "warning" if recent_delete_actions.exists() else "success",
                "delete_forever",
            ),
            safety_item(
                _("Token blacklist"),
                blacklisted_tokens.count(),
                _("%(count)s outstanding tokens") % {"count": format_number(outstanding_tokens.count())},
                "/admin/token_blacklist/outstandingtoken/",
                "warning" if blacklisted_tokens.exists() else "neutral",
                "vpn_key",
            ),
        ],
        "role_recommendations": [
            {"role": _("Operations manager"), "scope": _("Orders, personal pay, settlement, receipts, delivery")},
            {"role": _("Shop manager"), "scope": _("Products, categories, coupons, reviews, product QA")},
            {"role": _("Community manager"), "scope": _("Boards, posts, comments, FAQ, content pages")},
            {"role": _("Support operator"), "scope": _("Member lookup, memo review, payment evidence without destructive deletes")},
        ],
        "workflows": [
            {
                "title": _("Order operations"),
                "icon": "receipt_long",
                "items": [
                    {"label": _("Orders"), "url": "/admin/shop/shoporder/"},
                    {"label": _("Order print"), "url": "/admin/shop/shoporder/order-print/"},
                    {"label": _("Products"), "url": "/admin/shop/shopproduct/"},
                    {"label": _("Coupons"), "url": "/admin/shop/shopcoupon/"},
                ],
            },
            {
                "title": _("Settlement"),
                "icon": "monitoring",
                "items": [
                    {"label": _("Settlement report"), "url": "/admin/shop/shoporder/reports/"},
                    {"label": _("Product sales rank"), "url": "/admin/shop/shoporder/sales-rank/"},
                    {"label": _("Payment logs"), "url": "/admin/shop/shoporderdata/"},
                    {"label": _("Personal pay"), "url": "/admin/shop/shoppersonalpay/"},
                ],
            },
            {
                "title": _("Traffic and communication"),
                "icon": "analytics",
                "items": [
                    {"label": _("Visit statistics"), "url": "/admin/core/visitlog/reports/"},
                    {"label": _("Search keyword statistics"), "url": "/admin/core/searchkeyword/reports/"},
                    {"label": _("Mail tools"), "url": "/admin/core/notification/mail-tools/"},
                    {"label": "메일 캠페인", "url": "/admin/core/mailcampaign/"},
                    {"label": "발송 로그", "url": "/admin/core/mailsendlog/"},
                    {"label": _("Notifications"), "url": "/admin/core/notification/"},
                ],
            },
            {
                "title": _("Community"),
                "icon": "forum",
                "items": [
                    {"label": _("Boards"), "url": "/admin/bbs/board/"},
                    {"label": _("Posts"), "url": "/admin/bbs/post/"},
                    {"label": _("Members"), "url": "/admin/auth/user/"},
                    {"label": _("Profiles"), "url": "/admin/users/profile/"},
                    {"label": _("Member points"), "url": "/admin/users/user_point/"},
                    {"label": _("Member memos"), "url": "/admin/users/user_memo/"},
                    {"label": _("Member scraps"), "url": "/admin/users/user_scrap/"},
                ],
            },
        ],
        "watch_orders": [order_row(order) for order in outstanding_orders.order_by("-od_datetime")[:6]],
        "recent_orders": [order_row(order) for order in orders.order_by("-od_datetime")[:6]],
        "recent_members": [member_row(user) for user in members.order_by("-date_joined")[:6]],
        "recent_points": [point_row(point) for point in points.order_by("-po_datetime", "-pk")[:6]],
        "unread_memos": [memo_row(memo) for memo in unread_memos.order_by("-me_send_datetime", "-pk")[:6]],
        "recent_logs": [
            {
                "id": log.log_id,
                "order_id": log.od_id or "-",
                "pg": log.dt_pg or "-",
                "time": local_datetime(log.dt_time),
            }
            for log in raw_logs.order_by("-dt_time")[:6]
        ],
        "popular_paths": [
            {
                "path": row["path"],
                "count": format_number(row["count"]),
            }
            for row in visits.values("path").annotate(count=Count("id")).order_by("-count", "path")[:6]
        ],
        "popular_keywords": [
            {
                "keyword": keyword.keyword,
                "source": keyword.source,
                "count": format_number(keyword.count),
            }
            for keyword in search_keywords.order_by("-count", "keyword")[:6]
        ],
    }
