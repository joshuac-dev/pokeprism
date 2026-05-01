#!/usr/bin/env python3
"""Script to fetch TCGDex data and check implementations."""
import json, subprocess, sys

# Cards to audit - get the list of registered attack card IDs
card_ids = [
    "sv09-024",  # Blaziken ex
    "sv06-064",  # Wellspring Mask Ogerpon ex
    "sv10-012",  # Scizor ex?
    "sv10-020",  # ?
    "sv10-041",  # ?
    "sv10-051",  # ?
    "sv06-025",  # ?
    "sv05-023",  # Rellor
    "sv09-098",  # ?
    "sv10-087",  # ?
    "me03-001",  # ?
    "me03-023",  # ?
    "me03-029",  # ?
    "me03-034",  # ?
    "me03-051",  # ?
    "me03-052",  # ?
    "me02.5-002", # Erica's Gloom
    "me02.5-007", # ?
    "me02.5-013", # ?
    "me02.5-030", # ?
    "sv06-039",  # ?
    "sv06-093",  # ?
    "sv06-095",  # ?
    "sv06-096",  # ?
    "sv06-112",  # ?
    "sv06-118",  # ?
]

import urllib.request

def fetch_card(card_id):
    url = f"https://api.tcgdex.net/v2/en/cards/{card_id}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}

for card_id in card_ids[:10]:
    data = fetch_card(card_id)
    name = data.get("name", "?")
    attacks = data.get("attacks", [])
    print(f"\n=== {card_id} {name} ===")
    for i, atk in enumerate(attacks):
        print(f"  [{i}] {atk.get('name')} ({atk.get('damage', 0)}): {atk.get('effect', '')[:100]}")
