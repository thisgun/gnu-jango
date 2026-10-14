import { themeComponents as selectedThemeComponents } from "@g5-theme/components";
import { themeConfig as selectedThemeConfig } from "@g5-theme/theme.config";
import { G5_THEME_API_VERSION, type G5ThemeComponentSlots, type G5ThemeConfig } from "@/lib/theme-types";

// "@g5-theme/*" 는 빌드가 고른 테마 소스(nextjs/themes/<G5_THEME_SOURCE>)로 이어진다 — next.config.ts.
function validateThemeConfig(config: G5ThemeConfig): G5ThemeConfig {
  if (config.apiVersion !== G5_THEME_API_VERSION) {
    throw new Error(
      `[theme] Unsupported theme API version ${config.apiVersion}. Expected ${G5_THEME_API_VERSION}.`
    );
  }
  return config;
}

export const themeConfig = validateThemeConfig(selectedThemeConfig);
export const themeComponents: G5ThemeComponentSlots = selectedThemeComponents;

export type {
  G5ThemeComponentProps,
  G5ThemeComponentSlots,
  G5ThemeConfig,
  G5ThemeLayoutShellProps,
} from "@/lib/theme-types";
