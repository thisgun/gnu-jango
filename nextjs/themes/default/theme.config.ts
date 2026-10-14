import type { G5ThemeConfig } from "@/lib/theme-types";

// 기본(nextjs_default) 테마. 화면은 앱 자체가 그리므로 슬롯이 없고, 사이트 이름과 설명만 여기 둔다.
export const themeConfig = {
  apiVersion: 1,
  name: "default",
  label: "Next.js Default",
  site: {
    name: "그누보드5",
    description: "그누보드5 + Next.js 커뮤니티 & 쇼핑몰",
    logoText: "그누보드5",
    logoMark: "G",
    footerDescription: "",
    customerCenterTitle: "",
    customerCenterLines: [],
    copyrightName: "그누보드5",
  },
} satisfies G5ThemeConfig;
