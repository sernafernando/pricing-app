import { useState, useEffect, useCallback, useRef } from 'react';
import { useDebounce } from './useDebounce';
import { getRanking } from '../services/consultasService';

const DEFAULT_SORT_BY = 'dias_sin_venta';
const DEFAULT_SORT_DIR = 'desc';
const DEFAULT_PAGE_SIZE = 50;
const DEFAULT_STOR_IDS = [1];
const DEFAULT_VENTANA_DIAS = 90;

/**
 * Hook for the Consultas > Ranking page.
 * Manages filter state, sort state, and server-side pagination.
 *
 * Fetch strategy: a single effect watches (fetchData, page). fetchData is
 * memoised on filter/sort values. When a filter changes, filter setters also
 * reset page to 1 via the `pageRef` trick so that the next render has both
 * the new fetchData AND page=1 simultaneously — exactly one request fires.
 * Changing only the page (pagination controls) also fires exactly one request.
 */
export function useConsultasRanking() {
  // Filter state
  const [marca, setMarcaRaw] = useState('');
  const [categoria, setCategoriaRaw] = useState('');
  const [pm, setPmRaw] = useState('');
  const [storIds, setStorIdsRaw] = useState(DEFAULT_STOR_IDS);
  const [ventanaDias, setVentanaDiasRaw] = useState(DEFAULT_VENTANA_DIAS);

  // Debounce text filters
  const debouncedMarca = useDebounce(marca, 400);
  const debouncedCategoria = useDebounce(categoria, 400);

  // Sort state
  const [sortBy, setSortByRaw] = useState(DEFAULT_SORT_BY);
  const [sortDir, setSortDirRaw] = useState(DEFAULT_SORT_DIR);

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
  // This collapses the "filter changed + page reset" into a single state update
  // so only one fetchData reference is created and one fetch fires.
  const setMarca = useCallback((v) => { setMarcaRaw(v); setPage(1); }, []);
  const setCategoria = useCallback((v) => { setCategoriaRaw(v); setPage(1); }, []);
  const setPm = useCallback((v) => { setPmRaw(v); setPage(1); }, []);
  const setStorIds = useCallback((v) => { setStorIdsRaw(v); setPage(1); }, []);
  const setVentanaDias = useCallback((v) => { setVentanaDiasRaw(v); setPage(1); }, []);

  const fetchData = useCallback(async (fetchPage) => {
    // Cancel previous request if still pending
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
        sort_by: sortBy,
        sort_dir: sortDir,
        marca: debouncedMarca || null,
        categoria: debouncedCategoria || null,
        pm: pm || null,
        stor_ids: storIds,
        ventana_dias: ventanaDias,
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
  }, [pageSize, sortBy, sortDir, debouncedMarca, debouncedCategoria, pm, storIds, ventanaDias]);

  // Single fetch effect: fires when filters/sort change (new fetchData) OR when
  // the user navigates pages. Because filter setters always reset page to 1 in
  // the same batch, React batches both state updates and this effect runs once
  // with the new fetchData and page=1.
  useEffect(() => {
    fetchData(page);
  }, [fetchData, page]);

  // Toggle sort: same column → flip dir; different column → desc.
  // Also resets page to 1 so the combined state change produces one fetch.
  const toggleSort = useCallback((column) => {
    if (column === sortBy) {
      setSortDirRaw((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortByRaw(column);
      setSortDirRaw('desc');
    }
    setPage(1);
  }, [sortBy]);

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

    // Sort
    sortBy,
    sortDir,
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
