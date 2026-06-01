import { useState, useEffect, useCallback, useRef } from 'react';
import { useDebounce } from './useDebounce';
import { getRanking } from '../services/consultasService';

// Default sort: { columna, direccion } — matches Productos.jsx ordenColumnas shape.
const DEFAULT_SORT = [{ columna: 'dias_sin_venta', direccion: 'desc' }];
const DEFAULT_PAGE_SIZE = 50;
const DEFAULT_STOR_IDS = [1];

/**
 * Hook for the Consultas > Ranking page.
 * Manages filter state, multi-column sort state, and server-side pagination.
 *
 * Sort model: `ordenColumnas` is an ordered array of { columna, direccion } entries
 * — same shape as Productos.jsx, forwarded to consultasService as orden_campos/orden_direcciones.
 *
 * handleOrdenar(columna, event) — pass the raw click event; shift OR ctrl OR meta
 * activates multi-sort mode (add/cycle/remove). Plain click = single sort cycling.
 */
export function useConsultasRanking() {
  // Filter state
  const [marca, setMarcaRaw] = useState('');
  const [categoria, setCategoriaRaw] = useState('');
  const [pm, setPmRaw] = useState('');
  const [storIds, setStorIdsRaw] = useState(DEFAULT_STOR_IDS);
  const [incluirSinStock, setIncluirSinStockRaw] = useState(false);
  const [incluirCombos, setIncluirCombosRaw] = useState(false);
  // Free-text search (código / descripción)
  const [q, setQRaw] = useState('');

  // Debounce free-text search only (marca is a dropdown — no debounce needed)
  const debouncedQ = useDebounce(q, 400);

  // Multi-column sort state: ordered array of { columna, direccion }
  const [ordenColumnas, setOrdenColumnas] = useState(DEFAULT_SORT);

  // Pagination state
  const [page, setPage] = useState(1);
  const [pageSize, setPageSizeRaw] = useState(DEFAULT_PAGE_SIZE);

  // Data state
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Prevent duplicate in-flight requests
  const abortRef = useRef(null);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Filter setters that also reset page to 1 in the same render batch.
  const setMarca = useCallback((v) => { setMarcaRaw(v); setPage(1); }, []);
  const setCategoria = useCallback((v) => { setCategoriaRaw(v); setPage(1); }, []);
  const setPm = useCallback((v) => { setPmRaw(v); setPage(1); }, []);
  const setQ = useCallback((v) => { setQRaw(v); setPage(1); }, []);
  const setStorIds = useCallback((v) => { setStorIdsRaw(v); setPage(1); }, []);
  const setIncluirSinStock = useCallback((v) => { setIncluirSinStockRaw(v); setPage(1); }, []);
  const setIncluirCombos = useCallback((v) => { setIncluirCombosRaw(v); setPage(1); }, []);
  const setPageSize = useCallback((v) => { setPageSizeRaw(v); setPage(1); }, []);

  const fetchData = useCallback(async (fetchPage) => {
    if (abortRef.current) {
      abortRef.current.cancelled = true;
    }
    const token = { cancelled: false };
    abortRef.current = token;

    setLoading(true);
    setError(null);

    try {
      const result = await getRanking({
        page: fetchPage,
        page_size: pageSize,
        sort: ordenColumnas,
        marca: marca || null,
        categoria: categoria || null,
        pm: pm || null,
        stor_ids: storIds,
        incluir_sin_stock: incluirSinStock,
        incluir_combos: incluirCombos,
        q: debouncedQ || null,
      });

      if (token.cancelled) return;

      setItems(result.items);
      setTotal(result.total);
    } catch (err) {
      if (token.cancelled) return;
      const message =
        err?.response?.data?.detail || err?.message || 'Error al cargar el ranking';
      setError(message);
    } finally {
      if (!token.cancelled) {
        setLoading(false);
      }
    }
  }, [pageSize, ordenColumnas, marca, categoria, pm, storIds, incluirSinStock, incluirCombos, debouncedQ]);

  useEffect(() => {
    fetchData(page);
  }, [fetchData, page]);

  /**
   * handleOrdenar(columna, event) — mirrors Productos.jsx handleOrdenar exactly,
   * but accepts shift OR ctrl OR meta as the multi-sort modifier.
   *
   * Plain click: single sort, cycling asc→desc→off
   * Multi-modifier+click: add/cycle/remove in the multi-sort array
   */
  const handleOrdenar = useCallback((columna, event) => {
    const multiPressed = event?.shiftKey || event?.ctrlKey || event?.metaKey;

    if (!multiPressed) {
      // Plain click: single sort cycling
      setOrdenColumnas((prev) => {
        const existente = prev.find((o) => o.columna === columna);
        if (existente) {
          if (existente.direccion === 'asc') {
            return [{ columna, direccion: 'desc' }];
          } else {
            return [];
          }
        } else {
          return [{ columna, direccion: 'asc' }];
        }
      });
    } else {
      // Multi-modifier: add/cycle/remove
      setOrdenColumnas((prev) => {
        const existente = prev.find((o) => o.columna === columna);
        if (existente) {
          if (existente.direccion === 'asc') {
            return prev.map((o) =>
              o.columna === columna ? { ...o, direccion: 'desc' } : o
            );
          } else {
            return prev.filter((o) => o.columna !== columna);
          }
        } else {
          return [...prev, { columna, direccion: 'asc' }];
        }
      });
    }
    setPage(1);
  }, []);

  /**
   * getIconoOrden(columna) — returns '↕' / '▲' / '▼' exactly like Productos.jsx.
   */
  const getIconoOrden = useCallback((columna) => {
    const orden = ordenColumnas.find((o) => o.columna === columna);
    if (!orden) return '↕';
    return orden.direccion === 'asc' ? '▲' : '▼';
  }, [ordenColumnas]);

  /**
   * getNumeroOrden(columna) — returns 1-based priority or null.
   */
  const getNumeroOrden = useCallback((columna) => {
    const index = ordenColumnas.findIndex((o) => o.columna === columna);
    return index >= 0 ? index + 1 : null;
  }, [ordenColumnas]);

  const goToPage = useCallback((p) => {
    const clamped = Math.max(1, Math.min(p, totalPages));
    setPage(clamped);
  }, [totalPages]);

  const refresh = useCallback(() => {
    fetchData(page);
  }, [fetchData, page]);

  return {
    // Data
    items,
    total,
    loading,
    error,

    // Filters
    marca,
    setMarca,
    categoria,
    setCategoria,
    pm,
    setPm,
    q,
    setQ,
    storIds,
    setStorIds,
    incluirSinStock,
    setIncluirSinStock,
    incluirCombos,
    setIncluirCombos,

    // Sort (multi-column — Productos.jsx shape)
    ordenColumnas,
    handleOrdenar,
    getIconoOrden,
    getNumeroOrden,

    // Pagination
    page,
    pageSize,
    setPageSize,
    totalPages,
    goToPage,

    // Actions
    refresh,
  };
}
