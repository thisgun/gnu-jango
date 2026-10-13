import type { Metadata } from "next";
import { buildPageMetadata } from "@/lib/seo";
import {
  getShopProductBySeoResult,
  getShopProductResult,
} from "@/services/shop";
import type { ShopProduct } from "@/lib/api";
import ProductDetailClient from "./ProductDetailClient";

export const dynamicParams = true;
export const dynamic = "force-static";

export async function generateStaticParams() {
  return [{ it_id: "__g5_static__" }];
}

interface PageProps {
  params: Promise<{ it_id: string }>;
}

type ProductPageResolution = {
  product: ShopProduct | null;
};

async function resolveProductForPage(
  itId: string
): Promise<ProductPageResolution> {
  if (itId === "__g5_static__") return { product: null };

  const byId = await getShopProductResult(itId).catch(() => null);
  if (byId?.ok) return { product: byId.data };

  const bySeo = await getShopProductBySeoResult(itId).catch(() => null);
  if (bySeo?.ok) return { product: bySeo.data };

  return { product: null };
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { it_id } = await params;
  const { product } = await resolveProductForPage(it_id);

  const metadata = buildPageMetadata({
    title: product?.it_name || "상품 상세",
    description: product?.it_basic || product?.it_explan || product?.it_name,
    path: product?.it_id
      ? `/shop/products/${encodeURIComponent(product.it_id)}`
      : it_id === "__g5_static__"
        ? "/shop/products"
        : `/shop/products/${encodeURIComponent(it_id)}`,
    image: product?.image_url || product?.images?.[0],
  });

  return product
    ? metadata
    : { ...metadata, robots: { index: false, follow: false } };
}

export default async function ProductDetailPage({ params }: PageProps) {
  const { it_id } = await params;
  const { product } = await resolveProductForPage(it_id);

  return <ProductDetailClient itId={it_id} initialProduct={product} />;
}
