import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import api from '../services/api';
import styles from './DashboardMetricasML.module.css';
import TabRentabilidad from '../components/TabRentabilidad';
import PaginationControls from '../components/PaginationControls';
import { useQueryFilters } from '../hooks/useQueryFilters';
import { useServerPagination } from '../hooks/useServerPagination';

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

export default function DashboardMetricasML() {
  const [loading, setLoading] = useState(true);
  const [filtroRapidoActivo, setFiltroRapidoActivo] = useState('mesActual');
  const [mostrarDropdownFecha, setMostrarDropdownFecha] = useState(false);
  
  // Usar query params para tab, fechas y filtros de resumen
  const { getFilter, updateFilters } = useQueryFilters({
    tab: 'resumen',
    fecha_desde: getDefaultFechaDesde(),
    fecha_hasta: getDefaultFechaHasta(),
    marcas: '',
    categorias: '',
    tiendas_oficiales: '',
    pms: ''
  });

  const tabActivo = getFilter('tab');
  const fechaDesde = getFilter('fecha_desde');
  const fechaHasta = getFilter('fecha_hasta');
  const marcasQuery = getFilter('marcas');
  const categoriasQuery = getFilter('categorias');
  const tiendasOficialesQuery = getFilter('tiendas_oficiales');
  const pmsQuery = getFilter('pms');
  
  // Convertir strings a arrays
  const marcasSeleccionadas = useMemo(() => {
    if (!marcasQuery) return [];
    return marcasQuery.split(',').filter(Boolean);
  }, [marcasQuery]);

  const categoriasSeleccionadas = useMemo(() => {
    if (!categoriasQuery) return [];
    return categoriasQuery.split(',').filter(Boolean);
  }, [categoriasQuery]);

  const tiendasOficialesSeleccionadas = useMemo(() => {
    if (!tiendasOficialesQuery) return [];
    return tiendasOficialesQuery.split(',').filter(Boolean);
  }, [tiendasOficialesQuery]);

  const pmsSeleccionados = useMemo(() => {
    if (!pmsQuery) return [];
    return pmsQuery.split(',').filter(Boolean).map(id => parseInt(id.trim(), 10));
  }, [pmsQuery]);

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
  const [metricasGenerales, setMetricasGenerales] = useState(null);
  const [ventasPorMarca, setVentasPorMarca] = useState([]);
  const [ventasPorCategoria, setVentasPorCategoria] = useState([]);
  const [ventasPorLogistica, setVentasPorLogistica] = useState([]);
  const [ventasPorDia, setVentasPorDia] = useState([]);
  const [topProductos, setTopProductos] = useState([]);
  const [pms, setPms] = useState([]);

  // Opciones disponibles para los filtros (independientes de los datos filtrados)
  const [marcasDisponibles, setMarcasDisponibles] = useState([]);
  const [categoriasDisponibles, setCategoriasDisponibles] = useState([]);

  // Búsquedas en filtros
  const [busquedaMarca, setBusquedaMarca] = useState('');
  const [busquedaCategoria, setBusquedaCategoria] = useState('');

  // Toast notification
  const [toast, setToast] = useState(null);
  const toastTimeoutRef = useRef(null);

  // Función para mostrar toast
  const showToast = (message, type = 'success') => {
    if (toastTimeoutRef.current) {
      clearTimeout(toastTimeoutRef.current);
    }
    setToast({ message, type });
    toastTimeoutRef.current = setTimeout(() => setToast(null), 3000);
  };

  // Cleanup del toast timeout al desmontar
  useEffect(() => {
    return () => {
      if (toastTimeoutRef.current) {
        clearTimeout(toastTimeoutRef.current);
      }
    };
  }, []);

  // Hook de paginación server-side (solo para tab de operaciones)
  const paginationFilters = useMemo(() => ({
    from_date: fechaDesde,
    to_date: fechaHasta,
    ...(marcasSeleccionadas.length > 0 && { marcas: marcasSeleccionadas.join(',') }),
    ...(categoriasSeleccionadas.length > 0 && { categorias: categoriasSeleccionadas.join(',') }),
    ...(tiendasOficialesSeleccionadas.length > 0 && { tiendas_oficiales: tiendasOficialesSeleccionadas.join(',') }),
    ...(pmsSeleccionados.length > 0 && { pm_ids: pmsSeleccionados.join(',') })
  }), [fechaDesde, fechaHasta, marcasSeleccionadas, categoriasSeleccionadas, tiendasOficialesSeleccionadas, pmsSeleccionados]);

  const pagination = useServerPagination({
    endpoint: '/ventas-ml/operaciones-con-metricas',
    countEndpoint: null, // ML no tiene endpoint count todavía
    filters: paginationFilters,
    pageSize: 1000,
    enabled: tabActivo === 'operaciones'
  });

  // Cargar opciones disponibles para filtros
  const cargarOpcionesDisponibles = useCallback(async () => {
    try {
      // Params comunes para ambos endpoints
      const baseParams = {
        fecha_desde: fechaDesde,
        fecha_hasta: fechaHasta
      };
      if (tiendasOficialesSeleccionadas.length > 0) baseParams.tiendas_oficiales = tiendasOficialesSeleccionadas.join(',');
      if (pmsSeleccionados.length > 0) baseParams.pm_ids = pmsSeleccionados.join(',');

      // Para marcas disponibles: aplicar filtro de categorías (pero no de marcas)
      const marcasParams = { ...baseParams };
      if (categoriasSeleccionadas.length > 0) marcasParams.categorias = categoriasSeleccionadas.join(',');

      // Para categorías disponibles: aplicar filtro de marcas (pero no de categorías)
      const categoriasParams = { ...baseParams };
      if (marcasSeleccionadas.length > 0) categoriasParams.marcas = marcasSeleccionadas.join(',');

      const [marcasRes, categoriasRes] = await Promise.all([
        api.get('/dashboard-ml/marcas-disponibles', { params: marcasParams }),
        api.get('/dashboard-ml/categorias-disponibles', { params: categoriasParams })
      ]);

      setMarcasDisponibles(marcasRes.data || []);
      setCategoriasDisponibles(categoriasRes.data || []);
    } catch (error) {
      console.error('Error cargando opciones disponibles:', error);
      setMarcasDisponibles([]);
      setCategoriasDisponibles([]);
    }
  }, [fechaDesde, fechaHasta, marcasSeleccionadas, categoriasSeleccionadas, tiendasOficialesSeleccionadas, pmsSeleccionados]);




  const cargarDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const params = {
        fecha_desde: fechaDesde,
        fecha_hasta: fechaHasta
      };

      if (marcasSeleccionadas.length > 0) params.marcas = marcasSeleccionadas.join(',');
      if (categoriasSeleccionadas.length > 0) params.categorias = categoriasSeleccionadas.join(',');
      if (tiendasOficialesSeleccionadas.length > 0) params.tiendas_oficiales = tiendasOficialesSeleccionadas.join(',');
      if (pmsSeleccionados.length > 0) params.pm_ids = pmsSeleccionados.join(',');

      // Cargar todos los datos en paralelo
      const [
        metricasRes,
        marcasRes,
        categoriasRes,
        logisticaRes,
        diasRes,
        productosRes
      ] = await Promise.all([
        api.get('/dashboard-ml/metricas-generales', { params }),
        api.get('/dashboard-ml/por-marca', { params }),
        api.get('/dashboard-ml/por-categoria', { params }),
        api.get('/dashboard-ml/por-logistica', { params }),
        api.get('/dashboard-ml/por-dia', { params }),
        api.get('/dashboard-ml/top-productos', { params })
      ]);

      setMetricasGenerales(metricasRes.data);
      setVentasPorMarca(marcasRes.data || []);
      setVentasPorCategoria(categoriasRes.data || []);
      setVentasPorLogistica(logisticaRes.data || []);
      setVentasPorDia(diasRes.data || []);
      setTopProductos(productosRes.data || []);
    } catch {
      alert('Error al cargar el dashboard');
    } finally {
      setLoading(false);
    }
  }, [fechaDesde, fechaHasta, marcasSeleccionadas, categoriasSeleccionadas, tiendasOficialesSeleccionadas, pmsSeleccionados]);

  useEffect(() => {
    if (fechaDesde && fechaHasta) {
      cargarDashboard();
      cargarOpcionesDisponibles();
    }
  }, [fechaDesde, fechaHasta, cargarDashboard, cargarOpcionesDisponibles]);

  // Cargar PMs y opciones de filtros al montar el componente
  useEffect(() => {
    const cargarPMs = async () => {
      try {
        const response = await api.get('/usuarios/pms', { params: { solo_con_marcas: true } });
        setPms(response.data);
      } catch (error) {
        console.error('Error al cargar PMs:', error);
      }
    };
    cargarPMs();
    cargarOpcionesDisponibles();
  }, [cargarOpcionesDisponibles]);

  const formatearMoneda = (monto) => {
    return new Intl.NumberFormat('es-AR', {
      style: 'currency',
      currency: 'ARS',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(monto || 0);
  };

  const formatearPorcentaje = (valor) => {
    return `${parseFloat(valor || 0).toFixed(2)}%`;
  };

  const formatearFecha = (fecha) => {
    return new Date(fecha).toLocaleDateString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric'
    });
  };

  const getTipoLogistica = (tipo) => {
    const tipos = {
      'cross_docking': '📦 Colecta',
      'self_service': '🛵 Flex',
      'fulfillment': '📦 Full',
      'default': '🏢 Retiro',
      'drop_off': '📮 Drop Off',
      'xd_drop_off': '📮 XD Drop Off'
    };
    return tipos[tipo] || tipo;
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

  // Handlers para selector múltiple de Marcas
  const toggleMarca = (marca) => {
    const nuevasSeleccionadas = marcasSeleccionadas.includes(marca)
      ? marcasSeleccionadas.filter(m => m !== marca)
      : [...marcasSeleccionadas, marca];
    
    updateFilters({ marcas: nuevasSeleccionadas.join(',') || '' });
  };

  const limpiarMarcas = () => {
    updateFilters({ marcas: '' });
  };

  // Handlers para selector múltiple de Categorías
  const toggleCategoria = (categoria) => {
    const nuevasSeleccionadas = categoriasSeleccionadas.includes(categoria)
      ? categoriasSeleccionadas.filter(c => c !== categoria)
      : [...categoriasSeleccionadas, categoria];
    
    updateFilters({ categorias: nuevasSeleccionadas.join(',') || '' });
  };

  const limpiarCategorias = () => {
    updateFilters({ categorias: '' });
  };

  // Handlers para selector múltiple de Tiendas Oficiales
  const toggleTiendaOficial = (tiendaId) => {
    const nuevasSeleccionadas = tiendasOficialesSeleccionadas.includes(tiendaId)
      ? tiendasOficialesSeleccionadas.filter(t => t !== tiendaId)
      : [...tiendasOficialesSeleccionadas, tiendaId];
    
    updateFilters({ tiendas_oficiales: nuevasSeleccionadas.join(',') || '' });
  };

  const limpiarTiendasOficiales = () => {
    updateFilters({ tiendas_oficiales: '' });
  };

  // Exportar operaciones a Excel
  const exportarOperaciones = async () => {
    try {
      showToast('Generando archivo Excel...', 'info');
      
      const params = {
        from_date: fechaDesde,
        to_date: fechaHasta
      };
      
      if (marcasSeleccionadas.length > 0) params.marcas = marcasSeleccionadas.join(',');
      if (categoriasSeleccionadas.length > 0) params.categorias = categoriasSeleccionadas.join(',');
      if (tiendasOficialesSeleccionadas.length > 0) params.tiendas_oficiales = tiendasOficialesSeleccionadas.join(',');
      if (pmsSeleccionados.length > 0) params.pm_ids = pmsSeleccionados.join(',');
      
      const response = await api.get('/ventas-ml/exportar-operaciones', {
        params,
        responseType: 'blob'
      });
      
      // Crear URL del blob y descargar
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `operaciones_ml_${fechaDesde}_${fechaHasta}.xlsx`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      
      showToast('✅ Archivo descargado correctamente', 'success');
    } catch (error) {
      console.error('Error exportando operaciones:', error);
      showToast('❌ Error al exportar operaciones', 'error');
    }
  };

  // Handlers para selector múltiple de PMs
  const togglePM = (pmId) => {
    const nuevosSeleccionados = pmsSeleccionados.includes(pmId)
      ? pmsSeleccionados.filter(id => id !== pmId)
      : [...pmsSeleccionados, pmId];
    
    updateFilters({ pms: nuevosSeleccionados.join(',') || '' });
  };

  const limpiarPMs = () => {
    updateFilters({ pms: '' });
  };

  // La búsqueda ahora es server-side via el hook
  const operacionesFiltradas = pagination.data;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>📊 Dashboard Métricas ML</h1>

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
            💰 Rentabilidad
          </button>
        </div>

        {/* Contenedor con filtros rápidos + botón reload */}
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
          {tabActivo !== 'rentabilidad' && (
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
        </div>

        <div className={styles.filtros}>
          {tabActivo !== 'rentabilidad' && (
            <>
              {/* Filtro de MARCAS: selector múltiple */}
              <div className={styles.filtroSelect}>
                <label>MARCAS:</label>
                <div className={styles.multiSelect}>
                  <div className={styles.multiSelectHeader}>
                    <span className={styles.multiSelectLabel}>
                      {marcasSeleccionadas.length === 0 
                        ? 'Todas las marcas' 
                        : `${marcasSeleccionadas.length} marca${marcasSeleccionadas.length > 1 ? 's' : ''} seleccionada${marcasSeleccionadas.length > 1 ? 's' : ''}`}
                    </span>
                  </div>
                  <div className={styles.multiSelectDropdown}>
                    {marcasSeleccionadas.length > 0 && (
                      <div className={styles.multiSelectActions}>
                        <button 
                          type="button" 
                          onClick={limpiarMarcas}
                          className={styles.btnMultiSelectAction}
                        >
                          ✗ Limpiar selección
                        </button>
                      </div>
                    )}
                    <div className={styles.multiSelectSearch}>
                      <input
                        type="text"
                        placeholder="Buscar marca..."
                        value={busquedaMarca}
                        onChange={(e) => setBusquedaMarca(e.target.value)}
                        className={styles.multiSelectSearchInput}
                      />
                    </div>
                    <div className={styles.multiSelectOptions}>
                      {marcasDisponibles
                        .filter(marca => marca.toLowerCase().includes(busquedaMarca.toLowerCase()))
                        .map(marca => (
                          <label key={marca} className={styles.multiSelectOption}>
                            <input
                              type="checkbox"
                              checked={marcasSeleccionadas.includes(marca)}
                              onChange={() => toggleMarca(marca)}
                            />
                            <span>{marca}</span>
                          </label>
                        ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* Filtro de CATEGORÍAS: selector múltiple */}
              <div className={styles.filtroSelect}>
                <label>CATEGORÍAS:</label>
                <div className={styles.multiSelect}>
                  <div className={styles.multiSelectHeader}>
                    <span className={styles.multiSelectLabel}>
                      {categoriasSeleccionadas.length === 0 
                        ? 'Todas las categorías' 
                        : `${categoriasSeleccionadas.length} categoría${categoriasSeleccionadas.length > 1 ? 's' : ''} seleccionada${categoriasSeleccionadas.length > 1 ? 's' : ''}`}
                    </span>
                  </div>
                  <div className={styles.multiSelectDropdown}>
                    {categoriasSeleccionadas.length > 0 && (
                      <div className={styles.multiSelectActions}>
                        <button 
                          type="button" 
                          onClick={limpiarCategorias}
                          className={styles.btnMultiSelectAction}
                        >
                          ✗ Limpiar selección
                        </button>
                      </div>
                    )}
                    <div className={styles.multiSelectSearch}>
                      <input
                        type="text"
                        placeholder="Buscar categoría..."
                        value={busquedaCategoria}
                        onChange={(e) => setBusquedaCategoria(e.target.value)}
                        className={styles.multiSelectSearchInput}
                      />
                    </div>
                    <div className={styles.multiSelectOptions}>
                      {categoriasDisponibles
                        .filter(cat => cat.toLowerCase().includes(busquedaCategoria.toLowerCase()))
                        .map(cat => (
                          <label key={cat} className={styles.multiSelectOption}>
                            <input
                              type="checkbox"
                              checked={categoriasSeleccionadas.includes(cat)}
                              onChange={() => toggleCategoria(cat)}
                            />
                            <span>{cat}</span>
                          </label>
                        ))}
                    </div>
                  </div>
                </div>
              </div>
            </>
          )}

          {/* Filtro de TIENDAS OFICIALES: selector múltiple (visible en todas las tabs) */}
          <div className={styles.filtroSelect}>
            <label>TIENDAS OFICIALES:</label>
            <div className={styles.multiSelect}>
              <div className={styles.multiSelectHeader}>
                <span className={styles.multiSelectLabel}>
                  {tiendasOficialesSeleccionadas.length === 0 
                    ? 'Todas las tiendas' 
                    : `${tiendasOficialesSeleccionadas.length} tienda${tiendasOficialesSeleccionadas.length > 1 ? 's' : ''} seleccionada${tiendasOficialesSeleccionadas.length > 1 ? 's' : ''}`}
                </span>
              </div>
              <div className={styles.multiSelectDropdown}>
                {tiendasOficialesSeleccionadas.length > 0 && (
                  <div className={styles.multiSelectActions}>
                    <button 
                      type="button" 
                      onClick={limpiarTiendasOficiales}
                      className={styles.btnMultiSelectAction}
                    >
                      ✗ Limpiar selección
                    </button>
                  </div>
                )}
                <div className={styles.multiSelectOptions}>
                  <label className={styles.multiSelectOption}>
                    <input
                      type="checkbox"
                      checked={tiendasOficialesSeleccionadas.includes('57997')}
                      onChange={() => toggleTiendaOficial('57997')}
                    />
                    <span>Gauss</span>
                  </label>
                  <label className={styles.multiSelectOption}>
                    <input
                      type="checkbox"
                      checked={tiendasOficialesSeleccionadas.includes('2645')}
                      onChange={() => toggleTiendaOficial('2645')}
                    />
                    <span>TP-Link</span>
                  </label>
                  <label className={styles.multiSelectOption}>
                    <input
                      type="checkbox"
                      checked={tiendasOficialesSeleccionadas.includes('144')}
                      onChange={() => toggleTiendaOficial('144')}
                    />
                    <span>Forza/Verbatim</span>
                  </label>
                  <label className={styles.multiSelectOption}>
                    <input
                      type="checkbox"
                      checked={tiendasOficialesSeleccionadas.includes('191942')}
                      onChange={() => toggleTiendaOficial('191942')}
                    />
                    <span>Multi-marca</span>
                  </label>
                </div>
              </div>
            </div>
          </div>

          {/* Filtro de PMs: selector múltiple */}
          <div className={styles.filtroSelect}>
            <label>PRODUCT MANAGERS:</label>
            <div className={styles.multiSelect}>
              <div className={styles.multiSelectHeader}>
                <span className={styles.multiSelectLabel}>
                  {pmsSeleccionados.length === 0 
                    ? 'Todos los PMs' 
                    : `${pmsSeleccionados.length} PM${pmsSeleccionados.length > 1 ? 's' : ''} seleccionado${pmsSeleccionados.length > 1 ? 's' : ''}`}
                </span>
              </div>
              <div className={styles.multiSelectDropdown}>
                {pmsSeleccionados.length > 0 && (
                  <div className={styles.multiSelectActions}>
                    <button 
                      type="button" 
                      onClick={limpiarPMs}
                      className={styles.btnMultiSelectAction}
                    >
                      ✗ Limpiar selección
                    </button>
                  </div>
                )}
                <div className={styles.multiSelectOptions}>
                  {pms.map(pm => (
                    <label key={pm.id} className={styles.multiSelectOption}>
                      <input
                        type="checkbox"
                        checked={pmsSeleccionados.includes(pm.id)}
                        onChange={() => togglePM(pm.id)}
                      />
                      <span>{pm.nombre} {pm.apellido}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {(loading || (tabActivo === 'operaciones' && pagination.loading && pagination.currentPage === 1)) ? (
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
              placeholder="🔍 Buscar por ML ID, código, producto o marca..."
              value={pagination.searchTerm}
              onChange={(e) => pagination.setSearchTerm(e.target.value)}
              className={styles.buscador}
            />
            <div className={styles.resultadosCount}>
              {operacionesFiltradas.length} operación{operacionesFiltradas.length !== 1 ? 'es' : ''}
            </div>
            <button
              onClick={() => exportarOperaciones()}
              className="btn-tesla outline-subtle-success sm"
              style={{ marginLeft: '12px' }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M19 12v7H5v-7H3v7c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2v-7h-2zm-6 .67l2.59-2.58L17 11.5l-5 5-5-5 1.41-1.41L11 12.67V3h2z"/></svg>
              Exportar
            </button>
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
                  <th>ML ID</th>
                  <th>Código</th>
                  <th>Producto</th>
                  <th>Marca</th>
                  <th>Cant</th>
                  <th>Precio Unit</th>
                  <th>Total</th>
                  <th>IVA%</th>
                  <th>Costo Unit</th>
                  <th>Costo Total</th>
                  <th>Comisión%</th>
                  <th>Comisión $</th>
                  <th>Envío s/IVA</th>
                  <th>Limpio</th>
                  <th>Markup%</th>
                  <th>Lista</th>
                </tr>
              </thead>
              <tbody>
                {operacionesFiltradas.map((op, idx) => (
                  <tr key={idx}>
                    <td>{formatearFecha(op.fecha_venta)}</td>
                    <td>{op.ml_id || '-'}</td>
                    <td>{op.codigo || '-'}</td>
                    <td className={styles.descripcion}>{op.descripcion || '-'}</td>
                    <td>{op.marca || '-'}</td>
                    <td className={styles.centrado}>{op.cantidad}</td>
                    <td className={styles.monto}>{formatearMoneda(op.monto_unitario)}</td>
                    <td className={styles.monto}>{formatearMoneda(op.monto_total)}</td>
                    <td className={styles.centrado}>{op.iva}%</td>
                    <td className={styles.monto}>{formatearMoneda(op.costo_sin_iva)}</td>
                    <td className={styles.monto}>{formatearMoneda(op.costo_total)}</td>
                    <td className={styles.centrado}>{formatearPorcentaje(op.comision_porcentaje)}</td>
                    <td className={styles.monto}>{formatearMoneda(op.comision_pesos)}</td>
                    <td className={styles.monto}>{formatearMoneda(op.costo_envio)}</td>
                    <td className={styles.monto}>{formatearMoneda(op.monto_limpio)}</td>
                    <td className={`${styles.centrado} ${parseFloat(op.markup_porcentaje) < 0 ? styles.negativo : ''}`}>
                      {formatearPorcentaje(op.markup_porcentaje)}
                    </td>
                    <td>{op.tipo_publicacion || '-'}</td>
                  </tr>
                ))}
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
      ) : tabActivo === 'rentabilidad' ? (
        /* Tab de Rentabilidad */
        <TabRentabilidad 
          fechaDesde={fechaDesde} 
          fechaHasta={fechaHasta}
          tiendasOficiales={tiendasOficialesSeleccionadas}
          pmsSeleccionados={pmsSeleccionados}
          marcasSeleccionadas={marcasSeleccionadas}
          categoriasSeleccionadas={categoriasSeleccionadas}
        />
      ) : metricasGenerales ? (
        /* Tab de Resumen (incluye tienda-oficial con filtro) */
        <>
          {/* Banner informativo si hay tiendas oficiales seleccionadas */}
          {tiendasOficialesSeleccionadas.length > 0 && (
            <div className={styles.bannerTiendaOficial}>
              🏪 Filtrando por: <strong>
                {tiendasOficialesSeleccionadas.map(id => {
                  if (id === '57997') return 'Gauss';
                  if (id === '2645') return 'TP-Link';
                  if (id === '144') return 'Forza/Verbatim';
                  if (id === '191942') return 'Multi-marca';
                  return id;
                }).join(', ')}
              </strong>
            </div>
          )}

          {/* KPIs Principales - 3 cards grandes */}
          <div className={styles.kpisContainer}>
            <div className={styles.kpiCard}>
              <div className={styles.kpiIcon}>💰</div>
              <div className={styles.kpiContent}>
                <div className={styles.kpiLabel}>Total Facturado</div>
                <div className={styles.kpiValue}>{formatearMoneda(metricasGenerales.total_ventas_ml)}</div>
                <div className={styles.kpiStats}>
                  <span>{metricasGenerales.cantidad_operaciones} ventas</span>
                  <span className={styles.kpiDivider}>•</span>
                  <span>{metricasGenerales.cantidad_unidades} unidades</span>
                </div>
              </div>
            </div>

            <div className={`${styles.kpiCard} ${styles.kpiGanancia}`}>
              <div className={styles.kpiIcon}>📈</div>
              <div className={styles.kpiContent}>
                <div className={styles.kpiLabel}>Ganancia Neta</div>
                <div className={styles.kpiValue}>{formatearMoneda(metricasGenerales.total_ganancia)}</div>
                <div className={styles.kpiStats}>
                  <span className={styles.kpiHighlight}>{formatearPorcentaje(metricasGenerales.markup_porcentaje)} markup</span>
                  <span className={styles.kpiDivider}>•</span>
                  <span>Costo: {formatearMoneda(metricasGenerales.total_costo)}</span>
                </div>
              </div>
            </div>

            <div className={`${styles.kpiCard} ${styles.kpiLimpio}`}>
              <div className={styles.kpiIcon}>✨</div>
              <div className={styles.kpiContent}>
                <div className={styles.kpiLabel}>Neto después de ML</div>
                <div className={styles.kpiValue}>{formatearMoneda(metricasGenerales.total_limpio)}</div>
                <div className={styles.kpiStats}>
                  <span>{formatearPorcentaje((metricasGenerales.total_limpio / (metricasGenerales.total_ventas_ml || 1)) * 100)} del facturado</span>
                </div>
              </div>
            </div>
          </div>

          {/* Métricas secundarias en fila */}
          <div className={styles.metricsRow}>
            <div className={styles.metricMini}>
              <span className={styles.metricMiniLabel}>Ticket Promedio</span>
              <span className={styles.metricMiniValue}>
                {formatearMoneda(metricasGenerales.total_ventas_ml / (metricasGenerales.cantidad_operaciones || 1))}
              </span>
            </div>
            <div className={styles.metricMini}>
              <span className={styles.metricMiniLabel}>Ganancia/Venta</span>
              <span className={styles.metricMiniValue}>
                {formatearMoneda(metricasGenerales.total_ganancia / (metricasGenerales.cantidad_operaciones || 1))}
              </span>
            </div>
            <div className={styles.metricMini}>
              <span className={styles.metricMiniLabel}>Unids/Venta</span>
              <span className={styles.metricMiniValue}>
                {(metricasGenerales.cantidad_unidades / (metricasGenerales.cantidad_operaciones || 1)).toFixed(1)}
              </span>
            </div>
            <div className={styles.metricMini}>
              <span className={styles.metricMiniLabel}>Comisiones ML</span>
              <span className={`${styles.metricMiniValue} ${styles.negativo}`}>
                -{formatearMoneda(metricasGenerales.total_comisiones)}
              </span>
              <span className={styles.metricMiniPercent}>
                {formatearPorcentaje((metricasGenerales.total_comisiones / (metricasGenerales.total_ventas_ml || 1)) * 100)}
              </span>
            </div>
            <div className={styles.metricMini}>
              <span className={styles.metricMiniLabel}>Envíos</span>
              <span className={`${styles.metricMiniValue} ${styles.negativo}`}>
                -{formatearMoneda(metricasGenerales.total_envios)}
              </span>
              <span className={styles.metricMiniPercent}>
                {formatearPorcentaje((metricasGenerales.total_envios / (metricasGenerales.total_ventas_ml || 1)) * 100)}
              </span>
            </div>
          </div>

          {/* Gráfico de barras - Ventas por día */}
          {ventasPorDia.length > 0 && (
            <div className={styles.chartBarCard}>
              <h3 className={styles.chartTitle}>📅 Ventas por Día</h3>
              <div className={styles.barChart}>
                {(() => {
                  const datos = ventasPorDia.slice(-14);
                  const valores = datos.map(d => parseFloat(d.total_ventas));
                  const maxVenta = Math.max(...valores);
                  const minVenta = Math.min(...valores);

                  return datos.map((dia, idx) => {
                    const valor = parseFloat(dia.total_ventas);
                    const esMax = valor === maxVenta && maxVenta !== minVenta;
                    const esMin = valor === minVenta && maxVenta !== minVenta;

                    let barClassName = styles.bar;
                    if (esMax) barClassName = styles.barMax;
                    else if (esMin) barClassName = styles.barMin;

                    return (
                      <div key={idx} className={styles.barGroup}>
                        <div className={styles.barContainer}>
                          <div
                            className={barClassName}
                            style={{ height: `${(valor / maxVenta) * 100}%` }}
                            title={`${formatearMoneda(valor)} - ${dia.cantidad_operaciones} ops`}
                          >
                            <span className={`${styles.barValue} ${(esMax || esMin) ? styles.barValueVisible : ''}`}>
                              {formatearMoneda(valor).replace('$ ', '')}
                            </span>
                          </div>
                        </div>
                        <div className={styles.barLabel}>
                          {new Date(dia.fecha + 'T12:00:00').toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit' })}
                        </div>
                        <div className={styles.barOps}>{dia.cantidad_operaciones}</div>
                      </div>
                    );
                  });
                })()}
              </div>
            </div>
          )}

          {/* Gráficos y Tablas */}
          <div className={styles.chartsGrid}>
            {/* Ventas por Marca */}
            <div className={styles.chartCard}>
              <h3 className={styles.chartTitle}>🏷️ Top Marcas</h3>
              <div className={styles.rankingList}>
                {(() => {
                  const maxVenta = ventasPorMarca[0]?.total_ventas || 1;
                  return ventasPorMarca.slice(0, 8).map((item, idx) => (
                    <div key={idx} className={styles.rankingItem}>
                      <div className={styles.rankingPosition}>{idx + 1}</div>
                      <div className={styles.rankingContent}>
                        <div className={styles.rankingHeader}>
                          <span className={styles.rankingName}>{item.marca}</span>
                          <span className={styles.rankingAmount}>{formatearMoneda(item.total_ventas)}</span>
                        </div>
                        <div className={styles.rankingBarBg}>
                          <div
                            className={styles.rankingBar}
                            style={{ width: `${(item.total_ventas / maxVenta) * 100}%` }}
                          />
                        </div>
                        <div className={styles.rankingMeta}>
                          <span>Ganancia: {formatearMoneda(item.total_ganancia)}</span>
                          <span className={parseFloat(item.markup_porcentaje) >= 15 ? styles.markupBueno : parseFloat(item.markup_porcentaje) >= 0 ? styles.markupRegular : styles.markupMalo}>
                            {formatearPorcentaje(item.markup_porcentaje)} mkp
                          </span>
                          <span>{item.cantidad_operaciones} ops</span>
                        </div>
                      </div>
                    </div>
                  ));
                })()}
              </div>
            </div>

            {/* Ventas por Categoría */}
            <div className={styles.chartCard}>
              <h3 className={styles.chartTitle}>📦 Top Categorías</h3>
              <div className={styles.rankingList}>
                {(() => {
                  const maxVenta = ventasPorCategoria[0]?.total_ventas || 1;
                  return ventasPorCategoria.slice(0, 8).map((item, idx) => (
                    <div key={idx} className={styles.rankingItem}>
                      <div className={styles.rankingPosition}>{idx + 1}</div>
                      <div className={styles.rankingContent}>
                        <div className={styles.rankingHeader}>
                          <span className={styles.rankingName}>{item.categoria}</span>
                          <span className={styles.rankingAmount}>{formatearMoneda(item.total_ventas)}</span>
                        </div>
                        <div className={styles.rankingBarBg}>
                          <div
                            className={`${styles.rankingBar} ${styles.rankingBarCategoria}`}
                            style={{ width: `${(item.total_ventas / maxVenta) * 100}%` }}
                          />
                        </div>
                        <div className={styles.rankingMeta}>
                          <span>Ganancia: {formatearMoneda(item.total_ganancia)}</span>
                          <span className={parseFloat(item.markup_porcentaje) >= 15 ? styles.markupBueno : parseFloat(item.markup_porcentaje) >= 0 ? styles.markupRegular : styles.markupMalo}>
                            {formatearPorcentaje(item.markup_porcentaje)} mkp
                          </span>
                        </div>
                      </div>
                    </div>
                  ));
                })()}
              </div>
            </div>
          </div>

          {/* Segunda fila: Logística */}
          <div className={styles.chartsGridSmall}>
            {/* Ventas por Logística */}
            <div className={styles.chartCard}>
              <h3 className={styles.chartTitle}>🚚 Por Tipo de Envío</h3>
              <div className={styles.logisticaGrid}>
                {ventasPorLogistica.map((item, idx) => (
                  <div key={idx} className={styles.logisticaCard}>
                    <div className={styles.logisticaIcon}>{getTipoLogistica(item.tipo_logistica).split(' ')[0]}</div>
                    <div className={styles.logisticaInfo}>
                      <div className={styles.logisticaNombre}>{getTipoLogistica(item.tipo_logistica).split(' ').slice(1).join(' ')}</div>
                      <div className={styles.logisticaVentas}>{formatearMoneda(item.total_ventas)}</div>
                      <div className={styles.logisticaMeta}>
                        <span>{item.cantidad_operaciones} ops</span>
                        <span className={styles.logisticaEnvio}>Envío: {formatearMoneda(item.total_envios)}</span>
                      </div>
                    </div>
                  </div>
                ))}
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
                      <th>Ventas</th>
                      <th>Ganancia</th>
                      <th>Markup</th>
                      <th>Unids</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topProductos.map((item, idx) => (
                      <tr key={idx}>
                        <td>{item.codigo}</td>
                        <td className={styles.descripcion}>{item.descripcion}</td>
                        <td>{item.marca}</td>
                        <td className={styles.monto}>{formatearMoneda(item.total_ventas)}</td>
                        <td className={styles.monto}>{formatearMoneda(item.total_ganancia)}</td>
                        <td className={styles.centrado}>{formatearPorcentaje(item.markup_porcentaje)}</td>
                        <td className={styles.centrado}>{item.cantidad_unidades}</td>
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

      {/* Toast notification */}
      {toast && (
        <div className={`toast-notification ${toast.type}`}>
          {toast.message}
        </div>
      )}
    </div>
  );
}
