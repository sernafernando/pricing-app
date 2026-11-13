import { create } from 'zustand';
import { persist } from 'zustand/middleware';

const isName = (name) => name === null || typeof name === 'string';

// A stored filter is read back only in its known shape; anything else counts as "no filter", so a value
// left by an older build or edited by hand never breaks a page that renders the filter.
function readStoredFilter(stored) {
  const types = Array.isArray(stored?.selectedTypes) ? stored.selectedTypes.filter((type) => typeof type === 'string') : [];
  const names = {};
  const storedNames = stored?.selectedNames;
  if (storedNames && typeof storedNames === 'object' && !Array.isArray(storedNames)) {
    for (const [type, list] of Object.entries(storedNames)) {
      const valid = Array.isArray(list) ? list.filter(isName) : [];
      if (valid.length > 0) names[type] = valid;
    }
  }
  return { selectedTypes: types, selectedNames: names };
}

// Global (not per-panel) promo filter: ONE setting for the user, shared by the
// Productos promotions panels and the Publicaciones ML panel, and persisted in
// this browser so it survives a reload.
// selectedTypes empty => show ALL promos across every promo list.
export const usePromoFilterStore = create(
  persist(
    (set) => ({
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
    }),
    {
      name: 'promo-filter-store',
      version: 0,
      partialize: (state) => ({ selectedTypes: state.selectedTypes, selectedNames: state.selectedNames }),
      merge: (stored, current) => ({ ...current, ...readStoredFilter(stored) }),
    },
  ),
);
