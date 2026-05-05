# PokePrism - Current Status

> Read this first for current operational state. This file is the live handoff.
> `docs/PROJECT.md` is historical architecture context, not the active source
> of truth for implementation status.

Last updated: 2026-05-05 (session 18 — History page opponent list collapse)

## Current Workstream

PokePrism is post-phase-buildout. The original phase blueprint through Phase 13
and the 2026-05-03 hardening sweep are complete. Active work is ongoing
post-phase development:

- DB-backed card-effect audits and cursor-based handler fixes.
- Card-effect correctness, handler registration, and simulation validation.
- AI/coach hardening and decision-quality follow-up.
- Operational refinement for Docker, Celery, CI, and local workflows.

`docs/AUDIT_RULES.md` and `docs/AUDIT_STATE.md` define the active card audit
workflow. `docs/CARDLIST.md`, `docs/POKEMON_MASTER_LIST.md`, and
`docs/CARD_EXPANSION_RULES.md` are historical or supporting expansion-era docs;
they do not define current audit scope.

## Authoritative Metrics

These values are a dated local snapshot, not a permanent release baseline.
Re-check them before making claims in user-facing docs.

| Metric | Current evidence |
|---|---|
| Local cards table | **2,036** rows — 2026-05-05 |
| Coverage endpoint snapshot | **2,035 auditable cards, 1,742 implemented, 293 flat-only, 0 missing, 100.0%** — 2026-05-05 |
| Local matches table | 12,266 rows — 2026-05-05 |
| Local `card_performance` table | **1,947** rows — 2026-05-05 |
| Backend test baseline | **584 passed, 1 skipped** — 2026-05-05 session 18 (no backend changes). `cd backend && python3 -m pytest tests/ -x -q`. Historical: 579/1 (session 16), 565/1 (session 15), 547/1 (session 14), 542/1 (session 12), 522/1 (session 11), 490/1 (session 10), 478/1 (session 9), 466 (session 8). |
| Frontend unit tests | **118 passed (12 files)** — 2026-05-05 session 18. `cd frontend && npm test -- --run`. `History.test.tsx` (14); `OpponentListCell.test.tsx` (7); `OpponentDeckListModal.test.tsx` (8); `imageUrl.test.ts` (11); `Coverage.test.tsx` (12); `CardImageLightbox.test.tsx` (15); `LiveConsole.test.tsx` (18); `EventDetail.test.tsx` (16). |
| Playwright E2E inventory | 14 tests listed 2026-05-04 with `cd frontend && npm run test:e2e -- --list` |
| Effect import smoke | Passed 2026-05-05. `docker compose exec backend python -c "import app.engine.effects.attacks; import app.engine.effects.trainers; import app.engine.effects.energies; import app.engine.effects.abilities; import app.engine.effects.base"` |

## Session 18 Work (2026-05-05)

### Goal

Collapse long opponent lists on the History page. Simulations with many opponents were making the table excessively wide.

### Completed

1. **`OpponentListCell`** (`frontend/src/components/history/OpponentListCell.tsx`, new):
   - Shows at most the first 3 opponent deck names inline.
   - If `opponents.length > 3`, appends a `More… (+N)` button showing the hidden count.
   - Renders `—` for zero opponents.
   - Button has `aria-label="Show all N opponent decks"`, `e.stopPropagation()` to prevent row-level interference.

2. **`OpponentDeckListModal`** (`frontend/src/components/history/OpponentDeckListModal.tsx`, new):
   - Modal listing all opponent decks with a numbered `<ol>`.
   - Shows user deck name (or truncated simulation ID) as context subtitle.
   - `role="dialog"`, `aria-modal="true"`, close button `aria-label="Close opponent deck list"`.
   - Closes on Escape, backdrop click, close button.
   - `max-h-[70vh] overflow-y-auto` for long lists.

3. **History page updates** (`frontend/src/pages/History.tsx`):
   - `opponents` column cell replaced with `<OpponentListCell>`.
   - `opponentListModal` state added to hold the selected simulation's opponent data.
   - `<OpponentDeckListModal>` rendered when `opponentListModal` is set; closed when modal closes.
   - Sort, filter, search, pagination, compare, star, delete unaffected.

4. **Tests** — 29 new tests across 3 new files:
   - `OpponentListCell.test.tsx` (7 tests): zero/one/three/four+/More… click/aria-label.
   - `OpponentDeckListModal.test.tsx` (8 tests): all opponents listed, context, Escape/backdrop/close, a11y.
   - `History.test.tsx` (14 tests): integration — all opponent scenarios, modal open/close, controls still work.

### Validation (session 18)

| Command | Result |
|---|---|
| `cd frontend && npm test -- --run` | **118 passed (12 files)** |
| `cd frontend && npm run build` | **✓ built in 4.13s** |

### Files Changed (session 18)

| File | Change |
|---|---|
| `frontend/src/components/history/OpponentListCell.tsx` | New: inline truncated list with More… button |
| `frontend/src/components/history/OpponentDeckListModal.tsx` | New: full opponent deck list modal |
| `frontend/src/pages/History.tsx` | Replaced opponents cell; added `opponentListModal` state and rendering |
| `frontend/src/components/history/OpponentListCell.test.tsx` | New: 7 unit tests |
| `frontend/src/components/history/OpponentDeckListModal.test.tsx` | New: 8 unit tests |
| `frontend/src/pages/History.test.tsx` | New: 14 integration tests |
| `docs/STATUS.md` | This file |
| `docs/CHANGELOG.md` | Session 18 entry added |

## Session 17b Work (2026-05-05)

### Goal

Fix broken card images on the Coverage page by normalizing bare TCGDex asset URLs to renderable image URLs (append `/high.webp`).

### Root Cause

The DB stores bare TCGDex asset paths (e.g. `https://assets.tcgdex.net/en/sv/sv06/130`). Without a format suffix, the server returns HTML, not an image. All other backend endpoints (Memory, Cards search/detail) already used the `card_image_url()` normalizer from `app.api.cards`. Coverage was the only outlier — it was returning the raw DB value.

### Completed

1. **Backend fix** (`backend/app/api/coverage.py`):
   - Imported `card_image_url` from `app.api.cards`.
   - Changed `"image_url": row.image_url` → `"image_url": card_image_url(row.image_url)`.
   - Now consistent with Memory and Cards endpoints.

2. **Frontend utility** (`frontend/src/utils/imageUrl.ts`, new):
   - `normalizeTcgdexImageUrl(url, quality='high')` — defense-in-depth for future frontend use.
   - Returns `null` for null/undefined/empty. Passes through `.webp`/`.png`/`.jpg`/`.jpeg` unchanged. Appends `/{quality}.webp` to bare TCGDex paths.

3. **`CardImageLightbox` updated** (`frontend/src/components/cards/CardImageLightbox.tsx`):
   - Imports and applies `normalizeTcgdexImageUrl` before rendering `<img src=...>`.

4. **Tests updated**:
   - `backend/tests/test_api/test_coverage.py`: `test_each_card_includes_image_url` now asserts URL ends in `/high.webp`.
   - `frontend/src/utils/imageUrl.test.ts` (new, 11 tests): null/empty/already-normalized/png/jpg/jpeg/base-URL/low-quality cases.
   - `frontend/src/components/cards/CardImageLightbox.test.tsx` (15 tests, was 12): added base-URL normalization, already-normalized (no double-append), and .png pass-through cases.
   - `frontend/src/pages/Coverage.test.tsx`: mock `image_url` uses pre-normalized URL; `src` assertion expects `/high.webp`.

### Validation (session 17b)

| Command | Result |
|---|---|
| `cd backend && python3 -m pytest tests/test_api/test_coverage.py -q` | **5 passed** |
| `cd frontend && npm test -- --run` | **89 passed (9 files)** |
| `cd frontend && npm run build` | **✓ built in 4.18s** |

### Files Changed (session 17b)

| File | Change |
|---|---|
| `backend/app/api/coverage.py` | Use `card_image_url()` for normalized image URLs |
| `backend/tests/test_api/test_coverage.py` | Assert `/high.webp` normalization |
| `frontend/src/utils/imageUrl.ts` | New: `normalizeTcgdexImageUrl` utility |
| `frontend/src/utils/imageUrl.test.ts` | New: 11 utility tests |
| `frontend/src/components/cards/CardImageLightbox.tsx` | Use `normalizeTcgdexImageUrl` before rendering image |
| `frontend/src/components/cards/CardImageLightbox.test.tsx` | 15 tests (3 new: normalization behavior) |
| `frontend/src/pages/Coverage.test.tsx` | Mock/assertion updated for normalized URL |
| `docs/STATUS.md` | This file |
| `docs/CHANGELOG.md` | Session 17b entry added |

## Session 17 Work (2026-05-05)

### Goal

Add clickable card image preview/lightbox to the Coverage page. Clicking a card name opens a modal with the card image, metadata, and missing-effects info.

### Completed

1. **Coverage API `image_url`** (`backend/app/api/coverage.py`):
   - Added `"image_url": card_image_url(row.image_url)` to each card object in the `/api/coverage` response.
   - Uses the existing `card_image_url()` normalizer from `app.api.cards` (same as Memory/Cards endpoints).
   - `Card.image_url` column already existed; no migration needed.
   - Backward-compatible (only adds a field).

2. **`CardImageLightbox` component** (`frontend/src/components/cards/CardImageLightbox.tsx`, new):
   - Reusable modal/lightbox with `card: CardImageLightboxCard` and `onClose` props.
   - Shows card image (`max-h-[60vh] max-w-[80vw]`, rounded corners, shadow) or "No card image available." fallback.
   - Shows card name, set label, `tcgdex_id`, category, status badge, and missing effects.
   - Closes on: Escape key, backdrop click, close button (`aria-label="Close card preview"`).
   - `role="dialog"`, `aria-modal="true"`, inner panel stops click propagation.

3. **Coverage page updates** (`frontend/src/pages/Coverage.tsx`):
   - `CardCoverage` type gains `image_url?: string | null`.
   - `selectedCard: CardCoverage | null` state added.
   - Card name cell replaced with a `<button>` with hover-underline, accent color, `aria-label`, `data-testid`.
   - `<CardImageLightbox>` rendered when `selectedCard` is set; backdrop/Escape/close button dismiss it.
   - Sort, filter, and search behavior unchanged.

4. **Backend tests** (`backend/tests/test_api/test_coverage.py`, new — 5 tests):
   - Summary fields present; `image_url` in each card; null `image_url` returns null; missing-handler status; `test-002` excluded.

5. **Frontend tests** — 24 new tests across 2 new files:
   - `frontend/src/components/cards/CardImageLightbox.test.tsx` (12 tests).
   - `frontend/src/pages/Coverage.test.tsx` (12 tests).

### Validation (session 17)

| Command | Result |
|---|---|
| `cd backend && python3 -m pytest tests/test_api/test_coverage.py -v -q` | **5 passed** |
| `cd backend && python3 -m pytest tests/ -x -q` | **584 passed, 1 skipped** |
| `cd frontend && npm test -- --run` | **75 passed (8 files)** |
| `cd frontend && npm run build` | **✓ built in 4.28s** |

### Files Changed (session 17)

| File | Change |
|---|---|
| `backend/app/api/coverage.py` | Added `"image_url": row.image_url` to each card in response |
| `backend/tests/test_api/test_coverage.py` | New: 5 coverage API tests |
| `frontend/src/components/cards/CardImageLightbox.tsx` | New: reusable card image lightbox component |
| `frontend/src/components/cards/CardImageLightbox.test.tsx` | New: 12 lightbox component tests |
| `frontend/src/pages/Coverage.tsx` | `image_url` in type; `selectedCard` state; card name → button; lightbox rendered |
| `frontend/src/pages/Coverage.test.tsx` | New: 12 Coverage page tests |
| `docs/STATUS.md` | This file |
| `docs/CHANGELOG.md` | Session 17 entry added |

### Goal

Upgrade the live simulation console from a filtered event display into a complete verbose match transcript. Show all setup-phase events (opening hands with card names, coin flip, active/bench placement, prize setup), turn separators, per-turn draw with card names, and pass/end-turn — and keep AI reasoning in tile overlays only.

### Completed

1. **`_run_setup` enriched** (`backend/app/engine/runner.py`):
   - Emits `setup_start` with deck names before any draws.
   - After each player's opening draw, emits `opening_hand_drawn` (with `player`, `count`, and `cards=[card names]`).
   - `coin_flip` event was previously written to `state.events` but never sent via the callback; now emitted via `_emit` so it appears in live stream.
   - `prizes_set` event now includes `cards=[prize card names]` for full audit visibility.
   - Emits `setup_complete` with active Pokémon and bench counts for both players.
   - Emits `turn_start` (T1) at the end of setup so the console shows the turn-1 separator before the first action.

2. **`_run_turn` draw visible** (`backend/app/engine/runner.py`):
   - `prev_draw_len` is now captured *before* `_draw_cards`, and `_emit_since` is called immediately after — so turn-draw events are streamed live.
   - Previously the draw event sat in `state.events` but was only flushed much later in the first action's `_emit_since` window.

3. **`_end_turn` turn_start callback** (`backend/app/engine/runner.py`):
   - `turn_start` events for turns 2+ were emitted to `state.events` but not forwarded via the callback. Now calls `_emit(state.events[-1])` after appending.

4. **`_draw_cards` card names** (`backend/app/engine/runner.py`):
   - Tracks drawn card names in a local list; includes `cards=[names]` in the `draw` event.

5. **`_mulligan_redraw` new_hand** (`backend/app/engine/transitions.py`):
   - `mulligan` event now includes `new_hand=[card names]` so the console can show what was redrawn.

6. **`_emit` safe against bare `object.__new__` runners** (`backend/app/engine/runner.py`):
   - Changed `if self.event_callback` to `getattr(self, "event_callback", None)` so test helpers that use `object.__new__(MatchRunner)` without calling `__init__` don't get `AttributeError`.

7. **`LiveConsole.tsx` full rewrite of `fmt()`** (`frontend/src/components/simulation/LiveConsole.tsx`):
   - Added `fmtCards(cards, maxShow=8)` helper that truncates long lists with `…+N`.
   - Added format cases for: `setup_start`, `opening_hand_drawn`, `coin_flip`, `mulligan`, `place_active`, `place_bench`, `prizes_set`, `setup_complete`, `turn_start` (separator).
   - `draw` now shows card names when the `cards` field is present (`↓ Draw: Card A, Card B`); falls back to `↓ Draw ×N` for Supporter-emitted draws that lack `cards`.
   - `shuffle_deck` now renders `⟳ Shuffle deck` instead of the raw event name.
   - `turn_start` and `prizes_set` removed from the skip set — both render as visible rows.

8. **Backend tests** (`backend/tests/test_engine/test_runner_setup_events.py`, new):
   - 14 tests across 3 classes: `TestSetupEvents`, `TestDrawEventCards`, `TestMulliganEvent`.
   - `TestSetupEvents`: `setup_start` emitted; `opening_hand_drawn` for both players with card names; `coin_flip` emitted; `place_active`/`place_bench` emitted; `prizes_set` with card names; `setup_complete`; `turn_start` T1; setup event ordering.
   - `TestDrawEventCards`: DRAW-phase draw events include card names; `draw.count == len(draw.cards)` when `cards` is present; at least one DRAW-phase draw per turn emitted via callback.
   - `TestMulliganEvent`: `mulligan` includes `new_hand` list.

9. **Frontend tests updated** (`frontend/src/components/simulation/LiveConsole.test.tsx`):
   - Updated existing `turn_start` test (previously tested it was hidden; now tests it renders a separator).
   - Added `describe('LiveConsole — setup phase events')` with 8 new tests: `setup_start`, `opening_hand_drawn` (with names), `coin_flip`, `place_active`, `place_bench`, `prizes_set`, `setup_complete`, `mulligan`.
   - Added `describe('LiveConsole — draw event formatting')` with 3 new tests: draw with card names; draw without cards fallback; draw with empty cards fallback.

### Validation (session 16)

| Command | Result |
|---|---|
| `cd backend && python3 -m pytest tests/test_engine/test_runner_setup_events.py -x -q` | **14 passed** |
| `cd backend && python3 -m pytest tests/ -x -q` | **579 passed, 1 skipped** |
| `cd frontend && npm test -- --run` | **51 passed (6 files)** |
| `docker compose build backend celery-worker frontend` | **✓ all images built** |
| `docker compose up -d backend celery-worker celery-beat frontend` | **✓ deployed** |
| Backend health | **`{"status":"ok"}`** |

### Files Changed (session 16)

| File | Change |
|---|---|
| `backend/app/engine/runner.py` | `_run_setup` emits setup_start/opening_hand_drawn/coin_flip/prizes_set(+cards)/setup_complete/turn_start; `_run_turn` draw via `_emit_since`; `_end_turn` calls `_emit` for turn_start; `_draw_cards` includes card names; `_emit` uses `getattr` for safety |
| `backend/app/engine/transitions.py` | `_mulligan_redraw` includes `new_hand` in mulligan event |
| `backend/tests/test_engine/test_runner_setup_events.py` | New: 14 tests for setup event emission |
| `frontend/src/components/simulation/LiveConsole.tsx` | Full `fmt()` rewrite; `fmtCards()` helper; all setup events formatted; turn_start separator; draw with card names; shuffle_deck readable |
| `frontend/src/components/simulation/LiveConsole.test.tsx` | Updated turn_start test; +11 new tests |
| `docs/STATUS.md` | This file |
| `docs/CHANGELOG.md` | Session 16 entry added |

## Session 15 Work (2026-05-08)

### Goal

Emergency stabilization: fix a live simulation crash caused by an invalid import,
attach AI reasoning directly to visible events, make pass/end_turn visible in
the console, and restrict the AI Reasoning overlay to action-type events.

### Root Cause — Runtime Crash

`backend/app/engine/effects/attacks.py` (`_fluorite`) and
`backend/app/engine/effects/trainers.py` (`_wallys_compassion`) each contained
a bad lazy import: `from app.cards.loader import card_registry as _cr`. This
module does not export `card_registry`; the correct import is
`from app.cards import registry as card_registry` (already present at module
level in both files). The lazy imports were redundant and broken — they caused
`ImportError: cannot import name 'card_registry' from 'app.cards.loader'` the
first time either function was called during a live simulation.

### Root Cause — AI Reasoning Still Not Appearing in Overlay

The prior correlation approach (hidden `ai_decision` events emitted before
`StateTransition.apply`) was fragile at live runtime: event index positions
could drift when extra events were emitted by transitions, and
`liveEvents.indexOf(event)` could return stale positions. More importantly,
`pass` and `end_turn` events were filtered out of `liveEvents` entirely
(because LiveConsole was skipping them), so the clicked event index was always
−1 for those actions.

### Root Cause — Missing Turn Display (Turns 13–14 Vanish)

`LiveConsole.tsx` was hiding `end_turn` and `pass` event types with
`skip: true`. If a player's only action on a turn was to pass or end their turn,
no visible row appeared and the turn looked like it vanished.

### Root Cause — simulation_error Showing AI Reasoning

`EventDetail.tsx` rendered the AI Reasoning section for all events whenever
`isAiMode` was true. `simulation_error` is a lifecycle/system event, not an AI
action, so it should never have an AI Reasoning section.

### Completed

1. **Fix `_fluorite` bad import** (`backend/app/engine/effects/attacks.py`):
   Removed the bad `from app.cards.loader import card_registry as _cr` lazy
   import. Changed `_cr.get()` to `card_registry.get()` using the module-level
   import that was already present.

2. **Fix `_wallys_compassion` bad import** (`backend/app/engine/effects/trainers.py`):
   Same fix — removed bad lazy import, uses module-level `card_registry.get()`.

3. **Import smoke test** (`backend/tests/test_engine/test_import_smoke.py`, new):
   10 tests covering all simulation stack modules (runner, transitions, attacks,
   abilities, trainers, energies, batch, tasks.simulation) plus AST-level guards
   confirming no `from app.cards.loader import card_registry` pattern exists in
   `attacks.py` or `trainers.py`.

4. **Replace `_maybe_emit_ai_decision` with `_annotate_action_events_with_ai_reasoning`**
   (`backend/app/engine/runner.py`):
   New method annotates visible events in `state.events[prev_len:]` directly
   with `ai_reasoning`, `ai_action_type`, `ai_card_played`, `ai_target`, and
   `ai_attack_index` *after* `StateTransition.apply()` emits them but *before*
   `_emit_since()` publishes them. This means every published event already
   carries reasoning. All 3 `_maybe_emit_ai_decision` call sites in `_run_turn`
   updated. Hidden `ai_decision` events no longer emitted.

5. **Runner annotation tests** (`backend/tests/test_engine/test_runner_annotation.py`, new):
   8 unit tests: ATTACH_ENERGY annotates `energy_attached`; EVOLVE annotates
   `evolved`; ATTACK annotates all attack events; PASS annotates `pass`; END_TURN
   annotates `end_turn`; no reasoning → no annotation; only events after
   `prev_len` annotated; optional fields absent when action fields are None.

6. **Updated `TestMaybeEmitAiDecision`** (`backend/tests/test_players/test_ai_player.py`):
   Renamed/updated all 5 tests to use the new
   `_annotate_action_events_with_ai_reasoning` method (tests now pre-populate
   events and verify annotation rather than checking for emitted `ai_decision`
   events).

7. **LiveConsole pass/end_turn rows** (`frontend/src/components/simulation/LiveConsole.tsx`):
   Removed `end_turn` and `pass` from the skip set. Added explicit format cases:
   `pass` → `T{N} [{player}] · Pass`; `end_turn` → `T{N} [{player}] · End turn`.

8. **EventDetail AI Reasoning allowlist** (`frontend/src/components/simulation/EventDetail.tsx`):
   Added `AI_REASONING_EVENT_TYPES` set — an explicit allowlist of event types
   that can show an AI Reasoning section (all action types: energy_attached,
   evolved, attack variants, trainer plays, pass, end_turn, use_ability, etc.).
   `simulation_error` and all lifecycle events not in the list. AI annotation
   fields (`ai_reasoning`, `ai_action_type`, `ai_card_played`, `ai_target`,
   `ai_attack_index`) added to `SKIP_KEYS` so they don't appear in the raw
   Event Data section.

9. **Frontend tests**:
   - `LiveConsole.test.tsx` (4 → 7 tests): `pass` renders "Pass"; `end_turn`
     renders "End turn"; `turn_start` still hidden.
   - `EventDetail.test.tsx` (11 → 16 tests): `simulation_error` has no AI
     Reasoning section; lifecycle events have no AI Reasoning section; `pass`
     with direct `ai_reasoning` shows it; `end_turn` with direct `ai_reasoning`
     shows it; `pass` without reasoning shows "has not been persisted yet".

### Validation (session 15)

| Command | Result |
|---|---|
| `cd backend && python3 -m pytest tests/test_engine/test_import_smoke.py tests/test_engine/test_runner_annotation.py -q` | **18 passed** |
| `cd backend && python3 -m pytest tests/ -x -q` | **565 passed, 1 skipped** |
| `cd frontend && npm test -- --run` | **40 passed (6 files)** |
| `cd frontend && npm run build` | **✓ built in 4.33s** |
| `docker compose build backend celery-worker frontend && docker compose up -d ...` | **✓ deployed** |
| Backend container import smoke | **backend import smoke OK** |
| Celery-worker container import smoke | **worker import smoke OK** |

### Files Changed (session 15)

| File | Change |
|---|---|
| `backend/app/engine/effects/attacks.py` | Removed bad `from app.cards.loader import card_registry` in `_fluorite` |
| `backend/app/engine/effects/trainers.py` | Removed bad `from app.cards.loader import card_registry` in `_wallys_compassion` |
| `backend/app/engine/runner.py` | Replaced `_maybe_emit_ai_decision` with `_annotate_action_events_with_ai_reasoning`; updated 3 call sites |
| `backend/tests/test_engine/test_import_smoke.py` | New: 10 import smoke tests |
| `backend/tests/test_engine/test_runner_annotation.py` | New: 8 annotation unit tests |
| `backend/tests/test_players/test_ai_player.py` | Updated `TestMaybeEmitAiDecision` class to test new annotation method |
| `frontend/src/components/simulation/LiveConsole.tsx` | `pass`/`end_turn` now render visible rows; `turn_start` remains hidden |
| `frontend/src/components/simulation/EventDetail.tsx` | Added `AI_REASONING_EVENT_TYPES` allowlist; AI fields added to `SKIP_KEYS` |
| `frontend/src/components/simulation/LiveConsole.test.tsx` | +3 tests (pass, end_turn render; turn_start hidden) |
| `frontend/src/components/simulation/EventDetail.test.tsx` | +5 tests (simulation_error; lifecycle events; pass/end_turn with direct reasoning) |
| `docs/STATUS.md` | This file |
| `docs/CHANGELOG.md` | Session 15 entry added |

### Goal

Fix the live simulation UI so that clicking a decision/action event in the live console during an AI/H or AI/AI simulation opens the overlay with AI reasoning already populated — not just after the simulation completes.

### Root Cause

`AIPlayer._record_decision()` stores reasoning in `pending_decisions` immediately after choosing an action, but `drain_decisions()` is only called after the entire match finishes in `batch.py`. `MatchMemoryWriter.write_decisions()` writes to Postgres only after a `match_id` exists — also post-match.

`EventDetail.tsx` guarded its DB query on `event.match_id`, which is never present on live WebSocket events. Result: the AI Reasoning section always showed "No AI decision recorded" during a running simulation.

### Completed

1. **Live `ai_decision` engine event** (`backend/app/engine/runner.py`):
   - Added `MatchRunner._maybe_emit_ai_decision(state, pid, action)` helper.
   - Calls `state.emit_event("ai_decision", ...)` with `player`, `action_type`,
     `card_played`, `target`, `reasoning`, and `attack_index` when `action.reasoning` is set.
   - Called at all three strategic decision sites in `_run_turn()`: main-phase loop,
     attack-phase block, and Festival Lead second attack.
   - Filters naturally: only `AIPlayer` sets `action.reasoning`; heuristic/greedy
     players leave it `None`, so no event is emitted for non-AI decisions.
   - The event is captured by `_emit_since()` and published through the existing
     Redis → WebSocket pipeline with no changes to `simulation.py`.

2. **Frontend overlay live reasoning** (`frontend/src/components/simulation/EventDetail.tsx`):
   - Added `liveEvents?: NormalisedEvent[]` prop.
   - Added `eventToDecisionRow()` helper: converts a live `ai_decision` event to a
     `DecisionRow` for uniform rendering.
   - Added `findLiveDecision()` helper: if the clicked event IS an `ai_decision`, uses
     it directly; otherwise searches backwards from `clickedIndex` for the nearest
     prior `ai_decision` with matching `turn`, `player`, and `action_type`.
   - Live decision is computed synchronously — no `useEffect`, no async delay.
   - Live reasoning blocks are tagged with a `live` badge (`data-testid="event-detail-live-reasoning"`).
   - DB fetch still runs when `event.match_id` is present (post-completion enrichment).
   - "No AI decision recorded" message updated to "AI reasoning has not been persisted yet."

3. **`SimulationLive.tsx`** — passes `liveEvents={events}` to `<EventDetail>`.

4. **`LiveConsole.tsx`** — added `ai_decision` case: renders compact
   `🤖 ACTION_TYPE — "reasoning preview…"` in purple, clickable like any other event.
   **NOTE: This visible rendering was removed in session 14** — `ai_decision` events
   should not appear as console rows; reasoning belongs only in the tile overlay.

### Validation (session 13)

| Command | Result |
|---|---|
| `cd backend && python3 -m pytest tests/test_players/test_ai_player.py -q` | **25 passed** |
| `cd backend && python3 -m pytest tests/ -x -q` | **547 passed, 1 skipped** |
| `cd frontend && npm test -- --run` | **24 passed (5 files)** |
| `cd frontend && npm run build` | **✓ built in 4.10s** |
| `git diff --check` | Clean |

### Files Changed (session 13)

| File | Change |
|---|---|
| `backend/app/engine/runner.py` | Added `_maybe_emit_ai_decision()` helper; 3 call sites in `_run_turn()` |
| `backend/tests/test_players/test_ai_player.py` | Updated `GameStateStub` with `emit_event()`; added `TestMaybeEmitAiDecision` class (5 tests) |
| `frontend/src/components/simulation/EventDetail.tsx` | Added `liveEvents` prop, `findLiveDecision()`, `eventToDecisionRow()`, live-before-DB render logic |
| `frontend/src/components/simulation/LiveConsole.tsx` | Added `ai_decision` match-event case |
| `frontend/src/pages/SimulationLive.tsx` | Pass `liveEvents={events}` to `<EventDetail>` |
| `frontend/src/components/simulation/EventDetail.test.tsx` | New: 7 tests for live reasoning, correlation, DB fallback, H/H mode |
| `docs/STATUS.md` | This file |
| `docs/CHANGELOG.md` | Session 13 entry added |

## Session 12 Work (2026-05-06)

### Goal

Resolve four remaining STATUS.md effect-engine gaps:
1. Metrics inconsistency between Authoritative Metrics table and session notes.
2. `incoming_damage_reduction` timing bug (cleared before opponent attacks).
3. Three NOOP stubs: Iron Defender, Premium Power Pro, Cinderace Explosiveness.
4. Missing public-path coverage for Risky Ruins evolved special-effect bench placement.

### Completed

1. **STATUS.md metrics table corrected** — Authoritative Metrics table updated to `542 passed,
   1 skipped` (session 12 baseline). Historical counts preserved with session labels.
   Root cause: the old `504/7` figure was session 10 without Postgres running (DB-integration
   tests in `test_scheduled.py` were skipped). Session 11 with the full stack running was
   `522/1`. Session 12 adds 20 new tests → `542/1`.

2. **`incoming_damage_reduction` timing fix** (`backend/app/engine/runner.py`):
   - The bug: `_end_turn()` unconditionally reset `incoming_damage_reduction = 0` for ALL
     Pokémon of BOTH players at the end of every turn, destroying protection set by the current
     player before the opponent had a chance to attack.
   - Fix: moved `incoming_damage_reduction` resets (for `.active` and all `.bench` Pokémon)
     inside the `if pid != current_pid:` block, mirroring the existing pattern already used
     for `attack_damage_reduction` and `cant_retreat_next_turn`.

3. **Jasmine's Gaze new-Pokémon clause** (`backend/app/engine/effects/trainers.py`):
   - Added `player.opponent_next_turn_all_reduction += 30` alongside existing per-Pokémon
     reduction. This covers Pokémon that come into play AFTER the effect fires.
   - Added `opponent_next_turn_all_reduction: int = 0` to `PlayerState` (`state.py`).
   - Applied in `_apply_damage()` (`attacks.py`): checked for the defender's player state.
   - Cleared in `_end_turn()` at `pid != current_pid` (same timing as per-card reduction).

4. **Iron Defender (me01-118)** — NOOP stub replaced with real implementation:
   - `_iron_defender_b18` now sets `player.metal_type_damage_reduction += 30`.
   - Added `metal_type_damage_reduction: int = 0` to `PlayerState`.
   - Applied in `_apply_damage()`: if defender player has `metal_type_damage_reduction > 0`
     and the defender is Metal-type, subtract it from total damage.
   - Cleared at `pid != current_pid` in `_end_turn()`.
   - Card text: "During your opponent's next turn, all of your {M} Pokémon take 30 less
     damage from attacks … (includes new Pokémon that come into play)."

5. **Premium Power Pro (me01-124 / me02.5-199)** — NOOP stub replaced with real implementation:
   - `_premium_power_pro_b18` now sets `player.fighting_pokemon_damage_bonus += 30`.
   - Added `fighting_pokemon_damage_bonus: int = 0` to `PlayerState`.
   - Applied in `_apply_damage()`: if attacker player has bonus > 0 and attacker is Fighting-type,
     bonus is added BEFORE W/R and defense effects (matches "before applying Weakness and Resistance").
   - Cleared at `pid == current_pid` in `_end_turn()` (same-turn effect).
   - Corrected the previous NOOP comment: card text says YOUR Fighting Pokémon, not "each player's".

6. **Cinderace Explosiveness (me01-028)** — setup-phase placement hooks implemented:
   - `RuleEngine.deck_has_basic()` (`rules.py`): recognizes `me01-028` as a valid starting card.
   - `ActionValidator._setup_actions()` (`actions.py`): includes `me01-028` in `PLACE_ACTIVE`
     options during SETUP phase (alongside Basics).
   - `RandomPlayer.choose_setup()` and `BasePlayer.choose_setup()` (`players/base.py`):
     include `me01-028` in Basic-eligible candidates for Active slot selection.
   - Card text: "If this Pokémon is in your hand when you are setting up to play, you may put
     it face down in the Active Spot."

7. **Risky Ruins `bench_pokemon_from_effect` helper** (`backend/app/engine/transitions.py`):
   - Added public `bench_pokemon_from_effect(state, player_id, card, source_zone, *, allow_evolved=False)`.
   - Moves a Pokémon from any source zone to the Bench via a card effect.
   - Enforces bench size limit; rejects evolved Pokémon unless `allow_evolved=True`.
   - Triggers Risky Ruins (me01-127) for Basic non-Darkness Pokémon exactly as the standard
     `_play_basic` and `_place_bench` paths do.
   - Emits `bench_from_effect` and optionally `risky_ruins_damage` events.

### Validation (session 12)

| Command | Result |
|---|---|
| `cd backend && python3 -m pytest tests/test_engine/test_audit_fixes.py -q` | **140 passed** |
| `cd backend && python3 -m pytest tests/ -x -q` | **542 passed, 1 skipped** |
| `git diff --check` | Clean |

### Files Changed (session 12)

| File | Change |
|---|---|
| `backend/app/engine/state.py` | Added `metal_type_damage_reduction`, `opponent_next_turn_all_reduction`, `fighting_pokemon_damage_bonus` to `PlayerState` |
| `backend/app/engine/runner.py` | Fixed `incoming_damage_reduction` timing in `_end_turn()`; added clearing of new player-level fields |
| `backend/app/engine/effects/attacks.py` | Added player-level bonus/reduction checks in `_apply_damage()` |
| `backend/app/engine/effects/trainers.py` | Replaced Iron Defender NOOP; replaced Premium Power Pro NOOP; updated Jasmine's Gaze with player-level reduction |
| `backend/app/engine/rules.py` | Updated `deck_has_basic()` to recognize `me01-028` (Explosiveness) |
| `backend/app/engine/actions.py` | Updated `_setup_actions()` to include `me01-028` as PLACE_ACTIVE |
| `backend/app/players/base.py` | Updated `RandomPlayer.choose_setup()` and `BasePlayer.choose_setup()` for Explosiveness |
| `backend/app/engine/transitions.py` | Added `bench_pokemon_from_effect()` public helper |
| `backend/tests/test_engine/test_audit_fixes.py` | +20 tests for all four fixed gaps |
| `docs/STATUS.md` | This file |
| `docs/CHANGELOG.md` | Session 12 entry added |

### Audit discipline

This was **not** an audit session. `docs/AUDIT_STATE.md` was not advanced.
No DB-backed audit was performed. Cursor is unchanged.



### Goal

Fix the GitHub Actions Playwright E2E workflow. The `Run database migrations` step was
failing because `backend/alembic/env.py` read `sqlalchemy.url` from `backend/alembic.ini`
(hardcoded `localhost:5433`) instead of using the `DATABASE_URL` env var already set in
the container environment. This caused Alembic to attempt a connection to `localhost:5433`
from inside the Docker container, which fails.

### Completed

1. **`backend/alembic/env.py` — honor `DATABASE_URL` env var:**
   - Added `os.environ.get("DATABASE_URL")` override after `config = context.config`.
   - When `DATABASE_URL` is set (e.g. inside Docker containers), it overrides
     `alembic.ini`'s hardcoded `localhost:5433` URL.
   - Local development fallback through `alembic.ini` is preserved when
     `DATABASE_URL` is not set.

2. **`.github/workflows/e2e.yml` — explicit container-network URLs in `.env`:**
   - Added `DATABASE_URL`, `REDIS_URL`, `NEO4J_URI`, `OLLAMA_BASE_URL` to the
     `cat > .env` heredoc. Makes CI intent explicit and belt-and-suspenders.

3. **`.github/workflows/e2e.yml` — strengthened migration step:**
   - Env sanity check: asserts `DATABASE_URL` does not contain `localhost` and
     does contain `postgres:5432` before running Alembic.
   - Postgres reachability check: writes a small asyncpg script to the runner,
     `docker cp`s it into the backend container, and retries (up to 60s) until
     `SELECT 1` succeeds. Confirms Postgres is reachable from inside the container
     before `alembic upgrade head`.

4. **`.github/workflows/e2e.yml` — added "Seed card pool" step:**
   - Runs `docker compose exec -T backend python /app/scripts/seed_cards.py`
     after migrations. Required for the coverage-page E2E test and deck-builder
     full-stack tests to have real card data.

5. **`.github/workflows/e2e.yml` — added Docker diagnostics on failure:**
   - `if: failure()` step dumps `docker compose ps` + 200-line tail of postgres,
     backend, celery-worker, and frontend logs before the Playwright artifact upload.

### Frontend startup note

`frontend/playwright.config.ts` uses a `webServer` directive that automatically
starts the Vite dev server (`npm run dev -- --host 127.0.0.1 --port 4173`) when
Playwright runs. The Vite dev server proxies `/api` and `/socket.io` to
`http://localhost:8000` (the mapped Docker backend port). The Docker `frontend`
container does not need to be started in CI — Playwright handles it.

### Validation (session 11)

| Command | Result |
|---|---|
| `docker compose exec -T backend alembic upgrade head` | Exit 0, migrations applied via `postgres:5432` |
| asyncpg Postgres check from inside container | `Postgres reachable from backend container` |
| `cd backend && python3 -m pytest tests/ -x -q` | **522 passed, 1 skipped** (with full stack running; DB-integration tests from test_scheduled.py execute because Postgres is reachable) |
| `cd frontend && npm test -- --run --reporter=dot` | **17 passed (4 files)** |
| `cd frontend && npm run build` | Build succeeded |
| `git diff --check` | Clean |

### Files Changed (session 11)

| File | Change |
|---|---|
| `backend/alembic/env.py` | Added `DATABASE_URL` env override; added `import os` |
| `.github/workflows/e2e.yml` | Added container-network URLs to `.env`; strengthened migration step; added seed step; added Docker diagnostics |
| `docs/STATUS.md` | This file |
| `docs/CHANGELOG.md` | Session 11 entry added |

### Audit discipline

This was **not** an audit session. `docs/AUDIT_STATE.md` was not advanced.
No DB-backed audit was performed. Cursor is unchanged.

## Session 10 Work (2026-05-05)

### Goal

Fix the Session 8 fault-injection finding: worker crash blocks the simulation queue for up to 1 hour (Redis/Celery default visibility timeout). Add conservative application-level stale-running detection and safe recovery using opponent-batch checkpointing semantics.

### Completed

1. **Stale-running detection added** (`backend/app/tasks/simulation.py`):
   - `SIMULATION_STALE_RUNNING_MINUTES` constant (default `45`), overridable via `SIMULATION_STALE_RUNNING_MINUTES` env var.
   - `_classify_stale_simulation(db, sim, cutoff)` — returns `'skip'` / `'requeue'` / `'fail'`:
     - `'skip'`: simulation started recently, OR any checkpoint was updated after the cutoff (worker may still be alive).
     - `'requeue'`: stale + no checkpoints, or stale + only zero-persisted running/complete checkpoints.
     - `'fail'`: stale + running checkpoint has partial nonzero `matches_completed` (unsafe to replay without creating duplicate match rows).
   - `_recover_stale_running_simulations(SessionFactory, stale_minutes)` — queries all `running` sims older than threshold with `SELECT FOR UPDATE SKIP LOCKED`, classifies each, then either resets to `queued` (with `error_message` explaining the recovery) or marks `failed`.

2. **`_dispatch_next_queued()` extended** — Phase 0 calls `_recover_stale_running_simulations()` before the active-count check. Recovery errors are caught and logged as non-fatal warnings (they must not block normal dispatch).

3. **Concurrent delivery guard added** to `_run_simulation_async()` — Initial `SELECT` upgraded to `SELECT ... FOR UPDATE`; if `sim.status == 'running'` at task start, the worker bails immediately with `{"status": "skipped_duplicate_delivery"}`. This prevents two concurrent workers (stale recovery re-dispatches at T+45m AND Redis eventually redelivers the original unacked message at T+60m) from processing the same simulation.

4. **12 tests added** (`backend/tests/test_tasks/test_scheduled.py`):
   - `TestClassifyStaleSimulation` (6 DB integration tests, skipped when Postgres unreachable):
     - Fresh sim is never classified stale.
     - Stale sim + no checkpoints → requeue.
     - Stale sim + zero-persisted running checkpoint → requeue.
     - Stale sim + completed checkpoints → requeue.
     - Stale sim + partial nonzero running checkpoint → fail.
     - Stale sim but checkpoint updated recently → skip.
   - `TestRecoverStaleRunningSimulations` (2 DB integration tests):
     - Stale requeue changes status to `queued`.
     - Fresh sim not recovered.
   - `TestDispatchQueuedSimulation` (2 mock-based tests, always run):
     - Active running sim blocks dispatch.
     - No active sim dispatches queued.
   - `TestStaleThresholdConfigurable` (2 unit tests, always run):
     - Default threshold is set and positive.
     - `_classify_stale_simulation` respects explicit cutoff overrides.

5. **Live validation** — Injected a fake stale `running` simulation with `started_at = now() - 90 minutes`. Triggered `advance_simulation_queue` manually. Observed in worker logs:
   ```
   Stale-running recovery: requeuing simulation f99c41dc... (started_at=2026-05-05 09:31:54..., threshold=45 min)
   Queue: stale-running recovery affected 1 simulation(s): ['f99c41dc...']
   Queue: dispatched simulation f99c41dc...
   ```
   Simulation recovered and ran to `complete`. Disposable sim deleted. Queue depth 0.

6. **Celery-worker rebuilt** with updated `simulation.py`.

### Validation (session 10)

| Command | Result |
|---|---|
| `python3 -m pytest tests/test_tasks/test_scheduled.py -q` | **12 passed** |
| `cd backend && python3 -m pytest tests/ -x -q` | **490 passed, 1 skipped** |
| Live fault injection | Stale sim detected and requeued within 60s Beat cycle |

### Files Changed (session 10)

| File | Change |
|---|---|
| `backend/app/tasks/simulation.py` | Added `SIMULATION_STALE_RUNNING_MINUTES`, `_classify_stale_simulation`, `_recover_stale_running_simulations`; extended `_dispatch_next_queued` (Phase 0 recovery); added concurrent delivery guard in `_run_simulation_async` |
| `backend/tests/test_tasks/test_scheduled.py` | **New file** — 12 tests |
| `docs/HARDENING_SWEEP_REPORT.md` | Section 7B updated with implementation and live validation evidence |
| `docs/STATUS.md` | This file |
| `docs/CHANGELOG.md` | Session 10 entry added |

### Audit discipline

This was **not** an audit session. `docs/AUDIT_STATE.md` was not advanced.
No DB-backed audit was performed. Cursor is unchanged.

## Session 9 Work (2026-05-05)

### Goal
Add focused regression tests for the five handler bugs fixed in Session 8
(commit `b7af4b7`). No new features. No audit cursor advancement.

### Completed

1. **14 regression tests added** (`backend/tests/test_engine/test_audit_fixes.py`):
   - Ninjask Cast-Off Shell (me01-017): 2 tests — Shedinja benched; no-Shedinja no-op
   - Clawitzer Fall Back to Reload (me01-038): 3 tests — hand-only, Water-only,
     max_count=2; condition true/false
   - Grumpig Energized Steps (me01-063): 1 test — top-4 only, any Basic Energy,
     active+bench targets, any number of attachments
   - Fighting Gong (me01-116): 1 test — Basic included; Stage 1/2 excluded
   - Risky Ruins (me01-127): 5 tests — Basic non-Darkness damaged; Darkness no damage;
     evolved no damage; `_play_basic` non-Darkness and Darkness cases; `_place_bench` evolved

2. **2 latent handler bugs fixed** (`backend/app/engine/effects/abilities.py`) — found
   while authoring the regression tests above:
   - `_fall_back_to_reload` / `_cond_fall_back_to_reload`: called `_energy_provides_type`
     which was never imported in `abilities.py` (defined in `trainers.py`). Any game with
     Clawitzer and Water Energy in hand would fire a `NameError` at runtime.
     Fix: inlined as `"Water" in (c.energy_provides or [])`.
   - `_energized_steps`: `state.emit_event(...)` referenced `action.card_def_id` which
     does not exist on `Action` (has `card_instance_id`). Every Grumpig Energized Steps
     resolution would fire `AttributeError`. Fix: replaced with `action.card_instance_id or ""`.

3. **Docker stack rebuilt and restarted** — celery-worker rebuilt after `abilities.py`
   change; full stack `down && up`; worker confirmed healthy.

### Validation (session 9)

| Command | Result |
|---|---|
| `python3 -m pytest tests/test_engine/test_audit_fixes.py -q` | 88 passed |
| `cd backend && python3 -m pytest tests/ -x -q` | **478 passed, 1 skipped** |
| `docker compose ps` | All 8 services Up/healthy |
| `docker compose logs celery-worker` | `celery@... ready.` — clean start |

Frontend not run — no frontend files changed this session.

### Files Changed (session 9)

| File | Change |
|---|---|
| `backend/app/engine/effects/abilities.py` | Fixed `_energy_provides_type` NameError (×2) and `action.card_def_id` AttributeError |
| `backend/tests/test_engine/test_audit_fixes.py` | +14 regression tests |
| `docs/HARDENING_SWEEP_REPORT.md` | Session 9 header + regression coverage table added |
| `docs/STATUS.md` | This file |
| `docs/CHANGELOG.md` | Session 9 entry added |

Commit: `980e510` — pushed to `origin/main`. Working tree clean.

### Audit discipline

This was **not** an audit session. `docs/AUDIT_STATE.md` was not advanced.
No DB-backed audit was performed. Cursor is unchanged.

## Known Issues / Gaps

| Issue | Status | Notes |
|---|---|---|
| Section 7B Redis stale-running simulation gap | **Fixed (session 10)** | Application-level stale detection added to `_dispatch_next_queued`. Default threshold: 45 minutes (overridable via `SIMULATION_STALE_RUNNING_MINUTES` env var). See session 10 notes. |
| "Opponent's next turn" damage-reduction timing | **Fixed (session 12)** | `incoming_damage_reduction` reset moved to `pid != current_pid` block in `_end_turn()`. Player-level `opponent_next_turn_all_reduction` and `metal_type_damage_reduction` added for new-Pokémon clause. |
| Iron Defender / Premium Power Pro / Cinderace Explosiveness | **Fixed (session 12)** | Iron Defender: `metal_type_damage_reduction` player-level field. Premium Power Pro: `fighting_pokemon_damage_bonus` player-level field. Cinderace: `deck_has_basic` + `_setup_actions` + `choose_setup` updated. |
| me01-127 Risky Ruins evolved-placement via special effects | **Fixed (session 12)** | `bench_pokemon_from_effect()` helper in `transitions.py` provides public effect-path with Risky Ruins trigger. 4 new tests added. |

## Immediate Next Steps

1. **Rebuild celery-worker** with updated engine files:
   `docker compose build celery-worker && docker compose up -d celery-worker`
2. **Next recommended task:** Resume DB-backed card-effect audit from current
   `docs/AUDIT_STATE.md` cursor. Run `docs/AUDIT_RULES.md` workflow.
3. **Or:** Run AI/AI or coach simulations now that the stack is clean and all
   known handler bugs are fixed.

## Operational Caveats

- Any change under `backend/app/engine/effects/` requires rebuilding the celery worker:
  `docker compose build celery-worker && docker compose up -d celery-worker`
- **Stale-running recovery:** simulations stuck `running` for more than `SIMULATION_STALE_RUNNING_MINUTES` (default 45) with no checkpoint activity are automatically requeued by the `advance_simulation_queue` beat task. Set the env var to adjust. Simulations with partial nonzero checkpoint data are marked `failed` rather than requeued (safe default).
- `EnergyAttachment` uses `source_card_id=`, not `card_id=`.
- Do not commit `frontend/node_modules`.
- Do not advance `docs/AUDIT_STATE.md` without performing a real DB-backed audit per `docs/AUDIT_RULES.md`.
- Do not reset the database unless explicitly instructed.

## Current Commands

```bash
# Services
make up
make down
make build
make restart
make ps
make logs
make logs-all

# Database
make migrate
make seed

# Tests and checks
make test
make test-engine
make test-cards
make lint
cd frontend && npm test
cd frontend && npm run build
cd frontend && npm run test:e2e -- --list
docker compose config --quiet
```

## Read This First

- Current state and operations: `docs/STATUS.md`
- Historical changes and evidence: `docs/CHANGELOG.md`
- Active card audit workflow: `docs/AUDIT_RULES.md` and `docs/AUDIT_STATE.md`
- Historical architecture blueprint: `docs/PROJECT.md`
- Public setup/onboarding: `README.md`
- Supporting proposals and assessments: `docs/proposals/*.md`