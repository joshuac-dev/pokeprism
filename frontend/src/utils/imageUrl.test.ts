import { describe, expect, it } from 'vitest';
import { normalizeTcgdexImageUrl } from './imageUrl';

describe('normalizeTcgdexImageUrl', () => {
  it('returns null for null input', () => {
    expect(normalizeTcgdexImageUrl(null)).toBeNull();
  });

  it('returns null for undefined input', () => {
    expect(normalizeTcgdexImageUrl(undefined)).toBeNull();
  });

  it('returns null for empty string', () => {
    expect(normalizeTcgdexImageUrl('')).toBeNull();
  });

  it('appends /high.webp to a bare TCGDex asset path', () => {
    expect(normalizeTcgdexImageUrl('https://assets.tcgdex.net/en/sv/sv06/130'))
      .toBe('https://assets.tcgdex.net/en/sv/sv06/130/high.webp');
  });

  it('does not double-append when URL already ends in /high.webp', () => {
    const url = 'https://assets.tcgdex.net/en/sv/sv06/130/high.webp';
    expect(normalizeTcgdexImageUrl(url)).toBe(url);
  });

  it('does not double-append when URL already ends in /low.webp', () => {
    const url = 'https://assets.tcgdex.net/en/sv/sv06/130/low.webp';
    expect(normalizeTcgdexImageUrl(url)).toBe(url);
  });

  it('leaves .png URLs unchanged', () => {
    const url = 'https://example.com/card.png';
    expect(normalizeTcgdexImageUrl(url)).toBe(url);
  });

  it('leaves .jpg URLs unchanged', () => {
    const url = 'https://example.com/card.jpg';
    expect(normalizeTcgdexImageUrl(url)).toBe(url);
  });

  it('leaves .jpeg URLs unchanged', () => {
    const url = 'https://example.com/card.jpeg';
    expect(normalizeTcgdexImageUrl(url)).toBe(url);
  });

  it('leaves .webp URLs unchanged', () => {
    const url = 'https://example.com/card.webp';
    expect(normalizeTcgdexImageUrl(url)).toBe(url);
  });

  it('appends /low.webp when quality="low"', () => {
    expect(normalizeTcgdexImageUrl('https://assets.tcgdex.net/en/sv/sv06/130', 'low'))
      .toBe('https://assets.tcgdex.net/en/sv/sv06/130/low.webp');
  });
});
