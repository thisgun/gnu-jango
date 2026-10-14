import { ShopFooter } from "@/components/layout/Footer";

/**
 * 쇼핑몰 본문 뼈대 — 레퍼런스(Solune 테마 shop-shell)의 .solune-shop-page > #wrapper > #container > main, 그 뒤 푸터
 * 순서를 따른다. 쇼핑몰 CSS(solune-shop.*.css)가 .solune-shop-page 아래로, 안쪽 페이지는 ".solune-shop-page main …" 으로
 * 걸려 있어 이 이름들과 main 이 있어야 적용된다. 헤더는 루트 레이아웃이 그리고, 루트는 쇼핑몰 경로에서 main 과
 * 커뮤니티 푸터를 그리지 않는다(CommunityInnerShell · Footer). #wrapper 는 루트가 이미 써서 클래스로만 둔다.
 */
export default function ShopLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="solune-shop-page">
      <div className="solune-shop-wrapper">
        <div id="container" className="solune-shop-container">
          <main id="main-content" className="shop-content">{children}</main>
        </div>
      </div>
      <ShopFooter />
    </div>
  );
}
