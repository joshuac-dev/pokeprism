import { describe, expect, it } from 'vitest';
import { parsePTCGDeck } from './deckParser';

describe('parsePTCGDeck', () => {
  it('parses hyphenated set codes such as PR-SV', () => {
    const parsed = parsePTCGDeck('Pokémon: 1\n1 Pecharunt PR-SV 149');

    expect(parsed.totalCards).toBe(1);
    expect(parsed.pokemon[0]).toMatchObject({
      quantity: 1,
      name: 'Pecharunt',
      setAbbrev: 'PR-SV',
      setNumber: '149',
    });
  });

  it('maps basic energy shorthand to SVE numbers', () => {
    const parsed = parsePTCGDeck('Energy: 10\n6 Psychic Energy\n4 Darkness Energy');

    expect(parsed.totalCards).toBe(10);
    expect(parsed.energy).toEqual([
      { quantity: 6, name: 'Psychic Energy', setAbbrev: 'SVE', setNumber: '5' },
      { quantity: 4, name: 'Darkness Energy', setAbbrev: 'SVE', setNumber: '7' },
    ]);
  });
});
