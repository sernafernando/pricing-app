import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './DashboardMetricasML.module.css'; // Reutilizamos los estilos
import TabRentabilidadFuera from '../components/TabRentabilidadFuera';

export default function DashboardVentasFuera() {
  const [loading, setLoading] = useState(true);
  const [fechaDesde, setFechaDesde] = useState('');
  const [fechaHasta, setFechaHasta] = useState('');
  const [sucursalSeleccionada, setSucursalSeleccionada] = useState('');
  const [vendedorSeleccionado, setVendedorSeleccionado] = useState('');
  const [tabActivo, setTabActivo] = useState('resumen'); // 'resumen', 'operaciones' o 'rentabilidad'

  // Datos
  const [stats, setStats] = useState(null);
  const [ventasPorMarca, setVentasPorMarca] = useState([]);
  const [topProductos, setTopProductos] = useState([]);
  const [sucursalesDisponibles, setSucursalesDisponibles] = useState([]);
  const [vendedoresDisponibles, setVendedoresDisponibles] = useState([]);

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
  }, []);

  useEffect(() => {
    if (fechaDesde && fechaHasta) {
      if (tabActivo === 'resumen') {
        cargarDashboard();
      } else if (tabActivo === 'operaciones') {
        cargarOperaciones();
      }
    }
  }, [fechaDesde, fechaHasta, sucursalSeleccionada, vendedorSeleccionado, tabActivo]);

  const cargarDashboard = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      const params = {
        from_date: fechaDesde,
        to_date: fechaHasta
      };

      // Cargar todos los datos en paralelo
      const [statsRes, marcasRes, productosRes] = await Promise.all([
        axios.get(`${API_URL}/ventas-fuera-ml/stats`, { params, headers }),
        axios.get(`${API_URL}/ventas-fuera-ml/por-marca`, { params: { ...params, limit: 15 }, headers }),
        axios.get(`${API_URL}/ventas-fuera-ml/top-productos`, { params: { ...params, limit: 20 }, headers })
      ]);

      setStats(statsRes.data);
      setVentasPorMarca(marcasRes.data || []);
      setTopProductos(productosRes.data || []);

      // Extraer sucursales y vendedores disponibles de stats
      if (statsRes.data) {
        setSucursalesDisponibles(Object.keys(statsRes.data.por_sucursal || {}));
        setVendedoresDisponibles(Object.keys(statsRes.data.por_vendedor || {}));
      }
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

      if (sucursalSeleccionada) params.sucursal = sucursalSeleccionada;
      if (vendedorSeleccionado) params.vendedor = vendedorSeleccionado;

      const response = await axios.get(`${API_URL}/ventas-fuera-ml`, { params, headers });
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
      (op.codigo_item && op.codigo_item.toLowerCase().includes(searchLower)) ||
      (op.descripcion && op.descripcion.toLowerCase().includes(searchLower)) ||
      (op.marca && op.marca.toLowerCase().includes(searchLower)) ||
      (op.cliente && op.cliente.toLowerCase().includes(searchLower)) ||
      (op.vendedor && op.vendedor.toLowerCase().includes(searchLower))
    );
  });

  // Calcular ganancia para el resumen
  const calcularGanancia = () => {
    if (!stats) return 0;
    return stats.monto_total_sin_iva - stats.costo_total;
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>🏪 Dashboard Ventas por Fuera de ML</h1>

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
            💹 Rentabilidad
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

          {tabActivo === 'operaciones' && (
            <>
              <div className={styles.filtroSelect}>
                <label>Sucursal:</label>
                <select
                  value={sucursalSeleccionada}
                  onChange={(e) => setSucursalSeleccionada(e.target.value)}
                  className={styles.select}
                >
                  <option value="">Todas</option>
                  {sucursalesDisponibles.map(suc => (
                    <option key={suc} value={suc}>{suc}</option>
                  ))}
                </select>
              </div>

              <div className={styles.filtroSelect}>
                <label>Vendedor:</label>
                <select
                  value={vendedorSeleccionado}
                  onChange={(e) => setVendedorSeleccionado(e.target.value)}
                  className={styles.select}
                >
                  <option value="">Todos</option>
                  {vendedoresDisponibles.map(vend => (
                    <option key={vend} value={vend}>{vend}</option>
                  ))}
                </select>
              </div>
            </>
          )}

          {tabActivo !== 'rentabilidad' && (
            <button onClick={tabActivo === 'resumen' ? cargarDashboard : cargarOperaciones} className={styles.btnRecargar}>
              🔄 Recargar
            </button>
          )}
        </div>
      </div>

      {tabActivo === 'rentabilidad' ? (
        <TabRentabilidadFuera fechaDesde={fechaDesde} fechaHasta={fechaHasta} />
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
                  <th>Código</th>
                  <th>Producto</th>
                  <th>Marca</th>
                  <th>Cant</th>
                  <th>Precio Unit</th>
                  <th>IVA%</th>
                  <th>Total s/IVA</th>
                  <th>Total c/IVA</th>
                  <th>Costo</th>
                  <th>Markup%</th>
                  <th>Comprobante</th>
                </tr>
              </thead>
              <tbody>
                {operacionesFiltradas.map((op, idx) => (
                  <tr key={idx}>
                    <td>{formatearFecha(op.fecha)}</td>
                    <td>{op.sucursal || '-'}</td>
                    <td className={styles.descripcion}>{op.cliente || '-'}</td>
                    <td>{op.vendedor || '-'}</td>
                    <td>{op.codigo_item || '-'}</td>
                    <td className={styles.descripcion}>{op.descripcion || '-'}</td>
                    <td>{op.marca || '-'}</td>
                    <td className={styles.centrado}>{op.cantidad}</td>
                    <td className={styles.monto}>{formatearMoneda(op.precio_unitario_sin_iva)}</td>
                    <td className={styles.centrado}>{op.iva_porcentaje}%</td>
                    <td className={styles.monto}>{formatearMoneda(op.precio_final_sin_iva)}</td>
                    <td className={styles.monto}>{formatearMoneda(op.precio_final_con_iva)}</td>
                    <td className={styles.monto}>{formatearMoneda(op.costo_pesos_sin_iva)}</td>
                    <td className={`${styles.centrado} ${op.markup !== null && parseFloat(op.markup) < 0 ? styles.negativo : ''}`}>
                      {formatearPorcentaje(op.markup)}
                    </td>
                    <td>{op.tipo_comprobante} {op.punto_de_venta}-{op.numero_comprobante}</td>
                  </tr>
                ))}
              </tbody>
            </table>
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
              <span className={styles.metricMiniValue} style={{ color: calcularGanancia() > 0 ? '#10b981' : '#ef4444' }}>
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
                  return ventasPorMarca.slice(0, 10).map((item, idx) => (
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
                          <span>Costo: {formatearMoneda(item.costo_total)}</span>
                          <span className={item.markup_promedio !== null && parseFloat(item.markup_promedio) >= 0.15 ? styles.markupBueno : item.markup_promedio !== null && parseFloat(item.markup_promedio) >= 0 ? styles.markupRegular : styles.markupMalo}>
                            {item.markup_promedio !== null ? `${(parseFloat(item.markup_promedio) * 100).toFixed(1)}% mkp` : '-'}
                          </span>
                          <span>{item.total_ventas} ops</span>
                        </div>
                      </div>
                    </div>
                  ));
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
