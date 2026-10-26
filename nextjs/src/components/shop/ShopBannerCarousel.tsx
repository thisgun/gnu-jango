"use client";

import { useCallback, useEffect, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";
import type { Swiper as SwiperInstance } from "swiper";
import { ArrowRight, ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";
import type { ShopBanner } from "@/lib/api";
import {
  BANNER_INTERVAL_MS,
  BANNER_SPEED_MS,
  bannerLink,
  bannerSlidesToLoad,
  padBannerNumber,
  splitBannerCopy,
  withBannerSlides,
} from "@/lib/shop-banner";
import { useDynamicSwiper } from "@/lib/use-dynamic-swiper";
import { cn } from "@/lib/utils";

/** 키보드로 옮긴 초점인가. 마우스로 단추를 누를 때 생기는 초점은 :focus-visible 이 아니다. */
function isKeyboardFocus(target: EventTarget): boolean {
  if (!(target instanceof Element)) return false;
  try {
    return target.matches(":focus-visible");
  } catch {
    return true;
  }
}

/** 활성 막대가 얼마나 찼는지(0~1). shop-banner CSS 의 --solune-banner-progress 로 넘긴다. */
function setBannerProgress(swiper: SwiperInstance, value: number) {
  swiper.el?.style.setProperty("--solune-banner-progress", String(Math.max(0, Math.min(1, value))));
}

function BannerSlide({
  banner,
  index,
  active,
  load,
  onSettled,
  onImageError,
}: {
  banner: ShopBanner;
  index: number;
  active: boolean;
  load: boolean;
  onSettled?: () => void;
  onImageError: (bannerId: number) => void;
}) {
  const copy = splitBannerCopy(banner.bn_alt);
  const { href, openNew } = bannerLink(banner);

  return (
    <div className={cn("swiper-slide solune-banner-slide", banner.bn_border === 1 && "has-border")}>
      <a
        href={href}
        target={openNew ? "_blank" : undefined}
        rel={openNew ? "noopener noreferrer" : undefined}
        aria-label={copy ? `${copy.eyebrow}: ${copy.title}` : undefined}
        tabIndex={active ? 0 : -1}
      >
        <img
          className="solune-banner-img"
          /* 겹쳐 녹이는 효과라 모든 장이 한자리에 쌓여 loading="lazy" 가 듣지 않는다 — load 가 켜진 장만 받는다. */
          src={load ? banner.image_url : undefined}
          data-banner-id={banner.bn_id}
          alt={banner.bn_alt || `쇼핑몰 배너 ${index + 1}`}
          aria-hidden={copy ? true : undefined}
          width={1920}
          height={920}
          fetchPriority={index === 0 ? "high" : undefined}
          decoding={index === 0 ? undefined : "async"}
          draggable={false}
          onLoad={onSettled}
          onError={() => {
            onSettled?.();
            onImageError(banner.bn_id);
          }}
        />
      </a>
      {copy ? (
        /* 글은 화면 낭독기에 다시 내지 않는다(링크 이름이 같은 값). 클릭은 아래 링크로 통과시킨다. */
        <div className="solune-banner-caption" aria-hidden="true">
          <div className="solune-banner-caption-inner">
            <span className="solune-banner-eyebrow">{copy.eyebrow}</span>
            {/* 제목은 strong — 쇼핑몰 CSS 의 "main h2"(16px) 규칙에 걸리지 않는다. */}
            <strong className="solune-banner-title">{copy.title}</strong>
            <span className="solune-banner-cta">
              자세히 보기
              <ArrowRight size={16} aria-hidden />
            </span>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/**
 * 쇼핑 홈 첫 화면 — 레퍼런스 shop-banner.tsx(mainbanner.10.skin.php)와 같은 Swiper 설정:
 * loop · fade(900ms) · 6.5초 자동 넘김(마우스를 올리거나 키보드 초점이 들어오면 멎음) · 막대 표시 ·
 * "01 / 07" · 멈춤 단추 · 좌우 단추. 첫 장은 서버 HTML 에 그대로 있고(Swiper 전에도 같은 자리 · 같은 높이),
 * Swiper 는 브라우저에서 useDynamicSwiper 로 붙는다. 움직임을 줄여 달라고 한 사람에게는 자동으로 넘기지 않고
 * 넘김도 즉시 바뀐다. 한 장이면 Swiper 도 단추도 없다.
 */
export function ShopBannerCarousel({
  banners,
  reducedMotion,
  onImageError,
}: {
  banners: ShopBanner[];
  reducedMotion: boolean;
  onImageError: (bannerId: number) => void;
}) {
  const count = banners.length;
  const multi = count > 1;
  const swiperElRef = useRef<HTMLDivElement>(null);
  const prevRef = useRef<HTMLButtonElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const paginationRef = useRef<HTMLDivElement>(null);
  const pausedRef = useRef(false);
  const focusPausedRef = useRef(false);
  const firstSettledRef = useRef(false);
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [loaded, setLoaded] = useState<ReadonlySet<number>>(() => new Set([0]));

  /* 첫 장이 보인 뒤에 앞뒤 장을 받아 둔다 — 어느 쪽으로 넘기든 바로 보이게. */
  const warmNeighbours = useCallback(() => {
    if (firstSettledRef.current) return;
    firstSettledRef.current = true;
    if (count > 1) setLoaded((prev) => withBannerSlides(prev, [1, count - 1]));
  }, [count]);

  const swiperRef = useDynamicSwiper(
    swiperElRef,
    () => ({
      loop: true,
      effect: "fade",
      fadeEffect: { crossFade: true },
      speed: reducedMotion ? 0 : BANNER_SPEED_MS,
      autoplay: reducedMotion
        ? false
        : { delay: BANNER_INTERVAL_MS, disableOnInteraction: false, pauseOnMouseEnter: true },
      a11y: {
        prevSlideMessage: "이전 배너",
        nextSlideMessage: "다음 배너",
        paginationBulletMessage: "{{index}}번 배너로 이동",
        slideLabelMessage: "{{index}} / {{slidesLength}}",
      },
      navigation: { prevEl: prevRef.current, nextEl: nextRef.current },
      pagination: { el: paginationRef.current, clickable: true },
      on: {
        init(swiper) {
          /* 움직임 줄임이 바뀌면 Swiper 를 새로 세운다 — 번호를 새 Swiper 의 첫 자리에 맞춘다. */
          setIndex(swiper.realIndex);
          setBannerProgress(swiper, reducedMotion ? 1 : 0);
          if (pausedRef.current) swiper.autoplay?.stop();
        },
        slideChange(swiper) {
          const current = swiper.realIndex;
          setIndex(current);
          setLoaded((prev) => withBannerSlides(prev, bannerSlidesToLoad(current, count, firstSettledRef.current)));
        },
        autoplayTimeLeft(swiper, _timeLeft, percentage) {
          setBannerProgress(swiper, 1 - percentage);
        },
      },
    }),
    [reducedMotion],
    {
      enabled: multi,
      modules: (modules) => [modules.A11y, modules.Autoplay, modules.EffectFade, modules.Navigation, modules.Pagination],
    }
  );

  /* 서버 HTML 의 사진은 하이드레이션 전에 다 받아지거나 실패해 onLoad · onError 를 놓친다. 붙은 뒤에 한 번 본다. */
  useEffect(() => {
    const images = swiperElRef.current?.querySelectorAll<HTMLImageElement>("img[data-banner-id][src]") ?? [];
    images.forEach((image) => {
      if (!image.complete) return;
      if (image.naturalWidth === 0) onImageError(Number(image.dataset.bannerId));
      else if (image.dataset.bannerId === String(banners[0]?.bn_id)) warmNeighbours();
    });
    // 처음 붙을 때만 — 이후는 onLoad · onError 가 맡는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* 움직임 줄임이 켜지면 자동 넘김도 멈춤 단추도 없다 — 멈춤 상태(is-paused)를 남겨 두지 않는다. */
  useEffect(() => {
    if (!reducedMotion) return;
    pausedRef.current = false;
    setPaused(false);
  }, [reducedMotion]);

  const togglePause = () => {
    const next = !pausedRef.current;
    pausedRef.current = next;
    setPaused(next);
    const autoplay = swiperRef.current?.autoplay;
    if (!autoplay) return;
    if (next) autoplay.stop();
    else autoplay.start();
  };

  /* 마우스는 Swiper 의 pauseOnMouseEnter 가, 키보드 초점은 여기서 멈춘다. 초점이 나가면 다시 간다. */
  const handleFocus = (event: FocusEvent<HTMLDivElement>) => {
    const autoplay = swiperRef.current?.autoplay;
    if (!autoplay?.running || autoplay.paused || !isKeyboardFocus(event.target)) return;
    autoplay.pause();
    focusPausedRef.current = true;
  };
  const handleBlur = (event: FocusEvent<HTMLDivElement>) => {
    if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return;
    if (!focusPausedRef.current) return;
    focusPausedRef.current = false;
    const autoplay = swiperRef.current?.autoplay;
    if (autoplay?.running && !pausedRef.current) autoplay.resume();
  };
  /* 좌우 화살표는 초점이 배너 안에 있을 때만 — 페이지 어디서나 화살표를 가로채지 않는다. */
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const swiper = swiperRef.current;
    if (!swiper) return;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      swiper.slidePrev();
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      swiper.slideNext();
    }
  };

  return (
    <section className="solune-shop-banner" aria-label="쇼핑몰 추천 배너" aria-roledescription={multi ? "carousel" : undefined}>
      {/* 상태 클래스(is-multi · is-paused)는 Swiper 가 클래스를 붙이는 .swiper 가 아니라 이 바깥 상자에 둔다. */}
      <div
        id="main_bn"
        className={cn("solune-banner", multi && "is-multi", paused && "is-paused")}
        onFocus={multi ? handleFocus : undefined}
        onBlur={multi ? handleBlur : undefined}
        onKeyDown={multi ? handleKeyDown : undefined}
      >
        <div ref={swiperElRef} className="swiper solune-banner-swiper">
          <div className="swiper-wrapper">
            {banners.map((banner, slideIndex) => (
              <BannerSlide
                key={banner.bn_id}
                banner={banner}
                index={slideIndex}
                active={!multi || slideIndex === index}
                load={loaded.has(slideIndex)}
                onSettled={slideIndex === 0 ? warmNeighbours : undefined}
                onImageError={onImageError}
              />
            ))}
          </div>
          {multi ? (
            <>
              {/* 아래 표시줄 — 막대와 "01 / 07", 멈춤 단추를 본문 기둥 폭 안에 둔다. */}
              <div className="solune-banner-foot">
                <div ref={paginationRef} className="solune-banner-pagination swiper-pagination" />
                <div className="solune-banner-foot-right">
                  <span className="solune-banner-count">
                    <b className="solune-banner-count-now">{padBannerNumber(index + 1)}</b>
                    <span className="solune-banner-count-sep">/</span>
                    {padBannerNumber(count)}
                  </span>
                  {/* 마우스를 올려 두면 멎지만 손가락에는 그 길이 없다. 저절로 바뀌는 것은 멈출 수 있어야 한다. */}
                  {!reducedMotion ? (
                    <button
                      type="button"
                      className="solune-banner-play"
                      aria-pressed={paused}
                      aria-label={paused ? "자동 넘김 재생" : "자동 넘김 멈춤"}
                      onClick={togglePause}
                    >
                      {paused ? <Play size={12} aria-hidden /> : <Pause size={12} aria-hidden />}
                    </button>
                  ) : null}
                </div>
              </div>
              <button ref={prevRef} type="button" className="solune-banner-nav solune-banner-prev" aria-label="이전 배너">
                <ChevronLeft size={20} aria-hidden />
              </button>
              <button ref={nextRef} type="button" className="solune-banner-nav solune-banner-next" aria-label="다음 배너">
                <ChevronRight size={20} aria-hidden />
              </button>
            </>
          ) : null}
        </div>
      </div>
    </section>
  );
}
