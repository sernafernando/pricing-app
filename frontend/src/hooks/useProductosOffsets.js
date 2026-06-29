import { useState, useEffect } from 'react';
import api from '../services/api';

/**
 * Manages profit-offset state and markup-with-offset calculation for the Productos page.
 * This is a leaf hook: no injected deps, owns its own endpoints.
 */
export function useProductosOffsets() {
  const [offsetsVigentes, setOffsetsVigentes] = useState([]);
  const [offsetGrupoFiltros, setOffsetGrupoFiltros] = useState({}); // { grupo_id: [filtros] }
  const [tipoCambioUSD, setTipoCambioUSD] = useState(null);

  const cargarOffsetsVigentes = async () => {
    try {
      const [offsetsRes, tcRes] = await Promise.all([
        api.get('/offsets-ganancia', { params: { solo_vigentes: true } }),
        api.get('/tipo-cambio-hoy')
      ]);

      const tc = tcRes.data.tipo_cambio || 1000;
      setTipoCambioUSD(tc);

      // Only offsets without limits AND of type porcentaje_costo or monto_por_unidad (NOT monto_fijo)
      const sinLimite = (offsetsRes.data || []).filter(o =>
        !o.max_unidades && !o.max_monto_usd &&
        (o.tipo_offset === 'porcentaje_costo' || o.tipo_offset === 'monto_por_unidad')
      );
      setOffsetsVigentes(sinLimite);

      // For group offsets, fetch the group filters
      const grupoIds = [...new Set(sinLimite.filter(o => o.grupo_id).map(o => o.grupo_id))];
      if (grupoIds.length > 0) {
        const filtrosPromises = grupoIds.map(gId =>
          api.get(`/offset-grupos/${gId}/filtros`)
        );
        const filtrosRes = await Promise.all(filtrosPromises);
        const filtrosMap = {};
        grupoIds.forEach((gId, idx) => {
          filtrosMap[gId] = filtrosRes[idx].data || [];
        });
        setOffsetGrupoFiltros(filtrosMap);
      }
    } catch {
      // Silent error — does not affect main functionality
    }
  };

  // Bootstrap on mount — run once only
  useEffect(() => { cargarOffsetsVigentes(); }, []);

  const getMarkupColor = (markup) => {
    if (markup === null || markup === undefined) return 'var(--text-tertiary)';
    if (markup < 0) return 'var(--error)';
    if (markup < 1) return 'var(--warning)';
    return 'var(--success)';
  };

  /**
   * Calculates markup with offset applied for a product.
   * Returns null if no applicable offsets or calculation is not possible.
   */
  const calcularMarkupConOffset = (producto) => {
    if (!producto.markup && producto.markup !== 0) return null;
    if (!producto.costo || producto.costo <= 0) return null;
    if (offsetsVigentes.length === 0) return null;

    // Convert cost to ARS if needed
    const costoARS = producto.moneda_costo === 'USD' && tipoCambioUSD
      ? producto.costo * tipoCambioUSD
      : producto.costo;

    // Find offsets that apply to this product
    let totalDescuentoCosto = 0;
    let tieneOffset = false;

    for (const offset of offsetsVigentes) {
      let aplica = false;

      if (offset.grupo_id) {
        // Group offset: check against group filters
        const filtros = offsetGrupoFiltros[offset.grupo_id] || [];
        if (filtros.length > 0) {
          // Matches if it satisfies AT LEAST ONE filter
          aplica = filtros.some(f => {
            let match = true;
            if (f.marca && f.marca !== producto.marca) match = false;
            if (f.categoria && f.categoria !== producto.categoria) match = false;
            if (f.subcategoria_id && f.subcategoria_id !== producto.subcategoria_id) match = false;
            if (f.item_id && f.item_id !== producto.item_id) match = false;
            return match;
          });
        }
      } else {
        // Individual offset: match by level
        if (offset.item_id && offset.item_id === producto.item_id) aplica = true;
        else if (offset.subcategoria_id && offset.subcategoria_id === producto.subcategoria_id) aplica = true;
        else if (offset.categoria && offset.categoria === producto.categoria) aplica = true;
        else if (offset.marca && offset.marca === producto.marca) aplica = true;
      }

      if (!aplica) continue;

      tieneOffset = true;

      if (offset.tipo_offset === 'porcentaje_costo') {
        totalDescuentoCosto += costoARS * ((offset.porcentaje || 0) / 100);
      } else if (offset.tipo_offset === 'monto_por_unidad') {
        const montoARS = offset.moneda === 'USD' && tipoCambioUSD
          ? (offset.monto || 0) * tipoCambioUSD
          : (offset.monto || 0);
        totalDescuentoCosto += montoARS;
      }
    }

    if (!tieneOffset || totalDescuentoCosto === 0) return null;

    const costoAjustado = costoARS - totalDescuentoCosto;
    if (costoAjustado <= 0) return null;

    // Recalculate markup: limpio = (markup/100 + 1) * originalCost
    // new_markup = (limpio / adjustedCost - 1) * 100
    const markupDecimal = producto.markup / 100;
    const limpio = (markupDecimal + 1) * costoARS;
    const markupNuevo = ((limpio / costoAjustado) - 1) * 100;

    return Math.round(markupNuevo * 100) / 100;
  };

  return {
    offsetsVigentes,
    offsetGrupoFiltros,
    tipoCambioUSD,
    calcularMarkupConOffset,
    getMarkupColor,
  };
}
