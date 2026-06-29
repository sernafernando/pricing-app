/**
 * metricsColors.js
 *
 * Single source of truth for chart segment colors in the RMA Métricas dashboard.
 *
 * Maps RmaSeguimientoOpcion.color name strings to hex values from the Tesla Design
 * System tokens (design-tokens.css, --color-* variables).
 * Provides a deterministic fallback palette for dimensions with no opcion color
 * (e.g. proveedor, which is denormalized and has color=null on all buckets).
 *
 * DECISION: no raw hex literals outside this file — callers must use this module.
 */

/**
 * Backend color name → hex.
 * Mirrors --color-* CSS custom properties from design-tokens.css.
 * Only these names are stored in rma_seguimiento_opciones.color.
 */
const COLOR_NAME_TO_HEX = {
  blue:   '#3b82f6',
  green:  '#22c55e',
  red:    '#ef4444',
  orange: '#f59e0b',
  yellow: '#eab308',
  gray:   '#64748b',
  purple: '#a855f7',
  teal:   '#14b8a6',
};

/**
 * Fallback palette for segments with no backend color (proveedor dimension).
 * Ordered to maximise visual separation between adjacent segments.
 * All values match --cf-accent-* and --color-* tokens.
 */
const FALLBACK_PALETTE = [
  '#3b82f6', // blue
  '#22c55e', // green
  '#f59e0b', // orange
  '#a855f7', // purple
  '#14b8a6', // teal
  '#ef4444', // red
  '#eab308', // yellow
  '#64748b', // gray
];

/** "Sin clasificar" sentinel — neutral gray (--color-gray) */
const SIN_CLASIFICAR_COLOR = '#64748b';

/** "Otros" sentinel — lighter slate for the rolled-up tail */
const OTROS_COLOR = '#94a3b8';

/**
 * Color for percentage labels rendered directly on colored segments.
 * Exported so callers (e.g. ChartDonut) never hardcode raw hex.
 */
export const SEGMENT_LABEL_COLOR = '#ffffff';

/**
 * Resolve the fill color for a single chart segment.
 *
 * Resolution order:
 *   1. Sentinel valores ("Sin clasificar", "Otros") → fixed color.
 *   2. Backend color name present and mapped → hex from COLOR_NAME_TO_HEX.
 *   3. Fallback palette rotation by index (proveedor and any unmapped names).
 *
 * @param {{ valor: string, color: string|null }} bucket
 * @param {number} index  Zero-based position in the rendered buckets array.
 * @returns {string} hex color string
 */
export function getColorForBucket(bucket, index) {
  if (bucket.valor === 'Sin clasificar') return SIN_CLASIFICAR_COLOR;
  if (bucket.valor === 'Otros') return OTROS_COLOR;

  if (bucket.color && COLOR_NAME_TO_HEX[bucket.color]) {
    return COLOR_NAME_TO_HEX[bucket.color];
  }

  return FALLBACK_PALETTE[index % FALLBACK_PALETTE.length];
}

