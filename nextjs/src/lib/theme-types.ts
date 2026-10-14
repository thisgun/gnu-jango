import type { ComponentType, ReactNode } from "react";
import type { MenuItem } from "@/components/layout/menu";
import type { WritePost } from "@/lib/types";

/**
 * 테마 소스(nextjs/themes/<이름>)가 앱에 꽂는 자리. 기준 프로젝트의 슬롯 구조에서 문서(매뉴얼)
 * 테마에 필요한 것만 옮겼다. 슬롯이 없으면 앱이 기본 화면을 그린다.
 */
export const G5_THEME_API_VERSION = 1;

export type G5ThemeApiVersion = typeof G5_THEME_API_VERSION;

export type G5ThemeFeatures = {
  /** 글 보기 아래에 그 게시판의 목록(분류 칩 · 글 줄 · 쪽 · 검색)을 붙인다 — 그누보드 기본 화면. */
  listUnderPostView: boolean;
};

export const G5_THEME_FEATURE_DEFAULTS: G5ThemeFeatures = { listUnderPostView: true };

export type G5ThemeConfig = {
  apiVersion: G5ThemeApiVersion;
  /** themes/ 아래 폴더 이름과 같다. <body data-g5-theme-source> 로 나간다. */
  name: string;
  label: string;
  /** 테마가 켜고 끄는 앱 동작. 적지 않은 것은 기본값(아래 G5_THEME_FEATURE_DEFAULTS)을 쓴다. */
  features?: Partial<G5ThemeFeatures>;
  site: {
    name: string;
    description: string;
    logoText: string;
    logoMark: string;
    themeColor?: string;
    /** 첫 화면의 제목·설명. 커뮤니티가 아닌 테마(문서 사이트 등)가 덮어쓴다. */
    homeTitle?: string;
    homeDescription?: string;
    footerDescription: string;
    customerCenterTitle: string;
    customerCenterLines: string[];
    copyrightName: string;
  };
};

export type G5ThemeComponentProps = {
  config: G5ThemeConfig;
  menus?: MenuItem[];
};

export type G5ThemeLayoutShellProps = G5ThemeComponentProps & {
  children: ReactNode;
};

/** 글보기 헤더 슬롯. 데이터와 동작(작성자 사이드뷰·글 동작·공유)은 앱이 넘기고 테마는 배치만 맡는다. */
export type G5ThemeBoardViewHeaderProps = {
  post: WritePost;
  boTable: string;
  boardName: string;
  /** 게시판 목록 주소. 테마가 머리에 "목록" 단추를 그릴 때 쓴다. */
  listHref?: string;
  author: ReactNode;
  actions: ReactNode;
  share: ReactNode;
};

/**
 * 클라이언트 컴포넌트가 ThemeSlotsProvider 를 통해 받는 프레젠테이션 슬롯.
 * 구현체는 반드시 "use client" 모듈이어야 한다 (서버 레이아웃이 참조를 넘긴다).
 */
export type G5ThemeClientSlots = {
  BoardViewHeader?: ComponentType<G5ThemeBoardViewHeaderProps>;
};

export type G5ThemeComponentSlots = G5ThemeClientSlots & {
  /** 머리 · 본문 틀 · 바닥을 통째로 바꾼다. 있으면 앱의 Header / CommunityInnerShell / Footer 를 쓰지 않는다. */
  LayoutShell?: ComponentType<G5ThemeLayoutShellProps>;
  /** 첫 화면(/). 비동기 서버 컴포넌트여도 된다. */
  HomePage?: ComponentType<G5ThemeComponentProps>;
};
