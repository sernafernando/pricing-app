/**
 * useDraftFields — the PR-7 editable fields beyond title/images/manualPrice
 * (which stay in `usePublishFields`): brand, barcode, cost, the four
 * measurements, stock, promotional_price, visibility, free_shipping, and
 * the D12-seeded seo_title/seo_description/tags.
 *
 * Lazy `useReducer` init (same pattern as `usePublishFields`) — this modal
 * remounts per item via `key={ean}` in `TiendaNubeReconcile.jsx`, so a
 * fresh reducer instance is exactly "seed once when the draft envelope
 * loads" (D12, task 7.10). Measurement values start from
 * `row.publish_draft.fields[name].value`, which the BACKEND already
 * precedence-resolved (operator > override > gbp > profile > empty) — a
 * stored override therefore pre-fills for free (D8, task 7.5) without this
 * hook re-implementing precedence client-side.
 */
import { useReducer, useCallback } from 'react';
import { seedSeoTags } from '../seedSeoTags';

export const MEASUREMENT_FIELDS = ['weight', 'width', 'height', 'depth'];

function fieldValue(draftFields, name, fallback = '') {
  const raw = draftFields?.[name]?.value;
  return raw != null ? String(raw) : fallback;
}

function initDraftFields(row) {
  const draft = row?.publish_draft;
  const fields = draft?.fields || {};
  const seeded = seedSeoTags({
    name: row?.ml_title || '',
    descriptionHtml: row?.ml_desc || '',
    marca: row?.marca || '',
    categoria: row?.categoria || '',
  });

  return {
    brand: row?.marca || '',
    barcode: row?.barcode || '',
    sku: row?.ean || '',
    cost: fieldValue(fields, 'cost', row?.cost != null ? String(row.cost) : ''),
    stock: row?.stock != null ? String(row.stock) : '',
    promotionalPrice: row?.promotional_price != null ? String(row.promotional_price) : '',
    weight: fieldValue(fields, 'weight'),
    width: fieldValue(fields, 'width'),
    height: fieldValue(fields, 'height'),
    depth: fieldValue(fields, 'depth'),
    visibility: 'visible', // D4/PC7: TN v1 enum visible|unlisted|hidden
    freeShipping: false,
    seoTitle: seeded.seoTitle,
    seoDescription: seeded.seoDescription,
    tags: seeded.tags,
    appliedProfileId: null,
  };
}

function reducer(state, action) {
  switch (action.type) {
    case 'SET_FIELD':
      return { ...state, [action.field]: action.value };
    case 'APPLY_PROFILE':
      return {
        ...state,
        weight: String(action.profile.weight),
        width: String(action.profile.width),
        height: String(action.profile.height),
        depth: String(action.profile.depth),
        appliedProfileId: action.profile.id,
      };
    default:
      return state;
  }
}

export function useDraftFields(row) {
  const [state, dispatch] = useReducer(reducer, row, initDraftFields);

  const setField = useCallback((field, value) => dispatch({ type: 'SET_FIELD', field, value }), []);
  const applyProfile = useCallback((profile) => {
    if (!profile) return;
    dispatch({ type: 'APPLY_PROFILE', profile });
  }, []);

  return { ...state, setField, applyProfile };
}
