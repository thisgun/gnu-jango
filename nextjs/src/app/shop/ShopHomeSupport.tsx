"use client";

import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { boardListHref, boardPostHref } from "@/lib/board-url";
import type { PublicSettings } from "@/lib/schemas";
import type { Board, WritePost } from "@/lib/types";
import { formatListDate, truncate } from "@/lib/utils";
import { getShopHomeData } from "@/services/shop-home";

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
      try {
        const home = await getShopHomeData();
        if (!active) return;
        setSettings(home.settings);
        setNoticeBoard(home.noticeBoard);
        setNoticePosts(home.noticePosts);
        setNoticeState("ready");
        setSettingsState("ready");
      } catch {
        if (!active) return;
        setNoticeState("error");
        setSettingsState("error");
      }
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

  const noticeHref = noticeBoard ? boardListHref(noticeBoard.bo_table) : "/boards";

  // 레퍼런스 쇼핑 홈 아래 칸(BottomAside): 왼쪽 테두리 상자에 공지 세 줄, 오른쪽 옅은 바탕에 고객센터 · 무통장 입금.
  return (
    <aside className="solune-shop-sidebar" aria-label="쇼핑몰 안내">
      <section className="solune-shop-sidebar-card ondam-notice">
        <div className="ondam-notice-head">
          <h2>
            <Link href={noticeHref}>공지사항</Link>
          </h2>
          <Link className="ondam-notice-more" href={noticeHref}>
            전체 보기
            <ArrowRight size={13} strokeWidth={2.6} aria-hidden />
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
          <ul className="ondam-notice-list">
            {noticePosts.map((post) => (
              <li key={post.wr_id}>
                <Link href={boardPostHref(noticeBoard?.bo_table || "notice", post, settings?.cf_bbs_rewrite)}>
                  <span>{truncate(post.wr_subject || "제목 없음", 50)}</span>
                  <time dateTime={post.wr_datetime}>{formatListDate(post.wr_datetime)}</time>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="sct_noitem">
            {noticeBoard ? "아직 공지가 없습니다." : "공지사항 게시판이 설정되지 않았습니다."}
          </p>
        )}
      </section>

      <section className="solune-shop-sidebar-card solune-shop-help-card ondam-help">
        <section>
        <h3>고객센터</h3>
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
          <p className="ondam-help-tel">
            <a href={`tel:${telephoneHref}`}>{phone}</a>
          </p>
        ) : null}
        <p>
          주문과 상품 문의는 <Link href="/faq">고객센터</Link>에서 확인해 주세요.
          <br />
          <Link href="/shop/couponzone">쿠폰존</Link>에서 사용할 수 있는 쿠폰을 받아가세요.
        </p>
        </section>

        <section>
        <h3>무통장 입금</h3>
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
          <p className="ondam-help-bank">{bankAccounts.join("\n")}</p>
        ) : (
          <p>{bankEnabled ? "등록된 입금 계좌가 없습니다." : "무통장 입금이 설정되어 있지 않습니다."}</p>
        )}
        </section>
      </section>
    </aside>
  );
}
