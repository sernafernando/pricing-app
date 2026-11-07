# Diagnosis: Frontend unit suite OOM in CI

**Status:** Fix A + Fix B approved and in implementation (PR pending); Fix C deferred as intentional follow-up  
**Date:** 2026-11-07  
**Scope:** `frontend` Vitest **unit** project (`pnpm test` → `vitest run --project=unit`), GitHub Actions job `Frontend Tests`  
**Out of scope:** production app runtime, Coolify/server RAM, visual (Playwright) suite

---

## 1. What we are trying to solve

CI job **Frontend Tests** intermittently fails with **no failing assertion**. The Vitest worker process dies with a V8 heap OOM near the end of the ~399-file unit suite. That blocks stacked PRs and wastes Actions minutes on retries.

This is **not** evidence that Pricing App production is “inefficient” or needs more server RAM. It is a **test-runner memory** problem on ephemeral GitHub-hosted runners.

---

## 2. Symptom (hard evidence from CI logs)

| Run / job | HEAD (short) | Heap cap | Result near end | Evidence |
|-----------|--------------|----------|-----------------|----------|
| [42402163054 / 128492085788](https://github.com/sernafernando/pricing-app/actions/runs/42402163054/job/128492085788) | `84f9a75` | 8 GB (`NODE_OPTIONS`) | **398/399** files passed → OOM | `FATAL ERROR: Ineffective mark-compacts near heap limit`; `Worker exited unexpectedly` |
| [42403568320 / 128496349498](https://github.com/sernafernando/pricing-app/actions/runs/42403568320/job/128496349498) | `eaa709e` | **12 GB** | **398/399** → OOM | GC log: `Scavenge … 12272.1 (12279.1) MB` then same FATAL |
| [42405316182 / 128501634793](https://github.com/sernafernando/pricing-app/actions/runs/42405316182/job/128501634793) shard **1/2** | `fef6188` | 8 GB | **199/200** → OOM (~19 m) | Same FATAL |
| Same run / [128501634894](https://github.com/sernafernando/pricing-app/actions/runs/42405316182/job/128501634894) shard **2/2** | `fef6188` | 8 GB | **199/199** **pass** in ~4 m | Proves failure is **not** “half the tests are wrong”; cost is **uneven across files** |

Representative excerpts:

```text
FATAL ERROR: Ineffective mark-compacts near heap limit Allocation failed - JavaScript heap out of memory
Caused by: Error: Worker exited unexpectedly
Test Files  398 passed (399)
```

```text
[…] Scavenge (interleaved) 12272.1 (12279.1) -> 12268.2 (12287.1) MB […]
FATAL ERROR: Ineffective mark-compacts near heap limit
```

**Pattern:** almost the entire suite is green; death happens in the **last file / GC thrash window** after hundreds of jsdom environments. On the 12 GB run, last passing files logged ~8 minutes before FATAL (GC death spiral, not a new assertion).

**Contrast:** [#2156](https://github.com/sernafernando/pricing-app/pull/2156) Frontend Tests **passed** in ~6 m39 s on an earlier HEAD — OOM is **near the ceiling** and sensitive to runner load / file set / order, not a single deterministic `expect()` failure.

Suite size today: **~399** unit test files.

---

## 3. What we already tried (and rejected for the tacticals stack)

Experiments landed only on `.github/workflows/ci.yml` (tacticals stack), then **reverted** to match `main` (commit `7b7a95ed6` on `feat/tacticals-tienda-03-ui` + rebase of #2158–#2163):

| Approach | Outcome | Why we stop using it as the “fix” |
|----------|---------|-------------------------------------|
| Raise heap 4→8→12 GB | Still OOM at ~12 GB on full suite | Treats capacity, not cause; burns runner RAM |
| Cap `maxWorkers` via `pnpm test -- --maxWorkers=2` | Vitest saw a literal `--`; flag ignored | Fragile; doesn’t remove accumulation |
| Split into 2 shards | Shard 2 green; **shard 1 still OOM** | Heavy files cluster in one shard; **2×** (then 4×) concurrent jobs **steal Actions concurrency** from other PRs |
| 4 shards + 12 GB | Reverted before relying on it | Same class of workaround; multiplies runners |

**Motivation for reverting:** product PRs should not carry CI memory band-aids; concurrency cost is real; root cause belongs in the **unit test harness / suite**, in a dedicated change.

---

## 4. Problems detected (resolvable vs follow-up)

### P1 — Vitest worker heap exhaustion in CI (symptom)

- **What:** One Node worker grows until V8 cannot compact (`Ineffective mark-compacts`).
- **Evidence:** §2 table; heap ~8 GB and ~12 GB both fail on full or heavy shard.
- **Not:** A failed product assertion; not production server RAM.

### P2 — Full `lucide-react` catalog loaded in every unit worker via setup mock

- **Where:** `frontend/src/test/setup.js` currently:

```js
vi.mock('lucide-react', async (importOriginal) => {
  return await importOriginal();
});
```

- **Evidence:**
  - Comment in setup admits intent: load **all** real exports.
  - `lucide-react@0.563.0`: **~1914** icon modules under `dist/esm/icons`; barrel `dist/esm/lucide-react.js` ~221 KB; app code imports lucide from **~265** non-test modules; **~355** distinct named imports across `src` (unit-relevant).
  - Setup runs for **every** unit file; workers keep process-level module graphs across files.
- **Why it matters:** Unit tests do not need real SVG path implementations; they need resolvable components (and stable identity where tests use `toBe(Laptop)`).
- **Resolvable:** yes (harness change).

### P3 — Module-scoped `localStorage` stub never cleared between tests

- **Where:** same `setup.js`: `const localStorageData = {}` with `clear()` implemented, but `afterEach` only restores `console.error` and `vi.clearAllMocks()` — **does not** call `localStorage.clear()`.
- **Evidence:** code inspection; **49** source files touch `localStorage` APIs; several high-churn tests (`ThemeContext`, `MLQuestions`, column-sizing, etc.) call `setItem` without a global reset.
- **Why it matters:** keys accumulate for the lifetime of the worker → RSS + cross-test pollution (correctness flake risk, e.g. column-sizing).
- **Resolvable:** yes (one-line harness fix + keep tests that need specific keys explicit).

### P4 — Highly uneven cost across test files (amplifier)

- **Evidence:** shard **2/2** ~4 m all pass; shard **1/2** ~19 m then OOM. Heaviest unit files by line count include `PublicacionesML.test.jsx` (~3.3k), `VentasML.test.jsx` (~2.2k), large promo/TN/MLQuestions pages.
- **Why it matters:** index-based sharding does not balance **memory**; one worker still mounts huge trees repeatedly.
- **Resolvable (partially):** yes, but as **follow-up** refactors (split files, thinner renders) — larger than a harness PR.

### P5 — Draft stub via `Proxy` is insufficient for Vitest named exports

- **Evidence:** local experiment — `SaleItemThumbnail.test.jsx` failed with  
  `No "Package" export is defined on the "lucide-react" mock`  
  when mocking with a `Proxy` only. Vitest validates **named exports** on the mock module object; a Proxy trap is not enough.
- **Implication:** any lucide fix must expose **real named exports** Vitest can see (generated stub module, alias, or explicit export map) — not “Proxy-only `vi.mock`”.

---

## 5. Proposed solutions (concrete, per problem)

### Fix A — Replace `importOriginal()` lucide mock with a lightweight stub module (addresses P2, P5)

1. Add something like `frontend/src/test/lucide-react-stub.js` (or a small generator script checked into `frontend/scripts/`) that exports **stable per-name** React stub components (`forwardRef` → `<svg aria-hidden … />`) for every lucide name imported by the repo (~355 today), so:
   - `import { Package } from 'lucide-react'` works under Vitest;
   - `getCategoryIcon('NOTEBOOK') === Laptop` keeps working (distinct function identity per name).
2. Point the **unit** Vitest project at that stub via `vi.mock('lucide-react', () => import('./lucide-react-stub.js'))` **or** a Vite `resolve.alias` active only for the unit project — **not** for production build, **not** for visual project unless separately decided.
3. Do **not** call `importOriginal()` for lucide in unit setup.
4. **Acceptance:** `categoryIcon.test.js`, `SaleItemThumbnail.test.jsx`, and a sample of icon-heavy page tests pass; full `pnpm test` completes on CI **without** raising `NODE_OPTIONS` / without sharding.

### Fix B — Clear harness `localStorage` in `afterEach` (addresses P3)

1. In `setup.js` `afterEach`: `localStorage.clear()` (stub already implements it).
2. **Acceptance:** existing tests that rely on prior keys either set them in `beforeEach` (already common) or get a quick adjust; column-sizing / theme tests stay green.

### Fix C — Optional follow-up PR(s): slim heaviest page tests (addresses P4)

1. Inventory top memory/time offenders (start from largest page tests + CI timing).
2. Prefer thinner renders / fewer full-app mounts per file over “more RAM”.
3. Only after A+B if OOM persists under default CI heap (~4 GB class).

### Explicitly **not** proposed as the primary fix

- Permanently raising Actions heap or fan-out shards on every PR (concurrency + cost; already shown insufficient at 12 GB for the full suite).
- Changing production bundle or server sizing.

---

## 6. Suggested delivery shape (after approval)

| PR | Contents | Base |
|----|----------|------|
| **1** | Fix A + Fix B + this diagnosis (or short pointer in PR body) + any tiny test `beforeEach` fixes | `main` |
| **2+** | Fix C only if still needed | `main` |

Tacticals stack (#2156–#2163) keeps **stock** `Frontend Tests` job (already reverted). It may still flake until PR 1 lands on `main` and is merged/rebased into the stack.

---

## 7. Validation plan

1. Local: `pnpm test` in `frontend` on the fix branch (default Node heap).
2. CI on the fix PR: single `Frontend Tests` job, **no** extra `NODE_OPTIONS`, **no** matrix shards — must pass.
3. Regression spot checks: lucide identity tests + one heavy page file (`VentasML` or `PublicacionesML` subset).
4. If green: rebase tacticals onto updated `main` (or merge order as usual) so the stack inherits the harness fix without reintroducing CI band-aids.

---

## 8. Decisions (2026-11-07)

1. **PR 1 = Fix A + Fix B** — approved. Ship harness fix first; validate with full unit suite / CI without raising heap or sharding.
2. **Stub = generated file committed** + `frontend/scripts/generate-lucide-react-stub.mjs` (`pnpm run generate:lucide-stub`). Unit project aliases `lucide-react` → stub in `vite.config.js` (visual project keeps real lucide).
3. **Fix C** — still do it as a **follow-up PR** after A+B are green, even if we can no longer measure impact on the tacticals stack. C benefits the whole repo’s CI (time + headroom), not only one feature branch.

---

## 9. References

- Setup under discussion: `frontend/src/test/setup.js`
- Unit project config: `frontend/vite.config.js` (`environment: 'jsdom'`, `setupFiles: './src/test/setup.js'`)
- Revert on tacticals UI branch: `7b7a95ed6` — `revert(ci): restore Frontend Tests job to main defaults`
