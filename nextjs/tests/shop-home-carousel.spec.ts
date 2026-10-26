import { expect, test } from "@playwright/test";
import type { ShopBanner } from "../src/lib/api";
import {
  bannerLink,
  bannerSlidesToLoad,
  padBannerNumber,
  selectShopBanners,
  splitBannerCopy,
  withBannerSlides,
  withDemoSampleRotation,
} from "../src/lib/shop-banner";
import { assignCategoryIcons } from "../src/lib/shop-category-icons";

function banner(overrides: Partial<ShopBanner>): ShopBanner {
  return {
    bn_id: 1,
    bn_alt: "",
    bn_url: "",
    bn_position: "메인",
    bn_device: "both",
    bn_border: 0,
    bn_new_win: 0,
    bn_order: 0,
    image_url: "/data/banner/1",
    ...overrides,
  };
}

test.describe("shop home banner helpers", () => {
  test("picks banners for the visitor's device and falls back to all", () => {
    const list = [
      banner({ bn_id: 1, bn_device: "both" }),
      banner({ bn_id: 2, bn_device: "pc" }),
      banner({ bn_id: 3, bn_device: "mobile" }),
    ];
    expect(selectShopBanners(list, { isMobile: false }).map((b) => b.bn_id)).toEqual([1, 2]);
    expect(selectShopBanners(list, { isMobile: true }).map((b) => b.bn_id)).toEqual([1, 3]);
    const pcOnly = [banner({ bn_id: 9, bn_device: "pc" })];
    expect(selectShopBanners(pcOnly, { isMobile: true }).map((b) => b.bn_id)).toEqual([9]);
  });

  test("drops banners without an image or whose image failed", () => {
    const list = [banner({ bn_id: 1 }), banner({ bn_id: 2, image_url: "" }), banner({ bn_id: 3 })];
    expect(selectShopBanners(list, { isMobile: false, failedIds: [3] }).map((b) => b.bn_id)).toEqual([1]);
  });

  test("a lone demo banner gains the sample rotation", () => {
    const rotated = withDemoSampleRotation([banner({ bn_alt: "차분한 일상을 위한 데모 스토어" })]);
    expect(rotated).toHaveLength(3);
    expect(rotated[0].bn_alt).toBe("DESK NOTES|차분한 일상을 위한 데모 스토어");
    const own = [banner({ bn_alt: "우리 가게" })];
    expect(withDemoSampleRotation(own)).toBe(own);
  });

  test("caption copy needs both an eyebrow and a title", () => {
    expect(splitBannerCopy("AUTUMN TABLE | 한 그릇으로 차분해지는 저녁")).toEqual({
      eyebrow: "AUTUMN TABLE",
      title: "한 그릇으로 차분해지는 저녁",
    });
    expect(splitBannerCopy("그냥 대체 글")).toBeNull();
    expect(splitBannerCopy("|제목만")).toBeNull();
  });

  test("links go through the hit counter and open external targets in a new window", () => {
    expect(bannerLink(banner({ bn_id: 7, bn_url: "/shop/type-1" }))).toEqual({
      href: "/shop/bannerhit.php?bn_id=7",
      openNew: false,
    });
    expect(bannerLink(banner({ bn_url: "https://example.com", hit_url: "/hit/1" }))).toEqual({
      href: "/hit/1",
      openNew: true,
    });
    expect(bannerLink(banner({ bn_new_win: 1 })).openNew).toBe(true);
  });

  test("counter numbers are two digits", () => {
    expect(padBannerNumber(1)).toBe("01");
    expect(padBannerNumber(12)).toBe("12");
  });

  test("only the current slide and its neighbours are fetched", () => {
    expect(bannerSlidesToLoad(0, 7, false)).toEqual([0]);
    expect(bannerSlidesToLoad(0, 7, true)).toEqual([0, 1, 6]);
    expect(bannerSlidesToLoad(6, 7, true)).toEqual([6, 0, 5]);
    expect(bannerSlidesToLoad(0, 1, true)).toEqual([0]);
    const start = new Set([0]);
    expect(withBannerSlides(start, [0])).toBe(start);
    expect([...withBannerSlides(start, [0, 1, 6])]).toEqual([0, 1, 6]);
  });
});

test.describe("shop category icons", () => {
  test("never repeats an icon within one row", () => {
    const ids = ["10", "1010", "20", "2010", "30", "40", "50", "60", "70", "80", "90", "a0", "b0", "c0", "d0", "e0"];
    const icons = assignCategoryIcons(ids);
    expect(icons).toHaveLength(ids.length);
    expect(new Set(icons).size).toBe(ids.length);
  });
});
