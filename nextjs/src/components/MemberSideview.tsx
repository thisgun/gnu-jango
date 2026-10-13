"use client";

import { G5Link as Link } from "@/components/ui/g5-link";
import Image from "next/image";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useAuthStore } from "@/store/auth";
import { cn } from "@/lib/utils";
import { shouldBypassImageOptimization } from "@/lib/image";

export interface MemberSideviewProps {
  /** g5_member.mb_id. 비회원이면 비어 있거나 undefined 입니다. */
  mbId?: string | null;
  /** 화면에 표시할 회원 이름 또는 닉네임입니다. */
  name: string;
  /** 메일보내기 메뉴를 노출할 이메일입니다. */
  email?: string | null;
  /** 홈페이지 메뉴를 노출할 URL입니다. */
  homepage?: string | null;
  /** 회원 아이콘 URL입니다. */
  iconUrl?: string | null;
  /** 작성자 검색 메뉴를 현재 게시판으로 제한할 때 사용합니다. */
  boTable?: string | null;
  className?: string;
}

const ICON_SIZE = 20;

export function MemberSideview({
  mbId,
  name,
  email,
  homepage,
  iconUrl,
  boTable,
  className,
}: MemberSideviewProps) {
  const currentUser = useAuthStore((s) => s.user);
  const isSuperAdmin = !!currentUser?.is_super_admin;

  if (!mbId) {
    if (boTable && name) {
      return (
        <Link
          href={`/search?bo_table=${encodeURIComponent(boTable)}&sfl=wr_name&stx=${encodeURIComponent(name)}`}
          className={cn("hover:underline", className)}
          rel="nofollow"
        >
          {name}
        </Link>
      );
    }
    return <span className={className}>{name}</span>;
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-1 rounded hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
          aria-label={`${name} 회원 메뉴 열기`}
        >
          {iconUrl ? (
            <Image
              src={iconUrl}
              alt=""
              width={ICON_SIZE}
              height={ICON_SIZE}
              className="rounded-full"
              unoptimized={shouldBypassImageOptimization(iconUrl)}
            />
          ) : (
            <span
              aria-hidden="true"
              className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary"
            >
              {Array.from(name.trim())[0]?.toLocaleUpperCase("ko-KR") || "?"}
            </span>
          )}
          <span>{name}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-44 p-1" align="start">
        <ul className="text-sm">
          <SideviewItem href={`/mypage/memos/new?recv=${encodeURIComponent(mbId)}`}>
            쪽지보내기
          </SideviewItem>

          {email ? (
            <SideviewItem href={`mailto:${email}`} external>
              메일보내기
            </SideviewItem>
          ) : null}

          {homepage ? (
            <SideviewItem href={ensureHttp(homepage)} external>
              홈페이지
            </SideviewItem>
          ) : null}

          <SideviewItem href={`/members/${encodeURIComponent(mbId)}`}>
            자기소개
          </SideviewItem>

          {boTable ? (
            <SideviewItem
              href={`/search?bo_table=${encodeURIComponent(boTable)}&sfl=mb_id&stx=${encodeURIComponent(mbId)}`}
            >
              아이디로 검색
            </SideviewItem>
          ) : null}

          <SideviewItem href={`/recent?mb_id=${encodeURIComponent(mbId)}`}>
            전체게시물
          </SideviewItem>

          {isSuperAdmin ? (
            <>
              <li className="my-1 border-t" aria-hidden />
              <SideviewItem
                href={`/admin/auth/user/?q=${encodeURIComponent(mbId)}`}
                external
              >
                회원정보변경
              </SideviewItem>
              <SideviewItem
                href={`/admin/users/user_point/?q=${encodeURIComponent(mbId)}`}
                external
              >
                포인트내역
              </SideviewItem>
            </>
          ) : null}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

function SideviewItem({
  href,
  external,
  children,
}: {
  href: string;
  external?: boolean;
  children: React.ReactNode;
}) {
  if (external) {
    return (
      <li>
        <a
          href={href}
          target="_blank"
          rel="noopener nofollow"
          className="block rounded px-2 py-1.5 hover:bg-accent hover:text-accent-foreground"
        >
          {children}
        </a>
      </li>
    );
  }

  return (
    <li>
      <Link
        href={href}
        className="block rounded px-2 py-1.5 hover:bg-accent hover:text-accent-foreground"
      >
        {children}
      </Link>
    </li>
  );
}

function ensureHttp(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  return `http://${url}`;
}
