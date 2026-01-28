import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import axios from 'axios';

const PermisosContext = createContext();

const API_URL = import.meta.env.VITE_API_URL;

export const usePermisos = () => {
  const context = useContext(PermisosContext);
  if (!context) {
    throw new Error('usePermisos must be used within PermisosProvider');
  }
  return context;
};

export const PermisosProvider = ({ children }) => {
  const [permisos, setPermisos] = useState(new Set());
  const [rol, setRol] = useState(null);
  const [usuarioId, setUsuarioId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [initialized, setInitialized] = useState(false);
  const [error, setError] = useState(null);

  const cargarPermisos = useCallback(async () => {
    try {
      setLoading(true);
      const token = localStorage.getItem('token');
      if (!token) {
        setPermisos(new Set());
        setRol(null);
        setUsuarioId(null);
        setLoading(false);
        return;
      }

      const res = await axios.get(`${API_URL}/permisos/mis-permisos`, {
        headers: { Authorization: `Bearer ${token}` }
      });

      setPermisos(new Set(res.data.permisos));
      setRol(res.data.rol);
      setUsuarioId(res.data.usuario_id);
      setError(null);
      setInitialized(true);
    } catch (err) {
      console.error('Error cargando permisos:', err);
      setError(err.message);

      // En caso de error, intentar obtener el rol del usuario del authStore
      // para mantener compatibilidad temporal
      const token = localStorage.getItem('token');
      if (token) {
        try {
          // Decodificar el token para obtener info básica
          const payload = JSON.parse(atob(token.split('.')[1]));
          if (payload.rol) {
            console.warn('Usando rol del token por error en API de permisos');
            setRol(payload.rol);
            setUsuarioId(payload.usuario_id);
            // SUPERADMIN siempre tiene acceso
            if (payload.rol === 'SUPERADMIN') {
              setPermisos(new Set(['*'])); // Wildcard para indicar todos los permisos
            } else {
              // Para otros roles, dejar permisos vacíos si la API falló
              setPermisos(new Set());
            }
          } else {
            setPermisos(new Set());
          }
        } catch (tokenErr) {
          console.error('Error decodificando token:', tokenErr);
          setPermisos(new Set());
        }
      } else {
        setPermisos(new Set());
      }
    } finally {
      setLoading(false);
      setInitialized(true);
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

  const value = {
    permisos: Array.from(permisos),
    rol,
    usuarioId,
    tienePermiso,
    tieneAlgunPermiso,
    tieneTodosPermisos,
    loading,
    initialized,
    error,
    recargar: cargarPermisos
  };

  return (
    <PermisosContext.Provider value={value}>
      {children}
    </PermisosContext.Provider>
  );
};

export default PermisosContext;
