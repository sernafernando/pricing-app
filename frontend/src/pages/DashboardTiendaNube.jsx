import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import api from '../services/api';
import styles from './DashboardMetricasML.module.css'; // Reutilizamos los estilos
import TabRentabilidadTiendaNube from '../components/TabRentabilidadTiendaNube';
import EditableCell from '../components/EditableCell';
import { useQueryFilters } from '../hooks/useQueryFilters';

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

export default function DashboardTiendaNube() {
  const [loading, setLoading] = useState(true);
  const [filtroRapidoActivo, setFiltroRapidoActivo] = useState('mesActual');
  const [mostrarDropdownFecha, setMostrarDropdownFecha] = useState(false);
  
  // Usar query params para tab, fechas y filtros
  const { getFilter, updateFilters } = useQueryFilters({
    tab: 'resumen',
    fecha_desde: getDefaultFechaDesde(),
    fecha_hasta: getDefaultFechaHasta(),
    sucursales: '',
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
  const [, setSucursalesDisponibles] = useState([]);
  const [vendedoresDisponibles, setVendedoresDisponibles] = useState([]);

  // Datos de operaciones detalladas
  const [operaciones, setOperaciones] = useState([]);
  const [busqueda, setBusqueda] = useState('');
  const [soloSinCosto, setSoloSinCosto] = useState(false);

  // Métodos de pago por operación
  const [metodosPago, setMetodosPago] = useState({});
  const [comisionTarjeta, setComisionTarjeta] = useState(3.0);
  const [comisionEfectivo, setComisionEfectivo] = useState(1.0);

  // Overrides de marca/categoría/subcategoría
  const [overrides, setOverrides] = useState({});
  const [jerarquiaProductos, setJerarquiaProductos] = useState({}); // { marca: { categoria: [subcategorias] } }

  const cargarDashboard = useCallback(async () => {
    setLoading(true);
    try {
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
        api.get('/ventas-tienda-nube/stats', { params }),
        api.get('/ventas-tienda-nube/por-marca', { params: { ...params, limit: 15 } }),
        api.get('/ventas-tienda-nube/top-productos', { params: { ...params, limit: 20 } })
      ]);

      setStats(statsRes.data);
      setVentasPorMarca(marcasRes.data || []);
      setTopProductos(productosRes.data || []);

      // Usar las listas completas de sucursales y vendedores disponibles
      if (statsRes.data) {
        setSucursalesDisponibles(statsRes.data.sucursales_disponibles || []);
        setVendedoresDisponibles(statsRes.data.vendedores_disponibles || []);
      }
    } catch {
      alert('Error al cargar el dashboard');
    } finally {
      setLoading(false);
    }
  }, [fechaDesde, fechaHasta, sucursalesSeleccionadas, vendedoresSeleccionados]);

  const cargarOperaciones = useCallback(async () => {
    setLoading(true);
    try {
      const params = {
        from_date: fechaDesde,
        to_date: fechaHasta,
        limit: 1000
      };

      // Agregar filtros si están seleccionados (enviar todos separados por coma)
      if (sucursalesSeleccionadas.length > 0) {
        params.sucursal = sucursalesSeleccionadas.join(',');
      }
      if (vendedoresSeleccionados.length > 0) {
        params.vendedor = vendedoresSeleccionados.join(',');
      }

      // Cargar operaciones, métodos de pago, overrides y jerarquía en paralelo
      const [operacionesRes, metodosPagoRes, constantesRes, overridesRes, jerarquiaRes] = await Promise.all([
        api.get('/ventas-tienda-nube', { params }),
        api.get('/ventas-tienda-nube/metodos-pago', { params: { from_date: fechaDesde, to_date: fechaHasta } }),
        api.get('/pricing-constants/actual'),
        api.get('/ventas-tienda-nube/overrides', { params: { from_date: fechaDesde, to_date: fechaHasta } }),
        api.get('/ventas-tienda-nube/jerarquia-productos').catch(() => ({ data: {} }))
      ]);

      setOperaciones(operacionesRes.data || []);
      setMetodosPago(metodosPagoRes.data || {});
      setOverrides(overridesRes.data || {});
      setJerarquiaProductos(jerarquiaRes.data || {});

      if (constantesRes.data) {
        setComisionEfectivo(constantesRes.data.comision_tienda_nube || 1.0);
        setComisionTarjeta(constantesRes.data.comision_tienda_nube_tarjeta || 3.0);
      }
    } catch {
      alert('Error al cargar las operaciones');
    } finally {
      setLoading(false);
    }
  }, [fechaDesde, fechaHasta, sucursalesSeleccionadas, vendedoresSeleccionados]);

  useEffect(() => {
    if (fechaDesde && fechaHasta) {
      cargarDashboard();
    }
  }, [fechaDesde, fechaHasta, sucursalesSeleccionadas, vendedoresSeleccionados, cargarDashboard]);

  useEffect(() => {
    if (fechaDesde && fechaHasta) {
      cargarOperaciones();
    }
  }, [fechaDesde, fechaHasta, sucursalesSeleccionadas, vendedoresSeleccionados, cargarOperaciones]);

  const cambiarMetodoPago = async (itTransaction, nuevoMetodo) => {
    try {
      await api.post('/ventas-tienda-nube/metodo-pago', {
        it_transaction: itTransaction,
        metodo_pago: nuevoMetodo
      });

      // Actualizar estado local
      setMetodosPago(prev => ({ ...prev, [itTransaction]: nuevoMetodo }));
    } catch {
      alert('Error al guardar el método de pago');
    }
  };

  // Ref para debounce de overrides
  const debounceTimers = useRef({});

  const guardarOverrideAPI = useCallback(async (itTransaction, campo, valor) => {
    try {
      await api.post('/ventas-tienda-nube/override', {
        it_transaction: itTransaction,
        [campo]: valor
      });
    } catch {
      alert('Error al guardar cambios');
    }
  }, []);

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

  // Filtrar operaciones por búsqueda
  const operacionesFiltradas = operaciones.filter(op => {
    if (soloSinCosto && op.costo_pesos_sin_iva && op.costo_pesos_sin_iva > 0) return false;
    if (!busqueda) return true;
    const searchLower = busqueda.toLowerCase();
    return (
      (op.codigo_item && op.codigo_item.toLowerCase().includes(searchLower)) ||
      (op.descripcion && op.descripcion.toLowerCase().includes(searchLower)) ||
      (op.marca && op.marca.toLowerCase().includes(searchLower)) ||
      (op.cliente && op.cliente.toLowerCase().includes(searchLower)) ||
      (op.vendedor && op.vendedor.toLowerCase().includes(searchLower))
    );
  });

  // Calcular ganancia para el resumen (monto limpio - costo)
  const calcularGanancia = () => {
    if (!stats) return 0;
    return stats.ganancia_total || 0;
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>🛒 Dashboard Tienda Nube</h1>

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
          {tabActivo !== 'rentabilidad' && (
            <button 
              onClick={tabActivo === 'resumen' ? cargarDashboard : cargarOperaciones} 
              className={styles.btnRecargar}
              title="Recargar"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="23 4 23 10 17 10"/>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
              </svg>
            </button>
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
            <label className={styles.checkboxLabel}>
              <input
                type="checkbox"
                checked={soloSinCosto}
                onChange={(e) => setSoloSinCosto(e.target.checked)}
              />
              Solo sin costo
            </label>
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
            📋 Operaciones
          </button>
          <button
            className={`${styles.tab} ${tabActivo === 'rentabilidad' ? styles.tabActivo : ''}`}
            onClick={() => updateFilters({ tab: 'rentabilidad' })}
          >
            💹 Rentabilidad
          </button>
        </div>
      </div>

      {/* Alerta de productos sin costo */}
      {stats && stats.productos_sin_costo > 0 && tabActivo === 'resumen' && (
        <div className={styles.alertaSinCosto}>
          ⚠️ El período seleccionado tiene <strong>{stats.productos_sin_costo} producto{stats.productos_sin_costo !== 1 ? 's' : ''}</strong> sin costo cargado, los cuales fueron excluidos de todas las métricas.
        </div>
      )}

      {tabActivo === 'rentabilidad' ? (
        <TabRentabilidadTiendaNube 
          fechaDesde={fechaDesde} 
          fechaHasta={fechaHasta}
          vendedoresSeleccionados={vendedoresSeleccionados}
        />
      ) : loading ? (
        <div className={styles.loading}>Cargando...</div>
      ) : tabActivo === 'operaciones' ? (
        /* Tab de Detalle de Operaciones */
        <div className={styles.operacionesContainer}>
          <div className={styles.buscadorContainer}>
            <input
              type="text"
              placeholder="🔍 Buscar por código, producto, marca, cliente o vendedor..."
              value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
              className={styles.buscador}
            />
            <div className={styles.resultadosCount}>
              {operacionesFiltradas.length} operación{operacionesFiltradas.length !== 1 ? 'es' : ''}
            </div>
          </div>

          <div className={styles.tableWrapper}>
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
                  <th>Método Pago</th>
                  <th>Comisión TN</th>
                  <th>Costo</th>
                  <th>Ganancia</th>
                  <th>Markup%</th>
                  <th>Comprobante</th>
                </tr>
              </thead>
              <tbody>
                {operacionesFiltradas.map((op, idx) => {
                  const sinCosto = !op.costo_pesos_sin_iva || op.costo_pesos_sin_iva === 0;
                  const metodoPagoActual = metodosPago[op.id_operacion] || 'efectivo';
                  const comisionAplicada = metodoPagoActual === 'tarjeta' ? comisionTarjeta : comisionEfectivo;

                  // Recalcular comisión, ganancia y markup basado en el método de pago actual
                  const montoSinIva = parseFloat(op.precio_final_sin_iva) || 0;
                  const costoSinIva = parseFloat(op.costo_pesos_sin_iva) || 0;
                  const comisionCalculada = montoSinIva * (comisionAplicada / 100);
                  const montoLimpio = montoSinIva - comisionCalculada;
                  const gananciaCalculada = montoLimpio - costoSinIva;
                  const markupCalculado = costoSinIva > 0 ? gananciaCalculada / costoSinIva : null;

                  // Valores efectivos (override o original)
                  const marcaEfectiva = getValorEfectivo(op, 'marca');
                  const categoriaEfectiva = getValorEfectivo(op, 'categoria');
                  const subcategoriaEfectiva = getValorEfectivo(op, 'subcategoria');
                  const clienteEfectivo = getValorEfectivo(op, 'cliente') || op.cliente || '';
                  const codigoEfectivo = getValorEfectivo(op, 'codigo') || op.codigo_item || '';
                  const descripcionEfectiva = getValorEfectivo(op, 'descripcion') || op.descripcion || '';
                  const tieneOverride = overrides[op.id_operacion];
                  
                  // Helper para className de campo con override
                  const getClaseConOverride = (campo) => {
                    return tieneOverride?.[campo] ? styles.campoOverride : '';
                  };

                  return (
                    <tr key={`${op.id_operacion}-${idx}`} className={sinCosto ? styles.rowSinCosto : ''}>
                      <td>{formatearFecha(op.fecha)}</td>
                      <td>{op.sucursal || '-'}</td>
                      <td className={styles.descripcion}>
                        <EditableCell
                          type="text"
                          value={clienteEfectivo}
                          onChange={(val) => guardarOverride(op.id_operacion, 'cliente', val)}
                          placeholder="Cliente"
                          className={getClaseConOverride('cliente') ? styles.hasOverride : ''}
                        />
                      </td>
                      <td>{op.vendedor || '-'}</td>
                      <td>
                        <EditableCell
                          type="text"
                          value={codigoEfectivo}
                          onChange={(val) => guardarOverride(op.id_operacion, 'codigo', val)}
                          placeholder="Código"
                          className={getClaseConOverride('codigo') ? styles.hasOverride : ''}
                        />
                      </td>
                      <td className={styles.descripcion}>
                        <EditableCell
                          type="text"
                          value={descripcionEfectiva}
                          onChange={(val) => guardarOverride(op.id_operacion, 'descripcion', val)}
                          placeholder="Descripción"
                          className={getClaseConOverride('descripcion') ? styles.hasOverride : ''}
                        />
                      </td>
                      <td>
                        <EditableCell
                          type="select"
                          value={marcaEfectiva}
                          onChange={(val) => {
                            guardarOverride(op.id_operacion, 'marca', val);
                            // Limpiar categoría y subcategoría si cambia la marca
                            if (val !== marcaEfectiva) {
                              guardarOverride(op.id_operacion, 'categoria', '');
                              guardarOverride(op.id_operacion, 'subcategoria', '');
                            }
                          }}
                          options={[
                            ...getMarcasDisponibles(),
                            ...(marcaEfectiva && !getMarcasDisponibles().includes(marcaEfectiva) ? [marcaEfectiva] : [])
                          ]}
                          placeholder="Sin marca"
                          className={getClaseConOverride('marca') ? styles.hasOverride : ''}
                        />
                      </td>
                      <td>
                        <EditableCell
                          type="select"
                          value={categoriaEfectiva}
                          onChange={(val) => {
                            guardarOverride(op.id_operacion, 'categoria', val);
                            // Limpiar subcategoría si cambia la categoría
                            if (val !== categoriaEfectiva) {
                              guardarOverride(op.id_operacion, 'subcategoria', '');
                            }
                          }}
                          options={[
                            ...getCategoriasParaMarca(marcaEfectiva),
                            ...(categoriaEfectiva && !getCategoriasParaMarca(marcaEfectiva).includes(categoriaEfectiva) ? [categoriaEfectiva] : [])
                          ]}
                          placeholder={marcaEfectiva ? 'Sin categoría' : 'Seleccione marca primero'}
                          disabled={!marcaEfectiva}
                          className={getClaseConOverride('categoria') ? styles.hasOverride : ''}
                        />
                      </td>
                      <td>
                        <EditableCell
                          type="select"
                          value={subcategoriaEfectiva}
                          onChange={(val) => guardarOverride(op.id_operacion, 'subcategoria', val)}
                          options={[
                            ...getSubcategoriasParaCategoria(marcaEfectiva, categoriaEfectiva),
                            ...(subcategoriaEfectiva && !getSubcategoriasParaCategoria(marcaEfectiva, categoriaEfectiva).includes(subcategoriaEfectiva) ? [subcategoriaEfectiva] : [])
                          ]}
                          placeholder={categoriaEfectiva ? 'Sin subcategoría' : 'Seleccione categoría primero'}
                          disabled={!categoriaEfectiva}
                          className={getClaseConOverride('subcategoria') ? styles.hasOverride : ''}
                        />
                      </td>
                      <td className={styles.centrado}>
                        <EditableCell
                          type="number"
                          value={getValorEfectivo(op, 'cantidad') || op.cantidad || ''}
                          onChange={(val) => guardarOverride(op.id_operacion, 'cantidad', val)}
                          step={0.01}
                          className={getClaseConOverride('cantidad') ? styles.hasOverride : ''}
                        />
                      </td>
                      <td className={styles.monto}>
                        <EditableCell
                          type="number"
                          value={getValorEfectivo(op, 'precio_unitario') || op.precio_unitario_sin_iva || ''}
                          onChange={(val) => guardarOverride(op.id_operacion, 'precio_unitario', val)}
                          step={0.01}
                          className={getClaseConOverride('precio_unitario') ? styles.hasOverride : ''}
                        />
                      </td>
                      <td className={styles.centrado}>{op.iva_porcentaje}%</td>
                      <td className={styles.monto}>{formatearMoneda(op.precio_final_sin_iva)}</td>
                      <td>
                        <EditableCell
                          type="select"
                          value={metodoPagoActual}
                          onChange={(val) => cambiarMetodoPago(op.id_operacion, val)}
                          options={[
                            { value: 'efectivo', label: `Efectivo (${comisionEfectivo}%)` },
                            { value: 'tarjeta', label: `Tarjeta (${comisionTarjeta}%)` }
                          ]}
                          className={metodoPagoActual === 'tarjeta' ? styles.metodoPagoTarjeta : styles.metodoPagoEfectivo}
                        />
                      </td>
                      <td className={`${styles.monto} ${styles.asteriscoModificado}`}>
                        {formatearMoneda(comisionCalculada)} ({comisionAplicada}%)
                      </td>
                      <td className={styles.monto}>
                        <EditableCell
                          type="number"
                          value={getValorEfectivo(op, 'costo_unitario') || op.costo_unitario || ''}
                          onChange={(val) => guardarOverride(op.id_operacion, 'costo_unitario', val)}
                          step={0.01}
                          placeholder={sinCosto ? 'Sin costo' : ''}
                          className={`${getClaseConOverride('costo_unitario') ? styles.hasOverride : ''} ${sinCosto && !tieneOverride?.costo_unitario ? styles.campoSinCostoInput : ''}`}
                        />
                      </td>
                      <td className={`${styles.monto} ${gananciaCalculada >= 0 ? styles.valorPositivo : styles.valorNegativo}`}>
                        {formatearMoneda(gananciaCalculada)}
                      </td>
                      <td className={`${styles.centrado} ${markupCalculado !== null && markupCalculado < 0 ? styles.negativo : ''}`}>
                        {formatearPorcentaje(markupCalculado)}
                      </td>
                      <td>{op.tipo_comprobante} {op.numero_comprobante}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : stats ? (
        /* Tab de Resumen */
        <>
          {/* KPIs Principales - 4 cards grandes */}
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

            <div className={styles.kpiCard} style={{ borderLeftColor: '#f59e0b' }}>
              <div className={styles.kpiIcon}>🏷️</div>
              <div className={styles.kpiContent}>
                <div className={styles.kpiLabel}>Comisión Tienda Nube ({stats.comision_tn_porcentaje}%)</div>
                <div className={styles.kpiValue} style={{ color: '#f59e0b' }}>{formatearMoneda(stats.comision_tn_total)}</div>
                <div className={styles.kpiStats}>
                  <span>Monto limpio: {formatearMoneda(stats.monto_limpio_total)}</span>
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
                    {stats.markup_promedio !== null ? `${(stats.markup_promedio * 100).toFixed(1)}% markup` : 'Sin datos'}
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
              <span className={styles.metricMiniValue} style={{ color: calcularGanancia() > 0 ? '#10b981' : '#ef4444' }}>
                {((calcularGanancia() / stats.monto_limpio_total) * 100).toFixed(1)}%
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
    </div>
  );
}
