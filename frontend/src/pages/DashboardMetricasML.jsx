import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './DashboardMetricasML.module.css';
import TabRentabilidad from '../components/TabRentabilidad';

export default function DashboardMetricasML() {
  const [loading, setLoading] = useState(true);
  const [fechaDesde, setFechaDesde] = useState('');
  const [fechaHasta, setFechaHasta] = useState('');
  const [marcaSeleccionada, setMarcaSeleccionada] = useState('');
  const [categoriaSeleccionada, setCategoriaSeleccionada] = useState('');
  const [tabActivo, setTabActivo] = useState('resumen'); // 'resumen', 'operaciones', 'rentabilidad', 'tienda-oficial'
  
  // Derivar tiendaOficialActiva del tab activo
  const tiendaOficialActiva = tabActivo === 'tienda-oficial';

  // Datos
  const [metricasGenerales, setMetricasGenerales] = useState(null);
  const [ventasPorMarca, setVentasPorMarca] = useState([]);
  const [ventasPorCategoria, setVentasPorCategoria] = useState([]);
  const [ventasPorLogistica, setVentasPorLogistica] = useState([]);
  const [ventasPorDia, setVentasPorDia] = useState([]);
  const [topProductos, setTopProductos] = useState([]);
  const [marcasDisponibles, setMarcasDisponibles] = useState([]);
  const [categoriasDisponibles, setCategoriasDisponibles] = useState([]);

  // Datos de operaciones detalladas
  const [operaciones, setOperaciones] = useState([]);
  const [busqueda, setBusqueda] = useState('');

  // API base URL
  const API_URL = 'https://pricing.gaussonline.com.ar/api';

  useEffect(() => {
    // Configurar fechas por defecto: primer día del mes actual hasta hoy
    const hoy = new Date();
    const primerDiaMes = new Date(hoy.getFullYear(), hoy.getMonth(), 1);

    const formatearFechaISO = (fecha) => {
      return fecha.toISOString().split('T')[0];
    };

    setFechaDesde(formatearFechaISO(primerDiaMes));
    setFechaHasta(formatearFechaISO(hoy));

    // Cargar listas de marcas y categorías
    cargarMarcasYCategorias();
  }, []);

  useEffect(() => {
    if (fechaDesde && fechaHasta) {
      if (tabActivo === 'resumen' || tabActivo === 'tienda-oficial') {
        cargarDashboard();
      } else if (tabActivo === 'operaciones') {
        cargarOperaciones();
      }
    }
  }, [fechaDesde, fechaHasta, marcaSeleccionada, categoriaSeleccionada, tabActivo]);

  const cargarMarcasYCategorias = async () => {
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      const [marcasRes, categoriasRes] = await Promise.all([
        axios.get(`${API_URL}/dashboard-ml/marcas-disponibles`, { headers }),
        axios.get(`${API_URL}/dashboard-ml/categorias-disponibles`, { headers })
      ]);

      setMarcasDisponibles(marcasRes.data || []);
      setCategoriasDisponibles(categoriasRes.data || []);
    } catch (error) {
      console.error('Error cargando marcas/categorías:', error);
    }
  };

  const cargarDashboard = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      const params = {
        fecha_desde: fechaDesde,
        fecha_hasta: fechaHasta
      };

      if (marcaSeleccionada) params.marca = marcaSeleccionada;
      if (categoriaSeleccionada) params.categoria = categoriaSeleccionada;
      if (tiendaOficialActiva) params.tienda_oficial = 'true';

      // Cargar todos los datos en paralelo
      const [
        metricasRes,
        marcasRes,
        categoriasRes,
        logisticaRes,
        diasRes,
        productosRes
      ] = await Promise.all([
        axios.get(`${API_URL}/dashboard-ml/metricas-generales`, { params, headers }),
        axios.get(`${API_URL}/dashboard-ml/por-marca`, { params, headers }),
        axios.get(`${API_URL}/dashboard-ml/por-categoria`, { params, headers }),
        axios.get(`${API_URL}/dashboard-ml/por-logistica`, { params, headers }),
        axios.get(`${API_URL}/dashboard-ml/por-dia`, { params, headers }),
        axios.get(`${API_URL}/dashboard-ml/top-productos`, { params, headers })
      ]);

      setMetricasGenerales(metricasRes.data);
      setVentasPorMarca(marcasRes.data || []);
      setVentasPorCategoria(categoriasRes.data || []);
      setVentasPorLogistica(logisticaRes.data || []);
      setVentasPorDia(diasRes.data || []);
      setTopProductos(productosRes.data || []);
    } catch (error) {
      console.error('Error cargando dashboard:', error);
      alert('Error al cargar el dashboard');
    } finally {
      setLoading(false);
    }
  };

  const cargarOperaciones = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      const params = {
        from_date: fechaDesde,
        to_date: fechaHasta,
        limit: 1000
      };

      if (marcaSeleccionada) params.marca = marcaSeleccionada;
      if (tiendaOficialActiva) params.tienda_oficial = 'true';

      const response = await axios.get(`${API_URL}/ventas-ml/operaciones-con-metricas`, { params, headers });
      setOperaciones(response.data || []);
    } catch (error) {
      console.error('Error cargando operaciones:', error);
      alert('Error al cargar las operaciones');
    } finally {
      setLoading(false);
    }
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
      case '3dias':
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 2);
        break;
      case 'semana':
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 6);
        break;
      case '2semanas':
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 13);
        break;
      case 'mesActual':
        desde = new Date(hoy.getFullYear(), hoy.getMonth(), 1);
        break;
      case '30dias':
        desde = new Date(hoy);
        desde.setDate(desde.getDate() - 29);
        break;
      case '3meses':
        desde = new Date(hoy);
        desde.setMonth(desde.getMonth() - 3);
        break;
      default:
        return;
    }

    setFechaDesde(formatearFechaISO(desde));
    setFechaHasta(formatearFechaISO(hasta));
  };

  // Filtrar operaciones por búsqueda
  const operacionesFiltradas = operaciones.filter(op => {
    if (!busqueda) return true;
    const searchLower = busqueda.toLowerCase();
    return (
      (op.ml_id && op.ml_id.toLowerCase().includes(searchLower)) ||
      (op.codigo && op.codigo.toLowerCase().includes(searchLower)) ||
      (op.descripcion && op.descripcion.toLowerCase().includes(searchLower)) ||
      (op.marca && op.marca.toLowerCase().includes(searchLower))
    );
  });

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>📊 Dashboard Métricas ML</h1>

        {/* Tabs */}
        <div className={styles.tabs}>
          <button
            className={`${styles.tab} ${tabActivo === 'resumen' ? styles.tabActivo : ''}`}
            onClick={() => setTabActivo('resumen')}
          >
            📊 Resumen
          </button>
          <button
            className={`${styles.tab} ${tabActivo === 'operaciones' ? styles.tabActivo : ''}`}
            onClick={() => setTabActivo('operaciones')}
          >
            📋 Detalle de Operaciones
          </button>
          <button
            className={`${styles.tab} ${tabActivo === 'rentabilidad' ? styles.tabActivo : ''}`}
            onClick={() => setTabActivo('rentabilidad')}
          >
            💰 Rentabilidad
          </button>
          <button
            className={`${styles.tab} ${tabActivo === 'tienda-oficial' ? styles.tabActivo : ''}`}
            onClick={() => setTabActivo('tienda-oficial')}
          >
            🏪 Tienda Oficial TP-Link
          </button>
        </div>

        {/* Filtros Rápidos */}
        <div className={styles.filtrosRapidos}>
          <button onClick={() => aplicarFiltroRapido('hoy')} className={styles.btnFiltroRapido}>
            Hoy
          </button>
          <button onClick={() => aplicarFiltroRapido('ayer')} className={styles.btnFiltroRapido}>
            Ayer
          </button>
          <button onClick={() => aplicarFiltroRapido('3dias')} className={styles.btnFiltroRapido}>
            Últimos 3 días
          </button>
          <button onClick={() => aplicarFiltroRapido('semana')} className={styles.btnFiltroRapido}>
            Última semana
          </button>
          <button onClick={() => aplicarFiltroRapido('2semanas')} className={styles.btnFiltroRapido}>
            Últimas 2 semanas
          </button>
          <button onClick={() => aplicarFiltroRapido('mesActual')} className={styles.btnFiltroRapido}>
            Mes actual
          </button>
          <button onClick={() => aplicarFiltroRapido('30dias')} className={styles.btnFiltroRapido}>
            Últimos 30 días
          </button>
          <button onClick={() => aplicarFiltroRapido('3meses')} className={styles.btnFiltroRapido}>
            Últimos 3 meses
          </button>
        </div>

        <div className={styles.filtros}>
          <div className={styles.filtroFecha}>
            <label>Desde:</label>
            <input
              type="date"
              value={fechaDesde}
              onChange={(e) => setFechaDesde(e.target.value)}
              className={styles.dateInput}
            />
          </div>
          <div className={styles.filtroFecha}>
            <label>Hasta:</label>
            <input
              type="date"
              value={fechaHasta}
              onChange={(e) => setFechaHasta(e.target.value)}
              className={styles.dateInput}
            />
          </div>

          {tabActivo !== 'rentabilidad' && (
            <>
              <div className={styles.filtroSelect}>
                <label>Marca:</label>
                <select
                  value={marcaSeleccionada}
                  onChange={(e) => setMarcaSeleccionada(e.target.value)}
                  className={styles.select}
                >
                  <option value="">Todas</option>
                  {marcasDisponibles.map(marca => (
                    <option key={marca} value={marca}>{marca}</option>
                  ))}
                </select>
              </div>

              <div className={styles.filtroSelect}>
                <label>Categoría:</label>
                <select
                  value={categoriaSeleccionada}
                  onChange={(e) => setCategoriaSeleccionada(e.target.value)}
                  className={styles.select}
                >
                  <option value="">Todas</option>
                  {categoriasDisponibles.map(cat => (
                    <option key={cat} value={cat}>{cat}</option>
                  ))}
                </select>
              </div>

              <button onClick={cargarDashboard} className={styles.btnRecargar}>
                🔄 Recargar
              </button>
            </>
          )}
        </div>
      </div>

      {loading ? (
        <div className={styles.loading}>Cargando...</div>
      ) : tabActivo === 'operaciones' ? (
        /* Tab de Detalle de Operaciones */
        <div className={styles.operacionesContainer}>
          <div className={styles.buscadorContainer}>
            <input
              type="text"
              placeholder="🔍 Buscar por ML ID, código, producto o marca..."
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
          </div>
        </div>
      ) : tabActivo === 'rentabilidad' ? (
        /* Tab de Rentabilidad */
        <TabRentabilidad fechaDesde={fechaDesde} fechaHasta={fechaHasta} />
      ) : metricasGenerales ? (
        /* Tab de Resumen (incluye tienda-oficial con filtro) */
        <>
          {/* Banner informativo si está en tienda oficial */}
          {tiendaOficialActiva && (
            <div className={styles.bannerTiendaOficial}>
              🏪 Mostrando solo operaciones de la <strong>Tienda Oficial TP-Link</strong>
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
                  <span>{formatearPorcentaje((metricasGenerales.total_limpio / metricasGenerales.total_ventas_ml) * 100)} del facturado</span>
                </div>
              </div>
            </div>
          </div>

          {/* Métricas secundarias en fila */}
          <div className={styles.metricsRow}>
            <div className={styles.metricMini}>
              <span className={styles.metricMiniLabel}>Ticket Promedio</span>
              <span className={styles.metricMiniValue}>
                {formatearMoneda(metricasGenerales.total_ventas_ml / metricasGenerales.cantidad_operaciones)}
              </span>
            </div>
            <div className={styles.metricMini}>
              <span className={styles.metricMiniLabel}>Ganancia/Venta</span>
              <span className={styles.metricMiniValue}>
                {formatearMoneda(metricasGenerales.total_ganancia / metricasGenerales.cantidad_operaciones)}
              </span>
            </div>
            <div className={styles.metricMini}>
              <span className={styles.metricMiniLabel}>Unids/Venta</span>
              <span className={styles.metricMiniValue}>
                {(metricasGenerales.cantidad_unidades / metricasGenerales.cantidad_operaciones).toFixed(1)}
              </span>
            </div>
            <div className={styles.metricMini}>
              <span className={styles.metricMiniLabel}>Comisiones ML</span>
              <span className={styles.metricMiniValue} style={{ color: '#ef4444' }}>
                -{formatearMoneda(metricasGenerales.total_comisiones)}
              </span>
              <span className={styles.metricMiniPercent}>
                {formatearPorcentaje((metricasGenerales.total_comisiones / metricasGenerales.total_ventas_ml) * 100)}
              </span>
            </div>
            <div className={styles.metricMini}>
              <span className={styles.metricMiniLabel}>Envíos</span>
              <span className={styles.metricMiniValue} style={{ color: '#ef4444' }}>
                -{formatearMoneda(metricasGenerales.total_envios)}
              </span>
              <span className={styles.metricMiniPercent}>
                {formatearPorcentaje((metricasGenerales.total_envios / metricasGenerales.total_ventas_ml) * 100)}
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

          {/* Ventas por Día (Timeline) - REMOVIDO */}
          {false && ventasPorDia.length > 0 && (
            <div className={styles.timelineCard}>
              <h3 className={styles.chartTitle}>📅 Evolución Diaria</h3>
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Fecha</th>
                      <th>Ventas</th>
                      <th>Limpio</th>
                      <th>Ganancia</th>
                      <th>Ops</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ventasPorDia.map((item, idx) => (
                      <tr key={idx}>
                        <td>{formatearFecha(item.fecha)}</td>
                        <td className={styles.monto}>{formatearMoneda(item.total_ventas)}</td>
                        <td className={styles.monto}>{formatearMoneda(item.total_limpio)}</td>
                        <td className={styles.monto}>{formatearMoneda(item.total_ganancia)}</td>
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
