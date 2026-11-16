import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bell } from 'lucide-react';
import styles from './NotificationBell.module.css';
import NotificacionFamiliaTabs from './NotificacionFamiliaTabs';
import api from '../services/api';
import { useSSEChannel } from '../hooks/useSSEChannel';
import { useSSE } from '../contexts/SSEContext';
import { esNotificacionMarkup, tituloDeTipo } from '../utils/notificacionFamilias';
import NotificacionIcono from './NotificacionIcono';

export default function NotificationBell() {
  const navigate = useNavigate();
  const [notificaciones, setNotificaciones] = useState([]);
  const [stats, setStats] = useState(null);
  const [familia, setFamilia] = useState(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const noLeidas = stats?.no_leidas ?? 0;

  const fetchNotificaciones = async () => {
    try {
      setLoading(true);
      const params = familia ? { solo_no_leidas: false, familia } : { solo_no_leidas: false };
      const [notifResponse, statsResponse] = await Promise.all([
        api.get('/notificaciones/agrupadas', { params }),
        api.get('/notificaciones/stats')
      ]);

      setNotificaciones(notifResponse.data);
      setStats(statsResponse.data);
    } catch (error) {
      console.error('❌ Error al obtener notificaciones:', error);
      console.error('Error details:', error.response?.data || error.message);
    } finally {
      setLoading(false);
    }
  };

  const { isDegraded } = useSSE();

  useEffect(() => {
    fetchNotificaciones();
    // fetchNotificaciones se recrea cada render — recargar solo cuando cambia la familia
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [familia]);

  // SSE-driven reload: instant notification updates
  useSSEChannel('notificaciones:updated', fetchNotificaciones);

  // Fallback polling: re-activate 120s polling when SSE is degraded
  useEffect(() => {
    if (!isDegraded()) return;

    const interval = setInterval(fetchNotificaciones, 120000);
    return () => clearInterval(interval);
  }, [isDegraded]);

  const marcarComoLeida = async (notificacionesIds) => {
    try {
      // Marcar todas las notificaciones del grupo
      await Promise.all(
        notificacionesIds.map(id => api.patch(`/notificaciones/${id}/marcar-leida`))
      );
      await fetchNotificaciones();
    } catch (error) {
      console.error('Error al marcar notificación:', error);
    }
  };

  const marcarTodasLeidas = async () => {
    try {
      await api.post('/notificaciones/marcar-todas-leidas', null, {
        params: familia ? { familia } : {},
      });
      await fetchNotificaciones();
    } catch (error) {
      console.error('Error al marcar todas:', error);
    }
  };

  const eliminarNotificacion = async (notificacionesIds, tipo) => {
    if (tipo === 'compras.faltantes') return;
    try {
      // Eliminar todas las notificaciones del grupo
      await Promise.all(
        notificacionesIds.map(id => api.delete(`/notificaciones/${id}`))
      );
      await fetchNotificaciones();
    } catch (error) {
      console.error('Error al eliminar notificación:', error);
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
        <Bell size={20} strokeWidth={2} />
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

            <NotificacionFamiliaTabs familia={familia} onChange={setFamilia} stats={stats} compact />

            <div className={styles.notifList}>
              {loading ? (
                <div className={styles.loading}>Cargando...</div>
              ) : notificaciones.length === 0 ? (
                <div className={styles.empty}>No hay notificaciones</div>
              ) : (
                notificaciones.map((grupo) => (
                  <div
                    key={`${grupo.item_id}-${grupo.tipo}-${grupo.markup_real}`}
                    data-testid="notif-item"
                    className={`${styles.notifItem} ${!grupo.notificacion_reciente.leida ? styles.noLeida : ''}`}
                  >
                    <div className={styles.notifIcon}>
                      <NotificacionIcono tipo={grupo.tipo} size={18} />
                    </div>
                    <div className={styles.notifContent}>
                      {!esNotificacionMarkup(grupo.tipo) && (
                        <div className={styles.notifTitulo}>{tituloDeTipo(grupo.tipo)}</div>
                      )}
                      <div className={styles.notifMensaje}>
                        {grupo.notificacion_reciente.mensaje}
                        {grupo.count > 1 && (
                          <span className={styles.grupoCount}> ({grupo.count})</span>
                        )}
                      </div>
                      {esNotificacionMarkup(grupo.tipo) && grupo.codigo_producto && (
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
                          {grupo.tipo !== 'compras.faltantes' && (
                          <button
                            className={styles.actionBtn}
                            onClick={() => eliminarNotificacion(grupo.notificaciones_ids, grupo.tipo)}
                            title="Eliminar"
                          >
                            ✕
                          </button>
                          )}
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
