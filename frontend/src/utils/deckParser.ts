export interface DeckCard {
  quantity: number;
  name: string;
  setAbbrev: string;
  setNumber: string;
}

export interface ParsedDeck {
  pokemon: DeckCard[];
  trainers: DeckCard[];
  energy: DeckCard[];
  totalCards: number;
  errors: string[];
}

type Section = 'pokemon' | 'trainers' | 'energy' | null;

const BASIC_ENERGY_PTCGL_NUMBERS: Record<string, string> = {
  'grass energy': '1',
  'fire energy': '2',
  'water energy': '3',
  'lightning energy': '4',
  'psychic energy': '5',
  'fighting energy': '6',
  'darkness energy': '7',
  'metal energy': '8',
};

export function parsePTCGDeck(text: string): ParsedDeck {
  const result: ParsedDeck = {
    pokemon: [],
    trainers: [],
    energy: [],
    totalCards: 0,
    errors: [],
  };

  if (!text.trim()) return result;

  const cardLineRegex = /^(\d+)\s+(.+?)\s+([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)?)\s+(\d+)$/;
  const fallbackRegex = /^(\d+)\s+(.+)$/;

  let currentSection: Section = null;

  for (const rawLine of text.split('\n')) {
    const line = rawLine.trim();
    if (!line) continue;

    if (/^Pok[eé]mon/i.test(line)) {
      currentSection = 'pokemon';
      continue;
    }
    if (/^Trainer/i.test(line)) {
      currentSection = 'trainers';
      continue;
    }
    if (/^Energy/i.test(line)) {
      currentSection = 'energy';
      continue;
    }

    const fullMatch = cardLineRegex.exec(line);
    const fallbackMatch = fallbackRegex.exec(line);

    let card: DeckCard | null = null;

    if (fullMatch) {
      card = {
        quantity: parseInt(fullMatch[1], 10),
        name: fullMatch[2].trim(),
        setAbbrev: fullMatch[3],
        setNumber: fullMatch[4],
      };
    } else if (fallbackMatch) {
      const fallbackName = fallbackMatch[2].trim();
      const energyNumber = BASIC_ENERGY_PTCGL_NUMBERS[fallbackName.toLowerCase()];
      card = {
        quantity: parseInt(fallbackMatch[1], 10),
        name: fallbackName,
        setAbbrev: 'SVE',
        setNumber: energyNumber ?? '0',
      };
    }

    if (card) {
      result.totalCards += card.quantity;
      if (currentSection === 'pokemon') {
        result.pokemon.push(card);
      } else if (currentSection === 'trainers') {
        result.trainers.push(card);
      } else if (currentSection === 'energy') {
        result.energy.push(card);
      } else {
        // No section header encountered — treat as pokemon by default
        result.pokemon.push(card);
      }
    }
  }

  if (result.totalCards > 0 && result.totalCards !== 60) {
    result.errors.push(`Deck has ${result.totalCards} cards — must be exactly 60.`);
  }

  return result;
}
