# Observed Play Memory Merge-Readiness Report

Date: 2026-05-08
Branch: `feature/observed-play-memory`
Reviewed HEAD: `b3958c9a5c48734da560e3d378cee38f5a549a13`
Origin HEAD: `b3958c9a5c48734da560e3d378cee38f5a549a13`

## 1. Executive Summary

This was an independent hardening sweep of the `observed-play-memory` branch after Phase 6.2b validation. I found no merge-blocking correctness, migration, flag-safety, read-only, or validation failures in the observed-play retrieval path.

The branch is **ready after minor fixes**. The only branch-local issue found was documentation drift in the Phase 6.2 plan: older examples still used `query_card_ids/query_card_names` after the implementation was refined to `deck_card_ids/deck_card_names`. I corrected those stale references in this sweep.

Important non-blocking repository hygiene note: `frontend/node_modules` is already tracked on both `origin/main` and this branch. It was not dirty or staged in this sweep and was not introduced by `observed-play-memory`.

## 2. Branch and Commit Reviewed

- `git branch --show-current` -> `feature/observed-play-memory`
- `git rev-parse HEAD` -> `b3958c9a5c48734da560e3d378cee38f5a549a13`
- `git rev-parse origin/feature/observed-play-memory` -> `b3958c9a5c48734da560e3d378cee38f5a549a13`
- Initial `git status --short` was clean.
- `docs/AUDIT_STATE.md` was read only and was not modified.

## 3. Validation Commands Run

Initial checks:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse origin/feature/observed-play-memory
docker compose ps
docker compose exec backend alembic current
docker compose exec backend alembic heads
```

Hardening searches and inspection:

```bash
git diff --name-only origin/main...HEAD
git diff --stat origin/main...HEAD
rg -n "OBSERVED_PLAY_MEMORY_ENABLED|OBSERVED_PLAY_MEMORY_MAX_EVIDENCE|OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE" .
rg -n "query_card_ids|query_card_names|retrieval_metadata|no_relevant_evidence|observed_play_meta|observed_play_acknowledgment" backend frontend docs
rg -n "observed_play_logs|observed_play_events|observed_card_mentions|observed_play_memory_ingestions|observed_play_memory_items|card_performance|match_events|Neo4j|pgvector|GraphMemory|Embedding" backend/app backend/tests
rg -n "^(revision|down_revision)" backend/alembic/versions/*.py
git ls-files frontend/node_modules | wc -l
git ls-tree -r --name-only origin/main frontend/node_modules | wc -l
git ls-files | rg '(^|/)(\.env|.*\.env|node_modules|.*\.log|.*\.sqlite|.*\.db|.*\.dump|.*\.sql|.*\.png|.*\.jpg|.*\.jpeg|.*\.webp|.*\.zip|tmp|reports/|ptcgl_logs|battle.*log|screenshot)'
rg -n "(POSTGRES_PASSWORD|NEO4J_PASSWORD|OLLAMA|api[_-]?key|secret|token|password|BEGIN RSA|PRIVATE KEY|Gemst0n|Bearer )" --glob '!frontend/node_modules/**' --glob '!backend/alembic/versions/__pycache__/**' .
find . -type f -size +1M -not -path './.git/*' -not -path './frontend/node_modules/*' -not -path './backend/.pytest_cache/*' -not -path './frontend/dist/*' -print
git status --short --ignored
```

Final validation:

```bash
cd backend && python3 -m pytest tests/ -x -q
cd frontend && npm test -- --run
cd frontend && npm run build
git diff --check
git status --short
```

## 4. Test Results

- Backend: `1223 passed, 1 skipped, 4 warnings in 29.56s`
- Frontend unit tests: `353 passed (18 files)`
- Frontend build: passed
- `git diff --check`: passed
- Final status before report commit: only docs/report files changed

The backend warnings are existing `AsyncMock` resource warnings in Coach tests; they did not fail the suite.

## 5. Config / Flag Review

Result: pass.

- `backend/app/config.py` defaults `OBSERVED_PLAY_MEMORY_ENABLED` to `False`.
- `docker-compose.override.yml` passes `${OBSERVED_PLAY_MEMORY_ENABLED:-false}` to both `backend` and `celery-worker`.
- `.env.example` documents the flag as commented-out local-only enablement.
- No hard-coded `OBSERVED_PLAY_MEMORY_ENABLED: "true"` remains in compose/config/code.
- Flag-off Coach path returns `("", [], None)` from `_fetch_observed_play_block()` and does not inject the observed-play prompt block.

## 6. Migration Review

Result: pass.

- Observed-play migrations form one ordered chain:
  - `b9f8e1d2c3a4` <- `5b7e9c2d4a11`
  - `e1f2a3b4c5d6` <- `b9f8e1d2c3a4`
  - `f2a3b4c5d6e7` <- `e1f2a3b4c5d6`
  - `g3h4i5j6k7l8` <- `f2a3b4c5d6e7`
  - `h4i5j6k7l8m9` <- `g3h4i5j6k7l8`
  - `i5j6k7l8m9o0` <- `h4i5j6k7l8m9`
- `alembic heads` reports a single head: `i5j6k7l8m9o0`.
- Local DB current is `i5j6k7l8m9o0 (head)`.
- New `observed_play_meta` columns are nullable JSONB and safe for old simulations/mutations.
- No destructive upgrade migration was found.

## 7. Backend Review

Result: pass.

Files inspected included:

- `backend/app/config.py`
- `backend/app/api/observed_play.py`
- `backend/app/api/simulations.py`
- `backend/app/coach/analyst.py`
- `backend/app/coach/prompts.py`
- `backend/app/observed_play/coach_context.py`
- `backend/app/observed_play/readiness_service.py`
- `backend/app/observed_play/memory_ingestion.py`
- `backend/app/observed_play/parser.py`
- `backend/app/observed_play/card_mentions.py`
- `backend/app/observed_play/card_resolution.py`
- `backend/app/observed_play/schemas.py`
- `backend/app/db/models.py`
- observed-play Alembic migrations
- observed-play and Coach/simulation tests

Notes:

- `build_coach_context_preview()` and `_fetch_observed_play_block()` use read-only `SELECT` paths for retrieval.
- Tiered retrieval is deck-contextual, bounded by `OBSERVED_PLAY_MEMORY_MAX_EVIDENCE`, confidence-gated, and source-capped.
- Normal Coach path passes deck/candidate context and `allow_fallback=False`.
- No-relevant-evidence returns `would_inject=False`, empty `prompt_block`, and explicit `no_relevant_evidence=true`.
- `observed_play_acknowledgment` fallback behavior is explicit and visible through persisted simulation debug metadata.
- `coach-debug` is read-only and tolerates missing old metadata.

Expected writes:

- `simulations.observed_play_meta` stores per-round debug/injection metadata.
- `deck_mutations.observed_play_meta` stores mutation-level debug/injection metadata when mutations are written.

Those writes are expected simulation/debug metadata writes, not corpus mutation.

## 8. Frontend Review

Result: pass.

Files inspected included:

- `frontend/src/pages/ObservedPlay.tsx`
- `frontend/src/types/observedPlay.ts`
- `frontend/src/api/observedPlay.ts`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/types/simulation.ts`
- `frontend/src/api/simulations.ts`
- `frontend/src/components/observedPlay/RetrievalMetadataPanel.tsx`
- `frontend/src/components/simulation/ObservedPlayRetrievalDebugTile.tsx`
- related frontend tests

Notes:

- `/observed-play` preview clearly describes its manual-filter/no-simulation-context limitation.
- Dashboard `coach-debug` fetch is separate and non-fatal.
- Dashboard debug tile handles flag-off, old simulations with no `analysis_rounds`, no-relevant-evidence, and rounds with missing retrieval metadata.
- API types match implemented `deck_card_ids/deck_card_names` metadata.
- No remaining frontend use of `query_card_ids/query_card_names` was found.

## 9. Read-Only / Data-Write Review

Result: pass.

Retrieval/debug paths reviewed do not write to:

- `observed_play_logs`
- `observed_play_events`
- `observed_card_mentions`
- `observed_play_memory_ingestions`
- `observed_play_memory_items`
- `card_performance`
- `match_events`
- pgvector embeddings
- Neo4j graph memory

Observed-play ingestion endpoints intentionally mutate observed-play corpus tables when explicitly invoked by upload/reparse/resolve/ingest UI actions. Retrieval itself does not.

Existing Coach mutation flow can still write normal `deck_mutations` rows and record swaps through existing Coach machinery when Coach produces valid swaps. This sweep did not change that behavior.

## 10. Security / Data Hygiene Review

Result: pass for this branch; informational pre-existing repo issue noted.

- No dirty or staged `.env` files.
- No dirty or staged real logs, screenshots, database dumps, temporary reports, or local secrets.
- `backend/tests/fixtures/observed_play/*.md` are small curated test fixtures.
- `backend/init.sql` is tracked and pre-existing.
- `frontend/node_modules` is tracked in both `origin/main` and this branch (`3184` tracked paths). It was not changed, staged, or introduced here.

## 11. Documentation Consistency Review

Result: pass after minor docs fix.

Docs now agree on:

- Phase 6.1, 6.2a, and 6.2b completion.
- `OBSERVED_PLAY_MEMORY_ENABLED=false` default.
- Advisory-only scope.
- No gameplay-control claim.
- Dashboard tile as authoritative retrieval-debug UI.
- `/observed-play` preview limitation.
- Known LLM acknowledgment caveat and fallback `not_used_reason`.

The stale `query_card_ids/query_card_names` examples in `docs/proposals/OBSERVED_PLAY_EVIDENCE_RELEVANCE_PLAN.md` were corrected to `deck_card_ids/deck_card_names`.

## 12. Findings by Severity

### Blocker

None.

### High

None.

### Medium

None.

### Low

- Documentation drift: `docs/proposals/OBSERVED_PLAY_EVIDENCE_RELEVANCE_PLAN.md` still had older `query_card_ids/query_card_names` examples. Fixed in this sweep.

### Informational

- `frontend/node_modules` is tracked in the repository on both `origin/main` and this branch. Not introduced or modified by this branch, but worth cleaning up separately.
- Backend tests emit 4 `AsyncMock` resource warnings in Coach tests. Non-fatal and not specific to this report change.

## 13. Recommended Fixes Before Merge

No code fixes required before merge.

Recommended before merge:

- Review and accept this docs-only report.
- Consider a separate repository hygiene PR to remove tracked `frontend/node_modules` from version control.

## 14. Recommended Manual Checks Before Merge

- Run one flag-off H/H simulation and confirm no observed-play block appears in `coach-debug`.
- Run one flag-on H/H simulation with known matching corpus and confirm Dashboard tile shows Tier 1 deck-card evidence.
- Run one flag-on H/H simulation with no relevant corpus match and confirm `no_relevant_evidence=true`, `would_inject=false`, and no prompt block.
- Reconfirm observed-play corpus table row counts unchanged after a flag-on retrieval simulation.

## 15. Explicit Non-Findings / Things That Are Okay

- `OBSERVED_PLAY_MEMORY_ENABLED` defaults false.
- Backend and celery-worker share the same flag source.
- `.env.example` documents local opt-in safely.
- `coach-debug` fetch is read-only and non-fatal in the Dashboard.
- `/observed-play` Coach Context Preview is intentionally not authoritative for simulation deck-contextual retrieval.
- Simulation/debug metadata writes are expected and acceptable.
- Old simulations without observed-play metadata remain compatible.
- No semantic retrieval, deck archetype labeling, pgvector retrieval, AI Player control, deck-builder behavior, simulator gameplay logic, match event writes, card-performance writes, Neo4j writes, or observed-play ingestion behavior was changed in this sweep.

## 16. Final Merge-Readiness Verdict

**Ready after minor fixes.**

The minor docs drift was corrected in this report pass. With tests/build passing and no code findings, I consider the branch merge-ready from this hardening sweep.
