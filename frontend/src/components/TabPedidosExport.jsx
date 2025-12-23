import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import styles from '../pages/PedidosPreparacion.module.css';

const API_URL = 'https://pricing.gaussonline.com.ar/api';

export default function TabPedidosExport() {
  const [pedidos, setPedidos] = useState([]);
  const [estadisticas, setEstadisticas] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  
  // Filtros
  const [soloActivos, setSoloActivos] = useState(true);
  const [soloTN, setSoloTN] = useState(false);
  const [search, setSearch] = useState('');
  
  const getToken = () => localStorage.getItem('token');

  const cargarEstadisticas = useCallback(async () => {
    try {
      const response = await axios.get(
        `${API_URL}/pedidos-export-v2/estadisticas`,
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
      if (soloTN) params.append('solo_tn', 'true');
      if (search) params.append('buscar', search);
      params.append('limit', '100');

      const response = await axios.get(
        `${API_URL}/pedidos-export-v2?${params.toString()}`,
        { headers: { Authorization: `Bearer ${getToken()}` } }
      );
      
      setPedidos(response.data);
    } catch (error) {
      console.error('Error cargando pedidos:', error);
      alert('Error cargando pedidos');
    } finally {
      setLoading(false);
    }
  }, [soloActivos, soloTN, search]);

  const sincronizarPedidos = async () => {
    if (!confirm('¿Sincronizar pedidos desde el ERP? Puede tardar 1-2 minutos.')) {
      return;
    }

    setSyncing(true);
    try {
      const response = await axios.post(
        `${API_URL}/pedidos-export-v2/sincronizar`,
        {},
        { headers: { Authorization: `Bearer ${getToken()}` } }
      );
      
      alert(`✅ Sincronización OK:\n- Nuevos: ${response.data.nuevos}\n- Actualizados: ${response.data.actualizados}\n- Archivados: ${response.data.archivados}`);
      
      // Recargar datos
      await cargarPedidos();
      await cargarEstadisticas();
    } catch (error) {
      console.error('Error en sincronización:', error);
      alert('❌ Error en sincronización: ' + (error.response?.data?.detail || error.message));
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    cargarPedidos();
    cargarEstadisticas();
  }, [cargarPedidos, cargarEstadisticas]);

  return (
    <div className={styles.tabContent}>
      {/* Header con estadísticas */}
      <div className={styles.statsContainer}>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Total Pedidos</div>
          <div className={styles.statValue}>{estadisticas?.total_pedidos || 0}</div>
        </div>
        
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Total Items</div>
          <div className={styles.statValue}>{estadisticas?.total_items || 0}</div>
        </div>
        
        <div className={styles.statCard}>
          <div className={styles.statLabel}>TiendaNube</div>
          <div className={styles.statValue}>{estadisticas?.con_tiendanube || 0}</div>
        </div>
        
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Sin Dirección</div>
          <div className={styles.statValue}>{estadisticas?.sin_direccion || 0}</div>
        </div>
        
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Última Sync</div>
          <div className={styles.statValue} style={{ fontSize: '14px' }}>
            {estadisticas?.ultima_sync 
              ? new Date(estadisticas.ultima_sync).toLocaleString('es-AR')
              : 'N/A'}
          </div>
        </div>
      </div>

      {/* Controles */}
      <div className={styles.controls}>
        <button 
          onClick={sincronizarPedidos} 
          disabled={syncing}
          className={styles.btnPrimary}
        >
          {syncing ? '⏳ Sincronizando...' : '🔄 Sincronizar desde ERP'}
        </button>

        <div className={styles.filters}>
          <label>
            <input 
              type="checkbox" 
              checked={soloActivos} 
              onChange={(e) => setSoloActivos(e.target.checked)} 
            />
            Solo Activos
          </label>

          <label>
            <input 
              type="checkbox" 
              checked={soloTN} 
              onChange={(e) => setSoloTN(e.target.checked)} 
            />
            🛒 Solo TiendaNube
          </label>

          <input
            type="text"
            placeholder="Buscar por cliente, orden TN o ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={styles.searchInput}
          />

          <button onClick={cargarPedidos} className={styles.btnSecondary}>
            🔍 Filtrar
          </button>
        </div>
      </div>

      {/* Tabla de pedidos */}
      {loading ? (
        <div className={styles.loading}>Cargando pedidos...</div>
      ) : pedidos.length === 0 ? (
        <div className={styles.emptyState}>No hay pedidos con los filtros seleccionados</div>
      ) : (
        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>ID Pedido</th>
                <th>Cliente</th>
                <th>Items</th>
                <th>Orden TN</th>
                <th>Dirección de Envío</th>
                <th>Observaciones</th>
                <th>Fecha Envío</th>
              </tr>
            </thead>
            <tbody>
              {pedidos.map((pedido) => (
                <tr key={pedido.id_pedido}>
                  <td className={styles.textCenter}>
                    <strong>{pedido.id_pedido}</strong>
                  </td>
                  
                  <td>
                    <div>
                      <strong>{pedido.nombre_cliente || 'Sin nombre'}</strong>
                      {pedido.id_cliente && (
                        <div className={styles.textMuted}>ID: {pedido.id_cliente}</div>
                      )}
                    </div>
                  </td>
                  
                  <td className={styles.textCenter}>
                    <div className={styles.badge}>
                      {pedido.total_items} {pedido.total_items === 1 ? 'item' : 'items'}
                    </div>
                    {pedido.items && pedido.items.length > 0 && (
                      <div className={styles.itemsList}>
                        {pedido.items.map(item => (
                          <div key={item.item_id} className={styles.textMuted}>
                            Item {item.item_id} × {item.cantidad}
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                  
                  <td>
                    {pedido.orden_tn ? (
                      <span className={styles.badgeSuccess}>
                        🛒 {pedido.orden_tn}
                      </span>
                    ) : pedido.order_id_tn ? (
                      <span className={styles.badgeWarning}>
                        TN #{pedido.order_id_tn}
                      </span>
                    ) : (
                      <span className={styles.textMuted}>—</span>
                    )}
                  </td>
                  
                  <td>
                    {pedido.direccion_envio || pedido.tn_shipping_address ? (
                      <div>
                        <div>{pedido.direccion_envio || pedido.tn_shipping_address}</div>
                        {pedido.tn_shipping_city && (
                          <div className={styles.textMuted}>
                            {pedido.tn_shipping_city}, {pedido.tn_shipping_province}
                          </div>
                        )}
                        {pedido.tn_shipping_phone && (
                          <div className={styles.textMuted}>
                            📞 {pedido.tn_shipping_phone}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className={styles.textMuted}>Sin dirección</span>
                    )}
                  </td>
                  
                  <td>
                    {pedido.observaciones ? (
                      <div className={styles.observaciones}>{pedido.observaciones}</div>
                    ) : (
                      <span className={styles.textMuted}>—</span>
                    )}
                  </td>
                  
                  <td>
                    {pedido.fecha_envio ? (
                      new Date(pedido.fecha_envio).toLocaleDateString('es-AR')
                    ) : (
                      <span className={styles.textMuted}>—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
