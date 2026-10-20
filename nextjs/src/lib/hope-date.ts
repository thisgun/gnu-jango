/** YoungCart 희망배송일 helpers: dates are plain YYYY-MM-DD strings in the shop's local calendar. */

const KOREAN_WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"] as const;
const ISO_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

/** The calendar date of a YYYY-MM-DD string, or null when it is not a real date. */
export function parseIsoDate(value: string): Date | null {
  const match = ISO_DATE_PATTERN.exec(value.trim());
  if (!match) return null;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return null;
  }
  return date;
}

/** "2026-10-25 (일)"; the value as given when it is not a YYYY-MM-DD date. */
export function formatHopeDate(value: string): string {
  const date = parseIsoDate(value);
  if (!date) return value;
  return `${value.trim()} (${KOREAN_WEEKDAYS[date.getUTCDay()]})`;
}
