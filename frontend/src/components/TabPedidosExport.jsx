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
  const [editandoDireccion, setEditandoDireccion] = useState(false);
  const [direccionForm, setDireccionForm] = useState({
    direccion: '',
    ciudad: '',
    provincia: '',
    codigo_postal: '',
    telefono: '',
    destinatario: '',
    notas: ''
  });
  
  // Filtros
  const [soloActivos, setSoloActivos] = useState(true);
  const [soloTN, setSoloTN] = useState(false);
  const [soloML, setSoloML] = useState(false);
  const [soloOtros, setSoloOtros] = useState(false);
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
      if (soloML) params.append('solo_ml', 'true');
      if (search) params.append('buscar', search);
      params.append('limit', '200');

      const response = await axios.get(
        `${API_URL}/pedidos-simple?${params.toString()}`,
        { headers: { Authorization: `Bearer ${getToken()}` } }
      );
      
      // Si "Solo Otros" está activado, filtrar en el frontend
      let pedidosFiltrados = response.data;
      if (soloOtros) {
        pedidosFiltrados = response.data.filter(p => 
          p.user_id !== 50021 && p.user_id !== 50006
        );
      }
      
      setPedidos(pedidosFiltrados);
    } catch (error) {
      console.error('Error cargando pedidos:', error);
      alert('Error cargando pedidos');
    } finally {
      setLoading(false);
    }
  }, [soloActivos, soloTN, soloML, soloOtros, search]);

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

  // Obtener dirección con prioridad: override > TN > ERP
  const getDireccionDisplay = (pedido) => {
    return {
      direccion: pedido.override_shipping_address || pedido.tiendanube_shipping_address || pedido.soh_deliveryaddress,
      ciudad: pedido.override_shipping_city || pedido.tiendanube_shipping_city,
      provincia: pedido.override_shipping_province || pedido.tiendanube_shipping_province,
      codigo_postal: pedido.override_shipping_zipcode || pedido.tiendanube_shipping_zipcode,
      telefono: pedido.override_shipping_phone || pedido.tiendanube_shipping_phone,
      destinatario: pedido.override_shipping_recipient || pedido.tiendanube_recipient_name,
      hasOverride: !!pedido.override_shipping_address
    };
  };

  const abrirEditarDireccion = (pedido) => {
    const dir = getDireccionDisplay(pedido);
    setDireccionForm({
      direccion: dir.direccion || '',
      ciudad: dir.ciudad || '',
      provincia: dir.provincia || '',
      codigo_postal: dir.codigo_postal || '',
      telefono: dir.telefono || '',
      destinatario: dir.destinatario || '',
      notas: pedido.override_notes || ''
    });
    setEditandoDireccion(true);
  };

  const guardarDireccion = async () => {
    try {
      await axios.put(
        `${API_URL}/pedidos-simple/${pedidoSeleccionado.soh_id}/override-shipping`,
        direccionForm,
        { headers: { Authorization: `Bearer ${getToken()}` } }
      );
      
      alert('✅ Dirección actualizada correctamente');
      setEditandoDireccion(false);
      await cargarPedidos();
      
      // Actualizar pedido seleccionado
      const pedidoActualizado = await axios.get(
        `${API_URL}/pedidos-simple?solo_activos=true&limit=1`,
        { headers: { Authorization: `Bearer ${getToken()}` } }
      );
      const updated = pedidoActualizado.data.find(p => p.soh_id === pedidoSeleccionado.soh_id);
      if (updated) setPedidoSeleccionado(updated);
      
    } catch (error) {
      console.error('Error guardando dirección:', error);
      alert('❌ Error guardando dirección: ' + (error.response?.data?.detail || error.message));
    }
  };

  const eliminarOverride = async () => {
    if (!confirm('¿Eliminar override y volver a los datos originales?')) return;
    
    try {
      await axios.delete(
        `${API_URL}/pedidos-simple/${pedidoSeleccionado.soh_id}/override-shipping`,
        { headers: { Authorization: `Bearer ${getToken()}` } }
      );
      
      alert('✅ Override eliminado, mostrando datos originales');
      setEditandoDireccion(false);
      await cargarPedidos();
      
    } catch (error) {
      console.error('Error eliminando override:', error);
      alert('❌ Error: ' + (error.response?.data?.detail || error.message));
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
              onChange={(e) => {
                setSoloTN(e.target.checked);
                if (e.target.checked) {
                  setSoloML(false);
                  setSoloOtros(false);
                }
              }} 
            />
            <span>🛒 Solo TiendaNube</span>
          </label>

          <label className={styles.checkbox}>
            <input 
              type="checkbox" 
              checked={soloML} 
              onChange={(e) => {
                setSoloML(e.target.checked);
                if (e.target.checked) {
                  setSoloTN(false);
                  setSoloOtros(false);
                }
              }} 
            />
            <span>📦 Solo MercadoLibre</span>
          </label>

          <label className={styles.checkbox}>
            <input 
              type="checkbox" 
              checked={soloOtros} 
              onChange={(e) => {
                setSoloOtros(e.target.checked);
                if (e.target.checked) {
                  setSoloTN(false);
                  setSoloML(false);
                }
              }} 
            />
            <span>🏢 Solo Otros Usuarios</span>
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
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h3>Dirección de Envío</h3>
                    <button 
                      onClick={() => abrirEditarDireccion(pedidoSeleccionado)}
                      className={styles.btnEditDireccion}
                      title="Editar dirección de envío"
                    >
                      ✏️ Editar
                    </button>
                  </div>
                  
                  {(() => {
                    const dir = getDireccionDisplay(pedidoSeleccionado);
                    return dir.direccion ? (
                      <>
                        {dir.hasOverride && (
                          <div className={styles.overrideBadge}>
                            ⚠️ Dirección modificada manualmente
                          </div>
                        )}
                        <div className={styles.infoRow}>
                          <strong>Dirección:</strong> {dir.direccion}
                        </div>
                        {dir.ciudad && (
                          <div className={styles.infoRow}>
                            <strong>Localidad:</strong> {dir.ciudad}
                          </div>
                        )}
                        {dir.provincia && (
                          <div className={styles.infoRow}>
                            <strong>Provincia:</strong> {dir.provincia}
                          </div>
                        )}
                        {dir.codigo_postal && (
                          <div className={styles.infoRow}>
                            <strong>Código Postal:</strong> {dir.codigo_postal}
                          </div>
                        )}
                        {dir.telefono && (
                          <div className={styles.infoRow}>
                            <strong>Teléfono:</strong> {dir.telefono}
                          </div>
                        )}
                        {dir.destinatario && (
                          <div className={styles.infoRow}>
                            <strong>Destinatario:</strong> {dir.destinatario}
                          </div>
                        )}
                      </>
                    ) : (
                      <div className={styles.textMuted}>Sin dirección de envío</div>
                    );
                  })()}
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

      {/* Modal de edición de dirección */}
      {editandoDireccion && pedidoSeleccionado && (
        <div className={styles.modal} onClick={() => setEditandoDireccion(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()} style={{ maxWidth: '600px' }}>
            <div className={styles.modalHeader}>
              <h2>✏️ Editar Dirección de Envío</h2>
              <button 
                onClick={() => setEditandoDireccion(false)}
                className={styles.btnClose}
              >
                ✕
              </button>
            </div>

            <div className={styles.modalBody}>
              <div style={{ marginBottom: '15px', padding: '10px', background: 'var(--info-bg)', borderRadius: '6px', color: 'var(--info-text)' }}>
                <strong>📝 Nota:</strong> Este cambio sobrescribe los datos de TN/ERP. Se usará para visualización Y para las etiquetas de envío.
              </div>

              <div className={styles.formGroup}>
                <label>Dirección Completa *</label>
                <textarea
                  value={direccionForm.direccion}
                  onChange={(e) => setDireccionForm({...direccionForm, direccion: e.target.value})}
                  rows="3"
                  className={styles.formInput}
                  placeholder="Calle, número, piso, depto"
                />
              </div>

              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Ciudad/Localidad</label>
                  <input
                    type="text"
                    value={direccionForm.ciudad}
                    onChange={(e) => setDireccionForm({...direccionForm, ciudad: e.target.value})}
                    className={styles.formInput}
                  />
                </div>

                <div className={styles.formGroup}>
                  <label>Provincia</label>
                  <input
                    type="text"
                    value={direccionForm.provincia}
                    onChange={(e) => setDireccionForm({...direccionForm, provincia: e.target.value})}
                    className={styles.formInput}
                  />
                </div>
              </div>

              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Código Postal</label>
                  <input
                    type="text"
                    value={direccionForm.codigo_postal}
                    onChange={(e) => setDireccionForm({...direccionForm, codigo_postal: e.target.value})}
                    className={styles.formInput}
                  />
                </div>

                <div className={styles.formGroup}>
                  <label>Teléfono</label>
                  <input
                    type="text"
                    value={direccionForm.telefono}
                    onChange={(e) => setDireccionForm({...direccionForm, telefono: e.target.value})}
                    className={styles.formInput}
                  />
                </div>
              </div>

              <div className={styles.formGroup}>
                <label>Destinatario</label>
                <input
                  type="text"
                  value={direccionForm.destinatario}
                  onChange={(e) => setDireccionForm({...direccionForm, destinatario: e.target.value})}
                  className={styles.formInput}
                  placeholder="Nombre de quien recibe"
                />
              </div>

              <div className={styles.formGroup}>
                <label>Notas Adicionales</label>
                <textarea
                  value={direccionForm.notas}
                  onChange={(e) => setDireccionForm({...direccionForm, notas: e.target.value})}
                  rows="2"
                  className={styles.formInput}
                  placeholder="Ej: Timbre roto, entregar por portería, etc."
                />
              </div>

              <div className={styles.modalActions}>
                <button 
                  onClick={guardarDireccion}
                  className={styles.btnGuardar}
                  disabled={!direccionForm.direccion}
                >
                  💾 Guardar
                </button>
                
                {getDireccionDisplay(pedidoSeleccionado).hasOverride && (
                  <button 
                    onClick={eliminarOverride}
                    className={styles.btnEliminar}
                  >
                    🗑️ Eliminar Override
                  </button>
                )}

                <button 
                  onClick={() => setEditandoDireccion(false)}
                  className={styles.btnCancelar}
                >
                  Cancelar
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
