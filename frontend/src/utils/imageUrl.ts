/**
 * Normalize a TCGDex asset URL so the browser receives a concrete image variant.
 *
 * The DB stores bare TCGDex asset paths, e.g.:
 *   https://assets.tcgdex.net/en/sv/sv06/130
 *
 * Without a format suffix the server returns text/html. Appending `/high.webp`
 * returns image/webp and renders correctly in browsers.
 *
 * Rules:
 * - null / undefined / empty string → null
 * - URL already ends in .webp, .png, .jpg, or .jpeg → returned as-is
 * - bare TCGDex asset path → path + `/${quality}.webp`
 */
export function normalizeTcgdexImageUrl(
  url: string | null | undefined,
  quality: 'high' | 'low' = 'high',
): string | null {
  if (!url) return null;
  if (/\.(webp|png|jpe?g)$/i.test(url)) return url;
  return `${url}/${quality}.webp`;
}
