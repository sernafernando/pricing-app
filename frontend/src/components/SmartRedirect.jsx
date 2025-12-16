import { Navigate } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { usePermisos } from '../contexts/PermisosContext';

/**
 * Redirige al usuario a la primera página que tenga acceso
 * Evita loops infinitos cuando el usuario no tiene acceso a /productos
 */
export default function SmartRedirect() {
  const { tienePermiso, tieneAlgunPermiso, loading, initialized, permisos, recargar } = usePermisos();
  const [retryCount, setRetryCount] = useState(0);

  // Debug: ver qué está pasando
  console.log('SmartRedirect state:', { loading, initialized, permisosCount: permisos?.length, permisos, retryCount });

  // Si initialized pero permisos vacío, intentar recargar (máximo 2 veces)
  useEffect(() => {
    if (initialized && !loading && permisos?.length === 0 && retryCount < 2) {
      console.log('SmartRedirect: permisos vacíos, recargando...');
      const timer = setTimeout(() => {
        setRetryCount(r => r + 1);
        recargar();
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [initialized, loading, permisos, retryCount, recargar]);

  // Esperar hasta que los permisos estén completamente cargados
  if (loading || !initialized || (permisos?.length === 0 && retryCount < 2)) {
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

  // Lista de rutas en orden de prioridad con sus permisos requeridos
  const rutas = [
    { path: '/productos', permiso: 'productos.ver' },
    { path: '/tienda', permiso: 'productos.ver_tienda' },
    { path: '/dashboard-ventas', permisos: ['ventas_ml.ver_dashboard', 'ventas_fuera.ver_dashboard', 'ventas_tn.ver_dashboard'] },
    { path: '/dashboard-metricas-ml', permiso: 'ventas_ml.ver_dashboard' },
    { path: '/dashboard-ventas-fuera', permiso: 'ventas_fuera.ver_dashboard' },
    { path: '/dashboard-tienda-nube', permiso: 'ventas_tn.ver_dashboard' },
    { path: '/ultimos-cambios', permiso: 'productos.ver_auditoria' },
    { path: '/calculos', permiso: 'reportes.ver_calculadora' },
    { path: '/notificaciones', permiso: 'reportes.ver_notificaciones' },
    { path: '/admin', permiso: 'admin.ver_panel' },
    { path: '/gestion-pm', permiso: 'admin.gestionar_pms' },
    { path: '/mla-banlist', permiso: 'admin.gestionar_mla_banlist' },
    { path: '/items-sin-mla', permiso: 'admin.gestionar_mla_banlist' },
  ];

  // Buscar la primera ruta a la que tenga acceso
  for (const ruta of rutas) {
    if (ruta.permisos) {
      const tiene = tieneAlgunPermiso(ruta.permisos);
      console.log(`SmartRedirect: ${ruta.path} (permisos: ${ruta.permisos.join(', ')}) = ${tiene}`);
      if (tiene) {
        return <Navigate to={ruta.path} replace />;
      }
    } else if (ruta.permiso) {
      const tiene = tienePermiso(ruta.permiso);
      console.log(`SmartRedirect: ${ruta.path} (permiso: ${ruta.permiso}) = ${tiene}`);
      if (tiene) {
        return <Navigate to={ruta.path} replace />;
      }
    }
  }

  console.log('SmartRedirect: No se encontró ninguna ruta con permiso');

  // Si no tiene acceso a ninguna ruta, mostrar mensaje
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      alignItems: 'center',
      height: '100vh',
      color: 'var(--text-color, #fff)',
      textAlign: 'center',
      padding: '20px'
    }}>
      <h2>Sin acceso</h2>
      <p>No tienes permisos para acceder a ninguna sección del sistema.</p>
      <p>Contacta al administrador para que te asigne los permisos necesarios.</p>
    </div>
  );
}
