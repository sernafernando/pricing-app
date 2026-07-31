# Apply Progress: ml-wholesale-pxq-pricing

## PR 1 — Global collapse toggle (frontend only, independent)

Status: DONE. All 9 tasks complete, committed on `feat/pxq-collapse-toggle`
(commit `30c4b4ac`), targeting tracker branch `feat/ml-wholesale-pxq-pricing`.

- Diff: 5 files changed, 148 insertions(+), 2 deletions(-) — within the ~150
  line estimate and the 200-line attempt budget.
- Tests: `pnpm run test` (vitest run) — 35 files / 533 tests passed, including
  new coverage in `treeViewStore.test.js` (epoch/mode defaults, expandAll/
  collapseAll increment epoch, ephemeral partialize exclusion) and
  `TreeNode.test.jsx` (global-open opens nested promo panel, global-close
  closes it, manual toggle after global-open survives).
- Lint: `pnpm run lint` — 0 errors, 1 pre-acknowledged warning
  (`react-hooks/exhaustive-deps` on the epoch-only sync effect in
  `TreeNode.jsx`; intentional per design D6 — the effect must fire only on
  epoch change, not on every `collapseMode` render).
- Files touched: `frontend/src/store/treeViewStore.js`,
  `frontend/src/store/treeViewStore.test.js`,
  `frontend/src/components/promociones/TreeNode.jsx`,
  `frontend/src/components/promociones/TreeNode.test.jsx`,
  `frontend/src/components/promociones/ProductoMLAsPanel.jsx` (wired
  "Expandir todo" / "Colapsar todo" buttons — the tree view UI entry point).

## PR 2, 3, 3a, 4 — NOT STARTED (out of scope for this apply run)

Explicitly excluded per this run's instructions. Next apply run should pick
up PR 2 (`ml_pxq_tier` model + migration + permissions + quantity-aware
markup) targeting the tracker branch directly.
