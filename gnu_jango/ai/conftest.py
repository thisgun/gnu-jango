"""Fixtures for the AI tests: a fake provider and a small handbook + shop catalogue."""
from types import SimpleNamespace

import pytest

from gnu_jango.ai.client import provider_override
from gnu_jango.ai.store import clear_cache
from gnu_jango.ai.testing import FakeEmbeddingProvider
from gnu_jango.config import config as site_config
from gnu_jango.config.models import Config
from gnu_jango.docs_search.service import clear_memory_cache
from gnu_jango.testing.factories import BoardFactory, GroupFactory, PostFactory, ShopCategoryFactory, ShopProductFactory

# The fake provider maps these words to one concept, as a real model maps synonyms.
SYNONYMS = {"랩탑": "노트북", "laptop": "노트북", "환불": "반품", "돈돌려받기": "반품"}

SEMANTIC_ON = {"G5_AI_SEMANTIC_SEARCH": True, "G5_AI_SEMANTIC_MIN_SIMILARITY": 0.1}


@pytest.fixture
def fake_provider():
    provider = FakeEmbeddingProvider(synonyms=SYNONYMS)
    clear_cache()
    with provider_override(provider):
        yield provider
    clear_cache()


@pytest.fixture
def handbook(db):
    group = GroupFactory(gr_id="manual")
    board = BoardFactory(group=group, bo_table="hb_guide", bo_subject="운영 가이드", bo_use_search=True)
    Config.objects.update_or_create(name="cf_docs_group", defaults={"value": group.gr_id})
    site_config.clear()
    clear_memory_cache()
    chapters = SimpleNamespace(
        board=board,
        refund=PostFactory(board=board, wr_subject="주문 취소", wr_content="<p>반품 신청은 주문 상세에서 접수합니다.</p>"),
        shipping=PostFactory(board=board, wr_subject="배송 안내", wr_content="<p>택배 배송 조회 방법</p>"),
        secret=PostFactory(board=board, wr_subject="내부 메모", wr_content="<p>반품 비밀 절차</p>", wr_option="secret"),
    )
    yield chapters
    site_config.clear()
    clear_memory_cache()


@pytest.fixture
def catalogue(db):
    category = ShopCategoryFactory(ca_id="10", ca_name="컴퓨터")
    return SimpleNamespace(
        category=category,
        laptop=ShopProductFactory(it_id="NB-1", it_name="가벼운 노트북", category=category, it_basic="휴대용"),
        mouse=ShopProductFactory(it_id="MS-1", it_name="무선 마우스", category=category, it_basic="블루투스"),
        hidden=ShopProductFactory(it_id="NB-HIDDEN", it_name="단종 노트북", category=category, it_use="0"),
    )
