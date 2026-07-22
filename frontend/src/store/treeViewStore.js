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
    }),
    {
      name: 'tree-view-store',
    },
  ),
);
