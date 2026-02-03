import { useState, useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import AlertBanner, { AlertBannerContainer } from './AlertBanner';
import { useAuthStore } from '../store/authStore';
import api from '../services/api';
import styles from './AppLayout.module.css';

export default function AppLayout() {
  // Sincronizar estado del sidebar para ajustar el layout
  const [sidebarExpanded, setSidebarExpanded] = useState(() => {
    const saved = localStorage.getItem('sidebarPinned');
    return saved === null ? true : saved === 'true';
  });

  const user = useAuthStore((state) => state.user);
  const [todasLasAlertas, setTodasLasAlertas] = useState([]);
  const [alertasVisibles, setAlertasVisibles] = useState([]);
  const [indiceRotacion, setIndiceRotacion] = useState(0);
  const [maxAlertasVisibles, setMaxAlertasVisibles] = useState(1);

  // Cargar alertas activas y configuración
  useEffect(() => {
    if (user) {
      cargarAlertasActivas();
      cargarConfiguracion();
      // Refrescar cada 5 minutos
      const interval = setInterval(() => {
        cargarAlertasActivas();
        cargarConfiguracion();
      }, 300000);
      return () => clearInterval(interval);
    }
  }, [user]);

  const cargarAlertasActivas = async () => {
    try {
      const response = await api.get('/alertas/activas');
      setTodasLasAlertas(response.data);
      setIndiceRotacion(0); // Reset rotación cuando se cargan nuevas alertas
    } catch (error) {
      console.error('Error al cargar alertas activas:', error);
    }
  };

  const cargarConfiguracion = async () => {
    try {
      const response = await api.get('/alertas/configuracion');
      setMaxAlertasVisibles(response.data.max_alertas_visibles);
    } catch (error) {
      console.error('Error al cargar configuración de alertas:', error);
    }
  };

  // Sistema de rotación de alertas
  useEffect(() => {
    if (todasLasAlertas.length === 0) {
      setAlertasVisibles([]);
      return;
    }

    // Separar alertas sticky (duración 0) de rotativas (duración > 0)
    // Backend ya las envía ordenadas por prioridad DESC
    const alertasSticky = todasLasAlertas.filter(a => a.duracion_segundos === 0);
    const alertasRotativas = todasLasAlertas.filter(a => a.duracion_segundos > 0);

    // Calcular cuántos slots quedan para alertas rotativas
    const slotsParaRotativas = Math.max(0, maxAlertasVisibles - alertasSticky.length);

    // Si no hay alertas rotativas, solo mostrar sticky (ya están ordenadas por prioridad)
    if (alertasRotativas.length === 0) {
      setAlertasVisibles(alertasSticky.slice(0, maxAlertasVisibles));
      return;
    }

    // Mostrar alertas rotativas según índice actual
    // No mostrar más alertas de las que existen (evita duplicados)
    const cantidadAMostrar = Math.min(slotsParaRotativas, alertasRotativas.length);
    const rotativasVisibles = [];
    for (let i = 0; i < cantidadAMostrar; i++) {
      const index = (indiceRotacion + i) % alertasRotativas.length;
      rotativasVisibles.push(alertasRotativas[index]);
    }
    
    // Orden final: sticky arriba (mayor prioridad), rotativas abajo
    const alertasAMostrar = [...alertasSticky, ...rotativasVisibles];
    setAlertasVisibles(alertasAMostrar);

    // Si hay más rotativas que slots, configurar rotación
    if (alertasRotativas.length > slotsParaRotativas) {
      // Obtener duración de la PRIMERA alerta rotativa visible
      const duracionActual = rotativasVisibles[0]?.duracion_segundos || 5;

      // Rotar a la siguiente rotativa después de su duración
      const rotacionInterval = setInterval(() => {
        setIndiceRotacion(prev => (prev + 1) % alertasRotativas.length);
      }, duracionActual * 1000);

      return () => clearInterval(rotacionInterval);
    }
    // Si hay menos o igual rotativas que slots, no rotar (mostrar todas)
  }, [todasLasAlertas, indiceRotacion, maxAlertasVisibles]);

  const handleCerrarAlerta = async (alertaId) => {
    try {
      await api.post(`/alertas/${alertaId}/cerrar`);
      // Remover de la lista completa
      setTodasLasAlertas(prev => prev.filter(a => a.id !== alertaId));
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

    // 'storage' event se dispara automáticamente entre tabs
    window.addEventListener('storage', handleStorageChange);
    
    // Para cambios en la MISMA tab, usar custom event
    const handleCustomChange = (e) => {
      if (e.detail && e.detail.key === 'sidebarPinned') {
        setSidebarExpanded(e.detail.value === 'true');
      }
    };
    
    window.addEventListener('sidebarChange', handleCustomChange);

    return () => {
      window.removeEventListener('storage', handleStorageChange);
      window.removeEventListener('sidebarChange', handleCustomChange);
    };
  }, []);

  return (
    <div className={styles.appLayout}>
      <Sidebar />
      
      <div 
        className={styles.mainWrapper}
        data-sidebar-expanded={sidebarExpanded}
      >
        <TopBar sidebarExpanded={sidebarExpanded} />
        
        {/* Alert Banners - Sistema de rotación */}
        <AlertBannerContainer sidebarExpanded={sidebarExpanded}>
          {alertasVisibles.map((alerta) => (
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
