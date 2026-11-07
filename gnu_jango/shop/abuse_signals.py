"""이상 활동 점검: review manipulation and coupon abuse, by fixed rules an operator can check.

Nothing here changes data or acts on a member. Each rule is a ``Rule`` in ``RULES``; it returns
``Finding`` rows that carry their own evidence and links to the admin rows to look at. The shop
stores no abuse labels, so there is no score: every finding says which numbers crossed which
threshold.

Dropped on purpose: "many accounts registered from one IP in a day". The member model stores no
signup IP (only ``me_send_ip``, the IP a memo was sent from), so the rule has no data.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from .models import ShopCouponLog, ShopOrder, ShopOrderItem, ShopReview
from .order_statuses import INACTIVE_LINE_STATUSES
from .shipping import current_shipping_policy
from .signup_coupon import SIGNUP_COUPON_SUBJECT
from .text_similarity import clusters, similar_pairs

WINDOW_CHOICES = (7, 30, 90)
DEFAULT_WINDOW_DAYS = 30

SEVERITY_ORDER = {"high": 0, "medium": 1, "info": 2}
SEVERITY_LABELS = {"high": "주의", "medium": "확인", "info": "참고"}

# 후기 몰림. Five 5-star reviews from three people inside 24 hours is rare for a small shop, and
# the burst must beat the product's own earlier pace by 10x: a product that already gets a review
# every other day is not "bursting" at five a day.
BURST_MIN_REVIEWS = 5
BURST_MIN_AUTHORS = 3
BURST_SPAN = timedelta(hours=24)
BURST_BASELINE_DAYS = 90
BURST_RATE_FACTOR = 10
BURST_ROW_CAP = 20_000

# 유사 후기. Only the newest SIMILARITY_REVIEW_CAP reviews of the window are compared.
SIMILARITY_THRESHOLD = 0.8
SIMILARITY_MIN_LENGTH = 20
SIMILARITY_REVIEW_CAP = 2_000

NO_PURCHASE_REVIEW_CAP = 2_000
IN_CHUNK = 500

SHARED_IP_MIN_MEMBERS = 3
SHARED_IP_CAP = 30
SHARED_IP_ORDER_CAP = 2_000

LINK_ID_CAP = 100
SAMPLE_CAP = 5


@dataclass(frozen=True)
class Window:
    days: int
    now: object

    @property
    def since(self):
        return self.now - timedelta(days=self.days)


@dataclass(frozen=True)
class Link:
    label: str
    url: str


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    title: str
    evidence: tuple
    links: tuple = ()

    @property
    def severity_label(self):
        return SEVERITY_LABELS[self.severity]


@dataclass(frozen=True)
class Rule:
    code: str
    title: str
    summary: str
    check: object


@dataclass(frozen=True)
class RuleResult:
    rule: Rule
    findings: tuple


def window_days(value):
    try:
        days = int(value)
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_DAYS
    return days if days in WINDOW_CHOICES else DEFAULT_WINDOW_DAYS


def _stamp(moment):
    return timezone.localtime(moment).strftime("%m-%d %H:%M")


def _author(row):
    if row["user_id"] is not None:
        return f"u{row['user_id']}"
    return f"m{row['mb_id'] or row['is_name']}"


def _label(row):
    return row["mb_id"] or row["is_name"] or "(알 수 없음)"


def _chunks(values, size=IN_CHUNK):
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _review_links(ids, label="후기 보기"):
    ids = sorted(ids)[:LINK_ID_CAP]
    return (Link(label, reverse("admin:shop_shopreview_changelist") + "?" + urlencode({"id__in": ",".join(map(str, ids))})),)


def _review_change_links(ids):
    return tuple(Link(f"후기 #{pk}", reverse("admin:shop_shopreview_change", args=[pk])) for pk in sorted(ids)[:SAMPLE_CAP])


def _order_change_links(order_ids):
    return tuple(Link(f"주문 {od_id}", reverse("admin:shop_shoporder_change", args=[od_id])) for od_id in order_ids[:SAMPLE_CAP])


def _burst_in(rows):
    """The densest 24h stretch of one product's 5-star reviews that has enough reviews by enough
    authors, or None. ``rows`` are sorted by time."""
    best = None
    inside = Counter()
    left = 0
    for right, row in enumerate(rows):
        inside[_author(row)] += 1
        while row["is_time"] - rows[left]["is_time"] > BURST_SPAN:
            author = _author(rows[left])
            inside[author] -= 1
            if not inside[author]:
                del inside[author]
            left += 1
        count = right - left + 1
        if count >= BURST_MIN_REVIEWS and len(inside) >= BURST_MIN_AUTHORS and (best is None or count > best[0]):
            best = (count, len(inside), rows[left : right + 1])
    return best


def check_review_bursts(window):
    rows = list(
        ShopReview.objects.filter(is_time__gte=window.since, is_time__lte=window.now, is_score=5, product__isnull=False)
        .order_by("-is_time")
        .values("pk", "product_id", "product__it_name", "user_id", "mb_id", "is_name", "is_time")[:BURST_ROW_CAP]
    )
    by_product = defaultdict(list)
    for row in reversed(rows):
        by_product[row["product_id"]].append(row)
    bursts = {}
    for product_id, product_rows in by_product.items():
        burst = _burst_in(product_rows)
        if burst:
            bursts[product_id] = burst
    if not bursts:
        return []
    baseline_start = window.since - timedelta(days=BURST_BASELINE_DAYS)
    earlier = dict(
        ShopReview.objects.filter(product_id__in=list(bursts), is_time__gte=baseline_start, is_time__lt=window.since)
        .values_list("product_id")
        .annotate(total=Count("pk"))
    )
    findings = []
    for product_id, (count, authors, burst_rows) in bursts.items():
        daily = earlier.get(product_id, 0) / BURST_BASELINE_DAYS
        if count < BURST_RATE_FACTOR * daily:
            continue
        ids = [row["pk"] for row in burst_rows]
        name = burst_rows[0]["product__it_name"] or product_id
        findings.append(
            Finding(
                rule="review_burst",
                severity="high" if authors >= 2 * BURST_MIN_AUTHORS else "medium",
                title=f"{name}: 24시간에 5점 후기 {count}건",
                evidence=(
                    f"작성자 {authors}명, {_stamp(burst_rows[0]['is_time'])} ~ {_stamp(burst_rows[-1]['is_time'])}",
                    f"이전 {BURST_BASELINE_DAYS}일 하루 평균 {daily:.2f}건 ({earlier.get(product_id, 0)}건)",
                    "작성자: " + ", ".join(sorted({_label(row) for row in burst_rows})[:SAMPLE_CAP * 2]),
                ),
                links=_review_links(ids),
            )
        )
    return sorted(findings, key=lambda finding: finding.title)


def _plain_text(review):
    return strip_tags(review["is_content"] or "")


def check_similar_reviews(window):
    reviews = list(
        ShopReview.objects.filter(is_time__gte=window.since, is_time__lte=window.now)
        .exclude(is_content="")
        .order_by("-is_time", "-pk")
        .values("pk", "product__it_name", "user_id", "mb_id", "is_name", "is_content", "is_time")[:SIMILARITY_REVIEW_CAP]
    )
    texts = [_plain_text(review) for review in reviews]
    authors = [_author(review) for review in reviews]
    result = similar_pairs(
        texts,
        threshold=SIMILARITY_THRESHOLD,
        min_length=SIMILARITY_MIN_LENGTH,
        allow_pair=lambda i, j: authors[i] != authors[j],
    )
    groups = clusters(result.pairs)
    group_of = {index: number for number, group in enumerate(groups) for index in group}
    similarities_by_group = defaultdict(list)
    for pair in result.pairs:
        similarities_by_group[group_of[pair.left]].append(pair.similarity)
    findings = []
    for number, group in enumerate(groups):
        members = [reviews[index] for index in group]
        similarities = similarities_by_group[number]
        distinct = {authors[index] for index in group}
        snippet = texts[group[0]].strip().replace("\n", " ")[:60]
        findings.append(
            Finding(
                rule="similar_review",
                severity="high" if len(distinct) >= 3 else "medium",
                title=f"거의 같은 후기 {len(group)}건 (작성자 {len(distinct)}명)",
                evidence=(
                    f"문자 3-gram 유사도 {min(similarities):.0%} ~ {max(similarities):.0%}",
                    f"본문: {snippet}",
                    "작성자: " + ", ".join(sorted({_label(review) for review in members})[:SAMPLE_CAP * 2]),
                ),
                links=_review_links([review["pk"] for review in members]),
            )
        )
    return findings


def check_reviews_without_purchase(window):
    reviews = list(
        ShopReview.objects.filter(is_time__gte=window.since, is_time__lte=window.now, user__isnull=False, product__isnull=False)
        .exclude(user__is_superuser=True)
        .order_by("-is_time", "-pk")
        .values("pk", "product_id", "product__it_name", "user_id", "mb_id", "is_name")[:NO_PURCHASE_REVIEW_CAP]
    )
    if not reviews:
        return []
    bought = set()
    products = {review["product_id"] for review in reviews}
    for user_chunk in _chunks({review["user_id"] for review in reviews}):
        for product_chunk in _chunks(products):
            bought.update(
                ShopOrderItem.objects.filter(order__user_id__in=user_chunk, it_id__in=product_chunk)
                .exclude(ct_status__in=INACTIVE_LINE_STATUSES)
                .values_list("order__user_id", "it_id")
                .distinct()
            )
    required = int(current_shipping_policy().de_item_use_write or 0) == 1
    per_member = defaultdict(list)
    for review in reviews:
        if (review["user_id"], review["product_id"]) not in bought:
            per_member[review["user_id"]].append(review)
    note = (
        "후기 작성 조건 켜짐: 우회 또는 이후 주문 취소"
        if required
        else "후기 작성 조건 꺼짐 (허용된 후기)"
    )
    findings = []
    for member_reviews in per_member.values():
        names = sorted({review["product__it_name"] or review["product_id"] for review in member_reviews})
        findings.append(
            Finding(
                rule="no_purchase_review",
                severity="medium" if required else "info",
                title=f"{_label(member_reviews[0])}: 구매 이력 없는 후기 {len(member_reviews)}건",
                evidence=(f"상품: {', '.join(names[:SAMPLE_CAP])}", note),
                links=_review_links([review["pk"] for review in member_reviews]),
            )
        )
    return sorted(findings, key=lambda finding: (SEVERITY_ORDER[finding.severity], finding.title))


def _coupon_orders(order_ids, member_ids):
    """Which of ``order_ids`` used a coupon, and how many of ``member_ids`` used the signup coupon."""
    used = {
        od_id
        for od_id in ShopOrder.objects.filter(od_id__in=order_ids).filter(Q(od_coupon__gt=0) | Q(od_send_coupon__gt=0)).values_list("od_id", flat=True)
    }
    logs = ShopCouponLog.objects.filter(Q(order_id__in=order_ids) | Q(od_id__in=order_ids))
    used.update(od_id for od_id in logs.values_list("od_id", flat=True) if od_id)
    used.update(od_id for od_id in logs.exclude(order__isnull=True).values_list("order_id", flat=True))
    signup_users = set(
        logs.filter(coupon__cp_subject=SIGNUP_COUPON_SUBJECT, user_id__in=member_ids).values_list("user_id", flat=True)
    )
    return used, signup_users


def check_shared_ip_accounts(window):
    base = ShopOrder.objects.filter(od_datetime__gte=window.since, od_datetime__lte=window.now, od_ip__isnull=False, user__isnull=False)
    shared = list(
        base.values("od_ip")
        .annotate(members=Count("user", distinct=True), orders=Count("od_id"))
        .filter(members__gte=SHARED_IP_MIN_MEMBERS)
        .order_by("-members", "-orders", "od_ip")[:SHARED_IP_CAP]
    )
    if not shared:
        return []
    ips = [row["od_ip"] for row in shared]
    rows = list(
        base.filter(od_ip__in=ips)
        .order_by("-od_datetime")
        .values("od_id", "od_ip", "user_id", "user__username")[: SHARED_IP_ORDER_CAP]
    )
    by_ip = defaultdict(list)
    for row in rows:
        by_ip[row["od_ip"]].append(row)
    used, signup_users = _coupon_orders([row["od_id"] for row in rows], {row["user_id"] for row in rows})
    findings = []
    for entry in shared:
        ip = entry["od_ip"]
        ip_rows = by_ip[ip]
        coupon_orders = [row["od_id"] for row in ip_rows if row["od_id"] in used]
        signup = {row["user_id"] for row in ip_rows} & signup_users
        flagged = bool(coupon_orders or signup)
        evidence = [
            f"주문 {entry['orders']}건, 서로 다른 회원 {entry['members']}명",
            "회원: " + ", ".join(sorted({row["user__username"] for row in ip_rows})[: SAMPLE_CAP * 2]),
        ]
        if flagged:
            evidence.append(f"쿠폰 사용 주문 {len(coupon_orders)}건, 신규 회원 쿠폰 사용 회원 {len(signup)}명")
        findings.append(
            Finding(
                rule="shared_ip",
                severity="high" if flagged else "medium",
                title=f"IP {ip}: 회원 {entry['members']}명이 주문",
                evidence=tuple(evidence),
                links=(
                    Link("이 IP의 주문 목록", reverse("admin:shop_shoporder_changelist") + "?" + urlencode({"od_ip": ip})),
                    *_order_change_links(coupon_orders or [row["od_id"] for row in ip_rows]),
                ),
            )
        )
    return findings


RULES = (
    Rule(
        "review_burst",
        "후기 몰림",
        f"한 상품에 24시간 안에 5점 후기가 {BURST_MIN_REVIEWS}건 이상, 작성자 {BURST_MIN_AUTHORS}명 이상이고 "
        f"이전 {BURST_BASELINE_DAYS}일 하루 평균의 {BURST_RATE_FACTOR}배 이상일 때",
        check_review_bursts,
    ),
    Rule(
        "similar_review",
        "유사 후기",
        f"다른 작성자의 후기 본문이 문자 3-gram 유사도 {SIMILARITY_THRESHOLD:.0%} 이상(공백·기호 제외 {SIMILARITY_MIN_LENGTH}자 이상)일 때. "
        f"기간 안의 최신 후기 {SIMILARITY_REVIEW_CAP:,}건까지 비교합니다",
        check_similar_reviews,
    ),
    Rule(
        "no_purchase_review",
        "구매 이력 없는 후기",
        "회원이 그 상품의 유효한 주문 상품 줄(취소·반품·품절 제외)이 없는데 후기를 쓴 경우. 슈퍼관리자는 제외합니다",
        check_reviews_without_purchase,
    ),
    Rule(
        "shared_ip",
        "동일 IP 다중 계정",
        f"한 주문 IP를 {SHARED_IP_MIN_MEMBERS}명 이상의 회원이 쓴 경우. 쿠폰이나 신규 회원 쿠폰을 쓴 주문이 있으면 주의로 올립니다. "
        "공용 회선(학교, 사무실)은 정상일 수 있습니다",
        check_shared_ip_accounts,
    ),
)


def build_report(days=DEFAULT_WINDOW_DAYS, now=None):
    window = Window(days=window_days(days), now=now or timezone.now())
    results = [RuleResult(rule, tuple(rule.check(window))) for rule in RULES]
    counts = Counter(finding.severity for result in results for finding in result.findings)
    return {
        "window": window,
        "days": window.days,
        "results": results,
        "counts": {key: counts.get(key, 0) for key in SEVERITY_ORDER},
        "total": sum(counts.values()),
    }
