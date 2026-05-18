# PokePrism - Current Status

> Read this first for current operational state. This file is the live handoff.
> `docs/PROJECT.md` is historical architecture context, not the active source
> of truth for implementation status.

Last updated: 2026-05-18 (observed-play parser quality fix + DB-backed audit run 47 handoff)

## Current Workstream

PokePrism is post-phase-buildout. The original phase blueprint through Phase 13
and the 2026-05-03 hardening sweep are complete. Active work is ongoing
post-phase development:

- DB-backed card-effect audits and cursor-based handler fixes.
- Card-effect correctness, handler registration, and simulation validation.
- AI/coach hardening and decision-quality follow-up.
- Operational refinement for Docker, Celery, CI, and local workflows.

**Observed-play corpus readiness: READY (2026-05-18):**
- Scorecard before fix: Not Ready, 77.2/100. Blockers: 3 unknown events, 3 events
  below 80% confidence (same 3 events, confidence 0.30 each).
- Root causes:
  1. Sweep game-end ("Knocked Out all your opponent's Pokémon in play and took all
     your Prize cards. WINNER wins.") — no pattern. Added `RE_GAME_END_SWEEP`.
  2. Named Pokémon bounced to hand ("PLAYER moved OWNER's CARD to their hand.") —
     existing pattern requires numeric count. Added `RE_POKEMON_MOVED_TO_HAND`.
  3. Self-concede ("You conceded. WINNER wins.") — only opponent-concede covered.
     Added `RE_GAME_END_YOU_CONCEDED`.
- Affected logs reparsed: 3 (via `POST /api/observed-play/logs/{id}/reparse`).
- 18 regression tests added (`TestParserBlockerFixes` in `test_parser.py`).
- Scorecard after fix: **ready**, 97.22/100, unknown_event_count=0,
  low_confidence_event_count=0, unresolved=0, ambiguous=0.

**Deck mutation log consistency fix (2026-05-14):**
- Root cause: three interacting bugs (Cases C + D + G):
  1. `analyze_and_mutate()` wrote mutation rows to DB *before* `_apply_mutations()` ran,
     permanently committing skipped mutations.
  2. Deck reversions (2 consecutive regressions) only reverted the in-memory deck; DB
     mutation rows from the reverted period were never cleaned up.
  3. No `status` column on `deck_mutations` — all rows looked identical.
- Fix: `deck_mutations.status` column added (migration `k7l8m9o0p1q2`); analyst no
  longer writes mutations; simulation writes only applied mutations via new
  `_persist_applied_mutations()`; reversion marks rows `'reverted'` via new
  `_mark_mutations_reverted()`; API filters by `status='applied'`.
- Proposed mutations are no longer persisted as applied.
- Mutation log API (`GET /api/simulations/{id}/mutations`) returns only `status='applied'` rows.
- Reverted mutation rows are preserved for auditability but excluded from the user-facing applied log.
- 14 new regression tests in `test_simulation_task.py` (spec A–E).
- Affected sim `1df138cf` — data repair executed 2026-05-14: 15 rows marked `reverted`,
  1 row remains `applied` (round 3, Pikachu ex → Cynthia's Spiritomb). No match data deleted.
  API now returns exactly one mutation for that sim.
- Post-deploy: run `alembic upgrade head`, then `docker compose up -d --build backend celery-worker celery-beat`.

- **Audit workflow hardened to robust-audit-v2 (2026-05-12):** nightly workflow now
  requires a machine-readable `docs/audit_runs/<date>-card-effect-audit.json` report;
  `PARTIAL_TIME_BUDGET` is rejected; early stops must use `CONTINUATION_REQUIRED`;
  `TARGET_REACHED` requires `fixes+gaps >= target`; `DB_EXHAUSTED`/`FULL_CYCLE_COMPLETE`
  require a real full circular DB pass; PR gate at
  `.github/workflows/card-effect-audit-pr-gate.yml` validates every audit PR labeled
  `card-effect-audit` or `robust-audit-v2`.
- **Audit quality hardened to evidence schema v3 (2026-05-11):** Generic no-issue
  ledger entries are now rejected by the PR gate. Each entry must record `tcgdex_effects_extracted`,
  `implementation_evidence` (registry key, handler symbol, source file), `semantic_checks`,
  `mechanic_flags`, `confidence`, and specific notes. Validator:
  `backend/scripts/validate_card_audit_report.py`. Probe helper:
  `backend/scripts/card_effect_audit_probe.py`. Old shallow-format reports are
  no longer acceptable for new runs.
- **Audit quality hardened to behavioral coverage v4 (2026-05-13):** Risky
  mechanic rows can no longer claim `result=no-issue` based on registry evidence
  alone. Risky no-issue rows now require `behavioral_evidence` backed by an
  existing focused test or generated probe. Reports must include top-level
  `behavioral_rows_required`, `behavioral_rows_verified`,
  `behavioral_rows_unverified`, and `behavioral_coverage_percent`. `DB_EXHAUSTED`
  and `FULL_CYCLE_COMPLETE` are rejected when risky rows are behaviorally
  unverified; `CONTINUATION_REQUIRED` may carry unverified risky rows only with
  explicit behavioral accounting and non-high confidence.

**Simulation task re-delivery fix (2026-05-14):**
- Root cause: `task_acks_late=True` + Redis default visibility timeout (3600 s) + simulation
  running >1 h caused the broker to redeliver the task while the original was still running
  (or just completing). On redelivery the existing guards only skipped `"cancelled"` and
  `"running"` states, so a sim row already in `"complete"` was silently reset to `"running"`,
  had its rounds replayed, and was then marked `"failed"` when the coach-mutation guard fired
  on round 2.
- Fix 1: `_run_simulation_async` now returns immediately (`skipped_complete` / `skipped_failed`)
  for any terminal-state simulation without touching DB data.
- Fix 2: `celery_app.py` sets `broker_transport_options={"visibility_timeout": 86400}` (24 h).
- 2 regression tests added to `test_simulation_task.py`.
- Affected sim `6f79689d` — all 4900 matches intact; DB repair SQL in CHANGELOG.
- Deploy: `docker compose up -d --build celery-worker celery-beat` after merging.

**Nightly H/H simulation lifecycle fix (2026-05-13):**
- Root cause: `_run_scheduled_hh_async` called `run_hh_batch(persist=True)` which created a bare
  Simulation row (`status=running`, blank deck names, `matches_per_opponent=0`), completed all 200
  games in ~26 s, then returned without ever updating the row. The row stayed `status=running`
  indefinitely.
- History showed blank Your Deck / Opponent(s) because `user_deck_name=NULL` and no
  `SimulationOpponent` rows existed.
- Fix: `_run_scheduled_hh_async` now pre-creates the Simulation row with full metadata before
  calling `run_hh_batch`, wraps the batch in try/except (marks failed on error), creates a
  `SimulationOpponent` row for TR-Mewtwo on success, and marks the row `complete` after the batch.
- Non-overlap guard: skips if a scheduled H/H sim is still in `running/pending/queued` state;
  marks stale runs (> 1 h) as failed before starting a new one.
- 7 new lifecycle tests in `backend/tests/test_tasks/test_scheduled_hh.py` (mock-based, no DB).
- Module-level imports added to `scheduled.py` so tests can patch them cleanly.

**Round-robin nightly H/H rerun (2026-05-14):**
- Static Dragapult vs TR-Mewtwo nightly replaced by round-robin reruns of completed manual
  single-round H/H simulations.
- New `nightly_hh_rerun_history` table (migration `j6k7l8m9o0p1`) tracks source/generated pairs
  and cycle number for durable round-robin selection.
- New shared service `backend/app/services/nightly_hh_rerun.py`; Celery task now delegates to it.
- Fixed generated parameters: 25 matches/opponent, 3 rounds, target_win_rate=60%,
  target_consecutive_rounds=3, target_mode=per_opponent, deck_locked=false.
- Admin API: `GET/POST /api/admin/nightly-hh-rerun/{status,preview,trigger}`.
- Administration UI at `/admin` with Preview/Trigger buttons.
- To manually trigger: open `/admin` → click "Trigger Nightly H/H Rerun Now".
- Post-deploy migration required: `docker compose exec -T backend alembic upgrade head`.
- Stuck nightly run `1280be10-fc27-457b-b45d-dd5439c3bfc1` (200 matches, created 2026-05-11 02:00
  UTC): all matches complete; safe to repair — see repair SQL in CHANGELOG.

**Engine fix hardening (2026-05-13 — audit run 41 regression tests):**
- Three bugs corrected in `backend/app/engine/actions.py` and `backend/app/engine/effects/abilities.py`:
  - **Sticky Bind** (sv08-107 Gastrodon): `actions.py` was checking `opp_init.active` instead of
    `opp_init.bench`; fixed to `any(b.card_def_id == "sv08-107" for b in opp_init.bench)`.
  - **Forest of Vitality alt-print** (me02.5-188): same-turn Grass evolution check only matched
    `me01-117`; fixed to `in ("me01-117", "me02.5-188")`.
  - **Extra Helpings alt-print** (svp-184 Hop's Snorlax): `_EXTRA_HELPINGS_IDS` frozenset only
    contained `sv09-117`; added `svp-184`.
- 12 focused regression tests added in `backend/tests/test_engine/test_run41_fixes.py`.
- full tests run: `OBSERVED_PLAY_MEMORY_ENABLED=false python3 -m pytest tests/ -x -q` (`1487 passed, 7 skipped`)

**DB-backed audit handoff (2026-05-18 nightly robust-audit-v2 run 47):**
- current workstream: DB-backed card-effect audits and cursor-based handler fixes
- completion status: `CONTINUATION_REQUIRED`
- target findings: 25
- implemented fixes: 0
- documented engine gaps: 0
- database cards audited: 100
- first card audited: `Miraidon | SSP | 69 | sv08-069`
- last card fully audited: `Palpitoad | BLK | 20 | sv10.5b-020`
- next resume cursor: `Pancham | JTG | 83 | sv09-083`
- AUDIT_STATE.md update status: updated
- focused checks run: TCGDex preflight succeeded; local report validation passed (`python3 backend/scripts/validate_card_audit_report.py docs/audit_runs/2026-05-18-47-card-effect-audit.json`)
- full tests run: `OBSERVED_PLAY_MEMORY_ENABLED=false python3 -m pytest tests/ -x -q` (`1570 passed, 7 skipped`)
- implemented fixes in this slice: none
- documented engine gaps in this slice: none
- behavioral accounting (v4): `behavioral_rows_required=77`, `behavioral_rows_verified=0`, `behavioral_rows_unverified=77`, `behavioral_coverage_percent=0.0`
- operational notes: machine-readable v4 report at `docs/audit_runs/2026-05-18-47-card-effect-audit.json`

**DB-backed audit handoff (2026-05-17 nightly robust-audit-v2 run 46):**
- current workstream: DB-backed card-effect audits and cursor-based handler fixes
- completion status: `CONTINUATION_REQUIRED`
- target findings: 25
- implemented fixes: 6
- documented engine gaps: 0
- database cards audited: 104 (100 in-window + 4 out-of-window fixed entries)
- first card audited: `Magmar | JTG | 20 | sv09-020`
- last card fully audited: `Miraidon | PR-SV | 92 | svp-092`
- next resume cursor: `Miraidon | SSP | 69 | sv08-069`
- AUDIT_STATE.md update status: updated
- focused checks run: TCGDex preflight succeeded; local report validation passed (`python3 backend/scripts/validate_card_audit_report.py docs/audit_runs/2026-05-17-46-card-effect-audit.json`)
- full tests run: `OBSERVED_PLAY_MEMORY_ENABLED=false python3 -m pytest tests/ -x -q` (8 new regression tests in `test_run46_fixes.py`, all passing)
- implemented fixes in this slice: Bemusing Aroma self-confusion (sv10.5b-007), Fade Out energy discard (sv09-068), Magneton Overvolt Discharge registration (svp-153, svp-159), Koraidon Ancient filter (sv08-116), Alcremie ex bench-caster (sv09-075)
- documented engine gaps in this slice: none
- behavioral accounting (v4): `behavioral_rows_required=79`, `behavioral_rows_verified=0`, `behavioral_rows_unverified=79`, `behavioral_coverage_percent=0.0`
- operational notes: machine-readable v4 report at `docs/audit_runs/2026-05-17-46-card-effect-audit.json`

**DB-backed audit handoff (2026-05-16 nightly robust-audit-v2 run 45):**

**DB-backed audit handoff (2026-05-15 nightly robust-audit-v2 run 44):**
- current workstream: DB-backed card-effect audits and cursor-based handler fixes
- completion status: `CONTINUATION_REQUIRED`
- target findings: 25
- implemented fixes: 0
- documented engine gaps: 0
- database cards audited: 100
- first card audited: `Hop's Wooloo | JTG | 135 | sv09-135`
- last card fully audited: `Klinklang | SCR | 101 | sv07-101`
- next resume cursor: `Koffing | JTG | 91 | sv09-091`
- AUDIT_STATE.md update status: updated
- focused checks run: TCGDex preflight succeeded; local report validation passed (`python3 backend/scripts/validate_card_audit_report.py docs/audit_runs/2026-05-15-44-card-effect-audit.json`)
- full tests run: `OBSERVED_PLAY_MEMORY_ENABLED=false python3 -m pytest tests/ -x -q` (`1535 passed, 7 skipped`)
- implemented fixes in this slice: none
- documented engine gaps in this slice: none
- behavioral accounting (v4): `behavioral_rows_required=88`, `behavioral_rows_verified=0`, `behavioral_rows_unverified=88`, `behavioral_coverage_percent=0.0`
- operational notes: machine-readable v4 report at `docs/audit_runs/2026-05-15-44-card-effect-audit.json`

**DB-backed audit handoff (2026-05-14 nightly robust-audit-v2 run 43):**
- current workstream: DB-backed card-effect audits and cursor-based handler fixes
- completion status: `CONTINUATION_REQUIRED`
- target findings: 25
- implemented fixes: 4
- documented engine gaps: 2
- database cards audited: 100
- first card audited: `Glimmora | TWM | 109 | sv06-109`
- last card fully audited: `Hop's Snorlax | PR-SV | 184 | svp-184`
- next resume cursor: `Hop's Wooloo | JTG | 135 | sv09-135`
- AUDIT_STATE.md update status: updated
- focused checks run: TCGDex preflight succeeded; local report validation passed; `python3 -m pytest tests/test_engine/test_run43_fixes.py tests/test_engine/test_run34_gap_fixes.py tests/test_engine/test_run41_fixes.py tests/test_scripts/test_validate_card_audit_report.py -q` (`69 passed`)
- full tests run: `OBSERVED_PLAY_MEMORY_ENABLED=false python3 -m pytest tests/ -x -q` (`1514 passed, 7 skipped`)
- implemented fixes in this slice: Granite Cave, Gravity Gemstone, Haban Berry, Hop's Choice Band
- documented engine gaps in this slice: Grand Tree, Heavy Baton
- behavioral accounting (v4): `behavioral_rows_required=73`, `behavioral_rows_verified=0`, `behavioral_rows_unverified=73`, `behavioral_coverage_percent=0.0`
- operational notes: machine-readable v4 report at `docs/audit_runs/2026-05-14-43-card-effect-audit.json`

**DB-backed audit handoff (2026-05-13 nightly robust-audit-v2 run 40):**
- current workstream: DB-backed card-effect audits and cursor-based handler fixes
- completion status: `CONTINUATION_REQUIRED`
- target findings: 25
- implemented fixes: 0
- documented engine gaps: 0
- database cards audited: 100
- first card audited: `Drifloon | MEP | 5 | mep-005`
- last card fully audited: `Farigiraf | TWM | 84 | sv06-084`
- next resume cursor: `Farigiraf ex | TEF | 108 | sv05-108`
- AUDIT_STATE.md update status: updated
- focused checks run: TCGDex preflight succeeded; local report validation passed
- full tests run: `OBSERVED_PLAY_MEMORY_ENABLED=false python3 -m pytest tests/ -x -q` (`1488 passed, 7 skipped`)
- implemented fixes: none in this slice
- documented engine gaps: none in this slice
- operational notes: machine-readable v3 report at `docs/audit_runs/2026-05-13-40-card-effect-audit.json`

**DB-backed audit handoff (2026-05-12 nightly robust-audit-v2 run 39):**
- current workstream: DB-backed card-effect audits and cursor-based handler fixes
- completion status: `CONTINUATION_REQUIRED`
- target findings: 25
- implemented fixes: 0
- documented engine gaps: 0
- database cards audited: 100
- first card audited: `Cornerstone Mask Ogerpon | DRI | 111 | sv10-111`
- last card fully audited: `Drifblim | SCR | 61 | sv07-061`
- next resume cursor: `Drifloon | MEP | 5 | mep-005`
- AUDIT_STATE.md update status: updated
- focused checks run: TCGDex preflight succeeded; local report validation passed
- full tests run: `OBSERVED_PLAY_MEMORY_ENABLED=false python3 -m pytest tests/ -x -q` (`1488 passed, 7 skipped`)
- implemented fixes: none in this slice
- documented engine gaps: none in this slice after hardening review corrected false-positive missing-handler evidence (including Counter Gain passive Tool logic)
- operational notes: machine-readable v3 report at `docs/audit_runs/2026-05-12-39-card-effect-audit.json`

**DB-backed audit handoff (2026-05-12 nightly robust-audit-v2 run 38):**
- current workstream: DB-backed card-effect audits and cursor-based handler fixes
- completion status: `CONTINUATION_REQUIRED`
- target findings: 25
- implemented fixes: 0
- documented engine gaps: 0
- database cards audited: 100
- first card audited: `Boxed Order | TEF | 143 | sv05-143`
- last card fully audited: `Core Memory | POR | 70 | me03-070`
- next resume cursor: `Cornerstone Mask Ogerpon | DRI | 111 | sv10-111`
- AUDIT_STATE.md update status: updated
- focused checks run: TCGDex preflight succeeded; local report validation passed
- full tests run: `OBSERVED_PLAY_MEMORY_ENABLED=false python3 -m pytest tests/ -x -q` (`1488 passed, 7 skipped`)
- implemented fixes: none in this slice
- documented engine gaps: none in this slice
- operational notes: machine-readable v3 report at `docs/audit_runs/2026-05-12-38-card-effect-audit.json`

**DB-backed audit handoff (2026-05-12 nightly robust-audit-v2 run 36 + gap-fix follow-up):**
- current workstream: DB-backed card-effect audits and cursor-based handler fixes
- completion status: `TARGET_REACHED` + all 12 engine gaps subsequently implemented
- target findings: 25
- implemented fixes (audit): 13
- documented engine gaps (audit): 12 — all subsequently fixed in follow-up commit
- database cards audited: 1132 (+ 7 supplemental out-of-range, ledger=1139)
- first card audited: `Flutter Mane | TEF | 78 | sv05-078`
- last card fully audited: `Zweilous | sv10.5w | 66 | sv10.5w-066`
- next resume cursor: `Abomasnow | DRI | 60 | sv10-060` (last card was end of DB; wraps to first card)
- AUDIT_STATE.md update status: updated
- focused checks run: TCGDex preflight succeeded; local report validation passed
- full tests run: `python3 -m pytest tests/ -x -q` (`1466 passed, 7 skipped` after gap fixes)
- implemented fixes (audit): Compound Eyes scope (sv06.5-002 Galvantula), Psyduck Damp alt-prints (mep-007/mep-008), Froslass Shroud alt-print (svp-117), Sandy Flapping active handler (mep-016 Flygon), Primal Knowledge +30 vs Evolution (sv07-038 Carracosta), Soft Wool -30 (sv07-125 Dubwool), Thicket Body -30 (sv06-002 Tangrowth), Impervious Shell prevent ≥200 damage (sv07-044 Drednaw), Incandescent Body alt-print (sv06-123 Heatran), Poison Point alt-prints (sv05-008 Roselia, sv05-009 Roserade), Solid Shell -20 (sv05-010 Turtwig)
- engine gap fixes (follow-up): Big Net +1 retreat for Evolution (sv06-005), Metal Bridge free retreat for all Pokémon with Metal Energy (sv07-107/sv08.5-070), Initialization sv06-077 suppresses Rule Box abilities, Boom Boom Groove active handler with Festival Lead condition (sv06-015/svp-115), Wicked Tail on-evolve trigger (sv06-138), ACE Nullifier blocks ACE SPEC when Genesect has Tool (sv06.5-040), Massive Body blocks Stadium play when Active (sv06.5-042), Storehouse Hideaway blocks bench damage to Poltchageist (sv06-020), Solar Transfer active handler for mep-013, Changing Seasons stadium search once per turn (sv05-017), Unnerve protection from Boss/Catcher targeting (sv06.5-045)
- operational notes: v3 report at `docs/audit_runs/2026-05-12-36-card-effect-audit.json`; tests in `test_run36_gap_fixes.py` (19) and `test_run36_gap_fixes_impl.py` (24)

**DB-backed audit handoff (2026-05-11 nightly robust-audit-v2 run 34):**
- current workstream: DB-backed card-effect audits and cursor-based handler fixes
- completion status: `TARGET_REACHED`
- target findings: 25
- implemented fixes: 25
- documented engine gaps: 0
- database cards audited: 1035
- first card audited: `Lucario ex | PRE | 51 | sv08.5-051`
- last card fully audited: `Counter Gain | ASC | 186 | me02.5-186`
- next resume cursor: `Counter Gain | SSP | 169 | sv08-169`
- AUDIT_STATE.md update status: updated
- focused checks run: TCGDex preflight succeeded (`GET https://api.tcgdex.net/v2/en/cards/sv08.5-051` → HTTP 200); local audit report validation passed; `python3 -m pytest tests/test_scripts/test_validate_card_audit_report.py -q` (`29 passed`)
- full tests run: `python3 -m pytest tests/ -x -q` (`1421 passed, 7 skipped`)
- implemented fixes: Lumiose City, Nighttime Mine, Passho/Babiri/Colbur Berry, Powerglass, Punk Helmet, Rescue Board (PRE/TEF), Sacred Charm, Spikemuth Gym, Strange Timepiece, Surfing Beach, Team Rocket's Hypnotizer, Thick Scale, Academy at Night, Air Balloon alt-print coverage, Anthea & Concordia, Area Zero Underdepths (PRE/SCR), Binding Mochi alt-print coverage, Canari, Celebratory Fanfare, Community Center, and Counter Gain alt-print coverage
- documented engine gaps: none remaining from run 34
- known issues / follow-up: resume from `Counter Gain | SSP | 169 | sv08-169` for the next audit slice
- operational notes: machine-readable v3 report updated at `docs/audit_runs/2026-05-11-34-card-effect-audit.json`; backend engine/test files changed to implement all 25 findings from the run-34 ledger

**DB-backed audit handoff (2026-05-11 nightly robust-audit-v2 run 33):**
- current workstream: DB-backed card-effect audits and cursor-based handler fixes
- completion status: `BLOCKED_TCGDEX`
- target findings: 25
- implemented fixes: 0
- documented engine gaps: 0
- database cards audited: 0
- first card audited: (none — blocked before first card)
- last card fully audited: (none)
- next resume cursor: `Lucario ex | PRE | 51 | sv08.5-051` (unchanged per BLOCKED_TCGDEX rules)
- AUDIT_STATE.md update status: updated (cursor unchanged)
- focused checks run: TCGDex preflight attempted — timed out after 5 s (GET https://api.tcgdex.net/v2/en/cards/sv08.5-051, network unreachable in sandbox)
- full tests run: `python3 -m pytest tests/ -x -q` (engine tests: 305 passed, 1 skipped; validator tests: 29 passed)
- implemented fixes: none
- documented engine gaps: none
- known issues / follow-up: TCGDex network blocked in this run's sandbox environment; retry next run from `Lucario ex | PRE | 51 | sv08.5-051`
- operational notes: machine-readable report added at `docs/audit_runs/2026-05-11-33-card-effect-audit.json`; no engine code files changed

**DB-backed audit handoff (2026-05-11 nightly robust-audit-v2 run 30):**
- current workstream: DB-backed card-effect audits and cursor-based handler fixes
- completion status: `DB_EXHAUSTED`
- target findings: 25
- implemented fixes: 0
- documented engine gaps: 0
- database cards audited: 1607
- first card audited: `Lucario ex | PRE | 51 | sv08.5-051`
- last card fully audited: `Lt. Surge's Bargain | MEG | 120 | me01-120`
- next resume cursor: `Lucario ex | PRE | 51 | sv08.5-051`
- AUDIT_STATE.md update status: updated
- focused checks run: backend full-cycle audit script with live TCGDex fetches for all DB cards (TCGDEX_PREFLIGHT=ok, no unresolved fetches) and local backend baseline `.venv/bin/python -m pytest tests/ -x -q` (`1376 passed, 7 skipped`)
- full tests run: `.venv/bin/python -m pytest tests/ -x -q` (`1376 passed, 7 skipped`)
- implemented fixes: none in this pass
- documented engine gaps: none in this pass
- known issues / follow-up: continue next run from `Lucario ex | PRE | 51 | sv08.5-051` per DB_EXHAUSTED full-cycle behavior
- operational notes: machine-readable report added at `docs/audit_runs/2026-05-11-30-card-effect-audit.json`; no engine code files changed in this run

**Active planning branch:** `phase-7-observed-play-planning` — Observed-Play Intelligence Planning
**Phase 1 through Phase 6.2b are COMPLETE and manually validated.** Both phases validated 2026-05-08.
See `docs/proposals/OBSERVED_PLAY_MEMORY_IMPLEMENTATION_PLAN.md`.

**Phase 7.2 corpus readiness audit (2026-05-09):** Verdict: `not_ready_needs_more_logs`.
49 logs in corpus (all parsed+ingested). Archetype distribution: dragapult-ex (23),
crustle (12), gardevoir-ex (12), salazzle-ex (1), charizard-ex (1). All cross-matchup
pairs (different archetypes on each side) have exactly 1 log each — below the ≥3
minimum for Phase 7.2c matchup ranking. Salazzle-ex and Charizard-ex each need 4
more clean logs. No import candidates found locally.
Phase 7.2c is **gated** pending corpus expansion.
Full report: `docs/proposals/OBSERVED_PLAY_CORPUS_EXPANSION_PHASE_7_2_READINESS_REPORT.md`.

## Phase 7.2c — Guarded Matchup Boost (Current)

Status: Implemented and UX/debug validated

- Generic guarded matchup ranking boost inside existing deck_overlap_v1 retrieval path
- Strategy: matchup_context_boost_v1
- Boost cap: 0.12; minimum directed pair logs: 3
- When directed matchup pair has ≥3 clean corpus logs: matchup_boost applied (max 0.12)
- When pair is unseen or under-covered: matchup_boost=0.0; fallback to Phase 7.1d behavior
- Tier-first sort invariant preserved; lower-tier evidence with boost cannot outrank higher-tier
- No candidate pool expansion; no hard filtering; no evidence injection for no-match contexts
- No persistence; no migrations
- Real corpus currently under-covered: most contexts have matchup_ranking_enabled=False
- Full broad activation pending corpus expansion

**Phase 7.2c post-merge UX/debug validation (2026-05-10):**
Verdict: `ready_for_parallel_corpus_expansion`.
Branch: `phase-7-2c-post-merge-ux-debug-validation` (from `f4399a0`).
Four retrieval contexts checked (Dragapult vs Gardevoir, Crustle vs Dragapult,
no-match fake cards, no-label trainer-only deck). All contexts confirmed
`matchup_pair_eligible=False`, `matchup_boost_applied_count=0`, correct
`matchup_coverage_reason`. Coach-debug readability checklist: all 7 questions
answered YES. One minor UI fix: `matchup_boost_applied_count` now always shown
in 7.2c context (was hidden when 0). 380 frontend tests pass, build clean.
Full report: `docs/proposals/OBSERVED_PLAY_PHASE_7_2C_UX_DEBUG_VALIDATION_REPORT.md`.

**Phase 7.2b implementation:** matchup context preview metadata merged to main (`6234d5c`).
`matchup_strategy=matchup_context_preview_v1`. Directed matchup key computed from
highest-confidence archetype labels. All matchup fields are metadata-only:
`matchup_ranking_enabled=False`, `matchup_boost=0.0`, scores and ordering unchanged.
Hardening removed `|vs|unknown` partial-key overclaiming.
Backend: 1272 passed, 1 skipped. Frontend: 372 passed, 21 files.

**Phase 7.2a design:** `docs/proposals/OBSERVED_PLAY_MATCHUP_AWARE_RETRIEVAL_PHASE_7_2_PLAN.md`
contains the full matchup-aware retrieval design and corpus expansion plan.
Matchup ranking boost (Phase 7.2c) gated on corpus reaching minimum thresholds.
Candidate-pool expansion (Phase 7.2d) gated on matchup pairs reaching ≥3 logs.

**Phase 7.0 planning:** `docs/proposals/OBSERVED_PLAY_INTELLIGENCE_PHASE_7_PLAN.md`
recommends Phase 7.1 — Deck Archetype Labeling and Log/Deck Tags (complete through 7.1e).

**Phase 7.1a schema/API design:** `docs/proposals/OBSERVED_PLAY_ARCHETYPE_LABELING_PHASE_7_1_SPEC.md`
adds an implementation-ready design for manual labels plus deterministic
suggestions, multi-label log/deck support, user review/edit flows, no-migration
metadata-first storage options, API shape, deterministic inference rules, UI
surfaces, retrieval integration staging, and tests.

**Phase 7.1b backend preview:** deterministic backend archetype/package/strategy
label preview is implemented. New read-only endpoints:
- `GET /api/decks/{deck_id}/archetype-label-preview`
- `GET /api/observed-play/logs/{log_id}/archetype-label-preview`

Seed labels: Dragapult ex, Salazzle ex, Crustle, Charizard ex, Gardevoir ex,
Fire toolbox, Poison/Burn strategy, Spread damage, Stage 2 setup, Psychic
engine. Labels are advisory/contextual only, are not persisted by default, and
do not affect Coach retrieval ranking. No migrations, Coach strategy changes,
simulator gameplay changes, AI Player changes, pgvector/Neo4j writes,
`match_events` writes, `card_performance` writes, deck-builder changes, or
observed-play ingestion changes were made.

**Phase 7.1c UI preview display:** frontend read-only display/review surfaces
are implemented for the Phase 7.1b preview endpoints.
- `/observed-play` Raw Logs table now has a per-log "Preview labels" action
  that opens an advisory label preview modal grouped by observed player alias.
- Simulation Dashboard now shows a non-fatal "Deck Context Labels" tile when
  `user_deck_id` is available, using the deck preview endpoint.
- Shared frontend display component renders label, type, source, confidence,
  review status, evidence cards/counts, ambiguous state, no-label reason, and
  advisory/read-only copy.
- Validation: `npm ci`, frontend tests (`362 passed`), frontend build, and
  `git diff --check` passed. Endpoint smoke checks confirmed Dragapult,
  Gardevoir, Crustle, unknown/no-label, and mixed/ambiguous observed-log
  preview payloads remain plausible.

Phase 7.1c does not persist labels, does not add edit/accept/reject behavior,
does not change retrieval ranking, and does not alter Coach prompt injection,
Coach strategy, simulator gameplay, AI Player behavior, observed-play
ingestion, deck-builder behavior, pgvector/Neo4j, `match_events`, or
`card_performance`.

**Phase 7.1d retrieval ranking integration:** deterministic archetype/package/
strategy labels are now used as a bounded, inspectable ranking signal inside
the existing `deck_overlap_v1` tiered retrieval path.
- Retrieval metadata includes `label_strategy=archetype_label_boost_v1`,
  `label_ranking_enabled`, deck/candidate labels, boost cap, and per-evidence
  label match details.
- Label boost is additive and capped at `0.10`.
- Sorting is tier-first, then final score, so exact Tier 1 deck/card evidence
  still outranks lower-tier label-boosted evidence.
- Labels only re-rank the existing candidate pool. They do not hard-filter
  evidence, do not expand the candidate pool, and do not turn
  `no_relevant_evidence=true` into an injected block when `allow_fallback=false`.
- Labels are not persisted and remain advisory/debug metadata only.
- Dashboard retrieval debug displays label strategy, labels used for ranking,
  base/final score, label boost, matched labels, and label match reason.

No migrations, Coach strategy changes, Coach prompt-injection policy changes,
simulator gameplay changes, AI Player changes, observed-play ingestion changes,
deck-builder changes, pgvector/Neo4j writes, `match_events` writes, or
`card_performance` writes were made.

**Phase 6.1 verification summary:**
- User Check 1 ✅ — Flag-off context preview: `enabled=false`, `would_inject=false`, no evidence
- User Check 2 ✅ — Flag-off Coach: no observed-play evidence in prompt or output
- User Check 3 ✅ — Flag-on Coach: block injected, LLM acknowledges (or fallback `not_used_reason`)
- User Check 4 ✅ — Immutability: all observed-play memory tables unchanged after flag-on simulation

**Phase 6.2a — Evidence relevance retrieval (COMPLETE, manually validated 2026-05-08):**
- Tiered retrieval: Tier 1 (exact card-ID match) → Tier 2 (ILIKE name match) → Tier 3 (global fallback, opt-in only).
- Source diversity cap: max 2 items per `observed_play_log_id`.
- Win/loss outcome weighting: +0.05 tiebreaker bonus, never a hard gate.
- No relevant evidence (flag-on, no deck match): `would_inject=false`, `no_relevant_evidence=true`, empty prompt block.
- `CoachAnalyst` now passes deck/candidate card context to `_fetch_observed_play_block()`.
- `coach-debug` endpoint surfaces `retrieval_metadata` per round: `strategy`, `deck_card_ids`, `deck_card_names`, `candidate_card_ids`, `candidate_card_names`, `no_relevant_evidence`, and per-item `tier`, `relevance_score`, `match_source`, `matched_card_ids`, `matched_card_names`, `matched_reason`.
- Debug refinements (17b6999): `deck_card_ids`/`candidate_card_ids` separated; `match_source` field (`deck_card`/`candidate_card`/`name_fallback_deck`/`name_fallback_candidate`/`global_fallback`); `matched_card_names` resolved from `card_id_to_name` dict; `matched_reason` human-readable; `no_relevant_evidence` explicit bool; deck matches sorted before candidate matches.
- No migration required. Observed-play memory remains read-only and advisory.
- Backend: 1223 passed, 1 skipped.

**Phase 6.2a manual validation result (2026-05-08, commit 17b6999):**
- Validated via flag-on H/H simulation + `GET /api/simulations/{id}/coach-debug`.
- `strategy=deck_overlap_v1`, `allow_fallback=false`, `no_relevant_evidence=false`.
- `deck_card_ids`/`candidate_card_ids` separate and populated.
- All selected evidence was Tier 1, `match_source=deck_card`.
- `matched_card_names` populated (Dragapult ex, Budew, Fezandipiti ex, Munkidori, Lillie's Clefairy ex).
- `matched_reason` human-readable (e.g. "deck_card Dragapult ex matched actor_card_def_id sv06-001").
- No global fallback injected by default. Source diversity cap working. Simulation completed normally.

**Phase 6.2b — UI/debug visibility (COMPLETE, manually validated 2026-05-08):**
- `ObservedPlayCoachContextPreview` TypeScript type extended with `retrieval_metadata` and `no_relevant_evidence`.
- New TS interfaces: `EvidenceSelectionDetail`, `EvidenceExclusionSummary`, `ObservedPlayRetrievalMetadata`.
- `CoachContextPreviewSection` (on `/observed-play`) shows: no-relevant-evidence banner, deck context pills, candidate card pills, evidence selected table (Tier / Score / Match source / Matched cards / Reason), exclusion summary row.
- Shared `RetrievalMetadataPanel` component: `frontend/src/components/observedPlay/RetrievalMetadataPanel.tsx`.
- New `ObservedPlayRetrievalDebugTile` in `frontend/src/components/simulation/` — per-round retrieval accordion using data from `GET /api/simulations/{id}/coach-debug`.
- `Dashboard.tsx` loads coach-debug in a separate non-fatal effect and renders tile 14 "Observed-Play Retrieval Debug" after the Final Candidate Deck tile.
- New types `CoachDebugAnalysisRound`, `CoachDebugResponse` in `simulation.ts`; `getSimulationCoachDebug` in `simulations.ts`.
- Helper copy on `/observed-play` preview explains that deck-overlap retrieval metadata is in the simulation Dashboard.
- 7 new frontend tests for `ObservedPlayRetrievalDebugTile` (353 total, 18 files). Build clean.

**Phase 6.2b manual validation result (2026-05-08, commit 77e4048):**
- Validated in the simulation Dashboard after a completed flag-on H/H simulation.
- Observed-Play Retrieval Debug tile appears after Final Candidate Deck.
- Tile shows: flag enabled, any block injected, round count summary, per-round accordion.
- Per-round accordion shows: strategy (`deck_overlap_v1`), deck/candidate card pills, evidence selected table (Tier, Score, Match source, Matched cards, Reason), acknowledgment.
- Tile values match `GET /api/simulations/{id}/coach-debug` curl output exactly.
- UI is readable and sufficient for manual validation without curl.

**Important UI/data-flow note:**
- The `/observed-play` Coach Context Preview uses manual card-name filters with no simulation context; it may not have `retrieval_metadata` unless the endpoint is called with deck IDs.
- Real deck-contextual retrieval metadata for a simulation lives in `GET /api/simulations/{id}/coach-debug`.
- The authoritative UI for validating Phase 6.2a retrieval behavior is the simulation Dashboard "Observed-Play Retrieval Debug" tile (not the `/observed-play` preview).

**Phase 7.1e — Manual label ranking validation (COMPLETE, 2026-05-09):**
Six retrieval contexts validated: Dragapult, Gardevoir, Crustle, Mixed/Ambiguous,
Unknown/No-label, and No-match. All ranking invariants held. Corpus counts unchanged.

Validation verdict: `ready_for_phase_7_2_planning`.

Full report: `docs/proposals/OBSERVED_PLAY_LABEL_RANKING_PHASE_7_1E_VALIDATION_REPORT.md`

Key findings:
- All 6 contexts produced correct `would_inject`, `no_relevant_evidence`, and label boost behavior.
- `label_match_reason` text was clear and non-misleading in all cases.
- Tier-first sort invariant held; labels did not promote Tier 2 above Tier 1.
- 0.10 boost cap held in all cases observed.
- Duplicate-key accumulation did not materially distort any real corpus result.
- No code changes were made during Phase 7.1e.

**Next feature step:** Phase 7.2 — Matchup-aware retrieval. The label infrastructure
is validated and stable. Suggested focus: filter evidence by matchup archetype pair
and expand corpus with more Gardevoir, Crustle, and Salazzle logs.

Plans: `docs/proposals/OBSERVED_PLAY_INTELLIGENCE_PHASE_7_PLAN.md` and
`docs/proposals/OBSERVED_PLAY_ARCHETYPE_LABELING_PHASE_7_1_SPEC.md`.
Observed memory remains advisory only. No claim is made that observed-play evidence improves gameplay — the correct claim is: *observed-play evidence retrieval is deck-contextual, visible, verifiable, and advisory-only.*

**Known caveat:** The LLM (Gemma) may fail to acknowledge observed-play evidence even after a repair retry. This is now visible and non-silent through the fallback `not_used_reason` (`"LLM failed to acknowledge injected observed-play evidence after retries."`) and `coach-debug` metadata. `any_acknowledgment_missing=true` is a valid outcome when this occurs; the goal is that failure is always explicit, never silent.

**What observed-play injection does and does not do:**
- ✅ Can inject observed-play evidence into Coach prompts when `OBSERVED_PLAY_MEMORY_ENABLED=true`.
- ✅ Coach must cite evidence IDs or provide a `not_used_reason`.
- ✅ Injection is verified read-only for all observed-play memory tables.
- ❌ Does not affect AI Player, simulator runtime, deck builder, pgvector, Neo4j, `match_events`, `card_performance`, or gameplay decisions.
- ❌ No claim is made that observed-play evidence improves Coach decisions — the injection is wired and verifiable; impact is not yet measured.

### Local dev flag control

To enable Coach observed-play injection locally:
```bash
echo "OBSERVED_PLAY_MEMORY_ENABLED=true" >> .env
docker compose up -d --no-deps backend celery-worker
```

To disable (restore default):
```bash
sed -i '/OBSERVED_PLAY_MEMORY_ENABLED/d' .env
docker compose up -d --no-deps backend celery-worker
```

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
| Backend test baseline | **1201 passed, 1 skipped** — 2026-05-08 session 57. `cd backend && python3 -m pytest tests/ -x -q`. |
| Frontend unit tests | **339 passed (17 files)** — 2026-05-10 session 54. `cd frontend && npm test -- --run`. |
| Playwright E2E inventory | 14 tests listed 2026-05-04 with `cd frontend && npm run test:e2e -- --list` |
| Effect import smoke | Passed 2026-05-05. `docker compose exec backend python -c "import app.engine.effects.attacks; import app.engine.effects.trainers; import app.engine.effects.energies; import app.engine.effects.abilities; import app.engine.effects.base"` |
| Backend test baseline | **1547 passed, 1 skipped** — 2026-05-15. `cd backend && OBSERVED_PLAY_MEMORY_ENABLED=false python3 -m pytest tests/ -x -q`. |

## Dangerous Laser handler (2026-05-15)

- `Dangerous Laser` (sv06.5-058 / SFA 58) — ACE SPEC Item handler implemented.
- Exact card text: *"Your opponent's Active Pokémon is now Burned and Confused."*
- Handler `_dangerous_laser` applies `StatusCondition.BURNED` and `StatusCondition.CONFUSED` to opponent's Active; respects Unnerve ability; no-ops when opponent has no Active.
- Registered under key `sv06.5-058` in `backend/app/engine/effects/trainers.py`.
- 6 focused regression tests added to `backend/tests/test_engine/test_audit_fixes.py`.

## Session 57 Work (2026-05-08) — Coach ack retry + fallback reason + flag control

### Problems addressed

1. **Ack retry enforcement**: LLM sometimes omitted `observed_play_acknowledgment` silently. Added retry with repair prompt.
2. **Fallback not_used_reason**: When all retries fail, `not_used_reason` was still `null`. Added `_inject_ack_fallback()` to ensure every injected round has a non-null `not_used_reason`.
3. **Flag control**: `docker-compose.override.yml` hard-coded `OBSERVED_PLAY_MEMORY_ENABLED: "true"` with no easy way to turn it off. Now uses `${OBSERVED_PLAY_MEMORY_ENABLED:-false}`, defaulting to off unless set in `.env`.

### What was changed

- **`backend/app/coach/prompts.py`** — Added `COACH_OBSERVED_PLAY_ACK_REPAIR_PROMPT`: includes previous LLM response (≤2000 chars), instructs re-emission with ack field; does not resend deck context.
- **`backend/app/coach/analyst.py`**:
  - Added module-level `_ACK_FALLBACK_REASON` constant and `_inject_ack_fallback()` helper
  - Refactored `_get_swap_decisions`: saves `last_valid_swaps`/`last_valid_parsed` on missing-ack; retries on non-final attempts; accepts with `acknowledgment_missing=True` on final attempt; uses `last_valid_swaps` fallback if repair causes invalid swaps
  - `_inject_ack_fallback()` applied at all `acknowledgment_missing=True` return paths
- **`docker-compose.override.yml`** — Replaced `OBSERVED_PLAY_MEMORY_ENABLED: "true"` with `"${OBSERVED_PLAY_MEMORY_ENABLED:-false}"` on both `backend` and `celery-worker`; added comments explaining how to enable via `.env`
- **`.env.example`** — Added commented-out `# OBSERVED_PLAY_MEMORY_ENABLED=true` with instructions
- **Tests** — `TestObservedPlayAckRepair` updated to 6 tests; assertions now verify non-null `not_used_reason` on fallback paths

### Files changed

- `backend/app/coach/prompts.py`
- `backend/app/coach/analyst.py`
- `backend/tests/test_coach/test_analyst.py`
- `docker-compose.override.yml`
- `.env.example`
- `docs/STATUS.md`, `docs/CHANGELOG.md`

### Validation

- `docker compose exec backend python3 -c "from app.config import settings; print(settings.OBSERVED_PLAY_MEMORY_ENABLED)"` → `False`
- `docker compose exec celery-worker python3 -c "from app.config import settings; print(settings.OBSERVED_PLAY_MEMORY_ENABLED)"` → `False`
- `curl .../coach-context-preview?card_name=Dragapult+ex` → `enabled=false, would_inject=false`
- Backend: **1201 passed, 1 skipped**
- Frontend: **339 passed (17 files)** (unchanged)
- No observed-play memory behavior, simulation mutation logic, AI Player, pgvector, Neo4j, match_events, card_performance, or deck-builder changed.

## Session 56 Work (2026-05-08) — Coach observed-play no-mutation debug fix

### Root cause / Scenario 3

After fixing the celery-worker env (session 54), `OBSERVED_PLAY evidence fetch: would_inject=True evidence_count=8` appeared in the worker logs, confirming the block was injected. However, `GET /api/simulations/{id}/coach-debug` showed `observed_play_citations_found=[]` and `any_observed_play_cited=false`. The LLM received the evidence block but did not cite any observed-play event IDs in its structured response, because: (a) the prompt only softly requested citation; (b) there was no structured acknowledgment field in the response schema forcing the LLM to explicitly account for the observed-play block.

### What was changed

- **`backend/alembic/versions/h4i5j6k7l8m9_add_deck_mutation_observed_play_meta.py`** — new migration: adds `observed_play_meta JSONB nullable` column to `deck_mutations`
- **`backend/app/db/models.py`** — added `observed_play_meta = Column(JSONB)` to `DeckMutation`
- **`backend/app/coach/prompts.py`** — added `observed_play_acknowledgment` as a required top-level field in the JSON schema; added strong instruction: the LLM MUST include this field, set `block_provided=true` if the block was present, list cited event IDs in `used_evidence_ids`, and if no evidence was used explain in `not_used_reason`
- **`backend/app/coach/analyst.py`**:
  - `_fetch_observed_play_block()` now returns `tuple[str, list[str]]` (block_text, evidence_ids)
  - New `_extract_op_acknowledgment(parsed, available_ids)` method: normalises the `observed_play_acknowledgment` from the LLM response; logs WARNING if field was expected but absent
  - `_get_swap_decisions()` accepts `observed_play_ids` param; returns `tuple[list[dict], dict | None]` with the acknowledgment
  - `analyze_and_mutate()` builds `op_meta` dict (`block_injected`, `evidence_ids_available`, `acknowledgment`) and attaches it to each mutation
  - `_write_mutations()` stores `observed_play_meta` on `DeckMutation`
- **`backend/app/api/simulations.py`** — `GET /api/simulations/{id}/coach-debug` now surfaces per-mutation: `observed_play_block_injected`, `observed_play_evidence_ids_available`, `observed_play_citations_used`, `observed_play_not_used_reason`, `observed_play_acknowledgment_missing`; top-level `any_block_injected`
- **Tests**:
  - Updated `_fetch_observed_play_block` tests (4): now check `(block, ids)` tuple
  - Updated `_get_swap_decisions` callers (3): now unpack tuple
  - Updated `test_observed_play_is_valid_evidence_kind`: includes `observed_play_acknowledgment` in response
  - Added 5 new `TestCoachAnalystObservedPlay` tests for `_extract_op_acknowledgment`
  - Added `TestGetSimulationCoachDebug.test_observed_play_meta_fields_surfaced` (new test)
  - Updated `_make_mutation` mock to set `observed_play_meta=None` explicitly

### Files changed

- `backend/alembic/versions/h4i5j6k7l8m9_add_deck_mutation_observed_play_meta.py` (new)
- `backend/app/db/models.py`
- `backend/app/coach/prompts.py`
- `backend/app/coach/analyst.py`
- `backend/app/api/simulations.py`
- `backend/tests/test_api/test_simulations.py`
- `backend/tests/test_coach/test_analyst.py`
- `docs/STATUS.md`, `docs/CHANGELOG.md`

### Validation

- Migration applied cleanly: `g3h4i5j6k7l8 → h4i5j6k7l8m9`
- Backend: **1188 passed, 1 skipped**
- Frontend: **339 passed (17 files)** (unchanged)
- No observed-play memory behavior, simulation mutation logic, AI Player, pgvector, Neo4j, match_events, card_performance, or deck-builder changed.

## Session 54 Work (2026-05-10) — Coach observed-play injection fix + debug visibility

### Root cause

`OBSERVED_PLAY_MEMORY_ENABLED=true` was set only on the backend API container; the celery-worker container (which actually runs H/H simulation tasks) did not have it. `settings.OBSERVED_PLAY_MEMORY_ENABLED` evaluated `False` in the worker, so `_fetch_observed_play_block` returned `""` immediately without fetching any evidence. The preview API endpoint worked because it ran in the backend container.

Additional issue: the evidence kind validator only allowed `card_performance|synergy|round_result|candidate_metric`; `observed_play` was absent. Even after the env fix, the LLM would be unable to cite observed-play evidence IDs in the structured `evidence` field.

### What was changed

- **`docker-compose.override.yml`** — Added `OBSERVED_PLAY_MEMORY_ENABLED: "true"` to celery-worker environment
- **`backend/app/coach/analyst.py`** — Added INFO-level logging in `_fetch_observed_play_block`: logs evidence_count, evidence_ids[:3], would_inject, and injection char count. Added `"observed_play"` to valid evidence kinds in `_validate_swap_response`
- **`backend/app/coach/prompts.py`** — Added `observed_play` to the evidence kind schema; added instruction to cite observed-play event IDs using kind `observed_play` when OBSERVED PLAY EVIDENCE block is present
- **`backend/app/api/simulations.py`** — Added read-only `GET /api/simulations/{id}/coach-debug` endpoint: returns flag state, all DeckMutations with evidence JSONB, extracted observed_play citations, and current context preview excerpt
- **Tests** — Added `TestGetSimulationCoachDebug` (6 tests) in test_simulations.py; added `test_observed_play_is_valid_evidence_kind` in TestCoachAnalystObservedPlay; updated 3 prompt-content assertions to use `"— REVIEW ONLY"` suffix (distinguishing the actual block from the instruction reference)

### Files changed

- `docker-compose.override.yml`
- `backend/app/coach/analyst.py`
- `backend/app/coach/prompts.py`
- `backend/app/api/simulations.py`
- `backend/tests/test_api/test_simulations.py`
- `backend/tests/test_coach/test_analyst.py`
- `docs/STATUS.md`, `docs/CHANGELOG.md`

### Validation

- Backend: **1183 passed, 1 skipped**
- Frontend: **339 passed (17 files)**
- No observed-play memory behavior, simulation mutation logic, AI Player, pgvector, Neo4j, match_events, card_performance, or deck-builder changed.

## Session 53 Work (2026-05-10) — PTCGL Format Deck Export

### Root cause

The Final Candidate Deck Copy button copied internal TCGdex IDs (`4 sv06-130`, `1 me01-113`) because `Deck.deck_text` is always stored in internal format. The `final_deck_text` and `original_deck_text` fields passed through that internal text directly.

### What was changed

- **`GET /api/simulations/{id}/final-deck`** — extended to return:
  - `original_ptcgl_text` and `final_ptcgl_text`: human-readable PTCGL-grouped text
    (e.g. `"Pokémon: 10\n3 Dragapult ex TWM 130\n…"`)
  - `metadata_warnings`: list of cards that couldn't be fully formatted due to missing metadata
  - Each card dict now includes `set_abbrev`, `set_number`, `category`, `ptcgl_line` fields
  - All existing fields (`original_deck_text`, `final_deck_text`, `changed_cards`, etc.) unchanged
- **`_build_ptcgl_text()` helper** — pure module-level function; groups cards into Pokémon / Trainer / Energy / Other sections with section counts; sorts by name within sections; falls back to TCGdex ID + emits warning if name/set data missing
- **`DeckEvolutionPanel`** — main Copy button now copies `final_ptcgl_text`; label is "Copy PTCGL decklist"; original deck section also has "Copy PTCGL decklist" button; collapsible `<pre>` blocks show full PTCGL text; metadata warnings displayed in yellow box when present
- **Types** — `DeckCardEntry` gains `set_abbrev`, `set_number`, `category`, `ptcgl_line`; `FinalDeckResponse` gains `original_ptcgl_text`, `final_ptcgl_text`, `metadata_warnings`

### Files changed

- `backend/app/api/simulations.py` — `_build_ptcgl_text()` helper + extended `_fetch_deck_cards` + new response fields
- `backend/tests/test_api/test_simulations.py` — `TestBuildPtcglText` (8 unit tests) + 4 new endpoint tests
- `frontend/src/components/simulation/DeckEvolutionPanel.tsx` — PTCGL copy/display, metadata warnings
- `frontend/src/components/simulation/DeckEvolutionPanel.test.tsx` — 16 tests (was 13)
- `frontend/src/types/simulation.ts` — extended `DeckCardEntry` + `FinalDeckResponse`
- `docs/STATUS.md`, `docs/CHANGELOG.md`

### Validation

- Backend: **1176 passed, 1 skipped**
- Frontend: **339 passed (17 files)**, build clean
- No Coach logic, observed-play memory, AI Player, pgvector, Neo4j,
  match_events, card_performance, deck-builder, data reset, or runtime
  integration changed.

## Session 52 Work (2026-05-09) — Final Candidate Deck / Deck Evolution Panel

### What was added

After multi-round H/H simulations, users can now see the full deck evolution:

- **`GET /api/simulations/{id}/final-deck`** — returns original deck cards,
  final working deck cards, changed-card summary (original count → final count),
  `has_mutations` flag, and deck text for copy/export.
- **`DeckEvolutionPanel`** React component — read-only tile showing:
  - Safety note: "Original deck was not overwritten"
  - Changed-cards table (before → after counts, green/red)
  - Collapsible final candidate decklist + Copy button
  - Collapsible original decklist
  - "No mutations applied" state when deck unchanged
- **Dashboard** integration: "Final Candidate Deck" tile added as full-width
  tile after the Deck Mutation Log tile.
- 5 new backend tests for `/final-deck` endpoint (404, 422, has_mutations
  false, has_mutations true, changed_cards shape).
- 13 new frontend tests for `DeckEvolutionPanel`.
- TODO: save-as-new path deferred — panel is read-only.

### Files changed

- `backend/app/api/simulations.py` — new `GET /{id}/final-deck` endpoint
- `backend/tests/test_api/test_simulations.py` — 5 new endpoint tests
- `frontend/src/components/simulation/DeckEvolutionPanel.tsx` — new component
- `frontend/src/components/simulation/DeckEvolutionPanel.test.tsx` — 13 tests
- `frontend/src/pages/Dashboard.tsx` — imports + finalDeck state + new tile
- `frontend/src/api/simulations.ts` — `getSimulationFinalDeck()` added
- `frontend/src/types/simulation.ts` — `FinalDeckResponse`, `DeckCardEntry`, `ChangedCard` types
- `docs/STATUS.md`, `docs/CHANGELOG.md`

### Validation

- Backend: **1165 passed, 1 skipped**
- Frontend: **336 passed (17 files)**, build clean
- No Coach logic, observed-play memory, AI Player, pgvector, Neo4j,
  match_events, card_performance, deck-builder, data reset, or runtime
  integration changed.

## Session 51 Work (2026-05-09) — Multi-round Coach Simulation Deck Versioning Fix

### Root cause

After round 1 of a multi-round H/H simulation, Coach applied card swaps and
`_apply_mutations` updated `current_deck_cards` in memory. Round 2 then called
`ensure_deck_cards_for_id(user_deck_id, ..., current_deck_cards)` — passing the
original user deck UUID but now-mutated card contents. The guard in
`MatchMemoryWriter.ensure_deck_cards_for_id` saw that existing `DeckCard` rows
for `user_deck_id` (original contents) didn't match the mutated `current_deck_cards`
and raised `ValueError`. Original user deck rows were never modified — the mismatch
was caused by reusing `user_deck_id` with mutated contents.

### Fix (Option 2 — run-specific working deck versioning)

- `simulation.py`: Track `current_p1_deck_id` (starts as `user_deck_id`). After
  each Coach mutation where the deck text actually changes, create a new
  `Deck` row (`source="simulation"`, name `"<deck> — sim <id8> r<N>"`) via
  `ensure_deck_cards_for_id` with a fresh UUID and update `current_p1_deck_id`.
  Subsequent rounds use `current_p1_deck_id` (the working clone), leaving the
  original user deck and its `DeckCard` rows immutable.
- `best_p1_deck_id` mirrors `best_deck_cards` for regression-revert correctness.
- Round `deck_snapshot` stores `working_deck_id` so Celery retries restore the
  correct working deck UUID.
- At completion, `final_working_deck_id` is stored in `best_deck_snapshot` JSONB
  (no migration required).
- `memory/postgres.py`: Improved `ensure_deck_cards_for_id` error to include
  expected/actual count maps and per-card diffs.
- `api/simulations.py`: `GET /{id}` now returns `user_deck_id` and
  `final_working_deck_id`.
- 5 new backend checkpointing tests covering: original deck immutability, mutated
  working deck acceptance, mismatch error details, `source="simulation"` attribute,
  and round snapshot `working_deck_id` persistence.

### Files changed

- `backend/app/tasks/simulation.py`
- `backend/app/memory/postgres.py`
- `backend/app/api/simulations.py`
- `backend/tests/test_tasks/test_simulation_checkpointing.py`

### Validation

- Backend: **1160 passed, 1 skipped**
- Frontend: **323 passed (16 files)**, build clean
- No AI Player, pgvector, Neo4j, observed-play memory, match_events,
  card_performance, deck-builder, data reset, or runtime integration changed.

## Session 50 Work (2026-05-09) — Coach LLM + UI Triage & Fix

### Root cause

A completed H/H simulation produced no visible card swaps and Coach reasoning
was invisible in the UI. Investigation revealed two separate root causes:

**Coach LLM (backend `analyst.py`):**
- Ollama payload lacked `"format": "json"` → model returned prose instead of
  JSON on attempt 1 → `invalid_json` parse error → WARNING emitted.
- `num_predict: 768` was too small for a full Coach response with evidence.
- Repair prompt replaced the user message with only the error text — no deck
  context — so attempt 2 returned `{"swaps": [], "analysis": "..."}` with 0
  swaps. This is the deliberate security design (prevents hostile context
  resend); now `"format": "json"` makes attempt 1 succeed, so repair is a
  last-resort only.

**Frontend (mutation display):**
- `useSimulation.ts` mapped live WebSocket `deck_mutation` events using
  `ev.card_in`/`ev.card_out` but backend publishes `ev.add`/`ev.remove`.
- Mutations were never fetched from REST on init — only from live WS — so
  navigating to a completed sim showed 0 swaps.
- `DeckMutation` type used `round`/`card_in`/`card_out`; REST API returns
  `round_number`/`card_removed`/`card_added`/`reasoning`.
- `DeckChangesTile` showed no reasoning field.

### Changes

**`backend/app/coach/analyst.py`:**
- Added `"format": "json"` to Ollama payload — forces JSON output on first attempt.
- Increased `num_predict: 768 → 2048` — prevents mid-response truncation.
- `_get_swap_decisions`: logs `analysis` field at INFO when 0 swaps returned.
- `_get_swap_decisions`: WARNING now includes raw response preview (200 chars).
- `_get_swap_decisions`: ERROR on all-retries-fail includes last raw preview.
- `_call_ollama`: logs WARNING when Ollama returns empty content.

**`frontend/src/types/simulation.ts`:**
- `DeckMutation` updated to `round_number`/`card_removed`/`card_added`/`reasoning`
  (aligns with REST API and `MutationRow` in `dashboard.ts`).

**`frontend/src/stores/simulationStore.ts`:**
- Added `setMutations(mutations: DeckMutation[])` action for bulk REST load.

**`frontend/src/hooks/useSimulation.ts`:**
- Added `getSimulationMutations` import and REST fetch on init; mutations loaded
  from REST immediately (covers completed sims navigated from History).
- Fixed WS `deck_mutation` handler: `ev.add`/`ev.remove` → `card_removed`/`card_added`.
- `reasoning` now passed through from WS events.

**`frontend/src/components/simulation/DeckChangesTile.tsx`:**
- Updated to use new field names (`round_number`, `card_removed`, `card_added`).
- Added per-mutation expandable "Show/Hide reasoning" button.
- Empty state updated: "No deck swaps recommended" + "Coach analysed results but
  found no valid improvements to suggest".

**`backend/tests/test_coach/test_analyst.py`:**
- Added `TestCoachLLMLogging` class with 4 new tests:
  - `test_zero_swaps_logs_analysis` — analysis field logged at INFO.
  - `test_parse_failure_logs_raw_preview` — raw preview in ERROR on all-retries-fail.
  - `test_parse_failure_warning_includes_raw_preview` — raw in WARNING per attempt.
  - `test_ollama_payload_uses_json_format` — `format=json` + `num_predict=2048` verified.

**`frontend/src/components/simulation/DeckChangesTile.test.tsx`** (NEW — 10 tests):
- Empty state, swap count badge, card name render, round badge, reasoning expand/collapse.

### Validation

```text
Backend: 1155 passed, 1 skipped
Frontend: 323 passed (16 files)
Build: clean
OBSERVED_PLAY_MEMORY_ENABLED=false (unchanged default)
docs/AUDIT_STATE.md: not touched
```

No AI Player, simulator runtime, deck builder, pgvector, Neo4j,
`match_events`, `card_performance`, observed-play memory runtime, or gameplay
integration added or changed.
No data reset, force ingest, automatic ingestion, or DB mutations.

---

## Session 49 Work (2026-05-08) — Phase 6.1 End-Session Checkpoint

### Status

Phase 6.1 is **complete** at commit `e44681a`. This session records the
end-of-session checkpoint only. No new feature work was performed.

### Manual verification pending (next session)

The following must be confirmed before starting Phase 6.2:

1. **Flag-off:** `GET /api/observed-play/coach-context-preview` returns `enabled=false`, `would_inject=false`, `prompt_block=""` with default config.
2. **Flag-off Coach prompt:** Coach prompts are byte-for-byte identical to pre-6.1 behavior.
3. **Flag-on:** With `OBSERVED_PLAY_MEMORY_ENABLED=true` (local only), preview returns `would_inject=true`, bounded evidence block, readiness verdict, source-linked IDs, citation instructions. Test with `Dragapult ex`, `Salazzle ex`, `Dreepy`.
4. **No mutation:** `observed_play_logs`, `observed_play_events`, `observed_card_mentions`, `observed_play_memory_ingestions`, `observed_play_memory_items` row counts unchanged after preview calls.
5. **Reset flag:** Return to `OBSERVED_PLAY_MEMORY_ENABLED=false` after validation.

### Confirmed state at checkpoint

```text
Branch:    feature/observed-play-memory
HEAD:      e44681a25e3cdb8a4e59510dd6f1ee1782c4ed2f
DB:        g3h4i5j6k7l8 (head)
Backend:   1151 passed, 1 skipped
Frontend:  313 passed (15 files)
Build:     clean
Flag default: OBSERVED_PLAY_MEMORY_ENABLED=false
```

No AI Player, simulator runtime, deck builder, pgvector, Neo4j,
`match_events`, `card_performance`, or gameplay integration added.
No data reset, force ingest, automatic ingestion, or DB mutations.
`docs/AUDIT_STATE.md` not touched.

---

## Session 48 Work (2026-05-09) — Phase 6.1 Feature-Flagged Coach Prompt Evidence

### Goal

Wire the Phase 6.0 observed-play evidence layer into the Coach prompt/context
path behind `OBSERVED_PLAY_MEMORY_ENABLED=false` (default off). When enabled,
Coach can receive a bounded, source-linked observed-play evidence block with
review-only instructions and evidence IDs, gated by corpus readiness. Observed
memory remains advisory only and does not affect AI Player, simulator runtime,
deck builder, pgvector, Neo4j, match_events, card_performance, or gameplay decisions.

### Changes

**Backend (`backend/app/config.py`):**
- Added `OBSERVED_PLAY_MEMORY_ENABLED: bool = False`, `OBSERVED_PLAY_MEMORY_MAX_EVIDENCE: int = 8`, `OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE: float = 0.85`.

**Backend (`backend/app/observed_play/readiness_service.py`)** (NEW):
- Extracted `compute_corpus_readiness()` and `build_coach_evidence_filter()` from `api/observed_play.py` into shared importable module to prevent circular imports.

**Backend (`backend/app/observed_play/schemas.py`):**
- Appended Phase 6.1 schemas: `ObservedPlayCoachContextQuery`, `ObservedPlayEvidencePromptItem`, `ObservedPlayCoachContextPreview`.

**Backend (`backend/app/observed_play/coach_context.py`)** (NEW):
- Feature flag check, readiness gate, evidence fetch (re-using `build_coach_evidence_filter`), prompt block formatter, preview builder.
- `build_coach_context_preview(db, ...)` is the main entry point.
- `_REVIEW_ONLY_HEADER` defines prompt preamble with citation instructions.

**Backend (`backend/app/api/observed_play.py`):**
- Added `GET /api/observed-play/coach-context-preview` read-only endpoint.
- Refactored: readiness functions now imported from `readiness_service`.

**Backend (`backend/app/coach/analyst.py`):**
- Added `observed_play_block=""` param to `_build_prompt_messages` (no-op when empty).
- Added `_fetch_observed_play_block()` async helper: returns `""` when flag is off; calls `build_coach_context_preview`; returns `preview.prompt_block` if `would_inject`; catches all exceptions (safe fallback).
- Updated `analyze_and_mutate` to call `_fetch_observed_play_block()` before building prompt. With default-off flag, Coach prompts are byte-for-byte identical to pre-6.1.

**Backend tests (`backend/tests/test_api/test_observed_play.py`):**
- Appended `TestCoachContextPreview` class with 14 tests.

**Backend tests (`backend/tests/test_coach/test_analyst.py`):**
- Appended `TestCoachAnalystObservedPlay` class with 8 tests covering flag-off/on, prompt position, `_fetch_observed_play_block` behavior, and exception safety.

**Frontend (`frontend/src/types/observedPlay.ts`):**
- Added `ObservedPlayCoachContextPreview` and `GetCoachContextPreviewParams` interfaces.

**Frontend (`frontend/src/api/observedPlay.ts`):**
- Added `getCoachContextPreview(params?)` function calling `GET /api/observed-play/coach-context-preview`.

**Frontend (`frontend/src/pages/ObservedPlay.tsx`):**
- Added `CoachContextPreviewSection` component: shows flag status, readiness verdict, would_inject, reason, warnings, evidence count/IDs, prompt block preview.
- Wired into page after `CoachEvidenceSection`.

**Frontend tests (`frontend/src/pages/ObservedPlay.test.tsx`):**
- Added `getCoachContextPreview: vi.fn()` to mock and default `beforeEach` return.
- Added `CoachContextPreviewSection` describe block with 11 tests.

### Validation

```text
Backend: 1151 passed, 1 skipped
Frontend: 313 passed (15 files)
Frontend build: clean
No DB mutations. No writes to Neo4j, pgvector, match_events, card_performance.
OBSERVED_PLAY_MEMORY_ENABLED defaults to false.
```

### Scope adherence

- No AI Player, simulator runtime, deck builder, pgvector, Neo4j, match_events, card_performance, or gameplay integration.
- No data reset, force ingest, automatic ingestion.
- No new DB migrations.
- `docs/AUDIT_STATE.md` not touched.
- No real logs, screenshots, database dumps, or .env secrets committed.

## Session 47 Work (2026-05-09) — Phase 6.0 Coach-Only Advisory Evidence

### Goal

Add a read-only Coach advisory evidence layer that lets the Coach inspect
observed-play memory items as source-linked evidence. The integration is
advisory only — observed memory is not used by AI Player, simulator runtime,
deck builder, pgvector, Neo4j, match_events, card_performance, or gameplay decisions.

### Changes

**Backend (`backend/app/observed_play/schemas.py`):**
- Added Phase 6.0 constants: `COACH_EVIDENCE_DEFAULT_MIN_CONFIDENCE = 0.80`, `COACH_EVIDENCE_DEFAULT_LIMIT = 25`, `COACH_EVIDENCE_MAX_LIMIT = 100`.
- Added 4 new Pydantic schemas: `CoachEvidenceQuery`, `CoachEvidenceSummary`, `CoachEvidenceItem`, `CoachEvidenceResponse`.

**Backend (`backend/app/api/observed_play.py`):**
- Refactored `get_corpus_readiness` body into `async def _compute_corpus_readiness(db)` helper (shared by scorecard endpoint and coach-evidence readiness gate).
- `GET /api/observed-play/corpus-readiness` now delegates to `_compute_corpus_readiness`.
- Added `_build_coach_evidence_filter()` helper for reusable evidence WHERE clauses.
- Appended `GET /api/observed-play/coach-evidence` endpoint: readiness gate (HTTP 409 for `not_ready`), 7 aggregate queries (count, avg, memory_type distribution, top actors/targets/actions, evidence JOIN with log filename). Excludes unresolved card references and items below min_confidence by default.

**Frontend (`frontend/src/types/observedPlay.ts`):**
- Appended Phase 6.0 interfaces: `CoachEvidenceQuery`, `CoachEvidenceSummary`, `CoachEvidenceItem`, `CoachEvidenceResponse`, `GetCoachEvidenceParams`.

**Frontend (`frontend/src/api/observedPlay.ts`):**
- Added `CoachEvidenceResponse`, `GetCoachEvidenceParams` to imports.
- Appended `getCoachEvidence(params)` function.

**Frontend (`frontend/src/pages/ObservedPlay.tsx`):**
- Added `getCoachEvidence` import and `CoachEvidenceResponse`, `CoachEvidenceItem` type imports.
- Added `CoachEvidenceSection` component: search form (card name, memory type, action name, min confidence, limit), summary badges, evidence table with source raw line, 409 error state with blockers, needs-review warning display, dark mode.
- Added `<CoachEvidenceSection />` after `<CorpusScorecardSection />`.

**Tests:**
- `backend/tests/test_api/test_observed_play.py`: +16 backend tests (`TestCoachEvidence` class, patches `_compute_corpus_readiness`).
- `frontend/src/pages/ObservedPlay.test.tsx`: +14 frontend tests (Phase 6.0 `CoachEvidenceSection` describe block), added `getCoachEvidence: vi.fn()` to mock and `beforeEach` default.

### Validation

- Backend: **1129 passed, 1 skipped** (was 1108, +21 net new).
- Frontend: **300 passed** (was 285, +15 new).
- Frontend build: clean.
- No data reset, force ingest, automatic ingestion, AI Player, pgvector, Neo4j, simulator match_events, card_performance writes, deck-builder usage, or runtime memory usage added.
- `docs/AUDIT_STATE.md` not touched.
- No real logs, screenshots, database dumps, or raw audit reports committed.

---

## Session 46 Work (2026-05-09) — Phase 5.2 Corpus Quality / Readiness Scorecard

### Goal

Build a read-only Corpus Quality / Readiness Scorecard for the 49-log observed-play corpus. Summarise corpus coverage, parser quality, card-resolution burden, and memory quality. Provide a deterministic verdict (ready / needs_review / not_ready) and 0–100 readiness score. Strictly review-only — no Coach/AI, pgvector, Neo4j, simulator, card-performance, deck-builder, or runtime integration.

### Changes

**Backend (`backend/app/observed_play/schemas.py`):**
- Added 5 threshold constants: `READINESS_LOW_CONFIDENCE_EVENT_THRESHOLD = 0.80`, `READINESS_INGESTION_COVERAGE_THRESHOLD = 0.90`, `READINESS_AVG_EVENT_CONFIDENCE_THRESHOLD = 0.85`, `READINESS_AVG_MEMORY_CONFIDENCE_THRESHOLD = 0.75`, `READINESS_TOP_N_LIMIT = 10`.
- Added 5 new Pydantic schemas: `CorpusStats`, `ParserQualityStats`, `CardResolutionStats`, `MemoryQualityStats`, `CorpusReadinessReport`.

**Backend (`backend/app/api/observed_play.py`):**
- Added `or_` to sqlalchemy imports.
- Added new schema names to import block.
- Defined `_READINESS_CRITICAL_ROLES` inline (mirrors `_CRITICAL_MENTION_ROLES` from memory_ingestion.py, avoids circular imports).
- Appended `GET /api/observed-play/corpus-readiness` endpoint (~250 lines): 17 scalar queries + 3 fetchall queries across all 6 observed-play tables. Scores: Parser quality 35 pts + Ingestion coverage 25 pts + Card resolution 20 pts + Memory quality 20 pts = 100 max. Verdict: `not_ready` if any blocker, `needs_review` if any warning but no blockers, `ready` otherwise.

**Frontend (`frontend/src/types/observedPlay.ts`):**
- Appended Phase 5.2 TypeScript interfaces: `CorpusStats`, `ParserQualityStats`, `CardResolutionStats`, `MemoryQualityStats`, `CorpusReadinessReport`.

**Frontend (`frontend/src/api/observedPlay.ts`):**
- Added `CorpusReadinessReport` to imports.
- Appended `getCorpusReadiness()` function.

**Frontend (`frontend/src/pages/ObservedPlay.tsx`):**
- Added `getCorpusReadiness` import and `CorpusReadinessReport` type import.
- Added `VerdictBadge`, `ScorecardStatRow`, `CorpusScorecardSection` components.
- Updated phase banner to mention Phase 5.2.
- Added `<CorpusScorecardSection />` after `<MemoryAnalyticsSection />`.

**Tests:**
- `backend/tests/test_api/test_observed_play.py`: +17 backend tests (`TestCorpusReadiness` class — 14 endpoint tests + 3 helpers).
- `frontend/src/pages/ObservedPlay.test.tsx`: +17 frontend tests (Phase 5.2 describe block), fixed default mock collision (`memory_type_counts: []` in `beforeEach`).

### Phase 5.2 Corpus Scorecard — Live 49-Log Corpus Result

```
verdict:                ready
readiness_score:        97.22 / 100
logs:                   49 total / 49 parsed / 49 ingested / 0 failed
events:                 10,047
memory items:           4,786
unknown events:         0
events below 80%:       0
avg event confidence:   0.8879
avg log confidence:     0.8877
avg memory confidence:  0.8899
card mentions:          8,670 total / 8,670 resolved / 0 ambiguous / 0 unresolved / 0 critical unresolved
blockers:               []
warnings:               []
recommendations:        []
```

The corpus meets all readiness criteria. It is ready for limited downstream experimentation later (Phase 6 Coach-only advisory integration).

### Validation

- Backend: **1108 passed, 5 skipped** (was 1095, +17 new tests including recount).
- Frontend: **285 passed** (was 268, +17 new tests).
- Frontend build: clean.
- No Phase 6, data reset, force ingest, automatic ingestion, Coach/AI, pgvector, Neo4j writes, simulator match_events, card_performance writes, deck-builder usage, or runtime memory usage added.
- `docs/AUDIT_STATE.md` not touched.
- No real logs, screenshots, database dumps, or raw audit reports committed.

---

## Session 45 Work (2026-05-09) — Pre-Phase-5.2 Corpus Parser Triage / Hardening

### Goal

Automate the parser-hardening workflow. Create a read-only low-confidence audit script, run it against the 49 real battle logs, identify recurring parser gaps, improve parser patterns, reparse/re-ingest using the bulk debug options, and confirm the corpus drops to 0 events below 80% confidence.

### Changes

**New script:**
- `backend/scripts/observed_play_low_confidence_audit.py`: Read-only audit against live DB. `--threshold` and `--top` args. Outputs totals, by-event-type breakdown, top raw lines, normalised pattern groups, and per-log summary. Invoked via `docker compose exec backend python scripts/observed_play_low_confidence_audit.py --threshold 0.80 --top 200`. Does not write raw lines to the repo; `--output` paths should be under `tmp/` (added to `.gitignore`).

**Backend parser (`backend/app/observed_play/`):**
- `constants.py`: Added `ET_PLAYER_TIMEOUT = "player_timeout"` and `ET_PLAYER_RECONNECTED = "player_reconnected"` (informational system events, not ingested into memory).
- `patterns.py`: Added `RE_MULLIGAN_PLURAL` ("PLAYER took N mulligans."), four alternative game-end patterns (`RE_GAME_END_PRIZES_OPPONENT`, `RE_GAME_END_DECK_YOURS`, `RE_GAME_END_KO_NO_BENCH`, `RE_GAME_END_NO_BENCH_BACKUP`), and two system-event patterns (`RE_PLAYER_TIMEOUT`, `RE_PLAYER_RECONNECTED`).
- `confidence.py`: `card_effect_activated` now returns 0.88 (was 0.78) when `card_name_raw` is captured. The card name is always captured by `RE_CARD_EFFECT_ACTIVATED`, so this removes the only event type hardcoded below the 0.80 gate.
- `parser.py`: Added handlers for the 7 new patterns. Mulligan plural maps to `ET_MULLIGAN` with `amount` set. Game-end variants map to `ET_GAME_END` with appropriate `win_condition` values. Timeout/reconnect map to their own event types with `player_raw`/`player_alias`.

**Tests:**
- `tests/test_observed_play/test_parser.py`: +18 tests — `TestGameEndVariants` (6 tests for 4 new game-end patterns), `TestMulliganPlural` (5 tests), `TestPlayerSystemEvents` (7 tests). Also updated `card_effect_activated` confidence test to assert >= 0.88.

**Gitignore:**
- `.gitignore`: Added `tmp/` to prevent accidental commits of audit reports containing raw log lines.

### Pre-fix corpus baseline (old parser on existing DB)

- Total events: 10,047
- Events below 80%: **188** (1.9% of total)
  - `card_effect_activated`: 150 events at 0.78 (fixed: confidence raised to 0.88)
  - `unknown`: 38 events at 0.30 (fixed: 4 new game-end patterns, mulligan plural, timeout, reconnect)
- Average corpus confidence: 0.8840

### Post-fix corpus results (after bulk reparse + re-ingest)

- Events below 80%: **0** (0.0% of total)
- Unknown events: **0**
- Average corpus confidence: 0.8879
- All 49 logs reparsed; all 49 re-ingested; idempotency confirmed on second run.

### Validation

- Backend: 1095 passed, 1 skipped (was 1077, +18 new tests).
- Frontend: 268 passed, build clean.
- No Phase 5.2, data reset, automatic ingestion, Coach/AI integration, pgvector, Neo4j writes, simulator match_events, card_performance writes, deck-builder usage, or runtime memory usage added.

## Session 44 Work (2026-05-09) — Bulk Action Opt-in Flags

### Goal

Revise Observed Play bulk actions for testing/debugging workflows. Both defaults remain production-safe (already-ingested logs are skipped unless user opts in).

### Changes

**Backend:**
- `schemas.py`: Added `BulkReparseRequest` and `BulkIngestEligibleRequest` request schemas. Extended `BulkReparseLogResult` (`had_existing_memory`, `memory_warning`), `BulkReparseSummary` (`ingested_reparsed_count`), `BulkIngestPreviewLog` (`eligible_for_reingest` status), `BulkIngestEligiblePreview` (`eligible_for_reingest_count`, `include_already_ingested`), `BulkIngestLogResult` (`reingested` status), `BulkIngestEligibleSummary` (`reingested_count`, `include_already_ingested`).
- `api/observed_play.py`: Updated `reparse_all_logs`, `preview_ingest_eligible`, and `ingest_all_eligible` to accept optional request bodies. Reparse: opt-in `include_ingested` flag (default false) — reparsed ingested logs get `had_existing_memory=true` and `memory_warning`. Ingest: opt-in `include_already_ingested` flag (default false) — re-ingested logs use `status=reingested` and appear in `ingested_logs`.
- `tests/test_api/test_observed_play.py`: +16 backend tests.

**Frontend:**
- `types/observedPlay.ts`: Added `BulkReparseRequest`, `BulkIngestEligibleRequest` interfaces. Extended existing bulk interfaces with new fields.
- `api/observedPlay.ts`: Updated `bulkReparseAll`, `bulkPreviewEligible`, `bulkIngestEligible` to accept options objects.
- `pages/ObservedPlay.tsx`: Added `bulkIncludeIngested` and `bulkIncludeAlreadyIngested` state. Parse modal: checkbox to opt in to reparsing ingested logs with conditional warning text; result shows `ingested_reparsed_count` when non-zero. Ingest modal: checkbox to opt in to re-ingesting already-ingested eligible logs with replacement warning; preview refreshes on toggle; result shows `reingested_count` as separate column when non-zero.
- `pages/ObservedPlay.test.tsx`: +9 frontend tests.

### Validation

- Bulk actions now support explicit testing/debugging overrides. Parse/Reparse all can include already-ingested logs when the user opts in (default: skip); reparsing refreshes parse/card-mention data without changing memory. Ingest all eligible can re-ingest already-ingested eligible logs when the user opts in (default: skip); existing observed memory items for those logs are replaced rather than duplicated.
- No Phase 5.2, data reset, automatic ingestion, Coach/AI integration, pgvector, Neo4j writes, simulator match_events, card_performance writes, deck-builder usage, or runtime memory usage added.

## Session 43 Work (2026-05-08) — Bulk Parse / Ingest Actions

### Goal

Add safe bulk workflow actions to `/observed-play` to avoid manually reparsing and ingesting 49 uploaded battle logs one at a time.

### Changes

**Backend:**
- `schemas.py`: Added `BulkReparseLogResult`, `BulkReparseSummary`, `BulkIngestPreviewLog`, `BulkIngestEligiblePreview`, `BulkIngestLogResult`, `BulkIngestEligibleSummary` Pydantic models.
- `api/observed_play.py`: Added three endpoints:
  - `POST /logs/reparse-all` — reparses all non-ingested logs, commits per-log, skips `memory_status=ingested`.
  - `POST /memory-ingestion/preview-eligible` — read-only eligibility preview using same gates as single-log.
  - `POST /memory-ingestion/ingest-eligible` — ingests all eligible logs, commits per-log, idempotent.
- `tests/test_api/test_observed_play.py`: +18 backend tests covering all three endpoints.

**Frontend:**
- `types/observedPlay.ts`: Added bulk TypeScript interfaces.
- `api/observedPlay.ts`: Added `bulkReparseAll`, `bulkPreviewEligible`, `bulkIngestEligible` functions.
- `pages/ObservedPlay.tsx`: Added "Bulk Actions" panel between import report and Raw Logs sections with two buttons. Added inline `BulkParseModal` (confirm → run → show counts/confidence) and `BulkIngestEligibleModal` (preview eligibility → confirm ingest → show results). Post-action refreshes raw logs, memory analytics, and unresolved cards.
- `pages/ObservedPlay.test.tsx`: +13 frontend tests for bulk actions.

### Validation

- Backend: 1065 passed, 1 skipped
- Frontend: 259 passed (15 files), build clean
- No data reset, Phase 5.2, Coach/AI, pgvector, Neo4j, simulator, card-performance, deck-builder, or runtime integration.

## Session 42 Work (2026-05-07) — Parser Hardening: Special Conditions, Damage Counters, Checkup, Concession

### Goal

Harden the PTCGL log parser for real-corpus lines from a Dragapult ex vs Salazzle ex log that produced `unknown` events, lowering the log's ingestion eligibility score.

### Root causes

Parser had no patterns for: Pokémon Checkup markers, Burned/Poisoned condition damage counters, special condition applied/removed lines, checkup coin flips, ability-driven damage counter placement/movement, discarded card counts, cards moved to hand, cards shuffled into deck (with known-card sub-lines), and opponent concession game-end lines.

### Backend changes

- `constants.py`: Added 11 new event type constants: `ET_POKEMON_CHECKUP`, `ET_SPECIAL_CONDITION_APPLIED`, `ET_SPECIAL_CONDITION_REMOVED`, `ET_SPECIAL_CONDITION_DAMAGE`, `ET_DAMAGE_COUNTERS_PLACED`, `ET_DAMAGE_COUNTERS_MOVED`, `ET_POKEMON_SWITCHED`, `ET_CARDS_DISCARDED`, `ET_CARDS_DISCARDED_FROM_POKEMON`, `ET_CARDS_MOVED_TO_HAND`, `ET_CARDS_SHUFFLED_INTO_DECK`.
- `patterns.py`: Added 13 new compiled regexes covering all new event types including singular/plural variants and curly-apostrophe support.
- `confidence.py`: Added scoring entries for all new event types (0.82–0.97).
- `parser.py`: Added dispatch blocks for all new patterns; bullet sub-line capture for card lists in discard/move/shuffle events.
- `card_mentions.py`: Extended `_IGNORED_NORMALIZED` (burned, poisoned, paralyzed, confused, asleep, heads, tails, damage counters); added extraction branches for new event types; added payload card list extraction for discard/move/shuffle events.
- New fixture: `backend/tests/fixtures/observed_play/special_conditions_and_concession.md`
- New tests: 52 parser tests, 20 card-mention tests, 11 memory-ingestion tests (1047 backend total).

### Validation

- Backend: 1047 passed, 1 skipped
- Frontend: 246 passed (15 files), build clean
- No data reset, ingestion, Coach/AI, pgvector, Neo4j, simulator, card-performance, deck-builder, or runtime integration.



### Goal

Fix Raw Logs sorting for Parse and Cards columns discovered during real-corpus manual validation.

### Root causes

- **Parse**: `parse_status` sorted lexicographically on the raw string. With all 49 real logs at `parse_status="parsed"`, sorting appeared to do nothing. Fix: rank statuses with a `case()` expression (failed=0, raw_archived=1, parsed=2, parsed_with_warnings=3), tie-break with `confidence_score asc` so lower-confidence parsed logs surface for review within the same status group.
- **Cards**: `sort_by=ambiguous_card_count` was a single-column sort that didn't capture triage priority, and card counts may be similar across logs. Fix: add `sort_by=cards` as a new composite sort key (`unresolved_card_count → ambiguous_card_count → card_mention_count → confidence_score`). Frontend Cards header changed to use `sort_by=cards`. The `sort_by=cards` key was not in `LOG_SORT_FIELDS` (would have returned 422), making it unusable.

### Backend changes

- `LOG_SORT_FIELDS`: removed `parse_status` (now handled as composite)
- `_COMPOSITE_SORT_KEYS = {"parse_status", "cards"}` added
- `_ALL_SORT_KEYS = LOG_SORT_FIELDS.keys() | _COMPOSITE_SORT_KEYS` — used for whitelist validation
- `_apply_log_sort(q, sort_by, sort_dir)` extracted function:
  - `parse_status`: `case()` rank + `confidence_score asc` + stable tie-breaker
  - `cards`: composite multi-column sort (unresolved/ambiguous/total/confidence)
  - other: single-column + stable tie-breaker (unchanged)

### Frontend changes

- `LogSortKey` type: added `'cards'`
- Cards header: `sortKey="cards"` (was `"ambiguous_card_count"`), tooltip updated to mention unresolved/ambiguous/card mentions
- Parse header: tooltip added ("Sorts by parse status, then lower-confidence parsed logs.")

### Files changed

- `backend/app/api/observed_play.py` — composite sort logic
- `backend/tests/test_api/test_observed_play.py` — +4 HTTP tests (cards/parse), +6 `TestApplyLogSort` SQL unit tests (970 total)
- `frontend/src/pages/ObservedPlay.tsx` — `LogSortKey`, Cards header, Parse tooltip
- `frontend/src/pages/ObservedPlay.test.tsx` — updated Cards tests, +3 Parse tests (246 total)
- `docs/STATUS.md`, `docs/CHANGELOG.md`, `docs/proposals/OBSERVED_PLAY_MEMORY_IMPLEMENTATION_PLAN.md`

### Test results

- Frontend: **246 passed (15 files)** (+4 new tests)
- Backend: **970 passed, 1 skipped** (+10 new tests)
- Frontend build: **clean**

### Scope

Real-corpus sorting bugfix only. No Coach/AI, pgvector, Neo4j, simulator match_events, card_performance, deck-builder, runtime memory, data reset, or ingestion changes. No new DB migrations.

---

## Session 40 Work (2026-05-06) — Raw Logs Sorting

### Goal

Add sortable columns to the Raw Logs table for efficient real-corpus validation (49 uploaded logs).

### Implementation

Server-side sorting via `sort_by`/`sort_dir` query params (pagination is server-side). Backend whitelist validates 13 sort keys; invalid values return HTTP 422.

### Backend changes

- `GET /api/observed-play/logs`: added optional `sort_by` and `sort_dir` query params
- `LOG_SORT_FIELDS` dict maps 13 string keys to ORM columns (whitelisted; no SQL injection possible)
- Sort order: primary sort + stable tie-breaker (`created_at desc, id desc`)
- Default: `created_at desc` (preserves prior behavior)
- Invalid `sort_by`: HTTP 422 `"Invalid sort_by: ..."`
- Invalid `sort_dir`: HTTP 422 `"Invalid sort_dir: ..."`

Sort keys: `filename`, `parse_status`, `memory_status`, `event_count`, `confidence_score`, `card_mention_count`, `resolved_card_count`, `ambiguous_card_count`, `unresolved_card_count`, `memory_item_count`, `file_size_bytes`, `created_at`, `sha256_hash`

### Frontend changes

- `LogSortKey` union type + `SortableTh` component (accessible `<button>` with `▲`/`▼`/`↕` indicators and `aria-label`)
- `logSortBy`/`logSortDir` state; `fetchLogs` closes over sort state (dep array updated); `handleLogSort` toggles direction on active column, sets default dir on new column, resets page to 1
- All 10 Raw Logs table headers replaced with `<SortableTh>` components
- Cards column sorts by `ambiguous_card_count desc` with tooltip

### Files changed

- `backend/app/api/observed_play.py` — sort params + LOG_SORT_FIELDS
- `backend/tests/test_api/test_observed_play.py` — 11 new `TestLogListSort` tests (960 total)
- `frontend/src/api/observedPlay.ts` — `sort_by`/`sort_dir` in `ListLogsParams`
- `frontend/src/pages/ObservedPlay.tsx` — `SortableTh`, `LogSortKey`, sort state, `handleLogSort`, table headers
- `frontend/src/pages/ObservedPlay.test.tsx` — 10 new sorting tests (242 total)
- `docs/STATUS.md`, `docs/CHANGELOG.md`, `docs/proposals/OBSERVED_PLAY_MEMORY_IMPLEMENTATION_PLAN.md`

### Test results

- Frontend: **242 passed (15 files)** (+10 new sort tests)
- Backend: **960 passed, 1 skipped** (+11 new sort tests)
- Frontend build: **clean**

### Scope

Real-corpus review UI polish only. No Coach/AI, pgvector, Neo4j, simulator match_events, card_performance, deck-builder, runtime memory, data reset, or ingestion changes. No new DB migrations.

---

## Session 39 Work (2026-05-06) — Real-Corpus Bugfix

### Goal

Fix real-corpus manual testing bug: ambiguous card rows stopped disappearing from the Unresolved / Ambiguous Cards section after the first two sequential resolutions, requiring a manual browser refresh.

### Root cause

`ResolutionRuleModal` deferred the parent refresh until the user explicitly clicked "Close" and only if `affected_log_ids` was non-empty. After several resolutions the React closure over `onResolved` was stale or the condition was not met, so the refresh never fired. Additionally, `MemoryAnalyticsSection` fetched the unresolved lookup only once on mount, so analytics Review buttons stopped working after resolutions.

### Fix

- `ResolutionRuleModal`: call `onResolved()` immediately after `createResolutionRule` + `resolveCards` succeed, not conditionally on Close click. Removed `affectedAfterRule` state; simplified `handleClose`.
- `UnresolvedCardsSection`: added `onRefreshAnalytics` prop; `handleResolved` calls `load()`, `onRefreshLogs?.()`, and `onRefreshAnalytics?.()` every time. Guard `return null` so the section stays mounted while the modal is open (prevents premature unmount during the same render cycle).
- `MemoryAnalyticsSection.load()`: includes `getUnresolvedCards` in the Promise.all so the lookup is always current after any analytics refresh. `handleReviewResolved` unconditionally calls all refresh callbacks.
- Parent `ObservedPlay`: passes `onRefreshAnalytics={() => analyticsRefreshRef.current?.()}` to `<UnresolvedCardsSection>`.

### Files changed

- `frontend/src/pages/ObservedPlay.tsx` — all component changes
- `frontend/src/pages/ObservedPlay.test.tsx` — 2 existing tests updated + 8 new regression tests (232 total)
- `docs/STATUS.md`, `docs/CHANGELOG.md`, `docs/proposals/OBSERVED_PLAY_MEMORY_IMPLEMENTATION_PLAN.md`

### Test results

- Frontend: **232 passed (15 files)** (+8 new regression tests)
- Backend: **949 passed, 1 skipped** (no changes)
- Frontend build: **clean**

### Scope

Frontend state-refresh bugfix only. No Coach/AI, pgvector, Neo4j, simulator match_events, card_performance, deck-builder, runtime memory, data reset, or ingestion changes.

---

## Session 38 Work (2026-05-06) — End-of-Session Checkpoint

### Goal

End-of-session checkpoint. 49 real battle logs uploaded after data reset. No new feature work.

### Real corpus state after upload

**Import batch:** 1 batch, status: `completed`

| Field | Value |
|---|---|
| original_file_count | 49 |
| accepted_file_count | 49 |
| imported_file_count | 49 |
| duplicate_file_count | 0 |
| skipped_file_count | 0 |
| failed_file_count | 0 |
| started_at | 2026-05-06 20:01:56 UTC |
| finished_at | 2026-05-06 20:02:00 UTC |

**Post-upload table counts:**

| Table | Count |
|---|---|
| observed_play_import_batches | 1 |
| observed_play_logs | 49 |
| observed_play_events | 9,278 |
| observed_card_mentions | 7,093 |
| observed_card_resolution_rules | 2 |
| observed_play_memory_ingestions | 0 |
| observed_play_memory_items | 0 |

**Log quality snapshot:**

| parse_status | memory_status | logs | avg_confidence | event_range | unresolved_cards | ambiguous_cards |
|---|---|---|---|---|---|---|
| parsed | not_ingested | 49 | 0.878 | 86–403 | 0 | 5,066 |

**Key observations:**

- ✅ All 49 logs parsed successfully (`parse_status = parsed`)
- ✅ Average confidence 0.878 — above the 0.80 ingestion threshold
- ✅ Zero unresolved cards — no complete card-recognition failures
- ⚠️ 5,066 ambiguous card mentions across 49 logs (~103/log) — likely card versions that need resolution rules before or after ingestion
- ℹ️ 2 resolution rules already exist (created during session)
- ℹ️ 0 ingestions — no memory has been ingested yet; all logs remain `not_ingested`

**No ingestion performed. No Coach/AI integration. Memories remain review-only.**

### Files changed

- `docs/STATUS.md` only (checkpoint docs)

---

## Pre-Phase-5.2 Corpus Readiness Checkpoint (session 45 end-of-session)

This section replaces the now-completed "Tomorrow's Manual Validation Plan". All steps in that plan have been completed across sessions 39–45.

### Corpus state (confirmed 2026-05-09, after session 45)

```
Branch:                   feature/observed-play-memory
HEAD commit:              e50039d (fix(observed-play): harden parser from low-confidence corpus audit)
DB migration head:        g3h4i5j6k7l8

observed_play_logs:           49
observed_play_events:     10,047
observed_card_mentions:    8,670
observed_play_memory_ingestions:  198
observed_play_memory_items:   4,786

Events below 80% confidence:   0
Unknown events:                0
Average corpus confidence:     0.8879
Memory average confidence:     0.8899
Ambiguous reference count:     0
Unresolved reference count:    0
```

### Phase 5.2 readiness verdict

All readiness gates passed:
- ✅ All 49 logs ingest cleanly
- ✅ Unresolved references: 0
- ✅ Ambiguous references: 0 (all resolved during card review)
- ✅ Events below 80%: 0
- ✅ Unknown events: 0
- ✅ Bulk re-ingest idempotent (second run = same counts, no duplicates)
- ✅ No major parser bug detected across corpus

**Phase 5.2 can start next session.**

### What not to do at the start of Phase 5.2

- Do not re-upload or re-ingest logs.
- Do not run the reset script.
- Do not force-ingest ineligible logs.
- Do not lower confidence thresholds.
- Do not wire observed memory into Coach or AI.


---

## Session 37 Work (2026-05-06)

### Goal

Observed Play data reset: clear all development/test data before uploading real battle-log corpus.

### Summary

Created `scripts/reset_observed_play_data.sh` — a guarded local maintenance script that truncates all 7 observed-play tables and clears the observed-play upload archive/staging directories. Requires `--yes` flag; verifies tables before acting; prints pre- and post-reset counts. No card data, simulator matches, card_performance, audit state, Coach/AI, Neo4j, pgvector, or runtime memory integration touched.

### Pre-reset counts

| Table | Count |
|---|---|
| observed_play_import_batches | 48 |
| observed_play_logs | 45 |
| observed_play_events | 1196 |
| observed_card_mentions | 842 |
| observed_card_resolution_rules | 6 |
| observed_play_memory_ingestions | 6 |
| observed_play_memory_items | 158 |
| archive files | 4 |

All cleared to 0.

### Files changed

- `scripts/reset_observed_play_data.sh` (new)
- `docs/STATUS.md`, `docs/CHANGELOG.md`, `docs/proposals/OBSERVED_PLAY_MEMORY_IMPLEMENTATION_PLAN.md`

### Validation (session 37)

- Reset script: clean exit, all post-reset counts = 0 ✓
- Archive check: no files remaining ✓
- API smoke: logs total=0, memory summary zeroed, analytics empty ✓
- `cd backend && python3 -m pytest tests/ -x -q`: **949 passed, 1 skipped** ✓ (unchanged)
- `cd frontend && npm test -- --run`: **224 passed (15 files)** ✓ (unchanged)
- `cd frontend && npm run build`: clean ✓

## Session 36 Work (2026-05-06)

### Goal

Observed Play Phase 5.1 UI polish: align Memory Analytics table columns on branch `feature/observed-play-memory`.

### Summary

`AnalyticsGroupTable` now uses `w-full table-fixed` + `<colgroup>` with 8 fixed column widths (34%/7%/9%/10%/8%/11%/10%/11%) so all analytics sections share a consistent column grid. Named column headers for Examples and Review. Non-reviewable rows render a muted `—` placeholder in the Review column (instead of null). Label cells gain `title=` for truncation safety.

### Files changed

- `frontend/src/pages/ObservedPlay.tsx` — `AnalyticsGroupTable` column layout
- `frontend/src/pages/ObservedPlay.test.tsx` — 3 new column alignment tests (224 total)

### Validation (session 36)

- `cd backend && python3 -m pytest tests/ -x -q`: **949 passed, 1 skipped** ✓ (unchanged)
- `cd frontend && npm test -- --run`: **224 passed (15 files)** ✓
- `cd frontend && npm run build`: clean ✓
- `git diff --check`: clean ✓

## Session 35.1 Work (2026-05-06)

### Goal

Observed Play Memory Phase 5.1: Analytics Quality Triage Polish on branch `feature/observed-play-memory`.

### Summary

Made Memory Analytics actionable for quality triage: quality filter controls, Review action linking analytics rows to the existing manual card-resolution flow, examples modal filter label, and re-ingestion note.

### Backend changes

- `backend/app/observed_play/schemas.py`: Added `review_raw_name`, `review_status`, `can_review_resolution` fields to `MemoryAnalyticsGroup`.
- `backend/app/api/observed_play.py`:
  - `GET /memory-analytics`: Added `quality_filter` param (all/ambiguous/low_confidence/unresolved). Added quality filter logic to `_base_filter()`.
  - `_fetch_analytics_groups`: Added `is_card_group=False` param. When True, populates `review_raw_name`, `review_status`, `can_review_resolution` for groups with ambiguous/unresolved counts.
  - Card group calls (`top_actor_cards`, `top_target_cards`, `top_attachments`, `top_evolutions`, `top_knockouts`) now pass `is_card_group=True`.
  - `GET /memory-analytics/source-items`: Added `related_card_raw`, `min_confidence`, `card_name` filter params.

### Frontend changes

- `frontend/src/types/observedPlay.ts`: Added `review_raw_name`, `review_status`, `can_review_resolution` to `MemoryAnalyticsGroup`. Added `quality_filter` to `GetMemoryAnalyticsParams`. Added `related_card_raw`, `min_confidence`, `card_name` to `MemoryAnalyticsSourceItemsParams`.
- `frontend/src/api/observedPlay.ts`: Added `quality_filter` to `GetMemoryAnalyticsParams`.
- `frontend/src/pages/ObservedPlay.tsx`:
  - `AnalyticsGroupTable`: Added optional `onReview` prop. Review button appears when `can_review_resolution && (ambiguous_count + unresolved_count) > 0`.
  - `MemoryAnalyticsExamplesModal`: Added `filterLabel` prop, renders "Filter: {label}" below title.
  - `UnresolvedCardsSection`: Added `refreshRef` prop to expose `load` externally.
  - `MemoryAnalyticsSection`: Added `onRefreshLogs`, `onRefreshUnresolved` props. Added `qualityFilter` state with quality filter buttons. Added `unresolvedLookup` (fetched on mount), `reviewItem`, `examplesFilterLabel` state. `load` passes `quality_filter` when not 'all'. Opens `ResolutionRuleModal` for review rows. Added re-ingestion note. Added `onReview` to card group tables. Added `filterLabel` to examples modal. Sections for `top_target_cards`, `top_abilities`, `top_attachments`, `top_evolutions`, `top_knockouts` added (were missing from original render).
  - Main page: Added `unresolvedRefreshRef`. Passes `refreshRef`, `onRefreshLogs`, `onRefreshUnresolved` to `MemoryAnalyticsSection`; passes `refreshRef` to `UnresolvedCardsSection`.

### Tests Added

- `backend/tests/test_api/test_observed_play.py`: 9 new `TestMemoryAnalytics` tests — quality_filter variants (low_confidence, ambiguous, unresolved, all, invalid), source-items new filters (card_name, min_confidence, related_card_raw), review fields shape.
- `frontend/src/pages/ObservedPlay.test.tsx`: 5 new Phase 5.1 tests — quality filter controls render, ambiguous/low_confidence filter calls, Review button visibility, re-ingestion note, examples modal filter label.

### Validation (session 35.1)

- `cd backend && python3 -m pytest tests/ -x -q`: **949 passed, 1 skipped** ✓
- `cd frontend && npm test -- --run`: **221 passed (15 files)** ✓
- `cd frontend && npm run build`: clean ✓
- `git diff --check`: clean ✓

## Session 35 Work (2026-05-06)

### Goal

Observed Play Memory Phase 5: Read-Only Memory Analytics on branch `feature/observed-play-memory`.

### Summary

Added three read-only API endpoints and a `MemoryAnalyticsSection` frontend component to surface observed play memory analytics without integrating with Coach or AI Player.

### Backend changes

- `backend/app/observed_play/schemas.py`: Added `LOW_CONFIDENCE_THRESHOLD`, `MemorySummary`, `MemoryAnalyticsGroup`, and `MemoryAnalyticsResponse` schemas.
- `backend/app/api/observed_play.py`: Added `and_`, `case`, `distinct` imports. Added `LOW_CONFIDENCE_THRESHOLD`, `MemoryAnalyticsGroup`, `MemoryAnalyticsResponse`, `MemorySummary` schema imports. Three new read-only routes: `GET /memory-summary`, `GET /memory-analytics`, `GET /memory-analytics/source-items`. Helper `_fetch_analytics_groups` for reuse across aggregation queries.

### Frontend changes

- `frontend/src/types/observedPlay.ts`: Added `MemorySummary`, `MemoryAnalyticsGroup`, `MemoryAnalyticsResponse`, `MemoryAnalyticsSourceItemsParams` interfaces.
- `frontend/src/api/observedPlay.ts`: Added `getMemorySummary`, `getMemoryAnalytics`, `getMemoryAnalyticsSourceItems` API functions.
- `frontend/src/pages/ObservedPlay.tsx`: Added `useRef` import. Added `StatCard`, `AnalyticsGroupTable`, `MemoryAnalyticsExamplesModal`, and `MemoryAnalyticsSection` components. `MemoryAnalyticsSection` renders summary stat cards, memory type table, top action/actor/attack tables, quality flags table, and drill-down examples modal. Placed after `UnresolvedCardsSection`. `analyticsRefreshRef` wired to auto-refresh analytics after ingest success.

### Tests Added

- `backend/tests/test_api/test_observed_play.py`: 5 new `TestMemoryAnalytics` tests (empty summary, empty analytics, empty source items, filter params, read-only assertion).
- `frontend/src/pages/ObservedPlay.test.tsx`: 7 new Phase 5 tests (renders, empty state, summary cards, type counts, examples modal, refresh button, safety copy, dark mode classes).

### Validation (session 35)

- `cd backend && python3 -m pytest tests/ -x -q`: **940 passed, 1 skipped** ✓
- `cd frontend && npm test -- --run`: **215 passed (15 files)** ✓
- `cd frontend && npm run build`: clean ✓

## Session 31 Work (2026-05-06)

### Goal

Phase 3.2: Manual Card Resolution Rule UI. Wire the existing backend resolution
rule API into the Observed Play UI so users can review unresolved/ambiguous raw
card names, inspect candidates and source examples, create resolve/ignore rules,
and rerun card resolution for affected logs.

### Changes Applied

#### Backend (`backend/app/observed_play/schemas.py`)

- Added `SampleMentionItem` model with fields: `log_id`, `filename`, `event_id`,
  `turn_number`, `player_alias`, `mention_role`, `source_event_type`, `raw_line`.
- Extended `UnresolvedCardItem` with `sample_mentions: list[SampleMentionItem]`
  and `affected_log_ids: list[str]` (both default empty).

#### Backend (`backend/app/api/observed_play.py`)

- `get_unresolved_cards`: after main query, fetches sample mentions (≤5 per group)
  and affected log IDs (≤25 per group) via a single joined query; groups in Python.
- `create_resolution_rule`: added validation — empty `raw_name` → 422; unknown
  `action` → 422; `resolve` without target → 422; nonexistent `target_card_def_id`
  → 422; duplicate normalized name (any action) → 409 with clear message.
- Added `Card` import to support target card existence checks.

#### Frontend (`frontend/src/types/observedPlay.ts`)

- Added `SampleMentionItem` interface matching backend.
- Extended `UnresolvedCardItem` with optional `sample_mentions` and `affected_log_ids`.

#### Frontend (`frontend/src/pages/ObservedPlay.tsx`)

- New imports: `createResolutionRule`, `resolveCards`, `CardCandidateItem`,
  `ResolutionRuleCreate`, `SampleMentionItem`, `normalizeTcgdexImageUrl`.
- New `ResolutionRuleModal` component: shows raw name, status, candidate table
  (with thumbnail, name, set, number, card_def_id, reason, Select button), sample
  mentions table (role, event type, turn, player, source line), Ignore action.
  After successful rule creation, shows success message and re-resolved log count.
  Closing modal after success triggers refresh of unresolved section and raw logs.
- `UnresolvedCardsSection`: added `Action` column with `Review` button per row;
  clicking opens `ResolutionRuleModal`. Refresh triggered after rule creation.

### Tests Added

- **11 new backend tests** (`TestResolutionRules` × 7, `TestUnresolvedCardsPhase32` × 4)
  in `backend/tests/test_api/test_observed_play.py`:
  - resolve rule success, ignore rule success, resolve without target 422, invalid
    action 422, nonexistent target 422, duplicate 409, empty raw_name 422.
  - unresolved response includes candidates, sample_mentions, affected_log_ids, empty result.
- **10 new frontend tests** in `Phase 3.2 — Unresolved/Ambiguous Cards section` describe block:
  Review button renders, clicking Review opens modal, modal renders raw name + candidates,
  modal renders sample mentions, candidate select calls createResolutionRule, rerun called,
  success message shown, ignore calls createResolutionRule, API error shown, empty candidates.

### Scope Boundary

- Rules affect observed-play card resolution only.
- No Coach/AI integration, pgvector, Neo4j, simulator match_events, card_performance,
  deck-builder influence, or runtime recommendations.
- No automatic ingestion after rule creation.

### Validation (session 31)

- `cd backend && python3 -m pytest tests/ -x -q`: **935 passed, 1 skipped** ✓
- `cd frontend && npm test -- --run`: **198 passed (15 files)** ✓
- `cd frontend && npm run build`: **passed** ✓
- `docs/AUDIT_STATE.md` not touched ✓
- `frontend/node_modules` not committed ✓
- No real battle logs committed ✓

### Files Changed (session 31)

| File | Change |
|---|---|
| `backend/app/observed_play/schemas.py` | Added `SampleMentionItem`; extended `UnresolvedCardItem` |
| `backend/app/api/observed_play.py` | `get_unresolved_cards` sample/log expansion; `create_resolution_rule` validation/409 |
| `backend/tests/test_api/test_observed_play.py` | +11 tests (TestResolutionRules, TestUnresolvedCardsPhase32) |
| `frontend/src/types/observedPlay.ts` | `SampleMentionItem`; extended `UnresolvedCardItem` |
| `frontend/src/pages/ObservedPlay.tsx` | `ResolutionRuleModal`; enhanced `UnresolvedCardsSection` |
| `frontend/src/pages/ObservedPlay.test.tsx` | +10 Phase 3.2 tests |
| `docs/STATUS.md` | This file |
| `docs/CHANGELOG.md` | Phase 3.2 entry |
| `docs/proposals/OBSERVED_PLAY_MEMORY_IMPLEMENTATION_PLAN.md` | Phase 3.2 section |

## Session 32 Work (2026-05-06)

### Goal

Phase 3.2 hotfix: after creating a manual resolution rule and rerunning affected
log resolution, the Raw Logs table now refreshes immediately without a browser reload.

### Root Cause

`UnresolvedCardsSection` was self-contained with no external props.  `handleResolved`
only refreshed the local unresolved groups via `load()` but never called the parent
component's `fetchLogs`, so the Raw Logs table remained stale until page reload.

### Fix

- `UnresolvedCardsSection` now accepts an `onRefreshLogs?: () => void` prop.
- `handleResolved` calls `onRefreshLogs?.()` after `load()`.
- Parent component passes `() => fetchLogs(logPage)` as `onRefreshLogs`.
- No backend changes; no API changes; no DB migration.

### Tests Added (session 32)

- **+3 new frontend tests** in `Phase 3.2 — Unresolved/Ambiguous Cards section`:
  - After resolve rule + close modal → `listObservedPlayLogs` is called again.
  - After ignore rule + close modal → `listObservedPlayLogs` is called again.
  - Raw Logs table card count badges update from refreshed data (7✓/3? → 10✓).

### Validation (session 32)

- `cd backend && python3 -m pytest tests/ -x -q`: **935 passed, 1 skipped** ✓
- `cd frontend && npm test -- --run`: **200 passed (15 files)** ✓
- `cd frontend && npm run build`: **passed** ✓
- `docs/AUDIT_STATE.md` not touched ✓
- `frontend/node_modules` not committed ✓
- No real battle logs committed ✓

### Files Changed (session 32)

| File | Change |
|---|---|
| `frontend/src/pages/ObservedPlay.tsx` | `UnresolvedCardsSection` accepts `onRefreshLogs` prop; `handleResolved` calls it; parent passes `fetchLogs` |
| `frontend/src/pages/ObservedPlay.test.tsx` | +3 refresh tests |
| `docs/STATUS.md` | This file |
| `docs/CHANGELOG.md` | Hotfix entry |

## Session 33 Work (2026-05-06)

### Goal

Dark mode styling hotfix for `ObservedPlay.tsx`. The page showed white panels and
low-contrast text in dark mode because the file had zero `dark:` Tailwind classes.

### Root Cause

`ObservedPlay.tsx` was written without any `dark:` Tailwind variants. All other pages
(History, Memory, Coverage) had consistent dark mode support; Observed Play did not.

### Fix

Added 177 `dark:` Tailwind classes across all 13 components/sections in `ObservedPlay.tsx`:
StatusChip, RawLogModal, ConfidenceBadge, ParserDiagnosticsPanel, EventsModal,
CardResolutionBadges, ResolutionStatusBadge (palette), CardMentionsModal,
ResolutionRuleModal, UnresolvedCardsSection, MemoryPreviewModal, MemoryItemsModal,
and all main page sections (phase banner, upload, import report, import batches,
raw logs). Follows exact dark mode patterns from History.tsx and Memory.tsx
(`dark:bg-slate-900`, `dark:border-slate-700`, `dark:text-slate-400`, etc.).
Unresolved/ambiguous panel uses `dark:bg-amber-950/50 dark:border-amber-800`.

### Tests Added (session 33)

- **+6 new frontend tests** in `describe('Dark mode styling')`:
  - Raw Logs panel has `dark:bg-slate-900`
  - Import History/Batches panel has `dark:bg-slate-900`
  - Unresolved section has amber dark classes
  - RawLogModal has `dark:bg-slate-900`
  - MemoryPreviewModal has `dark:bg-slate-900`
  - ResolutionRuleModal has `dark:bg-slate-900`

### Validation (session 33)

- `cd backend && python3 -m pytest tests/ -x -q`: **935 passed, 1 skipped** ✓
- `cd frontend && npm test -- --run`: **206 passed (15 files)** ✓
- `cd frontend && npm run build`: **passed** ✓
- `docs/AUDIT_STATE.md` not touched ✓
- `frontend/node_modules` not committed ✓
- No real battle logs committed ✓

### Files Changed (session 33)

| File | Change |
|---|---|
| `frontend/src/pages/ObservedPlay.tsx` | +177 `dark:` Tailwind classes across all components |
| `frontend/src/pages/ObservedPlay.test.tsx` | +6 dark mode styling tests |
| `docs/STATUS.md` | This file |
| `docs/CHANGELOG.md` | Dark mode entry |

## Session 34 Work (2026-05-06)

### Goal

Stabilization sweep of Observed Play Memory feature branch before Phase 5.
Verified migrations, backend/frontend suites, Docker compose, API smoke, import
smoke, dark-mode behavior, and memory item review. Fixed one UI bug found during sweep.

### Bug Fixed

**"Force ingest" button present in MemoryPreviewModal when ineligible.**

The Phase 4.1 prompt explicitly prohibited a force-ingest UI ("Do not add a new
force-ingest UI in this pass"). The implementation agent added it anyway. Removed
the button (lines 1118–1126 in `ObservedPlay.tsx`). When a log is ineligible, only
the Cancel button is shown alongside the blocker/reason details. The backend force
path (`force=True, allow_unresolved=True`) remains available for future admin use;
only the UI exposure is removed.

### Checks Passed

| Check | Result |
|---|---|
| `git status --short` | clean ✓ |
| `git diff --check` | no whitespace errors ✓ |
| `alembic current` / `alembic heads` | `g3h4i5j6k7l8 (head)` ✓ |
| `docs/AUDIT_STATE.md` not touched | ✓ |
| `frontend/node_modules` not committed (pre-existing tracked files from Phase 8) | noted |
| No real battle logs committed | ✓ |
| Backend import smoke | all observed-play and engine imports ok ✓ |
| Docker compose up | all services healthy ✓ |
| `GET /api/observed-play/logs` | 45 logs, 200 OK ✓ |
| `GET /api/observed-play/unresolved-cards` | 50 groups, 200 OK ✓ |
| `POST /api/observed-play/logs/{id}/memory-preview` | eligible/ineligible responses correct ✓ |
| `GET /api/observed-play/logs/{id}/events` | 375 events ✓ |
| `GET /api/observed-play/logs/{id}/card-mentions` | 205 mentions ✓ |
| `POST /api/observed-play/logs/{id}/ingest-memory` | 158 items written ✓ |
| `GET /api/observed-play/logs/{id}/memory-items` | 158 items returned ✓ |
| Memory item quality | actor/target plausible, confidences correct ✓ |
| No Coach/AI/Neo4j/pgvector/simulator integration found | ✓ |

### Tests Added (session 34)

- **+1 test**: `MemoryPreviewModal does not show "Force ingest" when ineligible`
  — asserts neither "Force ingest" nor "Ingest memory" appears when preview is ineligible.
  207 frontend tests total (up from 206).

### Validation (session 34)

- `cd backend && python3 -m pytest tests/ -x -q`: **935 passed, 1 skipped** ✓
- `cd frontend && npm test -- --run`: **207 passed (15 files)** ✓
- `cd frontend && npm run build`: **passed** ✓

### Files Changed (session 34)

| File | Change |
|---|---|
| `frontend/src/pages/ObservedPlay.tsx` | Removed "Force ingest" button (7 lines) |
| `frontend/src/pages/ObservedPlay.test.tsx` | +1 force-ingest-absent test |
| `docs/STATUS.md` | This file |
| `docs/CHANGELOG.md` | Stabilization entry |



### Goal

Phase 2.2: Polish parser v1 after Phase 2.1. Fix dash-prefixed child-line player
attribution, expose parser diagnostics in the API and UI.

### Root Cause Fixed

Dash-prefixed child lines like `"- gehejo shuffled their deck."` were matched
against patterns with `stripped` (the raw whitespace-stripped value). The lazy
regex `^(?P<player>.+?) shuffled their deck` would capture `player = "- gehejo"`.
`get_alias("- gehejo")` registered it as a new third player → `unknown` alias.

### Fix Applied

1. **`_strip_dash_prefix(line)`** helper added to `parser.py` — strips leading
   `"- "` from a line for pattern matching only; `raw_line` still records the
   original line with the dash.

2. **`match_line`** computed after `stripped = line.strip()` at the top of the
   parser's main `while` loop. All ~44 pattern `.match()` and `.search()` calls
   now use `match_line`. The bottom `RE_DASH_LINE.match(stripped)` fallback still
   uses `stripped` so unrecognized dash lines are silently skipped.

3. **`patterns.py`** — removed `^-\s*` prefix from `RE_MULLIGAN_CARDS_LABEL`,
   `RE_DAMAGE_BREAKDOWN_LABEL`, and `RE_BENCH_FROM_DECK_HIDDEN`. These now rely
   on `match_line` normalization.

### Diagnostics API Exposure

4. **`schemas.py`** — new `ParserDiagnostics` Pydantic model with `unknown_count`,
   `unknown_ratio`, `low_confidence_count`, `event_type_counts`, `top_unknown_raw_lines`.
   Added `parser_diagnostics: ParserDiagnostics | None = None` to `LogSummary` and
   `ReparseSummary`.

5. **`api/observed_play.py`** — `_log_to_summary` now extracts `parser_diagnostics`
   from `metadata_json` and returns it in the log list response. Reparse endpoint
   includes `parser_diagnostics` in its `ReparseSummary` response.

### Diagnostics UI

6. **`frontend/src/types/observedPlay.ts`** — `ParserDiagnostics` interface added;
   `parser_diagnostics?: ParserDiagnostics | null` added to `ObservedPlayLog`.

7. **`frontend/src/pages/ObservedPlay.tsx`** — `ParserDiagnosticsPanel` component
   shows unknown count/ratio, low-confidence count, and top unknown lines. Shown
   inside `EventsModal` above the events table when diagnostics are present.
   Diagnostics state is initialized from the log list and updated after reparse.

### Tests Added

- Parser tests: **14 new tests** in `TestDashChildLineAttribution` class covering
  dash-prefixed shuffle, draw, hidden draw, evolution, bench-from-deck with player
  alias assertions; raw_line preservation; non-dash regression; Dwebble Ascension
  preserved; targeted no-damage attack stays `attack_used`; real-log fixture dash
  lines check; diagnostics still present after changes. (87 total, up from 73.)
- API tests: **3 new tests** in `TestParserDiagnosticsInApi` — log list includes
  `parser_diagnostics` when present, null for old logs, reparse response includes
  `parser_diagnostics`. (17 total in class, up from 14.)
- Frontend tests: **5 new tests** — diagnostics panel shown with correct values,
  top unknown lines rendered, modal works without diagnostics, reparse updates
  diagnostics display. (163 total, up from 159.)

### Validation (session 26)

- `cd backend && python3 -m pytest tests/ -x -q`: **747 passed, 1 skipped** ✓
- `cd frontend && npm test -- --run`: **163 passed (15 files)** ✓
- `cd frontend && npm run build`: ✓ built in ~4s
- `docs/AUDIT_STATE.md`: not modified ✓
- `frontend/node_modules`: not committed ✓
- No real battle-log corpus committed ✓
- No card resolution / Coach / AI / Neo4j / pgvector / memory ingestion added ✓

### Parser Limitations Remaining

Known patterns still producing `unknown` events in real logs:
- PTCGL text art separator lines
- Some conditional ability announcement formats
- Deck search confirmations without explicit card names
- "Looked at top N cards" observation lines
These are candidates for Phase 2.3 if needed before Phase 3.

## Session 29 Work (2026-05-06)

### Goal

Phase 3.1: Card Mention Cleanup and False-Unresolved Reduction. Strip safe
zone/location suffixes from extracted mention names, improve mention role
assignments for additional event types, and add `them`/numeric-card filtering so
false unresolved counts drop without any silent ambiguous resolution.

### Root Cause Fixed

Mention extraction stored raw names like `"Dreepy in the Active Spot"` because the
`RE_ATTACK` pattern captures `(?P<target_card>.+?)` including any trailing zone
phrase. `_resolve_one()` would then try to look up `"Dreepy in the Active Spot"` in
the card DB, which never matched → `unresolved`. Similarly, `"them"` passed
`_is_meaningful()` and could be extracted as a spurious mention.

### Changes Applied

#### `backend/app/observed_play/card_mentions.py`

1. **`_ZONE_SUFFIXES`** — 9 zone phrase variants to strip from mention names:
   `in the Active Spot`, `to the Active Spot`, `on the Bench`, `to the Bench`,
   `in the Bench`, `on your Bench`, `on their Bench`, `from the Active Spot`,
   `from the Bench`.

2. **`clean_extracted_card_name(raw)`** — strips the first matching zone suffix
   (case-insensitive) and returns the trimmed card name. Does not mutate `raw_line`.

3. **`_add()`** — calls `clean_extracted_card_name()` before `_is_meaningful()`.

4. **`_IGNORED_NORMALIZED`** extended with `"cards"` and `"them"`.

5. **`_RE_NUMERIC_CARDS`** — `re.compile(r"^\d+\s+cards?$")` added to
   `_is_meaningful()` so strings like `"2 cards"` are never extracted.

6. **Dispatch branches added**:
   - `ET_DRAW → drawn_card` (known draw events extract card name).
   - `ET_SWITCH_ACTIVE → actor_card` (switch/retreat events extract promoted Pokémon).
   - `ET_OPENING_HAND_DRAW_KNOWN` branch no longer incorrectly bundled with `ET_PLAY_TO_BENCH`.

7. **Payload card loop** — cleaned names applied for opening-hand and mulligan
   card lists.

### Tests Added

**27 new tests** across 3 new classes in `test_card_mentions.py`:

- `TestCleanExtractedCardName` (13 tests) — zone strip, multi-word names, no-op
  on clean names, all 9 suffix variants.
- `TestZoneSuffixCleaningInExtraction` (4 tests) — attack event with suffixed
  target produces clean mention name; name without suffix unchanged; attack event
  with no zone text unchanged.
- `TestImprovedMentionRoles` (11 tests) — `ET_DRAW → drawn_card`;
  `ET_SWITCH_ACTIVE → actor_card`; `ET_DRAW_HIDDEN` produces no mention;
  `opening_hand_draw_known` cards → `revealed_card`; `mulligan_cards_revealed` →
  `revealed_card`; `"them"`, `"a card"`, `"2 cards"` not extracted.

(64 total card mention tests, up from 37.)

### Validation (session 29)

- `cd backend && python3 -m pytest tests/test_observed_play/test_card_mentions.py -q`: **64 passed** ✓
- `cd backend && python3 -m pytest tests/ -x -q`: **831 passed, 1 skipped** ✓
- `cd frontend && npm test -- --run`: **173 passed (15 files)** ✓
- `cd frontend && npm run build`: ✓ built in ~4s
- `docs/AUDIT_STATE.md`: not modified ✓
- `frontend/node_modules`: not committed ✓
- No real battle-log corpus committed ✓
- No Coach / AI / Neo4j / pgvector / memory ingestion added ✓

### Expected Manual Validation

After reparsing real logs the suffix raw names `"Dreepy in the Active Spot"`,
`"Munkidori on the Bench"`, `"Dunsparce on the Bench"`, and `"Drakloak on the Bench"`
should no longer appear as unresolved card mentions. Cleaned names will resolve to
`ambiguous` (multiple prints) or `resolved` (unique print). Ambiguous same-name
cards remain ambiguous.

### Remaining Limitations

- Resolution rules UI (create-rule flow) not yet wired in frontend.
- No memory ingestion (Phase 4+).
- No Coach or AI Player integration (Phase 6/8).

## Session 28 Work (2026-05-06)

### Goal

Phase 3: Card Mention Extraction and Conservative Card Resolution. Extract
structured card mentions from parsed events, resolve them against the card DB,
report resolution status per log, and expose review UI for unresolved/ambiguous
cards.

### New DB Tables

- `observed_card_mentions` — one row per card mention extracted from a parsed
  event. Columns: `id`, `observed_play_log_id`, `observed_play_event_id`,
  `mention_index`, `mention_role`, `raw_name`, `normalized_name`,
  `resolved_card_def_id` (FK → `cards.tcgdex_id`), `resolved_card_name`,
  `resolution_status`, `resolution_confidence`, `resolution_method`,
  `candidate_count`, `candidates_json`, `source_event_type`, `source_field`,
  `source_payload_path`, `resolver_version`.
- `observed_card_resolution_rules` — manual ignore/override rules. Columns:
  `id`, `normalized_name`, `rule_type` (`ignore`/`resolve`), `resolved_card_def_id`,
  `notes`, `created_at`, `updated_at`.
- Alembic migration `f2a3b4c5d6e7` applied. DB now at `f2a3b4c5d6e7 (head)`.

### New Columns on `observed_play_logs`

- `card_mention_count INT` — total mentions extracted.
- `card_resolution_status TEXT` — `null` / `"not_resolved"` / `"resolved"` / `"has_unresolved"` / `"has_ambiguous"`.
- `resolver_version TEXT` — version of resolver used (`"1.0"`).

### New Backend Modules

- `backend/app/observed_play/card_mentions.py` — `normalize_card_name()`,
  `_is_meaningful()`, `extract_mentions_from_event()` with per-event-type dispatch
  and dedup by `(role, normalized_name, source_field)`.
- `backend/app/observed_play/card_resolution.py` — `_resolve_one()` (pure, no DB),
  `extract_and_resolve_mentions_for_log(db, log_id)` (async, idempotent delete+insert),
  energy alias table (11 types, bidirectional), `CardResolutionSummary` dataclass,
  log-level status derivation.

### Resolution Logic

1. Manual ignore/resolve rules (from `observed_card_resolution_rules`).
2. Exact normalized name match — unique → `resolved` / 0.98; multiple → `ambiguous` / 0.60.
3. Basic energy alias match — unique → `resolved` / 0.95.
4. Fallback → `unresolved` / 0.0.

Hidden card names (`"a card"`, `""`, etc.) excluded via `_IGNORED_NORMALIZED` frozenset.
Attack/ability names not extracted as mentions.

### New API Routes

- `GET /api/observed-play/logs/{id}/card-mentions` — paginated list of mentions, filterable by status.
- `POST /api/observed-play/logs/{id}/resolve-cards` — trigger resolution for a log; returns `CardResolutionSummaryResponse`.
- `GET /api/observed-play/unresolved-cards` — aggregate list of unresolved/ambiguous raw names across all logs.
- `POST /api/observed-play/resolution-rules` — create a manual ignore/resolve rule.

### Updated API Routes

- `GET /api/observed-play/logs` and `GET /api/observed-play/logs/{id}` — now return `card_mention_count`, `resolved_card_count`, `ambiguous_card_count`, `unresolved_card_count`, `card_resolution_status` in `LogSummary`.
- `POST /api/observed-play/logs/{id}/reparse` — now runs extraction+resolution after parse; returns the 5 new resolution fields in `ReparseSummary`.

### Frontend Changes

- `ObservedPlayLog` type: 5 optional resolution fields added.
- New types: `CardMentionItem`, `CardMentionListResponse`, `CardResolutionSummaryResponse`, `UnresolvedCardItem`, `UnresolvedCardsResponse`, `ResolutionRuleCreate`, `ResolutionRuleResponse`, `CardCandidateItem`.
- New API functions: `getCardMentions()`, `resolveCards()`, `getUnresolvedCards()`, `createResolutionRule()`.
- `ObservedPlay.tsx`: `CardResolutionBadges` — resolved/ambiguous/unresolved pill badges in log table "Cards" column. `CardMentionsModal` — dialog showing paginated mentions with status filter, raw name, resolved name, method, confidence. `UnresolvedCardsSection` — section above import history listing unresolved/ambiguous card names across all logs. Phase banner updated to "Phase 3 active".

### Tests Added

- **37 new backend tests** in `backend/tests/test_observed_play/test_card_mentions.py` covering extraction, resolution, dedup, energy alias, manual rules, edge cases. (All passing.)
- **~12 new frontend tests** in `Phase 3 card resolution` describe block: badges render, dash for no mentions, View cards button presence, modal open/close, empty modal state, unresolved section shows/hides, phase banner.

### Validation (session 28)

- `cd backend && python3 -m pytest tests/ -x -q`: **804 passed, 1 skipped** ✓
- `cd frontend && npm test -- --run`: **173 passed (15 files)** ✓
- `cd frontend && npm run build`: ✓ built in ~4s
- `docs/AUDIT_STATE.md`: not modified ✓
- `frontend/node_modules`: not committed ✓
- No real battle-log corpus committed ✓
- No Coach / AI / Neo4j / pgvector / memory ingestion added ✓

### Phase 3 Limitations / Next Steps

- Resolution rules UI (ignore/resolve buttons) is backend-only; frontend create-rule flow not yet wired.
- No memory ingestion (Phase 4+).
- No Coach or AI Player integration (Phase 6/8).

## Session 27 Work (2026-05-06)

### Goal

Phase 2.3: Address the top remaining unknown patterns from the manually validated
real log. After Phase 2.2 the log had 14 unknowns (4.8%). The top 5 patterns were:
direct retreat-to-bench, card/effect activation, discard-from-Pokémon, and
card-added-to-hand.

### New Event Types

- `ET_CARD_EFFECT_ACTIVATED` (`"card_effect_activated"`) — lines like `"Spiky Energy was activated."`
- `ET_DISCARD_FROM_POKEMON` (`"discard_from_pokemon"`) — lines like `"Basic Fighting Energy was discarded from DAVIDELIRIUM's Solrock."`
- `ET_CARD_ADDED_TO_HAND` (`"card_added_to_hand"`) — lines like `"Growing Grass Energy was added to gehejo's hand."` and hidden `"A card was added to PLAYER's hand."`

### New Patterns

- `RE_RETREAT_DIRECT` — `PLAYER retreated CARD to the Bench.` (direct form, before `RE_RETREAT`)
- `RE_DISCARD_FROM_POKEMON` — passive discard from Pokémon with player/target extraction (after `RE_DISCARD`)
- `RE_CARD_EFFECT_ACTIVATED` — `CARD was activated.` (late in parser before bullet-skip)
- `RE_CARD_ADDED_TO_HAND_KNOWN` — named-card form added to hand (after `RE_PRIZE_CARD_ADDED`)

Pattern ordering preserved: prize-card-added before named-card-added-to-hand so "A card was added to PLAYER's hand" still emits `prize_card_added_to_hand`.

Supports both straight `'` and curly `\u2019` apostrophes in possessive patterns.

### Diagnostics Improvement

- `top_unknown_raw_lines` de-duplicated using a seen-set; same list shape, no frontend changes.

### Tests Added

- **20 new tests** in `TestPhase23TopUnknowns` class covering all 4 new patterns,
  multi-word Pokémon names, curly apostrophe, hidden-card variant, Phase 2.2 regression
  (dash-prefix, Dwebble Ascension, targeted attack), and unknown-count reduction.
  (107 total parser tests, up from 87.)

### Validation (session 27)

- `cd backend && python3 -m pytest tests/test_observed_play/ -q`: **107 passed** ✓
- `cd backend && python3 -m pytest tests/ -x -q`: **767 passed, 1 skipped** ✓
- `cd frontend && npm test -- --run`: **163 passed (15 files)** ✓
- `cd frontend && npm run build`: ✓ built in ~4.5s
- `docs/AUDIT_STATE.md`: not modified ✓
- `frontend/node_modules`: not committed ✓
- No real battle-log corpus committed ✓
- No card resolution / Coach / AI / Neo4j / pgvector / memory ingestion added ✓

### Manual Real-Log Metrics (before/after Phase 2.3)

Before:  events=292, confidence=84%, unknown=14 (4.8%), low_confidence=14
Expected after: events≈292, confidence≥84%, unknown materially lower

The five top unknown lines targeted:
- `DAVIDELIRIUM retreated Hariyama to the Bench.` → `retreat` ✓
- `DAVIDELIRIUM retreated Mega Lucario ex to the Bench.` → `retreat` ✓
- `Spiky Energy was activated.` → `card_effect_activated` ✓
- `Basic Fighting Energy was discarded from DAVIDELIRIUM's Solrock.` → `discard_from_pokemon` ✓
- `Growing Grass Energy was added to gehejo's hand.` → `card_added_to_hand` ✓

### Parser Limitations Remaining

- PTCGL text art separator lines
- Some conditional ability announcement formats
- Deck search confirmations without explicit card names
- "Looked at top N cards" observation lines

## Session 26 Work (2026-05-06)


### Goal

Phase 2.1: Harden parser v1 against real PTCGL log patterns. Target: reduce
unknown/misclassified event ratio, improve confidence from 56% baseline.

### Patterns Fixed

9 specific real-log misclassification bugs resolved:

1. **Generic trainer play** — `PLAYER played CARD.` without `(Item)`/`(Supporter)` tag
   now parses as new `play_trainer` event type (not `unknown`).
2. **Hidden draw** — `PLAYER drew a card.` and `PLAYER drew N cards.` now correctly
   parse as `draw_hidden` (not misclassified as known draw). Hidden draws check BEFORE
   known draw pattern. `draw_hidden` now sets `amount=1` for singular form.
3. **Non-energy attachment** — `PLAYER attached TOOL to TARGET.` now parses as new
   `attach_card` event type when card name doesn't contain "Energy". Zone extracted
   from target string ("in the Active Spot" → `active`, "on the Bench" → `bench`).
   Energy attachments still correctly parse as `attach_energy`.
4. **Direct evolution** — `PLAYER evolved FROM to TO [in ZONE].` (PTCGL direct format)
   now parses as `evolve` with zone extraction. Possessive format still works.
5. **Ability used** — `PLAYER's CARD used ABILITY.` (no target) now parses as
   `ability_used`. Both straight (`'`) and curly (`'`) apostrophes supported.
6. **No-damage attack** — `PLAYER's CARD used ATTACK on TARGET.` (no "for N damage")
   now parses as `attack_used` with `damage=None`.
7. **Singular prize** — `PLAYER took a Prize card.` now parses as `prize_taken`
   with `prize_count_delta=1`. Checked before numeric pattern.
8. **Hidden bench from deck** — `- PLAYER drew N cards and played them to the Bench.`
   now parses as new `play_to_bench_hidden` event. `card_name_raw` is not set to `"them"`.
   Checked before `play_to_bench` pattern.
9. **Active switch/promotion** — `PLAYER's CARD is now in the Active Spot.` now
   parses as `switch_active` with `zone="active"`.

### New Event Types

- `play_trainer` — generic trainer play without explicit subtype (confidence 0.85)
- `attach_card` — non-energy card attachment to a Pokémon (confidence 0.87)
- `play_to_bench_hidden` — hidden aggregate bench placement from deck (confidence 0.82)

### Parser Diagnostics

Parser now computes and stores diagnostics in `metadata_json["parser_diagnostics"]`:

```json
{
  "unknown_count": N,
  "unknown_ratio": 0.14,
  "low_confidence_count": K,
  "event_type_counts": {"turn_start": 20, "draw_hidden": 14, ...},
  "top_unknown_raw_lines": ["...", ...]
}
```

Diagnostics are computed after each parse and reparse. Exposed via existing
`LogDetail.metadata_json` field — no schema/migration changes required.

### Tests Added

- Parser tests: **42 new tests** across 9 bug classes + diagnostics + real-log fixture
  (73 total up from 31).
- API tests: **2 new tests** for diagnostics in reparse response (27 total up from 25).
- New test fixture: `tests/fixtures/observed_play/real_log_sample.md` with all 9
  bug-example patterns.
- Updated `basic_setup_and_turns.md`: first draw changed to named-card draw for
  `test_draw_events_exist` to remain valid after draw-ordering fix.

### No Phase 3 Work

No card resolution, `observed_card_mentions`, unresolved-card UI, Coach/Player
integration, pgvector, Neo4j, simulator `match_events`, card performance writes,
or memory ingestion was added.

### Validation (session 25)

- `cd backend && python3 -m pytest tests/ -x -q`: **730 passed, 1 skipped** ✓
- `cd frontend && npm test -- --run`: **159 passed (15 files)** ✓
- `docs/AUDIT_STATE.md`: not modified ✓
- `frontend/node_modules`: not committed ✓
- No real battle-log corpus committed ✓

### Goal

Stabilize Phase 2 after a 500 error during manual upload validation.

### Root Cause

The Phase 2 Alembic migration (`e1f2a3b4c5d6`) was not applied to the running
PostgreSQL instance after the backend image was rebuilt. The code tried to INSERT
into `observed_play_events` which didn't exist yet, causing:

```
asyncpg.exceptions.UndefinedTableError: relation "observed_play_events" does not exist
```

The DB was at migration `b9f8e1d2c3a4` (Phase 1 head); `e1f2a3b4c5d6` was the new head.

### Fix Applied

1. **Migration applied** — `docker compose exec backend alembic upgrade head` promoted DB
   from `b9f8e1d2c3a4` → `e1f2a3b4c5d6`. The migration is idempotent. Steps added to
   docs for post-rebuild workflow.

2. **Duplicate result completeness** (`backend/app/observed_play/importer.py`):
   Duplicate branch now includes `event_count` and `confidence_score` from the existing
   log. These have schema defaults (0, None) so no 500 occurred, but the response was
   semantically incomplete.

3. **Frontend error detail** (`frontend/src/pages/ObservedPlay.tsx`):
   Upload error handler now extracts `error.response?.data?.detail` from Axios error
   before falling back to `error.message`. Users now see the specific backend failure
   reason instead of "Request failed with status code 500".

4. **EventsModal empty state** (`frontend/src/pages/ObservedPlay.tsx`):
   When a log has zero events (`data.total === 0`), the modal now shows
   "No parsed events found. Try Reparse." with an inline Reparse button,
   instead of an empty table. Pre-Phase-2 `raw_archived` logs can be reparsed directly.

5. **Phase banner** (`frontend/src/pages/ObservedPlay.tsx`):
   Updated from "Raw archive only. Parser and memory ingestion are not active yet."
   to "Phase 2 active — parser running. Memory ingestion not yet active."

### Tests Added

- Backend (`test_api/test_observed_play.py`): `test_returns_empty_list_for_raw_archived_log`
  (200+empty for Phase-1 log), `test_duplicate_response_includes_event_count_and_confidence`
  (duplicate result carries event_count/confidence_score). +2 tests.
- Frontend (`ObservedPlay.test.tsx`): upload 500 shows backend detail, duplicate with
  null event_count renders, empty event viewer shows no-events message + reparse button,
  happy-path event viewer shows events table, fetch failure shows error. +5 tests.

### Validation (session 24)

- `cd backend && python3 -m pytest tests/ -x -q`: **688 passed, 1 skipped** ✓
- `cd frontend && npm test -- --run`: **159 passed (15 files)** ✓
- `cd frontend && npm run build`: clean ✓
- `docker compose exec backend alembic current`: `e1f2a3b4c5d6 (head)` ✓
- `docs/AUDIT_STATE.md`: not touched ✓
- `frontend/node_modules`: not committed ✓
- No real battle logs committed ✓
- No card resolution/Coach/AI/memory ingestion added ✓

## Session 23 Work (2026-05-05)

### Goal

Observed Play Memory Phase 2: PTCGL battle log parser v1, structured event storage,
confidence scoring, new events/reparse API endpoints, and frontend event viewer.

### Completed

1. **`observed_play_events` table** (`backend/alembic/versions/e1f2a3b4c5d6_observed_play_events.py`): New migration adding the `observed_play_events` table with 30+ columns (event_type, turn_number, phase, player_raw/alias, card_name_raw, damage, energy_type, prize_count_delta, confidence_score, parser_version, etc.), two indexes (`ix_ope_log_id_event_index`, `ix_ope_log_id_event_type`), and FK to `observed_play_logs`.

2. **Parser modules** (4 new files):
   - `backend/app/observed_play/constants.py`: All event type constants (`ET_TURN_START`, `ET_DRAW`, `ET_ATTACK_USED`, etc.), phase constants, `PARSER_VERSION = "1.0"`.
   - `backend/app/observed_play/patterns.py`: Compiled regex patterns for all PTCGL log line types (turn start, draw, attach energy, play trainer, evolve, attack, KO, prize, mulligan, game end, etc.). Fixed turn-number regex to accept `"Alice's Turn 1"` format.
   - `backend/app/observed_play/confidence.py`: Deterministic per-event and log-level confidence scoring functions.
   - `backend/app/observed_play/parser.py`: Complete `parse_log()` implementation with `ParsedObservedLog`/`ParsedObservedEvent` dataclasses. Parser never throws; wraps inner parser in try/except. Player aliasing (first seen → `player_1`/`player_2`). Phase transitions (setup → turn → combat → game_end).

3. **Importer Phase 2 block** (`backend/app/observed_play/importer.py`): After `db.flush()`, parse log content and insert `ObservedPlayEvent` rows. `parse_status` transitions to `"parsed"` / `"parsed_with_warnings"` / `"parse_failed"`. Parse failures do not prevent archive writes or lose `raw_content`. Return dict now includes `event_count` and `confidence_score`. `batch.summary_json` now includes `total_events_parsed` and `average_confidence`.

4. **Schemas** (`backend/app/observed_play/schemas.py`): Added `EventSummary`, `PaginatedEvents`, `ReparseSummary` classes; `LogImportResult` gets `event_count`/`confidence_score`; `LogSummary` gets `parser_version`, `event_count`, `confidence_score`, `winner_raw`, `win_condition`.

5. **API endpoints** (`backend/app/api/observed_play.py`): Added `GET /logs/{log_id}/events` (paginated, filterable by event_type/turn_number/min_confidence) and `POST /logs/{log_id}/reparse` (deletes existing events, re-runs parser, updates log fields). `_log_to_summary` updated with new fields.

6. **Frontend** (`frontend/src/`):
   - `types/observedPlay.ts`: Added `EventSummary`, `PaginatedEvents`; updated `ObservedPlayLog` and `LogImportResult` with new fields.
   - `api/observedPlay.ts`: Added `getObservedPlayLogEvents`, `reparseObservedPlayLog`, `ListEventsParams`.
   - `pages/ObservedPlay.tsx`: Added `ConfidenceBadge` component, `EventsModal` component (paginated event table with reparse button), updated raw logs table with Events/Confidence columns and "View events" button alongside "View raw".

7. **Tests**:
   - `backend/tests/test_observed_play/test_parser.py` (NEW): 33 tests across smoke, parser version, fixture golden tests, confidence scoring, and edge cases.
   - `backend/tests/test_observed_play/test_importer.py`: 3 tests updated for new `parse_status` values.
   - `backend/tests/test_api/test_observed_play.py`: `_make_log_model` updated; `TestGetLogEvents` and `TestReparseLog` classes added.
   - `frontend/src/pages/ObservedPlay.test.tsx`: `getObservedPlayLogEvents` and `reparseObservedPlayLog` added to `vi.mock`; `sampleLog` updated with new fields; `beforeEach` defaults for new mocks.

8. **Fixture files** (`backend/tests/fixtures/observed_play/`): `basic_setup_and_turns.md` and `mulligan_attack_ko_prize.md` added (synthetic, match regex patterns, contain no real battle logs).

### Validation (session 23)

- `docker compose run --rm backend pytest tests/ -q --tb=short`: **682 passed, 5 skipped** ✓
- `cd frontend && npm test -- --run`: **154 passed (15 files)** ✓
- `cd frontend && npm run build`: clean ✓
- `docs/AUDIT_STATE.md`: not touched ✓
- `frontend/node_modules`: not committed ✓
- No real battle logs committed ✓
- Parser never throws; parse failures do not lose raw_content ✓

## Session 22 Work (2026-05-05)

### Goal

Fix Phase 1 raw Observed Play import so real PTCGL `.md` logs with spaces, bullets (`•`),
and curly punctuation (`'`) import successfully. Improve file-level error visibility in
the import report so users can see why an upload failed without checking logs.

### Root Cause

Docker named volumes are created by the Docker daemon as `root`-owned. The backend
container runs as `app` (uid=999). The volume was mounted after `USER app`, so the
app had write access to image layers but not to the named volume. Writes to
`/data/ptcgl_logs/archive/` failed with `PermissionError: [Errno 13] Permission denied`.

The UI did not display the error reason — the `error` field was returned by the API
but the import report table had no Error column.

### Fixes Applied

1. **Docker ownership** (`backend/Dockerfile`): Added `RUN mkdir -p /data/ptcgl_logs && chown -R app:app /data/ptcgl_logs` before `USER app`. Docker copies image layer ownership into a named volume on its first creation. For existing volumes, manual `chown -R app:app /data/ptcgl_logs` was applied at runtime.

2. **UTF-8 BOM decode** (`backend/app/observed_play/importer.py`): Added fallback decode via `utf-8-sig` for Windows PTCGL exports with BOM. Failed decode returns `"File is not valid UTF-8 or UTF-8 BOM text."`.

3. **`parse_status` correctness** (`backend/app/observed_play/importer.py`): Infrastructure failures (too large, decode error, archive write error) now use `"not_applicable"`, `"decode_failed"`, `"archive_failed"` — never `"failed"`. Phase 1 has no parser; `"failed"` was semantically wrong for infrastructure errors.

4. **`batch.errors_json` population** (`backend/app/observed_play/importer.py`): Per-file errors from failed results are now collected into `batch.errors_json` after `run_import` completes.

5. **Startup warning** (`backend/app/main.py`): Added `_warn_if_log_root_not_writable()` called from `create_app()` — logs a WARNING with chown instructions if `/data/ptcgl_logs` is not writable at startup.

6. **Frontend Error column** (`frontend/src/pages/ObservedPlay.tsx`): Added `Error` column to import report table (`l.error ?? '—'`). Added batch-level errors/warnings section below the counts grid.

### Tests Added

- **`backend/tests/test_observed_play/test_importer.py`**: 13 new async `TestRunImport` tests covering: realistic PTCGL log with bullets/curly apostrophes, spaced filename, UTF-8 BOM, invalid binary with clear error, `parse_status == "raw_archived"` for success, `parse_status != "failed"` for infrastructure failures, archive directory auto-created, archive file exists at stored_path, failed result includes error, `batch.errors_json` populated on failure, `batch.summary_json` includes files, duplicate detection.

- **`frontend/src/pages/ObservedPlay.test.tsx`**: 3 new tests: failed import shows file-level error in Error column, successful import shows `—`, batch-level errors/warnings render when present.

### Validation (session 22)

- `cd backend && python3 -m pytest tests/ -x -q`: **648 passed, 1 skipped** ✓
- `cd frontend && npm test -- --run`: **154 passed (15 files)** ✓
- `cd frontend && npm run build`: clean ✓
- `docs/AUDIT_STATE.md`: not touched ✓
- `frontend/node_modules`: not committed ✓
- No raw battle logs committed ✓
- No parser/card-resolution/memory ingestion added ✓

## Session 21 Work (2026-05-05)

### Goal

Observed Play Memory Phase 1: Raw Archive and Import Foundation on branch `feature/observed-play-memory`.

### Completed

**Phase 1 — Raw import foundation implemented:**

1. **DB models** (`backend/app/db/models.py`): Added `ObservedPlayImportBatch` and `ObservedPlayLog` ORM models with all Phase 1 fields, relationships, and unique constraint on `sha256_hash`.

2. **Alembic migration** (`backend/alembic/versions/b9f8e1d2c3a4_observed_play_foundation.py`): Creates `observed_play_import_batches`, `observed_play_logs`, 4 indexes, unique constraint. `alembic upgrade head` applied successfully.

3. **Storage module** (`backend/app/observed_play/storage.py`): SHA-256 computation, archive path convention (`archive/{sha[:2]}/{sha}{ext}`), archive/failed file writers, safe_filename, directory setup. Constants: max single file 2 MB, max ZIP 25 MB, max ZIP entries 500.

4. **Importer module** (`backend/app/observed_play/importer.py`): `run_import()` orchestrates `.md`/`.markdown`/`.txt` (single file) and `.zip` (synchronous, Phase 1). Duplicate detection via `sha256_hash`, ZIP-slip protection, size/entry limits. Sets `parse_status="raw_archived"`, `memory_status="not_ingested"` — no parser or memory ingestion.

5. **API routes** (`backend/app/api/observed_play.py`): `POST /api/observed-play/upload`, `GET /api/observed-play/batches`, `GET /api/observed-play/batches/{id}`, `GET /api/observed-play/logs`, `GET /api/observed-play/logs/{id}`. Registered in `backend/app/api/router.py`.

6. **Docker** (`docker-compose.yml`): Added `ptcgl_logs_data` named volume, mounted to backend and celery-worker at `/data/ptcgl_logs`. Added `OBSERVED_PLAY_LOG_ROOT` env var to both.

7. **Pydantic schemas** (`backend/app/observed_play/schemas.py`): `LogImportResult`, `BatchImportResponse`, `LogSummary`, `LogDetail`, `BatchSummary`, `BatchDetail`, `PaginatedBatches`, `PaginatedLogs`.

8. **Frontend** (`frontend/src/types/observedPlay.ts`, `frontend/src/api/observedPlay.ts`, `frontend/src/pages/ObservedPlay.tsx`): TypeScript types, API client functions, full Observed Play page with upload panel, import report, import history table, raw logs table, raw log viewer modal. Phase banner: "Raw archive only. Parser and memory ingestion are not active yet."

9. **Navigation**: Added Observed Play entry to `frontend/src/components/layout/Sidebar.tsx`. Route `/observed-play` added to `frontend/src/router.tsx`.

10. **Tests**: 37 new backend tests (18 storage, 7 importer, 12 API mock-DB style). 10 new frontend tests. All pass.

### Validation (session 21)

- `alembic upgrade head`: applied migration `b9f8e1d2c3a4` ✓
- `alembic current`: `b9f8e1d2c3a4 (head)` ✓
- `cd backend && python3 -m pytest tests/ -x -q`: **635 passed, 1 skipped** ✓
- `cd frontend && npm test -- --run`: **151 passed (15 files)** ✓
- `cd frontend && npm run build`: clean ✓
- `docker compose config`: valid ✓

**Not implemented (Phase 2+):** parser event extraction, card mention/resolution, Coach/AI Player integration, Neo4j writes, pgvector embeddings, memory ingestion.

## Session 20 Work (2026-05-05)

### Goal

Phase 0 design-alignment pass for Observed Play Memory on feature branch
`feature/observed-play-memory`.

### Completed

- docs(observed-play): add implementation plan — created `docs/proposals/OBSERVED_PLAY_MEMORY_IMPLEMENTATION_PLAN.md` (all 23 required sections); defines MVP boundary, parallel DB tables, parser v1 architecture, card resolution strategy, 10 API routes, 9 frontend components, confidence tiers, reparse/versioning, memory ingestion stages, testing strategy, and 8-phase phased plan. No production code or migrations added.
- chore: add `data/ptcgl_logs/` to `.gitignore`
- docs: update STATUS.md and CHANGELOG.md with branch/design status

## Session 19 Work (2026-05-05)

### Goal

Add optional manual deck/archetype name overrides to Simulation Setup.

### Completed

- feat(simulation): add manual deck name overrides — users can now specify Deck Archetype Name (user deck) and Opponent Archetype Name (each opponent) in Simulation Setup; blank fields preserve automatic Gemma/fallback naming

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
