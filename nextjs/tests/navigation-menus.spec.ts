import { expect, test } from "@playwright/test";
import type { MenuItem } from "../src/components/layout/menu";
import { buildNavigationMenus } from "../src/components/layout/navigation-menus";
import { boardListHref } from "../src/lib/board-url";

function links(menus: MenuItem[]): string[] {
  return menus.flatMap((menu) => [menu.me_link, ...(menu.children ?? []).map((child) => child.me_link)]);
}

test.describe("header navigation", () => {
  test("a site without menus lists its own boards instead of built-in board paths", () => {
    const menus = buildNavigationMenus([], [
      { bo_table: "공지사항", bo_subject: "공지사항" },
      { bo_table: "자유게시판", bo_subject: "자유게시판" },
    ]);

    const community = menus[0];
    expect(community.me_name).toBe("커뮤니티");
    expect(community.me_link).toBe("/recent");
    expect(community.children?.[0].me_link).toBe(boardListHref("공지사항"));
    expect(community.children?.map((child) => child.me_name)).toEqual(["공지사항", "자유게시판", "새글"]);
    expect(links(menus)).not.toContain("/free");
    expect(links(menus)).not.toContain("/qa");
    expect(links(menus)).not.toContain("/gallery");
    expect(links(menus)).toContain("/shop");
  });

  test("a site with no public boards keeps only the recent posts link under community", () => {
    const community = buildNavigationMenus([], [])[0];

    expect(community.me_link).toBe("/recent");
    expect(community.children?.map((child) => child.me_link)).toEqual(["/recent"]);
  });

  test("without board information (server runtime) the built-in menu stays as it was", () => {
    expect(links(buildNavigationMenus([], undefined))).toEqual(
      expect.arrayContaining(["/free", "/qa", "/gallery", "/recent"])
    );
  });

  test("the site's own menus come first and duplicates of the built-in menu are dropped", () => {
    const site: MenuItem[] = [
      { me_id: 10, me_code: "10", me_name: "쇼핑", me_link: "/shop", me_target: "" },
      { me_id: 20, me_code: "20", me_name: "공지", me_link: "/공지사항", me_target: "" },
    ];

    const menus = buildNavigationMenus(site, [{ bo_table: "공지사항", bo_subject: "공지사항" }]);

    expect(menus.slice(0, 2).map((menu) => menu.me_name)).toEqual(["쇼핑", "공지"]);
    expect(menus.filter((menu) => menu.me_link === "/shop")).toHaveLength(1);
  });

  test("a site menu that links to a board does not hide the community menu", () => {
    const site: MenuItem[] = [
      { me_id: 10, me_code: "10", me_name: "운영 공지", me_link: boardListHref("공지사항"), me_target: "" },
    ];

    const menus = buildNavigationMenus(site, [
      { bo_table: "공지사항", bo_subject: "공지사항" },
      { bo_table: "자유게시판", bo_subject: "자유게시판" },
    ]);

    expect(menus.map((menu) => menu.me_name)).toContain("커뮤니티");
    expect(links(menus)).toContain(boardListHref("자유게시판"));
  });
});
