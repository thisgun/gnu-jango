import { test, expect } from "@playwright/test";
import { parseApiEnvelope } from "../src/lib/api-response";
import { shopProductSchema } from "../src/lib/schemas";
import { unifiedSearchSchema } from "../src/services/search";

test("categoryless search products can open their detail page", () => {
  const product = shopProductSchema.parse({
    it_id: "search-item", ca_id: "", it_name: "입금 안내 상품", it_price: 12000,
    it_basic_price: 12000, it_cust_price: 0, it_point: 0, it_stock_qty: 5,
    it_soldout: "", it_type1: "", it_type2: "", it_type3: "", it_type4: "", it_type5: "",
    image_url: "", category: null,
  });
  expect(product.it_name).toBe("입금 안내 상품");
  expect(product.category).toBeUndefined();
});

test("unified search rejects unsafe result links", () => {
  for (const url of ["https://other.invalid/", "//other.invalid/", "/\\other.invalid/", "/\u0000"] ) {
    expect(unifiedSearchSchema.safeParse({query: "안내", results: [{
      type: "product", id: "1", title: "상품", url, snippet: "", score: 1, click_token: "",
    }]}).success).toBe(false);
  }
});

test("search pagination and truncation survive envelope parsing", () => {
  const response = parseApiEnvelope({success: true, data: {}, meta: {
    total: 350, current_page: 1, per_page: 20, total_pages: 10,
    engine: "inverted-index", truncated: true,
  }});
  expect(response.meta).toMatchObject({total: 350, total_pages: 10, truncated: true, engine: "inverted-index"});
});
