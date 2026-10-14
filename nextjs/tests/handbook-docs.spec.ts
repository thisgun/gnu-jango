import { expect, test } from "@playwright/test";
import { bookForPath, canonicalDocPath, chapterPositionByPath } from "../themes/handbook/book-nav";
import {
  booksFromBoards,
  collectAllPages,
  groupDocsChapters,
  parseCategoryList,
  type DocsBook,
} from "../themes/handbook/docs-nav";
import { parseHandbookThemeSettings } from "../themes/handbook/theme-settings";
import type { Board, WritePost } from "../src/lib/types";

const board = (overrides: Partial<Board>): Board => ({ bo_table: "hb_dev", bo_subject: "책", bo_order: 0, ...overrides }) as Board;
// 게시판은 wr_num 이 작은 글이 앞이다(새 글이 더 작은 번호를 받아 목록 맨 위로 오는 그누보드 규칙) — 장 1 이 가장 작은 번호.
const post = (id: number, subject: string, ca_name = ""): WritePost =>
  ({ wr_id: id, wr_subject: subject, ca_name, wr_num: id, wr_reply: "", wr_datetime: "2026-10-14 00:00:00" }) as unknown as WritePost;

test.describe("매뉴얼 주소와 목차", () => {
  test("글 주소는 /bbs · /boards · 짧은 주소 어느 꼴이든 같은 꼴로 맞춘다", () => {
    for (const path of ["/bbs/hb_dev/12", "/boards/hb_dev/12", "/hb_dev/12", "/hb_dev/12/", "/hb_dev/12?page=2#x"]) {
      expect(canonicalDocPath(path), path).toBe("/hb_dev/12");
    }
  });

  test("다른 사이트의 전체 주소는 어떤 매뉴얼과도 맞지 않는다", () => {
    expect(canonicalDocPath("https://example.com/hb_dev/12")).toBe("https://example.com/hb_dev/12");
  });

  test("지금 주소가 속한 책을 찾되, 이름이 비슷한 책(manual / manual2)을 헷갈리지 않는다", () => {
    const books = [{ table: "manual" }, { table: "manual2" }] as DocsBook[];

    expect(bookForPath(books, "/bbs/manual2/3")?.table).toBe("manual2");
    expect(bookForPath(books, "/bbs/manual/3")?.table).toBe("manual");
    expect(bookForPath(books, "/bbs/free/3")).toBeUndefined();
    expect(bookForPath(books, "/")).toBeUndefined();
  });

  test("책은 게시판 출력 순서(bo_order)로, 제목이 '앞 · 뒤' 꼴이면 앞이 안내 문구다", () => {
    const books = booksFromBoards([
      board({ bo_table: "b", bo_subject: "개발과 배포 · 서버에 올리기", bo_order: 3 }),
      board({ bo_table: "a", bo_subject: "시작하기 · 처음 따라하기", bo_order: 1, bo_category_list: "시작 전|따라하기" }),
    ]);

    expect(books.map((book) => book.table)).toEqual(["a", "b"]);
    expect(books[0]).toMatchObject({ label: "처음 따라하기", hint: "시작하기", categories: ["시작 전", "따라하기"] });
  });

  test("분류 설정 문자열은 부 순서가 된다", () => {
    expect(parseCategoryList(" 개요|1부 운영 ||API ")).toEqual(["개요", "1부 운영", "API"]);
  });

  test("장은 부(분류)별로 묶이고 부 순서는 게시판 분류 설정을, 장 순서는 글 순서를 따른다", () => {
    const groups = groupDocsChapters(
      [post(3, "둘째 부 첫 장", "둘째"), post(1, "첫 부 첫 장", "첫째"), post(2, "첫 부 둘째 장", "첫째")],
      "hb_dev",
      ["첫째", "둘째"]
    );

    expect(groups.map((group) => group.label)).toEqual(["첫째", "둘째"]);
    expect(groups[0].items.map((item) => item.label)).toEqual(["첫 부 첫 장", "첫 부 둘째 장"]);
  });

  test("쪽을 나눠 받는 중에 같은 글이 두 쪽에 걸쳐 와도 한 번만 넣는다", () => {
    const groups = groupDocsChapters([post(1, "가", "부"), post(1, "가", "부")], "hb_dev");

    expect(groups.flatMap((group) => group.items)).toHaveLength(1);
  });

  test("현재 장의 위치(몇 번째 / 전체)를 주소로 찾는다", () => {
    const groups = groupDocsChapters([post(1, "가", "부"), post(2, "나", "부")], "hb_dev");
    const book = { table: "hb_dev", label: "책", hint: "", groups, count: 2 } as DocsBook;

    expect(chapterPositionByPath(book, "/bbs/hb_dev/2")).toMatchObject({ number: 2, total: 2 });
    expect(chapterPositionByPath(book, "/bbs/hb_dev/99")).toBeNull();
  });

  test("모든 쪽을 모으되 쪽 수 상한을 넘기지 않는다", async () => {
    const asked: number[] = [];
    const items = await collectAllPages(async (page) => {
      asked.push(page);
      return { items: [page], lastPage: 50 };
    }, 5);

    expect(items).toEqual([1, 2, 3, 4, 5]);
    expect([...asked].sort()).toEqual([1, 2, 3, 4, 5]);
  });
});

test.describe("테마 설정(Django 가 싣는 값)", () => {
  const saved = { theme: "handbook", revision: 1, docs: { group: "manual", hints: { hb_dev: "개발" } }, sidebar: {}, site: {} };

  test("매뉴얼 그룹과 안내 문구를 읽는다", () => {
    expect(parseHandbookThemeSettings(saved)).toMatchObject({ docs: { group: "manual", hints: { hb_dev: "개발" } } });
  });

  test("저장한 적 없는 설정(변경 번호 0) · 다른 테마의 설정 · 모양이 아닌 값은 쓰지 않는다", () => {
    expect(parseHandbookThemeSettings({ ...saved, revision: 0 })).toBeNull();
    expect(parseHandbookThemeSettings({ ...saved, theme: "other" })).toBeNull();
    expect(parseHandbookThemeSettings("junk")).toBeNull();
    expect(parseHandbookThemeSettings(undefined)).toBeNull();
  });

  test("그룹 ID 가 그누보드 모양이 아니면 비운다", () => {
    expect(parseHandbookThemeSettings({ ...saved, docs: { group: "../etc", hints: {} } })?.docs.group).toBe("");
  });
});
