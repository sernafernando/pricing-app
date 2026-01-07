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
          <p>Cargando asignaciones del día...</p>
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
            <span className={styles.estadoEntregado}>✅ {data.total_entregados} entregados</span> • 
            <span className={styles.estadoPendiente}>⏳ {data.total_pendientes} pendientes</span>
          </p>
        </div>
        <button onClick={fetchAsignaciones} className={styles.btnSecondary}>
          🔄 Actualizar
        </button>
      </div>

      <div className={styles.card}>
        <table className={styles.tablaTesla}>
          <thead>
            <tr>
              <th style={{ width: '40px' }}></th>
              <th>Motoquero</th>
              <th>Total Envíos</th>
              <th>Entregados</th>
              <th>En Camino</th>
              <th>Pendientes</th>
              <th>Estado</th>
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
                  <td>
                    {expandidos.has(motoquero.motoquero_id) ? '▼' : '▶'}
                  </td>
                  <td>
                    <strong>{motoquero.nombre}</strong>
                    {!motoquero.activo && <span className={styles.textSecondary}> (inactivo)</span>}
                  </td>
                  <td><strong>{motoquero.total_envios}</strong></td>
                  <td><strong style={{ color: 'var(--success)' }}>{motoquero.entregados}</strong></td>
                  <td><strong style={{ color: 'var(--warning)' }}>{motoquero.en_camino}</strong></td>
                  <td><strong style={{ color: 'var(--error)' }}>{motoquero.pendientes}</strong></td>
                  <td>
                    {motoquero.entregados === motoquero.total_envios ? (
                      <strong style={{ color: 'var(--success)' }}>✅ Completado</strong>
                    ) : (
                      <strong style={{ color: 'var(--warning)' }}>⏳ En progreso</strong>
                    )}
                  </td>
                </tr>

                {/* FILAS EXPANDIDAS: Envíos del motoquero */}
                {expandidos.has(motoquero.motoquero_id) && motoquero.envios.map((envio) => (
                  <tr key={envio.mlshippingid} className={styles.filaExpandida}>
                    <td></td>
                    <td colSpan="2">
                      <code className={styles.codeTag}>{envio.mlshippingid}</code>
                      <div>📍 {envio.direccion}</div>
                      {envio.destinatario && (
                        <div className={styles.textSecondary}>
                          👤 {envio.destinatario}
                          {envio.telefono && <span> • 📞 {envio.telefono}</span>}
                        </div>
                      )}
                    </td>
                    <td>
                      {envio.zona_nombre && (
                        <span className={styles.textSecondary}>🗺️ {envio.zona_nombre}</span>
                      )}
                    </td>
                    <td colSpan="2">
                      {getEstadoBadge(envio.estado_display)}
                      <div className={styles.textSecondary}>ML: {envio.estado_ml}</div>
                    </td>
                    <td className={styles.textSecondary}>
                      <div>
                        Asignado: {new Date(envio.asignado_at).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}
                        {envio.entregado_at && (
                          <div className={styles.estadoEntregado}>
                            Entregado: {new Date(envio.entregado_at).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
