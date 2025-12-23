import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import styles from '../pages/PedidosPreparacion.module.css';

const API_URL = 'https://pricing.gaussonline.com.ar/api';

export default function TabPedidosExport() {
  const [pedidos, setPedidos] = useState([]);
  const [estadisticas, setEstadisticas] = useState(null);
  const [usuarios, setUsuarios] = useState([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  
  // Filtros
  const [soloActivos, setSoloActivos] = useState(true);
  const [userId, setUserId] = useState(''); // Filtro por user_id
  const [soloML, setSoloML] = useState(false);
  const [soloTN, setSoloTN] = useState(false);
  const [sinCodigoEnvio, setSinCodigoEnvio] = useState(false);
  const [search, setSearch] = useState('');
  
  const getToken = () => localStorage.getItem('token');

  const cargarUsuarios = useCallback(async () => {
    try {
      const response = await axios.get(
        `${API_URL}/usuarios-erp?solo_activos=true`,
        { headers: { Authorization: `Bearer ${getToken()}` } }
      );
      setUsuarios(response.data);
    } catch (error) {
      console.error('Error cargando usuarios:', error);
    }
  }, []);

  const cargarEstadisticas = useCallback(async () => {
    try {
      const response = await axios.get(
        `${API_URL}/pedidos-export/estadisticas-sincronizacion`,
        { headers: { Authorization: `Bearer ${getToken()}` } }
      );
      setEstadisticas(response.data);
    } catch (error) {
      console.error('Error cargando estadísticas:', error);
    }
  }, []);

  const cargarPedidos = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.append('solo_activos', soloActivos);
      params.append('limit', '500');
      
      // Filtros opcionales
      if (userId) params.append('user_id', userId);
      if (soloML) params.append('solo_ml', 'true');
      if (soloTN) params.append('solo_tn', 'true');
      if (sinCodigoEnvio) params.append('sin_codigo_envio', 'true');
      
      const response = await axios.get(
        `${API_URL}/pedidos-export/por-export/80?${params}`,
        { headers: { Authorization: `Bearer ${getToken()}` } }
      );
      
      let data = response.data;
      
      // Filtro de búsqueda local (para texto libre)
      if (search) {
        const searchLower = search.toLowerCase();
        data = data.filter(p => 
          p.soh_id?.toString().includes(searchLower) ||
          p.ml_order_id?.toLowerCase().includes(searchLower) ||
          p.direccion_entrega?.toLowerCase().includes(searchLower) ||
          p.observacion?.toLowerCase().includes(searchLower)
        );
      }
      
      setPedidos(data);
    } catch (error) {
      console.error('Error cargando pedidos:', error);
    } finally {
      setLoading(false);
    }
  }, [soloActivos, userId, soloML, soloTN, sinCodigoEnvio, search]);

  const sincronizarPedidos = async () => {
    if (!confirm('¿Sincronizar pedidos desde el ERP? Esto puede tardar unos segundos.')) return;
    
    setSyncing(true);
    try {
      const response = await axios.post(
        `${API_URL}/pedidos-export/sincronizar-export-80`,
        {},
        { headers: { Authorization: `Bearer ${getToken()}` } }
      );
      
      alert(`Sincronización iniciada: ${response.data.registros_obtenidos} registros`);
      
      // Recargar después de 3 segundos
      setTimeout(() => {
        cargarEstadisticas();
        cargarPedidos();
      }, 3000);
      
    } catch (error) {
      console.error('Error sincronizando:', error);
      alert('Error al sincronizar pedidos');
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    cargarUsuarios();
    cargarEstadisticas();
  }, [cargarUsuarios, cargarEstadisticas]);

  useEffect(() => {
    cargarPedidos();
  }, [cargarPedidos]);

  const formatearFecha = (fecha) => {
    if (!fecha) return '-';
    const date = new Date(fecha);
    return date.toLocaleString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    });
  };

  return (
    <div>
      {/* Estadísticas */}
      {estadisticas && (
        <div className={styles.statsContainer}>
          <div className={styles.statCard}>
            <div className={styles.statLabel}>Total Pedidos</div>
            <div className={styles.statValue}>{estadisticas.total_pedidos}</div>
          </div>
          <div className={styles.statCard}>
            <div className={styles.statLabel}>Activos</div>
            <div className={styles.statValue} style={{ color: '#10b981' }}>
              {estadisticas.activos}
            </div>
          </div>
          <div className={styles.statCard}>
            <div className={styles.statLabel}>Archivados</div>
            <div className={styles.statValue} style={{ color: '#6b7280' }}>
              {estadisticas.archivados}
            </div>
          </div>
          <div className={styles.statCard}>
            <div className={styles.statLabel}>% Activos</div>
            <div className={styles.statValue}>
              {estadisticas.porcentaje_activos.toFixed(1)}%
            </div>
          </div>
        </div>
      )}

      {/* Botón sincronizar */}
      <div style={{ marginBottom: '16px' }}>
        <button
          onClick={sincronizarPedidos}
          disabled={syncing}
          className={styles.syncButton}
        >
          {syncing ? '⏳ Sincronizando...' : '🔄 Sincronizar desde ERP'}
        </button>
      </div>

      {/* Filtros */}
      <div className={styles.filtrosContainer}>
        <div className={styles.filtrosRow}>
          <button
            className={`${styles.vistaBtn} ${soloActivos ? styles.vistaActiva : ''}`}
            onClick={() => setSoloActivos(!soloActivos)}
          >
            {soloActivos ? '✓ Solo Activos' : 'Ver Todos'}
          </button>

          <select
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            className={styles.select}
          >
            <option value="">Todos los usuarios</option>
            <option value="50021">🛒 TiendaNube (50021)</option>
            {usuarios.map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.user_name || u.user_loginname} ({u.user_id})
              </option>
            ))}
          </select>

          <div className={styles.checkboxGroup}>
            <label className={styles.checkboxLabel}>
              <input
                type="checkbox"
                checked={soloML}
                onChange={(e) => setSoloML(e.target.checked)}
              />
              Solo ML
            </label>
            <label className={styles.checkboxLabel}>
              <input
                type="checkbox"
                checked={soloTN}
                onChange={(e) => setSoloTN(e.target.checked)}
              />
              Solo TN
            </label>
            <label className={styles.checkboxLabel}>
              <input
                type="checkbox"
                checked={sinCodigoEnvio}
                onChange={(e) => setSinCodigoEnvio(e.target.checked)}
              />
              Sin etiqueta
            </label>
          </div>
          
          <input
            type="text"
            placeholder="Buscar por ID, ML Order, dirección..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={styles.searchInput}
          />
        </div>
      </div>

      {/* Tabla de pedidos */}
      {loading ? (
        <div className={styles.loading}>Cargando pedidos...</div>
      ) : pedidos.length === 0 ? (
        <div className={styles.empty}>No se encontraron pedidos</div>
      ) : (
        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>ID Pedido</th>
                <th>Fecha</th>
                <th>Cliente</th>
                <th>Dirección</th>
                <th>ML Order</th>
                <th>TN Order</th>
                <th>Total</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {pedidos.map((pedido) => (
                <tr key={pedido.soh_id}>
                  <td>
                    <strong>#{pedido.soh_id}</strong>
                  </td>
                  <td>{formatearFecha(pedido.fecha_pedido)}</td>
                  <td>
                    {pedido.nombre_cliente || `Cliente ${pedido.cust_id}`}
                  </td>
                  <td>
                    <div style={{ 
                      maxWidth: '300px', 
                      overflow: 'hidden', 
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap'
                    }}>
                      {pedido.direccion_entrega || '-'}
                    </div>
                  </td>
                  <td>
                    {pedido.ml_order_id ? (
                      <span className={styles.badge} style={{ background: '#ffe600', color: '#000' }}>
                        {pedido.ml_order_id}
                      </span>
                    ) : '-'}
                  </td>
                  <td>
                    {pedido.tiendanube_order_id ? (
                      <span className={styles.badge} style={{ background: '#3b82f6' }}>
                        {pedido.tiendanube_order_id}
                      </span>
                    ) : '-'}
                  </td>
                  <td>
                    {pedido.total ? `$${pedido.total.toLocaleString('es-AR')}` : '-'}
                  </td>
                  <td>
                    <span className={`${styles.badge} ${pedido.estado === 1 ? styles.badgeSuccess : styles.badgeWarning}`}>
                      {pedido.estado === 1 ? 'Pendiente' : `Estado ${pedido.estado}`}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      
      <div style={{ marginTop: '16px', color: 'var(--text-secondary)', fontSize: '12px' }}>
        Mostrando {pedidos.length} pedidos {soloActivos ? 'activos' : 'totales'}
      </div>
    </div>
  );
}
