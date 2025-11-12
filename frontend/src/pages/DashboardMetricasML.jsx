import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './DashboardMetricasML.module.css';

export default function DashboardMetricasML() {
  const [loading, setLoading] = useState(true);
  const [fechaDesde, setFechaDesde] = useState('');
  const [fechaHasta, setFechaHasta] = useState('');
  const [marcaSeleccionada, setMarcaSeleccionada] = useState('');
  const [categoriaSeleccionada, setCategoriaSeleccionada] = useState('');

  // Datos
  const [metricasGenerales, setMetricasGenerales] = useState(null);
  const [ventasPorMarca, setVentasPorMarca] = useState([]);
  const [ventasPorCategoria, setVentasPorCategoria] = useState([]);
  const [ventasPorLogistica, setVentasPorLogistica] = useState([]);
  const [ventasPorDia, setVentasPorDia] = useState([]);
  const [topProductos, setTopProductos] = useState([]);
  const [marcasDisponibles, setMarcasDisponibles] = useState([]);
  const [categoriasDisponibles, setCategoriasDisponibles] = useState([]);

  // API base URL
  const API_URL = 'https://pricing.gaussonline.com.ar/api';

  useEffect(() => {
    // Configurar fechas por defecto: últimos 30 días
    const hoy = new Date();
    const hace30Dias = new Date(hoy);
    hace30Dias.setDate(hace30Dias.getDate() - 30);

    const formatearFecha = (fecha) => {
      return fecha.toISOString().split('T')[0];
    };

    setFechaDesde(formatearFecha(hace30Dias));
    setFechaHasta(formatearFecha(hoy));

    // Cargar listas de marcas y categorías
    cargarMarcasYCategorias();
  }, []);

  useEffect(() => {
    if (fechaDesde && fechaHasta) {
      cargarDashboard();
    }
  }, [fechaDesde, fechaHasta, marcaSeleccionada, categoriaSeleccionada]);

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
      'cross_docking': '📦 Full',
      'self_service': '🏢 Flex',
      'drop_off': '📮 Drop Off',
      'xd_drop_off': '📮 XD Drop Off'
    };
    return tipos[tipo] || tipo;
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>📊 Dashboard Métricas ML</h1>

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
        </div>
      </div>

      {loading ? (
        <div className={styles.loading}>Cargando métricas...</div>
      ) : metricasGenerales ? (
        <>
          {/* Métricas Generales */}
          <div className={styles.metricasGrid}>
            <div className={styles.metricaCard}>
              <div className={styles.metricaLabel}>💰 Total Ventas ML</div>
              <div className={styles.metricaValue}>
                {formatearMoneda(metricasGenerales.total_ventas_ml)}
              </div>
              <div className={styles.metricaSubtext}>
                {metricasGenerales.cantidad_operaciones} operaciones
              </div>
            </div>

            <div className={styles.metricaCard}>
              <div className={styles.metricaLabel}>✨ Total Limpio</div>
              <div className={styles.metricaValue}>
                {formatearMoneda(metricasGenerales.total_limpio)}
              </div>
              <div className={styles.metricaSubtext}>
                Después de comisiones y envío
              </div>
            </div>

            <div className={styles.metricaCard}>
              <div className={styles.metricaLabel}>📈 Total Ganancia</div>
              <div className={styles.metricaValue}>
                {formatearMoneda(metricasGenerales.total_ganancia)}
              </div>
              <div className={styles.metricaSubtext}>
                {metricasGenerales.cantidad_unidades} unidades vendidas
              </div>
            </div>

            <div className={styles.metricaCard}>
              <div className={styles.metricaLabel}>📊 Markup %</div>
              <div className={styles.metricaValue}>
                {formatearPorcentaje(metricasGenerales.markup_porcentaje)}
              </div>
              <div className={styles.metricaSubtext}>
                Costo Total: {formatearMoneda(metricasGenerales.total_costo)}
              </div>
            </div>

            <div className={styles.metricaCard}>
              <div className={styles.metricaLabel}>💳 Comisiones ML</div>
              <div className={styles.metricaValue}>
                {formatearMoneda(metricasGenerales.total_comisiones)}
              </div>
              <div className={styles.metricaSubtext}>
                {formatearPorcentaje((metricasGenerales.total_comisiones / metricasGenerales.total_ventas_ml) * 100)} del total
              </div>
            </div>

            <div className={styles.metricaCard}>
              <div className={styles.metricaLabel}>🚚 Costos Envío</div>
              <div className={styles.metricaValue}>
                {formatearMoneda(metricasGenerales.total_envios)}
              </div>
              <div className={styles.metricaSubtext}>
                {formatearPorcentaje((metricasGenerales.total_envios / metricasGenerales.total_ventas_ml) * 100)} del total
              </div>
            </div>
          </div>

          {/* Gráficos y Tablas */}
          <div className={styles.chartsGrid}>
            {/* Ventas por Marca */}
            <div className={styles.chartCard}>
              <h3 className={styles.chartTitle}>🏷️ Ventas por Marca</h3>
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Marca</th>
                      <th>Ventas</th>
                      <th>Ganancia</th>
                      <th>Markup</th>
                      <th>Ops</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ventasPorMarca.slice(0, 10).map((item, idx) => (
                      <tr key={idx}>
                        <td>{item.marca}</td>
                        <td className={styles.monto}>{formatearMoneda(item.total_ventas)}</td>
                        <td className={styles.monto}>{formatearMoneda(item.total_ganancia)}</td>
                        <td className={styles.centrado}>{formatearPorcentaje(item.markup_porcentaje)}</td>
                        <td className={styles.centrado}>{item.cantidad_operaciones}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Ventas por Categoría */}
            <div className={styles.chartCard}>
              <h3 className={styles.chartTitle}>📦 Ventas por Categoría</h3>
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Categoría</th>
                      <th>Ventas</th>
                      <th>Ganancia</th>
                      <th>Markup</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ventasPorCategoria.slice(0, 10).map((item, idx) => (
                      <tr key={idx}>
                        <td>{item.categoria}</td>
                        <td className={styles.monto}>{formatearMoneda(item.total_ventas)}</td>
                        <td className={styles.monto}>{formatearMoneda(item.total_ganancia)}</td>
                        <td className={styles.centrado}>{formatearPorcentaje(item.markup_porcentaje)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Ventas por Logística */}
            <div className={styles.chartCard}>
              <h3 className={styles.chartTitle}>🚚 Ventas por Tipo de Envío</h3>
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Tipo</th>
                      <th>Ventas</th>
                      <th>Costo Envío</th>
                      <th>Ops</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ventasPorLogistica.map((item, idx) => (
                      <tr key={idx}>
                        <td>{getTipoLogistica(item.tipo_logistica)}</td>
                        <td className={styles.monto}>{formatearMoneda(item.total_ventas)}</td>
                        <td className={styles.monto}>{formatearMoneda(item.total_envios)}</td>
                        <td className={styles.centrado}>{item.cantidad_operaciones}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Top Productos */}
            <div className={styles.chartCard}>
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
          </div>

          {/* Ventas por Día (Timeline) */}
          {ventasPorDia.length > 0 && (
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
