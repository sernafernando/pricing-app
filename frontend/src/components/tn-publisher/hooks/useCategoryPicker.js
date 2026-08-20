/**
 * useCategoryPicker — category suggestion (embedder top-N) + NAME search
 * (`GET /categorias?q=`). Moved verbatim out of the pre-decomposition
 * `TnPublishModal.jsx` (2 of the 4 inline `api` calls that file made).
 *
 * tn-categorias-descubribles fix (defect 1): the picker used to be
 * search-only — a blank query never fired a request, so an operator who
 * didn't already know the category vocabulary had no way to see what
 * existed. `GET /categorias` now returns a bounded first page for a blank
 * `q` (backend contract change), and this hook fetches that page as soon
 * as the modal opens ("browse"), then re-fetches with the typed `q` once
 * the operator starts searching — same debounce, same endpoint, one
 * request path. `catalogEmpty` distinguishes "the unfiltered listing came
 * back empty" (never synced) from "my query matched nothing" — the
 * cheapest honest signal, no second endpoint needed.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useDebounce } from '../../../hooks/useDebounce';
import api from '../../../services/api';

function buildCategoryText(row) {
  if (!row) return '';
  return [row.categoria, row.subcategoria].filter(Boolean).join(' ').trim();
}

export function useCategoryPicker({ isOpen, ean, row }) {
  const [loadingSuggestion, setLoadingSuggestion] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [selectedCategory, setSelectedCategory] = useState(null);

  const [categoryQuery, setCategoryQuery] = useState('');
  const debouncedCategoryQuery = useDebounce(categoryQuery, 300);
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(null);
  // null until the first unfiltered (blank-q) listing resolves; then true
  // only when that listing came back empty — the "never synced" signal.
  const [catalogEmpty, setCatalogEmpty] = useState(null);
  const [syncingCategories, setSyncingCategories] = useState(false);
  const [syncResult, setSyncResult] = useState(null);
  const [syncError, setSyncError] = useState(null);
  const [syncRefreshToken, setSyncRefreshToken] = useState(0);

  // One-shot load: only the category suggestion needs a fetch — the product
  // fields (ml_title/ml_desc/images/categoria) already arrived on `row`.
  // Never re-fetches on re-render — only when `ean` changes.
  useEffect(() => {
    if (!isOpen || !ean) return;
    let cancelled = false;

    async function load() {
      setLoadingSuggestion(true);
      setLoadError(null);
      try {
        const categoryText = buildCategoryText(row);
        if (categoryText) {
          const sugResponse = await api.post('/tienda-nube-reconcile/categoria-sugerida', {
            category_text: categoryText,
            top_n: 5,
          });
          if (cancelled) return;
          const list = sugResponse.data?.suggestions || [];
          setSuggestions(list);
          const top = sugResponse.data?.top;
          setSelectedCategory(top ? { id: top.tn_category_id, path: top.category_path_text } : null);
        } else {
          setSuggestions([]);
          setSelectedCategory(null);
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(err?.response?.data?.error?.message || err?.message || 'No se pudo sugerir una categoría');
        }
      } finally {
        if (!cancelled) setLoadingSuggestion(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, ean]);

  // Debounced category NAME search — the manual path that replaces the old
  // raw-id input, plus the blank-query "browse" load. A 1-char query still
  // clears without a request (unchanged); a genuinely blank query now
  // fetches the same bounded listing the picker shows on open, instead of
  // clearing — that's what lets a re-cleared search box keep showing the
  // catalog rather than going blank.
  useEffect(() => {
    const q = debouncedCategoryQuery.trim();
    if (!isOpen) {
      setSearchResults([]);
      setSearching(false);
      setSearchError(null);
      return;
    }
    if (q.length === 1) {
      setSearchResults([]);
      setSearching(false);
      setSearchError(null);
      return;
    }
    let cancelled = false;
    async function loadOrSearch() {
      setSearching(true);
      setSearchError(null);
      try {
        const params = q ? { q, limit: 20 } : { limit: 20 };
        const response = await api.get('/tienda-nube-reconcile/categorias', { params });
        if (cancelled) return;
        const results = Array.isArray(response.data) ? response.data : [];
        setSearchResults(results);
        if (!q) setCatalogEmpty(results.length === 0);
      } catch (err) {
        if (!cancelled) {
          setSearchResults([]);
          setSearchError(err?.response?.data?.error?.message || err?.message || 'No se pudieron buscar categorías');
        }
      } finally {
        if (!cancelled) setSearching(false);
      }
    }
    loadOrSearch();
    return () => {
      cancelled = true;
    };
  }, [debouncedCategoryQuery, isOpen, syncRefreshToken]);

  // Operator-triggered refresh of the category catalog (wires the
  // already-implemented, already-tested `POST /categorias/sync`, which
  // previously had no frontend caller). Bumps `syncRefreshToken` on
  // success so the blank-query listing above re-fetches and `catalogEmpty`
  // reflects the just-synced catalog.
  const syncCategories = useCallback(async () => {
    setSyncingCategories(true);
    setSyncError(null);
    setSyncResult(null);
    try {
      const response = await api.post('/tienda-nube-reconcile/categorias/sync');
      setSyncResult(response.data);
      setSyncRefreshToken((t) => t + 1);
    } catch (err) {
      setSyncError(
        err?.response?.data?.error?.message || err?.message || 'No se pudo sincronizar el catálogo de categorías'
      );
    } finally {
      setSyncingCategories(false);
    }
  }, []);

  const pickSearchResult = useCallback((result) => {
    setSelectedCategory({ id: result.tn_category_id, path: result.category_path });
    setCategoryQuery('');
    setSearchResults([]);
  }, []);

  // True when the current selection came from the search box (it's not one
  // of the embedder suggestions) — rendered as its own checked option so the
  // operator always SEES what is selected.
  const selectionOutsideSuggestions = useMemo(
    () => selectedCategory != null && !suggestions.some((s) => s.tn_category_id === selectedCategory.id),
    [selectedCategory, suggestions]
  );

  return {
    loadingSuggestion,
    loadError,
    suggestions,
    selectedCategory,
    setSelectedCategory,
    categoryQuery,
    setCategoryQuery,
    debouncedCategoryQuery,
    searchResults,
    searching,
    searchError,
    pickSearchResult,
    selectionOutsideSuggestions,
    catalogEmpty,
    syncingCategories,
    syncResult,
    syncError,
    syncCategories,
  };
}
