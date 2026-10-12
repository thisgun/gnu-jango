"use client";

import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { boardListHref, boardPostHref } from "@/lib/board-url";
import type { PublicSettings } from "@/lib/schemas";
import type { Board, WritePost } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { getBoardPosts, getBoardsResult } from "@/services/boards";
import { getClientPublicSettings } from "@/services/settings";

type LoadState = "loading" | "ready" | "error";

export function ShopHomeSupport() {
  const [noticeBoard, setNoticeBoard] = useState<Board | null>(null);
  const [noticePosts, setNoticePosts] = useState<WritePost[]>([]);
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [noticeState, setNoticeState] = useState<LoadState>("loading");
  const [settingsState, setSettingsState] = useState<LoadState>("loading");
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let active = true;

    setNoticeState("loading");
    setSettingsState("loading");
    setNoticeBoard(null);
    setNoticePosts([]);
    setSettings(null);

    async function loadSupportInfo() {
      const [boardResult, settingsResult] = await Promise.allSettled([
        getBoardsResult(),
        getClientPublicSettings(),
      ]);
      if (!active) return;

      if (settingsResult.status === "fulfilled") {
        setSettings(settingsResult.value);
        setSettingsState("ready");
      } else {
        setSettingsState("error");
      }

      if (boardResult.status !== "fulfilled" || !boardResult.value.ok) {
        setNoticeState("error");
        return;
      }

      const notice = boardResult.value.data.find((board) => board.bo_table === "notice")
        ?? boardResult.value.data.find((board) => board.bo_subject.includes("공지"));
      setNoticeBoard(notice ?? null);
      if (!notice) {
        setNoticeState("ready");
        return;
      }

      const result = await getBoardPosts({ boTable: notice.bo_table, perPage: 3 });
      if (!active) return;
      if (result.error) {
        setNoticeState("error");
        return;
      }

      setNoticePosts(result.list.slice(0, 3));
      setNoticeState("ready");
    }

    void loadSupportInfo();
    return () => { active = false; };
  }, [retryKey]);

  const retryLoading = () => setRetryKey((current) => current + 1);

  const phone = String(settings?.de_admin_company_tel || settings?.cf_company_tel || "").trim();
  const telephoneHref = phone.replace(/[^\d+]/g, "");
  const bankEnabled = String(settings?.de_bank_use || "").trim() === "1";
  const bankAccounts = String(settings?.de_bank_account || "")
    .split(/\r?\n/)
    .map((account) => account.trim())
    .filter(Boolean);

  return (
    <section
      className="grid gap-8 border-t border-base-300 py-8 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)]"
      aria-label="쇼핑몰 안내"
    >
      <div className="min-w-0">
        <div className="flex items-center justify-between gap-3 border-b border-base-300 pb-3">
          <h2 className="text-lg font-bold text-base-content">공지사항</h2>
          <Link href={noticeBoard ? boardListHref(noticeBoard.bo_table) : "/boards"} className="section-more">
            전체 보기 <ChevronRight aria-hidden="true" className="size-4" />
          </Link>
        </div>
        {noticeState === "loading" ? (
          <p className="flex items-center gap-2 py-4 text-sm text-base-content/60" role="status" aria-live="polite">
            <span className="loading loading-spinner loading-xs" aria-hidden="true" />
            공지사항을 불러오는 중입니다.
          </p>
        ) : noticeState === "error" ? (
          <div className="alert alert-error mt-4 flex flex-col items-start gap-3 py-3 text-sm sm:alert-horizontal sm:items-center sm:justify-between">
            <span role="alert">공지사항을 불러오지 못했습니다. 잠시 후 다시 확인해 주세요.</span>
            <button type="button" className="btn btn-sm btn-ghost" onClick={retryLoading}>
              다시 시도
            </button>
          </div>
        ) : noticePosts.length > 0 ? (
          <ul className="divide-y divide-base-300">
            {noticePosts.map((post) => (
              <li key={post.wr_id}>
                <Link
                  href={boardPostHref(noticeBoard?.bo_table || "notice", post, settings?.cf_bbs_rewrite)}
                  className="flex min-h-11 items-center justify-between gap-3 py-2 text-sm text-base-content hover:text-primary"
                >
                  <span className="min-w-0 truncate">{post.wr_subject}</span>
                  <time className="shrink-0 text-xs text-base-content/60" dateTime={post.wr_datetime}>
                    {formatDate(post.wr_datetime)}
                  </time>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-4 text-sm text-base-content/60">
            {noticeBoard ? "등록된 공지사항이 없습니다." : "공지사항 게시판이 설정되지 않았습니다."}
          </p>
        )}
      </div>

      <div>
        <h2 className="border-b border-base-300 pb-3 text-lg font-bold text-base-content">고객센터</h2>
        {settingsState === "loading" ? (
          <p className="flex items-center gap-2 pt-4 text-sm text-base-content/60" role="status" aria-live="polite">
            <span className="loading loading-spinner loading-xs" aria-hidden="true" />
            안내 정보를 불러오는 중입니다.
          </p>
        ) : settingsState === "error" ? (
          <div className="flex flex-wrap items-center gap-3 pt-4">
            <p className="text-sm text-error" role="alert">고객센터 정보를 불러오지 못했습니다.</p>
            <button type="button" className="btn btn-sm btn-ghost" onClick={retryLoading}>
              다시 시도
            </button>
          </div>
        ) : phone ? (
          <a href={`tel:${telephoneHref}`} className="mt-4 inline-block text-2xl font-bold text-base-content hover:text-primary">
            {phone}
          </a>
        ) : (
          <p className="mt-4 text-sm text-base-content/60">고객센터 전화번호가 설정되지 않았습니다.</p>
        )}
        <p className="mt-3 text-sm leading-6 text-base-content/70">
          주문과 상품 문의는 <Link href="/faq" className="link link-hover">고객센터</Link>에서 확인해 주세요.
        </p>
        <p className="mt-2 text-sm leading-6 text-base-content/70">
          <Link href="/shop/couponzone" className="link link-hover">쿠폰존</Link>에서 사용할 수 있는 쿠폰을 받아가세요.
        </p>
      </div>

      <div>
        <h2 className="border-b border-base-300 pb-3 text-lg font-bold text-base-content">무통장 입금</h2>
        {settingsState === "loading" ? (
          <p className="flex items-center gap-2 pt-4 text-sm text-base-content/60" role="status" aria-live="polite">
            <span className="loading loading-spinner loading-xs" aria-hidden="true" />
            입금 안내를 불러오는 중입니다.
          </p>
        ) : settingsState === "error" ? (
          <div className="flex flex-wrap items-center gap-3 pt-4">
            <p className="text-sm text-error" role="alert">입금 안내를 불러오지 못했습니다.</p>
            <button type="button" className="btn btn-sm btn-ghost" onClick={retryLoading}>
              다시 시도
            </button>
          </div>
        ) : bankEnabled && bankAccounts.length > 0 ? (
          <ul className="mt-4 space-y-2 text-sm leading-6 text-base-content/75">
            {bankAccounts.map((account, index) => <li key={`${index}-${account}`}>{account}</li>)}
          </ul>
        ) : (
          <p className="mt-4 text-sm text-base-content/60">
            {bankEnabled ? "등록된 입금 계좌가 없습니다." : "무통장 입금이 설정되어 있지 않습니다."}
          </p>
        )}
      </div>
    </section>
  );
}
