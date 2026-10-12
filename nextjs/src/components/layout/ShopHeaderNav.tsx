"use client";

import { useEffect, useState } from "react";
import { Menu } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import type { ShopCategory } from "@/lib/api";
import { getShopCategories } from "@/services/shop";

const PRIMARY_LINKS = [
  { href: "/shop/type-1", label: "히트상품" },
  { href: "/shop/type-2", label: "추천상품" },
  { href: "/shop/type-3", label: "최신상품" },
  { href: "/shop/type-4", label: "인기상품" },
  { href: "/shop/type-5", label: "할인상품" },
] as const;

function ShopCategoryItem({ category, depth = 0 }: { category: ShopCategory; depth?: number }) {
  const children = category.children ?? [];

  return (
    <li>
      <Link
        href={`/shop/list-${encodeURIComponent(category.ca_id)}`}
        className={depth > 0 ? "text-sm text-base-content/75" : "font-semibold"}
        onClick={(event) => event.currentTarget.closest("details")?.removeAttribute("open")}
      >
        {category.ca_name}
        {category.item_count ? <span className="ml-auto text-xs text-base-content/50">{category.item_count}</span> : null}
      </Link>
      {children.length > 0 ? (
        <ul>
          {children.map((child) => <ShopCategoryItem key={child.ca_id} category={child} depth={depth + 1} />)}
        </ul>
      ) : null}
    </li>
  );
}

export function ShopHeaderNav() {
  const [categories, setCategories] = useState<ShopCategory[]>([]);

  useEffect(() => {
    let active = true;
    getShopCategories().then((items) => {
      if (active) setCategories(items);
    }).catch(() => {
      if (active) setCategories([]);
    });
    return () => { active = false; };
  }, []);

  return (
    <nav aria-label="쇼핑몰 주요 메뉴" className="solune-shop-header-nav">
      <details className="dropdown dropdown-start solune-shop-category-dropdown">
        <summary className="btn btn-sm solune-shop-category-trigger">
          <Menu aria-hidden="true" className="size-[15px]" />
          <span>카테고리</span>
        </summary>
        <ul className="menu dropdown-content z-50 mt-2 max-h-[70vh] w-64 flex-nowrap overflow-y-auto rounded-box border border-base-300 bg-base-100 p-2 shadow-lg">
          {categories.length > 0 ? categories.map((category) => (
            <ShopCategoryItem key={category.ca_id} category={category} />
          )) : (
            <li><Link href="/shop/products" onClick={(event) => event.currentTarget.closest("details")?.removeAttribute("open")}>전체 상품 보기</Link></li>
          )}
        </ul>
      </details>
      <div className="solune-shop-type-nav">
        {PRIMARY_LINKS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="solune-shop-type-link"
            onClick={(event) => event.currentTarget.closest("details")?.removeAttribute("open")}
          >
            {item.label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
