import { useState, useEffect, useCallback } from 'react';
import api from '../services/api';

/**
 * Hook para gestionar permisos del usuario actual
 * @returns {Object} - { permisos, tienePermiso, loading, error, recargar }
 */
export function usePermisos() {
  const [permisos, setPermisos] = useState(new Set());
  const [rol, setRol] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const cargarPermisos = useCallback(async () => {
    try {
      setLoading(true);
      const token = localStorage.getItem('token');
      if (!token) {
        setPermisos(new Set());
        setLoading(false);
        return;
      }

      const res = await api.get('/permisos/mis-permisos');

      setPermisos(new Set(res.data.permisos));
      setRol(res.data.rol);
      setError(null);
    } catch (err) {
      console.error('Error cargando permisos:', err);
      setError(err.message);
      setPermisos(new Set());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    cargarPermisos();
  }, [cargarPermisos]);

  /**
   * Verifica si el usuario tiene un permiso específico
   * @param {string} codigo - Código del permiso (ej: 'productos.ver')
   * @returns {boolean}
   */
  const tienePermiso = useCallback((codigo) => {
    // SUPERADMIN tiene todos los permisos
    if (rol === 'SUPERADMIN') return true;
    return permisos.has(codigo);
  }, [permisos, rol]);

  /**
   * Verifica si el usuario tiene al menos uno de los permisos
   * @param {string[]} codigos - Array de códigos de permisos
   * @returns {boolean}
   */
  const tieneAlgunPermiso = useCallback((codigos) => {
    if (rol === 'SUPERADMIN') return true;
    return codigos.some(codigo => permisos.has(codigo));
  }, [permisos, rol]);

  /**
   * Verifica si el usuario tiene todos los permisos
   * @param {string[]} codigos - Array de códigos de permisos
   * @returns {boolean}
   */
  const tieneTodosPermisos = useCallback((codigos) => {
    if (rol === 'SUPERADMIN') return true;
    return codigos.every(codigo => permisos.has(codigo));
  }, [permisos, rol]);

  return {
    permisos: Array.from(permisos),
    rol,
    tienePermiso,
    tieneAlgunPermiso,
    tieneTodosPermisos,
    loading,
    error,
    recargar: cargarPermisos
  };
}

/**
 * Hook simplificado para verificar un solo permiso
 * @param {string} codigo - Código del permiso
 * @returns {boolean | null} - true/false o null si está cargando
 */
export function usePermiso(codigo) {
  const { tienePermiso, loading } = usePermisos();

  if (loading) return null;
  return tienePermiso(codigo);
}

export default usePermisos;
