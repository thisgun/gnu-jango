"""고객 세그먼트 (RFM): which members are the shop's best, new, slipping and lost customers.

An order counts when it is paid (api.shop_common.PAID_STATUSES: 입금 through 완료, English
spellings included), so an unpaid 주문 and a cancelled or returned order do not. The order belongs to
the local day of od_datetime and its amount is od_receipt_price - od_refund_price, as in the
매출현황 report. Only members count; a guest order has no customer to follow. Nothing here calls a
model.

R is the days since the last counted order and F the counted orders in the window. Both are scored
1-5 by fixed bands (R_BANDS, F_BANDS), so a customer's segment never depends on who else bought: a
customer who ordered today is never lapsed. M, the net paid amount, is a relative 1-5 score for
display only; ties share the higher band. The segment comes from R and F alone.
"""

from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import date, timedelta
from statistics import median

from django.contrib.auth import get_user_model
from django.db.models import Count, F, IntegerField, Max, Sum
from django.utils import timezone

from gnu_jango.api.shop_common import PAID_STATUSES
from gnu_jango.shop.cart_reminders import mailable_users
from gnu_jango.utils.date_ranges import local_days

from .models import ShopOrder

WINDOW_CHOICES = (180, 365, 730)
DEFAULT_WINDOW = 365
LAPSED_DAYS = 90
SCORE_LEVELS = 5
# (largest value of the band, score); a value past the last band gets the default score.
R_BANDS = ((30, 5), (60, 4), (90, 3), (180, 2))
R_DEFAULT = 1
F_BANDS = ((1, 1), (2, 2), (3, 3), (5, 4))
F_DEFAULT = 5


@dataclass(frozen=True)
class Segment:
    key: str
    label: str
    hint: str


SEGMENTS = (
    Segment("champions", "챔피언", "최근에 자주 산 고객"),
    Segment("loyal", "충성 고객", "꾸준히 사는 고객"),
    Segment("potential", "잠재 충성", "최근에 샀고 더 살 여지가 있는 고객"),
    Segment("new", "신규 고객", "최근 한 번 산 고객"),
    Segment("attention", "관심 필요", "구매 간격이 벌어지기 시작한 고객"),
    Segment("at_risk", "이탈 위험", "자주 샀지만 한동안 사지 않은 고객"),
    Segment("cant_lose", "놓치면 안 될 고객", "자주 샀지만 오래 사지 않은 고객"),
    Segment("hibernating", "휴면", "구매가 적고 오래된 고객"),
    Segment("lost", "이탈", "오래전에 한 번 산 고객"),
)
SEGMENT_BY_KEY = {segment.key: segment for segment in SEGMENTS}

# Rows are R = 5 (bought most recently) down to 1; columns are F = 1 up to 5.
_GRID_ROWS = (
    ("new", "potential", "loyal", "champions", "champions"),
    ("new", "potential", "loyal", "champions", "champions"),
    ("attention", "attention", "attention", "loyal", "loyal"),
    ("hibernating", "hibernating", "at_risk", "at_risk", "cant_lose"),
    ("lost", "hibernating", "at_risk", "cant_lose", "cant_lose"),
)
SEGMENT_GRID = {
    (SCORE_LEVELS - row_index, column + 1): key
    for row_index, row in enumerate(_GRID_ROWS)
    for column, key in enumerate(row)
}


@dataclass(frozen=True)
class Customer:
    user_id: int
    username: str
    nickname: str
    email: str
    accepts_mail: bool
    last_order: date
    recency_days: int
    orders: int
    amount: int
    r_score: int = 0
    f_score: int = 0
    m_score: int = 0
    segment: str = ""

    @property
    def segment_label(self):
        return SEGMENT_BY_KEY[self.segment].label if self.segment else ""


@dataclass(frozen=True)
class SegmentRow:
    segment: Segment
    count: int
    share: float
    avg_orders: float
    avg_amount: int
    median_recency: int


@dataclass(frozen=True)
class SegmentReport:
    window_days: int
    start: date
    end: date
    customers: tuple
    rows: tuple
    median_amount: int
    lapsed_count: int
    at_risk_count: int


def band_score(value, bands, default):
    return next((score for limit, score in bands if value <= limit), default)


def m_scores(values):
    """Each value's 1-5 score by rank among ``values``; equal values share the higher band."""
    ordered = sorted(values)
    total = len(values)
    return [-(-SCORE_LEVELS * bisect_right(ordered, value) // total) for value in values]


def segment_for(r_score, f_score):
    return SEGMENT_GRID[(r_score, f_score)]


def score_customers(customers):
    """``customers`` with their R/F/M scores and segment filled in, in the same order."""
    amounts = m_scores([customer.amount for customer in customers])
    scored = []
    for customer, m in zip(customers, amounts):
        r = band_score(customer.recency_days, R_BANDS, R_DEFAULT)
        f = band_score(customer.orders, F_BANDS, F_DEFAULT)
        scored.append(replace(customer, r_score=r, f_score=f, m_score=m, segment=segment_for(r, f)))
    return scored


def segment_rows(customers):
    """One row per segment, in the registry order, empty segments included."""
    grouped = {segment.key: [] for segment in SEGMENTS}
    for customer in customers:
        grouped[customer.segment].append(customer)
    rows = []
    for segment in SEGMENTS:
        members = grouped[segment.key]
        count = len(members)
        rows.append(
            SegmentRow(
                segment=segment,
                count=count,
                share=count / len(customers) if customers else 0.0,
                avg_orders=sum(c.orders for c in members) / count if count else 0.0,
                avg_amount=round(sum(c.amount for c in members) / count) if count else 0,
                median_recency=round(median(c.recency_days for c in members)) if count else 0,
            )
        )
    return tuple(rows)


def summarize(customers, window_days, start, end):
    scored = tuple(score_customers(list(customers)))
    return SegmentReport(
        window_days=window_days,
        start=start,
        end=end,
        customers=scored,
        rows=segment_rows(scored),
        median_amount=round(median(c.amount for c in scored)) if scored else 0,
        lapsed_count=sum(1 for c in scored if c.recency_days > LAPSED_DAYS),
        at_risk_count=sum(1 for c in scored if c.segment == "at_risk"),
    )


def window_customers(start, end, today):
    """Members with a counted order on the local days ``start``..``end``, unscored."""
    totals = (
        ShopOrder.objects.filter(local_days("od_datetime", start, end), user__isnull=False, od_status__in=PAID_STATUSES)
        .values("user_id")
        .annotate(
            orders=Count("pk"),
            amount=Sum(F("od_receipt_price") - F("od_refund_price"), output_field=IntegerField()),
            last=Max("od_datetime"),
        )
    )
    totals = list(totals)
    users = (
        get_user_model()
        .objects.filter(pk__in=[row["user_id"] for row in totals])
        .select_related("profile")
        .in_bulk()
    )
    mailable = set(mailable_users().filter(pk__in=users).values_list("pk", flat=True))
    customers = []
    for row in sorted(totals, key=lambda item: item["user_id"]):
        user = users.get(row["user_id"])
        if user is None:
            continue
        profile = getattr(user, "profile", None)
        last = timezone.localtime(row["last"]).date()
        customers.append(
            Customer(
                user_id=user.pk,
                username=user.get_username(),
                nickname=profile.nickname if profile else "",
                email=user.email or "",
                accepts_mail=user.pk in mailable,
                last_order=last,
                recency_days=max((today - last).days, 0),
                orders=row["orders"],
                amount=row["amount"] or 0,
            )
        )
    return customers


def segment_report(window_days=DEFAULT_WINDOW, today=None):
    today = today or timezone.localdate()
    start = today - timedelta(days=window_days - 1)
    return summarize(window_customers(start, today, today), window_days, start, today)
