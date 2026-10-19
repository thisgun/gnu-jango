import { boardListHref } from "@/lib/board-url";
import { menuHref, type MenuItem } from "@/components/layout/menu";

/** A board the server says any visitor may list (runtime config navBoards). */
export type NavigationBoard = { bo_table: string; bo_subject: string };

const RECENT: MenuItem = { me_id: -14, me_code: "fallback_recent", me_name: "새글", me_link: "/recent", me_target: "" };

/** Used only when the server gave no board list (a separate Node runtime); a Django-served page always does. */
const BUILT_IN_COMMUNITY: MenuItem = {
  me_id: -1, me_code: "fallback_community", me_name: "커뮤니티", me_link: "/free", me_target: "",
  children: [
    { me_id: -11, me_code: "fallback_free", me_name: "자유게시판", me_link: "/free", me_target: "" },
    { me_id: -12, me_code: "fallback_qa", me_name: "질문답변", me_link: "/qa", me_target: "" },
    { me_id: -13, me_code: "fallback_gallery", me_name: "갤러리", me_link: "/gallery", me_target: "" },
    RECENT,
  ],
};

const OTHER_DEFAULT_MENUS: MenuItem[] = [
  {
    me_id: -2, me_code: "fallback_shop", me_name: "쇼핑몰", me_link: "/shop", me_target: "",
    children: [
      { me_id: -21, me_code: "fallback_shop_home", me_name: "쇼핑몰 홈", me_link: "/shop", me_target: "" },
      { me_id: -22, me_code: "fallback_coupon", me_name: "쿠폰존", me_link: "/shop/couponzone", me_target: "" },
    ],
  },
  {
    me_id: -3, me_code: "fallback_support", me_name: "고객센터", me_link: "/faq", me_target: "",
    children: [
      { me_id: -31, me_code: "fallback_faq", me_name: "자주 묻는 질문", me_link: "/faq", me_target: "" },
      { me_id: -32, me_code: "fallback_qna", me_name: "1:1 문의", me_link: "/mypage/qas", me_target: "" },
    ],
  },
  {
    me_id: -4, me_code: "fallback_member", me_name: "회원공간", me_link: "/mypage", me_target: "",
    children: [
      { me_id: -41, me_code: "fallback_login", me_name: "로그인", me_link: "/login", me_target: "" },
      { me_id: -42, me_code: "fallback_register", me_name: "회원가입", me_link: "/register", me_target: "" },
      { me_id: -43, me_code: "fallback_mypage", me_name: "마이페이지", me_link: "/mypage", me_target: "" },
    ],
  },
  {
    me_id: -5, me_code: "fallback_info", me_name: "사이트 안내", me_link: "/content/company", me_target: "",
    children: [
      { me_id: -51, me_code: "fallback_company", me_name: "회사소개", me_link: "/content/company", me_target: "" },
      { me_id: -52, me_code: "fallback_privacy", me_name: "개인정보처리방침", me_link: "/content/privacy", me_target: "" },
    ],
  },
];

/** The community menu from the site's own boards, or the built-in one when the boards are unknown. */
function communityMenu(boards: NavigationBoard[] | undefined): MenuItem {
  if (boards === undefined) return BUILT_IN_COMMUNITY;
  const children: MenuItem[] = boards.map((board, index) => ({
    me_id: -100 - index,
    me_code: `board_${board.bo_table}`,
    me_name: board.bo_subject || board.bo_table,
    me_link: boardListHref(board.bo_table),
    me_target: "",
  }));
  children.push(RECENT);
  // The top-level link is "new posts", not a board: a site menu that links to a board would otherwise
  // share its href and the de-duplication below would drop the whole community menu.
  return { ...BUILT_IN_COMMUNITY, me_link: RECENT.me_link, children };
}

/**
 * The header menu: the site's own menus first, then the defaults whose link the site menus do not
 * already use. `boards` comes from the server (runtime config navBoards); undefined keeps the
 * built-in community links.
 */
export function buildNavigationMenus(menus: MenuItem[], boards: NavigationBoard[] | undefined): MenuItem[] {
  const seen = new Set<string>();
  const merged: MenuItem[] = [];

  for (const menu of [...menus, communityMenu(boards), ...OTHER_DEFAULT_MENUS]) {
    const href = menuHref(menu.me_link);
    if (!href || seen.has(href)) continue;
    seen.add(href);
    merged.push(menu);
  }

  return merged;
}
