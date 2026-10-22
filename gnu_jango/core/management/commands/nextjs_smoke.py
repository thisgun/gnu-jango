import argparse
import base64
import hashlib
import json
import os
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from gnu_jango.bbs.models import Post_scrap
from gnu_jango.config.models import Config
from gnu_jango.core.models import Poll, PollChoice, PollComment, PollVote
from gnu_jango.shop.inventory import cancel_order_with_stock_restore
from gnu_jango.shop.item_info import article_title, parse_item_info_value
from gnu_jango.shop.order_points import item_status_update, take_back_order_points
from gnu_jango.shop.models import ShopCoupon, ShopCouponLog, ShopCouponZone, ShopOrder, ShopOrderData, ShopOrderItem, ShopPersonalPay, ShopProduct, ShopQA, ShopReview
from gnu_jango.shop.product_relations import related_product_ids, replace_product_relations
from gnu_jango.users.models import Profile, User_Memo, User_Point


MEMBER_ID_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
SMOKE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


class Command(BaseCommand):
    help = "Django-backed compatibility bridge for Next.js local smoke PHP scripts."

    def add_arguments(self, parser):
        parser.add_argument("--script", required=True)
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--admin", action="store_true")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("extra_args", nargs=argparse.REMAINDER)

    def handle(self, *args, **options):
        script = options["script"]
        try:
            if script == "seed_nextjs_smoke_user.php":
                payload = self.seed_user(options)
            elif script == "cleanup_nextjs_smoke_stocksms.php":
                payload = self.cleanup_stocksms(options)
            elif script == "set_nextjs_smoke_product_stock.php":
                payload = self.set_product_stock(options)
            elif script == "set_nextjs_smoke_product_shipping.php":
                payload = self.set_product_shipping(options)
            elif script == "set_nextjs_smoke_product_qty_limits.php":
                payload = self.set_product_qty_limits(options)
            elif script == "set_nextjs_smoke_product_custom_html.php":
                payload = self.set_product_custom_html(options)
            elif script == "set_nextjs_smoke_product_info.php":
                payload = self.set_product_info(options)
            elif script == "set_nextjs_smoke_product_relation.php":
                payload = self.set_product_relation(options)
            elif script == "set_nextjs_smoke_review_policy.php":
                payload = self.set_review_policy(options)
            elif script == "set_nextjs_smoke_coupon_zone.php":
                payload = self.set_coupon_zone(options)
            elif script == "seed_nextjs_smoke_coupon_zone.php":
                payload = self.seed_coupon_zone(options)
            elif script == "cleanup_nextjs_smoke_coupons.php":
                payload = self.cleanup_coupons(options)
            elif script == "set_nextjs_smoke_event.php":
                payload = self.set_event(options)
            elif script == "cleanup_nextjs_smoke_orders.php":
                payload = self.cleanup_orders(options)
            elif script == "seed_nextjs_smoke_order.php":
                payload = self.seed_order(options)
            elif script == "mark_nextjs_smoke_order_paid.php":
                payload = self.mark_order_paid(options)
            elif script == "seed_nextjs_smoke_points.php":
                payload = self.seed_points(options)
            elif script == "cleanup_nextjs_smoke_points.php":
                payload = self.cleanup_points(options)
            elif script == "cleanup_nextjs_smoke_shop_content.php":
                payload = self.cleanup_shop_content(options)
            elif script == "cleanup_nextjs_smoke_memos.php":
                payload = self.cleanup_memos(options)
            elif script == "seed_nextjs_smoke_personalpay.php":
                payload = self.seed_personalpay(options)
            elif script == "mark_nextjs_smoke_personalpay_paid.php":
                payload = self.mark_personalpay_paid(options)
            elif script == "cleanup_nextjs_smoke_personalpay.php":
                payload = self.cleanup_personalpay(options)
            elif script == "seed_nextjs_smoke_poll.php":
                payload = self.seed_poll(options)
            elif script == "cleanup_nextjs_smoke_polls.php":
                payload = self.cleanup_polls(options)
            elif script == "cleanup_nextjs_smoke_qas.php":
                payload = self.cleanup_qas(options)
            elif script == "seed_nextjs_smoke_qa.php":
                payload = self.seed_qa(options)
            elif script == "cleanup_nextjs_smoke_scraps.php":
                payload = self.cleanup_scraps(options)
            else:
                raise CommandError(f"unsupported smoke script: {script}")
        except Exception as exc:
            if options.get("json"):
                self.stderr.write(json.dumps({"success": False, "message": str(exc)}, ensure_ascii=True))
                raise SystemExit(1)
            raise

        if options.get("json"):
            self.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
        else:
            self.stdout.write(payload.get("message", "ok"))

    def arg_value(self, options, name):
        prefix = f"--{name}="
        for value in options.get("extra_args") or []:
            if value.startswith(prefix):
                return value[len(prefix) :]
        return None

    def env_or_arg(self, options, arg_name, env_name, default):
        arg = self.arg_value(options, arg_name)
        if arg:
            return arg
        value = os.environ.get(env_name)
        return value if value else default

    def arg_flag(self, options, name):
        return f"--{name}" in (options.get("extra_args") or [])

    def int_arg(self, options, name, default=0):
        value = self.arg_value(options, name)
        try:
            return int(value) if value not in (None, "") else default
        except (TypeError, ValueError):
            raise CommandError(f"--{name} must be an integer.")

    def product(self, options):
        product_id = self.arg_value(options, "product-id") or os.environ.get("LOCAL_SMOKE_SHOP_PRODUCT_ID") or "1446772772"
        product = ShopProduct.objects.filter(pk=product_id).first()
        if not product:
            raise CommandError(f"product not found: {product_id}")
        return product

    def config_name(self, suffix):
        return f"nextjs_smoke_{suffix}"[:50]

    def read_json_config(self, suffix, default):
        item = Config.objects.filter(name=self.config_name(suffix)).first()
        if not item:
            return default
        try:
            return json.loads(item.value)
        except (TypeError, ValueError):
            return default

    def write_json_config(self, suffix, value):
        Config.objects.update_or_create(
            name=self.config_name(suffix),
            defaults={"value": json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:2000]},
        )

    def delete_config(self, suffix):
        Config.objects.filter(name=self.config_name(suffix)).delete()

    def ensure_data_file(self, area, name):
        path = Path(settings.MEDIA_ROOT) / "data" / area
        path.mkdir(parents=True, exist_ok=True)
        file_path = path / name
        if not file_path.exists():
            file_path.write_bytes(SMOKE_PNG)
        return file_path

    def cleanup_stocksms(self, options):
        product_id = self.arg_value(options, "product-id") or "1446772772"
        hp = self.arg_value(options, "hp") or ""
        rows = self.read_json_config("stocksms", [])
        kept = [
            row
            for row in rows
            if not (str(row.get("it_id")) == str(product_id) and (not hp or str(row.get("hp")) == str(hp)))
        ]
        self.write_json_config("stocksms", kept)
        return {"success": True, "deleted": len(rows) - len(kept), "product_id": product_id, "hp": hp}

    def set_product_stock(self, options):
        product = self.product(options)
        stock = self.arg_value(options, "stock")
        soldout = self.arg_value(options, "soldout")
        stock_sms = self.arg_value(options, "stock-sms")
        io_id = self.arg_value(options, "io-id")
        io_type = self.int_arg(options, "io-type", 0)
        previous = {
            "success": True,
            "product_id": product.it_id,
            "previous_stock": product.it_stock_qty,
            "previous_soldout": product.it_soldout or "0",
            "previous_stock_sms": product.it_stock_sms or "0",
        }

        if io_id:
            options_list = list(product.options or [])
            matched = False
            for item in options_list:
                if str(item.get("io_id")) == str(io_id) and int(item.get("io_type") or 0) == io_type:
                    previous["previous_stock"] = int(item.get("io_stock_qty") or 0)
                    if stock is not None:
                        item["io_stock_qty"] = self.int_arg(options, "stock", 0)
                    matched = True
                    break
            if not matched:
                raise CommandError(f"option not found: {io_id}")
            product.options = options_list
            product.save(update_fields=["options"])
            return previous

        update_fields = []
        if stock is not None:
            product.it_stock_qty = self.int_arg(options, "stock", 0)
            update_fields.append("it_stock_qty")
        if soldout is not None:
            product.it_soldout = "1" if self.int_arg(options, "soldout", 0) else ""
            update_fields.append("it_soldout")
        if stock_sms is not None:
            product.it_stock_sms = "1" if self.int_arg(options, "stock-sms", 0) else ""
            update_fields.append("it_stock_sms")
        if update_fields:
            product.save(update_fields=update_fields)
        return previous

    def set_product_shipping(self, options):
        product = self.product(options)
        previous = {
            "success": True,
            "product_id": product.it_id,
            "previous_type": product.it_sc_type,
            "previous_method": product.it_sc_method,
            "previous_price": product.it_sc_price,
            "previous_minimum": product.it_sc_minimum,
            "previous_qty": product.it_sc_qty,
        }
        product.it_sc_type = self.int_arg(options, "type", product.it_sc_type)
        product.it_sc_method = self.int_arg(options, "method", product.it_sc_method)
        product.it_sc_price = self.int_arg(options, "price", product.it_sc_price)
        product.it_sc_minimum = self.int_arg(options, "minimum", product.it_sc_minimum)
        product.it_sc_qty = self.int_arg(options, "qty", product.it_sc_qty)
        product.save(update_fields=["it_sc_type", "it_sc_method", "it_sc_price", "it_sc_minimum", "it_sc_qty"])
        return previous

    def set_product_qty_limits(self, options):
        product = self.product(options)
        previous = {
            "success": True,
            "product_id": product.it_id,
            "previous_min": product.it_buy_min_qty,
            "previous_max": product.it_buy_max_qty,
            "previous_tel": product.it_tel_inq or "0",
        }
        if self.arg_value(options, "min") is not None:
            product.it_buy_min_qty = max(0, self.int_arg(options, "min", product.it_buy_min_qty))
        if self.arg_value(options, "max") is not None:
            product.it_buy_max_qty = max(0, self.int_arg(options, "max", product.it_buy_max_qty))
        if self.arg_value(options, "tel") is not None:
            product.it_tel_inq = "1" if self.int_arg(options, "tel", 0) else ""
        product.save(update_fields=["it_buy_min_qty", "it_buy_max_qty", "it_tel_inq"])
        return previous

    def set_product_custom_html(self, options):
        product = self.product(options)
        previous = {
            "success": True,
            "product_id": product.it_id,
            "previous_head_html": product.it_head_html,
            "previous_tail_html": product.it_tail_html,
        }
        if self.arg_value(options, "head") is not None:
            product.it_head_html = self.arg_value(options, "head") or ""
        if self.arg_value(options, "tail") is not None:
            product.it_tail_html = self.arg_value(options, "tail") or ""
        product.save(update_fields=["it_head_html", "it_tail_html"])
        return previous

    def set_product_info(self, options):
        product = self.product(options)
        previous = {
            "success": True,
            "product_id": product.it_id,
            "previous_info_gubun": product.it_info_gubun,
            "previous_info_value": json.dumps(product.it_info_value, ensure_ascii=False, separators=(",", ":")),
        }
        raw_gubun = self.arg_value(options, "raw-gubun")
        raw_value = self.arg_value(options, "raw-value")
        if raw_gubun is not None or raw_value is not None:
            # restore: the JSON rows reported above, or a YoungCart PHP-serialized value
            product.it_info_gubun = raw_gubun or ""
            product.it_info_value = parse_item_info_value(raw_value or "", product.it_info_gubun) or []
        else:
            gubun = self.arg_value(options, "gubun") or ""
            key = self.arg_value(options, "key") or ""
            product.it_info_gubun = gubun
            product.it_info_value = [
                {"key": key, "title": article_title(gubun, key), "value": self.arg_value(options, "value") or ""}
            ]
        product.save(update_fields=["it_info_gubun", "it_info_value"])
        return previous

    def set_product_relation(self, options):
        # the product's own related list (ShopProductRelation), reported and restored as a CSV
        product = self.product(options)
        previous_csv = ",".join(related_product_ids(product.it_id))
        restore_csv = self.arg_value(options, "restore-csv")
        related_id = self.arg_value(options, "related-id")
        if restore_csv is not None:
            replace_product_relations(product, restore_csv.split(","))
        elif related_id:
            replace_product_relations(product, [related_id])
        return {"success": True, "product_id": product.it_id, "previous_related_csv": previous_csv}

    def set_review_policy(self, options):
        return {
            "success": True,
            "previous_write": self.arg_value(options, "write") or "0",
            "previous_moderate": self.arg_value(options, "moderate") or "0",
        }

    def set_coupon_zone(self, options):
        subject = "NextJS smoke YoungCart coupon"
        if self.arg_flag(options, "cleanup"):
            zones = ShopCouponZone.objects.filter(cz_subject=subject)
            ShopCoupon.objects.filter(coupon_zone__in=zones).delete()
            deleted, _ = zones.delete()
            return {"success": True, "deleted": deleted}

        product = self.product(options)
        today = timezone.localdate()
        file_name = "nextjs_smoke_coupon.png"
        file_path = self.ensure_data_file("coupon", file_name)
        zone, _ = ShopCouponZone.objects.update_or_create(
            cz_subject=subject,
            defaults={
                "cz_type": 0,
                "cz_point": 0,
                "cz_start": today,
                "cz_end": today + timedelta(days=30),
                "cz_file": file_name,
                "cz_period": 30,
                "cp_method": 0,
                "cp_target": product.it_id,
                "cp_type": 0,
                "cp_price": 1000,
                "cp_minimum": 0,
                "cp_maximum": 0,
                "cp_trunc": 1,
                "image_url": f"/data/coupon/{file_name}",
            },
        )
        ShopCoupon.objects.filter(coupon_zone=zone).delete()
        return {
            "success": True,
            "cz_id": zone.pk,
            "cz_file": file_name,
            "cp_price": zone.cp_price,
            "cp_minimum": zone.cp_minimum,
            "expected_cp_start": today.isoformat(),
            "expected_cp_end": (today + timedelta(days=30)).isoformat(),
            "file_exists": file_path.exists(),
        }

    def set_event(self, options):
        event_id = "nextjs-smoke-event"
        if self.arg_flag(options, "cleanup"):
            self.delete_config("event")
            return {"success": True, "deleted": True}

        product = self.product(options)
        head_file = f"{event_id}_h.png"
        tail_file = f"{event_id}_t.png"
        head_path = self.ensure_data_file("event", head_file)
        tail_path = self.ensure_data_file("event", tail_file)
        self.write_json_config(
            "event",
            {
                "event_id": event_id,
                "product_id": product.it_id,
                "ev_subject": "NextJS smoke YoungCart event",
                "ev_head_html": "NextJS smoke event head html",
                "ev_tail_html": "NextJS smoke event tail html",
                "ev_head_image_url": f"/data/event/{head_file}",
                "ev_tail_image_url": f"/data/event/{tail_file}",
            },
        )
        return {
            "success": True,
            "event_id": event_id,
            "head_image_exists": head_path.exists(),
            "tail_image_exists": tail_path.exists(),
        }

    def smoke_user(self, options, env_name="LOCAL_SMOKE_LOGIN_ID"):
        member_id = self.env_or_arg(options, "id", env_name, "nextjs_smoke")
        User = get_user_model()
        user = User.objects.filter(username=member_id).first()
        if not user:
            raise CommandError(f"smoke member not found: {member_id}")
        return user

    def seed_coupon_zone(self, options):
        subject = os.environ.get("LOCAL_SMOKE_COUPON_SUBJECT") or "nextjs-local-coupon-smoke"
        method = int(os.environ.get("LOCAL_SMOKE_COUPON_METHOD") or "2")
        target = os.environ.get("LOCAL_SMOKE_COUPON_TARGET") or ""
        price_env = os.environ.get("LOCAL_SMOKE_COUPON_PRICE")
        subject_price = re.search(r"(\d+)", subject)
        price = int(price_env or (subject_price.group(1) if subject_price else "1000"))
        minimum = int(os.environ.get("LOCAL_SMOKE_COUPON_MINIMUM") or "0")
        maximum = int(os.environ.get("LOCAL_SMOKE_COUPON_MAXIMUM") or "0")
        product = None
        if not target and method in {0, 1}:
            product = self.product(options)
            target = product.it_id if method == 0 else str(product.category_id or "")
        if method in {0, 1} and not target:
            raise CommandError("coupon target is required for item/category coupons.")

        today = timezone.localdate()
        file_name = "nextjs_smoke_coupon.png"
        file_path = self.ensure_data_file("coupon", file_name)
        zone, _ = ShopCouponZone.objects.update_or_create(
            cz_subject=subject,
            defaults={
                "cz_type": 0,
                "cz_point": 0,
                "cz_start": today,
                "cz_end": today + timedelta(days=30),
                "cz_file": file_name,
                "cz_period": 30,
                "cp_method": method,
                "cp_target": target,
                "cp_type": 0,
                "cp_price": max(0, price),
                "cp_minimum": max(0, minimum),
                "cp_maximum": max(0, maximum),
                "cp_trunc": 1,
                "image_url": f"/data/coupon/{file_name}",
            },
        )
        coupons = ShopCoupon.objects.filter(coupon_zone=zone)
        coupon_ids = list(coupons.values_list("cp_id", flat=True))
        if coupon_ids:
            ShopCouponLog.objects.filter(cp_id__in=coupon_ids).delete()
            coupons.delete()
        return {
            "success": True,
            "cz_id": zone.pk,
            "cz_subject": zone.cz_subject,
            "cp_method": zone.cp_method,
            "cp_target": zone.cp_target,
            "cp_price": zone.cp_price,
            "cp_minimum": zone.cp_minimum,
            "expected_cp_start": today.isoformat(),
            "expected_cp_end": (today + timedelta(days=30)).isoformat(),
            "file_exists": file_path.exists(),
        }

    def cleanup_coupons(self, options):
        subject = os.environ.get("LOCAL_SMOKE_COUPON_SUBJECT") or ""
        login_id = os.environ.get("LOCAL_SMOKE_COUPON_LOGIN_ID") or os.environ.get("LOCAL_SMOKE_LOGIN_ID") or ""
        zones = ShopCouponZone.objects.filter(cz_subject=subject) if subject else ShopCouponZone.objects.none()
        coupons = ShopCoupon.objects.filter(coupon_zone__in=zones)
        if login_id:
            coupons = coupons.filter(Q(user__username=login_id) | Q(user__isnull=True))
        coupon_ids = list(coupons.values_list("cp_id", flat=True))
        if coupon_ids:
            ShopCouponLog.objects.filter(cp_id__in=coupon_ids).delete()
        deleted_coupons, _ = coupons.delete()
        deleted_zones, _ = zones.delete()
        return {
            "success": True,
            "subject": subject,
            "deleted_coupons": deleted_coupons,
            "deleted_zones": deleted_zones,
        }

    def cleanup_orders(self, options):
        order_id = self.arg_value(options, "order-id") or ""
        marker = os.environ.get("LOCAL_SMOKE_ORDER_MARKER") or "nextjs-local-order-smoke"
        queryset = ShopOrder.objects.filter(pk=order_id) if order_id else ShopOrder.objects.filter(od_memo__contains=marker)
        order_ids = list(queryset.values_list("od_id", flat=True))
        restored = 0
        for order in ShopOrder.objects.filter(pk__in=order_ids):
            if order.items.filter(stock_adjusted=True).exists():
                _, restored_count = cancel_order_with_stock_restore(order, "nextjs smoke cleanup")
                restored += restored_count
        ShopOrderData.objects.filter(od_id__in=order_ids).delete()
        deleted_orders, _ = ShopOrder.objects.filter(pk__in=order_ids).delete()
        return {
            "success": True,
            "deleted": deleted_orders,
            "orders": len(order_ids),
            "restored_stock": restored,
            "order_id": order_id,
        }

    def seed_order(self, options):
        order_id = os.environ.get("LOCAL_SMOKE_ORDER_ID") or "9999999999999998"
        marker = os.environ.get("LOCAL_SMOKE_ORDER_MARKER") or "nextjs-local-admin-order-smoke"
        member_id = os.environ.get("LOCAL_SMOKE_LOGIN_ID") or "nextjs_smoke"
        User = get_user_model()
        user = User.objects.filter(username=member_id).first()
        if not user:
            raise CommandError(f"member not found: {member_id}")
        product = self.product(options)
        profile = getattr(user, "profile", None)
        name = (
            getattr(profile, "realname", "")
            or user.get_full_name()
            or getattr(profile, "nickname", "")
            or user.get_username()
        )
        price = int(product.it_price or product.it_basic_price or 12000)
        now_label = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")

        with transaction.atomic():
            stale_ids = list(
                ShopOrder.objects.filter(Q(pk=order_id) | Q(od_memo__contains=marker)).values_list("od_id", flat=True)
            )
            if stale_ids:
                ShopOrderData.objects.filter(od_id__in=stale_ids).delete()
                ShopOrder.objects.filter(pk__in=stale_ids).delete()

            order = ShopOrder.objects.create(
                od_id=order_id,
                user=user,
                od_name=name,
                od_tel="02-1234-5678",
                od_hp="010-1234-5678",
                od_email=user.email or f"{member_id}@example.test",
                od_zip="06000",
                od_addr1="서울특별시 강남구 테스트로 1",
                od_addr2="101호",
                od_b_name=name,
                od_b_tel="02-1234-5678",
                od_b_hp="010-1234-5678",
                od_b_zip="06000",
                od_b_addr1="서울특별시 강남구 테스트로 1",
                od_b_addr2="101호",
                od_memo=f"{marker} order seeded for admin smoke",
                od_cart_price=price,
                od_send_cost=0,
                od_receipt_price=0,
                od_misu=price,
                od_status="주문",
                od_settle_case="무통장",
                od_deposit_name=name,
                od_datetime=timezone.now(),
                od_receipt_time="",
                od_ip="127.0.0.1",
            )
            item = ShopOrderItem.objects.create(
                order=order,
                product=product,
                ct_id=f"{order_id}-1",
                it_id=product.it_id,
                it_name=product.it_name,
                ct_price=price,
                ct_qty=1,
                ct_point=0,
                ct_status="주문",
                stock_adjusted=False,
                image_url=product.image_url or "",
            )
            ShopOrderData.objects.create(
                order=order,
                od_id=order.od_id,
                cart_id=item.ct_id,
                user=user,
                mb_id=user.get_username(),
                dt_pg="nextjs-smoke",
                dt_data=json.dumps({"marker": marker, "seeded_at": now_label}, ensure_ascii=False),
            )

        return {
            "success": True,
            "id": order.od_id,
            "order_id": order.od_id,
            "member_id": member_id,
            "product_id": product.it_id,
            "price": price,
            "marker": marker,
        }

    def paid_amount_for_order(self, order):
        subtotal = (
            int(order.od_cart_price or 0)
            + int(order.od_send_cost or 0)
            + int(order.od_send_cost2 or 0)
            - int(getattr(order, "od_cart_coupon", 0) or 0)
            - int(order.od_coupon or 0)
            - int(order.od_send_coupon or 0)
            - int(order.od_receipt_point or 0)
            - int(order.od_cancel_price or 0)
        )
        if int(order.od_misu or 0) > 0:
            return int(order.od_misu or 0)
        if int(order.od_receipt_price or 0) > 0:
            return int(order.od_receipt_price or 0)
        return max(0, subtotal)

    def mark_order_paid(self, options):
        order_id = self.arg_value(options, "order-id") or ""
        if not order_id:
            raise CommandError("--order-id is required.")
        status_arg = (self.arg_value(options, "status") or "paid").lower()
        status_value = "배송" if status_arg in {"shipping", "delivery", "배송"} else "입금"
        order = ShopOrder.objects.filter(pk=order_id).first()
        if not order:
            raise CommandError(f"order not found: {order_id}")

        paid_amount = self.paid_amount_for_order(order)
        now_label = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
        update_fields = ["od_status", "od_receipt_price", "od_misu", "od_receipt_time"]
        order.od_status = status_value
        order.od_receipt_price = paid_amount
        order.od_misu = 0
        order.od_receipt_time = now_label

        tno = ""
        app_no = ""
        if self.arg_flag(options, "with-toss-receipt"):
            tno = f"SMOKETOSS{order_id[-8:]}"
            app_no = f"APP{order_id[-8:]}"
            order.od_pg = "toss"
            order.od_tno = tno
            order.od_app_no = app_no
            update_fields.extend(["od_pg", "od_tno", "od_app_no"])

        delivery_company = ""
        invoice = ""
        if self.arg_flag(options, "with-delivery"):
            delivery_company = "CJ대한통운"
            invoice = f"SMOKE{order_id[-10:]}"
            order.od_delivery_company = delivery_company
            order.od_invoice = invoice
            order.od_invoice_time = now_label
            update_fields.extend(["od_delivery_company", "od_invoice", "od_invoice_time"])

        cash_no = ""
        cash_receipt_url = ""
        if self.arg_flag(options, "with-toss-cash-receipt"):
            cash_no = f"CASH{order_id[-10:]}"
            cash_receipt_url = f"https://dashboard.tosspayments.com/receipt/cash-receipt/{cash_no}"
            order.od_pg = "toss"
            order.od_cash_no = cash_no
            order.od_cash_res = cash_receipt_url
            update_fields.extend(["od_pg", "od_cash_no", "od_cash_res"])

        order.save(update_fields=sorted(set(update_fields)))
        order.items.exclude(ct_status__in=["취소", "cancel", "cancelled"]).update(**item_status_update(status_value))
        take_back_order_points(order)
        return {
            "success": True,
            "order_id": order.od_id,
            "status": status_value,
            "paid_amount": paid_amount,
            "tno": order.od_tno or tno,
            "app_no": order.od_app_no or app_no,
            "delivery_company": delivery_company or order.od_delivery_company,
            "invoice": invoice or order.od_invoice,
            "cash_no": cash_no or order.od_cash_no,
            "cash_receipt_url": cash_receipt_url or order.od_cash_res,
        }

    def point_config_suffix(self, member_id, marker):
        digest = hashlib.sha1(f"{member_id}:{marker}".encode("utf-8")).hexdigest()[:12]
        return f"points_{digest}"

    def seed_points(self, options):
        member_id = os.environ.get("LOCAL_SMOKE_POINT_LOGIN_ID") or os.environ.get("LOCAL_SMOKE_LOGIN_ID") or "nextjs_smoke"
        marker = os.environ.get("LOCAL_SMOKE_POINT_MARKER") or "nextjs-local-order-point"
        earn = int(os.environ.get("LOCAL_SMOKE_POINT_EARN") or "1500")
        use = int(os.environ.get("LOCAL_SMOKE_POINT_USE") or "300")
        User = get_user_model()
        user = User.objects.filter(username=member_id).first()
        if not user:
            raise CommandError(f"smoke member not found: {member_id}")
        profile, _ = Profile.objects.get_or_create(user=user)
        suffix = self.point_config_suffix(member_id, marker)
        if not self.read_json_config(suffix, None):
            self.write_json_config(suffix, {"member_id": member_id, "previous_point": profile.user_point, "marker": marker})
        User_Point.objects.filter(user=user, po_rel_table="smoke", po_rel_action=marker[:255]).delete()
        balance = max(0, earn - use)
        profile.user_point = balance
        profile.save(update_fields=["user_point"])
        earn_row = User_Point.objects.create(
            user=user,
            po_datetime=timezone.now(),
            po_content=f"{marker} earn",
            po_point=earn,
            po_use_point=0,
            po_mb_point=earn,
            po_rel_table="smoke",
            po_rel_action=marker[:255],
        )
        use_row = User_Point.objects.create(
            user=user,
            po_datetime=timezone.now(),
            po_content=f"{marker} use",
            po_point=-use,
            po_use_point=use,
            po_mb_point=balance,
            po_rel_table="smoke",
            po_rel_action=marker[:255],
        )
        return {
            "success": True,
            "member_id": member_id,
            "earn_point": earn,
            "use_point": use,
            "balance": balance,
            "earn_po_id": earn_row.pk,
            "use_po_id": use_row.pk,
        }

    def cleanup_points(self, options):
        member_id = os.environ.get("LOCAL_SMOKE_POINT_LOGIN_ID") or os.environ.get("LOCAL_SMOKE_LOGIN_ID") or "nextjs_smoke"
        marker = os.environ.get("LOCAL_SMOKE_POINT_MARKER") or "nextjs-local-order-point"
        User = get_user_model()
        user = User.objects.filter(username=member_id).first()
        previous = self.read_json_config(self.point_config_suffix(member_id, marker), {})
        restored = None
        if user:
            profile, _ = Profile.objects.get_or_create(user=user)
            if "previous_point" in previous:
                profile.user_point = int(previous.get("previous_point") or 0)
                profile.save(update_fields=["user_point"])
                restored = profile.user_point
            User_Point.objects.filter(user=user, po_rel_table="smoke", po_rel_action=marker[:255]).delete()
        self.delete_config(self.point_config_suffix(member_id, marker))
        return {"success": True, "member_id": member_id, "restored_point": restored}

    def cleanup_shop_content(self, options):
        marker = os.environ.get("LOCAL_SMOKE_SHOP_CONTENT_MARKER") or "nextjs-local-shop-content-smoke"
        member_id = os.environ.get("LOCAL_SMOKE_LOGIN_ID") or "nextjs_shop_smoke"
        review_filter = (
            Q(is_subject__contains=marker)
            | Q(is_content__contains=marker)
            | (Q(mb_id=member_id) & Q(is_subject__contains="Next.js"))
        )
        qa_filter = (
            Q(iq_subject__contains=marker)
            | Q(iq_question__contains=marker)
            | (Q(mb_id=member_id) & Q(iq_subject__contains="Next.js"))
        )
        deleted_reviews, _ = ShopReview.objects.filter(review_filter).delete()
        deleted_qas, _ = ShopQA.objects.filter(qa_filter).delete()
        return {
            "success": True,
            "marker": marker,
            "deleted_reviews": deleted_reviews,
            "deleted_qas": deleted_qas,
        }

    def cleanup_memos(self, options):
        marker = os.environ.get("LOCAL_SMOKE_MEMO_MARKER") or "nextjs-local-memo-smoke"
        sender_id = os.environ.get("LOCAL_SMOKE_MEMO_SENDER_ID") or ""
        receiver_id = os.environ.get("LOCAL_SMOKE_MEMO_RECEIVER_ID") or ""
        users = get_user_model().objects.filter(username__in=[sender_id, receiver_id])
        user_ids = list(users.values_list("pk", flat=True))
        memo_filter = Q(me_memo__contains=marker)
        if user_ids:
            memo_filter &= Q(user_id__in=user_ids) | Q(me_recv_user_id__in=user_ids) | Q(me_send_id__in=user_ids)
        deleted_memos, _ = User_Memo.objects.filter(memo_filter).delete()
        return {
            "success": True,
            "marker": marker,
            "deleted_memos": deleted_memos,
        }

    def seed_personalpay(self, options):
        pp_id = os.environ.get("LOCAL_SMOKE_PERSONALPAY_ID") or "9999999999999999"
        marker = os.environ.get("LOCAL_SMOKE_PERSONALPAY_MARKER") or "nextjs-local-personalpay-smoke"
        name = f"{marker} payer"
        price = 45670
        settle_case = "무통장"
        bank_account = "국민은행 000000-00-000000 지누장고"
        deposit_name = "Nextjs Personalpay"
        item, _ = ShopPersonalPay.objects.update_or_create(
            pp_id=pp_id,
            defaults={
                "pp_name": name,
                "pp_email": "personalpay@example.test",
                "pp_hp": "010-5555-6666",
                "pp_content": f"{marker} content",
                "pp_price": price,
                "pp_settle_case": settle_case,
                "pp_bank_account": bank_account,
                "pp_deposit_name": deposit_name,
                "pp_receipt_price": 0,
                "pp_pg": "",
                "pp_tno": "",
                "pp_app_no": "",
                "pp_cash": 0,
                "pp_cash_no": "",
                "pp_receipt_time": "",
                "pp_time": timezone.now(),
                "active": True,
            },
        )
        return {
            "success": True,
            "pp_id": item.pp_id,
            "name": name,
            "price": price,
            "settle_case": settle_case,
            "bank_account": bank_account,
            "deposit_name": deposit_name,
        }

    def mark_personalpay_paid(self, options):
        pp_id = os.environ.get("LOCAL_SMOKE_PERSONALPAY_ID") or "9999999999999999"
        item = ShopPersonalPay.objects.filter(pk=pp_id).first()
        if not item:
            raise CommandError(f"personal pay not found: {pp_id}")
        tno = f"SMOKEPP{pp_id[-8:]}"
        update_fields = ["pp_pg", "pp_tno", "pp_receipt_price", "pp_receipt_time", "pp_cash", "pp_cash_no"]
        item.pp_pg = "toss"
        item.pp_tno = tno
        cash_no = ""
        cash_receipt_url = ""
        if self.arg_flag(options, "processing"):
            item.pp_receipt_price = 0
            item.pp_receipt_time = ""
            item.pp_cash = 0
            item.pp_cash_no = ""
        else:
            item.pp_receipt_price = item.pp_price
            item.pp_receipt_time = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
            if self.arg_flag(options, "with-toss-cash-receipt"):
                cash_no = f"CASHPP{pp_id[-8:]}"
                cash_receipt_url = f"https://dashboard.tosspayments.com/receipt/cash-receipt/{cash_no}"
                item.pp_cash = 1
                item.pp_cash_no = cash_no
            else:
                item.pp_cash = 0
                item.pp_cash_no = ""
        item.save(update_fields=update_fields)
        return {
            "success": True,
            "pp_id": item.pp_id,
            "price": item.pp_price,
            "settle_case": item.pp_settle_case,
            "tno": item.pp_tno,
            "cash_no": cash_no or item.pp_cash_no,
            "cash_receipt_url": cash_receipt_url,
        }

    def cleanup_personalpay(self, options):
        pp_id = os.environ.get("LOCAL_SMOKE_PERSONALPAY_ID") or "9999999999999999"
        marker = os.environ.get("LOCAL_SMOKE_PERSONALPAY_MARKER") or "nextjs-local-personalpay-smoke"
        deleted, _ = ShopPersonalPay.objects.filter(Q(pk=pp_id) | Q(pp_content__contains=marker) | Q(pp_name__contains=marker)).delete()
        return {"success": True, "pp_id": pp_id, "deleted_personalpay": deleted}

    def seed_poll(self, options):
        marker = os.environ.get("LOCAL_SMOKE_POLL_MARKER") or "nextjs-local-poll-smoke"
        subject = os.environ.get("LOCAL_SMOKE_POLL_SUBJECT") or f"{marker} question"
        option_one = f"{marker} option one"
        option_two = f"{marker} option two"
        poll = Poll.objects.create(
            po_subject=subject,
            po_etc=marker,
            po_level=1,
            po_point=0,
            po_date=timezone.localdate(),
            po_use=1,
            po_begin_date=timezone.localdate() - timedelta(days=1),
            po_end_date=timezone.localdate() + timedelta(days=30),
        )
        PollChoice.objects.create(poll=poll, num=1, content=option_one, count=0)
        PollChoice.objects.create(poll=poll, num=2, content=option_two, count=0)
        return {
            "success": True,
            "po_id": poll.po_id,
            "po_subject": poll.po_subject,
            "option_one": option_one,
            "option_two": option_two,
        }

    def cleanup_polls(self, options):
        marker = os.environ.get("LOCAL_SMOKE_POLL_MARKER") or "nextjs-local-poll-smoke"
        subject = os.environ.get("LOCAL_SMOKE_POLL_SUBJECT") or ""
        polls = Poll.objects.filter(Q(po_etc__contains=marker) | Q(po_subject__contains=marker))
        if subject:
            polls = polls | Poll.objects.filter(po_subject=subject)
        poll_ids = list(polls.values_list("po_id", flat=True))
        PollVote.objects.filter(poll_id__in=poll_ids).delete()
        PollComment.objects.filter(poll_id__in=poll_ids).delete()
        deleted_polls, _ = Poll.objects.filter(pk__in=poll_ids).delete()
        return {"success": True, "marker": marker, "deleted_polls": deleted_polls}

    def cleanup_qas(self, options):
        marker = os.environ.get("LOCAL_SMOKE_QA_MARKER") or "nextjs-local-qa-smoke"
        member_id = os.environ.get("LOCAL_SMOKE_QA_LOGIN_ID") or ""
        qa_filter = Q(iq_subject__contains=marker) | Q(iq_question__contains=marker)
        if member_id:
            qa_filter |= Q(mb_id=member_id)
        deleted_qas, _ = ShopQA.objects.filter(qa_filter).delete()
        return {"success": True, "marker": marker, "deleted_qas": deleted_qas}

    def seed_qa(self, options):
        marker = os.environ.get("LOCAL_SMOKE_QA_MARKER") or "nextjs-local-admin-qa-smoke"
        member_id = os.environ.get("LOCAL_SMOKE_QA_LOGIN_ID") or os.environ.get("LOCAL_SMOKE_LOGIN_ID") or "nextjs_smoke"
        User = get_user_model()
        user = User.objects.filter(username=member_id).first()
        if not user:
            raise CommandError(f"member not found: {member_id}")
        product, _ = ShopProduct.objects.update_or_create(
            it_id="__general_qa__",
            defaults={
                "it_name": "General Q&A",
                "it_seo_title": "general-qa",
                "it_price": 0,
                "it_use": "",
                "it_stock_qty": 0,
            },
        )
        profile = getattr(user, "profile", None)
        nick = getattr(profile, "nickname", "") or user.get_username()
        name = getattr(profile, "realname", "") or user.get_full_name() or nick
        subject = f"{marker} question"

        with transaction.atomic():
            ShopQA.objects.filter(
                Q(iq_subject__contains=marker) | Q(iq_question__contains=marker),
                mb_id=member_id,
            ).delete()
            item = ShopQA.objects.create(
                product=product,
                user=user,
                mb_id=user.get_username(),
                mb_nick=nick,
                iq_name=name,
                iq_subject=subject,
                iq_question=f"{marker} question body for admin answer smoke.",
                iq_answer="",
                iq_email=user.email or "",
            )

        return {
            "success": True,
            "id": item.pk,
            "qa_id": item.pk,
            "member_id": member_id,
            "subject": subject,
            "marker": marker,
        }

    def cleanup_scraps(self, options):
        member_id = os.environ.get("LOCAL_SMOKE_SCRAP_LOGIN_ID") or ""
        if not member_id:
            return {"success": True, "deleted_scraps": 0}
        user = get_user_model().objects.filter(username=member_id).first()
        if not user:
            return {"success": True, "deleted_scraps": 0}
        deleted_scraps, _ = Post_scrap.objects.filter(user=user).delete()
        return {"success": True, "member_id": member_id, "deleted_scraps": deleted_scraps}

    def seed_user(self, options):
        admin_mode = bool(options.get("admin"))
        member_id = (
            self.env_or_arg(options, "id", "LOCAL_SMOKE_ADMIN_LOGIN_ID", "nextjs_admin_smoke")
            if admin_mode
            else self.env_or_arg(options, "id", "LOCAL_SMOKE_LOGIN_ID", "nextjs_smoke")
        )
        password = (
            self.env_or_arg(options, "password", "LOCAL_SMOKE_ADMIN_LOGIN_PASSWORD", "NextjsAdminSmoke123!")
            if admin_mode
            else self.env_or_arg(options, "password", "LOCAL_SMOKE_LOGIN_PASSWORD", "NextjsSmoke123!")
        )
        email = self.env_or_arg(
            options,
            "email",
            "LOCAL_SMOKE_ADMIN_LOGIN_EMAIL" if admin_mode else "LOCAL_SMOKE_LOGIN_EMAIL",
            f"{member_id}@example.test",
        )
        name = self.env_or_arg(
            options,
            "name",
            "LOCAL_SMOKE_ADMIN_LOGIN_NAME" if admin_mode else "LOCAL_SMOKE_LOGIN_NAME",
            "Nextjs Admin Smoke" if admin_mode else "Nextjs Smoke",
        )
        nick = self.env_or_arg(
            options,
            "nick",
            "LOCAL_SMOKE_ADMIN_LOGIN_NICK" if admin_mode else "LOCAL_SMOKE_LOGIN_NICK",
            "NextjsAdminSmoke" if admin_mode else "NextjsSmoke",
        )
        point = int(
            self.env_or_arg(
                options,
                "point",
                "LOCAL_SMOKE_ADMIN_LOGIN_POINT" if admin_mode else "LOCAL_SMOKE_LOGIN_POINT",
                "0",
            )
        )

        if not MEMBER_ID_RE.match(member_id):
            raise CommandError("member id must be 3-20 characters of letters, numbers, or underscores.")
        if len(password) < 8 or len(password) > 64:
            raise CommandError("password must be 8-64 characters.")
        if "@" not in email:
            raise CommandError("email must be valid.")
        if point < 0 or point > 10000000:
            raise CommandError("point must be between 0 and 10000000.")

        User = get_user_model()
        marker = "nextjs-local-admin-smoke" if admin_mode else "nextjs-local-smoke"
        with transaction.atomic():
            email_owner = User.objects.filter(email__iexact=email).exclude(username=member_id).first()
            if email_owner:
                email_field = "LOCAL_SMOKE_ADMIN_LOGIN_EMAIL" if admin_mode else "LOCAL_SMOKE_LOGIN_EMAIL"
                raise CommandError(f"email is already used by {email_owner.username}; set {email_field}.")

            user = User.objects.filter(username=member_id).first()
            action = "updated" if user else "created"
            if not user:
                user = User(username=member_id, date_joined=timezone.now())

            user.email = email
            user.first_name = name
            user.last_name = ""
            user.is_active = True
            user.is_staff = admin_mode
            user.is_superuser = admin_mode
            user.set_password(password)
            user.save()

            profile, _ = Profile.objects.get_or_create(user=user)
            profile.nickname = nick
            profile.realname = name
            profile.user_level = 10 if admin_mode else 2
            profile.user_point = point
            profile.save()

        return {
            "success": True,
            "action": action,
            "id": member_id,
            "member_id": member_id,
            "mb_id": member_id,
            "email": email,
            "password": password,
            "name": name,
            "nick": nick,
            "point": point,
            "level": 10 if admin_mode else 2,
            "marker": marker,
            "message": f"{action} smoke member {member_id}.",
        }
