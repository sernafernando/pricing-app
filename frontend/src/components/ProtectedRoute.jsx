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
  const { tienePermiso, tieneAlgunPermiso, tieneTodosPermisos, loading, rol } = usePermisos();

  // Si no hay token, redirigir a login
  if (!token) {
    return <Navigate to="/login" replace />;
  }

  // Mientras carga permisos, mostrar nada o un loader
  if (loading) {
    return null;
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
