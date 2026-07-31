import { create } from 'zustand';
import { persist } from 'zustand/middleware';

// Global (not per-product) view preference for the productos catalog/family
// publication tree (productos-catalog-family-tree). Controls whether the
// intermediate "familia" grouping node renders as its own row, or is skipped
// so its children render one level up (under the producto). Defaults to
// hidden (false) — persisted so the choice sticks across products/sessions.
export const useTreeViewStore = create(
  persist(
    (set) => ({
      showFamilia: false,

      toggleFamilia: () => set((state) => ({ showFamilia: !state.showFamilia })),

      setShowFamilia: (value) => set({ showFamilia: value }),

      // Global synchronized collapse toggle (tree-view-collapse). `collapseEpoch`
      // is a monotonic counter, not a boolean: every activation increments it,
      // even when re-applying the same mode, so `TreeNode`'s `useEffect([epoch])`
      // always fires. The epoch never changes on a manual toggle, so a manual
      // per-node choice survives until the NEXT global activation.
      //
      // `collapseMode` is read by nodes that mount LATER, and that is the whole
      // point: children only mount once their parent is open, so "expand all"
      // reaches an unmounted subtree through the mount cascade rather than in a
      // single pass. That cascade must stop as soon as the user takes manual
      // control, otherwise every node opened by hand from then on would explode
      // its entire subtree. `markManual()` is that off switch — it leaves the
      // epoch untouched (so already-mounted nodes keep exactly the state the
      // user gave them) and only stops future mounts from force-opening.
      collapseEpoch: 0,
      collapseMode: 'manual', // 'manual' | 'all-open' | 'all-closed'

      expandAll: () => set((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-open' })),

      collapseAll: () => set((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-closed' })),

      markManual: () => set((state) => (state.collapseMode === 'manual' ? state : { collapseMode: 'manual' })),
    }),
    {
      name: 'tree-view-store',
      // Ephemeral view state — collapseEpoch/collapseMode must NOT survive a
      // reload (a stale "all-open" epoch would force every node open on next
      // visit). Only showFamilia is a genuine sticky preference.
      partialize: (state) => ({ showFamilia: state.showFamilia }),
    },
  ),
);
