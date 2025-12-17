import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import styles from './PedidosPreparacion.module.css';

const API_URL = 'https://pricing.gaussonline.com.ar/api';

export default function PedidosPreparacion() {
  const [resumen, setResumen] = useState([]);
  const [estadisticas, setEstadisticas] = useState(null);
  const [tiposEnvio, setTiposEnvio] = useState([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  // Filtros
  const [tipoEnvio, setTipoEnvio] = useState('');
  const [search, setSearch] = useState('');
  const [vistaProduccion, setVistaProduccion] = useState(false);

  const getToken = () => localStorage.getItem('token');

  const cargarTiposEnvio = useCallback(async () => {
    try {
      const response = await axios.get(`${API_URL}/pedidos-preparacion/tipos-envio`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      setTiposEnvio(response.data);
    } catch (error) {
      console.error('Error cargando tipos de envío:', error);
    }
  }, []);

  const cargarEstadisticas = useCallback(async () => {
    try {
      const response = await axios.get(`${API_URL}/pedidos-preparacion/estadisticas`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      setEstadisticas(response.data);
    } catch (error) {
      console.error('Error cargando estadísticas:', error);
    }
  }, []);

  const cargarDatos = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (tipoEnvio) params.append('logistic_type', tipoEnvio);
      if (search) params.append('search', search);
      if (vistaProduccion) params.append('vista_produccion', 'true');

      const response = await axios.get(`${API_URL}/pedidos-preparacion/resumen?${params}`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      setResumen(response.data);
    } catch (error) {
      console.error('Error cargando datos:', error);
    } finally {
      setLoading(false);
    }
  }, [tipoEnvio, search, vistaProduccion]);

  const sincronizarDatos = async () => {
    setSyncing(true);
    try {
      await axios.post(`${API_URL}/pedidos-preparacion/sync`, {}, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      // Recargar todo después de sincronizar
      await Promise.all([cargarDatos(), cargarEstadisticas(), cargarTiposEnvio()]);
    } catch (error) {
      console.error('Error sincronizando:', error);
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    cargarTiposEnvio();
    cargarEstadisticas();
  }, [cargarTiposEnvio, cargarEstadisticas]);

  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

  const formatearFecha = (fecha) => {
    if (!fecha) return '-';
    const date = new Date(fecha);
    return date.toLocaleString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    });
  };

  const getBadgeClass = (tipo) => {
    switch (tipo?.toLowerCase()) {
      case 'turbo': return styles.badgeTurbo;
      case 'self_service': return styles.badgeSelfService;
      case 'cross_docking': return styles.badgeCrossDocking;
      case 'drop_off': return styles.badgeDropOff;
      case 'xd_drop_off': return styles.badgeXdDropOff;
      default: return styles.badgeDefault;
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>Pedidos en Preparacion</h1>
        <div className={styles.headerButtons}>
          <button onClick={cargarDatos} className={styles.refreshBtn} disabled={loading}>
            Actualizar
          </button>
          <button
            onClick={sincronizarDatos}
            className={styles.syncBtn}
            disabled={syncing}
          >
            {syncing ? 'Sincronizando...' : 'Sincronizar ERP'}
          </button>
        </div>
      </div>

      {/* Estadísticas */}
      {estadisticas && (
        <div className={styles.statsGrid}>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{estadisticas.total_items}</div>
            <div className={styles.statLabel}>Items distintos</div>
          </div>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{Math.round(estadisticas.total_unidades)}</div>
            <div className={styles.statLabel}>Unidades total</div>
          </div>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{estadisticas.total_paquetes}</div>
            <div className={styles.statLabel}>Paquetes total</div>
          </div>
          {estadisticas.por_tipo_envio?.map((tipo) => (
            <div key={tipo.tipo} className={styles.statCard}>
              <div className={styles.statValue}>{Math.round(tipo.unidades)}</div>
              <div className={styles.statLabel}>{tipo.tipo}</div>
              <div className={styles.statSub}>{tipo.paquetes} paquetes</div>
            </div>
          ))}
        </div>
      )}

      {/* Última actualización */}
      {estadisticas?.ultima_actualizacion && (
        <div className={styles.ultimaActualizacion}>
          Ultima actualizacion: {formatearFecha(estadisticas.ultima_actualizacion)}
          <span className={styles.updateInfo}>(se actualiza cada 5 min)</span>
        </div>
      )}

      {/* Filtros */}
      <div className={styles.filtrosContainer}>
        <div className={styles.filtrosRow}>
          <button
            className={`${styles.vistaBtn} ${vistaProduccion ? styles.vistaActiva : ''}`}
            onClick={() => setVistaProduccion(!vistaProduccion)}
          >
            Vista Produccion
          </button>

          <select
            value={tipoEnvio}
            onChange={(e) => setTipoEnvio(e.target.value)}
            className={styles.select}
          >
            <option value="">Todos los envios</option>
            {tiposEnvio.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>

          <input
            type="text"
            placeholder="Buscar codigo o descripcion..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={styles.searchInput}
          />
        </div>
        {vistaProduccion && (
          <div className={styles.vistaInfo}>
            Filtrando: EAN con guion + Notebooks, NB, PC ARMADA, AIO
          </div>
        )}
      </div>

      {/* Contenido */}
      {loading ? (
        <div className={styles.loading}>Cargando pedidos...</div>
      ) : (
        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Producto</th>
                <th>Cantidad</th>
                <th>Paquetes</th>
                <th>Tipo Envio</th>
              </tr>
            </thead>
            <tbody>
              {resumen.length === 0 ? (
                <tr>
                  <td colSpan={4} className={styles.empty}>No hay datos para mostrar</td>
                </tr>
              ) : (
                resumen.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <div className={styles.producto}>
                        <strong>{r.item_code || '-'}</strong>
                        <span className={styles.descripcion}>{r.item_desc || '-'}</span>
                      </div>
                    </td>
                    <td className={styles.cantidadGrande}>{r.cantidad}</td>
                    <td className={styles.cantidad}>{r.prepara_paquete}</td>
                    <td>
                      <span className={`${styles.badge} ${getBadgeClass(r.ml_logistic_type)}`}>
                        {r.ml_logistic_type || 'N/A'}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Contador de resultados */}
      <div className={styles.footer}>
        <span>Mostrando {resumen.length} productos</span>
      </div>
    </div>
  );
}
