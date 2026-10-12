/**
 * Page-level metadata 빌더.
 *
 * 사용 예:
 *   export async function generateMetadata({ params }): Promise<Metadata> {
 *     const post = await getPost(params.bo_table, params.wr_id);
 *     return buildPageMetadata({
 *       title: post.wr_subject,
 *       description: post.summary,
 *       path: `/boards/${params.bo_table}/${params.wr_id}`,
 *       image: post.thumbnail,
 *     });
 *   }
 *
 * - root layout 의 metadata 가 정의한 openGraph / twitter / metadataBase 를 자동 상속.
 * - title 은 root template ("%s — 사이트명") 에 의해 합성됨.
 */
import type { Metadata } from 'next';
import { APP_BASE_URL } from '@/lib/config';
import { toG5ShortPath } from '@/lib/g5-short-url';

export interface PageMetaInput {
  title: string;
  description?: string;
  /** 절대 또는 상대 경로 ("/boards/free/123"). canonical + og:url 에 사용. */
  path?: string;
  /** 절대 URL 권장. data:/blob: 는 무시. */
  image?: string | null;
  /** 검색 인덱스 노출 안 할 페이지 (마이페이지, 임시 페이지 등) */
  noindex?: boolean;
  /** OG type — 글이면 'article' 권장, 기본 'website' */
  type?: 'website' | 'article';
}

function safeAbsUrl(input: string | null | undefined): string | undefined {
  if (!input) return undefined;
  if (/^(data|blob):/i.test(input)) return undefined;
  if (input.startsWith('http://') || input.startsWith('https://')) return input;
  // 상대 경로 — APP_BASE_URL 과 합쳐 절대화
  try {
    return new URL(input, APP_BASE_URL).toString();
  } catch {
    return undefined;
  }
}

export function buildPageMetadata(input: PageMetaInput): Metadata {
  const url = input.path ? safeAbsUrl(toG5ShortPath(input.path)) : undefined;
  const image = safeAbsUrl(input.image ?? '/og-default.png');

  const og: NonNullable<Metadata['openGraph']> = {
    type: input.type ?? 'website',
    title: input.title,
    ...(input.description ? { description: input.description } : {}),
    ...(url ? { url } : {}),
    ...(image ? { images: [{ url: image, alt: input.title }] } : {}),
  };

  const twitter: NonNullable<Metadata['twitter']> = {
    card: 'summary_large_image',
    title: input.title,
    ...(input.description ? { description: input.description } : {}),
    ...(image ? { images: [image] } : {}),
  };

  return {
    title: input.title,
    ...(input.description ? { description: input.description } : {}),
    ...(url ? { alternates: { canonical: url } } : {}),
    openGraph: og,
    twitter,
    ...(input.noindex ? { robots: { index: false, follow: false } } : {}),
  };
}
