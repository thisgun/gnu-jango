import json

from django.core.management.base import BaseCommand, CommandError

from gnu_jango.api import v1_shop
from gnu_jango.shop.models import ShopOrder


SUPPORTED_OPERATIONS = ("reconcile", "cash_receipt")


class Command(BaseCommand):
    help = "Send paid orders to the configured PG verification adapter for reconciliation or receipt checks."

    def add_arguments(self, parser):
        parser.add_argument(
            "--operation",
            action="append",
            choices=SUPPORTED_OPERATIONS,
            help="Operation to run. Can be supplied multiple times. Defaults to reconcile.",
        )
        parser.add_argument(
            "--provider",
            action="append",
            help="Limit to one or more PG providers such as kcp, inicis, nicepay, naverpay, kakaopay.",
        )
        parser.add_argument("--order-id", action="append", default=[], help="Limit to one or more order ids.")
        parser.add_argument("--limit", type=int, default=100, help="Maximum number of orders to inspect.")
        parser.add_argument("--apply", action="store_true", help="Call the adapter. Without this, dry-run only.")
        parser.add_argument("--json", action="store_true", help="Print a machine-readable JSON summary.")

    def handle(self, *args, **options):
        operations = tuple(options["operation"] or ("reconcile",))
        providers = self.provider_filter(options)
        apply = bool(options["apply"])
        adapter_config = v1_shop.payment_adapter_config()
        if apply and not adapter_config["enabled"]:
            raise CommandError("SHOP_PAYMENT_ADAPTER_BASE_URL and SHOP_PAYMENT_ADAPTER_SECRET are required with --apply.")

        orders = self.orders(providers, options["order_id"], options["limit"])
        summary = {
            "applied": apply,
            "operations": list(operations),
            "providers": sorted(providers),
            "orders_inspected": orders.count(),
            "requests_planned": 0,
            "requests_sent": 0,
            "verified": 0,
            "failed": 0,
            "skipped": 0,
            "samples": [],
        }

        for order in orders:
            provider = str(order.od_pg or "").strip().lower()
            if provider not in providers:
                summary["skipped"] += 1
                continue
            for operation in operations:
                if operation == "cash_receipt" and not self.cash_receipt_candidate(order):
                    summary["skipped"] += 1
                    continue
                summary["requests_planned"] += 1
                if not apply:
                    self.append_sample(summary, order, operation, "planned")
                    continue
                self.send_adapter_request(order, provider, operation, summary)

        if options["json"]:
            self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        else:
            self.print_summary(summary)

    def provider_filter(self, options):
        configured = set(v1_shop.payment_adapter_config()["providers"]) or set(v1_shop.PAYMENT_ADAPTER_PROVIDERS)
        requested = {
            str(provider or "").strip().lower()
            for provider in (options.get("provider") or [])
            if str(provider or "").strip()
        }
        providers = requested or configured
        return providers & set(v1_shop.PAYMENT_ADAPTER_PROVIDERS)

    def orders(self, providers, order_ids, limit):
        queryset = (
            ShopOrder.objects.filter(od_receipt_price__gt=0)
            .exclude(od_pg="")
            .exclude(od_pg__iexact="bank")
            .order_by("-od_datetime", "-od_id")
        )
        if providers:
            queryset = queryset.filter(od_pg__in=providers)
        if order_ids:
            queryset = queryset.filter(od_id__in=[str(item).strip() for item in order_ids if str(item).strip()])
        return queryset[: max(1, int(limit or 100))]

    def cash_receipt_candidate(self, order):
        settle_case = str(order.od_settle_case or "").lower()
        return bool(order.od_cash_no or order.od_cash_res or "cash" in settle_case or "bank" in settle_case)

    def adapter_payload(self, order, operation):
        return {
            "operation": operation,
            "order_id": order.od_id,
            "uid": order.uid,
            "provider": order.od_pg,
            "transaction_id": order.od_tno,
            "amount": order.od_receipt_price,
            "receipt_point": order.od_receipt_point,
            "settle_case": order.od_settle_case,
            "status": order.od_status,
            "receipt_time": order.od_receipt_time,
            "cash_receipt_no": order.od_cash_no,
            "cash_receipt_response": order.od_cash_res,
        }

    def send_adapter_request(self, order, provider, operation, summary):
        payload = self.adapter_payload(order, operation)
        result, error = v1_shop.payment_adapter_request(operation, provider, payload)
        raw = {**payload, "payment_adapter": result if result is not None else getattr(error, "data", {})}
        v1_shop.record_payment_raw_log(
            order,
            order.od_id,
            f"adapter:{operation}:{provider}",
            order.od_tno,
            raw,
            prefix=f"adapter-{operation}",
        )
        summary["requests_sent"] += 1
        if error or not v1_shop.payment_adapter_success(result or {}):
            summary["failed"] += 1
            self.append_sample(summary, order, operation, "failed")
            return
        summary["verified"] += 1
        self.append_sample(summary, order, operation, "verified")

    def append_sample(self, summary, order, operation, status):
        if len(summary["samples"]) >= 20:
            return
        summary["samples"].append(
            {
                "order_id": order.od_id,
                "provider": order.od_pg,
                "operation": operation,
                "status": status,
            }
        )

    def print_summary(self, summary):
        self.stdout.write("Payment adapter reconciliation")
        self.stdout.write(f"  applied: {'yes' if summary['applied'] else 'no'}")
        self.stdout.write(f"  operations: {', '.join(summary['operations'])}")
        self.stdout.write(f"  providers: {', '.join(summary['providers']) or '(none)'}")
        self.stdout.write(f"  orders inspected: {summary['orders_inspected']}")
        self.stdout.write(f"  requests planned: {summary['requests_planned']}")
        self.stdout.write(f"  requests sent: {summary['requests_sent']}")
        self.stdout.write(f"  verified: {summary['verified']}")
        self.stdout.write(f"  failed: {summary['failed']}")
        self.stdout.write(f"  skipped: {summary['skipped']}")
