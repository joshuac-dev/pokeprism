# PokePrism - Current Status

> Read this first for current operational state. This file is the live handoff.
> `docs/PROJECT.md` is historical architecture context, not the active source
> of truth for implementation status.

Last updated: 2026-05-04

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
| Backend test baseline | Last full documented run: **411 passed, 3 skipped** on 2026-05-05 (DB-backed audit session Batch A). Run with `cd backend && python3 -m pytest tests/ -x -q`. |
| Frontend unit tests | 4 passed on 2026-05-04 with `cd frontend && npm test -- --run --reporter=dot` |
| Playwright E2E inventory | 14 tests listed on 2026-05-04 with `cd frontend && npm run test:e2e -- --list` |
| Effect import smoke | Passed on 2026-05-04 with `docker compose exec backend python -c "import app.engine.effects.attacks; import app.engine.effects.trainers; import app.engine.effects.energies; import app.engine.effects.abilities; import app.engine.effects.base"` |

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
- `celery-worker` has no dedicated healthcheck. It restarts via
  `restart: unless-stopped`.

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
