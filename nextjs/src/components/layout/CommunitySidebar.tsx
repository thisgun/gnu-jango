"use client";

import { type CSSProperties, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { ChevronRight, Search, UserRound } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { LoginForm } from "@/components/auth/LoginForm";
import { boardPostHref, type BbsRewriteMode } from "@/lib/board-url";
import { g5BaseUrlForRuntime } from "@/lib/config";
import type { PopularKeyword } from "@/lib/schemas";
import type { RecentItem } from "@/lib/types";
import { formatDate, formatNumber, truncate } from "@/lib/utils";
import { getPopularKeywords } from "@/services/search";
import { getRecentItems } from "@/services/recent";
import { getClientPublicSettings } from "@/services/settings";
import { useAuthStore } from "@/store/auth";

const SOCIAL_LOGO_FILES = {
  naver: "sns_naver_s.png",
  kakao: "sns_kakao_s.png",
  facebook: "sns_fb_s.png",
  google: "sns_gp_s.png",
  twitter: "sns_twitter_s.png",
  payco: "sns_payco_s.png",
} as const;

function socialLogoVars(): CSSProperties {
  const vars: Record<string, string> = {};
  for (const [name, file] of Object.entries(SOCIAL_LOGO_FILES)) {
    vars[`--solune-sns-${name}`] = `url("${g5BaseUrlForRuntime()}/skin/social/img/${file}")`;
  }
  return vars as CSSProperties;
}

function LoginWidget() {
  const { isInitialized, user, logout } = useAuthStore();
  const pathname = usePathname();
  return (
    <section
      className="card border border-base-300 bg-base-100 shadow-sm solune-sidebar-widget solune-login-card"
      aria-label={user ? "회원 정보" : "회원 로그인"}
      style={socialLogoVars()}
    >
      <div className="card-body">
        {user ? (
          <>
            <div className="solune-member-head">
              <span className="solune-member-avatar" aria-hidden="true"><UserRound size={20} /></span>
              <div className="min-w-0">
                <strong>{user.mb_nick || user.mb_name || user.mb_id}님</strong>
                <span>{user.is_super_admin ? "최고관리자" : `레벨 ${user.mb_level}`}</span>
              </div>
            </div>
            <dl className="solune-member-stats"><div><dt>포인트</dt><dd>{formatNumber(Number(user.mb_point) || 0)}P</dd></div></dl>
            <div className="solune-member-actions">
              {user.is_super_admin ? <a className="solune-member-admin" href="/admin/">관리자</a> : null}
              <Link href="/mypage">마이페이지</Link>
              <button type="button" onClick={() => void logout()}>로그아웃</button>
            </div>
          </>
        ) : (
          <>
            <h2 className="solune-login-title">로그인</h2>
            <LoginForm redirectAfterLogin={pathname || "/"} variant="compact" />
            {!isInitialized ? <span className="sr-only" role="status">로그인 상태 확인 중</span> : null}
          </>
        )}
      </div>
    </section>
  );
}

function CommentsWidget({ comments, rewriteMode }: { comments: RecentItem[]; rewriteMode: BbsRewriteMode }) {
  return (
    <section className="card border border-base-300 bg-base-100 shadow-sm solune-sidebar-widget solune-comment-widget" aria-labelledby="board-comments-title">
      <header className="solune-sidebar-widget-head">
        <h2 id="board-comments-title">최근 댓글</h2>
        <Link href="/recent?view=c" className="solune-sidebar-head-link">전체 <ChevronRight size={12} aria-hidden="true" /></Link>
      </header>
      <div className="solune-sidebar-widget-body">
        {comments.length ? (
          <ul className="solune-comment-list">
            {comments.slice(0, 6).map((comment) => (
              <li key={comment.bn_id}>
                <div className="solune-comment-link">
                  <Link
                    href={comment.is_comment && comment.wr_parent
                      ? `${boardPostHref(comment.bo_table, { wr_id: comment.wr_parent, wr_seo_title: comment.wr_seo_title }, rewriteMode)}#c_${comment.bn_id}`
                      : boardPostHref(comment.bo_table, comment, rewriteMode)}
                    className="solune-comment-excerpt"
                  >{truncate(comment.comment_excerpt || comment.wr_subject || "내용 없음", 46)}</Link>
                  <span className="solune-comment-meta">
                    <span className="solune-comment-board">{comment.bo_subject}</span>
                    <span className="solune-comment-name">{comment.wr_name || comment.mb_id}</span>
                    <time dateTime={comment.wr_datetime}>{formatDate(comment.wr_datetime)}</time>
                  </span>
                </div>
              </li>
            ))}
          </ul>
        ) : <p className="solune-empty">최근 댓글이 없습니다.</p>}
      </div>
    </section>
  );
}

function PopularWidget({ keywords }: { keywords: PopularKeyword[] }) {
  return (
    <section className="card border border-base-300 bg-base-100 shadow-sm solune-sidebar-widget solune-popular-widget" aria-labelledby="board-popular-title">
      <header className="solune-sidebar-widget-head">
        <h2 id="board-popular-title">인기검색어</h2>
        <Link href="/search" className="solune-sidebar-head-link" aria-label="통합 검색"><Search size={12} aria-hidden="true" /><span>검색</span></Link>
      </header>
      <div className="solune-sidebar-widget-body">
        {keywords.length ? (
          <ol className="solune-popular-list">
            {keywords.slice(0, 5).map((keyword, index) => (
              <li key={keyword.pp_word}>
                <Link href={`/search?q=${encodeURIComponent(keyword.pp_word)}`} className="solune-popular-item">
                  <span className="solune-popular-rank">{String(index + 1).padStart(2, "0")}</span>
                  <span className="solune-popular-word">{keyword.pp_word}</span>
                  <ChevronRight size={13} className="solune-popular-caret" aria-hidden="true" />
                </Link>
              </li>
            ))}
          </ol>
        ) : <p className="solune-empty">인기 검색어가 없습니다.</p>}
      </div>
    </section>
  );
}

export function CommunitySidebar({ rewriteMode }: { rewriteMode?: BbsRewriteMode }) {
  const [comments, setComments] = useState<RecentItem[]>([]);
  const [keywords, setKeywords] = useState<PopularKeyword[]>([]);
  const [settingsRewriteMode, setSettingsRewriteMode] = useState<BbsRewriteMode>(0);

  // 레이아웃이 레일을 그릴 때는 주소 방식(cf_bbs_rewrite)을 넘겨줄 페이지가 없으니 설정에서 읽는다.
  useEffect(() => {
    if (rewriteMode !== undefined) return;
    let active = true;
    getClientPublicSettings()
      .then((settings) => {
        if (active) setSettingsRewriteMode(Number(settings.cf_bbs_rewrite ?? 0) as BbsRewriteMode);
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, [rewriteMode]);

  useEffect(() => {
    let active = true;
    Promise.all([
      getRecentItems({ view: "c", limit: 6 }),
      getPopularKeywords(5),
    ])
      .then(([recent, popular]) => {
        if (!active) return;
        setComments(recent.items);
        setKeywords(popular);
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, []);

  return (
    <aside className="solune-sidebar" aria-label="커뮤니티 위젯">
      <LoginWidget />
      <CommentsWidget comments={comments} rewriteMode={rewriteMode ?? settingsRewriteMode} />
      <PopularWidget keywords={keywords} />
    </aside>
  );
}
