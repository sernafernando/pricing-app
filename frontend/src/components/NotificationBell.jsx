import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import styles from './NotificationBell.module.css';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL;

const api = axios.create({
  baseURL: `${API_URL}`,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default function NotificationBell() {
  const navigate = useNavigate();
  const [notificaciones, setNotificaciones] = useState([]);
  const [noLeidas, setNoLeidas] = useState(0);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const fetchNotificaciones = async () => {
    try {
      setLoading(true);
      const [notifResponse, statsResponse] = await Promise.all([
        api.get('/api/notificaciones/agrupadas?solo_no_leidas=false'),
        api.get('/api/notificaciones/stats')
      ]);

      setNotificaciones(notifResponse.data);
      setNoLeidas(statsResponse.data.no_leidas);
    } catch (error) {
      console.error('❌ Error al obtener notificaciones:', error);
      console.error('Error details:', error.response?.data || error.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchNotificaciones();
    // Actualizar cada 2 minutos
    const interval = setInterval(fetchNotificaciones, 120000);
    return () => clearInterval(interval);
  }, []);

  const marcarComoLeida = async (notificacionesIds) => {
    try {
      // Marcar todas las notificaciones del grupo
      await Promise.all(
        notificacionesIds.map(id => api.patch(`/api/notificaciones/${id}/marcar-leida`))
      );
      await fetchNotificaciones();
    } catch (error) {
      console.error('Error al marcar notificación:', error);
    }
  };

  const marcarTodasLeidas = async () => {
    try {
      await api.post('/api/notificaciones/marcar-todas-leidas');
      await fetchNotificaciones();
    } catch (error) {
      console.error('Error al marcar todas:', error);
    }
  };

  const eliminarNotificacion = async (notificacionesIds) => {
    try {
      // Eliminar todas las notificaciones del grupo
      await Promise.all(
        notificacionesIds.map(id => api.delete(`/api/notificaciones/${id}`))
      );
      await fetchNotificaciones();
    } catch (error) {
      console.error('Error al eliminar notificación:', error);
    }
  };

  const getTipoIcon = (tipo) => {
    switch (tipo) {
      case 'markup_bajo':
        return '⚠️';
      case 'stock_bajo':
        return '📦';
      case 'precio_desactualizado':
        return '💰';
      default:
        return '🔔';
    }
  };

  const formatearFecha = (fecha) => {
    const ahora = new Date();
    const fechaNotif = new Date(fecha);
    const diffMs = ahora - fechaNotif;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Ahora';
    if (diffMins < 60) return `Hace ${diffMins}m`;
    if (diffHours < 24) return `Hace ${diffHours}h`;
    if (diffDays === 1) return 'Ayer';
    if (diffDays < 7) return `Hace ${diffDays}d`;

    return fechaNotif.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit' });
  };

  return (
    <div className={styles.notificationBell}>
      <button
        className={styles.bellButton}
        onClick={() => setDropdownOpen(!dropdownOpen)}
        aria-label="Notificaciones"
      >
        🔔
        {noLeidas > 0 && (
          <span className={styles.badge}>{noLeidas > 99 ? '99+' : noLeidas}</span>
        )}
      </button>

      {dropdownOpen && (
        <>
          <div className={styles.backdrop} onClick={() => setDropdownOpen(false)} />
          <div className={styles.dropdown}>
            <div className={styles.header}>
              <h3>Notificaciones</h3>
              {noLeidas > 0 && (
                <button
                  className={styles.marcarTodasBtn}
                  onClick={marcarTodasLeidas}
                  title="Marcar todas como leídas"
                >
                  ✓ Marcar todas
                </button>
              )}
            </div>

            <div className={styles.notifList}>
              {loading ? (
                <div className={styles.loading}>Cargando...</div>
              ) : notificaciones.length === 0 ? (
                <div className={styles.empty}>No hay notificaciones</div>
              ) : (
                notificaciones.map((grupo) => (
                  <div
                    key={`${grupo.item_id}-${grupo.tipo}-${grupo.markup_real}`}
                    className={`${styles.notifItem} ${!grupo.notificacion_reciente.leida ? styles.noLeida : ''}`}
                  >
                    <div className={styles.notifIcon}>
                      {getTipoIcon(grupo.tipo)}
                    </div>
                    <div className={styles.notifContent}>
                      <div className={styles.notifMensaje}>
                        {grupo.notificacion_reciente.mensaje}
                        {grupo.count > 1 && (
                          <span className={styles.grupoCount}> ({grupo.count})</span>
                        )}
                      </div>
                      {grupo.codigo_producto && (
                        <div className={styles.notifProducto}>
                          <span>{grupo.codigo_producto} - {grupo.descripcion_producto}</span>
                          {grupo.pm && <span className={styles.pmTag}>PM: {grupo.pm.split(' ')[0]}</span>}
                        </div>
                      )}
                      <div className={styles.notifFooter}>
                        <span className={styles.notifFecha}>
                          {formatearFecha(grupo.ultima_fecha)}
                        </span>
                        <div className={styles.notifActions}>
                          {!grupo.notificacion_reciente.leida && (
                            <button
                              className={styles.actionBtn}
                              onClick={() => marcarComoLeida(grupo.notificaciones_ids)}
                              title="Marcar como leída"
                            >
                              ✓
                            </button>
                          )}
                          <button
                            className={styles.actionBtn}
                            onClick={() => eliminarNotificacion(grupo.notificaciones_ids)}
                            title="Eliminar"
                          >
                            ✕
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>

            {notificaciones.length > 0 && (
              <div className={styles.footer}>
                <button
                  className={styles.verTodasBtn}
                  onClick={() => {
                    setDropdownOpen(false);
                    navigate('/notificaciones');
                  }}
                >
                  Ver todas las notificaciones
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
