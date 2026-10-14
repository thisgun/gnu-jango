import { buildPageMetadata } from "@/lib/seo";
import { getShopBanners, getShopCategories, getShopPopups } from "@/services/shop";
import { DeferredShopSections } from "./DeferredShopSections";
import { ShopHomeBanners } from "./ShopHomeMarketing";
import { ShopHomePopups } from "./ShopHomePopups";
import { ShopHomeCategories } from "./ShopHomeCategories";
import { ShopHomePopular } from "./ShopHomePopular";
import { ShopHomeHit } from "./ShopHomeHit";
import { ShopHomeReviews } from "./ShopHomeReviews";
import { ShopHomeSupport } from "./ShopHomeSupport";

export const metadata = buildPageMetadata({
  title: "쇼핑몰",
  description: "히트상품, 최신상품, 추천상품과 인기상품을 한 화면에서 확인하세요.",
  path: "/shop",
});

export default async function ShopHomePage() {
  // 정적 내보내기는 한 번 만들어 모든 Django(로컬 · Vercel)가 같이 쓴다. 만드는 쪽 DB 의 배너 ·
  // 팝업 · 분류를 HTML 에 구우면 다른 서버에서 남의 그림 주소(http://127.0.0.1:8081/…)를 불러
  // 혼합 콘텐츠 오류가 났다. 서버 모드에서만 미리 읽고, 정적 화면은 브라우저가 불러온다(홈과 같은 규칙).
  const bakeData = process.env.G5_NEXT_RUNTIME === "server";
  const [banners, popups, categories] = await Promise.all([
    bakeData ? getShopBanners({ position: "메인", device: "all" }) : Promise.resolve([]),
    bakeData ? getShopPopups({ device: "all", limit: 5 }) : Promise.resolve([]),
    bakeData ? getShopCategories() : Promise.resolve([]),
  ]);

  return (
    // 좌우 여백은 쇼핑몰 레이아웃의 .solune-shop-container 가 준다. 배너는 화면 폭(w-screen)으로 그 밖까지 편다.
    <div className="shop-home-page">
      <ShopHomeBanners banners={banners} />
      <ShopHomeCategories categories={categories} />
      <div className="site-container px-0 pb-8">
        <ShopHomeHit />
        <DeferredShopSections />
        <ShopHomePopular />
        <ShopHomeReviews />
        <ShopHomeSupport />
      </div>
      <ShopHomePopups popups={popups} />
    </div>
  );
}
