/** Shared heading-anchor rule for the handbook table of contents and Python question-search results. */
export function slugifyHeading(text: string, index: number): string {
  const base = text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .replace(/\s+/g, "-")
    .slice(0, 60);
  return base ? `${base}-${index}` : `section-${index}`;
}
