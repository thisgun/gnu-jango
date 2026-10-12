import type { MetadataRoute } from 'next';
import { APP_BASE_URL } from '@/lib/config';

export const dynamic = 'force-static';

/**
 * PWA manifest — Next 13+ metadata route. 이전엔 public/manifest.json 정적 파일을
 * 사용했지만 manifest.ts 로 옮기면 metadata API 와 통합되고 환경 변수로 동적 조정 가능.
 *
 * 기존 public/manifest.json 은 그대로 둬도 무방하지만 빌드 시 /manifest.webmanifest
 * 가 자동 송출되며 metadata 의 manifest 필드도 자동 연결됨.
 */
export default function manifest(): MetadataRoute.Manifest {
  const basePath = new URL(APP_BASE_URL).pathname.replace(/\/+$/, '');
  const scope = `${basePath}/` || '/';
  const publicPath = (path: string) => `${basePath}${path}`;

  return {
    name: '그누보드5 커뮤니티',
    short_name: '그누보드5',
    description: '그누보드5 커뮤니티 & 쇼핑몰',
    start_url: scope,
    scope,
    display: 'standalone',
    background_color: '#ffffff',
    theme_color: '#2563eb',
    orientation: 'portrait',
    icons: [
      { src: publicPath('/icon-192.png'), sizes: '192x192', type: 'image/png', purpose: 'maskable' },
      { src: publicPath('/icon-512.png'), sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  };
}
