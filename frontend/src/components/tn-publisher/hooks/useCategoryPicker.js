/**
 * useCategoryPicker — category suggestion (embedder top-N) + NAME search
 * (`GET /categorias?q=`). Moved verbatim out of the pre-decomposition
 * `TnPublishModal.jsx` (2 of the 4 inline `api` calls that file made).
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
  // raw-id input. Empty/short queries clear the results without a request.
  useEffect(() => {
    const q = debouncedCategoryQuery.trim();
    if (!isOpen || q.length < 2) {
      setSearchResults([]);
      setSearching(false);
      setSearchError(null);
      return;
    }
    let cancelled = false;
    async function search() {
      setSearching(true);
      setSearchError(null);
      try {
        const response = await api.get('/tienda-nube-reconcile/categorias', {
          params: { q, limit: 20 },
        });
        if (!cancelled) setSearchResults(Array.isArray(response.data) ? response.data : []);
      } catch (err) {
        if (!cancelled) {
          setSearchResults([]);
          setSearchError(err?.response?.data?.error?.message || err?.message || 'No se pudieron buscar categorías');
        }
      } finally {
        if (!cancelled) setSearching(false);
      }
    }
    search();
    return () => {
      cancelled = true;
    };
  }, [debouncedCategoryQuery, isOpen]);

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
  };
}
