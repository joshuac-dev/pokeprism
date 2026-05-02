# Playwright E2E Test Plan

**Status:** proposal only — do not install Playwright  
**Date:** 2026-05-02  

---

## What Current Tests Cover

### Backend (pytest, 260 tests)
- Engine correctness: card handlers, transitions, state machine
- API contract: HTTP status codes, request validation, response shapes
- Coach/Analyst: prompt construction, response parsing, validation
- Simulation task: Celery task logic, writer calls
- Cards: loader, coverage, TCGDex fixture transforms

### Frontend (vitest, 4 tests)
- Two component unit tests — basic rendering only

### What is NOT tested
- That the app actually loads in a browser
- Socket.IO live event streaming and UI updates
- Route navigation (SimulationLive, History, Memory, Coverage pages)
- Chart and graph rendering (Recharts, D3, Neo4j mind-map)
- Simulation form submission → backend → WebSocket round-trip
- Cancel button mid-simulation
- Error state rendering (network failures, bad deck input)
- AI Reasoning overlay trigger and content
- Memory page card search and profile load
- Coverage page sort/filter behavior
- The 9 critical workflows listed below

---

## Playwright Gap Analysis

| Workflow | curl/API smoke | Browser needed |
|---|---|---|
| App loads, route renders | No | Yes |
| Create H/H full-deck sim | Partial (API only) | Yes (form + progress) |
| Create partial-deck sim | No | Yes |
| Create no-deck sim | No | Yes |
| See live match progress in console | No | Yes (WebSocket) |
| Cancel running simulation | No | Yes (cancel button + status) |
| View dashboard after completion | No | Yes (charts render) |
| View history list and match detail | No | Yes |
| Memory page — search + graph | No | Yes (D3 graph) |

---

## Recommended Test Cases (Priority Order)

### Tier 1 — Smoke (must pass before every deploy)

1. **App loads** — navigate to `/`, assert sidebar links are visible, no console errors.
2. **Simulation form renders** — navigate to `/simulation`, all form fields visible, submit disabled without deck input.
3. **H/H simulation round-trip** — fill form with a known deck (use a hardcoded test deck), click Start, assert:
   - WebSocket events appear in the console panel within 10s
   - Status badge transitions from `running` to `complete`
   - Match count increments
4. **Cancel simulation** — start a simulation, click Cancel within 2s, assert status becomes `cancelled` within 5s.
5. **Coverage page loads** — navigate to `/coverage`, assert table has > 2000 rows, 100% shown.

### Tier 2 — Feature (run on PRs touching relevant pages)

6. **Dashboard charts render** — after a completed simulation, navigate to `/dashboard`, assert Recharts SVG elements exist.
7. **History list** — navigate to `/history`, assert at least one simulation row visible with a status.
8. **AI Reasoning overlay** — run an AI/H simulation, click a console event with type `attack_declared`, assert the overlay opens and shows exactly one reasoning block (not multiple).
9. **Memory page card search** — navigate to `/memory`, type "Buddy-Buddy Poffin" in the search input, click the result, assert card profile stats appear.

### Tier 3 — Error states (run weekly)

10. **Invalid deck input** — submit form with a deck missing a Basic Pokémon, assert error message visible.
11. **Partial deck mode** — submit with a 10-card partial deck, assert the builder fills it and simulation starts.
12. **No-deck mode** — start simulation with no deck input in no-deck mode, assert simulation starts without error.

---

## Keeping Browser Tests Separate from Unit Tests

```
frontend/
  tests/           ← existing vitest unit tests (npm test, fast)
  e2e/             ← new Playwright tests (npm run e2e, slow)
    smoke.spec.ts
    simulation.spec.ts
    memory.spec.ts
```

`package.json` additions (do not apply now):
```json
"scripts": {
  "test:e2e": "playwright test",
  "test:e2e:headed": "playwright test --headed"
}
```

Vitest and Playwright should never run together. CI should gate on unit tests first; E2E runs as a separate job against a running Docker stack.

---

## CI Integration Sketch

```yaml
# .github/workflows/e2e.yml (do not create now)
e2e:
  needs: [unit-tests]
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - run: docker compose up -d
    - run: sleep 15  # wait for backend health
    - run: npx playwright install --with-deps chromium
    - run: npm run test:e2e
    - uses: actions/upload-artifact@v4
      if: failure()
      with:
        name: playwright-report
        path: playwright-report/
```

---

## Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| Playwright dependency adds ~200MB to node_modules | Low | Install in a separate `devDependencies` block, CI cache |
| E2E tests are flaky on timing | Medium | Use `waitFor` assertions, avoid fixed sleeps, test against local Docker stack |
| WebSocket tests are harder to stabilize | Medium | Mock the Socket.IO server for unit-level WS tests; use real stack for smoke only |
| Playwright requires a running backend | Low | Docker stack is already scripted (`make up`) |
| Test maintenance as UI changes | Medium | Focus E2E on user-visible outcomes, not DOM structure (use `data-testid` attributes) |

---

## Prerequisites Before Installing Playwright

1. Add `data-testid` attributes to key UI elements (simulation form, console panel, status badge) so tests are not tied to CSS classes.
2. Decide on a test-only deck (hardcoded minimal legal deck) to avoid depending on Ollama for H/H smoke tests.
3. Resolve Vite/esbuild upgrade first (VITE_UPGRADE_PLAN.md) to avoid building against a deprecated toolchain.
4. Get approval on this plan.
