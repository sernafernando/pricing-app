import { create } from 'zustand';

// Global (not per-panel) filter for the Productos promotions panels.
// selectedTypes empty => show ALL promos across every expanded MLA panel.
export const usePromoFilterStore = create((set) => ({
  selectedTypes: [],

  toggleType: (type) =>
    set((state) => ({
      selectedTypes: state.selectedTypes.includes(type)
        ? state.selectedTypes.filter((t) => t !== type)
        : [...state.selectedTypes, type],
    })),

  clear: () => set({ selectedTypes: [] }),
}));
