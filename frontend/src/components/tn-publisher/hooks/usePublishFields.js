/**
 * usePublishFields — one reducer over the editable draft fields (title,
 * ordered/deletable images, manual price). Replaces three of the original
 * 17 `useState` calls from the pre-decomposition `TnPublishModal.jsx`; the
 * remaining ones live in the sibling `useCategoryPicker` / `useMarkupOffset`
 * / `usePublishSubmit` hooks (see `tn-publisher/TnPublishModal.jsx`).
 *
 * Pure refactor (PR-6): behavior is moved verbatim, not changed. The
 * `dirty-only edits` shape referenced by the design doc lands with PR-7's
 * field-catalog work.
 */
import { useReducer, useCallback, useMemo } from 'react';
import { arrayMove } from '@dnd-kit/sortable';

function initFields(row) {
  return {
    title: row?.ml_title || '',
    // Ids are index-seeded so duplicate srcs can never collide as dnd-kit ids.
    images: (Array.isArray(row?.images) ? row.images : []).map((src, idx) => ({ id: `img-${idx}`, src })),
    manualPrice: row?.precio_lista_ml != null ? String(row.precio_lista_ml) : '',
  };
}

function reducer(state, action) {
  switch (action.type) {
    case 'SET_TITLE':
      return { ...state, title: action.value };
    case 'SET_MANUAL_PRICE':
      return { ...state, manualPrice: action.value };
    case 'REORDER_IMAGES': {
      const oldIndex = state.images.findIndex((img) => img.id === action.activeId);
      const newIndex = state.images.findIndex((img) => img.id === action.overId);
      if (oldIndex === -1 || newIndex === -1) return state;
      return { ...state, images: arrayMove(state.images, oldIndex, newIndex) };
    }
    case 'DELETE_IMAGE':
      return { ...state, images: state.images.filter((img) => img.id !== action.id) };
    default:
      return state;
  }
}

export function usePublishFields(row) {
  const [state, dispatch] = useReducer(reducer, row, initFields);

  const setTitle = useCallback((value) => dispatch({ type: 'SET_TITLE', value }), []);
  const setManualPrice = useCallback((value) => dispatch({ type: 'SET_MANUAL_PRICE', value }), []);

  const handleDragEnd = useCallback((event) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    dispatch({ type: 'REORDER_IMAGES', activeId: active.id, overId: over.id });
  }, []);

  const deleteImage = useCallback((id) => dispatch({ type: 'DELETE_IMAGE', id }), []);

  const imageIds = useMemo(() => state.images.map((img) => img.id), [state.images]);

  return {
    title: state.title,
    setTitle,
    images: state.images,
    imageIds,
    handleDragEnd,
    deleteImage,
    manualPrice: state.manualPrice,
    setManualPrice,
  };
}
