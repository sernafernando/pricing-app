import { useState, useEffect, useCallback, useRef } from 'react';
import { useDebounce } from './useDebounce';
import { getRanking } from '../services/consultasService';

const DEFAULT_SORT = [{ campo: 'dias_sin_venta', dir: 'desc' }];
const DEFAULT_PAGE_SIZE = 50;
const DEFAULT_STOR_IDS = [1];
const DEFAULT_VENTANA_DIAS = 90;

/**
 * Hook for the Consultas > Ranking page.
 * Manages filter state, multi-column sort state, and server-side pagination.
 *
 * Sort model: `sort` is an ordered array of { campo, dir } entries.
 * - Plain click on a header column: set that column as the sole primary sort,
 *   toggling dir if it was already the sole sort; otherwise set to desc.
 * - Shift+click: add/toggle a column in the sort list as a secondary/tertiary
 *   sort key. If the column is already in the list, toggle its dir; if not,
 *   append it with 'desc'. Clicking without shift always resets to that column alone.
 *
 * Fetch strategy: a single effect watches (fetchData, page). fetchData is
 * memoised on filter/sort values. When a filter changes, filter setters also
 * reset page to 1 via the `pageRef` trick so that the next render has both
 * the new fetchData AND page=1 simultaneously — exactly one request fires.
 */
export function useConsultasRanking() {
  // Filter state
  const [marca, setMarcaRaw] = useState('');
  const [categoria, setCategoriaRaw] = useState('');
  const [pm, setPmRaw] = useState('');
  const [storIds, setStorIdsRaw] = useState(DEFAULT_STOR_IDS);
  const [ventanaDias, setVentanaDiasRaw] = useState(DEFAULT_VENTANA_DIAS);
  const [incluirSinStock, setIncluirSinStockRaw] = useState(false);
  const [incluirCombos, setIncluirCombosRaw] = useState(false);

  // Debounce text filters
  const debouncedMarca = useDebounce(marca, 400);
  const debouncedCategoria = useDebounce(categoria, 400);

  // Multi-column sort state: ordered array of { campo, dir }
  const [sort, setSortRaw] = useState(DEFAULT_SORT);

  // Pagination state
  const [page, setPage] = useState(1);
  const [pageSize] = useState(DEFAULT_PAGE_SIZE);

  // Data state
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Prevent duplicate in-flight requests
  const abortRef = useRef(null);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Filter/sort setters that also reset page to 1 in the same render batch.
  const setMarca = useCallback((v) => { setMarcaRaw(v); setPage(1); }, []);
  const setCategoria = useCallback((v) => { setCategoriaRaw(v); setPage(1); }, []);
  const setPm = useCallback((v) => { setPmRaw(v); setPage(1); }, []);
  const setStorIds = useCallback((v) => { setStorIdsRaw(v); setPage(1); }, []);
  const setVentanaDias = useCallback((v) => { setVentanaDiasRaw(v); setPage(1); }, []);
  const setIncluirSinStock = useCallback((v) => { setIncluirSinStockRaw(v); setPage(1); }, []);
  const setIncluirCombos = useCallback((v) => { setIncluirCombosRaw(v); setPage(1); }, []);

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
        sort,
        marca: debouncedMarca || null,
        categoria: debouncedCategoria || null,
        pm: pm || null,
        stor_ids: storIds,
        ventana_dias: ventanaDias,
        incluir_sin_stock: incluirSinStock,
        incluir_combos: incluirCombos,
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
  }, [pageSize, sort, debouncedMarca, debouncedCategoria, pm, storIds, ventanaDias, incluirSinStock, incluirCombos]);

  useEffect(() => {
    fetchData(page);
  }, [fetchData, page]);

  /**
   * Toggle sort for a column.
   * - shiftKey=false: set as sole sort, toggling dir if already sole; otherwise desc.
   * - shiftKey=true: add/toggle column in the multi-sort list.
   *   If already present, toggle its dir. If not present, append with 'desc'.
   */
  const toggleSort = useCallback((campo, shiftKey = false) => {
    setSortRaw((prev) => {
      if (shiftKey) {
        const idx = prev.findIndex((s) => s.campo === campo);
        if (idx === -1) {
          return [...prev, { campo, dir: 'desc' }];
        }
        return prev.map((s, i) =>
          i === idx ? { campo, dir: s.dir === 'desc' ? 'asc' : 'desc' } : s
        );
      }
      // Plain click: reset to single sort
      const existing = prev.find((s) => s.campo === campo);
      if (prev.length === 1 && existing) {
        return [{ campo, dir: existing.dir === 'desc' ? 'asc' : 'desc' }];
      }
      return [{ campo, dir: 'desc' }];
    });
    setPage(1);
  }, []);

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
    storIds,
    setStorIds,
    ventanaDias,
    setVentanaDias,
    incluirSinStock,
    setIncluirSinStock,
    incluirCombos,
    setIncluirCombos,

    // Sort (multi-column)
    sort,
    toggleSort,

    // Pagination
    page,
    pageSize,
    totalPages,
    goToPage,

    // Actions
    refresh,
  };
}
