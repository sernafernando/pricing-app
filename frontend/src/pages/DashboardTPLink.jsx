import { useState, useEffect, useCallback, useMemo } from 'react';
import api from '../services/api';
import { toLocalDateString } from '../utils/dateUtils';
import styles from './DashboardTPLink.module.css';
import { useToast } from '../hooks/useToast';
import Toast from '../components/Toast';
import PaginationControls from '../components/PaginationControls';
import { useQueryFilters } from '../hooks/useQueryFilters';
import { useServerPagination } from '../hooks/useServerPagination';
import { usePermisos } from '../contexts/PermisosContext';
import SearchInput from '../components/SearchInput';
import { BarChart3, ClipboardList, DollarSign, TrendingUp, Sparkles, Calendar, Package, Truck, X, Star, RefreshCw } from 'lucide-react';

const TPLINK_API_BASE = '/dashboard-tplink';

const getDefaultFechaDesde = () => {
  const hoy = new Date();
  const primerDiaMes = new Date(hoy.getFullYear(), hoy.getMonth(), 1);
  return toLocalDateString(primerDiaMes);
};

const getDefaultFechaHasta = () => {
  return toLocalDateString();
};

export default function DashboardTPLink() {
  const { tienePermiso } = usePermisos();
  const puedeVerGanancia = tienePermiso('dashboard_tplink.ver_ganancia');

  const [loading, setLoading] = useState(true);
  const [filtroRapidoActivo, setFiltroRapidoActivo] = useState('mesActual');
  const [mostrarDropdownFecha, setMostrarDropdownFecha] = useState(false);

  const { getFilter, updateFilters } = useQueryFilters({
    tab: 'resumen',
    fecha_desde: getDefaultFechaDesde(),
    fecha_hasta: getDefaultFechaHasta(),
    categorias: '',
  });

  const tabActivo = getFilter('tab');
  const fechaDesde = getFilter('fecha_desde');
  const fechaHasta = getFilter('fecha_hasta');
  const categoriasQuery = getFilter('categorias');

  const categoriasSeleccionadas = useMemo(() => {
    if (!categoriasQuery) return [];
    return categoriasQuery.split(',').filter(Boolean);
  }, [categoriasQuery]);

  const [fechaTemporal, setFechaTemporal] = useState({
    desde: fechaDesde,
    hasta: fechaHasta
  });

  useEffect(() => {
    setFechaTemporal({ desde: fechaDesde, hasta: fechaHasta });
  }, [fechaDesde, fechaHasta]);

  // Data state
  const [metricasGenerales, setMetricasGenerales] = useState(null);
  const [ventasPorCategoria, setVentasPorCategoria] = useState([]);
  const [ventasPorLogistica, setVentasPorLogistica] = useState([]);
  const [ventasPorDia, setVentasPorDia] = useState([]);
  const [topProductos, setTopProductos] = useState([]);
  const [topProductosFacturacion, setTopProductosFacturacion] = useState([]);
  const [topLimit, setTopLimit] = useState(10);
  const [categoriasDisponibles, setCategoriasDisponibles] = useState([]);
  const [busquedaCategoria, setBusquedaCategoria] = useState('');

  const { toast, showToast, hideToast } = useToast();

  const paginationFilters = useMemo(() => ({
    from_date: fechaDesde,
    to_date: fechaHasta,
    ...(categoriasSeleccionadas.length > 0 && { categorias: categoriasSeleccionadas.join(',') }),
  }), [fechaDesde, fechaHasta, categoriasSeleccionadas]);

  const pagination = useServerPagination({
    endpoint: `${TPLINK_API_BASE}/operaciones`,
    countEndpoint: null,
    filters: paginationFilters,
    pageSize: 1000,
    enabled: tabActivo === 'operaciones'
  });

  const cargarCategoriasDisponibles = useCallback(async () => {
    try {
      const params = { fecha_desde: fechaDesde, fecha_hasta: fechaHasta };
      if (categoriasSeleccionadas.length > 0) params.categorias = categoriasSeleccionadas.join(',');
      const res = await api.get(`${TPLINK_API_BASE}/categorias-disponibles`, { params });
      setCategoriasDisponibles(res.data || []);
    } catch {
      setCategoriasDisponibles([]);
    }
  }, [fechaDesde, fechaHasta, categoriasSeleccionadas]);

  const cargarDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const params = { fecha_desde: fechaDesde, fecha_hasta: fechaHasta };
      if (categoriasSeleccionadas.length > 0) params.categorias = categoriasSeleccionadas.join(',');

      const [
        metricasRes,
        categoriasRes,
        logisticaRes,
        diasRes,
        productosRes,
        productosFacturacionRes
      ] = await Promise.all([
        api.get(`${TPLINK_API_BASE}/metricas-generales`, { params }),
        api.get(`${TPLINK_API_BASE}/por-categoria`, { params }),
        api.get(`${TPLINK_API_BASE}/por-logistica`, { params }),
        api.get(`${TPLINK_API_BASE}/por-dia`, { params }),
        api.get(`${TPLINK_API_BASE}/top-productos`, { params: { ...params, limit: 50 } }),
        api.get(`${TPLINK_API_BASE}/top-productos`, { params: { ...params, limit: 50, orden: 'facturacion' } })
      ]);

      setMetricasGenerales(metricasRes.data);
      setVentasPorCategoria(categoriasRes.data || []);
      setVentasPorLogistica(logisticaRes.data || []);
      setVentasPorDia(diasRes.data || []);
      setTopProductos(productosRes.data || []);
      setTopProductosFacturacion(productosFacturacionRes.data || []);
    } catch {
      showToast('Error al cargar el dashboard TP-Link', 'error');
    } finally {
      setLoading(false);
    }
  }, [fechaDesde, fechaHasta, categoriasSeleccionadas, showToast]);

  useEffect(() => {
    if (fechaDesde && fechaHasta) {
      cargarDashboard();
      cargarCategoriasDisponibles();
    }
  }, [fechaDesde, fechaHasta, cargarDashboard, cargarCategoriasDisponibles]);

  const formatearMoneda = (monto) => {
    return new Intl.NumberFormat('es-AR', {
      style: 'currency',
      currency: 'ARS',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(monto || 0);
  };

  const formatearPorcentaje = (valor) => `${parseFloat(valor || 0).toFixed(2)}%`;

  const formatearFecha = (fecha) => {
    return new Date(fecha).toLocaleDateString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric'
    });
  };

  const getTipoLogistica = (tipo) => {
    const tipos = {
      'cross_docking': 'Colecta',
      'self_service': 'Flex',
      'fulfillment': 'Full',
      'default': 'Retiro',
      'drop_off': 'Drop Off',
      'xd_drop_off': 'XD Drop Off'
    };
    return tipos[tipo] || tipo;
  };

  const aplicarFiltroRapido = (filtro) => {
    const hoy = new Date();
    const fmt = (f) => toLocalDateString(f);
    let desde, hasta = hoy;

    switch (filtro) {
      case 'hoy': desde = new Date(hoy); break;
      case 'ayer':
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 1);
        hasta = new Date(desde);
        break;
      case '3d': desde = new Date(hoy); desde.setDate(desde.getDate() - 2); break;
      case '7d': desde = new Date(hoy); desde.setDate(desde.getDate() - 6); break;
      case '14d': desde = new Date(hoy); desde.setDate(desde.getDate() - 13); break;
      case 'mesActual': desde = new Date(hoy.getFullYear(), hoy.getMonth(), 1); break;
      case '30d': desde = new Date(hoy); desde.setDate(desde.getDate() - 29); break;
      case '3m': desde = new Date(hoy); desde.setMonth(desde.getMonth() - 3); break;
      default: return;
    }

    setFiltroRapidoActivo(filtro);
    setMostrarDropdownFecha(false);
    updateFilters({ fecha_desde: fmt(desde), fecha_hasta: fmt(hasta) });
  };

  const aplicarFechaPersonalizada = () => {
    setFiltroRapidoActivo('custom');
    setMostrarDropdownFecha(false);
    updateFilters({ fecha_desde: fechaTemporal.desde, fecha_hasta: fechaTemporal.hasta });
  };

  const toggleCategoria = (categoria) => {
    const nuevas = categoriasSeleccionadas.includes(categoria)
      ? categoriasSeleccionadas.filter(c => c !== categoria)
      : [...categoriasSeleccionadas, categoria];
    updateFilters({ categorias: nuevas.join(',') || '' });
  };

  const limpiarCategorias = () => updateFilters({ categorias: '' });

  const operacionesFiltradas = pagination.data;

  // Helper: render masked value when user lacks ver_ganancia
  const renderGanancia = (value) => {
    if (!puedeVerGanancia) return '***';
    if (value === undefined || value === null) return '—';
    return formatearMoneda(value);
  };

  const renderMarkup = (value) => {
    if (!puedeVerGanancia) return '***';
    if (value === undefined || value === null) return '—';
    return formatearPorcentaje(value);
  };

  return (
    <div className={styles.container}>
      {/* Brand header bar */}
      <div className={styles.brandHeader}>
        <img
          src="/brand/tplink-logo-white.png"
          alt="TP-Link logo"
          className={styles.brandLogo}
        />
        <span className={styles.brandTitle}>Dashboard TP-Link</span>
      </div>

      <div className={styles.header}>
        {/* Tabs */}
        <div className={styles.tabs}>
          <button
            className={`${styles.tab} ${tabActivo === 'resumen' ? styles.tabActivo : ''}`}
            onClick={() => updateFilters({ tab: 'resumen' })}
          >
            <BarChart3 size={14} /> Resumen
          </button>
          <button
            className={`${styles.tab} ${tabActivo === 'operaciones' ? styles.tabActivo : ''}`}
            onClick={() => updateFilters({ tab: 'operaciones' })}
          >
            <ClipboardList size={14} /> Detalle de Operaciones
          </button>
        </div>

        {/* Quick date filters + reload */}
        <div className={styles.filtrosRapidosWrapper}>
          <div className={styles.filtrosRapidos}>
            <button
              onClick={() => setMostrarDropdownFecha(!mostrarDropdownFecha)}
              className={`${styles.btnFiltroRapido} ${styles.btnCalendar}`}
              title="Seleccionar rango personalizado"
            >
              <Calendar size={16} />
            </button>
            {['hoy', 'ayer', '3d', '7d', '14d', 'mesActual', '30d', '3m'].map((f) => (
              <button
                key={f}
                onClick={() => aplicarFiltroRapido(f)}
                className={`${styles.btnFiltroRapido} ${filtroRapidoActivo === f ? styles.activo : ''}`}
              >
                {f === 'mesActual' ? 'Mes actual' : f}
              </button>
            ))}

            {mostrarDropdownFecha && (
              <>
                <div className={styles.dropdownOverlay} onClick={() => setMostrarDropdownFecha(false)} />
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

          <button
            onClick={tabActivo === 'resumen' ? cargarDashboard : pagination.reset}
            className={styles.btnRecargar}
            disabled={pagination.loading}
            title="Recargar"
          >
            <RefreshCw size={16} />
          </button>
        </div>

        {/* Category filter */}
        <div className={styles.filtros}>
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
                    <button type="button" onClick={limpiarCategorias} className={styles.btnMultiSelectAction}>
                      <X size={12} /> Limpiar selección
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
        </div>
      </div>

      {(loading || (tabActivo === 'operaciones' && pagination.loading && pagination.currentPage === 1)) ? (
        <div className={styles.loading}>Cargando...</div>
      ) : tabActivo === 'operaciones' ? (
        <div className={styles.operacionesContainer}>
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
            <SearchInput
              value={pagination.searchTerm}
              onChange={pagination.setSearchTerm}
              placeholder="Buscar por ML ID, código o producto..."
              size="md"
              className={styles.buscador}
            />
            <div className={styles.resultadosCount}>
              {operacionesFiltradas.length} operación{operacionesFiltradas.length !== 1 ? 'es' : ''}
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
                  <th>ML ID</th>
                  <th>Código</th>
                  <th>Producto</th>
                  <th>Categoría</th>
                  <th>Cant</th>
                  <th>Precio Unit</th>
                  <th>Total</th>
                  <th>Costo Unit</th>
                  <th>Costo Total</th>
                  <th>Comisión%</th>
                  <th>Comisión $</th>
                  <th>Envío</th>
                  <th>Limpio</th>
                  <th>Markup%</th>
                  <th>Logística</th>
                </tr>
              </thead>
              <tbody>
                {operacionesFiltradas.map((op) => (
                  <tr
                    key={op.id_operacion}
                    className={op.is_cancelled ? styles.rowCancelada : ''}
                  >
                    <td>{formatearFecha(op.fecha_venta)}</td>
                    <td>
                      {op.ml_id || '-'}
                      {op.is_cancelled && <span className={styles.badgeCancelada}>Cancelada</span>}
                    </td>
                    <td>{op.codigo || '-'}</td>
                    <td className={styles.descripcion}>{op.descripcion || '-'}</td>
                    <td>{op.categoria || '-'}</td>
                    <td className={styles.centrado}>{op.cantidad}</td>
                    <td className={styles.monto}>{formatearMoneda(op.monto_unitario)}</td>
                    <td className={styles.monto}>{formatearMoneda(op.monto_total)}</td>
                    <td className={styles.monto}>{renderGanancia(op.costo_sin_iva)}</td>
                    <td className={styles.monto}>{renderGanancia(op.costo_total)}</td>
                    <td className={styles.centrado}>{renderMarkup(op.comision_porcentaje)}</td>
                    <td className={styles.monto}>{renderGanancia(op.comision_pesos)}</td>
                    <td className={styles.monto}>{formatearMoneda(op.costo_envio)}</td>
                    <td className={styles.monto}>{formatearMoneda(op.monto_limpio)}</td>
                    <td className={`${styles.centrado} ${puedeVerGanancia && parseFloat(op.markup_porcentaje) < 0 ? styles.negativo : ''}`}>
                      {renderMarkup(op.markup_porcentaje)}
                    </td>
                    <td>{getTipoLogistica(op.tipo_logistica) || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {pagination.paginationMode === 'infinite' && pagination.loading && pagination.currentPage > 1 && (
              <div className={styles.loadingMore}>Cargando más resultados...</div>
            )}
            {pagination.paginationMode === 'infinite' && !pagination.hasMore && pagination.data.length > 0 && (
              <div className={styles.endOfResults}>Todos los resultados cargados</div>
            )}
          </div>
        </div>
      ) : metricasGenerales ? (
        <>
          {/* KPIs */}
          <div className={styles.kpisContainer}>
            <div className={styles.kpiCard}>
              <div className={styles.kpiIcon}><DollarSign size={20} /></div>
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
              <div className={styles.kpiIcon}><TrendingUp size={20} /></div>
              <div className={styles.kpiContent}>
                <div className={styles.kpiLabel}>Ganancia Neta</div>
                <div className={styles.kpiValue}>
                  {puedeVerGanancia ? formatearMoneda(metricasGenerales.total_ganancia) : '***'}
                </div>
                <div className={styles.kpiStats}>
                  <span className={styles.kpiHighlight}>
                    {renderMarkup(metricasGenerales.markup_porcentaje)} markup
                  </span>
                  <span className={styles.kpiDivider}>•</span>
                  <span>Costo: {renderGanancia(metricasGenerales.total_costo)}</span>
                </div>
              </div>
            </div>

            <div className={`${styles.kpiCard} ${styles.kpiLimpio}`}>
              <div className={styles.kpiIcon}><Sparkles size={20} /></div>
              <div className={styles.kpiContent}>
                <div className={styles.kpiLabel}>Neto después de ML</div>
                <div className={styles.kpiValue}>{formatearMoneda(metricasGenerales.total_limpio)}</div>
                <div className={styles.kpiStats}>
                  <span>
                    {formatearPorcentaje((metricasGenerales.total_limpio / (metricasGenerales.total_ventas_ml || 1)) * 100)} del facturado
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Secondary metrics row */}
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
                {puedeVerGanancia
                  ? formatearMoneda(metricasGenerales.total_ganancia / (metricasGenerales.cantidad_operaciones || 1))
                  : '***'}
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
                {puedeVerGanancia ? `-${formatearMoneda(metricasGenerales.total_comisiones)}` : '***'}
              </span>
              {puedeVerGanancia && (
                <span className={styles.metricMiniPercent}>
                  {formatearPorcentaje((metricasGenerales.total_comisiones / (metricasGenerales.total_ventas_ml || 1)) * 100)}
                </span>
              )}
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

          {/* Bar chart — sales by day */}
          {ventasPorDia.length > 0 && (
            <div className={styles.chartBarCard}>
              <h3 className={styles.chartTitle}><Calendar size={16} /> Ventas por Día</h3>
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

          {/* Charts grid: Category + Logistica */}
          <div className={styles.chartsGrid}>
            {/* Top Categorías */}
            <div className={styles.chartCard}>
              <h3 className={styles.chartTitle}><Package size={16} /> Top Categorías</h3>
              <div className={styles.rankingList}>
                {(() => {
                  const maxVenta = ventasPorCategoria[0]?.total_ventas || 1;
                  return ventasPorCategoria.slice(0, 10).map((item, idx) => (
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
                          <span>Ganancia: {puedeVerGanancia ? formatearMoneda(item.total_ganancia) : '***'}</span>
                          <span className={
                            puedeVerGanancia
                              ? (parseFloat(item.markup_porcentaje) >= 15 ? styles.markupBueno : parseFloat(item.markup_porcentaje) >= 0 ? styles.markupRegular : styles.markupMalo)
                              : ''
                          }>
                            {renderMarkup(item.markup_porcentaje)} mkp
                          </span>
                        </div>
                      </div>
                    </div>
                  ));
                })()}
              </div>
            </div>

            {/* Logística */}
            <div className={styles.chartCard}>
              <h3 className={styles.chartTitle}><Truck size={16} /> Por Tipo de Envío</h3>
              <div className={styles.logisticaGrid}>
                {ventasPorLogistica.map((item, idx) => (
                  <div key={idx} className={styles.logisticaCard}>
                    <div className={styles.logisticaIcon}><Truck size={18} /></div>
                    <div className={styles.logisticaInfo}>
                      <div className={styles.logisticaNombre}>{getTipoLogistica(item.tipo_logistica)}</div>
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

          {/* Top Productos por Unidades */}
          {topProductos.length > 0 && (
            <div className={styles.timelineCard}>
              <div className={styles.chartHeader}>
                <h3 className={styles.chartTitle}><Star size={16} /> Top Productos por Unidades</h3>
                <select className={styles.topLimitSelect} value={topLimit} onChange={(e) => setTopLimit(Number(e.target.value))}>
                  <option value={10}>Top 10</option>
                  <option value={25}>Top 25</option>
                  <option value={50}>Top 50</option>
                </select>
              </div>
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Código</th>
                      <th>Descripción</th>
                      <th>Ventas</th>
                      <th>Ganancia</th>
                      <th>Markup</th>
                      <th>Unids</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topProductos.slice(0, topLimit).map((item, idx) => (
                      <tr key={idx}>
                        <td>{item.codigo}</td>
                        <td className={styles.descripcion}>{item.descripcion}</td>
                        <td className={styles.monto}>{formatearMoneda(item.total_ventas)}</td>
                        <td className={styles.monto}>{puedeVerGanancia ? formatearMoneda(item.total_ganancia) : '***'}</td>
                        <td className={styles.centrado}>{renderMarkup(item.markup_porcentaje)}</td>
                        <td className={styles.centrado}>{item.cantidad_unidades}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Top Productos por Facturación */}
          {topProductosFacturacion.length > 0 && (
            <div className={styles.timelineCard}>
              <div className={styles.chartHeader}>
                <h3 className={styles.chartTitle}><DollarSign size={16} /> Top Productos por Facturación</h3>
                <select className={styles.topLimitSelect} value={topLimit} onChange={(e) => setTopLimit(Number(e.target.value))}>
                  <option value={10}>Top 10</option>
                  <option value={25}>Top 25</option>
                  <option value={50}>Top 50</option>
                </select>
              </div>
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Código</th>
                      <th>Descripción</th>
                      <th>Ventas</th>
                      <th>Ganancia</th>
                      <th>Markup</th>
                      <th>Unids</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topProductosFacturacion.slice(0, topLimit).map((item, idx) => (
                      <tr key={idx}>
                        <td>{item.codigo}</td>
                        <td className={styles.descripcion}>{item.descripcion}</td>
                        <td className={styles.monto}>{formatearMoneda(item.total_ventas)}</td>
                        <td className={styles.monto}>{puedeVerGanancia ? formatearMoneda(item.total_ganancia) : '***'}</td>
                        <td className={styles.centrado}>{renderMarkup(item.markup_porcentaje)}</td>
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

      <Toast toast={toast} onClose={hideToast} />
    </div>
  );
}
