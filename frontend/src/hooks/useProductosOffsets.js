import { useState, useEffect } from 'react';
import api from '../services/api';
import { cargarOffsetsVigentes, costoConOffset, markupConOffset } from '../utils/offsetsGanancia';

/**
 * Markup -> color thresholds (canonical, shared across the app): negative is
 * error, [0,1) is warning, >=1 is success, null/undefined is neutral. Pure
 * function of `markup` only — exported standalone so callers that just need
 * the color (e.g. MlaPromocionesPanel) don't have to mount the whole
 * `useProductosOffsets` hook (and its offsets/tipo-cambio API calls) just to
 * reach it.
 */
export function getMarkupColor(markup) {
  if (markup === null || markup === undefined) return 'var(--text-tertiary)';
  if (markup < 0) return 'var(--error)';
  if (markup < 1) return 'var(--warning)';
  return 'var(--success)';
}

/**
 * `record()` keys whose backend value is a RAW DECIMAL RATIO (e.g. 0.15)
 * instead of an already-scaled percent (e.g. 15). `mejor_oferta` is the only
 * one today — see `costo_ppp_service.py`. Centralised here so callers never
 * need to know which keys need the `* 100` conversion.
 */
const PPP_RATIO_KEYS = new Set(['mejor_oferta']);

/**
 * Formats a PPP markup percent for display. `markupKey` selects whether the
 * raw `markups[key]` value is already a percent or a raw ratio that still
 * needs `* 100` (see `PPP_RATIO_KEYS`). Returns `null` when there is nothing
 * to render (caller decides the "no data" fallback).
 */
export function formatPppMonto(value, markupKey) {
  if (value === null || value === undefined) return null;
  const percent = PPP_RATIO_KEYS.has(markupKey) ? value * 100 : value;
  return `${percent.toFixed(2)}%`;
}

/** Formats a PPP source date as dd/mm/aa — always shown, no relative wording. */
export function formatPppFecha(fecha) {
  if (!fecha) return null;
  const d = new Date(fecha);
  if (Number.isNaN(d.getTime())) return null;
  const dd = String(d.getUTCDate()).padStart(2, '0');
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
  const yy = String(d.getUTCFullYear()).slice(-2);
  return `${dd}/${mm}/${yy}`;
}

/**
 * Manages profit-offset state and markup-with-offset calculation for the Productos page.
 * This is a leaf hook: no injected deps, owns its own endpoints.
 */
export function useProductosOffsets() {
  const [offsetsVigentes, setOffsetsVigentes] = useState([]);
  const [offsetGrupoFiltros, setOffsetGrupoFiltros] = useState({}); // { grupo_id: [filtros] }
  const [tipoCambioUSD, setTipoCambioUSD] = useState(null);

  const cargarOffsets = async () => {
    try {
      const loaded = await cargarOffsetsVigentes({
        offsets: () => api.get('/offsets-ganancia', { params: { solo_vigentes: true } }),
        tipoCambio: () => api.get('/tipo-cambio-hoy'),
        grupoFiltros: (gId) => api.get(`/offset-grupos/${gId}/filtros`),
      });
      setTipoCambioUSD(loaded.tipoCambio);
      setOffsetsVigentes(loaded.offsets);
      setOffsetGrupoFiltros(loaded.grupoFiltros);
    } catch {
      // Silent error — does not affect main functionality
    }
  };

  // Bootstrap on mount — run once only
  useEffect(() => { cargarOffsets(); }, []);

  /**
   * Calculates markup with offset applied for a product.
   * Returns null if no applicable offsets or calculation is not possible.
   * The logic lives in utils/offsetsGanancia (shared with the Publicaciones ML Precios tab).
   */
  const calcularMarkupConOffset = (producto) =>
    markupConOffset(
      producto.markup,
      costoConOffset(producto, { offsets: offsetsVigentes, grupoFiltros: offsetGrupoFiltros, tipoCambio: tipoCambioUSD }),
    );

  return {
    offsetsVigentes,
    offsetGrupoFiltros,
    tipoCambioUSD,
    calcularMarkupConOffset,
    getMarkupColor,
  };
}
