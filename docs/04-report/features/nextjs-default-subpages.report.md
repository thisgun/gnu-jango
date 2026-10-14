# Next.js 기본 테마 전체 서브페이지 개선 보고서

- 날짜: 2026-10-14
- 기준: 레퍼런스 `http://127.0.0.9/`(커뮤니티) · `/shop`(쇼핑몰), 소스 `C:\xampp824\www\gnuboard5_3\nextjs\{src,themes\default}` (읽기 전용)
- 확인 주소: Next dev `http://127.0.0.1:3000`, Django 통합 테마 `http://127.0.0.1:8081` (Build 13)

## 바뀐 화면

| 영역 | 내용 |
|---|---|
| 쇼핑 공통 | 레퍼런스 CSS 12개(`solune-shop.*.css`)를 그대로 옮기고, 앱 전용 보정은 `solune-shop.app*.css` 로 분리. 쇼핑 레이아웃(`main.shop-content`), 쇼핑 푸터, 머리글 고정(`.g5-default-header { display: contents }`), 장바구니 가방·계정 아이콘 |
| 쇼핑 홈 | 섹션 머리, 상품 줄(스크롤 스냅 + 진행 막대 + 스켈레톤), 리뷰 줄, 고객센터 사이드 |
| 상품 목록·전체 상품 | `ShopListHeader`(분류 펼침, 정렬, 보기 전환) + `SoluneProductCard` 격자 |
| 상품 상세 | 레퍼런스 구성으로 분해(`ProductDetailView`, `ProductPurchaseControls`, `ProductReviewList` 등) |
| 장바구니·주문·주문상세·개인결제 | 레퍼런스 표/카드/쿠폰 대화상자 구성 |
| 쿠폰존·사용후기·상품문의·위시리스트·비교·이벤트 | 레퍼런스 목록·검색 막대 |
| 커뮤니티 | 게시판 목록(갤러리 포함), 검색, 최근 글, FAQ, 설문, 회원 정보, 로그인·회원가입, 404, 커뮤니티 푸터 |
| 마이페이지 | 레이아웃·패널·하위 화면 전체 |

## Django API 수정 (테스트 포함)

- 통합 검색이 본문 전체를 돌려주던 문제 → 220자 미리보기만, 열람 포인트 게시판은 본인·결제 글만 본문 일치 판정 (`core/test_search_preview.py`)
- 목록 미리보기에서 비밀글 제외 (`core/test_board_list_extras.py`)
- 상품문의 목록·상세·내 문의에 1:1 문의(`__general_qa__`)가 섞이던 기존 버그 수정
- 비밀 상품문의의 작성자 이름 가림("비공개"), 사용후기·상품문의 `sfl` 검색 필드 (`core/test_shop_board_search.py`)
- 게시판 분류별 글 수 API (`BOARD_CATEGORY_COUNTS`, 기본 꺼짐)

## 검증

| 항목 | 결과 |
|---|---|
| `npm run typecheck` · `npm run lint` | 통과 |
| `check:runtime-config` · `check:static-export-guards` | 통과 |
| `manage.py test` (전체) | 2019개 OK (skip 6) |
| `npm run build:theme` → `check:theme-sync` | Build 13, 454개 파일 일치 |
| 8081 캡처 25경로 × 390/768/1440 | 가로 넘침 없음. 콘솔 오류는 예상된 것만(외부 리뷰 이미지 NotSameOrigin, 비로그인 개인결제 401, 404 화면 리소스) |
| 쓰기 검증 | DB 사본(`.tmp-nextjs-runtime/progress-20261013.sqlite3`, 8095)에서만 수행. QA 계정도 사본에만 만듦 |

캡처: `.tmp-nextjs-runtime/full-subpages-parity/` (`django8081/`, `django8081/top/pair-*.png` 레퍼런스 대조)

## 남은 차이 (데이터·설정)

- 레퍼런스 DB와 상품 재고·글 수·사이트 이름이 달라 SOLD OUT 배지, 건수, 푸터 이름이 다르게 보임
- 레퍼런스는 소셜 로그인이 켜져 있어 로그인 카드에 소셜 버튼이 있음
- 레퍼런스 품절 판정은 "재고 − 미출고 주문 수량"을 쓴다. 우리 Django는 주문 시 재고를 바로 차감하므로 같지만, 이관된 옛 미출고 주문(`stock_adjusted=False`)은 차감되지 않는다
- lucide-react 버전 차이(1.23 → 1.54)로 일부 아이콘 획이 미세하게 다름
- 별도 지시 전까지 푸시·운영 배포 안 함
