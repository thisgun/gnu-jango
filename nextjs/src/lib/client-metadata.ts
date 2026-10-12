"use client";

import { g5ShortHref } from "@/lib/g5-short-url";

const DEFAULT_SITE_NAME = "그누보드5";

const HTML_ENTITIES: Record<string, string> = {
  amp: "&",
  apos: "'",
  bull: "•",
  copy: "©",
  gt: ">",
  hellip: "…",
  ldquo: "“",
  lsquo: "‘",
  lt: "<",
  mdash: "—",
  middot: "·",
  nbsp: " ",
  ndash: "–",
  quot: '"',
  reg: "®",
  rdquo: "”",
  rsquo: "’",
  trade: "™",
};

function decodeHtmlEntities(value: string): string {
  return value.replace(/&(#x[\da-f]+|#\d+|[a-z][a-z\d]+);/gi, (entity, code: string) => {
    if (code.startsWith("#")) {
      const codePoint = code[1]?.toLowerCase() === "x"
        ? Number.parseInt(code.slice(2), 16)
        : Number.parseInt(code.slice(1), 10);
      if (Number.isInteger(codePoint) && codePoint >= 0 && codePoint <= 0x10ffff) {
        return String.fromCodePoint(codePoint);
      }
      return entity;
    }
    return HTML_ENTITIES[code.toLowerCase()] ?? entity;
  });
}

export function htmlToPlainText(value: string | null | undefined): string {
  let text = (value ?? "")
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ");

  // Some imported reviews contain double-escaped entities such as &amp;nbsp;.
  text = decodeHtmlEntities(decodeHtmlEntities(text));
  return text.replace(/\s+/g, " ").trim();
}

export function plainTextSummary(value: string | null | undefined, fallback: string): string {
  const text = htmlToPlainText(value);

  return (text || fallback).slice(0, 160);
}

export function clientAbsoluteUrl(value: string): string | undefined {
  if (/^(data|blob):/i.test(value)) return undefined;

  try {
    return new URL(value, window.location.origin).toString();
  } catch {
    return undefined;
  }
}

export function applyClientJsonLd(id: string, payload: object | object[] | null) {
  if (typeof window === "undefined") return;

  const existing = Array.from(
    document.head.querySelectorAll<HTMLScriptElement>(
      'script[type="application/ld+json"][data-g5-json-ld]'
    )
  ).find((script) => script.dataset.g5JsonLd === id);

  if (!payload) {
    existing?.remove();
    return;
  }

  const script = existing ?? document.createElement("script");
  script.type = "application/ld+json";
  script.dataset.g5JsonLd = id;
  script.textContent = JSON.stringify(payload).replace(/</g, "\\u003c");

  if (!existing) document.head.appendChild(script);
}

function upsertMeta(
  selector: string,
  configure: (meta: HTMLMetaElement) => void,
  content: string
) {
  const existing = document.head.querySelector<HTMLMetaElement>(selector);
  const meta = existing ?? document.createElement("meta");
  configure(meta);
  meta.setAttribute("content", content);
  if (!existing) document.head.appendChild(meta);
}

function upsertCanonical(href: string) {
  const existing = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  const link = existing ?? document.createElement("link");
  link.setAttribute("rel", "canonical");
  link.setAttribute("href", href);
  if (!existing) document.head.appendChild(link);
}

export function applyClientPageMetadata(input: {
  title: string;
  description?: string | null;
  path: string;
  image?: string | null;
  siteName?: string;
}) {
  if (typeof window === "undefined") return;

  const siteName = input.siteName ?? DEFAULT_SITE_NAME;
  const title = input.title.endsWith(` — ${siteName}`)
    ? input.title
    : `${input.title} — ${siteName}`;
  const description = plainTextSummary(input.description, input.title);
  const canonical = new URL(g5ShortHref(input.path), window.location.origin).toString();

  document.title = title;
  upsertCanonical(canonical);
  upsertMeta('meta[name="description"]', (meta) => {
    meta.setAttribute("name", "description");
  }, description);
  upsertMeta('meta[property="og:title"]', (meta) => {
    meta.setAttribute("property", "og:title");
  }, title);
  upsertMeta('meta[property="og:description"]', (meta) => {
    meta.setAttribute("property", "og:description");
  }, description);
  upsertMeta('meta[property="og:url"]', (meta) => {
    meta.setAttribute("property", "og:url");
  }, canonical);
  upsertMeta('meta[name="twitter:title"]', (meta) => {
    meta.setAttribute("name", "twitter:title");
  }, title);
  upsertMeta('meta[name="twitter:description"]', (meta) => {
    meta.setAttribute("name", "twitter:description");
  }, description);

  const image = input.image ? clientAbsoluteUrl(input.image) : undefined;
  if (!image) return;

  upsertMeta('meta[property="og:image"]', (meta) => {
    meta.setAttribute("property", "og:image");
  }, image);
  upsertMeta('meta[name="twitter:image"]', (meta) => {
    meta.setAttribute("name", "twitter:image");
  }, image);
}
