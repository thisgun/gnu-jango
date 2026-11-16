"""이상 활동 점검: review manipulation and coupon abuse, by fixed rules an operator can check.

Nothing here changes data or acts on a member. Each rule is a ``Rule`` in ``RULES``; it returns
``Finding`` rows that carry their own evidence and links to the admin rows to look at. The shop
stores no abuse labels, so there is no score: every finding says which numbers crossed which
threshold.

Dropped on purpose: "many accounts registered from one IP in a day". The member model stores no
signup IP (only ``me_send_ip``, the IP a memo was sent from), so the rule has no data.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib.admin.models import LogEntry
from django.db.models import Case, Count, Exists, Min, OuterRef, Q, TextField, Value, When
from django.db.models.functions import Cast
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from .models import ShopCouponLog, ShopOrder, ShopReview
from .review_gate import received_lines
from .shipping import current_shipping_policy
from .signup_coupon import SIGNUP_COUPON_SUBJECT
from .text_similarity import clusters, similar_pairs

WINDOW_CHOICES = (7, 30, 90)
DEFAULT_WINDOW_DAYS = 30

SEVERITY_ORDER = {"high": 0, "medium": 1, "info": 2}
SEVERITY_LABELS = {"high": "주의", "medium": "확인", "info": "참고"}

# 후기 몰림. Five 5-star reviews from three people inside 24 hours is rare for a small shop, and
# the burst must beat the product's own pace by 10x: a product that already gets a review every
# other day, or that sells steadily from its first day, is not "bursting" at five a day. The pace
# is every other visible review of the product since BURST_BASELINE_DAYS before the window, spread
# over the days the product has had reviews (at least BURST_MIN_PACE_DAYS).
BURST_MIN_REVIEWS = 5
BURST_MIN_AUTHORS = 3
BURST_SPAN = timedelta(hours=24)
BURST_BASELINE_DAYS = 90
BURST_RATE_FACTOR = 10
BURST_MIN_PACE_DAYS = 7
BURST_ROW_CAP = 20_000

# 유사 후기. Only the newest SIMILARITY_REVIEW_CAP reviews of the window are compared.
SIMILARITY_THRESHOLD = 0.8
SIMILARITY_MIN_LENGTH = 20
SIMILARITY_REVIEW_CAP = 2_000

NO_PURCHASE_REVIEW_CAP = 2_000
NO_PURCHASE_DISPLAY_CAP = 200
IN_CHUNK = 500

SHARED_IP_MIN_MEMBERS = 3
SHARED_IP_CAP = 30

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
class Found:
    findings: tuple
    counts: Counter
    note: str = ""

    @classmethod
    def of(cls, findings, note="", cap=None):
        return cls(tuple(findings[:cap]), Counter(finding.severity for finding in findings), note)


@dataclass(frozen=True)
class Rule:
    code: str
    title: str
    summary: str
    check: object
    reads_reviews: bool = False


@dataclass(frozen=True)
class RuleResult:
    rule: Rule
    findings: tuple
    counts: Counter = field(default_factory=Counter)
    note: str = ""
    restricted: bool = False

    @property
    def total(self):
        return sum(self.counts.values())

    @property
    def hidden_count(self):
        return max(self.total - len(self.findings), 0)


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


def _listed(items, cap):
    items = list(items)
    text = ", ".join(items[:cap])
    return f"{text} 외 {len(items) - cap}" if len(items) > cap else text


def _visible_reviews():
    return ShopReview.objects.filter(is_confirm="1")


def _pending_q():
    handled = LogEntry.objects.filter(
        content_type__app_label=ShopReview._meta.app_label,
        content_type__model=ShopReview._meta.model_name,
        object_id=Cast(OuterRef("pk"), TextField()),
    )
    return Q(is_confirm="0") & ~Q(Exists(handled))


def _capped_note(shown, found, what):
    return f"기간 안의 {what} {found:,}건 중 최신 {shown:,}건만 검사했습니다" if found > shown else ""


def _review_links(ids, label="후기 보기"):
    ids = sorted(ids)
    if len(ids) > LINK_ID_CAP:
        label = f"{label} (전체 {len(ids)}건 중 {LINK_ID_CAP}건)"
    query = urlencode({"id__in": ",".join(map(str, ids[:LINK_ID_CAP]))})
    return (Link(label, reverse("admin:shop_shopreview_changelist") + "?" + query),)


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


def _burst_pace(bursts, baseline_start, now):
    """Per product: (reviews outside the burst's own 24h, days they are spread over)."""
    totals = {}
    inside = {}
    ids = list(bursts)
    for chunk in _chunks(ids, 200):
        rows = (
            _visible_reviews()
            .filter(product_id__in=chunk, is_time__gte=baseline_start, is_time__lte=now)
            .values("product_id")
            .annotate(total=Count("pk"), first=Min("is_time"))
        )
        totals.update({row["product_id"]: (row["total"], row["first"]) for row in rows})
        spans = Q()
        for product_id in chunk:
            start = bursts[product_id][2][0]["is_time"]
            spans |= Q(product_id=product_id, is_time__gte=start, is_time__lte=start + BURST_SPAN)
        inside.update(_visible_reviews().filter(spans).values_list("product_id").annotate(n=Count("pk")))
    pace = {}
    for product_id, (total, first) in totals.items():
        others = total - inside.get(product_id, 0)
        active_days = (now - first).total_seconds() / 86400
        pace[product_id] = (others, max(BURST_MIN_PACE_DAYS, active_days - BURST_SPAN.days))
    return pace


def check_review_bursts(window):
    five_star = _visible_reviews().filter(is_time__gte=window.since, is_time__lte=window.now, is_score=5, product__isnull=False)
    rows = list(
        five_star.order_by("-is_time").values("pk", "product_id", "product__it_name", "user_id", "mb_id", "is_name", "is_time")[:BURST_ROW_CAP]
    )
    note = _capped_note(len(rows), five_star.count(), "5점 후기") if len(rows) == BURST_ROW_CAP else ""
    by_product = defaultdict(list)
    for row in reversed(rows):
        by_product[row["product_id"]].append(row)
    bursts = {}
    for product_id, product_rows in by_product.items():
        burst = _burst_in(product_rows)
        if burst:
            bursts[product_id] = burst
    if not bursts:
        return Found.of((), note)
    pace = _burst_pace(bursts, window.since - timedelta(days=BURST_BASELINE_DAYS), window.now)
    findings = []
    for product_id, (count, authors, burst_rows) in bursts.items():
        others, days = pace[product_id]
        daily = others / days
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
                    f"그 밖의 후기 하루 평균 {daily:.2f}건 ({others}건 / {days:.0f}일)",
                    "작성자: " + _listed(sorted({_label(row) for row in burst_rows}), SAMPLE_CAP * 2),
                ),
                links=_review_links(ids),
            )
        )
    findings.sort(key=lambda finding: finding.title)
    return Found.of(findings, note)


def _plain_text(review):
    return strip_tags(review["is_content"] or "")


def check_similar_reviews(window):
    in_window = _visible_reviews().filter(is_time__gte=window.since, is_time__lte=window.now).exclude(is_content="")
    reviews = list(
        in_window.order_by("-is_time", "-pk").values("pk", "product__it_name", "user_id", "mb_id", "is_name", "is_content", "is_time")[
            :SIMILARITY_REVIEW_CAP
        ]
    )
    note = _capped_note(len(reviews), in_window.count(), "후기") if len(reviews) == SIMILARITY_REVIEW_CAP else ""
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
                    "작성자: " + _listed(sorted({_label(review) for review in members}), SAMPLE_CAP * 2),
                ),
                links=_review_links([review["pk"] for review in members]),
            )
        )
    return Found.of(findings, note)


def _waiting_first(member_reviews):
    return (all(review["is_confirm"] == "1" for review in member_reviews), -len(member_reviews), _label(member_reviews[0]))


def check_reviews_without_purchase(window):
    in_window = (
        ShopReview.objects.filter(Q(is_confirm="1") | _pending_q())
        .filter(is_time__gte=window.since, is_time__lte=window.now, user__isnull=False, product__isnull=False)
        .exclude(user__is_superuser=True)
    )
    reviews = list(
        in_window.order_by("-is_time", "-pk").values("pk", "product_id", "product__it_name", "user_id", "mb_id", "is_name", "is_confirm")[
            :NO_PURCHASE_REVIEW_CAP
        ]
    )
    if not reviews:
        return Found.of(())
    note = _capped_note(len(reviews), in_window.count(), "후기") if len(reviews) == NO_PURCHASE_REVIEW_CAP else ""
    received = set()
    products = {review["product_id"] for review in reviews}
    for user_chunk in _chunks({review["user_id"] for review in reviews}):
        for product_chunk in _chunks(products):
            received.update(
                received_lines()
                .filter(order__user_id__in=user_chunk, it_id__in=product_chunk)
                .values_list("order__user_id", "it_id")
                .distinct()
            )
    required = int(current_shipping_policy().de_item_use_write or 0) == 1
    per_member = defaultdict(list)
    for review in reviews:
        if (review["user_id"], review["product_id"]) not in received:
            per_member[review["user_id"]].append(review)
    advice = "후기 작성 조건 켜짐: 우회 또는 이후 주문 취소" if required else "후기 작성 조건 꺼짐 (허용된 후기)"
    findings = []
    for member_reviews in sorted(per_member.values(), key=_waiting_first):
        names = sorted({review["product__it_name"] or review["product_id"] for review in member_reviews})
        pending = [review["pk"] for review in member_reviews if review["is_confirm"] != "1"]
        title = f"{_label(member_reviews[0])}: 배송 완료 이력 없는 후기 {len(member_reviews)}건"
        evidence = [f"상품: {_listed(names, SAMPLE_CAP)}", advice]
        if pending:
            title += f" (승인 대기 {len(pending)}건)"
            evidence.append("승인 대기 후기는 아직 쇼핑몰에 보이지 않습니다. 승인 전에 확인하십시오")
        findings.append(
            Finding(
                rule="no_purchase_review",
                severity="medium" if required else "info",
                title=title,
                evidence=tuple(evidence),
                links=_review_links([review["pk"] for review in member_reviews]) + _review_change_links(pending),
            )
        )
    return Found.of(findings, note, cap=NO_PURCHASE_DISPLAY_CAP)


def _coupon_order_q():
    logged = ShopCouponLog.objects.filter(Q(order_id=OuterRef("pk")) | Q(od_id=OuterRef("od_id")))
    return Q(od_coupon__gt=0) | Q(od_send_coupon__gt=0) | Q(Exists(logged))


def check_shared_ip_accounts(window):
    base = ShopOrder.objects.filter(od_datetime__gte=window.since, od_datetime__lte=window.now, od_ip__isnull=False, user__isnull=False)
    signup_users = ShopCouponLog.objects.filter(coupon__cp_subject=SIGNUP_COUPON_SUBJECT, user__isnull=False).values("user_id")
    flagged_q = Q(coupon_orders__gt=0) | Q(signup_members__gt=0)
    grouped = (
        base.values("od_ip")
        .annotate(
            members=Count("user", distinct=True),
            orders=Count("od_id"),
            coupon_orders=Count("od_id", filter=_coupon_order_q()),
            signup_members=Count("user", distinct=True, filter=Q(user_id__in=signup_users)),
        )
        .filter(members__gte=SHARED_IP_MIN_MEMBERS)
    )
    total = grouped.count()
    if not total:
        return Found.of(())
    high = grouped.filter(flagged_q).count()
    shared = list(
        grouped.annotate(is_flagged=Case(When(flagged_q, then=Value(1)), default=Value(0)))
        .order_by("-is_flagged", "-members", "-orders", "od_ip")[:SHARED_IP_CAP]
    )
    in_scope = base.filter(od_ip__in=[entry["od_ip"] for entry in shared])
    findings = []
    for entry in shared:
        ip = entry["od_ip"]
        coupon_count = entry["coupon_orders"]
        signup_count = entry["signup_members"]
        ip_orders = in_scope.filter(od_ip=ip)
        names = ip_orders.order_by("user__username").values_list("user__username", flat=True).distinct()[: SAMPLE_CAP * 2 + 1]
        sample = (ip_orders.filter(_coupon_order_q()) if coupon_count else ip_orders).order_by("-od_datetime").values_list("od_id", flat=True)[:SAMPLE_CAP]
        flagged = bool(coupon_count or signup_count)
        evidence = [
            f"주문 {entry['orders']}건, 서로 다른 회원 {entry['members']}명",
            "회원: " + _listed(names, SAMPLE_CAP * 2) + (f" (전체 {entry['members']}명)" if entry["members"] > SAMPLE_CAP * 2 else ""),
        ]
        if flagged:
            evidence.append(f"쿠폰 사용 주문 {coupon_count}건, 신규 회원 쿠폰 사용 회원 {signup_count}명")
        findings.append(
            Finding(
                rule="shared_ip",
                severity="high" if flagged else "medium",
                title=f"IP {ip}: 회원 {entry['members']}명이 주문",
                evidence=tuple(evidence),
                links=(
                    Link("이 IP의 주문 목록", reverse("admin:shop_shoporder_changelist") + "?" + urlencode({"od_ip": ip})),
                    *_order_change_links(list(sample)),
                ),
            )
        )
    return Found(tuple(findings), Counter(high=high, medium=total - high))


RULES = (
    Rule(
        "review_burst",
        "후기 몰림",
        f"한 상품에 24시간 안에 5점 후기가 {BURST_MIN_REVIEWS}건 이상, 작성자 {BURST_MIN_AUTHORS}명 이상이고 "
        f"그 상품의 평소 하루 평균(이전 {BURST_BASELINE_DAYS}일과 같은 기간의 나머지 날)의 {BURST_RATE_FACTOR}배 이상일 때. "
        "숨긴 후기는 제외합니다",
        check_review_bursts,
        reads_reviews=True,
    ),
    Rule(
        "similar_review",
        "유사 후기",
        f"다른 작성자의 후기 본문이 문자 3-gram 유사도 {SIMILARITY_THRESHOLD:.0%} 이상(공백·기호 제외 {SIMILARITY_MIN_LENGTH}자 이상)일 때. "
        f"기간 안의 최신 후기 {SIMILARITY_REVIEW_CAP:,}건까지 비교하며 숨긴 후기는 제외합니다",
        check_similar_reviews,
        reads_reviews=True,
    ),
    Rule(
        "no_purchase_review",
        "배송 완료 이력 없는 후기",
        "회원이 그 상품을 배송 완료(완료)로 받은 주문 줄이 없는데 후기를 쓴 경우. 쇼핑몰의 후기 작성 조건과 같은 기준이며 "
        "취소·반품·품절, 아직 배송 전인 주문은 구매로 보지 않습니다. 승인 대기 후기는 포함해 맨 위에 표시하고, "
        "슈퍼관리자의 후기와 관리 화면에서 숨긴 후기는 제외합니다",
        check_reviews_without_purchase,
        reads_reviews=True,
    ),
    Rule(
        "shared_ip",
        "동일 IP 다중 계정",
        f"한 주문 IP를 {SHARED_IP_MIN_MEMBERS}명 이상의 회원이 쓴 경우. 쿠폰이나 신규 회원 쿠폰을 쓴 주문이 있으면 주의로 올리고, "
        f"IP가 {SHARED_IP_CAP}개를 넘으면 주의부터 보여 줍니다. "
        "공용 회선(학교, 사무실, 통신사 공용 IP)은 정상일 수 있습니다. IPv6는 주소 그대로 비교합니다",
        check_shared_ip_accounts,
    ),
)


def build_report(days=DEFAULT_WINDOW_DAYS, now=None, can_view_reviews=True):
    window = Window(days=window_days(days), now=now or timezone.now())
    results = []
    for rule in RULES:
        if rule.reads_reviews and not can_view_reviews:
            results.append(RuleResult(rule, (), restricted=True))
            continue
        found = rule.check(window)
        results.append(RuleResult(rule, found.findings, found.counts, found.note))
    counts = sum((result.counts for result in results), Counter())
    return {
        "window": window,
        "days": window.days,
        "results": results,
        "counts": {key: counts.get(key, 0) for key in SEVERITY_ORDER},
        "total": sum(counts.values()),
        "hidden": sum(result.hidden_count for result in results),
        "is_trimmed": any(result.hidden_count or result.note for result in results),
    }
