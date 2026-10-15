import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { slugifyHeading } from "../themes/handbook/anchors";

type AnchorFixture = { text: string; index: number; anchor: string };
const fixtures = JSON.parse(
  readFileSync(resolve(process.cwd(), "../gnu_jango/docs_search/anchor_fixtures.json"), "utf8")
) as AnchorFixture[];

test("handbook page TOC anchors match the Python search anchors", () => {
  for (const fixture of fixtures) {
    expect(slugifyHeading(fixture.text, fixture.index), fixture.text).toBe(fixture.anchor);
  }
});
