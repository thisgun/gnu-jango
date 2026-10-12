import { buildPageMetadata } from "@/lib/seo";
import { getShopBanners, getShopCategories, getShopPopups } from "@/services/shop";
import { DeferredShopSections } from "./DeferredShopSections";
import { ShopHomeBanners, ShopHomePopups } from "./ShopHomeMarketing";
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
  const [banners, popups, categories] = await Promise.all([
    getShopBanners({ position: "메인", device: "all" }),
    getShopPopups({ device: "all", limit: 5 }),
    getShopCategories(),
  ]);

  return (
    <div className="shop-home-page -mt-4">
      <ShopHomeBanners banners={banners} />
      <ShopHomeCategories categories={categories} />
      <div className="site-container px-0 pb-8 sm:px-2 lg:px-4">
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
