import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import api from '../services/api';
import { useAuthStore } from '../store/authStore';

const PermisosContext = createContext();

// eslint-disable-next-line react-refresh/only-export-components
export const usePermisos = () => {
  const context = useContext(PermisosContext);
  if (!context) {
    throw new Error('usePermisos must be used within PermisosProvider');
  }
  return context;
};

export const PermisosProvider = ({ children }) => {
  // El provider envuelve toda la app (incluido /login), así que monta una sola
  // vez. Nos suscribimos al token para recargar permisos cuando el usuario
  // inicia o cierra sesión sin recargar la página (navegación SPA).
  const token = useAuthStore((state) => state.token);

  const [permisos, setPermisos] = useState(new Set());
  const [rol, setRol] = useState(null);
  const [usuarioId, setUsuarioId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [initialized, setInitialized] = useState(false);
  const [error, setError] = useState(null);

  // Tracks whether permisos were EVER loaded in this session. Kept in a ref
  // (not state) so cargarPermisos — memoized with [] deps — reads the live
  // value instead of a stale closure.
  const everLoadedRef = useRef(false);

  const cargarPermisos = useCallback(async () => {
    // Solo la carga inicial es bloqueante. Los refetches posteriores (cada
    // rotación del access token, ~24 min por el proactive refresh) son
    // SILENCIOSOS: flipear loading acá desmontaba la página entera vía el
    // gate de ProtectedRoute y el usuario lo veía como "la app se refrescó
    // sola", perdiendo lo que estaba tipeando.
    const esCargaInicial = !everLoadedRef.current;
    if (esCargaInicial) {
      setLoading(true);
    }

    const token = localStorage.getItem('token');
    if (!token) {
      // Sin token no es un error: ProtectedRoute redirige a /login.
      // Reset del ref: el próximo login vuelve a cargar en modo bloqueante
      // para no mostrar la app con los permisos del usuario anterior.
      everLoadedRef.current = false;
      setPermisos(new Set());
      setRol(null);
      setUsuarioId(null);
      setError(null);
      setInitialized(true);
      setLoading(false);
      return;
    }

    // Reintentos con backoff. Un fallo transitorio de red NO debe dejar la app
    // con permisos vacíos: eso ocultaría secciones de la sidebar y bloquearía
    // páginas a un usuario que sí tiene acceso.
    const delays = [0, 400, 1200];
    let lastErr = null;

    for (const delay of delays) {
      if (delay > 0) {
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
      try {
        const res = await api.get('/permisos/mis-permisos');
        // Éxito: una lista vacía es un estado VÁLIDO (ej: rol FICHAJE),
        // no un error. Se distingue de un fallo justamente por llegar acá.
        everLoadedRef.current = true;
        setPermisos(new Set(res.data.permisos));
        setRol(res.data.rol);
        setUsuarioId(res.data.usuario_id);
        setError(null);
        setInitialized(true);
        setLoading(false);
        return;
      } catch (err) {
        lastErr = err;
      }
    }

    // Todos los reintentos fallaron.
    if (!esCargaInicial) {
      // Refetch en background fallido (ej: backend reiniciándose durante un
      // deploy). Conservar los permisos vigentes es estrictamente mejor que
      // tirar al usuario a una pantalla de error a mitad de trabajo; la
      // próxima rotación de token reintenta sola.
      console.error('Error recargando permisos (se conservan los actuales):', lastErr);
      return;
    }

    // Carga inicial fallida: NO fabricamos permisos ni marcamos initialized —
    // dejamos un estado de error explícito para que la UI ofrezca reintentar
    // en vez de renderizar la app a medias.
    console.error('Error cargando permisos tras reintentos:', lastErr);
    setError(lastErr?.message || 'No se pudieron cargar los permisos');
    setInitialized(false);
    setLoading(false);
  }, []);

  // Recarga al montar y cada vez que cambia el token (login → carga permisos
  // reales; logout → vuelve a un set vacío sin permisos colgados de la sesión
  // anterior). Esto evita el redirect erróneo a /fichaje tras loguearse.
  useEffect(() => {
    cargarPermisos();
  }, [cargarPermisos, token]);

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
