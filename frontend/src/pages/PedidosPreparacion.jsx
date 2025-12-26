import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import styles from './PedidosPreparacion.module.css';
import TabPedidosExport from '../components/TabPedidosExport';
import { usePermisos } from '../contexts/PermisosContext';

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
  const { tienePermiso } = usePermisos();
  
  const [resumen, setResumen] = useState([]);
  const [estadisticas, setEstadisticas] = useState(null);
  const [tiposEnvio, setTiposEnvio] = useState([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  // Tab activa
  const [tabActiva, setTabActiva] = useState('preparacion'); // 'preparacion' | 'export'

  // Filtros
  const [tipoEnvio, setTipoEnvio] = useState('');
  const [search, setSearch] = useState('');
  const [vistaProduccion, setVistaProduccion] = useState(false);
  const [modoVista, setModoVista] = useState('lista'); // 'lista' o 'cards'
  const [componentes, setComponentes] = useState({}); // Cache de componentes por item_id

  // Estados para banlist y prearmado
  const [procesando, setProcesando] = useState(new Set());
  const [modalPrearmado, setModalPrearmado] = useState(null); // { item_id, item_code, item_desc, cantidad_actual }

  const getToken = () => localStorage.getItem('token');
  
  // Permisos
  const puedeGestionarBanlist = tienePermiso('admin.gestionar_produccion_banlist');
  const puedeMarcarPrearmado = tienePermiso('produccion.marcar_prearmado');

  // Abrir modal de pre-armado
  const abrirModalPrearmado = (producto) => {
    if (!puedeMarcarPrearmado) {
      alert('No tenés permiso para marcar productos como pre-armados');
      return;
    }
    
    setModalPrearmado({
      item_id: producto.item_id,
      item_code: producto.item_code,
      item_desc: producto.item_desc,
      cantidad_actual: producto.cantidad_prearmada || 0,
      cantidad_pendiente: Math.round(producto.cantidad)
    });
  };

  // Guardar cantidad pre-armada
  const guardarPrearmado = async () => {
    const cantidad = parseInt(document.getElementById('input-prearmado').value);
    
    if (isNaN(cantidad) || cantidad < 0) {
      alert('Ingresá una cantidad válida');
      return;
    }
    
    if (cantidad === 0) {
      // Si es 0, desmarcar
      await desmarcarPrearmado(modalPrearmado.item_id);
      setModalPrearmado(null);
      return;
    }
    
    setProcesando(prev => new Set([...prev, modalPrearmado.item_id]));
    
    try {
      await axios.post(`${API_URL}/produccion-prearmado/${modalPrearmado.item_id}`, 
        { cantidad },
        { headers: { Authorization: `Bearer ${getToken()}` }}
      );
      
      // Actualizar estado local
      setResumen(prev => prev.map(item => 
        item.item_id === modalPrearmado.item_id 
          ? { ...item, esta_prearmado: true, cantidad_prearmada: cantidad }
          : item
      ));
      
      setModalPrearmado(null);
      
    } catch (error) {
      console.error('Error marcando prearmado:', error);
      alert('Error al marcar pre-armado: ' + (error.response?.data?.detail || error.message));
    } finally {
      setProcesando(prev => {
        const newSet = new Set(prev);
        newSet.delete(modalPrearmado.item_id);
        return newSet;
      });
    }
  };
  
  // Desmarcar pre-armado
  const desmarcarPrearmado = async (itemId) => {
    setProcesando(prev => new Set([...prev, itemId]));
    
    try {
      await axios.delete(`${API_URL}/produccion-prearmado/${itemId}`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      
      setResumen(prev => prev.map(item => 
        item.item_id === itemId 
          ? { ...item, esta_prearmado: false, cantidad_prearmada: 0 }
          : item
      ));
      
    } catch (error) {
      console.error('Error desmarcando prearmado:', error);
      alert('Error al desmarcar pre-armado: ' + (error.response?.data?.detail || error.message));
    } finally {
      setProcesando(prev => {
        const newSet = new Set(prev);
        newSet.delete(itemId);
        return newSet;
      });
    }
  };

  // Bannear producto
  const bannearProducto = async (itemId, itemCode, itemDesc) => {
    if (!puedeGestionarBanlist) {
      alert('No tenés permiso para gestionar el banlist de producción');
      return;
    }
    
    const motivo = prompt(`¿Por qué querés bannear "${itemCode} - ${itemDesc}" de la vista de producción?`);
    if (!motivo || motivo.trim() === '') return;
    
    setProcesando(prev => new Set([...prev, itemId]));
    
    try {
      await axios.post(`${API_URL}/produccion-banlist`, {
        item_id: itemId,
        motivo: motivo.trim()
      }, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      
      alert('✅ Producto baneado de la vista de producción');
      
      // Quitar de la lista local
      setResumen(prev => prev.filter(item => item.item_id !== itemId));
      
    } catch (error) {
      console.error('Error baneando producto:', error);
      alert('Error al bannear producto: ' + (error.response?.data?.detail || error.message));
    } finally {
      setProcesando(prev => {
        const newSet = new Set(prev);
        newSet.delete(itemId);
        return newSet;
      });
    }
  };

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
        <h1 className={styles.title}>Envíos Pendientes</h1>
      </div>

      {/* Navegación por Tabs */}
      <div className={styles.tabsContainer}>
        <button
          className={`${styles.tabBtn} ${tabActiva === 'preparacion' ? styles.tabActiva : ''}`}
          onClick={() => setTabActiva('preparacion')}
        >
          📦 Preparación
        </button>
        <button
          className={`${styles.tabBtn} ${tabActiva === 'export' ? styles.tabActiva : ''}`}
          onClick={() => setTabActiva('export')}
        >
          📋 Pedidos Pendientes
        </button>
      </div>

      {/* Contenido condicional según tab activa */}
      {tabActiva === 'preparacion' ? (
        <>
          {/* Botones de control del tab Preparación */}
          <div className={styles.tabControls}>
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
                    <th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {resumen.length === 0 ? (
                    <tr>
                      <td colSpan={5} className={styles.empty}>No hay datos para mostrar</td>
                    </tr>
                  ) : (
                    resumen.map((r) => (
                      <tr key={r.id}>
                        <td>
                          <div className={styles.producto}>
                            <strong>{r.item_code || '-'}</strong>
                            <span className={styles.descripcion}>{r.item_desc || '-'}</span>
                            {r.esta_prearmado && (
                              <span className={styles.badgePrearmado} title={`Pre-armando: ${r.cantidad_prearmada} unidades`}>
                                🔧 {r.cantidad_prearmada} pre-armando
                              </span>
                            )}
                          </div>
                        </td>
                        <td className={styles.cantidadGrande}>{r.cantidad}</td>
                        <td className={styles.cantidad}>{r.prepara_paquete}</td>
                        <td>
                          <span className={`${styles.badge} ${getBadgeClass(r.ml_logistic_type)}`}>
                            {r.ml_logistic_type || 'N/A'}
                          </span>
                        </td>
                        <td>
                          <div className={styles.accionesContainer}>
                            {puedeMarcarPrearmado && (
                              <button
                                className={`${styles.btnPrearmado} ${r.esta_prearmado ? styles.btnPrearmadoActivo : ''}`}
                                onClick={() => abrirModalPrearmado(r)}
                                disabled={procesando.has(r.item_id)}
                                title={r.esta_prearmado ? `Pre-armando: ${r.cantidad_prearmada}` : "Marcar como pre-armado"}
                              >
                                {procesando.has(r.item_id) ? '⏳' : (r.esta_prearmado ? `✓ ${r.cantidad_prearmada}` : '🔧 Pre-armar')}
                              </button>
                            )}
                            {vistaProduccion && puedeGestionarBanlist && (
                              <button
                                className={styles.btnBannear}
                                onClick={() => bannearProducto(r.item_id, r.item_code, r.item_desc)}
                                disabled={procesando.has(r.item_id)}
                                title="Bannear de vista producción"
                              >
                                🚫
                              </button>
                            )}
                          </div>
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
        </>
      ) : (
        <TabPedidosExport />
      )}

      {/* Modal Pre-armado */}
      {modalPrearmado && (
        <div className={styles.modalOverlay} onClick={() => setModalPrearmado(null)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h3>🔧 Pre-armar Producto</h3>
              <button className={styles.modalClose} onClick={() => setModalPrearmado(null)}>×</button>
            </div>
            
            <div className={styles.modalBody}>
              <div className={styles.modalProducto}>
                <strong>{modalPrearmado.item_code}</strong>
                <span>{modalPrearmado.item_desc}</span>
              </div>
              
              <div className={styles.modalInfo}>
                <div className={styles.modalInfoItem}>
                  <span>Cantidad pendiente:</span>
                  <strong>{modalPrearmado.cantidad_pendiente}</strong>
                </div>
                <div className={styles.modalInfoItem}>
                  <span>Actualmente pre-armando:</span>
                  <strong>{modalPrearmado.cantidad_actual}</strong>
                </div>
              </div>
              
              <div className={styles.modalInput}>
                <label htmlFor="input-prearmado">¿Cuántas unidades estás pre-armando?</label>
                <input
                  id="input-prearmado"
                  type="number"
                  min="0"
                  max={modalPrearmado.cantidad_pendiente}
                  defaultValue={modalPrearmado.cantidad_actual}
                  className={styles.inputCantidad}
                  autoFocus
                  onKeyPress={(e) => e.key === 'Enter' && guardarPrearmado()}
                />
                <small>Ingresá 0 para desmarcar</small>
              </div>
            </div>
            
            <div className={styles.modalFooter}>
              <button className={styles.btnCancelar} onClick={() => setModalPrearmado(null)}>
                Cancelar
              </button>
              <button className={styles.btnGuardar} onClick={guardarPrearmado}>
                Guardar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
