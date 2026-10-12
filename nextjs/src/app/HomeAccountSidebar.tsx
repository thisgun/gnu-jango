"use client";

import { ChevronRight, CircleUserRound, MessageSquareText } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { useAuthStore } from "@/store/auth";
import type { HomePost } from "./HomeCommunityHighlights";

export function HomeAccountSidebar({ latestPosts }: { latestPosts: HomePost[] }) {
  const user = useAuthStore((state) => state.user);

  return (
    <aside className="g5-home-sidebar" aria-label="회원 정보와 바로가기">
      <section className="card border border-base-300 bg-base-100 shadow-sm">
        <div className="card-body gap-3 p-4">
          <div className="flex items-center gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-blue-50 text-blue-700">
              <CircleUserRound aria-hidden="true" className="size-5" />
            </span>
            <div className="min-w-0">
              <h2 className="truncate text-sm font-extrabold text-base-content">
                {user ? `${user.mb_nick || user.mb_id}님, 반갑습니다` : "그누보드 커뮤니티"}
              </h2>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {user ? `보유 포인트 ${Number(user.mb_point).toLocaleString("ko-KR")}P` : "로그인하고 커뮤니티에 참여해 보세요."}
              </p>
            </div>
          </div>
          <div className="card-actions grid grid-cols-2">
            {user ? (
              <>
                <Link href="/mypage" className="btn btn-primary btn-sm">마이페이지</Link>
                <Link href="/boards" className="btn btn-outline btn-sm">글 둘러보기</Link>
              </>
            ) : (
              <>
                <Link href="/login" className="btn btn-primary btn-sm">로그인</Link>
                <Link href="/register" className="btn btn-outline btn-sm">회원가입</Link>
              </>
            )}
          </div>
        </div>
      </section>

      <section className="home-panel overflow-hidden" aria-labelledby="home-quick-links">
        <div className="section-header">
          <h2 id="home-quick-links" className="section-title">바로가기</h2>
        </div>
        <ul className="menu menu-sm w-full gap-0 p-2">
          <li><Link href="/boards" className="g5-sidebar-link">전체 게시판<ChevronRight aria-hidden="true" className="size-4" /></Link></li>
          <li><Link href="/recent" className="g5-sidebar-link">최신글<ChevronRight aria-hidden="true" className="size-4" /></Link></li>
          <li><Link href="/faq" className="g5-sidebar-link">자주 묻는 질문<ChevronRight aria-hidden="true" className="size-4" /></Link></li>
          <li><Link href="/shop" className="g5-sidebar-link">쇼핑몰<ChevronRight aria-hidden="true" className="size-4" /></Link></li>
        </ul>
      </section>

      <section className="home-panel overflow-hidden" aria-labelledby="home-sidebar-latest">
        <div className="section-header">
          <div className="flex items-center gap-2">
            <MessageSquareText aria-hidden="true" className="size-4 text-primary" />
            <h2 id="home-sidebar-latest" className="section-title">최근 게시글</h2>
          </div>
          <Link href="/recent" className="section-more">더보기<ChevronRight aria-hidden="true" className="size-3.5" /></Link>
        </div>
        {latestPosts.length > 0 ? (
          <ul className="divide-y divide-[#edf0f4] px-4">
            {latestPosts.slice(0, 5).map((post) => (
              <li key={`${post.bo_table}-${post.wr_id}`}>
                <Link href={post.href} className="block py-3">
                  <span className="block truncate text-sm font-semibold text-base-content hover:text-primary">{post.wr_subject}</span>
                  <span className="mt-1 block truncate text-xs text-muted-foreground">{post.boardSubject} · {post.mb_nick || post.wr_name || "작성자"}</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-4 py-5 text-sm text-muted-foreground">표시할 게시글이 없습니다.</p>
        )}
      </section>
    </aside>
  );
}
