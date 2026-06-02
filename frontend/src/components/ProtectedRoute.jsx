import { Navigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import { usePermisos } from '../contexts/PermisosContext';

/**
 * Componente para proteger rutas con autenticación y permisos
 * @param {Object} props
 * @param {React.ReactNode} props.children - Contenido protegido
 * @param {string[]} [props.allowedRoles] - Roles permitidos (sistema legacy)
 * @param {string} [props.permiso] - Código de permiso requerido
 * @param {string[]} [props.permisos] - Múltiples permisos, requiere al menos uno
 * @param {boolean} [props.requireAll] - Si true, requiere todos los permisos en vez de al menos uno
 * @param {React.ReactNode} [props.fallback] - Componente a mostrar si no tiene permiso (default: redirige a /)
 */
export default function ProtectedRoute({
  children,
  allowedRoles,
  permiso,
  permisos,
  requireAll = false,
  fallback
}) {
  const token = useAuthStore((state) => state.token);
  const user = useAuthStore((state) => state.user);
  const { tienePermiso, tieneAlgunPermiso, tieneTodosPermisos, loading, initialized, error, recargar, rol } = usePermisos();

  // Si no hay token, redirigir a login
  if (!token) {
    return <Navigate to="/login" replace />;
  }

  // Mientras carga permisos, mostrar loader
  if (loading) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh',
        color: 'var(--text-color, #fff)'
      }}>
        <div>Cargando permisos...</div>
      </div>
    );
  }

  // Si la carga de permisos falló, NO renderizar la app con permisos vacíos
  // (ocultaría secciones y bloquearía páginas). Ofrecer reintentar.
  if (error && !initialized) {
    return (
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '1rem',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh',
        color: 'var(--text-color, #fff)'
      }}>
        <div>No pudimos cargar tus permisos.</div>
        <button onClick={recargar}>Reintentar</button>
      </div>
    );
  }

  // Safety net: aún sin inicializar y sin error → seguir mostrando loader
  if (!initialized) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh',
        color: 'var(--text-color, #fff)'
      }}>
        <div>Cargando permisos...</div>
      </div>
    );
  }

  // Verificar roles (sistema legacy - mantener compatibilidad)
  if (allowedRoles && allowedRoles.length > 0) {
    const userRole = user?.rol || rol;
    if (!userRole || !allowedRoles.includes(userRole)) {
      if (fallback) return fallback;
      return <Navigate to="/" replace />;
    }
  }

  // Verificar permiso único
  if (permiso) {
    if (!tienePermiso(permiso)) {
      if (fallback) return fallback;
      return <Navigate to="/" replace />;
    }
  }

  // Verificar múltiples permisos
  if (permisos && permisos.length > 0) {
    const tiene = requireAll
      ? tieneTodosPermisos(permisos)
      : tieneAlgunPermiso(permisos);

    if (!tiene) {
      if (fallback) return fallback;
      return <Navigate to="/" replace />;
    }
  }

  return children;
}
