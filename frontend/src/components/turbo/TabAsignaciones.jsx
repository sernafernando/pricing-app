import { useState, useEffect, Fragment } from 'react';
import axios from 'axios';
import styles from '../../pages/TurboRouting.module.css';

const API_URL = 'https://pricing.gaussonline.com.ar/api';

export default function TabAsignaciones() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expandidos, setExpandidos] = useState(new Set());

  const getToken = () => localStorage.getItem('token');

  const fetchAsignaciones = async () => {
    setLoading(true);
    try {
      const { data: response } = await axios.get(`${API_URL}/turbo/asignaciones/hoy`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      setData(response);
    } catch (error) {
      alert(error.response?.data?.detail || 'Error cargando asignaciones del día');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAsignaciones();
  }, []);

  const toggleMotoquero = (motoqueroId) => {
    const nuevos = new Set(expandidos);
    if (nuevos.has(motoqueroId)) {
      nuevos.delete(motoqueroId);
    } else {
      nuevos.add(motoqueroId);
    }
    setExpandidos(nuevos);
  };

  const getEstadoBadge = (estadoDisplay) => {
    const badges = {
      pendiente: { className: styles.estadoPendiente, text: '⏳ Pendiente' },
      en_camino: { className: styles.estadoEnCamino, text: '🚚 En camino' },
      entregado: { className: styles.estadoEntregado, text: '✅ Entregado' }
    };
    const badge = badges[estadoDisplay] || badges.pendiente;
    return <span className={badge.className}>{badge.text}</span>;
  };

  if (loading) {
    return (
      <div className={styles.tabContent}>
        <div className={styles.loadingState}>
          <p>⏳ Cargando asignaciones del día...</p>
        </div>
      </div>
    );
  }

  if (!data || data.total_asignaciones === 0) {
    return (
      <div className={styles.tabContent}>
        <div className={styles.emptyState}>
          <p>No hay asignaciones para hoy.</p>
          <p>Ejecutá la asignación automática en el tab de Envíos.</p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.tabContent}>
      <div className={styles.header}>
        <div>
          <h2>📋 Asignaciones del Día</h2>
          <p className={styles.subtitle}>
            {data.fecha} • <strong>{data.total_asignaciones} envíos asignados</strong> • 
            <span style={{ color: 'var(--success)', marginLeft: '0.5rem' }}>✅ {data.total_entregados} entregados</span> • 
            <span style={{ color: 'var(--error)', marginLeft: '0.5rem' }}>⏳ {data.total_pendientes} pendientes</span>
          </p>
        </div>
        <button onClick={fetchAsignaciones} className={styles.btnSecondary}>
          🔄 Actualizar
        </button>
      </div>

      {/* RESUMEN POR MOTOQUERO */}
      <div className={styles.card}>
        <h3 className={styles.sectionTitle}>Resumen por Motoquero</h3>
        <div className={styles.tableContainer}>
          <table className={styles.tablaTesla}>
            <thead>
              <tr>
                <th style={{ width: '50px' }}></th>
                <th>Motoquero</th>
                <th style={{ width: '120px', textAlign: 'center' }}>Total</th>
                <th style={{ width: '120px', textAlign: 'center' }}>✅ Entregados</th>
                <th style={{ width: '120px', textAlign: 'center' }}>🚚 En Camino</th>
                <th style={{ width: '120px', textAlign: 'center' }}>⏳ Pendientes</th>
                <th style={{ width: '150px' }}>Estado</th>
              </tr>
            </thead>
            <tbody>
              {data.motoqueros.map((motoquero) => (
                <Fragment key={motoquero.motoquero_id}>
                  {/* FILA PRINCIPAL: Motoquero */}
                  <tr 
                    onClick={() => toggleMotoquero(motoquero.motoquero_id)}
                    className={`${styles.motoqueroRow} ${expandidos.has(motoquero.motoquero_id) ? styles.motoqueroRowExpanded : ''}`}
                  >
                    <td style={{ textAlign: 'center', fontSize: '1.2rem' }}>
                      {expandidos.has(motoquero.motoquero_id) ? '▼' : '▶'}
                    </td>
                    <td>
                      <strong>{motoquero.nombre}</strong>
                      {!motoquero.activo && <span className={styles.textSecondary}> (inactivo)</span>}
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <strong>{motoquero.total_envios}</strong>
                    </td>
                    <td style={{ textAlign: 'center', color: 'var(--success)' }}>
                      <strong>{motoquero.entregados}</strong>
                    </td>
                    <td style={{ textAlign: 'center', color: 'var(--warning)' }}>
                      <strong>{motoquero.en_camino}</strong>
                    </td>
                    <td style={{ textAlign: 'center', color: 'var(--error)' }}>
                      <strong>{motoquero.pendientes}</strong>
                    </td>
                    <td>
                      {motoquero.entregados === motoquero.total_envios ? (
                        <strong style={{ color: 'var(--success)' }}>✅ Completado</strong>
                      ) : (
                        <strong style={{ color: 'var(--warning)' }}>⏳ En progreso</strong>
                      )}
                    </td>
                  </tr>

                  {/* FILAS EXPANDIDAS: Detalle de envíos */}
                  {expandidos.has(motoquero.motoquero_id) && (
                    <tr className={styles.filaExpandida}>
                      <td colSpan="7" style={{ padding: 0 }}>
                        <div style={{ padding: '1rem', background: 'var(--bg-secondary)' }}>
                          <table className={styles.tablaTesla} style={{ marginBottom: 0 }}>
                            <thead>
                              <tr>
                                <th>Código ML</th>
                                <th>Dirección</th>
                                <th>Destinatario</th>
                                <th>Zona</th>
                                <th>Estado</th>
                                <th>Horarios</th>
                              </tr>
                            </thead>
                            <tbody>
                              {motoquero.envios.map((envio) => (
                                <tr key={envio.mlshippingid}>
                                  <td>
                                    <code className={styles.codeTag}>{envio.mlshippingid}</code>
                                  </td>
                                  <td>
                                    <div>📍 {envio.direccion}</div>
                                  </td>
                                  <td>
                                    {envio.destinatario ? (
                                      <>
                                        <div>{envio.destinatario}</div>
                                        {envio.telefono && (
                                          <div className={styles.textSecondary}>📞 {envio.telefono}</div>
                                        )}
                                      </>
                                    ) : (
                                      <span className={styles.textSecondary}>-</span>
                                    )}
                                  </td>
                                  <td>
                                    {envio.zona_nombre || <span className={styles.textSecondary}>-</span>}
                                  </td>
                                  <td>
                                    {getEstadoBadge(envio.estado_display)}
                                    <div className={styles.textSecondary} style={{ fontSize: '0.75rem', marginTop: '0.25rem' }}>
                                      ML: {envio.estado_ml}
                                    </div>
                                  </td>
                                  <td>
                                    <div style={{ fontSize: '0.85rem' }}>
                                      <div className={styles.textSecondary}>
                                        Asignado: {new Date(envio.asignado_at).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}
                                      </div>
                                      {envio.entregado_at && (
                                        <div style={{ color: 'var(--success)', marginTop: '0.25rem' }}>
                                          Entregado: {new Date(envio.entregado_at).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}
                                        </div>
                                      )}
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
