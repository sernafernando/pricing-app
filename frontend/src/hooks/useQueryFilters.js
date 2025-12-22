import { useSearchParams } from 'react-router-dom';
import { useCallback, useMemo } from 'react';

/**
 * Hook para manejar filtros via query params
 * 
 * @param {Object} defaults - Valores por defecto para cada filtro
 * @param {Object} types - Tipos para parseo especial (opcional)
 * @returns {Object} - { getFilter, updateFilters, resetFilters, searchParams, getAllFilters }
 * 
 * @example
 * const { getFilter, updateFilters } = useQueryFilters({
 *   tab: 'rentabilidad',
 *   page: 1,
 *   marcas: [],
 *   productos: []
 * }, {
 *   productos: 'number[]'  // Parsear como array de números
 * });
 * 
 * // Leer
 * const tabActivo = getFilter('tab'); // 'rentabilidad'
 * const marcas = getFilter('marcas'); // ['HP', 'EPSON']
 * const productos = getFilter('productos'); // [123, 456] <- números!
 * 
 * // Escribir
 * updateFilters({ marcas: ['HP'] });
 * updateFilters({ page: 2, tab: 'resumen' });
 */
export function useQueryFilters(defaults = {}, types = {}) {
  const [searchParams, setSearchParams] = useSearchParams();
  
  /**
   * Obtiene el valor de un filtro desde query params
   * Si no existe, retorna el valor por defecto
   */
  const getFilter = useCallback((key) => {
    const value = searchParams.get(key);
    
    // Si no hay valor en URL, usar default
    if (value === null || value === undefined) {
      return defaults[key] !== undefined ? defaults[key] : '';
    }
    
    // Si el default es array, parsear como array
    if (defaults[key] && Array.isArray(defaults[key])) {
      if (!value) return [];
      const items = value.split(',').filter(Boolean);
      
      // Si hay configuración de tipo especial
      if (types[key] === 'number[]') {
        return items.map(item => parseInt(item, 10)).filter(n => !isNaN(n));
      }
      
      return items;
    }
    
    // Si el default es número, parsear como número
    if (typeof defaults[key] === 'number') {
      const parsed = parseInt(value, 10);
      return isNaN(parsed) ? defaults[key] : parsed;
    }
    
    // Si el default es boolean, parsear como boolean
    if (typeof defaults[key] === 'boolean') {
      return value === 'true';
    }
    
    // Retornar string
    return value;
  }, [searchParams, defaults, types]);
  
  /**
   * Obtiene todos los filtros como objeto
   */
  const getAllFilters = useCallback(() => {
    const filters = {};
    Object.keys(defaults).forEach(key => {
      filters[key] = getFilter(key);
    });
    return filters;
  }, [defaults, getFilter]);
  
  /**
   * Actualiza múltiples filtros a la vez
   * - Si el valor es null/undefined/''/[], elimina el param
   * - Si el valor es array, lo joinea con comas
   * - Caso contrario, lo convierte a string
   */
  const updateFilters = useCallback((updates, options = {}) => {
    const { replace = false } = options;
    const newParams = new URLSearchParams(searchParams);
    
    Object.entries(updates).forEach(([key, value]) => {
      // Eliminar param si el valor está vacío
      if (
        value === null || 
        value === undefined || 
        value === '' || 
        (Array.isArray(value) && value.length === 0)
      ) {
        newParams.delete(key);
      } 
      // Array: joinear con comas
      else if (Array.isArray(value)) {
        newParams.set(key, value.join(','));
      } 
      // Otros: convertir a string
      else {
        newParams.set(key, String(value));
      }
    });
    
    setSearchParams(newParams, { replace });
  }, [searchParams, setSearchParams]);
  
  /**
   * Resetea todos los filtros a sus valores por defecto
   */
  const resetFilters = useCallback(() => {
    setSearchParams(new URLSearchParams());
  }, [setSearchParams]);
  
  /**
   * Elimina un filtro específico
   */
  const removeFilter = useCallback((key) => {
    const newParams = new URLSearchParams(searchParams);
    newParams.delete(key);
    setSearchParams(newParams);
  }, [searchParams, setSearchParams]);
  
  return { 
    getFilter, 
    getAllFilters,
    updateFilters, 
    resetFilters, 
    removeFilter,
    searchParams 
  };
}
