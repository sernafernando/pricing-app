import { create } from 'zustand';

// Global (not per-panel) filter for the Productos promotions panels.
// selectedTypes empty => show ALL promos across every expanded MLA panel.
export const usePromoFilterStore = create((set) => ({
  selectedTypes: [],

  // Per-type name narrowing. { [promotion_type]: string[] }.
  // A type ABSENT from the map, or mapped to an empty array, means "no name
  // narrowing for this type" -> every name of that type passes. Names come
  // from resolvePromoName (promo.name, falling back to promo.payload.name,
  // or null when genuinely unnamed).
  selectedNames: {},

  toggleType: (type) =>
    set((state) => ({
      selectedTypes: state.selectedTypes.includes(type)
        ? state.selectedTypes.filter((t) => t !== type)
        : [...state.selectedTypes, type],
      // selectedNames for a deselected type is intentionally NOT pruned:
      // the type predicate already makes it unreachable, and re-selecting
      // the type restores the analyst's prior narrowing.
    })),

  toggleName: (type, name) =>
    set((state) => {
      const current = state.selectedNames[type] || [];
      const next = current.includes(name) ? current.filter((n) => n !== name) : [...current, name];
      const selectedNames = { ...state.selectedNames };
      if (next.length === 0) {
        delete selectedNames[type]; // absent == unfiltered, one representation
      } else {
        selectedNames[type] = next;
      }
      return { selectedNames };
    }),

  clearNamesForType: (type) =>
    set((state) => {
      const selectedNames = { ...state.selectedNames };
      delete selectedNames[type];
      return { selectedNames };
    }),

  clear: () => set({ selectedTypes: [], selectedNames: {} }),
}));
