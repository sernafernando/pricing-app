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
      // always fires. This is what lets a manual per-node toggle survive a
      // repeated global toggle — manual toggles never touch this store, so the
      // epoch (and thus the sync effect) never fires again until the NEXT
      // global activation.
      collapseEpoch: 0,
      collapseMode: 'manual', // 'manual' | 'all-open' | 'all-closed'

      expandAll: () => set((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-open' })),

      collapseAll: () => set((state) => ({ collapseEpoch: state.collapseEpoch + 1, collapseMode: 'all-closed' })),
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
