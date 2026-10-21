"""Recount it_sum_qty of products from their completed order lines (backfill)."""

from django.core.management.base import BaseCommand

from gnu_jango.shop.product_counters import recount_product_sales


class Command(BaseCommand):
    help = (
        "Recount each product's sold quantity (it_sum_qty) from its 완료 order lines, as youngcart "
        "orderlistupdate.php does. Cancelled and returned lines are not counted. Safe to run again."
    )

    def add_arguments(self, parser):
        parser.add_argument("it_ids", nargs="*", help="Product ids to recount (default: every product).")

    def handle(self, *args, **options):
        updated = recount_product_sales(options["it_ids"] or None)
        self.stdout.write(f"products={updated}")
