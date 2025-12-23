import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import styles from './TabPedidosExport.module.css';

const API_URL = 'https://pricing.gaussonline.com.ar/api';

export default function TabPedidosExport() {
  const [pedidos, setPedidos] = useState([]);
  const [estadisticas, setEstadisticas] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [pedidoSeleccionado, setPedidoSeleccionado] = useState(null);
  
  // Filtros
  const [soloActivos, setSoloActivos] = useState(true);
  const [soloTN, setSoloTN] = useState(false);
  const [search, setSearch] = useState('');
  
  const getToken = () => localStorage.getItem('token');

  const cargarEstadisticas = useCallback(async () => {
    try {
      const response = await axios.get(
        `${API_URL}/pedidos-simple/estadisticas`,
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
      params.append('limit', '200');

      const response = await axios.get(
        `${API_URL}/pedidos-simple?${params.toString()}`,
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
        `${API_URL}/pedidos-simple/sincronizar`,
        {},
        { 
          headers: { Authorization: `Bearer ${getToken()}` },
          timeout: 120000 // 2 minutos timeout
        }
      );
      
      alert(`✅ Sincronización OK:\n- Registros obtenidos: ${response.data.registros_obtenidos || 0}`);
      
      await cargarPedidos();
      await cargarEstadisticas();
    } catch (error) {
      console.error('Error en sincronización:', error);
      alert('❌ Error en sincronización: ' + (error.response?.data?.detail || error.message));
    } finally {
      setSyncing(false);
    }
  };

  const getUserLabel = (userId) => {
    const labels = {
      50003: 'TiendaNube Web',
      50006: 'MercadoLibre',
      50007: 'Notas/Devoluciones',
      50009: 'Gauss Interno',
      50010: 'Gauss Mayorista',
      50011: 'Gauss Minorista',
      50015: 'Gauss Corporativo',
      50017: 'Gauss General',
      50021: 'TiendaNube',
      50031: 'Gauss Gobierno',
    };
    return labels[userId] || `User ${userId}`;
  };

  useEffect(() => {
    cargarPedidos();
    cargarEstadisticas();
  }, [cargarPedidos, cargarEstadisticas]);

  return (
    <div className={styles.container}>
      {/* Header con estadísticas */}
      <div className={styles.statsGrid}>
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
          <div className={styles.statTime}>
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
          className={styles.btnSync}
        >
          {syncing ? '⏳ Sincronizando...' : '🔄 Sincronizar desde ERP'}
        </button>

        <div className={styles.filters}>
          <label className={styles.checkbox}>
            <input 
              type="checkbox" 
              checked={soloActivos} 
              onChange={(e) => setSoloActivos(e.target.checked)} 
            />
            <span>Solo Activos</span>
          </label>

          <label className={styles.checkbox}>
            <input 
              type="checkbox" 
              checked={soloTN} 
              onChange={(e) => setSoloTN(e.target.checked)} 
            />
            <span>🛒 Solo TiendaNube</span>
          </label>

          <input
            type="text"
            placeholder="Buscar por cliente, orden TN o ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={styles.searchInput}
          />

          <button onClick={cargarPedidos} className={styles.btnFilter}>
            🔍 Filtrar
          </button>
        </div>
      </div>

      {/* Tabla de pedidos */}
      {loading ? (
        <div className={styles.loading}>Cargando pedidos...</div>
      ) : pedidos.length === 0 ? (
        <div className={styles.empty}>No hay pedidos con los filtros seleccionados</div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>ID PEDIDO</th>
                <th>CLIENTE</th>
                <th>ITEMS</th>
                <th>ORDEN TN</th>
                <th>DIRECCIÓN DE ENVÍO</th>
                <th>OBSERVACIONES</th>
                <th>FECHA ENVÍO</th>
                <th>ACCIONES</th>
              </tr>
            </thead>
            <tbody>
              {pedidos.map((pedido) => (
                <tr 
                  key={pedido.soh_id}
                  onClick={() => setPedidoSeleccionado(pedido)}
                  className={styles.row}
                >
                  <td>
                    <div className={styles.pedidoId}>
                      <strong>GBP: {pedido.soh_id}</strong>
                      {pedido.user_id && (
                        <div className={styles.userBadge}>
                          {getUserLabel(pedido.user_id)}
                        </div>
                      )}
                    </div>
                  </td>
                  
                  <td>
                    <div className={styles.cliente}>
                      <strong>{pedido.nombre_cliente || 'Sin nombre'}</strong>
                      {pedido.cust_id && (
                        <div className={styles.clienteId}>ID: {pedido.cust_id}</div>
                      )}
                    </div>
                  </td>
                  
                  <td className={styles.textCenter}>
                    <div className={styles.itemsBadge}>
                      {pedido.total_items} {pedido.total_items === 1 ? 'item' : 'items'}
                    </div>
                  </td>
                  
                  <td>
                    {pedido.tiendanube_number ? (
                      <div className={styles.ordenTN}>
                        <div className={styles.ordenTNNumber}>
                          🛒 {pedido.tiendanube_number}
                        </div>
                        {pedido.ws_internalid && (
                          <div className={styles.ordenTNId}>ID: {pedido.ws_internalid}</div>
                        )}
                      </div>
                    ) : pedido.ws_internalid ? (
                      <div className={styles.ordenTNId}>TN #{pedido.ws_internalid}</div>
                    ) : (
                      <span className={styles.textMuted}>—</span>
                    )}
                  </td>
                  
                  <td>
                    {pedido.soh_deliveryaddress || pedido.tiendanube_shipping_address ? (
                      <div className={styles.direccion}>
                        <div>{pedido.soh_deliveryaddress || pedido.tiendanube_shipping_address}</div>
                        {pedido.tiendanube_shipping_city && (
                          <div className={styles.localidad}>
                            {pedido.tiendanube_shipping_city}, {pedido.tiendanube_shipping_province}
                          </div>
                        )}
                        {pedido.tiendanube_shipping_phone && (
                          <div className={styles.telefono}>
                            📞 {pedido.tiendanube_shipping_phone}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className={styles.sinDireccion}>Sin dirección</span>
                    )}
                  </td>
                  
                  <td>
                    {pedido.soh_observation1 ? (
                      <div className={styles.observaciones}>{pedido.soh_observation1}</div>
                    ) : (
                      <span className={styles.textMuted}>—</span>
                    )}
                  </td>
                  
                  <td className={styles.textCenter}>
                    {pedido.soh_deliverydate ? (
                      new Date(pedido.soh_deliverydate).toLocaleDateString('es-AR')
                    ) : (
                      <span className={styles.textMuted}>—</span>
                    )}
                  </td>

                  <td className={styles.textCenter}>
                    <button 
                      onClick={(e) => {
                        e.stopPropagation();
                        setPedidoSeleccionado(pedido);
                      }}
                      className={styles.btnDetalle}
                    >
                      Ver Detalle
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Modal de detalle */}
      {pedidoSeleccionado && (
        <div className={styles.modal} onClick={() => setPedidoSeleccionado(null)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2>Pedido GBP: {pedidoSeleccionado.soh_id}</h2>
              <button 
                onClick={() => setPedidoSeleccionado(null)}
                className={styles.btnClose}
              >
                ✕
              </button>
            </div>

            <div className={styles.modalBody}>
              <div className={styles.infoGrid}>
                <div className={styles.infoSection}>
                  <h3>Información del Cliente</h3>
                  <div className={styles.infoRow}>
                    <strong>Cliente GBP:</strong> {pedidoSeleccionado.nombre_cliente || 'Sin nombre'}
                  </div>
                  <div className={styles.infoRow}>
                    <strong>ID Cliente:</strong> {pedidoSeleccionado.cust_id || 'N/A'}
                  </div>
                  <div className={styles.infoRow}>
                    <strong>Canal:</strong> {getUserLabel(pedidoSeleccionado.user_id)}
                  </div>
                  {pedidoSeleccionado.tiendanube_recipient_name && (
                    <div className={styles.infoRow}>
                      <strong>Destinatario TN:</strong> {pedidoSeleccionado.tiendanube_recipient_name}
                    </div>
                  )}
                </div>

                {pedidoSeleccionado.ws_internalid && (
                  <div className={styles.infoSection}>
                    <h3>Información TiendaNube</h3>
                    <div className={styles.infoRow}>
                      <strong>Pedido TN ID:</strong> {pedidoSeleccionado.ws_internalid}
                    </div>
                    {pedidoSeleccionado.tiendanube_number && (
                      <div className={styles.infoRow}>
                        <strong>Pedido TN #:</strong> {pedidoSeleccionado.tiendanube_number}
                      </div>
                    )}
                    {pedidoSeleccionado.tiendanube_shipping_phone && (
                      <div className={styles.infoRow}>
                        <strong>Teléfono TN:</strong> {pedidoSeleccionado.tiendanube_shipping_phone}
                      </div>
                    )}
                  </div>
                )}

                <div className={styles.infoSection}>
                  <h3>Dirección de Envío</h3>
                  {pedidoSeleccionado.soh_deliveryaddress || pedidoSeleccionado.tiendanube_shipping_address ? (
                    <>
                      <div className={styles.infoRow}>
                        <strong>Dirección:</strong> {pedidoSeleccionado.soh_deliveryaddress || pedidoSeleccionado.tiendanube_shipping_address}
                      </div>
                      {pedidoSeleccionado.tiendanube_shipping_city && (
                        <>
                          <div className={styles.infoRow}>
                            <strong>Localidad:</strong> {pedidoSeleccionado.tiendanube_shipping_city}
                          </div>
                          <div className={styles.infoRow}>
                            <strong>Provincia:</strong> {pedidoSeleccionado.tiendanube_shipping_province}
                          </div>
                          {pedidoSeleccionado.tiendanube_shipping_zipcode && (
                            <div className={styles.infoRow}>
                              <strong>Código Postal:</strong> {pedidoSeleccionado.tiendanube_shipping_zipcode}
                            </div>
                          )}
                        </>
                      )}
                    </>
                  ) : (
                    <div className={styles.textMuted}>Sin dirección de envío</div>
                  )}
                </div>

                {pedidoSeleccionado.soh_observation1 && (
                  <div className={styles.infoSection}>
                    <h3>Observaciones</h3>
                    <div className={styles.observacionesDetalle}>
                      {pedidoSeleccionado.soh_observation1}
                    </div>
                  </div>
                )}
                
                {pedidoSeleccionado.soh_internalannotation && (
                  <div className={styles.infoSection}>
                    <h3>Notas Internas</h3>
                    <div className={styles.observacionesDetalle}>
                      {pedidoSeleccionado.soh_internalannotation}
                    </div>
                  </div>
                )}
              </div>

              <div className={styles.itemsSection}>
                <h3>Items del Pedido:</h3>
                <div className={styles.cantidadTotal}>
                  Cantidad Total Items: {pedidoSeleccionado.total_items}
                </div>
                <table className={styles.itemsTable}>
                  <thead>
                    <tr>
                      <th>Item ID</th>
                      <th>Código</th>
                      <th>Descripción</th>
                      <th>Cantidad</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pedidoSeleccionado.items && pedidoSeleccionado.items.map((item, idx) => (
                      <tr key={idx}>
                        <td>{item.item_id}</td>
                        <td>{item.item_code || '—'}</td>
                        <td>{item.item_desc || 'Sin descripción'}</td>
                        <td className={styles.textCenter}>{item.cantidad}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
