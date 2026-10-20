import { expect, test } from "@playwright/test";
import {
  DEFAULT_HOME_DISPLAY,
  DEFAULT_SHOP_LIST_DISPLAY,
  columnSteps,
  shopGridStyle,
  shopHomeDisplaySchema,
  shopListDisplayOf,
  shopListDisplaySchema,
  shopRowItemClass,
  shopRowLimit,
  shopRowStyle,
} from "../src/lib/shop-display";
import { hasShopLogo, shopLogoSources } from "../src/components/layout/ShopLogo";

test.describe("shop display settings", () => {
  test("column steps keep the pre-settings layout for the defaults", () => {
    expect(columnSteps(2, 5)).toEqual([2, 3, 4, 5]);
    expect(columnSteps(1, 8)).toEqual([1, 3, 6, 8]);
    expect(columnSteps(4, 2)).toEqual([4, 3, 3, 2]);
    expect(columnSteps(3, 3)).toEqual([3, 3, 3, 3]);
  });

  test("row style sets slides per view with the half-card peek", () => {
    const section = { ...DEFAULT_HOME_DISPLAY.type1, pc_cols: 4, mobile_cols: 1 };
    expect(shopRowStyle(section, true)).toEqual({
      "--solune-row-spv-xs": 1.5,
      "--solune-row-spv-sm": 2.5,
      "--solune-row-spv-md": 3.5,
      "--solune-row-spv-lg": 4.5,
    });
    expect(shopRowStyle(section, false)["--solune-row-spv-lg"]).toBe(4);
  });

  test("items beyond each screen's count are marked for CSS to hide", () => {
    const section = { ...DEFAULT_HOME_DISPLAY.type1, pc_count: 10, mobile_count: 8 };
    expect(shopRowLimit(section)).toBe(10);
    expect(shopRowItemClass(7, section)).toBeUndefined();
    expect(shopRowItemClass(8, section)).toBe("solune-row-item--hide-mobile");
    const mobileHeavy = { ...section, pc_count: 3, mobile_count: 6 };
    expect(shopRowLimit(mobileHeavy)).toBe(6);
    expect(shopRowItemClass(3, mobileHeavy)).toBe("solune-row-item--hide-pc");
    expect(shopRowItemClass(6, mobileHeavy)).toBe("solune-row-item--hide-mobile solune-row-item--hide-pc");
  });

  test("home display falls back to the youngcart defaults", () => {
    expect(shopHomeDisplaySchema.parse(undefined)).toEqual(DEFAULT_HOME_DISPLAY);
    expect(shopHomeDisplaySchema.parse("junk")).toEqual(DEFAULT_HOME_DISPLAY);
    const parsed = shopHomeDisplaySchema.parse({
      type2: { use: false, pc_cols: "3", pc_count: 6, mobile_cols: 1, mobile_count: 4, count: 0 },
    });
    expect(parsed.type1).toEqual(DEFAULT_HOME_DISPLAY.type1);
    expect(parsed.type2).toEqual({ use: false, pc_cols: 3, pc_count: 6, mobile_cols: 1, mobile_count: 4 });
  });

  test("list display reads the public settings block", () => {
    expect(shopListDisplayOf(null)).toEqual(DEFAULT_SHOP_LIST_DISPLAY);
    const parsed = shopListDisplaySchema.parse({
      search: { pc_cols: 4, rows: 3, per_page: 12, mobile_cols: 1 },
      related: { use: false, pc_cols: 3, mobile_cols: 1 },
    });
    expect(parsed.search.per_page).toBe(12);
    expect(parsed.listtype).toEqual(DEFAULT_SHOP_LIST_DISPLAY.listtype);
    expect(parsed.related.use).toBe(false);
    expect(shopGridStyle(1, 4)).toEqual({
      "--shop-grid-cols-xs": 1,
      "--shop-grid-cols-sm": 2,
      "--shop-grid-cols-md": 3,
      "--shop-grid-cols-lg": 4,
    });
  });

  test("logo sources pick the uploaded header and footer images", () => {
    const settings = { shop_logo: " /media/top.png ", shop_logo_mobile: "", shop_logo_footer: "", shop_logo_mobile_footer: "/media/m.png" };
    expect(shopLogoSources(settings, "header")).toEqual({ pc: "/media/top.png", mobile: "" });
    expect(shopLogoSources(settings, "footer")).toEqual({ pc: "", mobile: "/media/m.png" });
    expect(hasShopLogo(shopLogoSources(null, "header"))).toBe(false);
  });
});
