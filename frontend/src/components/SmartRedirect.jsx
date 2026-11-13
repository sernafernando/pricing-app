import { Navigate } from 'react-router-dom';
import { usePermisos } from '../contexts/PermisosContext';
import FullScreenLoader from './FullScreenLoader';

/**
 * Redirige al usuario a la primera página que tenga acceso
 * Evita loops infinitos cuando el usuario no tiene acceso a la primera ruta
 *
 * Nota: la resiliencia ante fallos de carga de permisos (retry + estado de
 * error) vive en PermisosContext/ProtectedRoute. Acá un set de permisos vacío
 * ya es un estado VÁLIDO (rol FICHAJE) y se redirige a /fichaje.
 */
export default function SmartRedirect() {
  const { tienePermiso, loading, initialized } = usePermisos();
  // `permiso` may list several codes separated by commas: any of them grants the route.
  const puedeVer = (permiso) => permiso.split(',').some((codigo) => tienePermiso(codigo));

  // Esperar hasta que los permisos estén completamente cargados
  if (loading || !initialized) {
    return <FullScreenLoader />;
  }

  // Lista de rutas en orden de prioridad con sus permisos requeridos
  const rutas = [
    // Publicaciones ML is the default landing; /productos stays reachable by URL only.
    { path: '/ml-publicaciones', permiso: 'productos.ver,ml_ops.ver' },
    { path: '/tienda', permiso: 'productos.ver_tienda' },
    { path: '/dashboard-metricas-ml', permiso: 'ventas_ml.ver_dashboard' },
    { path: '/dashboard-ventas-fuera', permiso: 'ventas_fuera.ver_dashboard' },
    { path: '/dashboard-tienda-nube', permiso: 'ventas_tn.ver_dashboard' },
    { path: '/ultimos-cambios', permiso: 'productos.ver_auditoria' },
    { path: '/calculos', permiso: 'reportes.ver_calculadora' },
    { path: '/notificaciones', permiso: 'reportes.ver_notificaciones' },
    { path: '/admin', permiso: 'admin.ver_panel' },
    { path: '/gestion-pm', permiso: 'admin.gestionar_pms' },
    { path: '/mla-banlist', permiso: 'admin.gestionar_mla_banlist' },
    { path: '/items-sin-mla', permiso: 'admin.ver_items_sin_mla' },
    { path: '/pedidos-preparacion', permiso: 'ordenes.ver_preparacion' },
    { path: '/rma', permiso: 'rma.ver' },
    { path: '/claims', permiso: 'rma.ver' },
    { path: '/seguimiento-envios', permiso: 'seguimiento_envios.ver' },
    { path: '/rrhh/empleados', permiso: 'rrhh.ver' },
    { path: '/administracion/proveedores', permiso: 'administracion.ver_proveedores' },
    { path: '/dashboard-tplink', permiso: 'dashboard_tplink.ver' },
  ];

  // Buscar la primera ruta a la que tenga acceso
  for (const ruta of rutas) {
    if (puedeVer(ruta.permiso)) {
      return <Navigate to={ruta.path} replace />;
    }
  }

  // User has zero permissions but is authenticated → likely FICHAJE role → redirect to /fichaje
  const token = localStorage.getItem('token');
  if (token) {
    return <Navigate to="/fichaje" replace />;
  }

  // Not authenticated at all
  return <Navigate to="/login" replace />;
}
