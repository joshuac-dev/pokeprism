#!/usr/bin/env python3
"""Phase 7 live-stack validation script.

Verifies the full Task Queue & Simulation Orchestration stack:
  1. FastAPI health endpoint responds
  2. POST /api/simulations creates a simulation
  3. Simulation status progresses to "complete" or "failed" within timeout
  4. Simulation has at least one round recorded
  5. Mutations endpoint responds (even if empty)

Run from backend/ while the Docker stack is up:
    python3 -m scripts.validate_phase7

Requirements:
  - Docker stack running (docker-compose up)
  - At least one Celery worker running
  - Cards pre-loaded in the database (run validate_phase5/6 first)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

BASE_URL = "http://localhost:8000"
TIMEOUT = 120  # seconds to wait for simulation to complete

# 60-card Dragapult ex / Dusknoir deck (tcgdex IDs — sv06 = TWM, sv08.5 = PRE, etc.)
TEST_DECK = """\
4 Dreepy sv06-128
3 Drakloak sv06-129
3 Dragapult ex sv06-130
4 Duskull sv08.5-035
2 Dusclops sv08.5-036
2 Dusknoir sv08.5-037
1 Fezandipiti sv06-096
1 Fezandipiti ex me02.5-142
1 Munkidori sv06-095
1 Psyduck me02.5-039
4 Buddy-Buddy Poffin sv05-144
3 Ultra Ball me01-131
3 Rare Candy me01-125
2 Night Stretcher me02.5-196
2 Prime Catcher sv05-157
2 Boss's Orders me01-114
2 Maximum Belt sv05-154
2 Legacy Energy sv06-167
2 Morty's Conviction sv05-155
2 Eri sv05-146
2 Secret Box sv06-163
1 Bug Catching Set sv06-143
1 Enhanced Hammer sv06-148
1 Binding Mochi sv08.5-095
1 Janine's Secret Art sv08.5-112
4 Psychic Energy mee-005
2 Mist Energy sv05-161
2 Prism Energy me02.5-216
"""

# Opponent deck (Team Rocket's Mewtwo ex — sv10 = DRI, me01 = MEG, me02.5 = ASC)
OPPONENT_DECK = """\
3 Team Rocket's Mewtwo ex sv10-081
3 Team Rocket's Mimikyu sv10-087
2 Team Rocket's Sneasel sv10-128
2 Team Rocket's Articuno sv10-051
2 Shaymin sv10-010
2 Psyduck me02.5-039
2 Yveltal me01-088
1 Mega Absol ex me01-086
1 Lunatone me01-074
3 Team Rocket's Transceiver sv10-178
3 Team Rocket's Giovanni sv10-174
3 Team Rocket's Factory sv10-173
2 Team Rocket's Proton sv10-177
2 Team Rocket's Archer sv10-170
2 Team Rocket's Ariana sv10-171
2 Team Rocket's Petrel sv10-176
2 Team Rocket's Watchtower sv10-180
2 Spikemuth Gym sv10-169
2 Sacred Ash sv10-168
2 Energy Recycler sv10-164
2 Ultra Ball me01-131
2 Boss's Orders me01-114
1 Lillie's Determination me01-119
1 Energy Switch me01-115
1 Pokégear 3.0 sv01-186
1 Colress's Tenacity sv06.5-057
3 Psychic Energy mee-005
3 Darkness Energy mee-007
2 Team Rocket's Energy sv10-182
1 Prism Energy me02.5-216
"""


def _check(label: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    line = f"  [{status}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    return condition


def _count_cards(deck_text: str) -> int:
    total = 0
    for line in deck_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts:
            try:
                total += int(parts[0])
            except ValueError:
                pass
    return total


def run_validation() -> int:
    """Run all checks.  Returns 0 on full pass, 1 otherwise."""
    all_passed = True
    print("=" * 60)
    print("Phase 7 Validation — PokéPrism Task Queue & Orchestration")
    print("=" * 60)

    # ── 0. Verify test decks are 60 cards ──────────────────────────────────
    print("\n[0] Pre-flight deck checks")
    user_count = _count_cards(TEST_DECK)
    opp_count = _count_cards(OPPONENT_DECK)
    all_passed &= _check("User deck has 60 cards", user_count == 60, f"got {user_count}")
    all_passed &= _check("Opponent deck has 60 cards", opp_count == 60, f"got {opp_count}")

    # ── 1. Health check ─────────────────────────────────────────────────────
    print("\n[1] FastAPI health check")
    try:
        resp = httpx.get(f"{BASE_URL}/health", timeout=5.0)
        all_passed &= _check("GET /health returns 200", resp.status_code == 200, str(resp.status_code))
        all_passed &= _check("Response contains status=ok", resp.json().get("status") == "ok")
    except Exception as exc:
        all_passed &= _check("GET /health reachable", False, str(exc))
        print("  Cannot reach API — aborting remaining checks.")
        return 1

    # ── 2. Create simulation ─────────────────────────────────────────────────
    print("\n[2] POST /api/simulations")
    try:
        resp = httpx.post(
            f"{BASE_URL}/api/simulations",
            json={
                "deck_text": TEST_DECK,
                "deck_mode": "full",
                "game_mode": "hh",
                "deck_locked": True,
                "num_rounds": 2,
                "matches_per_opponent": 10,
                "target_win_rate": 0.40,
                "opponent_deck_texts": [OPPONENT_DECK],
                "excluded_card_ids": [],
            },
            timeout=10.0,
        )
        all_passed &= _check("POST returns 201", resp.status_code == 201, str(resp.status_code))
        body = resp.json()
        sim_id = body.get("simulation_id")
        all_passed &= _check("Response contains simulation_id", sim_id is not None)
        all_passed &= _check("Status is 'pending'", body.get("status") == "pending")
        if "warning" in body:
            print(f"  [INFO] Warning: {body['warning']}")
    except Exception as exc:
        all_passed &= _check("POST /api/simulations succeeded", False, str(exc))
        return 1

    if not sim_id:
        print("  Cannot continue without simulation_id.")
        return 1

    # ── 3. Poll until complete ───────────────────────────────────────────────
    print(f"\n[3] Polling simulation {sim_id} (timeout {TIMEOUT}s)")
    deadline = time.time() + TIMEOUT
    final_status = None
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{BASE_URL}/api/simulations/{sim_id}", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                final_status = data.get("status")
                rounds_completed = data.get("rounds_completed", 0)
                elapsed = int(TIMEOUT - (deadline - time.time()))
                print(
                    f"  [{elapsed:3d}s] status={final_status!r}  "
                    f"rounds_completed={rounds_completed}",
                    end="\r",
                )
                if final_status in ("complete", "failed"):
                    break
        except Exception as exc:
            print(f"\n  [WARN] Poll error: {exc}")
        time.sleep(3)
    print()  # newline after \r

    all_passed &= _check(
        "Simulation reached terminal state",
        final_status in ("complete", "failed"),
        f"final_status={final_status!r}",
    )
    if final_status == "failed":
        try:
            err = httpx.get(f"{BASE_URL}/api/simulations/{sim_id}", timeout=5.0)
            em = err.json().get("error_message", "(none)")
            print(f"  [INFO] error_message: {em}")
        except Exception:
            pass

    # ── 4. Verify rounds ─────────────────────────────────────────────────────
    print("\n[4] GET /api/simulations/{id}/rounds")
    try:
        resp = httpx.get(f"{BASE_URL}/api/simulations/{sim_id}/rounds", timeout=5.0)
        all_passed &= _check("GET /rounds returns 200", resp.status_code == 200)
        rounds = resp.json()
        all_passed &= _check(
            "At least 1 round recorded",
            len(rounds) >= 1,
            f"got {len(rounds)} rounds",
        )
        if rounds:
            r = rounds[0]
            all_passed &= _check(
                "Round has round_number",
                "round_number" in r,
            )
    except Exception as exc:
        all_passed &= _check("GET /rounds succeeded", False, str(exc))

    # ── 5. Verify mutations endpoint ─────────────────────────────────────────
    print("\n[5] GET /api/simulations/{id}/mutations")
    try:
        resp = httpx.get(f"{BASE_URL}/api/simulations/{sim_id}/mutations", timeout=5.0)
        all_passed &= _check("GET /mutations returns 200", resp.status_code == 200)
        mutations = resp.json()
        print(f"  [INFO] {len(mutations)} mutation(s) recorded")
    except Exception as exc:
        all_passed &= _check("GET /mutations succeeded", False, str(exc))

    # ── 6. Star / unstar ─────────────────────────────────────────────────────
    print("\n[6] PATCH /api/simulations/{id}/star")
    try:
        resp = httpx.patch(f"{BASE_URL}/api/simulations/{sim_id}/star", timeout=5.0)
        all_passed &= _check("PATCH /star returns 200", resp.status_code == 200)
        all_passed &= _check("starred=True after first patch", resp.json().get("starred") is True)
    except Exception as exc:
        all_passed &= _check("PATCH /star succeeded", False, str(exc))

    # ── 7. List simulations ──────────────────────────────────────────────────
    print("\n[7] GET /api/simulations/")
    try:
        resp = httpx.get(f"{BASE_URL}/api/simulations/", timeout=5.0)
        all_passed &= _check("GET /api/simulations/ returns 200", resp.status_code == 200)
        all_passed &= _check("List contains at least 1 entry", len(resp.json()) >= 1)
    except Exception as exc:
        all_passed &= _check("GET /api/simulations/ succeeded", False, str(exc))

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if all_passed:
        print("RESULT: ALL CHECKS PASSED ✓")
    else:
        print("RESULT: SOME CHECKS FAILED ✗")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(run_validation())
