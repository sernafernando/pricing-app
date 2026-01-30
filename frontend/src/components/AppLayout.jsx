import { useState, useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import AlertBanner, { AlertBannerContainer } from './AlertBanner';
import { useAuthStore } from '../store/authStore';
import styles from './AppLayout.module.css';

export default function AppLayout() {
  // Sincronizar estado del sidebar para ajustar el layout
  const [sidebarExpanded, setSidebarExpanded] = useState(() => {
    const saved = localStorage.getItem('sidebarPinned');
    return saved === null ? true : saved === 'true';
  });

  const user = useAuthStore((state) => state.user);

  // Escuchar cambios en localStorage para sincronizar
  useEffect(() => {
    const handleStorageChange = () => {
      const saved = localStorage.getItem('sidebarPinned');
      setSidebarExpanded(saved === 'true');
    };

    window.addEventListener('storage', handleStorageChange);
    
    // También crear un custom event para cambios en la misma tab
    const interval = setInterval(() => {
      const saved = localStorage.getItem('sidebarPinned');
      const current = saved === 'true';
      if (current !== sidebarExpanded) {
        setSidebarExpanded(current);
      }
    }, 100);

    return () => {
      window.removeEventListener('storage', handleStorageChange);
      clearInterval(interval);
    };
  }, [sidebarExpanded]);

  // Ejemplo de banners condicionales por rol
  const showAdminBanner = user?.rol === 'SUPERADMIN' || user?.rol === 'ADMIN';

  return (
    <div className={styles.appLayout}>
      <Sidebar />
      
      <div 
        className={styles.mainWrapper}
        data-sidebar-expanded={sidebarExpanded}
      >
        <TopBar sidebarExpanded={sidebarExpanded} />
        
        {/* Alert Banners - Configurables según necesidad */}
        <AlertBannerContainer>
          {/* Ejemplo de banner informativo para admins */}
          {showAdminBanner && (
            <AlertBanner
              id="admin-welcome-2026"
              variant="info"
              message="Nueva funcionalidad disponible: Dashboard de métricas mejorado con gráficos en tiempo real."
              action={{
                label: 'Ver ahora',
                onClick: () => window.location.href = '/dashboard-metricas-ml'
              }}
              dismissible={true}
            />
          )}
          
          {/* Agregar más banners según necesidad:
          
          <AlertBanner
            id="maintenance-warning"
            variant="warning"
            message="Mantenimiento programado para el 15/02 de 2:00 a 4:00 AM."
            dismissible={true}
          />
          
          <AlertBanner
            id="critical-error"
            variant="error"
            message="Error al sincronizar con MercadoLibre. Contacta a soporte."
            dismissible={false}
            persistent={true}
          />
          */}
        </AlertBannerContainer>
        
        <main className={styles.mainContent}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
