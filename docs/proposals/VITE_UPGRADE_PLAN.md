# Vite Upgrade Plan

**Status:** accepted and implemented 2026-05-02 with the conservative Vite 6 path; retained as historical rationale. Do not run `npm audit fix --force` from this old plan.
**Date:** 2026-05-02  

---

## Advisory Summary

- **GHSA-67mh-4wv8-2f99** — esbuild `<=0.24.2` allows any website to send requests to the Vite dev server and read responses.
- Severity: **moderate**
- Affected: **development server only** — production builds are not served by Vite's dev server.
- Current stack: `vite@5.4.21` (lockfile), `esbuild@0.21.5`, `vitest@4.1.5`
- Recommended fix by npm audit: `vite@8.0.10` (three semver-major jumps: 5 → 6 → 7 → 8)

---

## Production vs Dev Impact

| Scenario | Affected? |
|---|---|
| Production build output (`npm run build`) | **No** — esbuild is used only at build time; the advisory is a *dev server* issue |
| Developer running `npm run dev` on a shared or exposed host | **Yes** — any same-network origin can read dev server responses |
| CI build / Docker production image | **No** |
| Deployed Nginx-served frontend | **No** |

**Practical risk for PokéPrism:** Dev server is bound to `0.0.0.0` (see `vite.config.ts` `server.host`). If the developer's machine is on a shared network, any same-network site could probe the dev server. On a private machine or behind a firewall this risk is low. Production is unaffected.

---

## Upgrade Options

### Option A — Minimum fix: skip to vite@6.x (smallest jump)

`vite` 5 → 6 is a breaking change but the most conservative:
- Node ≥20 required (current requirement is likely already ≥18)
- `@vitejs/plugin-react` must upgrade to `≥4.4` (plugin-react `4.3.0` supports vite 5; `4.4+` is needed for vite 6 compat)
- Vitest 4.x supports vite 6 — no vitest version change required
- esbuild bundled with vite 6 is `0.24.2`+ which fixes the advisory

**Risk level: low-medium.** Vite 6 introduced a new Environment API but most apps need no changes.

### Option B — Jump to vite@8.x (npm audit suggestion, highest risk)

Jumps three major versions. Includes:
- Vite 6 breaking changes (Environment API, `resolve.conditions` defaults)
- Vite 7 breaking changes (`outDir` cleaning behavior, `esbuildOptions` deprecated → `oxcOptions`)
- Vite 8 breaking changes (oxc transformer replaces esbuild for JSX by default; see warning already printed by vitest: `"esbuild option was specified by vite:react-babel, use oxc instead"`)

**Risk level: medium-high.** The current vitest output already shows deprecation warnings about `esbuildOptions`; upgrading to vite 8 would make these warnings into errors unless `@vitejs/plugin-react` is also upgraded.

---

## Recommended Path

**Option A** (vite 5 → 6) with a controlled rollout:

1. Pin vitest to `^4.1.5` (already pinned) — no change.
2. Upgrade `vite` to `^6.4.2` and `@vitejs/plugin-react` to `^4.4.0` in `package.json`.
3. Upgrade `esbuild` to `^0.25.0` (advisory-clean version, compatible with vite 6).
4. Run validation (see below). Fix any build errors before merging.

Commands (for review — do not run without approval):
```bash
npm install vite@^6.4.2 @vitejs/plugin-react@^4.4.0 esbuild@^0.25.0 --save-dev
npm run build
npm test
```

---

## Validation Commands

After the upgrade (do NOT run now):

```bash
# Unit tests
cd frontend && npm test

# TypeScript check
cd frontend && npx tsc --noEmit

# Production build (must complete without errors)
cd frontend && npm run build

# Check bundle sizes are similar (< 10% regression)
ls -lh frontend/dist/assets/*.js

# Dev server spot-check (manually verify app loads in browser)
cd frontend && npm run dev
```

---

## Estimated Risk

| Item | Risk |
|---|---|
| Unit tests | Low — vitest 4.x is vite 6 compatible |
| TypeScript types | Low — vite 6 types are a superset |
| Plugin compatibility | Low-medium — `plugin-react@4.4+` supports both vite 5 and 6 |
| Build output differences | Low — tree-shaking and chunk names may differ slightly |
| Dev server behavior | Low — proxy config format unchanged in vite 6 |

---

## Decision Boundary

- **Approve Option A** to patch the dev server advisory with minimal risk.
- **Defer Option B** (vite 8) until `@vitejs/plugin-react` officially documents vite 8 support and the deprecation warnings about `esbuildOptions` are resolved upstream.
- **Do nothing** if the dev server is only used on a private, firewalled machine — the advisory is dev-only and production is unaffected.
