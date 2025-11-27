import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import styles from './Notificaciones.module.css';

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

export default function Notificaciones() {
  const [notificaciones, setNotificaciones] = useState([]);
  const [stats, setStats] = useState({ total: 0, no_leidas: 0, por_tipo: {} });
  const [loading, setLoading] = useState(false);
  const [filtroTipo, setFiltroTipo] = useState(null);
  const [soloNoLeidas, setSoloNoLeidas] = useState(false);
  const [paginaActual, setPaginaActual] = useState(0);
  const [expandedNotif, setExpandedNotif] = useState(null);
  const [orderData, setOrderData] = useState({});
  const [loadingOrder, setLoadingOrder] = useState({});

  const ITEMS_PER_PAGE = 20;

  const fetchNotificaciones = async () => {
    try {
      setLoading(true);
      const [notifResponse, statsResponse] = await Promise.all([
        api.get('/api/notificaciones', {
          params: {
            limit: 100,
            offset: 0,
            solo_no_leidas: soloNoLeidas,
            tipo: filtroTipo
          }
        }),
        api.get('/api/notificaciones/stats')
      ]);

      setNotificaciones(notifResponse.data);
      setStats(statsResponse.data);
    } catch (error) {
      console.error('Error al obtener notificaciones:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchNotificaciones();
  }, [soloNoLeidas, filtroTipo]);

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
      await api.post('/api/notificaciones/marcar-todas-leidas', null, {
        params: { tipo: filtroTipo }
      });
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

  const limpiarLeidas = async () => {
    if (!confirm('¿Eliminar todas las notificaciones leídas?')) return;
    try {
      await api.delete('/api/notificaciones/limpiar');
      await fetchNotificaciones();
    } catch (error) {
      console.error('Error al limpiar:', error);
    }
  };

  const fetchOrderData = async (notif) => {
    if (!notif.id_operacion) return;

    try {
      setLoadingOrder({ ...loadingOrder, [notif.id]: true });
      const response = await axios.get(
        `https://ml-webhook.gaussonline.com.ar/api/ml/render?resource=%2Forders%2F${notif.id_operacion}&format=json`
      );
      setOrderData({ ...orderData, [notif.id]: response.data });
    } catch (error) {
      console.error('Error al obtener datos de orden:', error);
    } finally {
      setLoadingOrder({ ...loadingOrder, [notif.id]: false });
    }
  };

  const toggleExpand = async (notif) => {
    if (expandedNotif === notif.id) {
      setExpandedNotif(null);
    } else {
      setExpandedNotif(notif.id);
      if (!orderData[notif.id] && notif.id_operacion) {
        await fetchOrderData(notif);
      }
      if (!notif.leida) {
        await marcarComoLeida(notif.id);
      }
    }
  };

  const getTipoIcon = (tipo) => {
    switch (tipo) {
      case 'markup_bajo': return '⚠️';
      case 'stock_bajo': return '📦';
      case 'precio_desactualizado': return '💰';
      default: return '🔔';
    }
  };

  const formatearFecha = (fecha) => {
    const date = new Date(fecha);
    return date.toLocaleString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const abrirEnML = async (notif) => {
    try {
      // Si ya tenemos pack_id en la notificación, usarlo directamente
      if (notif.pack_id) {
        window.open(`https://www.mercadolibre.com.ar/ventas/${notif.pack_id}/detalle`, '_blank');
        return;
      }

      // Si no, intentar obtenerlo de los datos de orden ya cargados
      let orderInfo = orderData[notif.id];

      // Si no tenemos los datos, fetchearlos
      if (!orderInfo && notif.id_operacion) {
        setLoadingOrder({ ...loadingOrder, [notif.id]: true });
        const response = await axios.get(
          `https://ml-webhook.gaussonline.com.ar/api/ml/render?resource=%2Forders%2F${notif.id_operacion}&format=json`
        );
        orderInfo = response.data;
        setOrderData({ ...orderData, [notif.id]: orderInfo });
        setLoadingOrder({ ...loadingOrder, [notif.id]: false });
      }

      if (orderInfo && orderInfo.pack_id) {
        window.open(`https://www.mercadolibre.com.ar/ventas/${orderInfo.pack_id}/detalle`, '_blank');
      } else {
        alert('No se pudo obtener el pack_id de la orden');
      }
    } catch (error) {
      console.error('Error al obtener pack_id:', error);
      alert('Error al obtener información de la orden');
      setLoadingOrder({ ...loadingOrder, [notif.id]: false });
    }
  };

  const notificacionesPaginadas = notificaciones.slice(
    paginaActual * ITEMS_PER_PAGE,
    (paginaActual + 1) * ITEMS_PER_PAGE
  );

  const totalPaginas = Math.ceil(notificaciones.length / ITEMS_PER_PAGE);

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1>📬 Notificaciones</h1>
        <div className={styles.stats}>
          <div className={styles.statCard}>
            <span className={styles.statLabel}>Total</span>
            <span className={styles.statValue}>{stats.total}</span>
          </div>
          <div className={styles.statCard}>
            <span className={styles.statLabel}>No leídas</span>
            <span className={styles.statValue}>{stats.no_leidas}</span>
          </div>
        </div>
      </div>

      <div className={styles.filters}>
        <div className={styles.filterGroup}>
          <label>
            <input
              type="checkbox"
              checked={soloNoLeidas}
              onChange={(e) => setSoloNoLeidas(e.target.checked)}
            />
            Solo no leídas
          </label>
        </div>

        <div className={styles.filterGroup}>
          <label>Tipo:</label>
          <select value={filtroTipo || ''} onChange={(e) => setFiltroTipo(e.target.value || null)}>
            <option value="">Todas</option>
            <option value="markup_bajo">⚠️ Markup Bajo</option>
            <option value="stock_bajo">📦 Stock Bajo</option>
            <option value="precio_desactualizado">💰 Precio Desactualizado</option>
          </select>
        </div>

        <div className={styles.actions}>
          {stats.no_leidas > 0 && (
            <button onClick={marcarTodasLeidas} className={styles.btnSecondary}>
              ✓ Marcar todas como leídas
            </button>
          )}
          <button onClick={limpiarLeidas} className={styles.btnDanger}>
            🗑️ Limpiar leídas
          </button>
        </div>
      </div>

      {loading ? (
        <div className={styles.loading}>Cargando...</div>
      ) : notificaciones.length === 0 ? (
        <div className={styles.empty}>
          <p>📭 No hay notificaciones</p>
        </div>
      ) : (
        <>
          <div className={styles.notifList}>
            {notificacionesPaginadas.map((notif) => (
              <div
                key={notif.id}
                className={`${styles.notifCard} ${!notif.leida ? styles.noLeida : ''}`}
              >
                <div className={styles.notifHeader} onClick={() => toggleExpand(notif)}>
                  <div className={styles.notifIcon}>{getTipoIcon(notif.tipo)}</div>
                  <div className={styles.notifMain}>
                    <div className={styles.notifMensaje}>{notif.mensaje}</div>
                    {notif.codigo_producto && (
                      <div className={styles.notifProducto}>
                        {notif.codigo_producto} - {notif.descripcion_producto}
                      </div>
                    )}
                  </div>
                  <div className={styles.notifMeta}>
                    <span className={styles.notifFecha}>{formatearFecha(notif.fecha_creacion)}</span>
                    {!notif.leida && <span className={styles.badgeNoLeida}>Nueva</span>}
                  </div>
                  <div className={styles.expandIcon}>
                    {expandedNotif === notif.id ? '▼' : '▶'}
                  </div>
                </div>

                {expandedNotif === notif.id && (
                  <div className={styles.notifDetalle}>
                    <div className={styles.detalleGrid}>
                      <div className={styles.detalleItem}>
                        <strong>Markup Real:</strong>
                        <span className={notif.markup_real < 0 ? styles.negativo : ''}>
                          {notif.markup_real}%
                        </span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Markup Esperado:</strong>
                        <span>{notif.markup_objetivo}%</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Monto Venta:</strong>
                        <span>${parseFloat(notif.monto_venta).toLocaleString('es-AR')}</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Fecha Venta:</strong>
                        <span>{formatearFecha(notif.fecha_venta)}</span>
                      </div>
                    </div>

                    {loadingOrder[notif.id] ? (
                      <div className={styles.loadingOrder}>Cargando datos de orden...</div>
                    ) : orderData[notif.id] ? (
                      <div className={styles.orderData}>
                        <h4>Datos de la Orden ML</h4>
                        <pre className={styles.orderJson}>
                          {JSON.stringify(orderData[notif.id], null, 2)}
                        </pre>
                      </div>
                    ) : null}

                    <div className={styles.detalleActions}>
                      {notif.id_operacion && (
                        <button
                          onClick={() => abrirEnML(notif)}
                          className={styles.btnPrimary}
                        >
                          🔗 Ver en MercadoLibre
                        </button>
                      )}
                      <button
                        onClick={() => eliminarNotificacion(notif.id)}
                        className={styles.btnDanger}
                      >
                        🗑️ Eliminar
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          {totalPaginas > 1 && (
            <div className={styles.pagination}>
              <button
                onClick={() => setPaginaActual(paginaActual - 1)}
                disabled={paginaActual === 0}
                className={styles.paginationBtn}
              >
                ← Anterior
              </button>
              <span className={styles.paginationInfo}>
                Página {paginaActual + 1} de {totalPaginas}
              </span>
              <button
                onClick={() => setPaginaActual(paginaActual + 1)}
                disabled={paginaActual >= totalPaginas - 1}
                className={styles.paginationBtn}
              >
                Siguiente →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
