/**
 * Locale-aware date formatting (LR-007).
 *
 * Components used to call `new Date(value).toLocaleString()` with no locale argument, which follows
 * the *browser's* locale rather than the one the user picked in the app. Switching to Spanish
 * changed every nav label but left dates in US order, which is precisely the ambiguity LR-007
 * exists to remove: 07/09 is two different days depending on who is reading it.
 *
 * Pass the active locale from `useLocale()`.
 */

/** Values the API sends that are not really dates get rendered as they arrived. */
function parse(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** e.g. "23/07/2026" in es, "7/23/2026" in en. */
export function formatDate(value: string | null | undefined, locale: string): string {
  const date = parse(value);
  if (!date) return value ?? "";
  return new Intl.DateTimeFormat(locale).format(date);
}

/** e.g. "23/07/2026, 14:05:09" in es, "7/23/2026, 2:05:09 PM" in en. */
export function formatDateTime(value: string | null | undefined, locale: string): string {
  const date = parse(value);
  if (!date) return value ?? "";
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(date);
}
