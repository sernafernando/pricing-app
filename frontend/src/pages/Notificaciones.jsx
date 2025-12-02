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
  const [preciosSeteados, setPreciosSeteados] = useState({});
  const [vistaAgrupada, setVistaAgrupada] = useState(true);
  const [expandedGrupo, setExpandedGrupo] = useState(null);

  const ITEMS_PER_PAGE = 20;

  const fetchNotificaciones = async () => {
    try {
      setLoading(true);
      const endpoint = vistaAgrupada ? '/api/notificaciones/agrupadas' : '/api/notificaciones';
      const params = vistaAgrupada
        ? { solo_no_leidas: soloNoLeidas, tipo: filtroTipo }
        : { limit: 100, offset: 0, solo_no_leidas: soloNoLeidas, tipo: filtroTipo };

      const [notifResponse, statsResponse] = await Promise.all([
        api.get(endpoint, { params }),
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
  }, [soloNoLeidas, filtroTipo, vistaAgrupada]);

  const marcarComoLeida = async (notifId) => {
    try {
      await api.patch(`/api/notificaciones/${notifId}/marcar-leida`);

      // Actualizar estado local en lugar de recargar todo
      setNotificaciones(notificaciones.map(n =>
        n.id === notifId ? { ...n, leida: true, fecha_lectura: new Date().toISOString() } : n
      ));

      // Actualizar stats
      setStats(prev => ({
        ...prev,
        no_leidas: Math.max(0, prev.no_leidas - 1)
      }));
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

  const marcarTodasNoLeidas = async () => {
    try {
      await api.post('/api/notificaciones/marcar-todas-no-leidas', null, {
        params: { tipo: filtroTipo }
      });
      await fetchNotificaciones();
    } catch (error) {
      console.error('Error al marcar todas como no leídas:', error);
    }
  };

  const marcarComoNoLeida = async (notifId) => {
    try {
      await api.patch(`/api/notificaciones/${notifId}/marcar-no-leida`);
      await fetchNotificaciones();
    } catch (error) {
      console.error('Error al marcar como no leída:', error);
    }
  };

  const eliminarNotificacion = async (notifId) => {
    try {
      const notif = notificaciones.find(n => n.id === notifId);
      await api.delete(`/api/notificaciones/${notifId}`);

      // Actualizar estado local
      setNotificaciones(notificaciones.filter(n => n.id !== notifId));

      // Actualizar stats
      setStats(prev => ({
        ...prev,
        total: Math.max(0, prev.total - 1),
        no_leidas: notif && !notif.leida ? Math.max(0, prev.no_leidas - 1) : prev.no_leidas
      }));

      // Cerrar expandido si es la misma
      if (expandedNotif === notifId) {
        setExpandedNotif(null);
      }
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

  const fetchPrecioSeteado = async (notif) => {
    if (!notif.item_id || preciosSeteados[notif.id]) return;

    try {
      const response = await api.get(`/api/productos/${notif.item_id}/pricing-stored`);
      if (response.data && response.data.precio_lista_ml) {
        setPreciosSeteados(prev => ({ ...prev, [notif.id]: response.data.precio_lista_ml }));
      }
    } catch (error) {
      console.error('Error al obtener precio seteado:', error);
    }
  };

  const toggleExpand = async (notif) => {
    if (expandedNotif === notif.id) {
      setExpandedNotif(null);
    } else {
      setExpandedNotif(notif.id);
      // Obtener precio seteado del producto
      await fetchPrecioSeteado(notif);
      if (!notif.leida) {
        await marcarComoLeida(notif.id);
        await fetchNotificaciones();
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

  const abrirEnML = (notif) => {
    if (notif.ml_id) {
      window.open(`https://www.mercadolibre.com.ar/ventas/${notif.ml_id}/detalle`, '_blank');
    } else {
      alert('No se puede abrir la orden: ml_id no disponible');
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
          <label>
            <input
              type="checkbox"
              checked={vistaAgrupada}
              onChange={(e) => setVistaAgrupada(e.target.checked)}
            />
            Agrupar por producto/markup
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
          {stats.leidas > 0 && (
            <button onClick={marcarTodasNoLeidas} className={styles.btnSecondary}>
              ○ Marcar todas como no leídas
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
      ) : vistaAgrupada ? (
        <>
          <div className={styles.notifList}>
            {notificacionesPaginadas.map((grupo) => (
              <div
                key={`${grupo.item_id}-${grupo.tipo}-${grupo.markup_real}`}
                className={`${styles.grupoCard} ${!grupo.notificacion_reciente.leida ? styles.noLeida : ''}`}
              >
                <div className={styles.grupoHeader} onClick={async () => {
                  if (expandedGrupo === grupo) {
                    setExpandedGrupo(null);
                  } else {
                    setExpandedGrupo(grupo);
                    await fetchPrecioSeteado(grupo.notificacion_reciente);
                    // Marcar todas las del grupo como leídas si no lo están
                    if (!grupo.notificacion_reciente.leida) {
                      await Promise.all(grupo.notificaciones_ids.map(id =>
                        api.patch(`/api/notificaciones/${id}/marcar-leida`)
                      ));
                      await fetchNotificaciones();
                    }
                  }
                }}>
                  <div className={styles.notifIcon}>{getTipoIcon(grupo.tipo)}</div>
                  <div className={styles.grupoMain}>
                    <div className={styles.grupoProducto}>
                      {grupo.codigo_producto} - {grupo.descripcion_producto}
                    </div>
                    <div className={styles.grupoInfo}>
                      <span className={styles.grupoMarkup}>Markup Real: {grupo.markup_real}%</span>
                      <span className={styles.grupoCount}>({grupo.count} notificación{grupo.count > 1 ? 'es' : ''})</span>
                      {grupo.pm && <span className={styles.pmTag}>PM: {grupo.pm}</span>}
                    </div>
                    <div className={styles.grupoFechas}>
                      {grupo.count > 1 ? (
                        <span>{formatearFecha(grupo.primera_fecha)} → {formatearFecha(grupo.ultima_fecha)}</span>
                      ) : (
                        <span>{formatearFecha(grupo.ultima_fecha)}</span>
                      )}
                    </div>
                  </div>
                  <div className={styles.expandIcon}>
                    {expandedGrupo === grupo ? '▼' : '▶'}
                  </div>
                </div>

                {expandedGrupo === grupo && (
                  <div className={styles.grupoDetalle}>
                    {/* Mostrar detalles de la notificación más reciente */}
                    <h4 className={styles.seccionTitulo}>📊 Operación Más Reciente</h4>
                    <div className={styles.detalleGrid}>
                      <div className={styles.detalleItem}>
                        <strong>Markup Real:</strong>
                        <span className={grupo.notificacion_reciente.markup_real < 0 ? styles.negativo : ''}>
                          {grupo.notificacion_reciente.markup_real}%
                        </span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Monto de la Venta:</strong>
                        <span>${parseFloat(grupo.notificacion_reciente.monto_venta).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Costo de la Venta:</strong>
                        <span>${grupo.notificacion_reciente.costo_operacion ? parseFloat(grupo.notificacion_reciente.costo_operacion).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : 'N/A'}</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Costo Envío:</strong>
                        <span>${grupo.notificacion_reciente.costo_envio ? parseFloat(grupo.notificacion_reciente.costo_envio).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '0,00'}</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Fecha Venta:</strong>
                        <span>{formatearFecha(grupo.notificacion_reciente.fecha_venta)}</span>
                      </div>
                    </div>

                    {/* Sección 2: Configuración ML */}
                    <h4 className={styles.seccionTitulo}>🛒 Configuración ML</h4>
                    <div className={styles.detalleGrid}>
                      <div className={styles.detalleItem}>
                        <strong>Cantidad:</strong>
                        <span>{grupo.notificacion_reciente.cantidad || 1} unidad{grupo.notificacion_reciente.cantidad > 1 ? 'es' : ''}</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Lista de Precios:</strong>
                        <span>{grupo.notificacion_reciente.tipo_publicacion || 'N/A'}</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Comisión ML:</strong>
                        <span>{grupo.notificacion_reciente.comision_ml ? `${parseFloat(grupo.notificacion_reciente.comision_ml).toFixed(2)}%` : 'N/A'}</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>IVA:</strong>
                        <span>{grupo.notificacion_reciente.iva_porcentaje || 21}%</span>
                      </div>
                    </div>

                    {/* Sección 3: Configuración del Producto */}
                    <h4 className={styles.seccionTitulo}>⚙️ Configuración Producto</h4>
                    <div className={styles.detalleGrid}>
                      <div className={styles.detalleItem}>
                        <strong>Precio Venta Seteado:</strong>
                        <span>${preciosSeteados[grupo.notificacion_reciente.id] ? parseFloat(preciosSeteados[grupo.notificacion_reciente.id]).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : 'Cargando...'}</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Markup Esperado:</strong>
                        <span>{grupo.notificacion_reciente.markup_objetivo}%</span>
                      </div>
                      {grupo.notificacion_reciente.pm && (
                        <div className={styles.detalleItem}>
                          <strong>Product Manager:</strong>
                          <span>{grupo.notificacion_reciente.pm}</span>
                        </div>
                      )}
                      <div className={styles.detalleItem}>
                        <strong>Costo Actual:</strong>
                        <span>${grupo.notificacion_reciente.costo_actual ? parseFloat(grupo.notificacion_reciente.costo_actual).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : 'N/A'}</span>
                      </div>
                    </div>

                    <div className={styles.detalleActions}>
                      {grupo.notificacion_reciente.ml_id && (
                        <button
                          onClick={() => abrirEnML(grupo.notificacion_reciente)}
                          className={styles.btnPrimary}
                        >
                          🔗 Ver última en MercadoLibre
                        </button>
                      )}
                      {grupo.notificacion_reciente.leida && (
                        <button
                          onClick={() => {
                            Promise.all(grupo.notificaciones_ids.map(id => marcarComoNoLeida(id)));
                          }}
                          className={styles.btnSecondary}
                        >
                          ○ Marcar no leídas ({grupo.count})
                        </button>
                      )}
                      <button
                        onClick={() => {
                          if (confirm(`¿Eliminar ${grupo.count} notificación${grupo.count > 1 ? 'es' : ''}?`)) {
                            Promise.all(grupo.notificaciones_ids.map(id => eliminarNotificacion(id)))
                              .then(() => setExpandedGrupo(null));
                          }
                        }}
                        className={styles.btnDanger}
                      >
                        🗑️ Eliminar todas ({grupo.count})
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
                    {notif.pm && (
                      <div className={styles.pmTag}>PM: {notif.pm}</div>
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
                    {/* Sección 1: Datos de la Operación */}
                    <h4 className={styles.seccionTitulo}>📊 Operación</h4>
                    <div className={styles.detalleGrid}>
                      <div className={styles.detalleItem}>
                        <strong>Markup Real:</strong>
                        <span className={notif.markup_real < 0 ? styles.negativo : ''}>
                          {notif.markup_real}%
                        </span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Monto de la Venta:</strong>
                        <span>${parseFloat(notif.monto_venta).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Costo de la Venta:</strong>
                        <span>${notif.costo_operacion ? parseFloat(notif.costo_operacion).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : 'N/A'}</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Costo Envío:</strong>
                        <span>${notif.costo_envio ? parseFloat(notif.costo_envio).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '0,00'}</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Fecha Venta:</strong>
                        <span>{formatearFecha(notif.fecha_venta)}</span>
                      </div>
                    </div>

                    {/* Sección 2: Configuración ML */}
                    <h4 className={styles.seccionTitulo}>🛒 Configuración ML</h4>
                    <div className={styles.detalleGrid}>
                      <div className={styles.detalleItem}>
                        <strong>Cantidad:</strong>
                        <span>{notif.cantidad || 1} unidad{notif.cantidad > 1 ? 'es' : ''}</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Lista de Precios:</strong>
                        <span>{notif.tipo_publicacion || 'N/A'}</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Comisión ML:</strong>
                        <span>{notif.comision_ml ? `${parseFloat(notif.comision_ml).toFixed(2)}%` : 'N/A'}</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>IVA:</strong>
                        <span>{notif.iva_porcentaje || 21}%</span>
                      </div>
                    </div>

                    {/* Sección 3: Configuración del Producto */}
                    <h4 className={styles.seccionTitulo}>⚙️ Configuración Producto</h4>
                    <div className={styles.detalleGrid}>
                      <div className={styles.detalleItem}>
                        <strong>Precio Venta Seteado:</strong>
                        <span>${preciosSeteados[notif.id] ? parseFloat(preciosSeteados[notif.id]).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : 'Cargando...'}</span>
                      </div>
                      <div className={styles.detalleItem}>
                        <strong>Markup Esperado:</strong>
                        <span>{notif.markup_objetivo}%</span>
                      </div>
                      {notif.pm && (
                        <div className={styles.detalleItem}>
                          <strong>Product Manager:</strong>
                          <span>{notif.pm}</span>
                        </div>
                      )}
                      <div className={styles.detalleItem}>
                        <strong>Costo Actual:</strong>
                        <span>${notif.costo_actual ? parseFloat(notif.costo_actual).toLocaleString('es-AR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : 'N/A'}</span>
                      </div>
                    </div>

                    <div className={styles.detalleActions}>
                      {notif.ml_id && (
                        <button
                          onClick={() => abrirEnML(notif)}
                          className={styles.btnPrimary}
                        >
                          🔗 Ver en MercadoLibre
                        </button>
                      )}
                      {notif.leida && (
                        <button
                          onClick={() => marcarComoNoLeida(notif.id)}
                          className={styles.btnSecondary}
                        >
                          ○ Marcar no leída
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
