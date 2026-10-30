"""Shop mails, after youngcart: the order mails of shop/ordermail1.inc.php and ordermail2.inc.php
(a notice to the shop admin and an order summary to the customer), the processing mail of
adm/shop_admin/ordermail.inc.php (입금 확인 / 배송 안내), the product recommendation of
shop/itemrecommendmail.php, the 배송완료 안내 of the shipment tracking (not in youngcart) and the
status mails of the customer's return / exchange requests (shop/returns.py).

Every mail obeys cf_email_use (기본환경설정 > 메일발송 사용). Order mails are queued with
transaction.on_commit so they only leave once the order is saved, and a mail server failure is
logged, never raised: an order or a status change must not fail because a mail could not be sent.
"""

import logging
from email.utils import formataddr

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Value
from django.db.models.functions import Concat
from django.template.loader import render_to_string
from django.utils import timezone

from gnu_jango.config.models import Config
from gnu_jango.defaults import CONFIGS
from gnu_jango.shop.models import ShopOrder

logger = logging.getLogger(__name__)

STATUS_PAID = "입금"
STATUS_SHIPPING = "배송"
STATUS_MAIL_TARGETS = {STATUS_PAID, STATUS_SHIPPING}
# youngcart ordermail.inc.php shows these line states in the customer's words
LINE_STATUS_LABELS = {"준비": "상품준비중", "배송": "배송중"}


def config_text(name, default=""):
    value = Config.objects.filter(name=name).values_list("value", flat=True).first()
    return default if value is None else str(value).strip()


def mail_enabled():
    """cf_email_use: youngcart sends no mail at all while it is off."""
    default = CONFIGS.get("cf_email_use", (1,))[0]
    try:
        return int(config_text("cf_email_use", str(default)) or 0) > 0
    except ValueError:
        return False


def site_title():
    return config_text("cf_title") or "GNU Jango"


def admin_email():
    return config_text("cf_admin_email")


def sender_address():
    """cf_admin_email_name <cf_admin_email>, the sender of youngcart's shop mails."""
    email = admin_email()
    if not email:
        return settings.DEFAULT_FROM_EMAIL
    return formataddr((config_text("cf_admin_email_name") or site_title(), email))


def site_link(path, request=None):
    """An absolute link to a page of the (Next.js) site, "" when no origin is known."""
    site = str(getattr(settings, "SOCIAL_APP_BASE_URL", "") or "").rstrip("/")
    if site:
        return f"{site}{path}"
    if request is not None:
        return request.build_absolute_uri(path)
    return ""


def absolute_asset_url(url, request=None):
    url = str(url or "").strip()
    if not url or url.lower().startswith(("https://", "http://")):
        return url
    if request is not None:
        return request.build_absolute_uri(url)
    return site_link(url) if url.startswith("/") else ""


def single_line(value, limit=200):
    """A header-safe one-line text (Django refuses a subject with a line break)."""
    return " ".join(str(value or "").split())[:limit]


def send_shop_mail(subject, template, context, recipients, *, reply_to=None):
    """Render ``shop/mail/<template>.txt`` and ``.html`` and send them. Returns whether it went out."""
    recipients = [address for address in recipients if address]
    if not recipients:
        return False
    context = {"site_title": site_title(), **context}
    try:
        text_body = render_to_string(f"shop/mail/{template}.txt", context)
        html_body = render_to_string(f"shop/mail/{template}.html", context)
        message = EmailMultiAlternatives(
            single_line(subject),
            text_body,
            sender_address(),
            recipients,
            reply_to=[address for address in (reply_to or []) if address] or None,
        )
        message.attach_alternative(html_body, "text/html")
        message.send()
    except Exception:  # noqa: BLE001 - a mail server failure must not break the shop flow
        logger.exception("Shop mail %s could not be sent", template)
        return False
    return True


def order_link(order):
    path = f"/shop/orders/{order.od_id}" if order.user_id else f"/shop/orders/{order.od_id}?uid={order.uid}"
    return site_link(path)


def order_lines(order):
    lines = []
    for item in order.items.order_by("ct_id"):
        unit = item.io_price if item.io_type == 1 else item.ct_price + item.io_price
        lines.append(
            {
                "it_id": item.it_id,
                "it_name": item.it_name,
                "option": item.ct_option if item.ct_option and item.ct_option != item.it_name else "",
                "qty": item.ct_qty,
                "unit_price": max(0, unit),
                "total": max(0, unit) * item.ct_qty,
                "status": LINE_STATUS_LABELS.get(item.ct_status, item.ct_status),
            }
        )
    return lines


def order_totals(order):
    from gnu_jango.shop.order_flow import order_cart_coupon

    coupon = order_cart_coupon(order) + int(order.od_coupon or 0) + int(order.od_send_coupon or 0)
    send_cost = int(order.od_send_cost or 0) + int(order.od_send_cost2 or 0)
    total = max(0, int(order.od_cart_price or 0) - int(order.od_cancel_price or 0) + send_cost - coupon)
    return {"cart_price": order.od_cart_price, "send_cost": send_cost, "coupon": coupon, "total": total}


def order_context(order):
    from gnu_jango.api.shop_payments import settle_case_is_bank

    return {
        "order": order,
        "lines": order_lines(order),
        "totals": order_totals(order),
        "is_bank": settle_case_is_bank(order.od_settle_case),
        "settle_case": "무통장입금" if settle_case_is_bank(order.od_settle_case) else order.od_settle_case,
        "order_url": order_link(order),
        "ordered_at": timezone.localtime(order.od_datetime).strftime("%Y-%m-%d %H:%M") if order.od_datetime else "",
    }


def send_order_placed_mails(order_id):
    """youngcart ordermail2.inc.php: the admin's new-order notice and the customer's order summary."""
    if not mail_enabled():
        return 0
    order = ShopOrder.objects.filter(pk=order_id).first()
    if order is None:
        return 0
    context = order_context(order)
    title = site_title()
    sent = 0
    if send_shop_mail(
        f"{title} - 주문 알림 메일 ({order.od_name})",
        "order_admin",
        context,
        [admin_email()],
        reply_to=[order.od_email],
    ):
        sent += 1
    if send_shop_mail(f"{title} - 주문 내역 안내 메일", "order_customer", context, [order.od_email]):
        sent += 1
    return sent


def send_order_status_mail(order_id, status):
    """adm/shop_admin/ordermail.inc.php: the customer's 결제/배송 내역 안내 once the shop records the
    deposit (입금) or the shipment (배송). Sent only when there is a receipt or an invoice to tell."""
    if status not in STATUS_MAIL_TARGETS or not mail_enabled():
        return False
    order = ShopOrder.objects.filter(pk=order_id).first()
    if order is None or not order.od_email:
        return False
    has_receipt = int(order.od_receipt_price or 0) > 0 or int(order.od_receipt_point or 0) > 0
    has_delivery = bool(order.od_delivery_company and order.od_invoice)
    if status == STATUS_PAID and not has_receipt:
        return False
    if status == STATUS_SHIPPING and not has_delivery:
        return False
    context = {
        **order_context(order),
        "status": status,
        "has_receipt": has_receipt,
        "has_delivery": has_delivery,
    }
    if not send_shop_mail(f"{site_title()} - {order.od_name}님 주문 처리 내역 안내", "order_status", context, [order.od_email]):
        return False
    # youngcart keeps a note of the mail in the shop memo
    note = f"{timezone.localtime().strftime('%Y-%m-%d %H:%M:%S')} - 결제/배송내역 메일발송\n"
    ShopOrder.objects.filter(pk=order.pk).update(od_shop_memo=Concat(Value(note), "od_shop_memo"))
    return True


def send_order_delivered_mail(order_id):
    """배송완료 안내: the shipment tracking found the order delivered and moved it to 완료
    (shop/delivery_tracking.py, only with 배송완료 시 주문 완료 처리 on)."""
    from gnu_jango.shop.models import ShopShipmentTracking

    if not mail_enabled():
        return False
    order = ShopOrder.objects.filter(pk=order_id).first()
    if order is None or not order.od_email:
        return False
    tracking = ShopShipmentTracking.objects.filter(order_id=order.pk).first()
    delivered_at = ""
    location = ""
    if tracking and tracking.delivered_at:
        delivered_at = timezone.localtime(tracking.delivered_at).strftime("%Y-%m-%d %H:%M")
    if tracking and tracking.events and isinstance(tracking.events[-1], dict):
        location = single_line(tracking.events[-1].get("location"))
    context = {**order_context(order), "delivered_at": delivered_at, "delivered_location": location}
    subject = f"{site_title()} - {order.od_name}님 주문 상품 배송완료 안내"
    return send_shop_mail(subject, "order_delivered", context, [order.od_email])


def _run_safely(callback, *args):
    try:
        callback(*args)
    except Exception:  # noqa: BLE001 - never let a mail break the order flow
        logger.exception("Shop mail callback %s failed for %s", callback.__name__, args)


def send_subscription_mail(subscription_id, title, body, path):
    """정기구독 notices (결제 예정, 결제 완료/실패, 일시정지, 건너뜀, 해지) to the subscriber, with a
    link to the subscription (or the order a charge made)."""
    from gnu_jango.shop.models import ShopSubscription

    if not mail_enabled():
        return False
    subscription = ShopSubscription.objects.select_related("user").filter(pk=subscription_id).first()
    if subscription is None:
        return False
    recipient = subscription.od_email or subscription.user.email
    context = {
        "subscription": subscription,
        "title": title,
        "body": body,
        "link": site_link(path),
        "name": subscription.od_name or subscription.user.get_username(),
    }
    return send_shop_mail(f"[{site_title()}] {title}", "subscription_notice", context, [recipient])


def queue_subscription_mail(subscription, *, title, body, path):
    subscription_id = subscription.pk
    transaction.on_commit(lambda: _run_safely(send_subscription_mail, subscription_id, title, body, path))


def queue_order_placed_mails(order):
    """Send the order mails once the surrounding transaction commits."""
    order_id = order.pk
    transaction.on_commit(lambda: _run_safely(send_order_placed_mails, order_id))


def queue_order_status_mail(order, status):
    if status not in STATUS_MAIL_TARGETS:
        return
    order_id = order.pk
    transaction.on_commit(lambda: _run_safely(send_order_status_mail, order_id, status))


def queue_order_delivered_mail(order):
    order_id = order.pk
    transaction.on_commit(lambda: _run_safely(send_order_delivered_mail, order_id))


def send_return_request_mails(request_id, status):
    """A return or exchange request (shop/returns.py) moved to ``status``: the customer hears of
    every change, the shop of a new request. ``status`` is the one queued, so a later change
    committed before this runs does not mail the same status twice."""
    from gnu_jango.shop.models import ShopReturnRequest
    from gnu_jango.shop.returns import notification_body, notification_title

    if not mail_enabled():
        return 0
    request = ShopReturnRequest.objects.select_related("order").filter(pk=request_id).first()
    if request is None:
        return 0
    order = request.order
    request.status = status
    context = {
        **order_context(order),
        "request": request,
        "title": notification_title(request),
        "summary": notification_body(request),
        "request_lines": list(request.lines.order_by("pk")),
    }
    sent = 0
    if send_shop_mail(f"{site_title()} - {notification_title(request)}", "return_status", context, [order.od_email]):
        sent += 1
    if status == ShopReturnRequest.STATUS_REQUESTED and send_shop_mail(
        f"{site_title()} - {request.get_kind_display()} 신청 알림 ({order.od_name})",
        "return_admin",
        context,
        [admin_email()],
        reply_to=[order.od_email],
    ):
        sent += 1
    return sent


def queue_return_request_mails(request):
    request_id, status = request.pk, request.status
    transaction.on_commit(lambda: _run_safely(send_return_request_mails, request_id, status))


def send_product_recommend_mail(request, product, sender, to_email, subject, content):
    """shop/itemrecommendmail.php: a member recommends a product to one address.

    The mail goes out from the shop's sender address (a member's own address as the From would
    fail SPF/DMARC) with Reply-To set to the member, and every text the member wrote is escaped
    by the template."""
    from gnu_jango.api.shop_common import product_image_url

    member_name = (
        getattr(getattr(sender, "profile", None), "nickname", "")
        or getattr(getattr(sender, "profile", None), "realname", "")
        or sender.first_name
        or sender.get_username()
    )
    context = {
        "product": product,
        "product_url": site_link(f"/shop/products/{product.it_id}", request),
        "image_url": absolute_asset_url(product_image_url(product), request),
        "member_name": member_name,
        "subject": subject,
        "content": content,
    }
    return send_shop_mail(
        f"[{site_title()}] {subject}",
        "product_recommend",
        context,
        [to_email],
        reply_to=[sender.email],
    )
