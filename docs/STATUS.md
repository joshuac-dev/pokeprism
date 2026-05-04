# PokePrism - Current Status

> Read this first for current operational state. This file is the live handoff.
> `docs/PROJECT.md` is historical architecture context, not the active source
> of truth for implementation status.

Last updated: 2026-05-04 (session 4)

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
| Local cards table | 2,027 rows from `docker compose exec postgres psql -U pokeprism -d pokeprism -c "SELECT count(*) FROM cards;"` on 2026-05-04 |
| Coverage endpoint snapshot | 2,026 auditable cards, 1,734 implemented, 292 flat-only, 0 missing, 100.0% from direct `backend` container call to `app.api.coverage.get_coverage()` on 2026-05-04 |
| Local matches table | 6,900 rows from the same DB snapshot |
| Local `card_performance` table | 270 rows from the same DB snapshot |
| Running simulations | 0 from the same DB snapshot |
| Backend test baseline | Latest full documented run for the Neo4j graph optimization workstream: **439 passed** on 2026-05-04. Run with `cd backend && python3 -m pytest tests/ -x -q`. Historical prior baseline: 424 passed after the simulation queue work. |
| Frontend unit tests | 4 passed on 2026-05-04 with `cd frontend && npm test -- --run --reporter=dot` |
| Playwright E2E inventory | 14 tests listed on 2026-05-04 with `cd frontend && npm run test:e2e -- --list` |
| Effect import smoke | Passed on 2026-05-04 with `docker compose exec backend python -c "import app.engine.effects.attacks; import app.engine.effects.trainers; import app.engine.effects.energies; import app.engine.effects.abilities; import app.engine.effects.base"` |

## Session 2 Work (2026-05-04)

Three features completed:

1. **Precious Trolley handler (sv08-185)** — ACE SPEC trainer that benches up to
   all available bench spaces worth of Basic Pokémon from deck. Generator-based
   handler with ChoiceRequest. Registered as `sv08-185` in the Ace Spec block of
   `trainers.py`. 3 tests added.

2. **Neutralization Zone handler (sv06.5-060)** — Stadium registered as `_noop`
   (passive). Passive damage prevention added to `_apply_damage` in `attacks.py`:
   if the attacker has `has_rule_box` and the defender does not, damage is zeroed.
   `IRRECOVERABLE_FROM_DISCARD` frozenset added to `base.py` (contains
   `sv06.5-060`); `is_recoverable_from_discard()` helper applied to Pal Pad and
   Miracle Headset candidate filtering as forward-defense. 7 tests added (3
   damage-prevention, 4 irrecoverable-from-discard).

3. **Simulation queue (one-at-a-time)** — Only one simulation runs at a time.
   New sims check `active_count` (pending + running); if >0 they are created as
   `queued` and not dispatched. `_dispatch_next_queued()` uses `SELECT FOR UPDATE
   SKIP LOCKED` to atomically claim the oldest queued sim on every task
   completion. A Beat safety-net task (`advance_simulation_queue`) runs every
   60 seconds to recover from worker crashes. Celery worker concurrency reduced
   from 2 → 1 in `docker-compose.yml`. `'queued'` added to status unions in
   `frontend/src/types/history.ts` and `frontend/src/types/simulation.ts`.
   `cancel_simulation` also handles queued sims and triggers dispatch.

Files changed (sessions 2–3):
- `backend/app/engine/effects/trainers.py` — Precious Trolley handler + NZ noop registration + sv08.5-097/098/099 alt registrations
- `backend/app/engine/effects/attacks.py` — Neutralization Zone passive damage check + svp-173/200/208 alt registrations
- `backend/app/engine/effects/abilities.py` — svp-173 Boosted Evolution passive registration
- `backend/app/engine/effects/base.py` — IRRECOVERABLE_FROM_DISCARD + is_recoverable_from_discard()
- `backend/app/api/simulations.py` — queue-aware create/cancel
- `backend/app/tasks/simulation.py` — _dispatch_next_queued(), run_simulation modified
- `backend/app/tasks/scheduled.py` — advance_simulation_queue Beat task
- `backend/app/tasks/celery_app.py` — Beat schedule entry
- `backend/tests/test_engine/test_audit_fixes.py` — 10 new tests (411→424 total)
- `docker-compose.yml` — --concurrency=2 → --concurrency=1
- `frontend/src/types/history.ts` — 'queued' added to status union
- `frontend/src/types/simulation.ts` — 'queued' added to status union
- `frontend/src/components/history/StatusBadge.tsx` — 'queued' entry with distinct style/label
- `frontend/src/components/history/FilterBar.tsx` — 'Queued' option added to status filter

## Session 3 Work (2026-05-04)

Six missing handler registrations fixed (all alt prints — no new handler logic):

- **sv08.5-097, sv08.5-098, sv08.5-099** (Black Belt's Training alts) — registered
  to existing `_black_belt_training` in `trainers.py`.
- **svp-173** (Eevee alt) — attack registered to `_reckless_charge_eevee` in
  `attacks.py`; Boosted Evolution passive registered as noop in `abilities.py`.
- **svp-200** (Eevee alt) — attack registered to `_call_for_family` in `attacks.py`.
- **svp-208** (Victini alt) — attack registered to `_v_force` in `attacks.py`.

Frontend: "Queued" StatusBadge entry added with a distinct muted-slate style
(previously fell through to raw string display). "Queued" option added to
History page FilterBar status dropdown.

## Session 4 Work (2026-05-04)

Neo4j graph persistence optimized:

- `GraphMemoryWriter._update_synergies()` now builds deterministic unique-card
  pairs and writes them with chunked `UNWIND $pairs AS pair` Cypher instead of
  one `session.run()` per card pair. Semantics are unchanged: duplicate card
  copies are ignored, win/loss deltas remain +1.0/-0.5, and `weight` /
  `games_observed` updates match the prior behavior.
- `GraphMemoryWriter` now caches Deck/Card/BELONGS_TO setup per writer instance
  using a deck ID/name/card-quantity fingerprint and batches Card and BELONGS_TO
  MERGEs with `UNWIND $cards AS card`. MatchResult and BEATS writes still happen
  per match.

Focused tests added for pair generation, chunking, deltas, exact Neo4j
relationship values, deterministic deck card rows, and once-per-writer deck
setup caching.

Validation after these graph optimizations:

- `python3 -m pytest backend/tests/test_memory/test_graph_synergy_batch.py -q`
  — 12 passed.
- `python3 -m pytest backend/tests/test_memory/test_graph.py -q` — 6 passed.
- `cd backend && python3 -m pytest tests/ -x -q` — 439 passed.

Benchmark handoff: 25 persisted H/H matches, 1 opponent, Iron Crown ex Deck vs
Torterra ex Deck, both decks with 60 unique cards. After synergy batching:
total 13.38s, simulation+Redis 1.40s, Postgres 1.60s, Neo4j 10.21s. After
deck setup caching/batching: total 12.29s, simulation+Redis 1.39s, Postgres
1.53s, Neo4j 9.21s, 10,037 match events, 100 expected synergy chunks, 2 deck
setup cache entries. Absolute times include contention from an older
redelivered Celery simulation that remained active.

Neo4j optimization is intentionally paused after these safe batching/caching
improvements. Batch-level or deferred graph persistence remains a possible
future optimization, but it is deferred rather than rejected. The current
per-match graph persistence semantics are preferred for now to preserve data
quality, immediate graph visibility, and AI/coach memory fidelity. Shift next
work away from Neo4j batching unless runtime becomes unacceptable again.

## Current Known Issues / Gaps

- DeckBuilder Phase 3, simulation-backed preference weighting from historical
  data, remains deferred. The current builder is conservative and deterministic.
- AI/Coach provider abstraction is intentionally not planned. PokePrism remains
  Ollama-only by product decision; see
  `docs/proposals/AI_COACH_HARDENING_ASSESSMENT.md`.
- AI decision quality still has documented follow-up areas: reasoning-to-action
  mismatch, Fairy Zone rules misunderstanding, and no greedy-KO override
  backstop.
- Team Rocket's Watchtower (sv10-180 / me02.5-210): Colorless Pokémon ability
  suppression is fully implemented in the action validator. Passive ability
  interactions (e.g. Damp) remain a future gap if a Colorless Pokémon with a
  passive ability becomes relevant.
- Mystery Garden (me02.5-194 / me01-122): fully implemented via `USE_STADIUM`
  ActionType; once-per-turn Energy-discard draw effect is live.
- Spiky Energy (sv09-159): damage-retaliation effect fully implemented in
  `_apply_damage`; detection fixed to use `att.card_def_id` directly.
- Boomerang Energy (sv06-166): reattach-after-discard effect fully implemented
  in `transitions.py`.
- Neutralization Zone (sv06.5-060): passive damage prevention is implemented.
  The "cannot be retrieved from discard" restriction is enforced in Pal Pad and
  Miracle Headset. Other future retrieval handlers (if added) must apply
  `is_recoverable_from_discard()` filtering.
- `celery-worker` has no dedicated healthcheck. It restarts via
  `restart: unless-stopped`.
- Simulation queue relies on Beat task as crash-recovery fallback (every 60s).
  There is no push notification to the frontend when a queued sim transitions to
  running; the frontend must poll for status changes.
- Neo4j graph writes remain per-match for MatchResult and BEATS relationships.
  Deck/Card/BELONGS_TO setup and synergy pair updates are batched/cached.
  Match-result aggregation and batch-level/deferred graph persistence are
  deferred future opportunities, not active next work.

## Operational Caveats

- After changes under `backend/app/engine/effects/`, rebuild the worker image:
  `docker compose build celery-worker && docker compose up -d celery-worker`.
  The backend container mounts `./backend/app:/app/app`, but `celery-worker`
  runs baked code from its image.
- `make restart` restarts backend, worker, and beat, but it does not rebuild the
  worker image.
- `make reset-data` truncates simulation data and clears Neo4j relationships.
  Do not run it unless that destructive action is explicitly intended.
- Full-stack E2E is opt-in: run from `frontend/` with
  `POKEPRISM_E2E_FULL_STACK=1 npm run test:e2e` against a running Docker stack.
- AI-backed modes require a working Ollama model and suitable local hardware.
  H/H simulations do not require Ollama inference.
- Running frontend dependency commands can dirty tracked `frontend/node_modules`
  in this repository. Do not commit `frontend/node_modules`.

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

## Immediate Next Steps

1. Continue the DB-backed audit from `docs/AUDIT_STATE.md` using the rules in
   `docs/AUDIT_RULES.md`. Do not advance `next_start_cursor` unless an actual
   card audit is performed.
2. Implement the next safe card-handler batch discovered by audit or simulation
   coverage gates, with focused tests and a worker rebuild.
3. Run at least one simulation containing newly implemented cards to verify the
   coverage gate and runtime worker path use the new handlers.
4. Re-run the full backend suite when handler or engine changes are complete and
   update this file with the exact command and result.
5. Keep `docs/CHANGELOG.md` as the historical record for completed work and
   resolved uncertainty.

## Read This First

- Current state and operations: `docs/STATUS.md`
- Historical changes and evidence: `docs/CHANGELOG.md`
- Active card audit workflow: `docs/AUDIT_RULES.md` and `docs/AUDIT_STATE.md`
- Historical architecture blueprint: `docs/PROJECT.md`
- Public setup/onboarding: `README.md`
- Supporting proposals and assessments: `docs/proposals/*.md`

## Archival Note

Older session-by-session notes that previously lived in this file were
compressed into this current-state handoff. Historical facts should be preserved
in `docs/CHANGELOG.md`; if a future detail is missing from the changelog, add it
there rather than expanding this status file back into a session log.
