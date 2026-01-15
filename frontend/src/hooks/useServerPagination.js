import { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { useDebounce } from './useDebounce';

const API_URL = 'https://pricing.gaussonline.com.ar/api';

/**
 * Hook para paginación server-side con soporte para scroll infinito y paginación clásica.
 * 
 * @param {Object} config - Configuración del hook
 * @param {string} config.endpoint - Endpoint de la API (ej: '/ventas-fuera-ml/operaciones')
 * @param {string} config.countEndpoint - Endpoint para contar total (ej: '/ventas-fuera-ml/operaciones/count')
 * @param {Object} config.filters - Filtros a aplicar (fecha_desde, fecha_hasta, marca, etc.)
 * @param {number} config.pageSize - Tamaño de página (default: 1000)
 * @param {boolean} config.enabled - Si está habilitado (default: true)
 * @param {Function} config.onDataLoaded - Callback cuando se cargan datos
 * 
 * @returns {Object} Estado y funciones de paginación
 */
export function useServerPagination({
  endpoint,
  countEndpoint = null,
  filters = {},
  pageSize = 1000,
  enabled = true,
  onDataLoaded = null
}) {
  // Estado
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [paginationMode, setPaginationMode] = useState('infinite'); // 'infinite' o 'classic'
  
  // Búsqueda
  const [searchTerm, setSearchTerm] = useState('');
  const debouncedSearch = useDebounce(searchTerm, 500);

  // Cache de páginas (para paginación clásica)
  const cacheRef = useRef({});
  
  // Ref para evitar requests duplicados
  const loadingRef = useRef(false);

  // Ref para el scroll container (scroll infinito)
  const scrollContainerRef = useRef(null);

  /**
   * Genera la clave de cache basada en filtros y búsqueda
   */
  const getCacheKey = useCallback((page) => {
    const filterStr = JSON.stringify({ ...filters, search: debouncedSearch });
    return `${endpoint}-${page}-${filterStr}`;
  }, [endpoint, filters, debouncedSearch]);

  /**
   * Invalida todo el cache (útil después de editar)
   */
  const invalidateCache = useCallback(() => {
    cacheRef.current = {};
    setData([]);
    setCurrentPage(1);
    setTotalItems(0);
    setHasMore(true);
  }, []);

  /**
   * Carga el total de items (para paginación clásica)
   */
  const loadTotalCount = useCallback(async () => {
    if (!countEndpoint || !enabled) return;

    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };
      
      const params = {
        ...filters,
        ...(debouncedSearch && { search: debouncedSearch })
      };

      const response = await axios.get(`${API_URL}${countEndpoint}`, { params, headers });
      setTotalItems(response.data.total || 0);
    } catch (err) {
      console.error('Error cargando total:', err);
    }
  }, [countEndpoint, filters, debouncedSearch, enabled]);

  /**
   * Carga una página específica
   */
  const loadPage = useCallback(async (page, append = false) => {
    if (loadingRef.current || !enabled) return;

    // Verificar cache en modo clásico
    if (paginationMode === 'classic') {
      const cacheKey = getCacheKey(page);
      if (cacheRef.current[cacheKey]) {
        setData(cacheRef.current[cacheKey]);
        setCurrentPage(page);
        return;
      }
    }

    loadingRef.current = true;
    setLoading(true);
    setError(null);

    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };
      
      const offset = (page - 1) * pageSize;
      const params = {
        ...filters,
        limit: pageSize,
        offset,
        ...(debouncedSearch && { search: debouncedSearch })
      };

      const response = await axios.get(`${API_URL}${endpoint}`, { params, headers });
      const newData = response.data || [];

      // Actualizar data
      if (append && paginationMode === 'infinite') {
        // Scroll infinito: agregar al final
        setData(prev => [...prev, ...newData]);
      } else {
        // Paginación clásica: reemplazar
        setData(newData);
        
        // Guardar en cache
        const cacheKey = getCacheKey(page);
        cacheRef.current[cacheKey] = newData;
      }

      setCurrentPage(page);
      setHasMore(newData.length === pageSize);

      // Callback
      if (onDataLoaded) {
        onDataLoaded(newData);
      }

      // Warning si hay demasiados items cargados
      if (paginationMode === 'infinite' && data.length + newData.length > 10000) {
        console.warn(`⚠️  ${data.length + newData.length} items cargados. Considera usar paginación clásica para mejor performance.`);
      }

    } catch (err) {
      console.error('Error cargando página:', err);
      setError(err.message || 'Error al cargar datos');
    } finally {
      setLoading(false);
      loadingRef.current = false;
    }
  }, [endpoint, filters, pageSize, debouncedSearch, enabled, paginationMode, getCacheKey, data.length, onDataLoaded]);

  /**
   * Carga la siguiente página (scroll infinito)
   */
  const loadNextPage = useCallback(() => {
    if (!hasMore || loading || paginationMode !== 'infinite') return;
    loadPage(currentPage + 1, true);
  }, [hasMore, loading, currentPage, loadPage, paginationMode]);

  /**
   * Va a una página específica (paginación clásica)
   */
  const goToPage = useCallback((page) => {
    if (paginationMode !== 'classic') return;
    
    const totalPages = Math.ceil(totalItems / pageSize);
    if (page < 1 || page > totalPages) return;
    
    loadPage(page, false);
  }, [paginationMode, totalItems, pageSize, loadPage]);

  /**
   * Handler para scroll (detecta cuando llegar al final)
   */
  const handleScroll = useCallback((e) => {
    if (paginationMode !== 'infinite' || !hasMore || loading) return;

    const target = e.target;
    const scrollPosition = target.scrollTop + target.clientHeight;
    const scrollHeight = target.scrollHeight;
    
    // Trigger cuando está a 200px del final
    if (scrollHeight - scrollPosition < 200) {
      loadNextPage();
    }
  }, [paginationMode, hasMore, loading, loadNextPage]);

  /**
   * Cambia el modo de paginación
   */
  const togglePaginationMode = useCallback(() => {
    const newMode = paginationMode === 'infinite' ? 'classic' : 'infinite';
    setPaginationMode(newMode);
    
    // Reset al cambiar de modo
    invalidateCache();
    
    // En modo clásico, cargar el total
    if (newMode === 'classic' && countEndpoint) {
      loadTotalCount();
    }
  }, [paginationMode, invalidateCache, countEndpoint, loadTotalCount]);

  /**
   * Reset completo (útil cuando cambian los filtros)
   */
  const reset = useCallback(() => {
    invalidateCache();
    if (paginationMode === 'classic' && countEndpoint) {
      loadTotalCount();
    }
    loadPage(1, false);
  }, [invalidateCache, paginationMode, countEndpoint, loadTotalCount, loadPage]);

  // Effect: Cargar primera página cuando cambian los filtros o búsqueda
  // Usamos un ref para evitar el loop infinito
  const filtersRef = useRef();
  const searchRef = useRef();
  
  useEffect(() => {
    if (!enabled) return;
    
    // Comparar si realmente cambiaron los filtros
    const filtersChanged = JSON.stringify(filtersRef.current) !== JSON.stringify(filters);
    const searchChanged = searchRef.current !== debouncedSearch;
    
    if (filtersChanged || searchChanged) {
      filtersRef.current = filters;
      searchRef.current = debouncedSearch;
      
      // Llamar directamente las funciones sin usar reset para evitar loop
      invalidateCache();
      if (paginationMode === 'classic' && countEndpoint) {
        loadTotalCount();
      }
      loadPage(1, false);
    }
  }, [filters, debouncedSearch, enabled, invalidateCache, paginationMode, countEndpoint, loadTotalCount, loadPage]);

  // Effect: Cargar total en modo clásico cuando cambia el modo
  useEffect(() => {
    if (paginationMode === 'classic' && countEndpoint && enabled && totalItems === 0) {
      loadTotalCount();
    }
  }, [paginationMode, countEndpoint, enabled, loadTotalCount, totalItems]);

  // Calcular totalPages para paginación clásica
  const totalPages = paginationMode === 'classic' 
    ? Math.ceil(totalItems / pageSize)
    : 0;

  return {
    // Data
    data,
    loading,
    error,
    
    // Paginación
    currentPage,
    totalPages,
    totalItems,
    hasMore,
    pageSize,
    
    // Modo
    paginationMode,
    togglePaginationMode,
    
    // Búsqueda
    searchTerm,
    setSearchTerm,
    
    // Funciones
    loadNextPage,
    goToPage,
    reset,
    invalidateCache,
    
    // Scroll handler (para scroll infinito)
    handleScroll,
    scrollContainerRef
  };
}
