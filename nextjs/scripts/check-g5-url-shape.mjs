import { readFileSync } from "node:fs";
import { join } from "node:path";
import vm from "node:vm";
import * as ts from "typescript";

const root = process.cwd();
const shortUrlPath = join(root, "src/lib/g5-short-url.ts");
const productUrlPath = join(root, "src/lib/product-url.ts");

function fail(message) {
  console.error("[check-g5-url-shape] " + message);
  process.exit(1);
}

function loadTypeScriptModule(path, dependencies = {}) {
  const output = ts.transpileModule(readFileSync(path, "utf8"), {
    compilerOptions: {
      esModuleInterop: true,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: path,
    reportDiagnostics: true,
  });
  const diagnostics = output.diagnostics || [];
  if (diagnostics.length > 0) {
    fail("TypeScript transpilation failed for " + path);
  }

  const module = { exports: {} };
  vm.runInNewContext(output.outputText, {
    module,
    exports: module.exports,
    URLSearchParams,
    require(id) {
      if (Object.hasOwn(dependencies, id)) return dependencies[id];
      if (id === "@/lib/config") {
        return {
          appUrl(pathname) {
            return "https://nextjs.thisgun.net" + pathname;
          },
          g5PathForRuntime(pathname) {
            return pathname;
          },
          stripG5BasePath(pathname) {
            return pathname;
          },
        };
      }
      throw new Error("unexpected module dependency: " + id);
    },
  }, { filename: path });
  return module.exports;
}

const { appShortUrl, g5ShortHref, toG5ShortPath } = loadTypeScriptModule(shortUrlPath);
if (![appShortUrl, g5ShortHref, toG5ShortPath].every((value) => typeof value === "function")) {
  fail("g5-short-url exports are missing");
}

const KOREAN_BOARD = "%EC%9E%90%EC%9C%A0%EA%B2%8C%EC%8B%9C%ED%8C%90"; // 자유게시판

const cases = [
  // Board pages are published under /bbs/ (the internal Next.js route stays /boards).
  ["/boards", "/bbs"],
  ["/boards?group=community", "/bbs?group=community"],
  ["/boards/free", "/bbs/free"],
  ["/boards/free?sca=notice#top", "/bbs/free?sca=notice#top"],
  ["/boards/free/6", "/bbs/free/6"],
  ["/boards/free/write", "/bbs/free/write"],
  ["/boards/free/hello-world/", "/bbs/free/hello-world/"],
  ["/boards/free/rss", "/rss/free"],
  ["/boards/" + KOREAN_BOARD, "/bbs/" + KOREAN_BOARD],
  ["/boards/" + KOREAN_BOARD + "/6", "/bbs/" + KOREAN_BOARD + "/6"],
  ["/bbs/free/6", "/bbs/free/6"],
  ["/bbs/board.php?bo_table=free&page=2", "/bbs/free?page=2"],
  ["/bbs/board.php?bo_table=free&wr_id=6&page=2#reply", "/bbs/free/6?page=2#reply"],
  ["/bbs/board.php?bo_table=free&wr_seo_title=hello-world", "/bbs/free/hello-world/"],
  ["/bbs/board.php", "/bbs"],
  ["/bbs/write.php?bo_table=free&w=u&wr_id=6", "/bbs/free/write?w=u&wr_id=6"],
  ["/bbs/write.php", "/bbs"],
  ["/bbs/group.php?gr_id=community", "/bbs?group=community"],
  ["/mobile/group.php?gr_id=community", "/bbs?group=community"],
  ["/bbs/content.php?co_id=company", "/content/company"],
  ["/bbs/search.php?stx=delivery&sfl=wr_subject&bo_table=free&page=2", "/search?sfl=wr_subject&bo_table=free&page=2&q=delivery"],
  ["/bbs/login.php?url=%2Ffree%3Fpage%3D2", "/login?redirect=%2Ffree%3Fpage%3D2"],
  ["/bbs/login.php?url=https%3A%2F%2Fevil.example&foo=bar", "/login?foo=bar"],
  ["/bbs/register.php", "/register"],
  ["/mobile", "/"],
  ["/mobile/shop/cart.php", "/shop/cart"],
  ["/mobile/shop/item.php?it_id=1446772772&page=2", "/shop/1446772772?page=2"],
  ["/mobile/shop/category.php?ca_id=2010101010&page=2", "/shop/list-2010101010?page=2"],
  ["/mobile/shop/orderform.php?sw_direct=1", "/shop/order?direct=1"],
  ["/shop/item.php?it_id=1446772772&foo=bar#review", "/shop/1446772772?foo=bar#review"],
  ["/shop/item.php?it_seo_title=%EC%83%81%ED%92%88", "/shop/%EC%83%81%ED%92%88/"],
  ["/shop/item.php?it_id=cart", "/shop/products/cart"],
  ["/shop/item.php?it_seo_title=cart", "/shop/products"],
  ["/shop/category.php?ca_id=2010101010&page=2", "/shop/list-2010101010?page=2"],
  ["/shop/orderform.php?sw_direct=1", "/shop/order?direct=1"],
  ["/shop/products?it_type1=1", "/shop/type-1"],
  ["/shop/products?it_type5=1&page=2", "/shop/type-5?page=2"],
  ["/shop/products?sort=latest", "/shop/products?sort=latest"],
  ["/shop/products/cart", "/shop/products/cart"],
];

for (const [input, expected] of cases) {
  const actual = toG5ShortPath(input);
  if (actual !== expected) {
    fail(input + " produced " + actual + "; expected " + expected);
  }
}

if (g5ShortHref("/boards/free/6") !== "/bbs/free/6") {
  fail("g5ShortHref did not apply the /bbs board URL");
}
if (appShortUrl("/shop/products/1446772772") !== "https://nextjs.thisgun.net/shop/1446772772") {
  fail("appShortUrl did not apply the short product URL");
}

const productUrl = loadTypeScriptModule(productUrlPath, {
  "@/lib/board-url": {
    isBbsSeoRewrite(mode) {
      return Number(mode) === 2;
    },
  },
  "@/lib/g5-short-url": {
    g5ShortHref(value) {
      return toG5ShortPath(value);
    },
  },
});
const safeSeo = { it_id: "123", it_seo_title: "linen-shirt" };
const unsafeSeo = { it_id: "123", it_seo_title: "../cart" };
const reservedSeo = { it_id: "123", it_seo_title: "cart" };

if (productUrl.shopProductPath(safeSeo, 2) !== "/shop/products/linen-shirt/") {
  fail("SEO product URL was not preserved");
}
if (productUrl.shopProductPath(safeSeo) !== "/shop/products/123") {
  fail("numeric product URL was not preserved");
}
for (const product of [unsafeSeo, reservedSeo]) {
  const path = productUrl.shopProductPath(product, 2);
  if (path !== "/shop/products/123" || path.includes("/../") || path === "/shop/cart") {
    fail("unsafe SEO segment escaped the product route: " + path);
  }
}

console.log("[check-g5-url-shape] " + cases.length + " legacy URL cases and product path guards passed");
