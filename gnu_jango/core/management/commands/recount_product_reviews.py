"""Recount it_use_cnt / it_use_avg of products from their published reviews (backfill)."""

from django.core.management.base import BaseCommand

from gnu_jango.shop.product_counters import recount_product_reviews


class Command(BaseCommand):
    help = (
        "Recount each product's review count (it_use_cnt) and average score (it_use_avg) from its "
        "published reviews, as youngcart update_use_cnt / update_use_avg do. Safe to run again."
    )

    def add_arguments(self, parser):
        parser.add_argument("it_ids", nargs="*", help="Product ids to recount (default: every product).")

    def handle(self, *args, **options):
        updated = recount_product_reviews(options["it_ids"] or None)
        self.stdout.write(f"products={updated}")
