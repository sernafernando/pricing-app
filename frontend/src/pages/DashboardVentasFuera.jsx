import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import axios from 'axios';
import styles from './DashboardMetricasML.module.css'; // Reutilizamos los estilos
import TabRentabilidadFuera from '../components/TabRentabilidadFuera';
import TabAdminVentasFuera from '../components/TabAdminVentasFuera';
import ModalEditarCosto from '../components/ModalEditarCosto';
import PaginationControls from '../components/PaginationControls';
import { useAuthStore } from '../store/authStore';
import { useQueryFilters } from '../hooks/useQueryFilters';
import { useServerPagination } from '../hooks/useServerPagination';

// API base URL
const API_URL = import.meta.env.VITE_API_URL;

// Helper para obtener fechas por defecto
const getDefaultFechaDesde = () => {
  const hoy = new Date();
  const primerDiaMes = new Date(hoy.getFullYear(), hoy.getMonth(), 1);
  return primerDiaMes.toISOString().split('T')[0];
};

const getDefaultFechaHasta = () => {
  const hoy = new Date();
  return hoy.toISOString().split('T')[0];
};

export default function DashboardVentasFuera() {
  const user = useAuthStore((state) => state.user);
  const esAdmin = user?.rol === 'ADMIN' || user?.rol === 'SUPERADMIN';

  const [loading, setLoading] = useState(true);
  const [filtroRapidoActivo, setFiltroRapidoActivo] = useState('mesActual');
  const [mostrarDropdownFecha, setMostrarDropdownFecha] = useState(false);
  
  // Usar query params para tab, fechas y filtros
  const { getFilter, updateFilters } = useQueryFilters({
    tab: 'resumen',
    fecha_desde: getDefaultFechaDesde(),
    fecha_hasta: getDefaultFechaHasta(),
    sucursal: '',
    vendedor: '',
    vendedores: ''
  });

  const tabActivo = getFilter('tab');
  const fechaDesde = getFilter('fecha_desde');
  const fechaHasta = getFilter('fecha_hasta');
  
  const sucursalesQuery = getFilter('sucursales');
  const sucursalesSeleccionadas = useMemo(() => {
    if (!sucursalesQuery) return [];
    return sucursalesQuery.split(',').filter(Boolean);
  }, [sucursalesQuery]);

  const vendedoresQuery = getFilter('vendedores');
  const vendedoresSeleccionados = useMemo(() => {
    if (!vendedoresQuery) return [];
    return vendedoresQuery.split(',').filter(Boolean);
  }, [vendedoresQuery]);

  // Fechas temporales para el dropdown (sincronizadas con las fechas actuales)
  const [fechaTemporal, setFechaTemporal] = useState({
    desde: fechaDesde,
    hasta: fechaHasta
  });

  // Sincronizar fechas temporales cuando cambian las fechas del filtro
  useEffect(() => {
    setFechaTemporal({
      desde: fechaDesde,
      hasta: fechaHasta
    });
  }, [fechaDesde, fechaHasta]);

  // Datos
  const [stats, setStats] = useState(null);
  const [ventasPorMarca, setVentasPorMarca] = useState([]);
  const [topProductos, setTopProductos] = useState([]);
  const [sucursalesDisponibles, setSucursalesDisponibles] = useState([]);
  const [vendedoresDisponibles, setVendedoresDisponibles] = useState([]);

  // Estado para solo modificadas (filtro local)
  const [soloModificadas, setSoloModificadas] = useState(false);
  const [soloSinCosto, setSoloSinCosto] = useState(false);

  // Modal editar costo
  const [modalCostoAbierto, setModalCostoAbierto] = useState(false);
  const [operacionEditando, setOperacionEditando] = useState(null);

  // Overrides de marca/categoría/subcategoría
  const [overrides, setOverrides] = useState({});
  const [jerarquiaProductos, setJerarquiaProductos] = useState({}); // { marca: { categoria: [subcategorias] } }

  // Helper para cargar overrides y jerarquía (definido antes del hook de paginación)
  const cargarOverridesYJerarquia = useCallback(async () => {
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      const [overridesRes, jerarquiaRes] = await Promise.all([
        axios.get(`${API_URL}/ventas-fuera-ml/overrides`, { 
          params: { from_date: fechaDesde, to_date: fechaHasta }, 
          headers 
        }),
        axios.get(`${API_URL}/ventas-fuera-ml/jerarquia-productos`, { headers })
          .catch(() => ({ data: {} }))
      ]);

      setOverrides(overridesRes.data || {});
      setJerarquiaProductos(jerarquiaRes.data || {});
    } catch (error) {
      console.error('Error cargando overrides:', error);
    }
  }, [fechaDesde, fechaHasta]);

  // Hook de paginación server-side (solo para tab de operaciones)
  const paginationFilters = useMemo(() => ({
    from_date: fechaDesde,
    to_date: fechaHasta,
    // Enviar todas las sucursales seleccionadas separadas por coma
    ...(sucursalesSeleccionadas.length > 0 && { sucursal: sucursalesSeleccionadas.join(',') }),
    // Enviar todos los vendedores seleccionados separados por coma
    ...(vendedoresSeleccionados.length > 0 && { vendedor: vendedoresSeleccionados.join(',') }),
    solo_sin_costo: soloSinCosto
  }), [fechaDesde, fechaHasta, sucursalesSeleccionadas, vendedoresSeleccionados, soloSinCosto]);

  const pagination = useServerPagination({
    endpoint: '/ventas-fuera-ml/operaciones',
    countEndpoint: '/ventas-fuera-ml/operaciones/count',
    filters: paginationFilters,
    pageSize: 1000,
    enabled: tabActivo === 'operaciones',
    onDataLoaded: cargarOverridesYJerarquia
  });

  const cargarDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      const params = {
        from_date: fechaDesde,
        to_date: fechaHasta
      };

      // Agregar filtros si están seleccionados (enviar todos separados por coma)
      if (sucursalesSeleccionadas.length > 0) {
        params.sucursal = sucursalesSeleccionadas.join(',');
      }
      if (vendedoresSeleccionados.length > 0) {
        params.vendedor = vendedoresSeleccionados.join(',');
      }

      // Cargar todos los datos en paralelo
      const [statsRes, marcasRes, productosRes] = await Promise.all([
        axios.get(`${API_URL}/ventas-fuera-ml/stats`, { params, headers }),
        axios.get(`${API_URL}/ventas-fuera-ml/por-marca`, { params: { ...params, limit: 15 }, headers }),
        axios.get(`${API_URL}/ventas-fuera-ml/top-productos`, { params: { ...params, limit: 20 }, headers })
      ]);

      setStats(statsRes.data);
      setVentasPorMarca(marcasRes.data || []);
      setTopProductos(productosRes.data || []);

      // Usar las listas completas de sucursales y vendedores disponibles
      if (statsRes.data) {
        setSucursalesDisponibles(statsRes.data.sucursales_disponibles || []);
        setVendedoresDisponibles(statsRes.data.vendedores_disponibles || []);
      }
    } catch (error) {
      alert('Error al cargar el dashboard');
    } finally {
      setLoading(false);
    }
  }, [fechaDesde, fechaHasta, sucursalesSeleccionadas, vendedoresSeleccionados]);

  useEffect(() => {
    if (fechaDesde && fechaHasta) {
      cargarDashboard();
    }
  }, [fechaDesde, fechaHasta, sucursalesSeleccionadas, vendedoresSeleccionados, cargarDashboard]);

  const abrirModalCosto = (operacion) => {
    setOperacionEditando(operacion);
    setModalCostoAbierto(true);
  };

  const cerrarModalCosto = () => {
    setModalCostoAbierto(false);
    setOperacionEditando(null);
  };

  const onCostoGuardado = () => {
    // Invalidar cache y recargar página actual
    pagination.invalidateCache();
  };

  // Ref para debounce de overrides
  const debounceTimers = useRef({});

  const guardarOverrideAPI = useCallback(async (itTransaction, campo, valor) => {
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      await axios.post(`${API_URL}/ventas-fuera-ml/override`, {
        it_transaction: itTransaction,
        [campo]: valor
      }, { headers });

      // Invalidar cache para que se recargue con datos frescos
      pagination.invalidateCache();
    } catch (error) {
      alert('Error al guardar cambios');
    }
  }, [pagination]);

  const guardarOverride = useCallback((itTransaction, campo, valor) => {
    // Actualizar estado local inmediatamente
    setOverrides(prev => ({
      ...prev,
      [itTransaction]: {
        ...(prev[itTransaction] || {}),
        [campo]: valor || null
      }
    }));

    // Debounce la llamada al API (500ms)
    const timerKey = `${itTransaction}-${campo}`;
    if (debounceTimers.current[timerKey]) {
      clearTimeout(debounceTimers.current[timerKey]);
    }
    debounceTimers.current[timerKey] = setTimeout(() => {
      guardarOverrideAPI(itTransaction, campo, valor);
    }, 500);
  }, [guardarOverrideAPI]);

  // Obtener valor efectivo (override o valor original)
  const getValorEfectivo = (op, campo) => {
    const override = overrides[op.id_operacion];
    if (override && override[campo] !== undefined && override[campo] !== null) {
      return override[campo];
    }
    return op[campo] || '';
  };

  // Obtener marcas disponibles de la jerarquía
  const getMarcasDisponibles = () => {
    return Object.keys(jerarquiaProductos).sort();
  };

  // Obtener categorías disponibles según la marca seleccionada
  const getCategoriasParaMarca = (marca) => {
    if (!marca || !jerarquiaProductos[marca]) return [];
    return Object.keys(jerarquiaProductos[marca]).sort();
  };

  // Obtener subcategorías disponibles según marca y categoría
  const getSubcategoriasParaCategoria = (marca, categoria) => {
    if (!marca || !categoria || !jerarquiaProductos[marca] || !jerarquiaProductos[marca][categoria]) return [];
    return jerarquiaProductos[marca][categoria].sort();
  };

  const formatearMoneda = (monto) => {
    return new Intl.NumberFormat('es-AR', {
      style: 'currency',
      currency: 'ARS',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(monto || 0);
  };

  const formatearPorcentaje = (valor) => {
    if (valor === null || valor === undefined) return '-';
    return `${(parseFloat(valor) * 100).toFixed(2)}%`;
  };

  const formatearFecha = (fecha) => {
    if (!fecha) return '-';
    return new Date(fecha).toLocaleDateString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric'
    });
  };

  const aplicarFiltroRapido = (filtro) => {
    const hoy = new Date();
    const formatearFechaISO = (fecha) => fecha.toISOString().split('T')[0];

    let desde, hasta = hoy;

    switch (filtro) {
      case 'hoy':
        desde = new Date(hoy);
        break;
      case 'ayer':
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 1);
        hasta = new Date(desde);
        break;
      case '3d':
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 2);
        break;
      case '7d':
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 6);
        break;
      case '14d':
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 13);
        break;
      case 'mesActual':
        desde = new Date(hoy.getFullYear(), hoy.getMonth(), 1);
        break;
      case '30d':
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 29);
        break;
      case '3m':
        desde = new Date(hoy);
        desde.setMonth(desde.getMonth() - 3);
        break;
      default:
        return;
    }

    setFiltroRapidoActivo(filtro);
    setMostrarDropdownFecha(false);
    updateFilters({
      fecha_desde: formatearFechaISO(desde),
      fecha_hasta: formatearFechaISO(hasta)
    });
  };

  const aplicarFechaPersonalizada = () => {
    setFiltroRapidoActivo('custom');
    setMostrarDropdownFecha(false);
    updateFilters({
      fecha_desde: fechaTemporal.desde,
      fecha_hasta: fechaTemporal.hasta
    });
  };

  const toggleVendedor = (vendedor) => {
    const nuevosSeleccionados = vendedoresSeleccionados.includes(vendedor)
      ? vendedoresSeleccionados.filter(v => v !== vendedor)
      : [...vendedoresSeleccionados, vendedor];
    
    updateFilters({ vendedores: nuevosSeleccionados.join(',') || '' });
  };

  const limpiarVendedores = () => {
    updateFilters({ vendedores: '' });
  };

  const toggleSucursal = (sucursal) => {
    const nuevasSeleccionadas = sucursalesSeleccionadas.includes(sucursal)
      ? sucursalesSeleccionadas.filter(s => s !== sucursal)
      : [...sucursalesSeleccionadas, sucursal];
    
    updateFilters({ sucursales: nuevasSeleccionadas.join(',') || '' });
  };

  const limpiarSucursales = () => {
    updateFilters({ sucursales: '' });
  };

  // Verificar si una operación tiene override
  const tieneOverride = (opId) => {
    const override = overrides[opId];
    if (!override) return false;
    return Object.values(override).some(v => v !== null && v !== undefined && v !== '');
  };

  // Filtrar operaciones solo por "modificadas" (filtro local)
  // La búsqueda se hace server-side via el hook
  const operacionesFiltradas = useMemo(() => {
    if (!soloModificadas) return pagination.data;
    
    return pagination.data.filter(op => tieneOverride(op.id_operacion));
  }, [pagination.data, soloModificadas]);

  // Calcular ganancia para el resumen
  const calcularGanancia = () => {
    if (!stats) return 0;
    return stats.monto_total_sin_iva - stats.costo_total;
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>🏪 Dashboard Ventas por Fuera de ML</h1>

        {/* Contenedor con filtros rápidos + botón reload + filtros adicionales */}
        <div className={styles.filtrosRapidosWrapper}>
          {/* Filtros Rápidos Compactos */}
          <div className={styles.filtrosRapidos}>
            <button 
              onClick={() => setMostrarDropdownFecha(!mostrarDropdownFecha)} 
              className={`${styles.btnFiltroRapido} ${styles.btnCalendar}`}
              title="Seleccionar rango personalizado"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
                <line x1="16" y1="2" x2="16" y2="6"/>
                <line x1="8" y1="2" x2="8" y2="6"/>
                <line x1="3" y1="10" x2="21" y2="10"/>
              </svg>
            </button>
            
            <button 
              onClick={() => aplicarFiltroRapido('hoy')} 
              className={`${styles.btnFiltroRapido} ${filtroRapidoActivo === 'hoy' ? styles.activo : ''}`}
            >
              Hoy
            </button>
            <button 
              onClick={() => aplicarFiltroRapido('ayer')} 
              className={`${styles.btnFiltroRapido} ${filtroRapidoActivo === 'ayer' ? styles.activo : ''}`}
            >
              Ayer
            </button>
            <button 
              onClick={() => aplicarFiltroRapido('3d')} 
              className={`${styles.btnFiltroRapido} ${filtroRapidoActivo === '3d' ? styles.activo : ''}`}
            >
              3d
            </button>
            <button 
              onClick={() => aplicarFiltroRapido('7d')} 
              className={`${styles.btnFiltroRapido} ${filtroRapidoActivo === '7d' ? styles.activo : ''}`}
            >
              7d
            </button>
            <button 
              onClick={() => aplicarFiltroRapido('14d')} 
              className={`${styles.btnFiltroRapido} ${filtroRapidoActivo === '14d' ? styles.activo : ''}`}
            >
              14d
            </button>
            <button
              onClick={() => aplicarFiltroRapido('mesActual')}
              className={`${styles.btnFiltroRapido} ${filtroRapidoActivo === 'mesActual' ? styles.activo : ''}`}
            >
              Mes actual
            </button>
            <button 
              onClick={() => aplicarFiltroRapido('30d')} 
              className={`${styles.btnFiltroRapido} ${filtroRapidoActivo === '30d' ? styles.activo : ''}`}
            >
              30d
            </button>
            <button 
              onClick={() => aplicarFiltroRapido('3m')} 
              className={`${styles.btnFiltroRapido} ${filtroRapidoActivo === '3m' ? styles.activo : ''}`}
            >
              3m
            </button>

            {/* Dropdown de fecha personalizada */}
            {mostrarDropdownFecha && (
              <>
                <div 
                  className={styles.dropdownOverlay} 
                  onClick={() => setMostrarDropdownFecha(false)}
                />
                <div className={styles.dropdownFecha}>
                  <div className={styles.dropdownFechaContent}>
                    <div className={styles.dropdownFechaField}>
                      <label>Desde</label>
                      <input
                        type="date"
                        value={fechaTemporal.desde}
                        onChange={(e) => setFechaTemporal({ ...fechaTemporal, desde: e.target.value })}
                        className={styles.dropdownDateInput}
                      />
                    </div>
                    <div className={styles.dropdownFechaField}>
                      <label>Hasta</label>
                      <input
                        type="date"
                        value={fechaTemporal.hasta}
                        onChange={(e) => setFechaTemporal({ ...fechaTemporal, hasta: e.target.value })}
                        className={styles.dropdownDateInput}
                      />
                    </div>
                    <button onClick={aplicarFechaPersonalizada} className="btn-tesla outline-subtle-primary sm">
                      Aplicar
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Botón recargar - Separado */}
          {tabActivo !== 'rentabilidad' && tabActivo !== 'admin' && (
            <button 
              onClick={tabActivo === 'resumen' ? cargarDashboard : pagination.reset} 
              className={styles.btnRecargar}
              disabled={pagination.loading}
              title="Recargar"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="23 4 23 10 17 10"/>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
              </svg>
            </button>
          )}

          {/* Filtro de SUCURSAL: selector múltiple (visible en todas las tabs) */}
          {sucursalesDisponibles.length > 0 && (
            <div className={styles.filtroSelect}>
              <label>SUCURSALES:</label>
              <div className={styles.multiSelect}>
                <div className={styles.multiSelectHeader}>
                  <span className={styles.multiSelectLabel}>
                    {sucursalesSeleccionadas.length === 0 
                      ? 'Todas las sucursales' 
                      : `${sucursalesSeleccionadas.length} sucursal${sucursalesSeleccionadas.length > 1 ? 'es' : ''} seleccionada${sucursalesSeleccionadas.length > 1 ? 's' : ''}`}
                  </span>
                </div>
                <div className={styles.multiSelectDropdown}>
                  {sucursalesSeleccionadas.length > 0 && (
                    <div className={styles.multiSelectActions}>
                      <button 
                        type="button" 
                        onClick={limpiarSucursales}
                        className={styles.btnMultiSelectAction}
                      >
                        ✗ Limpiar selección
                      </button>
                    </div>
                  )}
                  <div className={styles.multiSelectOptions}>
                    {sucursalesDisponibles.map(sucursal => (
                      <label key={sucursal} className={styles.multiSelectOption}>
                        <input
                          type="checkbox"
                          checked={sucursalesSeleccionadas.includes(sucursal)}
                          onChange={() => toggleSucursal(sucursal)}
                        />
                        <span>{sucursal}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Filtro de VENDEDORES: selector múltiple (visible en todas las tabs) */}
          {vendedoresDisponibles.length > 0 && (
            <div className={styles.filtroSelect}>
              <label>VENDEDORES:</label>
              <div className={styles.multiSelect}>
                <div className={styles.multiSelectHeader}>
                  <span className={styles.multiSelectLabel}>
                    {vendedoresSeleccionados.length === 0 
                      ? 'Todos los vendedores' 
                      : `${vendedoresSeleccionados.length} vendedor${vendedoresSeleccionados.length > 1 ? 'es' : ''} seleccionado${vendedoresSeleccionados.length > 1 ? 's' : ''}`}
                  </span>
                </div>
                <div className={styles.multiSelectDropdown}>
                  {vendedoresSeleccionados.length > 0 && (
                    <div className={styles.multiSelectActions}>
                      <button 
                        type="button" 
                        onClick={limpiarVendedores}
                        className={styles.btnMultiSelectAction}
                      >
                        ✗ Limpiar selección
                      </button>
                    </div>
                  )}
                  <div className={styles.multiSelectOptions}>
                    {vendedoresDisponibles.map(vendedor => (
                      <label key={vendedor} className={styles.multiSelectOption}>
                        <input
                          type="checkbox"
                          checked={vendedoresSeleccionados.includes(vendedor)}
                          onChange={() => toggleVendedor(vendedor)}
                        />
                        <span>{vendedor}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {tabActivo === 'operaciones' && (
            <>
              <label className={styles.checkboxLabel}>
                <input
                  type="checkbox"
                  checked={soloSinCosto}
                  onChange={(e) => setSoloSinCosto(e.target.checked)}
                />
                Solo sin costo
              </label>
              <label className={styles.checkboxLabel}>
                <input
                  type="checkbox"
                  checked={soloModificadas}
                  onChange={(e) => setSoloModificadas(e.target.checked)}
                />
                Solo modificadas
              </label>
            </>
          )}
        </div>

        {/* Tabs */}
        <div className={styles.tabs}>
          <button
            className={`${styles.tab} ${tabActivo === 'resumen' ? styles.tabActivo : ''}`}
            onClick={() => updateFilters({ tab: 'resumen' })}
          >
            📊 Resumen
          </button>
          <button
            className={`${styles.tab} ${tabActivo === 'operaciones' ? styles.tabActivo : ''}`}
            onClick={() => updateFilters({ tab: 'operaciones' })}
          >
            📋 Detalle de Operaciones
          </button>
          <button
            className={`${styles.tab} ${tabActivo === 'rentabilidad' ? styles.tabActivo : ''}`}
            onClick={() => updateFilters({ tab: 'rentabilidad' })}
          >
            💹 Rentabilidad
          </button>
          {esAdmin && (
            <button
              className={`${styles.tab} ${tabActivo === 'admin' ? styles.tabActivo : ''}`}
              onClick={() => updateFilters({ tab: 'admin' })}
            >
              ⚙️ Admin
            </button>
          )}
        </div>
      </div>

      {/* Alerta de productos sin costo */}
      {stats && stats.productos_sin_costo > 0 && tabActivo === 'resumen' && (
        <div className={styles.alertaSinCosto}>
          ⚠️ El período seleccionado tiene <strong>{stats.productos_sin_costo} producto{stats.productos_sin_costo !== 1 ? 's' : ''}</strong> sin costo cargado, los cuales fueron excluidos de todas las métricas.
        </div>
      )}

      {tabActivo === 'admin' ? (
        <TabAdminVentasFuera />
      ) : tabActivo === 'rentabilidad' ? (
        <TabRentabilidadFuera 
          fechaDesde={fechaDesde} 
          fechaHasta={fechaHasta}
          sucursal={sucursalesSeleccionadas.join(',')}
          vendedor={vendedoresSeleccionados.join(',')}
        />
      ) : (loading || (tabActivo === 'operaciones' && pagination.loading && pagination.currentPage === 1)) ? (
        <div className={styles.loading}>Cargando...</div>
      ) : tabActivo === 'operaciones' ? (
        /* Tab de Detalle de Operaciones */
        <div className={styles.operacionesContainer}>
          {/* Controles de paginación */}
          <PaginationControls
            mode={pagination.paginationMode}
            onToggleMode={pagination.togglePaginationMode}
            currentPage={pagination.currentPage}
            totalPages={pagination.totalPages}
            totalItems={pagination.totalItems}
            hasMore={pagination.hasMore}
            loading={pagination.loading}
            onGoToPage={pagination.goToPage}
            pageSize={pagination.pageSize}
          />

          <div className={styles.buscadorContainer}>
            <input
              type="text"
              placeholder="🔍 Buscar por código, producto, marca o cliente..."
              value={pagination.searchTerm}
              onChange={(e) => pagination.setSearchTerm(e.target.value)}
              className={styles.buscador}
            />
            <div className={styles.resultadosCount}>
              {operacionesFiltradas.length} operación{operacionesFiltradas.length !== 1 ? 'es' : ''}
              {soloModificadas && ' (solo modificadas)'}
            </div>
          </div>

          <div 
            className={styles.tableWrapper}
            onScroll={pagination.handleScroll}
            ref={pagination.scrollContainerRef}
          >
            <table className={styles.tableOperaciones}>
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Sucursal</th>
                  <th>Cliente</th>
                  <th>Vendedor</th>
                  <th>Codigo</th>
                  <th>Producto</th>
                  <th>Marca</th>
                  <th>Categoría</th>
                  <th>Subcategoría</th>
                  <th>Cant</th>
                  <th>Precio Unit</th>
                  <th>IVA%</th>
                  <th>Total s/IVA</th>
                  <th>Total c/IVA</th>
                  <th>Costo</th>
                  <th>Markup%</th>
                  <th>Comprobante</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {operacionesFiltradas.map((op, idx) => {
                  const sinCosto = !op.costo_pesos_sin_iva || op.costo_pesos_sin_iva === 0;
                  const override = overrides[op.id_operacion];
                  const filaModificada = override && Object.values(override).some(v => v !== null && v !== undefined && v !== '');

                  // Valores efectivos (override o original)
                  const marcaEfectiva = getValorEfectivo(op, 'marca');
                  const categoriaEfectiva = getValorEfectivo(op, 'categoria');
                  const subcategoriaEfectiva = getValorEfectivo(op, 'subcategoria');
                  const clienteEfectivo = getValorEfectivo(op, 'cliente') || op.cliente || '';
                  const codigoEfectivo = getValorEfectivo(op, 'codigo') || op.codigo_item || '';
                  const descripcionEfectiva = getValorEfectivo(op, 'descripcion') || op.descripcion || '';

                  // Helper para mostrar asterisco si campo modificado
                  const asterisco = (campo) => override?.[campo] ? <span className={styles.asteriscoModificado}>*</span> : null;
                  
                  // Helper para className de campo editable
                  const getClaseCampoEditable = (campo, sinCosto = false) => {
                    const clases = [styles.inputEditableInline];
                    if (override?.[campo]) clases.push(styles.campoOverride);
                    if (sinCosto) clases.push(styles.campoSinCosto);
                    return clases.join(' ');
                  };

                  return (
                    <tr
                      key={op.metrica_id || idx}
                      className={`${sinCosto ? styles.rowSinCosto : ''} ${filaModificada ? styles.rowModificada : ''}`}
                    >
                      <td>{formatearFecha(op.fecha)}</td>
                      <td>{op.sucursal || '-'}</td>
                      <td>
                        <span
                          className={getClaseCampoEditable('cliente')}
                          onClick={() => {
                            const nuevoValor = prompt('Cliente:', clienteEfectivo);
                            if (nuevoValor !== null) guardarOverride(op.id_operacion, 'cliente', nuevoValor);
                          }}
                          role="button"
                          tabIndex={0}
                          aria-label="Editar cliente"
                          title="Click para editar"
                        >
                          {clienteEfectivo || '-'}{asterisco('cliente')}
                        </span>
                      </td>
                      <td>{op.vendedor || '-'}</td>
                      <td>
                        <span
                          className={getClaseCampoEditable('codigo')}
                          onClick={() => {
                            const nuevoValor = prompt('Código:', codigoEfectivo);
                            if (nuevoValor !== null) guardarOverride(op.id_operacion, 'codigo', nuevoValor);
                          }}
                          role="button"
                          tabIndex={0}
                          aria-label="Editar código de producto"
                          title="Click para editar"
                        >
                          {codigoEfectivo || '-'}{asterisco('codigo')}
                        </span>
                      </td>
                      <td className={styles.descripcion}>
                        <span
                          className={getClaseCampoEditable('descripcion')}
                          onClick={() => {
                            const nuevoValor = prompt('Descripción:', descripcionEfectiva);
                            if (nuevoValor !== null) guardarOverride(op.id_operacion, 'descripcion', nuevoValor);
                          }}
                          role="button"
                          tabIndex={0}
                          aria-label="Editar descripción de producto"
                          title="Click para editar"
                        >
                          {descripcionEfectiva || '-'}{asterisco('descripcion')}
                        </span>
                      </td>
                      <td>
                        <select
                          value={marcaEfectiva}
                          onChange={(e) => {
                            guardarOverride(op.id_operacion, 'marca', e.target.value);
                            if (e.target.value !== marcaEfectiva) {
                              guardarOverride(op.id_operacion, 'categoria', '');
                              guardarOverride(op.id_operacion, 'subcategoria', '');
                            }
                          }}
                          className={`${styles.selectEditable} ${override?.marca ? styles.campoOverride : ''}`}
                          aria-label="Marca del producto"
                        >
                          <option value="">-</option>
                          {getMarcasDisponibles().map(m => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                          {marcaEfectiva && !getMarcasDisponibles().includes(marcaEfectiva) && (
                            <option value={marcaEfectiva}>{marcaEfectiva}</option>
                          )}
                        </select>
                        {asterisco('marca')}
                      </td>
                      <td>
                        <select
                          value={categoriaEfectiva}
                          onChange={(e) => {
                            guardarOverride(op.id_operacion, 'categoria', e.target.value);
                            if (e.target.value !== categoriaEfectiva) {
                              guardarOverride(op.id_operacion, 'subcategoria', '');
                            }
                          }}
                          className={`${styles.selectEditable} ${override?.categoria ? styles.campoOverride : ''}`}
                          disabled={!marcaEfectiva}
                          aria-label="Categoría del producto"
                        >
                          <option value="">-</option>
                          {getCategoriasParaMarca(marcaEfectiva).map(c => (
                            <option key={c} value={c}>{c}</option>
                          ))}
                          {categoriaEfectiva && !getCategoriasParaMarca(marcaEfectiva).includes(categoriaEfectiva) && (
                            <option value={categoriaEfectiva}>{categoriaEfectiva}</option>
                          )}
                        </select>
                        {asterisco('categoria')}
                      </td>
                      <td>
                        <select
                          value={subcategoriaEfectiva}
                          onChange={(e) => guardarOverride(op.id_operacion, 'subcategoria', e.target.value)}
                          className={`${styles.selectEditable} ${override?.subcategoria ? styles.campoOverride : ''}`}
                          disabled={!categoriaEfectiva}
                          aria-label="Subcategoría del producto"
                        >
                          <option value="">-</option>
                          {getSubcategoriasParaCategoria(marcaEfectiva, categoriaEfectiva).map(s => (
                            <option key={s} value={s}>{s}</option>
                          ))}
                          {subcategoriaEfectiva && !getSubcategoriasParaCategoria(marcaEfectiva, categoriaEfectiva).includes(subcategoriaEfectiva) && (
                            <option value={subcategoriaEfectiva}>{subcategoriaEfectiva}</option>
                          )}
                        </select>
                        {asterisco('subcategoria')}
                      </td>
                      <td className={styles.centrado}>
                        <span
                          className={getClaseCampoEditable('cantidad')}
                          onClick={() => {
                            const valorActual = getValorEfectivo(op, 'cantidad') || op.cantidad || '';
                            const nuevoValor = prompt('Cantidad:', valorActual);
                            if (nuevoValor !== null) guardarOverride(op.id_operacion, 'cantidad', nuevoValor ? parseFloat(nuevoValor) : null);
                          }}
                          role="button"
                          tabIndex={0}
                          aria-label="Editar cantidad"
                          title="Click para editar"
                        >
                          {getValorEfectivo(op, 'cantidad') || op.cantidad || '-'}{asterisco('cantidad')}
                        </span>
                      </td>
                      <td className={styles.monto}>
                        <span
                          className={getClaseCampoEditable('precio_unitario')}
                          onClick={() => {
                            const valorActual = getValorEfectivo(op, 'precio_unitario') || op.precio_unitario_sin_iva || '';
                            const nuevoValor = prompt('Precio unitario:', valorActual);
                            if (nuevoValor !== null) guardarOverride(op.id_operacion, 'precio_unitario', nuevoValor ? parseFloat(nuevoValor) : null);
                          }}
                          role="button"
                          tabIndex={0}
                          aria-label="Editar precio unitario"
                          title="Click para editar"
                        >
                          {formatearMoneda(getValorEfectivo(op, 'precio_unitario') || op.precio_unitario_sin_iva)}{asterisco('precio_unitario')}
                        </span>
                      </td>
                      <td className={styles.centrado}>{op.iva_porcentaje}%</td>
                      <td className={styles.monto}>{formatearMoneda(op.precio_final_sin_iva)}</td>
                      <td className={styles.monto}>{formatearMoneda(op.precio_final_con_iva)}</td>
                      <td className={styles.monto}>
                        <span
                          className={getClaseCampoEditable('costo_unitario', sinCosto)}
                          onClick={() => {
                            const valorActual = getValorEfectivo(op, 'costo_unitario') || op.costo_unitario || '';
                            const nuevoValor = prompt('Costo unitario:', valorActual);
                            if (nuevoValor !== null) guardarOverride(op.id_operacion, 'costo_unitario', nuevoValor ? parseFloat(nuevoValor) : null);
                          }}
                          role="button"
                          tabIndex={0}
                          aria-label="Editar costo unitario"
                          title="Click para editar"
                        >
                          {(getValorEfectivo(op, 'costo_unitario') || op.costo_unitario) ? formatearMoneda(getValorEfectivo(op, 'costo_unitario') || op.costo_unitario) : 'Sin costo'}{asterisco('costo_unitario')}
                        </span>
                      </td>
                      <td className={`${styles.centrado} ${op.markup !== null && parseFloat(op.markup) < 0 ? styles.negativo : ''}`}>
                        {formatearPorcentaje(op.markup)}
                      </td>
                      <td>{op.tipo_comprobante} {op.numero_comprobante}</td>
                      <td>
                        <button
                          onClick={() => abrirModalCosto(op)}
                          className={sinCosto ? styles.alertWarning : styles.btnAccionTabla}
                          aria-label={sinCosto ? 'Agregar costo' : 'Editar costo'}
                          title={sinCosto ? 'Agregar costo' : 'Editar costo'}
                        >
                          {sinCosto ? '+$' : '✏️'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {/* Indicador de carga para scroll infinito */}
            {pagination.paginationMode === 'infinite' && pagination.loading && pagination.currentPage > 1 && (
              <div className={styles.loadingMore}>
                Cargando más resultados...
              </div>
            )}

            {/* Mensaje de fin de resultados */}
            {pagination.paginationMode === 'infinite' && !pagination.hasMore && pagination.data.length > 0 && (
              <div className={styles.endOfResults}>
                ✓ Todos los resultados cargados
              </div>
            )}
          </div>
        </div>
      ) : stats ? (
        /* Tab de Resumen */
        <>
          {/* KPIs Principales - 3 cards grandes */}
          <div className={styles.kpisContainer}>
            <div className={styles.kpiCard}>
              <div className={styles.kpiIcon}>💰</div>
              <div className={styles.kpiContent}>
                <div className={styles.kpiLabel}>Total Facturado (sin IVA)</div>
                <div className={styles.kpiValue}>{formatearMoneda(stats.monto_total_sin_iva)}</div>
                <div className={styles.kpiStats}>
                  <span>{stats.total_ventas} ventas</span>
                  <span className={styles.kpiDivider}>•</span>
                  <span>{Math.round(stats.total_unidades)} unidades</span>
                </div>
              </div>
            </div>

            <div className={`${styles.kpiCard} ${styles.kpiGanancia}`}>
              <div className={styles.kpiIcon}>📈</div>
              <div className={styles.kpiContent}>
                <div className={styles.kpiLabel}>Ganancia Bruta</div>
                <div className={styles.kpiValue}>{formatearMoneda(calcularGanancia())}</div>
                <div className={styles.kpiStats}>
                  <span className={styles.kpiHighlight}>
                    {stats.markup_promedio !== null ? `${(stats.markup_promedio * 100).toFixed(1)}% markup prom` : 'Sin datos'}
                  </span>
                  <span className={styles.kpiDivider}>•</span>
                  <span>Costo: {formatearMoneda(stats.costo_total)}</span>
                </div>
              </div>
            </div>

            <div className={`${styles.kpiCard} ${styles.kpiLimpio}`}>
              <div className={styles.kpiIcon}>🧾</div>
              <div className={styles.kpiContent}>
                <div className={styles.kpiLabel}>Total con IVA</div>
                <div className={styles.kpiValue}>{formatearMoneda(stats.monto_total_con_iva)}</div>
                <div className={styles.kpiStats}>
                  <span>IVA: {formatearMoneda(stats.monto_total_con_iva - stats.monto_total_sin_iva)}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Métricas secundarias en fila */}
          <div className={styles.metricsRow}>
            <div className={styles.metricMini}>
              <span className={styles.metricMiniLabel}>Ticket Promedio</span>
              <span className={styles.metricMiniValue}>
                {formatearMoneda(stats.monto_total_sin_iva / stats.total_ventas)}
              </span>
            </div>
            <div className={styles.metricMini}>
              <span className={styles.metricMiniLabel}>Ganancia/Venta</span>
              <span className={styles.metricMiniValue}>
                {formatearMoneda(calcularGanancia() / stats.total_ventas)}
              </span>
            </div>
            <div className={styles.metricMini}>
              <span className={styles.metricMiniLabel}>Unids/Venta</span>
              <span className={styles.metricMiniValue}>
                {(stats.total_unidades / stats.total_ventas).toFixed(1)}
              </span>
            </div>
            <div className={styles.metricMini}>
              <span className={styles.metricMiniLabel}>Costo Promedio</span>
              <span className={styles.metricMiniValue}>
                {formatearMoneda(stats.costo_total / stats.total_unidades)}
              </span>
            </div>
            <div className={styles.metricMini}>
              <span className={styles.metricMiniLabel}>Margen Bruto</span>
              <span className={`${styles.metricMiniValue} ${calcularGanancia() > 0 ? styles.valorPositivo : styles.valorNegativo}`}>
                {((calcularGanancia() / stats.monto_total_sin_iva) * 100).toFixed(1)}%
              </span>
            </div>
          </div>

          {/* Gráficos y Tablas */}
          <div className={styles.chartsGrid}>
            {/* Ventas por Sucursal */}
            <div className={styles.chartCard}>
              <h3 className={styles.chartTitle}>🏢 Por Sucursal</h3>
              <div className={styles.rankingList}>
                {(() => {
                  const sucursales = Object.entries(stats.por_sucursal || {})
                    .map(([nombre, data]) => ({ nombre, ...data }))
                    .sort((a, b) => b.monto - a.monto);
                  const maxVenta = sucursales[0]?.monto || 1;

                  return sucursales.slice(0, 8).map((item, idx) => (
                    <div key={idx} className={styles.rankingItem}>
                      <div className={styles.rankingPosition}>{idx + 1}</div>
                      <div className={styles.rankingContent}>
                        <div className={styles.rankingHeader}>
                          <span className={styles.rankingName}>{item.nombre}</span>
                          <span className={styles.rankingAmount}>{formatearMoneda(item.monto)}</span>
                        </div>
                        <div className={styles.rankingBarBg}>
                          <div
                            className={styles.rankingBar}
                            style={{ width: `${(item.monto / maxVenta) * 100}%` }}
                          />
                        </div>
                        <div className={styles.rankingMeta}>
                          <span>{item.ventas} ventas</span>
                          <span>{Math.round(item.unidades)} unids</span>
                        </div>
                      </div>
                    </div>
                  ));
                })()}
              </div>
            </div>

            {/* Ventas por Vendedor */}
            <div className={styles.chartCard}>
              <h3 className={styles.chartTitle}>👤 Por Vendedor</h3>
              <div className={styles.rankingList}>
                {(() => {
                  const vendedores = Object.entries(stats.por_vendedor || {})
                    .map(([nombre, data]) => ({ nombre, ...data }))
                    .sort((a, b) => b.monto - a.monto);
                  const maxVenta = vendedores[0]?.monto || 1;

                  return vendedores.slice(0, 8).map((item, idx) => (
                    <div key={idx} className={styles.rankingItem}>
                      <div className={styles.rankingPosition}>{idx + 1}</div>
                      <div className={styles.rankingContent}>
                        <div className={styles.rankingHeader}>
                          <span className={styles.rankingName}>{item.nombre}</span>
                          <span className={styles.rankingAmount}>{formatearMoneda(item.monto)}</span>
                        </div>
                        <div className={styles.rankingBarBg}>
                          <div
                            className={`${styles.rankingBar} ${styles.rankingBarCategoria}`}
                            style={{ width: `${(item.monto / maxVenta) * 100}%` }}
                          />
                        </div>
                        <div className={styles.rankingMeta}>
                          <span>{item.ventas} ventas</span>
                          <span>{Math.round(item.unidades)} unids</span>
                        </div>
                      </div>
                    </div>
                  ));
                })()}
              </div>
            </div>
          </div>

          {/* Segunda fila: Marcas */}
          <div className={styles.chartsGrid}>
            {/* Ventas por Marca */}
            <div className={styles.chartCard}>
              <h3 className={styles.chartTitle}>🏷️ Top Marcas</h3>
              <div className={styles.rankingList}>
                {(() => {
                  const maxVenta = ventasPorMarca[0]?.monto_sin_iva || 1;
                  return ventasPorMarca.slice(0, 10).map((item, idx) => {
                    const ganancia = parseFloat(item.monto_sin_iva || 0) - parseFloat(item.costo_total || 0);
                    return (
                      <div key={idx} className={styles.rankingItem}>
                        <div className={styles.rankingPosition}>{idx + 1}</div>
                        <div className={styles.rankingContent}>
                          <div className={styles.rankingHeader}>
                            <span className={styles.rankingName}>{item.marca || 'Sin marca'}</span>
                            <span className={styles.rankingAmount}>{formatearMoneda(item.monto_sin_iva)}</span>
                          </div>
                          <div className={styles.rankingBarBg}>
                            <div
                              className={styles.rankingBar}
                              style={{ width: `${(parseFloat(item.monto_sin_iva) / maxVenta) * 100}%` }}
                            />
                          </div>
                          <div className={styles.rankingMeta}>
                            <span>Ganancia: {formatearMoneda(ganancia)}</span>
                            <span className={item.markup_promedio !== null && parseFloat(item.markup_promedio) >= 0.15 ? styles.markupBueno : item.markup_promedio !== null && parseFloat(item.markup_promedio) >= 0 ? styles.markupRegular : styles.markupMalo}>
                              {item.markup_promedio !== null ? `${(parseFloat(item.markup_promedio) * 100).toFixed(1)}% mkp` : '-'}
                            </span>
                            <span>{item.total_ventas} ops</span>
                          </div>
                        </div>
                      </div>
                    );
                  });
                })()}
              </div>
            </div>
          </div>

          {/* Top Productos (ancho completo) */}
          {topProductos.length > 0 && (
            <div className={styles.timelineCard}>
              <h3 className={styles.chartTitle}>⭐ Top Productos</h3>
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Código</th>
                      <th>Descripción</th>
                      <th>Marca</th>
                      <th>Ventas ($)</th>
                      <th>Unidades</th>
                      <th>Operaciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topProductos.map((item, idx) => (
                      <tr key={idx}>
                        <td>{item.codigo}</td>
                        <td className={styles.descripcion}>{item.descripcion}</td>
                        <td>{item.marca}</td>
                        <td className={styles.monto}>{formatearMoneda(item.monto_total)}</td>
                        <td className={styles.centrado}>{Math.round(item.unidades_vendidas)}</td>
                        <td className={styles.centrado}>{item.cantidad_operaciones}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className={styles.noData}>No hay datos disponibles</div>
      )}

      {/* Modal para editar costo */}
      <ModalEditarCosto
        mostrar={modalCostoAbierto}
        onClose={cerrarModalCosto}
        onSave={onCostoGuardado}
        operacion={operacionEditando}
      />
    </div>
  );
}
