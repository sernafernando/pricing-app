import { useState, useEffect } from 'react';
import styles from './NotificationBell.module.css';
import axios from 'axios';

const api = axios.create({
  baseURL: 'https://pricing.gaussonline.com.ar',
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default function NotificationBell() {
  const [notificaciones, setNotificaciones] = useState([]);
  const [noLeidas, setNoLeidas] = useState(0);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  console.log('🔔 NotificationBell montado - noLeidas:', noLeidas, 'total notifs:', notificaciones.length);

  const fetchNotificaciones = async () => {
    try {
      setLoading(true);
      console.log('🔔 Fetching notificaciones...');
      const [notifResponse, statsResponse] = await Promise.all([
        api.get('/api/notificaciones?limit=20&solo_no_leidas=false'),
        api.get('/api/notificaciones/stats')
      ]);

      console.log('✅ Notificaciones response:', notifResponse.data);
      console.log('✅ Stats response:', statsResponse.data);

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

  const marcarComoLeida = async (notifId) => {
    try {
      await api.patch(`/api/notificaciones/${notifId}/marcar-leida`);
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

  const eliminarNotificacion = async (notifId) => {
    try {
      await api.delete(`/api/notificaciones/${notifId}`);
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
                notificaciones.map((notif) => (
                  <div
                    key={notif.id}
                    className={`${styles.notifItem} ${!notif.leida ? styles.noLeida : ''}`}
                  >
                    <div className={styles.notifIcon}>
                      {getTipoIcon(notif.tipo)}
                    </div>
                    <div className={styles.notifContent}>
                      <div className={styles.notifMensaje}>{notif.mensaje}</div>
                      {notif.codigo_producto && (
                        <div className={styles.notifProducto}>
                          {notif.codigo_producto} - {notif.descripcion_producto}
                        </div>
                      )}
                      <div className={styles.notifFooter}>
                        <span className={styles.notifFecha}>
                          {formatearFecha(notif.fecha_creacion)}
                        </span>
                        <div className={styles.notifActions}>
                          {!notif.leida && (
                            <button
                              className={styles.actionBtn}
                              onClick={() => marcarComoLeida(notif.id)}
                              title="Marcar como leída"
                            >
                              ✓
                            </button>
                          )}
                          <button
                            className={styles.actionBtn}
                            onClick={() => eliminarNotificacion(notif.id)}
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
                    // TODO: navegar a página de todas las notificaciones
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
