"""Prompt templates for the Coach/Analyst system (Gemma 4 E4B)."""

COACH_EVOLUTION_PROMPT = """\
You are an expert Pokémon TCG deck analyst. Analyze this deck's performance and \
propose 0-{max_swaps} card swaps to improve its win rate.

## Current Deck
{deck_list}

## Round Performance
Win rate: {win_rate:.1%} ({wins}/{total_games} games)
Average turns per game: {avg_turns:.1f}
Primary loss reasons: {loss_reasons}

## Card Performance (current deck)
{card_stats}

## Top Candidate Replacements (from historical data)
{candidate_cards}

## Synergy Analysis
Strong synergies to preserve: {top_synergies}
Weak synergies (candidates for removal): {weak_synergies}

## Similar Past Situations
{similar_situations}

## Excluded Cards (DO NOT suggest these as additions)
{excluded_cards}

## Instructions
- Propose between 0 and {max_swaps} swaps (remove one card, add one card per swap).
- Prefer removing cards with low win_rate AND low synergy with the rest of the deck.
- Preserve core engine cards (draw support, main attacker, energy acceleration).
- Each swap must maintain a 60-card deck.
- If the deck is performing well (win_rate > 60%), propose 0 swaps.
- Respond ONLY with valid JSON in this exact format:

{{
  "swaps": [
    {{
      "remove": "<tcgdex_id>",
      "add": "<tcgdex_id>",
      "reasoning": "<one sentence>"
    }}
  ],
  "analysis": "<2-3 sentence overall assessment>"
}}
"""

DECK_NAME_PROMPT = """\
Generate a creative, lore-appropriate name for a Pokémon TCG deck with this composition:
Main attacker: {main_attacker}
Key support cards: {support_cards}
Strategy: {strategy}

Respond with ONLY the deck name, no explanation. Maximum 5 words.
"""
