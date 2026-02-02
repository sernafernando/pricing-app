import { useState, useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import axios from 'axios';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import AlertBanner, { AlertBannerContainer } from './AlertBanner';
import { useAuthStore } from '../store/authStore';
import styles from './AppLayout.module.css';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default function AppLayout() {
  // Sincronizar estado del sidebar para ajustar el layout
  const [sidebarExpanded, setSidebarExpanded] = useState(() => {
    const saved = localStorage.getItem('sidebarPinned');
    return saved === null ? true : saved === 'true';
  });

  const user = useAuthStore((state) => state.user);
  const [alertasActivas, setAlertasActivas] = useState([]);

  // Cargar alertas activas para el usuario
  useEffect(() => {
    if (user) {
      cargarAlertasActivas();
      // Refrescar cada 5 minutos
      const interval = setInterval(cargarAlertasActivas, 300000);
      return () => clearInterval(interval);
    }
  }, [user]);

  const cargarAlertasActivas = async () => {
    try {
      const response = await api.get('/alertas/activas');
      setAlertasActivas(response.data);
    } catch (error) {
      console.error('Error al cargar alertas activas:', error);
    }
  };

  const handleCerrarAlerta = async (alertaId) => {
    try {
      await api.post(`/alertas/${alertaId}/cerrar`);
      setAlertasActivas(prev => prev.filter(a => a.id !== alertaId));
    } catch (error) {
      console.error('Error al cerrar alerta:', error);
    }
  };

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

  return (
    <div className={styles.appLayout}>
      <Sidebar />
      
      <div 
        className={styles.mainWrapper}
        data-sidebar-expanded={sidebarExpanded}
      >
        <TopBar sidebarExpanded={sidebarExpanded} />
        
        {/* Alert Banners - Dinámicos desde el backend */}
        <AlertBannerContainer sidebarExpanded={sidebarExpanded}>
          {alertasActivas.map((alerta) => (
            <AlertBanner
              key={alerta.id}
              id={`alerta-${alerta.id}`}
              variant={alerta.variant}
              message={alerta.mensaje}
              action={alerta.action_label && alerta.action_url ? {
                label: alerta.action_label,
                onClick: () => window.location.href = alerta.action_url
              } : null}
              dismissible={alerta.dismissible}
              persistent={alerta.persistent}
              onDismiss={() => handleCerrarAlerta(alerta.id)}
            />
          ))}
        </AlertBannerContainer>
        
        <main className={styles.mainContent}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
