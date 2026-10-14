import "./theme.css";
import type { G5ThemeComponentSlots } from "@/lib/theme-types";
import { HandbookServerLayoutShell } from "./layout-shell.server";
import { HandbookHomePage } from "./home";
import { HandbookBoardViewHeader } from "./board-view-header";

export const themeComponents = {
  LayoutShell: HandbookServerLayoutShell,
  BoardViewHeader: HandbookBoardViewHeader,
  HomePage: HandbookHomePage,
} satisfies G5ThemeComponentSlots;
