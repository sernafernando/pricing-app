import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import styles from './PedidosPreparacion.module.css';

const API_URL = 'https://pricing.gaussonline.com.ar/api';

// Componente Card para mostrar producto con sus componentes
function ProductoCard({ producto, componentes, onLoadComponentes, getBadgeClass }) {
  const [mostrarComponentes, setMostrarComponentes] = useState(false);

  const toggleComponentes = () => {
    if (!mostrarComponentes && !componentes) {
      onLoadComponentes();
    }
    setMostrarComponentes(!mostrarComponentes);
  };

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <div className={styles.cardProducto}>
          <strong className={styles.cardCodigo}>{producto.item_code || '-'}</strong>
          <span className={styles.cardDescripcion}>{producto.item_desc || '-'}</span>
        </div>
        <button 
          className={styles.cardToggle}
          onClick={toggleComponentes}
          title="Ver componentes"
        >
          {mostrarComponentes ? '▼' : '▶'}
        </button>
      </div>

      <div className={styles.cardStats}>
        <div className={styles.cardStat}>
          <span className={styles.cardStatLabel}>Cantidad</span>
          <span className={styles.cardStatValue}>{Math.round(producto.cantidad)}</span>
        </div>
        <div className={styles.cardStat}>
          <span className={styles.cardStatLabel}>Paquetes</span>
          <span className={styles.cardStatValue}>{producto.prepara_paquete}</span>
        </div>
        <div className={styles.cardStat}>
          <span className={styles.cardStatLabel}>Tipo Envío</span>
          <span className={`${styles.badge} ${getBadgeClass(producto.ml_logistic_type)}`}>
            {producto.ml_logistic_type || 'N/A'}
          </span>
        </div>
      </div>

      {mostrarComponentes && (
        <div className={styles.cardComponentes}>
          <div className={styles.componentesHeader}>
            <strong>Componentes:</strong>
          </div>
          {!componentes ? (
            <div className={styles.componentesLoading}>Cargando...</div>
          ) : componentes.length === 0 ? (
            <div className={styles.componentesEmpty}>Sin componentes asociados</div>
          ) : (
            <div className={styles.componentesList}>
              {componentes.map((comp) => (
                <div key={comp.item_id} className={styles.componenteItem}>
                  <div className={styles.componenteInfo}>
                    <strong>{comp.item_code}</strong>
                    <span>{comp.item_desc}</span>
                  </div>
                  <div className={styles.componenteCantidad}>
                    x {comp.cantidad}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

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
  const [modoVista, setModoVista] = useState('lista'); // 'lista' o 'cards'
  const [componentes, setComponentes] = useState({}); // Cache de componentes por item_id

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

      console.log('[PedidosPreparacion] Cargando con params:', {
        tipoEnvio,
        search,
        vistaProduccion,
        url: `${API_URL}/pedidos-preparacion/resumen?${params}`
      });

      const response = await axios.get(`${API_URL}/pedidos-preparacion/resumen?${params}`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      console.log('[PedidosPreparacion] Resultados:', response.data.length, 'productos');
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

  const cargarComponentes = useCallback(async (itemId) => {
    try {
      const response = await axios.get(`${API_URL}/pedidos-preparacion/componentes/${itemId}`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      setComponentes(prev => ({ ...prev, [itemId]: response.data }));
    } catch (error) {
      console.error('Error cargando componentes:', error);
      setComponentes(prev => ({ ...prev, [itemId]: [] }));
    }
  }, []);

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

          <div className={styles.modoVistaButtons}>
            <button
              className={`${styles.modoVistaBtn} ${modoVista === 'lista' ? styles.modoVistaActivo : ''}`}
              onClick={() => setModoVista('lista')}
              title="Vista Lista"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
            <button
              className={`${styles.modoVistaBtn} ${modoVista === 'cards' ? styles.modoVistaActivo : ''}`}
              onClick={() => setModoVista('cards')}
              title="Vista Cards"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="7" height="7" />
                <rect x="14" y="3" width="7" height="7" />
                <rect x="3" y="14" width="7" height="7" />
                <rect x="14" y="14" width="7" height="7" />
              </svg>
            </button>
          </div>

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
      ) : modoVista === 'lista' ? (
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
      ) : (
        <div className={styles.cardsContainer}>
          {resumen.length === 0 ? (
            <div className={styles.empty}>No hay datos para mostrar</div>
          ) : (
            resumen.map((r) => (
              <ProductoCard
                key={r.id}
                producto={r}
                componentes={componentes[r.item_id]}
                onLoadComponentes={() => cargarComponentes(r.item_id)}
                getBadgeClass={getBadgeClass}
              />
            ))
          )}
        </div>
      )}

      {/* Contador de resultados */}
      <div className={styles.footer}>
        <span>Mostrando {resumen.length} productos</span>
      </div>
    </div>
  );
}
