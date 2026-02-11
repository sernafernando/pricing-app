import { useState, useEffect, useCallback } from 'react';
import api from '../services/api';
import styles from './TurboRouting.module.css';
import { usePermisos } from '../contexts/PermisosContext';
import MapaEnvios from '../components/turbo/MapaEnvios';
import GestionZonas from '../components/turbo/GestionZonas';
import TabBanlist from '../components/turbo/TabBanlist';
import TabAsignaciones from '../components/turbo/TabAsignaciones';

export default function TurboRouting() {
  const { tienePermiso } = usePermisos();
  
  // Estados principales
  const [loading, setLoading] = useState(true);
  const [tabActiva, setTabActiva] = useState('envios'); // 'envios' | 'motoqueros' | 'mapa' | 'zonas' | 'estadisticas'
  
  // Envíos Turbo
  const [envios, setEnvios] = useState([]);
  const [enviosSeleccionados, setEnviosSeleccionados] = useState(new Set());
  const [filtroEstado, setFiltroEstado] = useState('');
  const [search, setSearch] = useState('');
  const [incluirAsignados, setIncluirAsignados] = useState(false);
  
  // Motoqueros
  const [motoqueros, setMotoqueros] = useState([]);
  const [motoqueroSeleccionado, setMotoqueroSeleccionado] = useState(null);
  const [modalMotoquero, setModalMotoquero] = useState(null); // null | { mode: 'create' | 'edit', data: {...} }
  
  // Estadísticas
  const [estadisticas, setEstadisticas] = useState(null);
  const [resumen, setResumen] = useState([]);
  
  // Zonas
  const [zonas, setZonas] = useState([]);
  
  // Asignación
  const [modalAsignacion, setModalAsignacion] = useState(false);
  const [procesando, setProcesando] = useState(false);
  
  // Geocoding
  const [geocodificando, setGeocodificando] = useState(false);
  
  // Asignación automática
  const [asignandoAutomatico, setAsignandoAutomatico] = useState(false);
  
  const puedeGestionar = tienePermiso('ordenes.gestionar_turbo_routing');
  
  // ========================================
  // FETCH DATA
  // ========================================
  
  const fetchEnvios = useCallback(async () => {
    try {
      const response = await api.get('/turbo/envios/pendientes', {
        params: { incluir_asignados: incluirAsignados }
      });
      setEnvios(response.data);
    } catch {
      alert('Error al cargar envíos pendientes');
    }
  }, [incluirAsignados]);
  
  const fetchMotoqueros = useCallback(async () => {
    try {
      const response = await api.get('/turbo/motoqueros');
      setMotoqueros(response.data);
    } catch {
      alert('Error al cargar motoqueros');
    }
  }, []);
  
  const fetchEstadisticas = useCallback(async () => {
    try {
      const [statsRes, resumenRes] = await Promise.all([
        api.get('/turbo/estadisticas'),
        api.get('/turbo/asignaciones/resumen')
      ]);
      setEstadisticas(statsRes.data);
      setResumen(resumenRes.data);
    } catch {
      alert('Error al cargar estadísticas');
    }
  }, []);
  
  const fetchZonas = useCallback(async () => {
    try {
      const response = await api.get('/turbo/zonas', {
        params: { solo_activas: false } // Mostrar TODAS las zonas (activas e inactivas)
      });
      setZonas(response.data);
    } catch {
      alert('Error al cargar zonas');
    }
  }, []);
  
  const fetchEnviosParaMapa = useCallback(async () => {
    try {
      const response = await api.get('/turbo/envios/pendientes', {
        params: { incluir_asignados: true }
      });
      setEnvios(response.data);
    } catch {
      alert('Error al cargar envíos para mapa');
    }
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      if (tabActiva === 'envios') {
        await fetchEnvios();
        await fetchMotoqueros();
      } else if (tabActiva === 'motoqueros') {
        await fetchMotoqueros();
      } else if (tabActiva === 'mapa') {
        await Promise.all([fetchEnviosParaMapa(), fetchZonas()]);
      } else if (tabActiva === 'zonas') {
        await fetchZonas();
      } else if (tabActiva === 'estadisticas') {
        await fetchEstadisticas();
      }
    } finally {
      setLoading(false);
    }
  }, [tabActiva, fetchEnvios, fetchMotoqueros, fetchEnviosParaMapa, fetchZonas, fetchEstadisticas]);
  
  useEffect(() => {
    loadData();
  }, [loadData]);
  
  // ========================================
  // HANDLERS - ENVÍOS
  // ========================================
  
  const toggleSeleccionEnvio = (shipmentId) => {
    setEnviosSeleccionados(prev => {
      const newSet = new Set(prev);
      if (newSet.has(shipmentId)) {
        newSet.delete(shipmentId);
      } else {
        newSet.add(shipmentId);
      }
      return newSet;
    });
  };
  
  const seleccionarTodos = () => {
    if (enviosSeleccionados.size === enviosFiltrados.length) {
      setEnviosSeleccionados(new Set());
    } else {
      setEnviosSeleccionados(new Set(enviosFiltrados.map(e => e.mlshippingid)));
    }
  };
  
  const abrirModalAsignacion = () => {
    if (enviosSeleccionados.size === 0) {
      alert('Seleccioná al menos un envío');
      return;
    }
    if (!puedeGestionar) {
      alert('No tenés permiso para asignar envíos');
      return;
    }
    setModalAsignacion(true);
  };
  
  const asignarEnvios = async () => {
    if (!motoqueroSeleccionado) {
      alert('Seleccioná un motoquero');
      return;
    }
    
    setProcesando(true);
    try {
      await api.post(
        '/turbo/asignacion/manual',
        {
          motoquero_id: motoqueroSeleccionado,
          mlshippingids: Array.from(enviosSeleccionados)
        }
      );
      
      // Invalidar cache para que stats se actualicen
      await api.post(
        '/turbo/cache/invalidar',
        {}
      ).catch(() => {}); // Ignore errors
      
      alert(`✅ ${enviosSeleccionados.size} envíos asignados correctamente`);
      setModalAsignacion(false);
      setEnviosSeleccionados(new Set());
      setMotoqueroSeleccionado(null);
      await fetchEnvios();
    } catch (error) {
      alert(error.response?.data?.detail || 'Error al asignar envíos');
    } finally {
      setProcesando(false);
    }
  };
  
  const geocodificarTodos = async () => {
    if (!puedeGestionar) {
      alert('No tenés permiso para geocodificar envíos');
      return;
    }
    
    const confirmacion = confirm(
      '🗺️ ¿Geocodificar todos los envíos Turbo pendientes?\n\n' +
      'Usará ML Webhook API (100% precisión, 0 costo)\n' +
      'Necesario para auto-generar zonas con K-Means\n\n' +
      'Esto puede tardar unos segundos...'
    );
    
    if (!confirmacion) return;
    
    setGeocodificando(true);
    try {
      const response = await api.post(
        '/turbo/geocoding/batch-ml',
        {}
      );
      
      const { exitosos, total, sin_coordenadas, porcentaje_exito } = response.data;
      
      alert(
        `✅ Geocoding completado\n\n` +
        `• Total: ${total} envíos\n` +
        `• Geocodificados: ${exitosos} (${porcentaje_exito}%)\n` +
        `• Sin coordenadas: ${sin_coordenadas}\n\n` +
        `Ahora podés auto-generar zonas con K-Means`
      );
    } catch (error) {
      alert(error.response?.data?.detail || 'Error al geocodificar envíos');
    } finally {
      setGeocodificando(false);
    }
  };
  
  const asignarAutomaticamente = async () => {
    if (!puedeGestionar) {
      alert('No tenés permiso para asignar envíos');
      return;
    }
    
    const confirmacion = confirm(
      '🤖 ¿Asignar automáticamente envíos por zona?\n\n' +
      'El sistema usará point-in-polygon para detectar la zona de cada envío\n' +
      'y lo asignará al motoquero correspondiente.\n\n' +
      'Solo se asignarán envíos con coordenadas geocodificadas.\n\n' +
      '¿Continuar?'
    );
    
    if (!confirmacion) return;
    
    setAsignandoAutomatico(true);
    try {
      const response = await api.post(
        '/turbo/asignar-automatico',
        {}
      );
      
      const { total_procesados, total_asignados, total_sin_zona, mensaje } = response.data;
      
      alert(
        `${mensaje}\n\n` +
        `• Procesados: ${total_procesados} envíos\n` +
        `• Asignados: ${total_asignados}\n` +
        `• Sin zona: ${total_sin_zona}\n\n` +
        `Recargando datos...`
      );
      
      // Recargar envíos y estadísticas
      await Promise.all([fetchEnvios(), fetchEstadisticas()]);
      
    } catch (error) {
      alert(error.response?.data?.detail || 'Error al asignar automáticamente');
    } finally {
      setAsignandoAutomatico(false);
    }
  };
  
  // ========================================
  // HANDLERS - MOTOQUEROS
  // ========================================
  
  const abrirModalCrearMotoquero = () => {
    if (!puedeGestionar) {
      alert('No tenés permiso para gestionar motoqueros');
      return;
    }
    setModalMotoquero({
      mode: 'create',
      data: { nombre: '', telefono: '', activo: true }
    });
  };
  
  const abrirModalEditarMotoquero = (motoquero) => {
    if (!puedeGestionar) {
      alert('No tenés permiso para gestionar motoqueros');
      return;
    }
    setModalMotoquero({
      mode: 'edit',
      data: { ...motoquero }
    });
  };
  
  const guardarMotoquero = async () => {
    const { mode, data } = modalMotoquero;
    
    if (!data.nombre.trim()) {
      alert('El nombre es obligatorio');
      return;
    }
    
    setProcesando(true);
    try {
      if (mode === 'create') {
        await api.post('/turbo/motoqueros', data);
        alert('✅ Motoquero creado');
      } else {
        await api.put(`/turbo/motoqueros/${data.id}`, data);
        alert('✅ Motoquero actualizado');
      }
      
      setModalMotoquero(null);
      await fetchMotoqueros();
    } catch (error) {
      alert(error.response?.data?.detail || 'Error al guardar motoquero');
    } finally {
      setProcesando(false);
    }
  };
  
  const desactivarMotoquero = async (id) => {
    if (!confirm('¿Desactivar este motoquero?')) return;
    
    try {
      await api.delete(`/turbo/motoqueros/${id}`);
      alert('✅ Motoquero desactivado');
      await fetchMotoqueros();
    } catch (error) {
      alert(error.response?.data?.detail || 'Error al desactivar motoquero');
    }
  };
  
  // ========================================
  // FILTROS
  // ========================================
  
  const enviosFiltrados = envios.filter(envio => {
    const matchEstado = !filtroEstado || envio.mlstatus === filtroEstado;
    const matchSearch = !search || 
      envio.mlshippingid?.toString().includes(search) ||
      envio.mlreceiver_name?.toLowerCase().includes(search.toLowerCase()) ||
      envio.direccion_completa?.toLowerCase().includes(search.toLowerCase());
    
    return matchEstado && matchSearch;
  });
  
  const motoquerosFiltrados = motoqueros.filter(m => 
    search ? m.nombre.toLowerCase().includes(search.toLowerCase()) : true
  );
  
  // ========================================
  // RENDER
  // ========================================
  
  if (!puedeGestionar) {
    return (
      <div className={styles.container}>
        <div className={styles.noPermiso}>
          <h2>Sin permiso</h2>
          <p>No tenés acceso a Turbo Routing</p>
        </div>
      </div>
    );
  }
  
  return (
    <div className={styles.container}>
      {/* HEADER */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <h1 className={styles.titulo}>🏍️ Turbo Routing</h1>
          <p className={styles.subtitulo}>
            Gestión de envíos Turbo (entrega en 1 hora)
          </p>
        </div>
        <div className={styles.headerRight}>
          <button 
            className="btn-tesla ghost"
            onClick={async () => {
              try {
                await api.post('/turbo/cache/invalidar', {});
                alert('✅ Cache invalidado');
                await loadData();
              } catch {
                alert('Error al invalidar cache');
              }
            }}
            disabled={loading}
            title="Forzar actualización desde ERP"
          >
            ⚡ Refrescar Cache
          </button>
          <button 
            className="btn-tesla secondary"
            onClick={loadData}
            disabled={loading}
          >
            🔄 Actualizar
          </button>
        </div>
      </div>
      
      {/* TABS */}
      <div className={styles.tabs}>
        <button 
          className={`${styles.tab} ${tabActiva === 'envios' ? styles.tabActiva : ''}`}
          onClick={() => setTabActiva('envios')}
        >
          📦 Envíos Pendientes
          {envios.length > 0 && <span className={styles.badge}>{envios.length}</span>}
        </button>
        <button 
          className={`${styles.tab} ${tabActiva === 'asignaciones' ? styles.tabActiva : ''}`}
          onClick={() => setTabActiva('asignaciones')}
        >
          📋 Asignaciones
        </button>
        <button 
          className={`${styles.tab} ${tabActiva === 'motoqueros' ? styles.tabActiva : ''}`}
          onClick={() => setTabActiva('motoqueros')}
        >
          🏍️ Motoqueros
          {motoqueros.length > 0 && <span className={styles.badge}>{motoqueros.length}</span>}
        </button>
        <button 
          className={`${styles.tab} ${tabActiva === 'mapa' ? styles.tabActiva : ''}`}
          onClick={() => setTabActiva('mapa')}
        >
          🗺️ Mapa
        </button>
        <button 
          className={`${styles.tab} ${tabActiva === 'zonas' ? styles.tabActiva : ''}`}
          onClick={() => setTabActiva('zonas')}
        >
          📍 Zonas
          {zonas.length > 0 && <span className={styles.badge}>{zonas.length}</span>}
        </button>
        <button 
          className={`${styles.tab} ${tabActiva === 'estadisticas' ? styles.tabActiva : ''}`}
          onClick={() => setTabActiva('estadisticas')}
        >
          📊 Estadísticas
        </button>
        <button 
          className={`${styles.tab} ${tabActiva === 'banlist' ? styles.tabActiva : ''}`}
          onClick={() => setTabActiva('banlist')}
        >
          🚫 Banlist
        </button>
      </div>
      
      {/* CONTENIDO */}
      {loading ? (
        <div className={styles.loading}>Cargando...</div>
      ) : (
        <>
          {tabActiva === 'asignaciones' && (
            <TabAsignaciones />
          )}
          
          {tabActiva === 'envios' && (
            <TabEnvios 
              envios={enviosFiltrados}
              enviosSeleccionados={enviosSeleccionados}
              filtroEstado={filtroEstado}
              search={search}
              incluirAsignados={incluirAsignados}
              geocodificando={geocodificando}
              asignandoAutomatico={asignandoAutomatico}
              onToggleSeleccion={toggleSeleccionEnvio}
              onSeleccionarTodos={seleccionarTodos}
              onFiltroEstadoChange={setFiltroEstado}
              onSearchChange={setSearch}
              onIncluirAsignadosChange={setIncluirAsignados}
              onAsignar={abrirModalAsignacion}
              onGeocodificar={geocodificarTodos}
              onAsignarAutomatico={asignarAutomaticamente}
            />
          )}
          
          {tabActiva === 'motoqueros' && (
            <TabMotoqueros 
              motoqueros={motoquerosFiltrados}
              search={search}
              onSearchChange={setSearch}
              onCrear={abrirModalCrearMotoquero}
              onEditar={abrirModalEditarMotoquero}
              onDesactivar={desactivarMotoquero}
            />
          )}
          
          {tabActiva === 'mapa' && (
            <div className={styles.mapaContainer}>
              <MapaEnvios 
                envios={envios}
                zonas={zonas.filter(z => z.activa)}
                onEnvioClick={() => {/* TODO: implementar click en envío */}}
                onZonaClick={() => {/* TODO: implementar click en zona */}}
              />
            </div>
          )}
          
          {tabActiva === 'zonas' && (
            <div className={styles.zonasContainer}>
              <GestionZonas 
                zonas={zonas}
                onZonaCreada={() => {
                  // Recargar TODAS las zonas desde el servidor (estado fresh)
                  fetchZonas();
                }}
                onZonaEliminada={(zonaId) => {
                  setZonas(zonas.filter(z => z.id !== zonaId));
                }}
              />
            </div>
          )}
          
          {tabActiva === 'estadisticas' && (
            <TabEstadisticas 
              estadisticas={estadisticas}
              resumen={resumen}
            />
          )}
          
          {tabActiva === 'banlist' && (
            <TabBanlist />
          )}
        </>
      )}
      
      {/* MODALS */}
      {modalAsignacion && (
        <ModalAsignacion 
          enviosCount={enviosSeleccionados.size}
          motoqueros={motoqueros.filter(m => m.activo)}
          motoqueroSeleccionado={motoqueroSeleccionado}
          onMotoqueroChange={setMotoqueroSeleccionado}
          onConfirmar={asignarEnvios}
          onCancelar={() => setModalAsignacion(false)}
          procesando={procesando}
        />
      )}
      
      {modalMotoquero && (
        <ModalMotoquero 
          mode={modalMotoquero.mode}
          data={modalMotoquero.data}
          onChange={(field, value) => setModalMotoquero(prev => ({
            ...prev,
            data: { ...prev.data, [field]: value }
          }))}
          onGuardar={guardarMotoquero}
          onCancelar={() => setModalMotoquero(null)}
          procesando={procesando}
        />
      )}
    </div>
  );
}

// ============================================
// COMPONENTE: TabEnvios
// ============================================

function TabEnvios({ 
  envios, 
  enviosSeleccionados, 
  filtroEstado, 
  search,
  incluirAsignados,
  geocodificando,
  asignandoAutomatico,
  onToggleSeleccion, 
  onSeleccionarTodos,
  onFiltroEstadoChange,
  onSearchChange,
  onIncluirAsignadosChange,
  onAsignar,
  onGeocodificar,
  onAsignarAutomatico
}) {
  const todosSeleccionados = envios.length > 0 && enviosSeleccionados.size === envios.length;
  
  return (
    <div className={styles.tabContent}>
      {/* TOOLBAR */}
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <input 
            type="text"
            placeholder="Buscar por ID, destinatario, dirección..."
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className={styles.searchInput}
          />
          
          <select 
            value={filtroEstado}
            onChange={(e) => onFiltroEstadoChange(e.target.value)}
            className={styles.select}
          >
            <option value="">Todos los estados</option>
            <option value="ready_to_ship">ready_to_ship</option>
            <option value="not_delivered">not_delivered</option>
          </select>
          
          <label className={styles.checkboxLabel}>
            <input 
              type="checkbox"
              checked={incluirAsignados}
              onChange={(e) => onIncluirAsignadosChange(e.target.checked)}
            />
            <span>Mostrar asignados</span>
          </label>
        </div>
        
        <div className={styles.toolbarRight}>
          <button 
            className="btn-tesla secondary"
            onClick={onGeocodificar}
            disabled={geocodificando}
            title="Geocodificar todos los envíos Turbo usando ML Webhook (100% precisión)"
          >
            {geocodificando ? '⏳ Geocodificando...' : '🗺️ Geocodificar Todos'}
          </button>
          
          <button 
            className="btn-tesla outline-subtle-primary"
            onClick={onAsignarAutomatico}
            disabled={asignandoAutomatico}
            title="Asignar automáticamente envíos a motoqueros según zona (point-in-polygon)"
          >
            {asignandoAutomatico ? '⏳ Asignando...' : '🤖 Asignar Automático'}
          </button>
          
          {enviosSeleccionados.size > 0 && (
            <>
              <span className={styles.seleccionInfo}>
                {enviosSeleccionados.size} seleccionados
              </span>
              <button 
                className="btn-tesla outline-subtle-primary"
                onClick={onAsignar}
              >
                ➡️ Asignar a Motoquero
              </button>
            </>
          )}
        </div>
      </div>
      
      {/* TABLA */}
      <div className="table-container-tesla">
        <table className="table-tesla">
          <thead className="table-tesla-head">
            <tr>
              <th>
                <input 
                  type="checkbox"
                  checked={todosSeleccionados}
                  onChange={onSeleccionarTodos}
                />
              </th>
              <th>Shipment ID</th>
              <th>Estado</th>
              <th>Destinatario</th>
              <th>Dirección</th>
              <th>Fecha Promesa</th>
              <th>Orden ML</th>
            </tr>
          </thead>
          <tbody className="table-tesla-body">
            {envios.length === 0 ? (
              <tr>
                <td colSpan="7" className={styles.emptyRow}>
                  No hay envíos Turbo pendientes
                </td>
              </tr>
            ) : (
              envios.map(envio => (
                <tr key={envio.mlshippingid}>
                  <td>
                    <input 
                      type="checkbox"
                      checked={enviosSeleccionados.has(envio.mlshippingid)}
                      onChange={() => onToggleSeleccion(envio.mlshippingid)}
                    />
                  </td>
                  <td><strong>{envio.mlshippingid}</strong></td>
                  <td>
                    <span className={`${styles.estadoBadge} ${styles[envio.mlstatus]}`}>
                      {envio.mlstatus}
                    </span>
                  </td>
                  <td>{envio.mlreceiver_name || '-'}</td>
                  <td className={styles.direccion} title={envio.direccion_completa}>
                    {envio.direccion_completa || '-'}
                  </td>
                  <td>{envio.mlestimated_delivery_limit ? new Date(envio.mlestimated_delivery_limit).toLocaleString('es-AR') : '-'}</td>
                  <td>{envio.mlo_id || '-'}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ============================================
// COMPONENTE: TabMotoqueros
// ============================================

function TabMotoqueros({ motoqueros, search, onSearchChange, onCrear, onEditar, onDesactivar }) {
  return (
    <div className={styles.tabContent}>
      {/* TOOLBAR */}
      <div className={styles.toolbar}>
        <input 
          type="text"
          placeholder="Buscar motoquero..."
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className={styles.searchInput}
        />
        
        <button 
          className="btn-tesla outline-subtle-primary"
          onClick={onCrear}
        >
          ➕ Nuevo Motoquero
        </button>
      </div>
      
      {/* TABLA */}
      <div className="table-container-tesla">
        <table className="table-tesla">
          <thead className="table-tesla-head">
            <tr>
              <th>ID</th>
              <th>Nombre</th>
              <th>Teléfono</th>
              <th>Estado</th>
              <th>Fecha Creación</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody className="table-tesla-body">
            {motoqueros.length === 0 ? (
              <tr>
                <td colSpan="6" className={styles.emptyRow}>
                  No hay motoqueros registrados
                </td>
              </tr>
            ) : (
              motoqueros.map(moto => (
                <tr key={moto.id}>
                  <td><strong>{moto.id}</strong></td>
                  <td>{moto.nombre}</td>
                  <td>{moto.telefono || '-'}</td>
                  <td>
                    <span className={`${styles.estadoBadge} ${moto.activo ? styles.activo : styles.inactivo}`}>
                      {moto.activo ? '✅ Activo' : '❌ Inactivo'}
                    </span>
                  </td>
                  <td>{moto.created_at ? new Date(moto.created_at).toLocaleDateString('es-AR') : '-'}</td>
                  <td>
                    <div className={styles.acciones}>
                      <button 
                        className="btn-tesla secondary"
                        onClick={() => onEditar(moto)}
                        title="Editar"
                      >
                        ✏️
                      </button>
                      {moto.activo && (
                        <button 
                          className="btn-tesla outline-subtle-danger"
                          onClick={() => onDesactivar(moto.id)}
                          title="Desactivar"
                        >
                          🗑️
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
    </div>
  );
}

// ============================================
// COMPONENTE: TabEstadisticas
// ============================================

function TabEstadisticas({ estadisticas, resumen }) {
  if (!estadisticas) {
    return <div className={styles.loading}>Cargando estadísticas...</div>;
  }
  
  return (
    <div className={styles.tabContent}>
      {/* STATS GENERALES */}
      <div className={styles.statsGrid}>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Envíos Pendientes</div>
          <div className={styles.statValue}>{estadisticas.total_envios_pendientes}</div>
        </div>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Motoqueros Activos</div>
          <div className={styles.statValue}>{estadisticas.total_motoqueros_activos}</div>
        </div>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Envíos Asignados Hoy</div>
          <div className={styles.statValue}>{estadisticas.asignaciones_hoy}</div>
        </div>
      </div>
      
      {/* RESUMEN POR MOTOQUERO */}
      <h3 className={styles.seccionTitulo}>Resumen por Motoquero</h3>
      <div className="table-container-tesla">
        <table className="table-tesla">
          <thead className="table-tesla-head">
            <tr>
              <th>Motoquero</th>
              <th>Envíos Asignados</th>
              <th>Última Asignación</th>
            </tr>
          </thead>
          <tbody className="table-tesla-body">
            {resumen.length === 0 ? (
              <tr>
                <td colSpan="3" className={styles.emptyRow}>
                  No hay asignaciones registradas
                </td>
              </tr>
            ) : (
              resumen.map(r => (
                <tr key={r.motoquero_id}>
                  <td><strong>{r.nombre}</strong></td>
                  <td>{r.total_envios}</td>
                  <td>{r.ultima_asignacion ? new Date(r.ultima_asignacion).toLocaleString('es-AR') : '-'}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ============================================
// COMPONENTE: ModalAsignacion
// ============================================

function ModalAsignacion({ 
  enviosCount, 
  motoqueros, 
  motoqueroSeleccionado, 
  onMotoqueroChange, 
  onConfirmar, 
  onCancelar,
  procesando
}) {
  return (
    <div className="modal-overlay-tesla" onClick={onCancelar}>
      <div className="modal-tesla" onClick={e => e.stopPropagation()}>
        <div className="modal-header-tesla">
          <h3>Asignar Envíos a Motoquero</h3>
          <button className="modal-close-tesla" onClick={onCancelar}>✕</button>
        </div>
        
        <div className="modal-body-tesla">
          <p className={styles.modalInfo}>
            Vas a asignar <strong>{enviosCount} envíos</strong> al motoquero seleccionado:
          </p>
          
          <label className={styles.modalLabel}>
            Seleccionar Motoquero:
          </label>
          <select 
            value={motoqueroSeleccionado || ''}
            onChange={(e) => onMotoqueroChange(Number(e.target.value))}
            className={`${styles.select} ${styles.modalSelect}`}
          >
            <option value="">-- Seleccioná un motoquero --</option>
            {motoqueros.map(m => (
              <option key={m.id} value={m.id}>
                {m.nombre} {m.telefono ? `(${m.telefono})` : ''}
              </option>
            ))}
          </select>
        </div>
        
        <div className="modal-footer-tesla">
          <button 
            className="btn-tesla secondary"
            onClick={onCancelar}
            disabled={procesando}
          >
            Cancelar
          </button>
          <button 
            className="btn-tesla outline-subtle-primary"
            onClick={onConfirmar}
            disabled={procesando || !motoqueroSeleccionado}
          >
            {procesando ? 'Asignando...' : 'Confirmar Asignación'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ============================================
// COMPONENTE: ModalMotoquero
// ============================================

function ModalMotoquero({ mode, data, onChange, onGuardar, onCancelar, procesando }) {
  const titulo = mode === 'create' ? 'Crear Motoquero' : 'Editar Motoquero';
  
  return (
    <div className="modal-overlay-tesla" onClick={onCancelar}>
      <div className="modal-tesla" onClick={e => e.stopPropagation()}>
        <div className="modal-header-tesla">
          <h3>{titulo}</h3>
          <button className="modal-close-tesla" onClick={onCancelar}>✕</button>
        </div>
        
        <div className="modal-body-tesla">
          <div className={styles.modalField}>
            <label className={styles.modalLabel}>
              Nombre *
            </label>
            <input 
              type="text"
              value={data.nombre}
              onChange={(e) => onChange('nombre', e.target.value)}
              className={`${styles.input} ${styles.modalSelect}`}
              placeholder="Ej: Juan Pérez"
            />
          </div>
          
          <div className={styles.modalField}>
            <label className={styles.modalLabel}>
              Teléfono
            </label>
            <input 
              type="text"
              value={data.telefono || ''}
              onChange={(e) => onChange('telefono', e.target.value)}
              className={`${styles.input} ${styles.modalSelect}`}
              placeholder="Ej: +54 9 11 1234-5678"
            />
          </div>
          
          {mode === 'edit' && (
            <div>
              <label className={styles.modalCheckboxLabel}>
                <input 
                  type="checkbox"
                  checked={data.activo}
                  onChange={(e) => onChange('activo', e.target.checked)}
                />
                <span>Activo</span>
              </label>
            </div>
          )}
        </div>
        
        <div className="modal-footer-tesla">
          <button 
            className="btn-tesla secondary"
            onClick={onCancelar}
            disabled={procesando}
          >
            Cancelar
          </button>
          <button 
            className="btn-tesla outline-subtle-primary"
            onClick={onGuardar}
            disabled={procesando}
          >
            {procesando ? 'Guardando...' : 'Guardar'}
          </button>
        </div>
      </div>
    </div>
  );
}
