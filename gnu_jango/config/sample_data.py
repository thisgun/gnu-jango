"""Create and remove a small, trackable set of public demo content."""

import json
import uuid
from datetime import timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

from gnu_jango.api.page_bootstrap import batch_bootstrap_changes
from gnu_jango.bbs.models import Board, Comment, Group, Post, Post_file
from gnu_jango.bbs.utils import get_next_num, get_pretty_url
from gnu_jango.config import config as site_config
from gnu_jango.config.models import Config
from gnu_jango.core.models import ContentPage, FAQItem, FAQMaster, Poll, PollChoice, Site_menu
from gnu_jango.shop.models import ShopBanner, ShopCategory, ShopProduct
from gnu_jango.notifications.context import suppress_notification_events


MANIFEST_NAME = "g5_sample_data_manifest_v1"
MANIFEST_VERSION = 1
SAMPLE_IMAGES = tuple(f"product-{number:02}.webp" for number in range(1, 7))
SAMPLE_BANNER = "banner.webp"
BASE36_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
SAMPLE_ASSET_SIZES = {
    "product-01.webp": 15778,
    "product-02.webp": 11238,
    "product-03.webp": 14112,
    "product-04.webp": 12400,
    "product-05.webp": 10332,
    "product-06.webp": 8790,
    "banner.webp": 11552,
}

MANIFEST_LIST_FIELDS = (
    "groups",
    "boards",
    "boards_used",
    "posts",
    "comments",
    "post_files",
    "categories",
    "products",
    "banners",
    "faq_masters",
    "faq_items",
    "polls",
    "poll_choices",
    "menus",
    "menu_snapshots",
    "content_pages",
    "content_page_snapshots",
    "home_settings",
    "board_map",
)

COMMUNITY_MANIFEST_FIELDS = (
    "groups", "boards", "boards_used", "posts", "comments", "post_files",
    "faq_masters", "faq_items", "polls", "poll_choices", "menus", "content_pages",
)

SAMPLE_CONTENT_PAGES = {
    "company": (
        "사이트 소개",
        "<p>이 사이트는 그누보드5와 영카트 기능을 살펴보기 위한 데모입니다. 게시글과 상품은 화면 예시를 위해 만든 가상 데이터입니다.</p>"
        "<p>이 데모는 실제 판매나 서비스 운영을 위한 사이트가 아닙니다.</p>",
    ),
    "privacy": (
        "개인정보처리방침",
        "<p><strong>데모 안내</strong></p><p>이 페이지는 예시입니다. 실제 개인정보 처리방침이 아니며, 데모 운영자가 실제 개인정보를 수집한다는 뜻도 아닙니다.</p>"
        "<p>실서비스를 시작하기 전에는 실제 수집 항목, 이용 목적, 보유 기간과 운영 방식에 맞춰 내용을 작성하고 검토해야 합니다.</p>",
    ),
    "provision": (
        "이용약관",
        "<p><strong>데모 안내</strong></p><p>이 페이지는 화면 확인을 위한 예시이며 실제 서비스에 적용되는 이용약관이 아닙니다.</p>"
        "<p>실서비스를 시작하기 전에는 서비스 운영 방식과 관련 법령에 맞는 약관을 별도로 작성하고 검토해야 합니다.</p>",
    ),
}

BOARD_CONTENT = {
    "notice": {
        "subject": "공지사항",
        "posts": [
            ("새로운 커뮤니티에 오신 것을 환영합니다", "이곳에서 공지와 서비스 소식을 확인할 수 있습니다. 편하게 둘러보세요.", True, None),
            ("샘플 콘텐츠 안내", "관리자 샘플 데이터 메뉴에서 예시 게시글과 상품을 추가하거나 정리할 수 있습니다.", False, None),
            ("게시판 이용 방법", "질문과 의견은 자유게시판이나 질문답변 게시판에 남겨 주세요.", False, None),
        ],
    },
    "free": {
        "subject": "자유게시판",
        "posts": [
            ("커뮤니티에 오신 걸 환영합니다", "관심 있는 이야기와 새로운 소식을 자유롭게 나눠 보세요.", False, None),
            ("요즘 책상 위에 두고 쓰는 것", "자주 쓰는 물건을 가까이에 두니 하루가 한결 정돈되는 느낌입니다.", False, None),
            ("좋은 도구를 고르는 기준", "오래 쓸 수 있는지, 지금 하는 일에 꼭 필요한지 먼저 살펴봅니다.", False, None),
            ("오늘의 작은 기록", "바쁜 하루 중 잠깐 멈춰서 마음에 남은 장면을 적어 봅니다.", False, None),
            ("처음 오셨다면 인사를 남겨 주세요", "이야기를 나누고 싶은 주제가 있다면 새 글로 시작해 보세요.", False, None),
        ],
    },
    "qa": {
        "subject": "질문답변",
        "posts": [
            ("게시글에 사진을 올리려면 어떻게 하나요?", "글쓰기 화면에서 이미지 파일을 선택한 뒤 등록하면 됩니다.", False, None),
            ("상품 목록은 어디에서 볼 수 있나요?", "상단 메뉴의 쇼핑몰을 선택하면 상품과 카테고리를 확인할 수 있습니다.", False, None),
            ("모바일에서도 게시판을 이용할 수 있나요?", "화면 크기에 맞춰 게시판과 쇼핑몰이 자동으로 정리됩니다.", False, None),
            ("계정 정보를 바꾸고 싶어요", "로그인한 뒤 마이페이지에서 프로필과 계정 설정을 확인해 주세요.", False, None),
        ],
    },
    "gallery": {
        "subject": "갤러리",
        "posts": [
            ("기록이 시작되는 책상", "일과 기록을 차분히 시작할 수 있는 공간을 담았습니다.", False, 1),
            ("나무결이 돋보이는 데스크 매트", "책상 위에 따뜻한 질감을 더하는 작은 소품입니다.", False, 2),
            ("가볍게 높이를 더하는 노트북 스탠드", "작업 공간을 단정하게 정리하는 데 도움이 됩니다.", False, 3),
            ("투명한 유리 머그", "아침의 빛이 잘 어울리는 데일리 컵입니다.", False, 4),
            ("오래 쓰는 주방 도구", "매일 사용하는 도구는 손에 편안하게 잡히는 것이 좋습니다.", False, 5),
            ("하루를 천천히 준비하는 시간", "좋아하는 차와 함께 여유로운 아침을 준비해 봅니다.", False, 6),
        ],
    },
}

PRODUCTS = (
    ("책상 위의 작은 기록 세트", 28000, "노트와 펜을 한곳에 두고 하루를 기록해 보세요."),
    ("슬림 데스크 선반", 42000, "자주 쓰는 소품을 편리하게 올려둘 수 있는 선반입니다."),
    ("내추럴 우드 데스크 매트", 35000, "차분한 나무 질감으로 작업 공간을 정돈해 줍니다."),
    ("알루미늄 노트북 스탠드", 39000, "시선을 편안하게 맞추고 책상 공간을 넓혀 줍니다."),
    ("데일리 글라스 머그", 16000, "가볍고 투명한 유리로 만든 데일리 머그입니다."),
    ("스테인리스 드립 포트", 54000, "물을 천천히 따르기 좋은 작은 드립 포트입니다."),
)
DISCOUNTED_SAMPLE_PRODUCT_NUMBERS = frozenset({2, 5})


def _sample_product_fields(number, price):
    discounted = number in DISCOUNTED_SAMPLE_PRODUCT_NUMBERS
    compare_price = ((price * 5 + 3999) // 4000) * 1000 if discounted else 0
    return {
        "it_cust_price": compare_price,
        "it_type1": "1",
        "it_type2": "1",
        "it_type3": "1",
        "it_type4": "1",
        "it_type5": "1" if discounted else "",
    }


FAQS = (
    ("샘플 데이터는 어떻게 정리하나요?", "관리자 메뉴의 샘플 데이터 페이지에서 ‘샘플 데이터 삭제’를 선택하면 이 페이지가 만든 콘텐츠만 정리합니다."),
    ("샘플 이미지가 저장 공간을 많이 차지하나요?", "이미지는 WebP로 최적화되어 앱의 정적 리소스로 제공됩니다. 갤러리 글과 상품은 같은 작은 이미지를 함께 사용합니다."),
    ("샘플 상품으로 주문할 수 있나요?", "예시 상품은 쇼핑몰 화면을 살펴보기 위한 데이터입니다. 실제 결제 연동은 설정하지 않습니다."),
    ("기존 게시판이나 상품도 삭제되나요?", "삭제 작업은 생성 기록에 저장된 샘플 항목만 대상으로 합니다. 샘플에 실제 댓글이나 주문 이력이 연결되어 있으면 해당 항목을 남깁니다."),
)

POLL_CHOICES = ("커뮤니티 게시글", "사진 갤러리", "라이프스타일 상품", "사용 팁과 가이드")


class SampleDataError(Exception):
    """A safe, user-facing sample-data operation error."""


def empty_manifest():
    return {
        "version": MANIFEST_VERSION,
        "created_at": timezone.now().isoformat(),
        **{field: [] for field in MANIFEST_LIST_FIELDS},
    }


def _decode_manifest(config_row):
    if not config_row:
        return None
    try:
        manifest = json.loads(config_row.value)
    except (TypeError, ValueError) as exc:
        raise SampleDataError("샘플 데이터 관리 기록을 읽을 수 없습니다. 관리자에게 확인해 주세요.") from exc
    if not isinstance(manifest, dict) or manifest.get("version") != MANIFEST_VERSION:
        raise SampleDataError("이 샘플 데이터 관리 기록은 현재 버전과 맞지 않습니다.")
    for field in MANIFEST_LIST_FIELDS:
        # Older shop-only manifests predate the community navigation fields.
        manifest.setdefault(field, [])
        if not isinstance(manifest.get(field), list):
            raise SampleDataError("샘플 데이터 관리 기록의 형식이 올바르지 않습니다.")
    return manifest


def _ids(manifest, field):
    return manifest.get(field, []) if manifest else []


def _asset_size(name):
    if name not in (*SAMPLE_IMAGES, SAMPLE_BANNER):
        raise SampleDataError("등록되지 않은 샘플 이미지입니다.")
    return SAMPLE_ASSET_SIZES[name]


def sample_asset_summary():
    items = []
    for name in (*SAMPLE_IMAGES, SAMPLE_BANNER):
        items.append({"name": name, "bytes": _asset_size(name)})
    return {"items": items, "total_bytes": sum(item["bytes"] for item in items)}


def managed_counts(manifest):
    if not manifest:
        return {
            "groups": 0,
            "boards": 0,
            "posts": 0,
            "comments": 0,
            "gallery_images": 0,
            "categories": 0,
            "products": 0,
            "banners": 0,
            "faqs": 0,
            "polls": 0,
            "menus": 0,
            "content_pages": 0,
        }
    return {
        "groups": Group.objects.filter(pk__in=_ids(manifest, "groups")).count(),
        "boards": Board.objects.filter(pk__in=_ids(manifest, "boards")).count(),
        "posts": Post.objects.filter(pk__in=_ids(manifest, "posts")).count(),
        "comments": Comment.objects.filter(pk__in=_ids(manifest, "comments")).count(),
        "gallery_images": Post_file.objects.filter(pk__in=_ids(manifest, "post_files")).count(),
        "categories": ShopCategory.objects.filter(pk__in=_ids(manifest, "categories")).count(),
        "products": ShopProduct.objects.filter(pk__in=_ids(manifest, "products")).count(),
        "banners": ShopBanner.objects.filter(pk__in=_ids(manifest, "banners")).count(),
        "faqs": FAQItem.objects.filter(pk__in=_ids(manifest, "faq_items")).count(),
        "polls": Poll.objects.filter(pk__in=_ids(manifest, "polls")).count(),
        "menus": Site_menu.objects.filter(pk__in=_ids(manifest, "menus")).count(),
        "content_pages": ContentPage.objects.filter(pk__in=_ids(manifest, "content_pages")).count(),
    }


def get_status():
    config_row = Config.objects.filter(name=MANIFEST_NAME).first()
    manifest = _decode_manifest(config_row)
    counts = managed_counts(manifest)
    return {
        "manifest": manifest,
        "counts": counts,
        "has_data": any(counts.values()),
        "has_community_data": any(counts[field] for field in ("boards", "posts", "comments", "faqs", "menus", "content_pages")),
        "shop_status": shop_sample_status(manifest),
        "assets": sample_asset_summary(),
    }


def shop_sample_status(manifest):
    products = list(ShopProduct.objects.filter(pk__in=_ids(manifest, "products")).select_related("category"))
    visible = [product for product in products if product.it_use == "1" and (not product.category_id or product.category.ca_use)]
    sections = [
        {"name": name, "count": sum(getattr(product, f"it_type{number}") == "1" for product in visible)}
        for number, name in enumerate(("히트상품", "추천상품", "신상품", "인기상품", "할인상품"), start=1)
    ]
    unassigned = sum(not any(getattr(product, f"it_type{number}") == "1" for number in range(1, 6)) for product in visible)
    missing = max(0, len(PRODUCTS) - len(products))
    hidden = len(products) - len(visible)
    return {
        "total": len(products), "visible": len(visible), "missing": missing, "hidden": hidden,
        "unassigned": unassigned, "sections": sections,
        "needs_repair": bool(missing or hidden or unassigned),
    }


def _public_board(board):
    group = board.group
    return board.bo_list_level <= 1 and board.bo_read_level <= 1 and not (group and group.gr_use_access)


def _new_board(table, subject, token, manifest):
    candidates = (table, f"sample-{table}", f"demo-{table}-{token[:5]}")
    for candidate in candidates:
        existing = Board.objects.filter(bo_table=candidate).first()
        if existing:
            if _public_board(existing):
                return existing
            continue

        # Sites that name tables in Korean (/bbs/자유게시판) already have this board under its subject.
        same_subject = Board.objects.filter(bo_subject=subject).order_by("pk")
        existing = next((board for board in same_subject if _public_board(board)), None)
        if existing:
            return existing

        board = Board.objects.create(
            group=_get_sample_group(manifest),
            bo_subject=subject,
            bo_table=candidate,
            bo_mobile_subject=subject,
            bo_list_level=1,
            bo_read_level=1,
            bo_write_level=1,
            bo_reply_level=1,
            bo_comment_level=1,
            bo_upload_level=1,
            bo_download_level=1,
            bo_html_level=1,
            bo_link_level=1,
            bo_skin="basic",
            bo_mobile_skin="basic",
            bo_table_width=100,
            bo_subject_len=60,
            bo_mobile_subject_len=30,
            bo_page_rows=15,
            bo_mobile_page_rows=15,
            bo_image_width=720,
            bo_gallery_cols=3,
            bo_gallery_width=240,
            bo_gallery_height=240,
            bo_mobile_gallery_width=160,
            bo_mobile_gallery_height=160,
            bo_upload_count=1,
            bo_upload_size=1024 * 1024,
            bo_use_search=True,
        )
        manifest["boards"].append(board.pk)
        return board
    raise SampleDataError(f"{subject} 샘플 게시판을 만들 수 없습니다.")


def _get_sample_group(manifest):
    group = Group.objects.filter(gr_id="sample").first()
    if group:
        return group
    group = Group.objects.create(gr_id="sample", gr_subject="샘플 콘텐츠")
    manifest["groups"].append(group.pk)
    return group


def _free_root_category_id():
    """A two-character root code that no category starts with, and that starts with none.

    YoungCart codes nest two characters per level and product listings match by prefix, so a
    longer code would read as a sub-category and could land inside a real one. The prefix match
    ignores case on SQLite and most MySQL collations, so codes are compared in lower case.
    """
    codes = {ca_id.lower() for ca_id in ShopCategory.objects.values_list("ca_id", flat=True) if ca_id}
    taken = {code[:2] for code in codes}
    for first in reversed(BASE36_DIGITS[1:]):
        if first in codes:
            continue
        for second in BASE36_DIGITS:
            if first + second not in taken:
                return first + second
    raise SampleDataError("샘플 분류에 사용할 빈 분류 코드가 없습니다.")


def _create_post(board, definition, created_at, manifest):
    subject, content, is_notice, image_number = definition
    post = Post.objects.create(
        board=board,
        wr_num=get_next_num(board_id=board.pk),
        wr_parent=0,
        wr_subject=subject,
        wr_content=content,
        wr_slug="",
        wr_name="샘플 운영자",
        wr_datetime=created_at,
        wr_last=created_at,
        is_notice=1 if is_notice else 0,
    )
    post.wr_parent = post.pk
    post.save(update_fields=["wr_parent"])
    manifest["posts"].append(post.pk)

    if image_number:
        filename = SAMPLE_IMAGES[image_number - 1]
        image_url = f"/sample-data/{filename}"
        post_file = Post_file.objects.create(
            board=board,
            post=post,
            bf_no=0,
            bf_source=filename,
            bf_fileurl=image_url,
            bf_thumburl=image_url,
            bf_storage="sample_static",
            bf_filesize=_asset_size(filename),
            bf_width=600,
            bf_height=600,
            bf_type=18,
            bf_datetime=created_at,
        )
        post.wr_file = 1
        post.save(update_fields=["wr_file"])
        manifest["post_files"].append(post_file.pk)
    return post


def _create_comment(post, content, created_at, manifest):
    comment = Comment.objects.create(
        board=post.board,
        post=post,
        wr_content=content,
        wr_name="커뮤니티 회원",
        wr_datetime=created_at,
        wr_last=created_at,
    )
    manifest["comments"].append(comment.pk)
    Post.objects.filter(pk=post.pk).update(
        wr_comment=Comment.objects.filter(post=post).count(),
        wr_last=created_at,
    )


def _ensure_shop_samples(manifest):
    """Restore only tracked shop content; retain edited prices, stock, text and images."""
    now, token = timezone.now(), uuid.uuid4().hex
    result = {"created": 0, "updated": 0}
    category = ShopCategory.objects.select_for_update().filter(
        pk__in=_ids(manifest, "categories"), ca_parent="",
    ).order_by("ca_id").first()
    if category is None:
        category = ShopCategory.objects.create(ca_id=_free_root_category_id(), ca_name="데모 스토어", ca_order=1, ca_use=True)
        if category.pk not in manifest["categories"]:
            manifest["categories"].append(category.pk)
    elif not category.ca_use:
        category.ca_use = True
        category.save(update_fields=["ca_use"])

    tracked = _ids(manifest, "products")
    products = {product.pk: product for product in ShopProduct.objects.select_for_update().filter(pk__in=tracked)}
    raw_slots = manifest.get("shop_product_slots")
    slots = raw_slots if isinstance(raw_slots, dict) else {str(number): pk for number, pk in enumerate(tracked[:len(PRODUCTS)], 1)}
    slots = {str(number): pk for number, pk in slots.items() if pk in tracked}
    manifest["products"] = [pk for pk in tracked if pk in products]
    for number, (name, price, description) in enumerate(PRODUCTS, start=1):
        product = products.get(slots.get(str(number)))
        if product is None:
            image_url = f"/sample-data/{SAMPLE_IMAGES[number - 1]}"
            product = ShopProduct.objects.create(
                it_id=f"SAMPLE{token[:8]}{number:02d}", category=category,
                it_name=name, it_seo_title=f"demo-product-{number:02d}-{token[:5]}", it_brand="SOLUNE",
                it_price=price, it_basic_price=price, **_sample_product_fields(number, price),
                it_hit=12 + number * 7, it_update_time=now - timedelta(hours=number), it_order=number,
                it_stock_qty=20, it_use="1", it_basic=description, it_content=description,
                image_url=image_url, images=[image_url],
            )
            manifest["products"].append(product.pk)
            slots[str(number)] = product.pk
            result["created"] += 1
        else:
            # Applying visibility is explicit. Do not reset inventory or overwrite real content.
            fields = {**_sample_product_fields(number, product.it_price), "it_use": "1", "category_id": category.pk}
            changed = [field for field, value in fields.items() if getattr(product, field) != value]
            if changed:
                for field in changed:
                    setattr(product, field, fields[field])
                product.save(update_fields=changed)
                result["updated"] += 1
    manifest["shop_product_slots"] = slots
    if not ShopBanner.objects.filter(pk__in=_ids(manifest, "banners")).exists():
        banner = ShopBanner.objects.create(
            bn_alt="차분한 일상을 위한 데모 스토어", bn_url=f"/shop/list-{category.pk}",
            bn_position="메인", bn_device="both", bn_order=1,
            image_url=f"/sample-data/{SAMPLE_BANNER}", is_active=True,
        )
        manifest["banners"] = [banner.pk]
    return result


@batch_bootstrap_changes()
def ensure_shop_sample_data():
    """Idempotently add missing shop samples and apply their home visibility."""
    sample_asset_summary()
    with transaction.atomic():
        row, _ = Config.objects.get_or_create(
            name=MANIFEST_NAME, defaults={"value": json.dumps(empty_manifest(), ensure_ascii=False)},
        )
        row = Config.objects.select_for_update().get(pk=row.pk)
        manifest = _decode_manifest(row)
        result = _ensure_shop_samples(manifest)
        value = json.dumps(manifest, ensure_ascii=False)
        if row.value != value:
            row.value = value
            row.save(update_fields=["value"])
        return {**result, "products": len(manifest["products"])}


def _has_community_samples(manifest):
    return any(_ids(manifest, field) for field in COMMUNITY_MANIFEST_FIELDS)


def _create_community_records(manifest):
    """Create the board, post, comment, FAQ and poll batch in an existing manifest."""
    token = uuid.uuid4().hex
    boards = {}
    posts_by_table = {}
    now = timezone.now()

    for table, board_definition in BOARD_CONTENT.items():
        board = _new_board(table, board_definition["subject"], token, manifest)
        boards[table] = board
        if board.pk not in manifest["boards_used"]:
            manifest["boards_used"].append(board.pk)
        posts_by_table[table] = []
        for index, definition in enumerate(board_definition["posts"]):
            created_at = now - timedelta(days=(index % 5) + 1, hours=index)
            post = _create_post(board, definition, created_at, manifest)
            posts_by_table[table].append(post)

    _create_comment(posts_by_table["free"][0], "반갑습니다. 게시판이 보기 좋게 정리되어 있네요.", now - timedelta(hours=2), manifest)
    _create_comment(posts_by_table["free"][1], "저도 책상 정리부터 해봐야겠습니다.", now - timedelta(hours=1), manifest)
    _create_comment(posts_by_table["gallery"][0], "공간 사진 잘 봤습니다. 차분한 분위기가 좋네요.", now - timedelta(minutes=30), manifest)

    for board in boards.values():
        board.bo_count_write = board.posts.count()
        board.bo_count_comment = board.comments.count()
        board.save(update_fields=["bo_count_write", "bo_count_comment"])

    faq_master = FAQMaster.objects.create(fm_subject="자주 묻는 질문", fm_order=1, fm_use=1)
    manifest["faq_masters"].append(faq_master.pk)
    for index, (subject, content) in enumerate(FAQS, start=1):
        item = FAQItem.objects.create(
            master=faq_master,
            fa_subject=subject,
            fa_content=content,
            fa_order=index,
            fa_use=1,
        )
        manifest["faq_items"].append(item.pk)

    poll = Poll.objects.create(
        po_subject="어떤 콘텐츠를 가장 기대하시나요?",
        po_etc="샘플 설문입니다.",
        po_use=1,
        po_date=timezone.localdate(),
        po_begin_date=timezone.localdate() - timedelta(days=1),
        po_end_date=timezone.localdate() + timedelta(days=30),
    )
    manifest["polls"].append(poll.pk)
    for index, choice in enumerate(POLL_CHOICES, start=1):
        poll_choice = PollChoice.objects.create(poll=poll, num=index, content=choice)
        manifest["poll_choices"].append(poll_choice.pk)

    manifest["board_map"] = [{"table": table, "pk": board.pk} for table, board in boards.items()]
    return boards


def _sample_boards_from_manifest(manifest):
    boards = {}
    for item in manifest.get("board_map", []):
        if isinstance(item, dict) and item.get("table") and item.get("pk"):
            board = Board.objects.filter(pk=item["pk"]).first()
            if board:
                boards[item["table"]] = board

    used_ids = _ids(manifest, "boards_used")
    for table, definition in BOARD_CONTENT.items():
        if table in boards:
            continue
        candidates = Board.objects.filter(pk__in=used_ids)
        board = candidates.filter(bo_table=table).first()
        board = board or next((candidate for candidate in candidates if candidate.bo_subject == definition["subject"]), None)
        if board:
            boards[table] = board
    return boards


def _content_page_snapshot(page):
    return {
        "id": page.pk,
        "co_subject": page.co_subject,
        "co_content": page.co_content,
        "co_html": page.co_html,
        "co_use": page.co_use,
    }


def _menu_snapshot(menu):
    return {
        "id": menu.pk,
        "me_code": menu.me_code,
        "me_name": menu.me_name,
        "me_link": menu.me_link,
        "me_type": menu.me_type,
        "me_type_pk": menu.me_type_pk,
        "me_target": menu.me_target,
        "me_order": menu.me_order,
        "me_use": menu.me_use,
        "me_mobile_use": menu.me_mobile_use,
    }


def _ensure_sample_content_pages(manifest):
    for order, (co_id, (subject, content)) in enumerate(SAMPLE_CONTENT_PAGES.items(), start=1):
        if ContentPage.objects.filter(pk=co_id).exists():
            continue
        page = ContentPage.objects.create(
            co_id=co_id,
            co_subject=subject,
            co_content=content,
            co_mobile_content=content,
            co_html=1,
            co_order=order,
            co_use=1,
        )
        manifest["content_pages"].append(page.pk)
        manifest["content_page_snapshots"].append(_content_page_snapshot(page))


def _sample_menu_definitions(boards):
    def board_link(table):
        board = boards.get(table)
        return get_pretty_url("Board", board_pk=board.pk) if board else "/"

    return [
        ("10", "커뮤니티", board_link("free"), "Board", boards.get("free"), 1),
        ("1001", "자유게시판", board_link("free"), "Board", boards.get("free"), 1),
        ("1002", "질문답변", board_link("qa"), "Board", boards.get("qa"), 2),
        ("1003", "갤러리", board_link("gallery"), "Board", boards.get("gallery"), 3),
        ("1004", "새글", "/recent", "", None, 4),
        ("20", "쇼핑몰", "/shop", "", None, 2),
        ("2001", "전체 상품", "/shop", "", None, 1),
        ("2002", "쿠폰존", "/shop/couponzone", "", None, 2),
        ("30", "고객센터", "/faq", "", None, 3),
        ("3001", "자주 묻는 질문", "/faq", "", None, 1),
        ("3002", "1:1 문의", "/mypage/qas", "", None, 2),
        ("40", "회원공간", "/mypage", "", None, 4),
        ("4001", "로그인", "/login", "", None, 1),
        ("4002", "회원가입", "/register", "", None, 2),
        ("4003", "마이페이지", "/mypage", "", None, 3),
        ("50", "사이트 안내", "/content/company", "", None, 5),
        ("5001", "사이트 소개", "/content/company", "", None, 1),
        ("5002", "개인정보처리방침", "/content/privacy", "", None, 2),
        ("5003", "이용약관", "/content/provision", "", None, 3),
    ]


def _ensure_sample_menus(manifest, boards):
    # Existing administrator-authored navigation always wins over demo defaults.
    if Site_menu.objects.exists():
        return
    for code, name, link, menu_type, board, order in _sample_menu_definitions(boards):
        menu = Site_menu.objects.create(
            me_code=code,
            me_name=name,
            me_link=link,
            me_type=menu_type,
            me_type_pk=board.pk if menu_type == "Board" and board else 0,
            me_target="",
            me_order=order,
            me_use=1,
            me_mobile_use=1,
        )
        manifest["menus"].append(menu.pk)
        manifest["menu_snapshots"].append(_menu_snapshot(menu))


def _ensure_home_board_settings(manifest, boards):
    configured_boards = [table for table in ("notice", "free", "qa") if table in boards]
    desired = {
        "cf_home_boards": ",".join(configured_boards),
        "cf_home_gallery": "gallery" if "gallery" in boards else "",
    }
    site_config.clear()
    for name, value in desired.items():
        row = Config.objects.filter(name=name).first()
        previous = row.value if row else None
        if previous == value or previous not in (None, ""):
            continue
        if row:
            row.value = value
            row.save(update_fields=["value"])
        else:
            Config.objects.create(name=name, value=value)
        manifest["home_settings"].append({"name": name, "previous": previous, "sample": value})
    site_config.clear()


def _ensure_demo_site_experience(manifest, boards):
    _ensure_sample_content_pages(manifest)
    _ensure_sample_menus(manifest, boards)
    _ensure_home_board_settings(manifest, boards)


@suppress_notification_events()
def _apply_sample_data(require_new):
    sample_asset_summary()
    with transaction.atomic():
        row, _ = Config.objects.get_or_create(
            name=MANIFEST_NAME,
            defaults={"value": json.dumps(empty_manifest(), ensure_ascii=False)},
        )
        row = Config.objects.select_for_update().get(pk=row.pk)
        manifest = _decode_manifest(row)
        if manifest is None:
            manifest = empty_manifest()

        already_seeded = _has_community_samples(manifest)
        if require_new and already_seeded:
            raise SampleDataError("커뮤니티 샘플 데이터가 이미 있습니다. 먼저 현재 샘플을 삭제해 주세요.")

        if already_seeded:
            boards = _sample_boards_from_manifest(manifest)
        else:
            boards = _create_community_records(manifest)

        shop_result = _ensure_shop_samples(manifest)
        _ensure_demo_site_experience(manifest, boards)
        row.value = json.dumps(manifest, ensure_ascii=False)
        row.save(update_fields=["value"])
        return manifest, not already_seeded, shop_result


@batch_bootstrap_changes()
def create_sample_data():
    """Create the community demo batch while preserving an already-seeded shop."""
    manifest, _, _ = _apply_sample_data(require_new=True)
    return manifest


@batch_bootstrap_changes()
def ensure_demo_sample_data():
    """Idempotently prepare demo community content, navigation, pages and shop samples."""
    manifest, created_community, shop_result = _apply_sample_data(require_new=False)
    return {
        "created_community": created_community,
        "counts": managed_counts(manifest),
        "shop": shop_result,
        "manifest": manifest,
    }


@batch_bootstrap_changes()
def repair_sample_product_types():
    """Apply the demo store's home sections to only products tracked by its manifest."""
    with transaction.atomic():
        config_row = Config.objects.select_for_update().filter(name=MANIFEST_NAME).first()
        manifest = _decode_manifest(config_row)
        product_ids = _ids(manifest, "products")
        if not product_ids:
            return 0

        products_by_id = {
            product.pk: product for product in ShopProduct.objects.filter(pk__in=product_ids)
        }
        updated_products = []
        for number, product_id in enumerate(product_ids, start=1):
            product = products_by_id.get(product_id)
            if product is None:
                continue
            for field, value in _sample_product_fields(number, product.it_price).items():
                setattr(product, field, value)
            updated_products.append(product)

        if updated_products:
            ShopProduct.objects.bulk_update(
                updated_products,
                ("it_cust_price", "it_type1", "it_type2", "it_type3", "it_type4", "it_type5"),
            )
            from gnu_jango.api.page_bootstrap import invalidate_page_bootstrap

            invalidate_page_bootstrap()
        return len(updated_products)


def _has_related_rows(instance):
    """Keep a managed row if other records now depend on it."""
    for relation in instance._meta.related_objects:
        # Search documents are derived data and cascade with their source. They
        # must not make a disposable sample look like it gained real user data.
        if relation.related_model._meta.label_lower == "site_search.searchdocument":
            continue
        accessor = relation.get_accessor_name()
        if not accessor:
            continue
        try:
            related = getattr(instance, accessor)
        except ObjectDoesNotExist:
            continue
        if hasattr(related, "exists"):
            if related.exists():
                return True
        elif related is not None:
            return True
    return False


def _matches_snapshot(instance, snapshot, fields):
    return bool(snapshot) and all(getattr(instance, field) == snapshot.get(field) for field in fields)


def _modified_sample_experience(manifest):
    menu_snapshots = {int(item["id"]): item for item in manifest.get("menu_snapshots", []) if isinstance(item, dict) and item.get("id")}
    menu_fields = (
        "me_code", "me_name", "me_link", "me_type", "me_type_pk", "me_target", "me_order", "me_use", "me_mobile_use",
    )
    for menu in Site_menu.objects.filter(pk__in=_ids(manifest, "menus")):
        if not _matches_snapshot(menu, menu_snapshots.get(menu.pk), menu_fields):
            return True

    page_snapshots = {str(item["id"]): item for item in manifest.get("content_page_snapshots", []) if isinstance(item, dict) and item.get("id")}
    page_fields = ("co_subject", "co_content", "co_html", "co_use")
    for page in ContentPage.objects.filter(pk__in=_ids(manifest, "content_pages")):
        if not _matches_snapshot(page, page_snapshots.get(str(page.pk)), page_fields):
            return True
    return False


@batch_bootstrap_changes()
def remove_sample_data():
    """Remove tracked sample rows while preserving any that gained real activity."""
    with transaction.atomic():
        config_row = Config.objects.select_for_update().filter(name=MANIFEST_NAME).first()
        manifest = _decode_manifest(config_row)
        if not manifest:
            return {"deleted": 0, "retained": 0, "manifest": None}

        before_counts = managed_counts(manifest)
        tracked_comments = _ids(manifest, "comments")
        tracked_files = _ids(manifest, "post_files")
        tracked_posts = _ids(manifest, "posts")
        tracked_products = _ids(manifest, "products")
        tracked_categories = _ids(manifest, "categories")
        tracked_masters = _ids(manifest, "faq_masters")
        tracked_polls = _ids(manifest, "polls")
        tracked_menus = _ids(manifest, "menus")
        tracked_pages = _ids(manifest, "content_pages")
        menu_snapshots = {int(item["id"]): item for item in manifest.get("menu_snapshots", []) if isinstance(item, dict) and item.get("id")}
        page_snapshots = {str(item["id"]): item for item in manifest.get("content_page_snapshots", []) if isinstance(item, dict) and item.get("id")}
        preserve_demo_navigation = _modified_sample_experience(manifest)

        Comment.objects.filter(pk__in=tracked_comments).delete()
        Post_file.objects.filter(pk__in=tracked_files).delete()

        retained_posts = []
        for post in Post.objects.select_for_update().filter(pk__in=tracked_posts).order_by("pk"):
            if _has_related_rows(post):
                latest_comment = post.comments.order_by("-wr_datetime", "-pk").first()
                post.wr_comment = post.comments.count()
                post.wr_last = latest_comment.wr_datetime if latest_comment else post.wr_datetime
                post.save(update_fields=["wr_comment", "wr_last"])
                retained_posts.append(post.pk)
            else:
                post.delete()

        retained_products = []
        for product in ShopProduct.objects.select_for_update().filter(pk__in=tracked_products).order_by("pk"):
            if _has_related_rows(product):
                retained_products.append(product.pk)
            else:
                product.delete()

        preserve_demo_navigation = preserve_demo_navigation or bool(retained_posts or retained_products)

        retained_menus = []
        if preserve_demo_navigation:
            retained_menus = list(Site_menu.objects.filter(pk__in=tracked_menus).values_list("pk", flat=True))
        else:
            menu_fields = (
                "me_code", "me_name", "me_link", "me_type", "me_type_pk", "me_target", "me_order", "me_use", "me_mobile_use",
            )
            for menu in Site_menu.objects.select_for_update().filter(pk__in=tracked_menus).order_by("pk"):
                if _matches_snapshot(menu, menu_snapshots.get(menu.pk), menu_fields):
                    menu.delete()
                else:
                    retained_menus.append(menu.pk)

        retained_pages = []
        if preserve_demo_navigation:
            retained_pages = list(ContentPage.objects.filter(pk__in=tracked_pages).values_list("pk", flat=True))
        else:
            page_fields = ("co_subject", "co_content", "co_html", "co_use")
            for page in ContentPage.objects.select_for_update().filter(pk__in=tracked_pages).order_by("pk"):
                if _matches_snapshot(page, page_snapshots.get(str(page.pk)), page_fields):
                    page.delete()
                else:
                    retained_pages.append(page.pk)

        if preserve_demo_navigation:
            retained_menus = list(Site_menu.objects.filter(pk__in=tracked_menus).values_list("pk", flat=True))
            retained_pages = list(ContentPage.objects.filter(pk__in=tracked_pages).values_list("pk", flat=True))
        else:
            for item in manifest.get("home_settings", []):
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                setting = Config.objects.filter(name=item["name"]).first()
                if not setting or setting.value != item.get("sample"):
                    continue
                if item.get("previous") is None:
                    setting.delete()
                else:
                    setting.value = item["previous"]
                    setting.save(update_fields=["value"])
            site_config.clear()

        ShopBanner.objects.filter(pk__in=_ids(manifest, "banners")).delete()
        FAQItem.objects.filter(pk__in=_ids(manifest, "faq_items")).delete()

        retained_masters = []
        for master in FAQMaster.objects.select_for_update().filter(pk__in=tracked_masters).order_by("pk"):
            if _has_related_rows(master):
                retained_masters.append(master.pk)
            else:
                master.delete()

        retained_polls = []
        retained_choices = []
        choice_ids = _ids(manifest, "poll_choices")
        for poll in Poll.objects.select_for_update().filter(pk__in=tracked_polls).order_by("pk"):
            if poll.votes.exists() or poll.comments.exists():
                retained_polls.append(poll.pk)
                retained_choices.extend(poll.choices.filter(pk__in=choice_ids).values_list("pk", flat=True))
                continue
            PollChoice.objects.filter(pk__in=choice_ids, poll=poll).delete()
            if _has_related_rows(poll):
                retained_polls.append(poll.pk)
            else:
                poll.delete()

        retained_categories = []
        for category in ShopCategory.objects.select_for_update().filter(pk__in=tracked_categories).order_by("pk"):
            if _has_related_rows(category):
                retained_categories.append(category.pk)
            else:
                category.delete()

        retained_boards = []
        tracked_board_ids = _ids(manifest, "boards")
        for board in Board.objects.select_for_update().filter(pk__in=_ids(manifest, "boards")).order_by("pk"):
            if preserve_demo_navigation or _has_related_rows(board):
                retained_boards.append(board.pk)
            else:
                board.delete()

        retained_groups = []
        for group in Group.objects.select_for_update().filter(pk__in=_ids(manifest, "groups")).order_by("pk"):
            if _has_related_rows(group):
                retained_groups.append(group.pk)
            else:
                group.delete()

        retained_used_boards = (
            list(Board.objects.filter(pk__in=tracked_board_ids).values_list("pk", flat=True))
            if preserve_demo_navigation
            else list(
                Post.objects.filter(pk__in=retained_posts)
                .order_by()
                .values_list("board_id", flat=True)
                .distinct()
            )
        )
        for board in Board.objects.select_for_update().filter(pk__in=_ids(manifest, "boards_used")):
            board.bo_count_write = board.posts.count()
            board.bo_count_comment = board.comments.count()
            board.save(update_fields=["bo_count_write", "bo_count_comment"])

        next_manifest = {
            **manifest,
            "groups": retained_groups,
            "boards": retained_boards,
            "boards_used": retained_used_boards,
            "posts": retained_posts,
            "comments": [],
            "post_files": [],
            "categories": retained_categories,
            "products": retained_products,
            "banners": [],
            "faq_masters": retained_masters,
            "faq_items": [],
            "polls": retained_polls,
            "poll_choices": retained_choices,
            "menus": retained_menus,
            "menu_snapshots": [item for item in manifest.get("menu_snapshots", []) if isinstance(item, dict) and item.get("id") in retained_menus],
            "content_pages": retained_pages,
            "content_page_snapshots": [item for item in manifest.get("content_page_snapshots", []) if isinstance(item, dict) and item.get("id") in retained_pages],
            "home_settings": manifest.get("home_settings", []) if preserve_demo_navigation else [],
            "board_map": manifest.get("board_map", []) if preserve_demo_navigation else [],
        }
        if any(next_manifest[field] for field in MANIFEST_LIST_FIELDS if field != "boards_used"):
            config_row.value = json.dumps(next_manifest, ensure_ascii=False)
            config_row.save(update_fields=["value"])
            remaining_manifest = next_manifest
        else:
            config_row.delete()
            remaining_manifest = None

        after_counts = managed_counts(remaining_manifest)
        return {
            "deleted": sum(before_counts.values()) - sum(after_counts.values()),
            "retained": sum(after_counts.values()),
            "manifest": remaining_manifest,
        }
