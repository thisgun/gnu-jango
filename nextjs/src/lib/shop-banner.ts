import type { ShopBanner } from "@/lib/api";

/** 자동 넘김 간격과 겹쳐 녹이는 시간 — 레퍼런스 shop-banner.tsx(mainbanner.10.skin.php)와 같은 값. */
export const BANNER_INTERVAL_MS = 6500;
export const BANNER_SPEED_MS = 900;

const DEMO_SAMPLE_BANNER_ALT = "차분한 일상을 위한 데모 스토어";

const DEMO_SAMPLE_BANNER_FALLBACKS: ShopBanner[] = [
  {
    bn_id: -2,
    bn_alt: "DESK OBJECTS|책상 위를 더 가볍게",
    bn_url: "/shop/type-1",
    bn_position: "메인",
    bn_device: "both",
    bn_border: 0,
    bn_new_win: 0,
    bn_order: 2,
    image_url: "/sample-data/product-02.webp",
  },
  {
    bn_id: -3,
    bn_alt: "SLOW KITCHEN|매일 쓰는 도구의 온기",
    bn_url: "/shop/type-2",
    bn_position: "메인",
    bn_device: "both",
    bn_border: 0,
    bn_new_win: 0,
    bn_order: 3,
    image_url: "/sample-data/product-04.webp",
  },
];

/** 데모 배너 한 장만 있는 설치본은 넘김이 보이도록 견본 두 장을 덧붙인다. */
export function withDemoSampleRotation(banners: ShopBanner[]): ShopBanner[] {
  if (banners.length !== 1 || banners[0].bn_alt.trim() !== DEMO_SAMPLE_BANNER_ALT) {
    return banners;
  }
  return [{ ...banners[0], bn_alt: `DESK NOTES|${DEMO_SAMPLE_BANNER_ALT}` }, ...DEMO_SAMPLE_BANNER_FALLBACKS];
}

/**
 * 지금 화면에 낼 배너. 그림이 없거나 받지 못한 배너는 빼고, 접속기기(bn_device: both · pc · mobile)에
 * 맞는 것만 고른다. 맞는 것이 하나도 없으면 기기를 가리지 않고 낸다(빈 첫 화면보다 낫다).
 */
export function selectShopBanners(
  banners: ShopBanner[],
  { isMobile, failedIds = [] }: { isMobile: boolean; failedIds?: readonly number[] }
): ShopBanner[] {
  const usable = withDemoSampleRotation(banners).filter(
    (banner) => banner.image_url && !failedIds.includes(banner.bn_id)
  );
  const forDevice = usable.filter((banner) => {
    const device = (banner.bn_device || "both").toLowerCase();
    return isMobile ? device !== "pc" && device !== "desktop" : device !== "mobile";
  });
  return forDevice.length > 0 ? forDevice : usable;
}

/** 배너 폼의 "이미지 설명"(bn_alt)이 "눈썹글|제목" 꼴일 때만 사진 위에 글을 얹는다. 아니면 그냥 대체 글. */
export function splitBannerCopy(alt: string): { eyebrow: string; title: string } | null {
  const [eyebrow = "", ...rest] = (alt || "").split("|");
  const title = rest.join("|").trim();
  return eyebrow.trim() && title ? { eyebrow: eyebrow.trim(), title } : null;
}

/** 배너 링크 — 클릭 수를 세는 bannerhit 를 거친다. 새 창 설정이거나 바깥 주소면 새 창. */
export function bannerLink(banner: Pick<ShopBanner, "bn_id" | "bn_url" | "bn_new_win" | "hit_url">) {
  const href = banner.hit_url || `/shop/bannerhit.php?bn_id=${encodeURIComponent(String(banner.bn_id))}`;
  const openNew = banner.bn_new_win === 1 || /^https?:\/\//i.test(banner.bn_url || "");
  return { href, openNew };
}

/** "01 / 07" 의 두 자리 숫자. */
export function padBannerNumber(value: number): string {
  return String(value).padStart(2, "0");
}

/**
 * 받아 둘 슬라이드 번호. 겹쳐 녹이는(fade) 효과라 모든 장이 한자리에 쌓여 loading="lazy" 가 듣지 않는다.
 * 지금 장과 그 앞뒤 장만 받는다. 첫 장을 다 받기 전에는 첫 장만 — 대역폭을 나눠 쓰지 않게.
 */
export function bannerSlidesToLoad(current: number, count: number, firstSettled: boolean): number[] {
  if (count <= 1) return [0];
  if (current === 0 && !firstSettled) return [0];
  return [current, (current + 1) % count, (current - 1 + count) % count];
}

/** 이미 있는 묶음에 번호를 더한다. 더할 것이 없으면 같은 묶음을 돌려 다시 그리지 않게 한다. */
export function withBannerSlides(prev: ReadonlySet<number>, slides: number[]): ReadonlySet<number> {
  if (slides.every((slide) => prev.has(slide))) return prev;
  return new Set([...prev, ...slides]);
}
