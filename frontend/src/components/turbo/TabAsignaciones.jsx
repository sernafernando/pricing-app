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
      {/* HEADER */}
      <div className={styles.header}>
        <div>
          <h2>📋 Asignaciones del Día</h2>
          <p className={styles.subtitle}>
            {data.fecha} • <strong>{data.total_asignaciones} envíos</strong> • 
            <span className={styles.successText}> ✅ {data.total_entregados} entregados</span> • 
            <span className={styles.errorText}> ⏳ {data.total_pendientes} pendientes</span>
          </p>
        </div>
        <button onClick={fetchAsignaciones} className={styles.btnSecondary}>
          🔄 Actualizar
        </button>
      </div>

      {/* TABLA RESUMEN */}
      <div className={styles.card}>
        <h3 className={styles.cardTitle}>Resumen por Motoquero</h3>
        <div className={styles.tableContainer}>
          <table className={styles.tablaTesla}>
            <thead>
              <tr>
                <th className={styles.colExpand}></th>
                <th>Motoquero</th>
                <th className={styles.colNumber}>Total</th>
                <th className={styles.colNumber}>✅ OK</th>
                <th className={styles.colNumber}>🚚 Camino</th>
                <th className={styles.colNumber}>⏳ Pend</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {data.motoqueros.map((m) => (
                <Fragment key={m.motoquero_id}>
                  <tr 
                    onClick={() => toggleMotoquero(m.motoquero_id)}
                    className={styles.clickableRow}
                  >
                    <td className={styles.colExpand}>
                      {expandidos.has(m.motoquero_id) ? '▼' : '▶'}
                    </td>
                    <td>
                      <strong>{m.nombre}</strong>
                      {!m.activo && <span className={styles.textMuted}> (inactivo)</span>}
                    </td>
                    <td className={styles.colNumber}><strong>{m.total_envios}</strong></td>
                    <td className={`${styles.colNumber} ${styles.successText}`}><strong>{m.entregados}</strong></td>
                    <td className={`${styles.colNumber} ${styles.warningText}`}><strong>{m.en_camino}</strong></td>
                    <td className={`${styles.colNumber} ${styles.errorText}`}><strong>{m.pendientes}</strong></td>
                    <td>
                      {m.entregados === m.total_envios ? (
                        <span className={`${styles.badge} ${styles.badgeSuccess}`}>✅ Completado</span>
                      ) : (
                        <span className={`${styles.badge} ${styles.badgeWarning}`}>⏳ En progreso</span>
                      )}
                    </td>
                  </tr>

                  {/* DETALLE EXPANDIDO */}
                  {expandidos.has(m.motoquero_id) && (
                    <tr className={styles.expandedRow}>
                      <td colSpan="7" className={styles.expandedCell}>
                        <div className={styles.expandedContent}>
                          <table className={styles.tablaTesla}>
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
                              {m.envios.map((e) => (
                                <tr key={e.mlshippingid}>
                                  <td>
                                    <code className={styles.codeTag}>{e.mlshippingid}</code>
                                  </td>
                                  <td>📍 {e.direccion}</td>
                                  <td>
                                    {e.destinatario ? (
                                      <>
                                        <div>{e.destinatario}</div>
                                        {e.telefono && <div className={styles.textMuted}>📞 {e.telefono}</div>}
                                      </>
                                    ) : (
                                      <span className={styles.textMuted}>-</span>
                                    )}
                                  </td>
                                  <td>{e.zona_nombre || <span className={styles.textMuted}>-</span>}</td>
                                  <td>
                                    <span className={`${styles.badge} ${
                                      e.estado_display === 'entregado' ? styles.badgeSuccess :
                                      e.estado_display === 'en_camino' ? styles.badgeWarning :
                                      styles.badgeError
                                    }`}>
                                      {e.estado_display === 'entregado' && '✅ Entregado'}
                                      {e.estado_display === 'en_camino' && '🚚 En camino'}
                                      {e.estado_display === 'pendiente' && '⏳ Pendiente'}
                                    </span>
                                    <div className={styles.textMuted}>ML: {e.estado_ml}</div>
                                  </td>
                                  <td className={styles.textMuted}>
                                    <div>Asignado: {new Date(e.asignado_at).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}</div>
                                    {e.entregado_at && (
                                      <div className={styles.successText}>
                                        Entregado: {new Date(e.entregado_at).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}
                                      </div>
                                    )}
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
