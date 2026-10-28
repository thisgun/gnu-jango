# API 계약 자동화 (OpenAPI 스키마 · TypeScript 타입 · ETag)

v1 API의 응답 모양을 OpenAPI 스키마로 고정하고, 그 스키마에서 Next.js 타입을 만들어 백엔드와 프런트가 어긋나면 CI에서 바로 실패하게 합니다.

## 구성

| 단계 | 위치 | 하는 일 |
|---|---|---|
| 응답 선언 | `gnu_jango/api/contracts/` | v1 뷰가 돌려주는 dict의 모양을 DRF serializer로 *설명*합니다(렌더링에는 쓰지 않음). 뷰에는 `@extend_schema(responses=envelope("이름", Serializer()))`를 `@api_view` 위에 붙입니다. |
| 계약 테스트 | `gnu_jango/core/contract_testing.py`, `test_api_contract*.py` | 실제로 API를 호출해 JSON을 생성된 스키마로 검증합니다. 선언하지 않은 키가 있거나, 빠졌거나, 타입이 다르면(정수/불리언/문자열, null) 실패합니다. |
| 범위 검사 | `test_api_contract.py`의 `ContractCoverageTests` | 응답 모양이 선언된 v1 API는 반드시 어느 `test_api_contract*.py`의 `CONTRACT_OPERATIONS`에 들어 있어야 합니다. |
| 스키마 파일 | `openapi/schema.json` | drf-spectacular가 만든 스키마. CI(django 작업)가 다시 만들어 diff합니다. |
| TS 타입 | `nextjs/src/types/api.gen.ts` | `npm run api:types`가 스키마에서 생성. CI(nextjs 작업)가 `npm run check:api-types`로 최신인지 확인합니다. |
| 프런트 검사 | `nextjs/src/lib/api-contract.ts`, `src/types/api-contract-checks.ts` | `ApiData<"/api/v1/...">`로 응답 데이터 타입을 꺼내고, 손으로 쓴 타입(`Board`, `Post`, `ShopProduct`, `ShopCategory`, 설정 zod 스키마)이 실제 응답과 맞는지 `npm run typecheck`에서 검사합니다. |

## 응답 모양이 선언된 API

| API | 응답 컴포넌트 |
|---|---|
| `GET /api/v1/settings` | `SiteSettingsEnvelope` |
| `GET /api/v1/boards` | `BoardListEnvelope` |
| `GET /api/v1/boards/{bo_table}` | `BoardEnvelope` |
| `GET /api/v1/boards/{bo_table}/posts` | `BoardPostListEnvelope` (meta: `BoardPostsPageMeta`) |
| `GET /api/v1/posts/{bo_table}/{wr_id}` | `PostDetailEnvelope` |
| `GET /api/v1/shop/categories` | `ShopCategoriesEnvelope` |
| `GET /api/v1/shop/categories/{ca_id}` | `ShopCategoryDetailEnvelope` (meta: `PageMeta`) |
| `GET /api/v1/shop/products` | `ShopProductsEnvelope` (meta: `PageMeta`) |
| `GET /api/v1/shop/products/{it_id}` | `ShopProductDetailEnvelope` |
| `GET /api/v1/auth/me` | `AuthMeEnvelope` |

나머지 API는 아직 응답 모양이 없어 생성 타입에서 `never`가 됩니다. 하나씩 늘려 갑니다.

## API를 바꾸거나 새로 선언할 때

1. `gnu_jango/api/contracts/`의 serializer를 실제 dict에 맞게 고치고(새 API면 `@extend_schema` 추가), `test_api_contract*.py`에 계약 테스트와 `CONTRACT_OPERATIONS` 항목을 추가합니다.
2. 스키마와 타입을 다시 만듭니다.

   ```bash
   python manage.py spectacular --format openapi-json --file openapi/schema.json
   cd nextjs && npm run api:types
   ```

3. `npm run typecheck`가 실패하면 프런트 타입(또는 API)을 고칩니다. 세 파일(`openapi/schema.json`, `nextjs/src/types/api.gen.ts`, 바뀐 코드)을 함께 커밋합니다.

## ETag (`gnu_jango/api/caching.py`)

쿠키가 있는 브라우저 요청의 API 응답은 공용 PC 디스크 캐시에 회원 데이터가 남지 않도록 `Cache-Control: no-store, private`입니다. 그래서 누가 요청해도 같은 공개 데이터도 매번 다시 내려받았습니다.

`@shared_response_etag`를 붙인 뷰는 200 응답에 내용 기반 `ETag`와 `Cache-Control: private, no-cache`를 붙입니다. 브라우저는 사본을 두되 매번 서버에 확인하고, 바뀌지 않았으면 빈 `304 Not Modified`를 받습니다.

적용한 API: `settings`, `boards`(목록), `shop/categories`, `shop/categories/{ca_id}`, `shop/products`(목록).

**요청한 사람에 따라 결과가 달라지는 API에는 붙이지 않습니다**: 메뉴(회원 등급별), 장바구니, 글 상세·글 목록(`can_manage`, `is_scrapped` 등), 로그인 사용자 정보. 브라우저에 남은 사본이 같은 브라우저의 다음 사용자에게 보일 수 있기 때문입니다.

ETag는 응답 본문의 해시라 서버의 조회 비용은 그대로이고, 전송량과 브라우저의 JSON 처리만 줄어듭니다.

## 다음 단계

- 무한 스크롤 목록(`InfinitePostList`)용 커서 페이지네이션(선택 옵션). 그누보드식 번호 페이지 화면은 그대로 둡니다.
- 응답 모양 선언을 더 많은 API로 확대(글 SEO 주소, 장바구니, 주문 등).
