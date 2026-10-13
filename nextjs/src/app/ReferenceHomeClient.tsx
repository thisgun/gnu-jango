"use client";

import { type CSSProperties, useEffect, useState } from "react";
import { ArrowRight, ChevronDown, ChevronRight, Search, UserRound } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { LoginForm } from "@/components/auth/LoginForm";
import { GalleryThumbnail } from "@/app/boards/[bo_table]/GalleryThumbnail";
import { ApiError } from "@/lib/api";
import { boardListHref, boardPostHref } from "@/lib/board-url";
import { g5BaseUrlForRuntime } from "@/lib/config";
import { formatDate, formatNumber, truncate } from "@/lib/utils";
import { sanitizeCommerceHtml, sanitizeInlineHtml } from "@/lib/sanitize";
import type { PopularKeyword, VisitStats } from "@/lib/schemas";
import type { FaqItem, Poll, RecentItem } from "@/lib/types";
import { votePoll } from "@/services/polls";
import { useAuthStore } from "@/store/auth";
import { loadReferenceHomeData, type ReferenceHomeData } from "./reference-home-data";

function plainFaqSubject(value: string): string {
  const sanitized = sanitizeInlineHtml(value);
  return sanitized.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

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

function BoardPanel({
  board,
  posts,
  rewriteMode,
}: ReferenceHomeData["boardPanels"][number] & { rewriteMode: ReferenceHomeData["rewriteMode"] }) {
  const table = board.bo_table;
  return (
    <section className="card border border-base-300 bg-base-100 shadow-sm solune-reference-panel" aria-labelledby={`home-board-${table}`}>
      <div className="solune-panel-head">
        <h2 id={`home-board-${table}`} className="solune-panel-title">{board.bo_subject || table}</h2>
        <Link href={boardListHref(table)} className="solune-panel-more">
          <span className="sr-only">{board.bo_subject || table} </span>더보기
          <ArrowRight size={14} strokeWidth={2.6} aria-hidden="true" />
        </Link>
      </div>
      <div className="solune-panel-body">
        {posts.length > 0 ? (
          <ul className="solune-latest-list">
            {posts.map((post) => (
              <li className="solune-latest-row" key={`${table}-${post.wr_id}`}>
                <Link href={boardPostHref(table, post, rewriteMode)} className="solune-latest-subject">
                  {post.is_secret ? <span className="badge badge-ghost badge-xs solune-latest-badge">비밀</span> : null}
                  <span className="solune-latest-text">{truncate(post.wr_subject || "제목 없음", 60)}</span>
                  {Number(post.wr_comment) > 0 ? (
                    <span className="solune-latest-comment">{formatNumber(Number(post.wr_comment))}</span>
                  ) : null}
                </Link>
                <span className="solune-latest-meta">
                  <span className="solune-latest-author">
                    <span className="solune-author-photo" aria-hidden="true"><UserRound /></span>
                    <span className="solune-author-name">{post.mb_nick || post.wr_name || "작성자"}</span>
                  </span>
                  <time dateTime={post.wr_datetime}>{formatDate(post.wr_datetime)}</time>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="solune-empty">아직 등록된 글이 없습니다.</p>
        )}
      </div>
    </section>
  );
}

function FaqPanel({ faqs }: { faqs: FaqItem[] }) {
  return (
    <section className="card border border-base-300 bg-base-100 shadow-sm solune-reference-panel solune-faq-panel" aria-labelledby="home-faq-heading">
      <div className="solune-panel-head">
        <h2 id="home-faq-heading" className="solune-panel-title">자주 묻는 질문</h2>
        <Link href="/faq" className="solune-panel-more">더보기 <ArrowRight size={13} aria-hidden="true" /></Link>
      </div>
      {faqs.length > 0 ? (
        <div className="solune-faq-list">
          {faqs.map((faq, index) => (
            <details key={faq.fa_id} name="home-faq" className="solune-faq-item" open={index === 0}>
              <summary className="solune-faq-q">
                <span className="badge badge-primary badge-soft badge-sm solune-faq-badge" aria-hidden="true">Q</span>
                <span className="solune-faq-subject" dangerouslySetInnerHTML={{ __html: plainFaqSubject(faq.fa_subject) }} />
                <ChevronDown size={15} className="solune-faq-chevron" aria-hidden="true" />
              </summary>
              <div className="solune-faq-a" dangerouslySetInnerHTML={{ __html: sanitizeCommerceHtml(faq.fa_content) }} />
            </details>
          ))}
        </div>
      ) : (
        <div className="solune-panel-body"><p className="solune-empty">등록된 FAQ가 없습니다.</p></div>
      )}
    </section>
  );
}

function GalleryPanel({ data, rewriteMode }: { data: NonNullable<ReferenceHomeData["gallery"]>; rewriteMode: ReferenceHomeData["rewriteMode"] }) {
  return (
    <section className="card border border-base-300 bg-base-100 shadow-sm solune-reference-panel solune-gallery-panel" aria-labelledby="home-gallery-heading">
      <div className="solune-panel-head">
        <h2 id="home-gallery-heading" className="solune-panel-title">{data.board.bo_subject || "갤러리"}</h2>
        <Link href={boardListHref(data.board.bo_table)} className="solune-panel-more">
          더보기 <ArrowRight size={14} strokeWidth={2.6} aria-hidden="true" />
        </Link>
      </div>
      <div className="solune-panel-body">
        {data.posts.length > 0 ? <ul className="solune-gallery-grid">
          {data.posts.slice(0, 8).map((post, index) => {
            const image = post.thumbnail || post.images?.[0] || "";
            return (
              <li className="solune-gallery-item" key={`${data.board.bo_table}-${post.wr_id}`}>
                <Link href={boardPostHref(data.board.bo_table, post, rewriteMode)} className="solune-gallery-link">
                  <span className="solune-gallery-thumb">
                    <GalleryThumbnail src={image} alt={post.wr_subject || "갤러리 사진"} sizes="(max-width: 640px) 45vw, (max-width: 1024px) 30vw, 210px" priority={index < 4} />
                  </span>
                  <span className="solune-gallery-subject">
                    {truncate(post.wr_subject || "제목 없음", 60)}
                    {Number(post.wr_comment) > 0 ? <span className="solune-gallery-comment">{formatNumber(Number(post.wr_comment))}</span> : null}
                  </span>
                </Link>
                <span className="solune-gallery-meta">
                  <span className="solune-gallery-writer">{post.mb_nick || post.wr_name || "작성자"}</span>
                  <time dateTime={post.wr_datetime}>{formatDate(post.wr_datetime)}</time>
                </span>
              </li>
            );
          })}
        </ul> : <p className="solune-empty">등록된 갤러리 게시물이 없습니다.</p>}
      </div>
    </section>
  );
}

function LoginWidget() {
  const { isInitialized, user, logout } = useAuthStore();
  return (
    <section className="card border border-base-300 bg-base-100 shadow-sm solune-sidebar-widget solune-login-card" aria-label={user ? "회원 정보" : "회원 로그인"} style={socialLogoVars()}>
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
            <LoginForm redirectAfterLogin="/" variant="compact" />
            {!isInitialized ? <span className="sr-only" role="status">로그인 상태 확인 중</span> : null}
          </>
        )}
      </div>
    </section>
  );
}

function CommentsWidget({ comments, rewriteMode }: { comments: RecentItem[]; rewriteMode: ReferenceHomeData["rewriteMode"] }) {
  return (
    <section className="card border border-base-300 bg-base-100 shadow-sm solune-sidebar-widget solune-comment-widget" aria-labelledby="home-comments-title">
      <header className="solune-sidebar-widget-head">
        <h2 id="home-comments-title">최근 댓글</h2>
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
        ) : <p className="solune-empty">아직 등록된 댓글이 없습니다.</p>}
      </div>
    </section>
  );
}

function PopularWidget({ keywords }: { keywords: PopularKeyword[] }) {
  return (
    <section className="card border border-base-300 bg-base-100 shadow-sm solune-sidebar-widget solune-popular-widget" aria-labelledby="home-popular-title">
      <header className="solune-sidebar-widget-head">
        <h2 id="home-popular-title">인기검색어</h2>
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
        ) : <p className="solune-empty">최근 검색 기록이 없습니다.</p>}
      </div>
    </section>
  );
}

function PollWidget({ initialPoll }: { initialPoll: Poll }) {
  const [poll, setPoll] = useState(initialPoll);
  const [selected, setSelected] = useState<number | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => setPoll(initialPoll), [initialPoll]);

  async function submitVote() {
    if (selected === null) return setError("투표할 항목을 선택해 주세요.");
    if (!poll.can_vote) return setError("로그인 후 투표할 수 있습니다.");
    setPending(true);
    setError("");
    try {
      setPoll(await votePoll(poll.po_id, selected));
      setSelected(null);
    } catch (cause) {
      setError(cause instanceof ApiError || cause instanceof Error ? cause.message : "투표를 처리하지 못했습니다.");
    } finally {
      setPending(false);
    }
  }

  const showResults = poll.has_voted || !poll.can_vote;
  return (
    <section className="card border border-base-300 bg-base-100 shadow-sm solune-sidebar-widget solune-poll-widget" aria-labelledby="home-poll-title">
      <header className="solune-sidebar-widget-head">
        <h2 id="home-poll-title">설문조사</h2>
        <Link href={`/polls?po_id=${poll.po_id}`} className="solune-sidebar-head-link">결과보기</Link>
      </header>
      <div className="solune-sidebar-widget-body">
        <p className="solune-poll-question">{poll.po_subject}</p>
        {showResults ? (
          <ul className="solune-poll-result">
            {poll.options.map((option) => (
              <li key={option.num}>
                <span className="solune-poll-result-head"><span>{option.content}</span><span>{option.count}표</span></span>
                <span className="solune-poll-bar"><span style={{ width: `${Math.max(0, Math.min(100, option.rate))}%` }} /></span>
              </li>
            ))}
          </ul>
        ) : (
          <>
            <ul className="solune-poll-options">
              {poll.options.map((option) => (
                <li key={option.num}>
                  <label className="solune-poll-option">
                    <input type="radio" name="home-poll" className="radio radio-primary radio-sm" checked={selected === option.num} onChange={() => { setSelected(option.num); setError(""); }} />
                    <span>{option.content}</span>
                  </label>
                </li>
              ))}
            </ul>
            <button type="button" className="btn btn-primary btn-block solune-poll-submit" disabled={pending} onClick={() => void submitVote()}>{pending ? "처리 중…" : "투표하기"}</button>
          </>
        )}
        {error ? <p className="solune-poll-error" role="alert">{error}</p> : null}
      </div>
    </section>
  );
}

function VisitWidget({ visit }: { visit: VisitStats | null }) {
  if (!visit) {
    return (
      <section className="card border border-base-300 bg-base-100 shadow-sm solune-sidebar-widget solune-visit-widget" aria-labelledby="home-visit-title">
        <header className="solune-sidebar-widget-head">
          <h2 id="home-visit-title">접속자집계</h2>
          <span className="solune-sidebar-status"><i aria-hidden="true" />실시간</span>
        </header>
        <div className="solune-sidebar-widget-body"><p className="solune-empty">방문 통계를 불러올 수 없습니다.</p></div>
      </section>
    );
  }
  const ratio = visit.max > 0 ? Math.round((visit.today / visit.max) * 100) : 0;
  return (
    <section className="card border border-base-300 bg-base-100 shadow-sm solune-sidebar-widget solune-visit-widget" aria-labelledby="home-visit-title">
      <header className="solune-sidebar-widget-head">
        <h2 id="home-visit-title">접속자집계</h2>
        <span className="solune-sidebar-status"><i aria-hidden="true" />실시간</span>
      </header>
      <div className="solune-sidebar-widget-body">
        <dl className="solune-visit-stats">
          <div className="solune-visit-lead"><dt>오늘</dt><dd><strong className="solune-visit-figure">{formatNumber(visit.today)}</strong></dd></div>
          <div className="solune-visit-peak"><dt>최대</dt><dd><span className="solune-visit-peak-value">{formatNumber(visit.max)}</span><span className="solune-visit-bar" role="img" aria-label={`오늘 접속자는 최고 기록 대비 ${ratio}%`}><span style={{ width: `${Math.min(100, ratio)}%` }} /></span><span className="solune-visit-caption">오늘은 최고 기록의 <b>{ratio}%</b></span></dd></div>
          <div className="solune-visit-cell"><dt>어제</dt><dd>{formatNumber(visit.yesterday)}</dd></div>
          <div className="solune-visit-cell"><dt>전체</dt><dd>{formatNumber(visit.total)}</dd></div>
        </dl>
      </div>
    </section>
  );
}

export function ReferenceHomeClient({ initialData }: { initialData: ReferenceHomeData }) {
  const [home, setHome] = useState(initialData);
  const [loaded, setLoaded] = useState(initialData.boardPanels.length > 0);

  useEffect(() => {
    let active = true;
    void loadReferenceHomeData()
      .then((data) => {
        if (active) setHome(data);
      })
      .catch((error: unknown) => console.error("[reference-home:refresh]", error))
      .finally(() => {
        if (active) setLoaded(true);
      });
    return () => { active = false; };
  }, []);

  return (
    <div className="solune-content-shell" aria-busy={!loaded}>
      <div className="solune-main-content">
        <h1 className="sr-only">그누보드5 커뮤니티</h1>
        <div className="solune-board-grid">
          {home.boardPanels.map((panel) => (
            <BoardPanel key={panel.board.bo_table} {...panel} rewriteMode={home.rewriteMode} />
          ))}
          {home.faqs.length > 0 ? <FaqPanel faqs={home.faqs} /> : null}
          {!loaded && home.boardPanels.length === 0
            ? Array.from({ length: 4 }, (_, index) => <section key={index} className="card border border-base-300 bg-base-100 shadow-sm solune-reference-panel skeleton solune-panel-skeleton" aria-hidden="true" />)
            : null}
        </div>
        {home.gallery ? <GalleryPanel data={home.gallery} rewriteMode={home.rewriteMode} /> : null}
      </div>
      <aside className="solune-sidebar" aria-label="커뮤니티 위젯">
        <LoginWidget />
        <CommentsWidget comments={home.comments} rewriteMode={home.rewriteMode} />
        <PopularWidget keywords={home.popularKeywords} />
        {home.poll ? <PollWidget initialPoll={home.poll} /> : null}
        <VisitWidget visit={home.visit} />
      </aside>
    </div>
  );
}
