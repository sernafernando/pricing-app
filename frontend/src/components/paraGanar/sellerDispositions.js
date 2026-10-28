/** Catalog seller disposition — Activo / Excluido (TOP ranking). */

export const DISPOSITION_ACTIVE = 'active';
export const DISPOSITION_EXCLUDED = 'excluded';

/** Legacy labels still may appear until rewritten; treat as excluded. */
const LEGACY_EXCLUDED = new Set([
  'ignore_participant',
  'hide',
  'exclude_from_top',
  DISPOSITION_EXCLUDED,
]);

export const SELLER_DISPOSITIONS = [
  { value: DISPOSITION_ACTIVE, label: 'Activo' },
  { value: DISPOSITION_EXCLUDED, label: 'Excluido' },
];

export function normalizeDisposition(value) {
  if (!value || value === DISPOSITION_ACTIVE) return DISPOSITION_ACTIVE;
  if (LEGACY_EXCLUDED.has(value)) return DISPOSITION_EXCLUDED;
  return DISPOSITION_ACTIVE;
}

export function dispositionLabel(value) {
  const normalized = normalizeDisposition(value);
  const found = SELLER_DISPOSITIONS.find((item) => item.value === normalized);
  return found ? found.label : normalized;
}
