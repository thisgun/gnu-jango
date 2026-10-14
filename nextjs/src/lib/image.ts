/**
 * next/image 의 이미지 최적화를 건너뛸지 결정.
 *
 * 사용자 게시글 본문/썸네일은 임의 외부 호스트 이미지를 포함할 수 있어
 * remotePatterns 에 명시 안 된 도메인이면 throw. 그런 src 들은 unoptimized
 * 로 raw <img> 처럼 렌더해 표시는 보존하면서, 우리 서버를 통한 SSRF 경로는
 * 안 거치도록.
 *
 * 신뢰 호스트 (운영 도메인, 소셜 CDN) 만 최적화 통과시키고, 나머지는 우회.
 * 이 리스트는 next.config.ts 의 ALLOWED_IMAGE_HOSTS 와 의도적으로 같이 관리.
 */
function siteHost(): string | undefined {
  try {
    return process.env.NEXT_PUBLIC_APP_URL ? new URL(process.env.NEXT_PUBLIC_APP_URL).hostname : undefined;
  } catch {
    return undefined;
  }
}

const SITE_HOST = siteHost();

const TRUSTED_HOSTS = new Set<string>([
  // 운영 도메인은 배포마다 NEXT_PUBLIC_APP_URL 로 지정 / dev
  ...(SITE_HOST ? [SITE_HOST] : []),
  'localhost',
  // 소셜 로그인 프로필 CDN
  'graph.facebook.com',
  'lh3.googleusercontent.com',
  'k.kakaocdn.net',
  'phinf.pstatic.net',
]);

export function shouldBypassImageOptimization(src: string | null | undefined): boolean {
  if (!src) return true;
  // data: / blob: / svg → next/image 가 어차피 최적화 불가능.
  if (/^(data|blob):/i.test(src) || /\.svg(?:[?#].*)?$/i.test(src)) return true;
  // Django 가 이미 줄여 보낸 사본(목록 썸네일) — 다시 최적화할 필요가 없다.
  if (/^(?:https?:\/\/[^/]+)?\/api\/v1\/thumbs\//i.test(src)) return true;

  // 상대 경로 / 프로토콜 상대 경로는 우리 도메인 — 최적화 통과.
  if (src.startsWith('/') && !src.startsWith('//')) return false;

  try {
    const url = new URL(src);
    // 127.x 대역은 dev 환경 — 통과.
    if (url.hostname.startsWith('127.')) return false;
    // http 는 모두 우회 (운영은 https 만).
    if (url.protocol === 'http:') return true;
    // 신뢰 호스트가 아니면 우회 — remotePatterns 에 없어도 throw 안 함.
    return !TRUSTED_HOSTS.has(url.hostname);
  } catch {
    // URL 파싱 실패 — 깨진 src. 우회 (raw img 도 빈 이미지로 깨질 것).
    return true;
  }
}
