import { useState, useEffect, Fragment } from 'react';
import axios from 'axios';
import styles from './TabAsignaciones.module.css';
import '../../styles/buttons-tesla.css';

const API_URL = import.meta.env.VITE_API_URL || 'https://pricing.gaussonline.com.ar/api';

const limpiarNombreZona = (zona) => {
  if (!zona) return '-';
  return zona
    .replace(/ - Zona generada automáticamente.*$/i, '')
    .replace(/\(.*envíos.*\)/i, '')
    .trim();
};

const getBadgeEstado = (estado) => {
  const badges = {
    entregado: { text: 'Entregado', class: styles.badgeSuccess },
    en_camino: { text: 'En camino', class: styles.badgeWarning },
    pendiente: { text: 'Pendiente', class: styles.badgeError }
  };
  return badges[estado] || badges.pendiente;
};

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
      if (error.response?.status === 401 || error.response?.status === 403) {
        localStorage.removeItem('token');
        window.location.href = '/login';
        return;
      }
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

  const handleKeyDown = (e, motoqueroId) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggleMotoquero(motoqueroId);
    }
  };

  if (loading) {
    return (
      <div className={styles.loadingState}>
        <div className={styles.loadingSpinner} role="status" aria-label="Cargando"></div>
        <p className={styles.loadingText}>Cargando asignaciones del día...</p>
      </div>
    );
  }

  if (!data || data.total_asignaciones === 0) {
    return (
      <div className={styles.emptyState}>
        <div className={styles.emptyIcon} aria-hidden="true">📋</div>
        <p className={styles.emptyTitle}>No hay asignaciones para hoy</p>
        <p className={styles.emptySubtitle}>Ejecutá la asignación automática en el tab de Envíos</p>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {/* HEADER CON STATS */}
      <div className={styles.header}>
        <div className={styles.headerContent}>
          <h2 className={styles.title}>Asignaciones del Día</h2>
          <p className={styles.subtitle}>
            {data.fecha} &bull;{' '}
            <span className={styles.subtitleStrong}>{data.total_asignaciones} envíos</span> &bull;{' '}
            <span className={styles.statsSuccess}>{data.total_entregados} entregados</span> &bull;{' '}
            <span className={styles.statsWarning}>{data.total_pendientes} pendientes</span>
          </p>
        </div>
        <button 
          onClick={fetchAsignaciones} 
          className="btn-tesla secondary sm"
          aria-label="Actualizar asignaciones"
        >
          Actualizar
        </button>
      </div>

      {/* CARD CON TABLA */}
      <div className={styles.card}>
        <div className={styles.cardHeader}>
          <h3 className={styles.cardTitle}>Resumen por Motoquero</h3>
        </div>
        
        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead className={styles.tableHead}>
              <tr>
                <th className={styles.colExpand} aria-label="Expandir"></th>
                <th>Motoquero</th>
                <th className={styles.colNumber}>Total</th>
                <th className={styles.colNumber}>Entregados</th>
                <th className={styles.colNumber}>En camino</th>
                <th className={styles.colNumber}>Pendientes</th>
                <th className={styles.colStatus}>Estado</th>
              </tr>
            </thead>
            <tbody className={styles.tableBody}>
              {data.motoqueros.map((m) => {
                const isExpanded = expandidos.has(m.motoquero_id);
                return (
                  <Fragment key={m.motoquero_id}>
                    {/* FILA PRINCIPAL - RESUMEN MOTOQUERO */}
                    <tr 
                      onClick={() => toggleMotoquero(m.motoquero_id)}
                      onKeyDown={(e) => handleKeyDown(e, m.motoquero_id)}
                      className={styles.clickableRow}
                      tabIndex={0}
                      role="button"
                      aria-expanded={isExpanded}
                      aria-label={`Expandir detalles de ${m.nombre}`}
                    >
                      <td className={styles.colExpand}>
                        <span 
                          className={`${styles.expandIcon} ${isExpanded ? styles.expandIconOpen : ''}`}
                          aria-hidden="true"
                        >
                          ▶
                        </span>
                      </td>
                      <td>
                        <span className={styles.cellStrong}>{m.nombre}</span>
                        {!m.activo && (
                          <span className={styles.cellMuted}>(inactivo)</span>
                        )}
                      </td>
                      <td className={styles.colNumber}>
                        <span className={styles.cellStrong}>{m.total_envios}</span>
                      </td>
                      <td className={styles.colNumber}>
                        <span className={styles.cellSuccess}>{m.entregados}</span>
                      </td>
                      <td className={styles.colNumber}>
                        <span className={styles.cellWarning}>{m.en_camino}</span>
                      </td>
                      <td className={styles.colNumber}>
                        <span className={styles.cellError}>{m.pendientes}</span>
                      </td>
                      <td>
                        {m.entregados === m.total_envios ? (
                          <span className={`${styles.badge} ${styles.badgeSuccess}`}>Completado</span>
                        ) : (
                          <span className={`${styles.badge} ${styles.badgePrimary}`}>En progreso</span>
                        )}
                      </td>
                    </tr>

                    {/* FILA EXPANDIDA - DETALLE DE ENVÍOS */}
                    {isExpanded && (
                      <tr className={styles.expandedRow}>
                        <td colSpan="7" className={styles.expandedCell}>
                          <div className={styles.expandedContent}>
                            <h4 className={styles.expandedTitle}>
                              Envíos de {m.nombre} ({m.total_envios})
                            </h4>
                            
                            <div className={styles.tableContainer}>
                              <table className={styles.table}>
                                <thead className={styles.tableHead}>
                                  <tr>
                                    <th className={styles.colCode}>Código ML</th>
                                    <th>Dirección</th>
                                    <th className={styles.colDest}>Destinatario</th>
                                    <th className={styles.colState}>Estado</th>
                                    <th className={styles.colTime}>Horarios</th>
                                  </tr>
                                </thead>
                                <tbody className={styles.tableBody}>
                                  {m.envios.map((e) => {
                                    const badge = getBadgeEstado(e.estado_display);
                                    return (
                                      <tr key={e.mlshippingid}>
                                        <td>
                                          <code className={styles.codeTag}>{e.mlshippingid}</code>
                                        </td>
                                        <td>
                                          <div className={styles.addressMain}>{e.direccion}</div>
                                          {e.zona_nombre && (
                                            <div className={styles.addressZone}>
                                              Zona: {limpiarNombreZona(e.zona_nombre)}
                                            </div>
                                          )}
                                        </td>
                                        <td>
                                          {e.destinatario ? (
                                            <>
                                              <div className={styles.destName}>{e.destinatario}</div>
                                              {e.telefono && (
                                                <div className={styles.destPhone}>Tel: {e.telefono}</div>
                                              )}
                                            </>
                                          ) : (
                                            <span className={styles.cellMuted}>Sin datos</span>
                                          )}
                                        </td>
                                        <td>
                                          <span className={`${styles.badge} ${badge.class}`}>
                                            {badge.text}
                                          </span>
                                        </td>
                                        <td>
                                          <div className={styles.timeAssigned}>
                                            Asignado: {new Date(e.asignado_at).toLocaleTimeString('es-AR', { 
                                              hour: '2-digit', 
                                              minute: '2-digit' 
                                            })}
                                          </div>
                                          {e.entregado_at && (
                                            <div className={styles.timeDelivered}>
                                              Entregado: {new Date(e.entregado_at).toLocaleTimeString('es-AR', { 
                                                hour: '2-digit', 
                                                minute: '2-digit' 
                                              })}
                                            </div>
                                          )}
                                        </td>
                                      </tr>
                                    );
                                  })}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
