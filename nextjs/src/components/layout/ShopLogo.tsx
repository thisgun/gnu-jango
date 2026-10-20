"use client";

import { useState } from "react";
import type { PublicSettings } from "@/lib/schemas";

/** 로고를 모바일 그림으로 바꾸는 폭 — 헤더 · 푸터가 폰 모양으로 바뀌는 폭과 같다. */
export const SHOP_LOGO_MOBILE_MEDIA = "(max-width: 767px)";

export interface ShopLogoSources {
  /** PC(넓은 화면) 로고 — 올린 것이 없으면 "" */
  pc: string;
  /** 모바일 로고 — 올린 것이 없으면 "" (그때는 PC 로고를 쓴다) */
  mobile: string;
}

/** 공개 설정의 쇼핑몰 로고(관리자 쇼핑몰 설정에서 올린 그림). 위치: header(상단) · footer(하단). */
export function shopLogoSources(settings: PublicSettings | null | undefined, position: "header" | "footer"): ShopLogoSources {
  const pick = (value: string | undefined) => (value || "").trim();
  return position === "header"
    ? { pc: pick(settings?.shop_logo), mobile: pick(settings?.shop_logo_mobile) }
    : { pc: pick(settings?.shop_logo_footer), mobile: pick(settings?.shop_logo_mobile_footer) };
}

export function hasShopLogo(sources: ShopLogoSources): boolean {
  return Boolean(sources.pc || sources.mobile);
}

/**
 * 올린 로고 — 폰 폭에서는 모바일 로고(없으면 PC 로고), 넓은 화면에서는 PC 로고. PC 로고가 없으면 넓은 화면은
 * fallbackSrc(기본 로고 그림)를 쓴다. fallbackSrc 도 없고 PC 로고도 없으면 모바일 로고를 어디서나 쓴다.
 */
export function ShopLogoPicture({
  sources,
  alt,
  className,
  fallbackSrc = "",
  width,
  height,
}: {
  sources: ShopLogoSources;
  alt: string;
  className?: string;
  fallbackSrc?: string;
  width?: number;
  height?: number;
}) {
  // 올린 파일을 불러오지 못하면(지워졌으면) 기본 로고로 돌아간다.
  const uploaded = sources.pc || sources.mobile;
  const [failedSrc, setFailedSrc] = useState("");
  const useFallback = Boolean(fallbackSrc) && failedSrc !== "" && failedSrc === uploaded;
  const main = useFallback ? fallbackSrc : sources.pc || fallbackSrc || sources.mobile;
  if (!main) return null;
  const usesUpload = !useFallback && Boolean(sources.pc || !fallbackSrc);
  return (
    <picture className="solune-brand-picture">
      {!useFallback && sources.mobile && sources.mobile !== main ? (
        <source media={SHOP_LOGO_MOBILE_MEDIA} srcSet={sources.mobile} />
      ) : null}
      <img
        className={[className, usesUpload ? "solune-brand-logo--uploaded" : ""].filter(Boolean).join(" ")}
        src={main}
        alt={alt}
        width={usesUpload ? undefined : width}
        height={usesUpload ? undefined : height}
        decoding="async"
        onError={() => setFailedSrc(uploaded)}
      />
    </picture>
  );
}
