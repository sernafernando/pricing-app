import { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import styles from './DashboardMetricasML.module.css'; // Reutilizamos los estilos
import TabRentabilidadTiendaNube from '../components/TabRentabilidadTiendaNube';
import { useAuthStore } from '../store/authStore';

export default function DashboardTiendaNube() {
  const user = useAuthStore((state) => state.user);
  const esAdmin = user?.rol === 'ADMIN' || user?.rol === 'SUPERADMIN';

  const [loading, setLoading] = useState(true);
  const [fechaDesde, setFechaDesde] = useState('');
  const [fechaHasta, setFechaHasta] = useState('');
  const [sucursalSeleccionada, setSucursalSeleccionada] = useState('');
  const [vendedorSeleccionado, setVendedorSeleccionado] = useState('');
  const [tabActivo, setTabActivo] = useState('resumen'); // 'resumen', 'operaciones', 'rentabilidad'

  // Datos
  const [stats, setStats] = useState(null);
  const [ventasPorMarca, setVentasPorMarca] = useState([]);
  const [topProductos, setTopProductos] = useState([]);
  const [sucursalesDisponibles, setSucursalesDisponibles] = useState([]);
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
  }, [fechaDesde, fechaHasta, sucursalSeleccionada, vendedorSeleccionado, tabActivo, soloSinCosto]);

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
        axios.get(`${API_URL}/ventas-tienda-nube/stats`, { params, headers }),
        axios.get(`${API_URL}/ventas-tienda-nube/por-marca`, { params: { ...params, limit: 15 }, headers }),
        axios.get(`${API_URL}/ventas-tienda-nube/top-productos`, { params: { ...params, limit: 20 }, headers })
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

      // Cargar operaciones, métodos de pago, overrides y jerarquía en paralelo
      const [operacionesRes, metodosPagoRes, constantesRes, overridesRes, jerarquiaRes] = await Promise.all([
        axios.get(`${API_URL}/ventas-tienda-nube`, { params, headers }),
        axios.get(`${API_URL}/ventas-tienda-nube/metodos-pago`, { params: { from_date: fechaDesde, to_date: fechaHasta }, headers }),
        axios.get(`${API_URL}/pricing-constants/actual`, { headers }),
        axios.get(`${API_URL}/ventas-tienda-nube/overrides`, { params: { from_date: fechaDesde, to_date: fechaHasta }, headers }),
        axios.get(`${API_URL}/ventas-tienda-nube/jerarquia-productos`, { headers }).catch(() => ({ data: {} }))
      ]);

      setOperaciones(operacionesRes.data || []);
      setMetodosPago(metodosPagoRes.data || {});
      setOverrides(overridesRes.data || {});
      setJerarquiaProductos(jerarquiaRes.data || {});

      if (constantesRes.data) {
        setComisionEfectivo(constantesRes.data.comision_tienda_nube || 1.0);
        setComisionTarjeta(constantesRes.data.comision_tienda_nube_tarjeta || 3.0);
      }
    } catch (error) {
      console.error('Error cargando operaciones:', error);
      alert('Error al cargar las operaciones');
    } finally {
      setLoading(false);
    }
  };

  const cambiarMetodoPago = async (itTransaction, nuevoMetodo) => {
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      await axios.post(`${API_URL}/ventas-tienda-nube/metodo-pago`, {
        it_transaction: itTransaction,
        metodo_pago: nuevoMetodo
      }, { headers });

      // Actualizar estado local
      setMetodosPago(prev => ({ ...prev, [itTransaction]: nuevoMetodo }));
    } catch (error) {
      console.error('Error guardando método de pago:', error);
      alert('Error al guardar el método de pago');
    }
  };

  // Ref para debounce de overrides
  const debounceTimers = useRef({});

  const guardarOverrideAPI = useCallback(async (itTransaction, campo, valor) => {
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      await axios.post(`${API_URL}/ventas-tienda-nube/override`, {
        it_transaction: itTransaction,
        [campo]: valor
      }, { headers });
    } catch (error) {
      console.error('Error guardando override:', error);
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

              <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={soloSinCosto}
                  onChange={(e) => setSoloSinCosto(e.target.checked)}
                />
                Solo sin costo
              </label>
            </>
          )}

          {tabActivo !== 'rentabilidad' && (
            <button onClick={tabActivo === 'resumen' ? cargarDashboard : cargarOperaciones} className={styles.btnRecargar}>
              🔄 Recargar
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

      {tabActivo === 'rentabilidad' ? (
        <TabRentabilidadTiendaNube fechaDesde={fechaDesde} fechaHasta={fechaHasta} />
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

                  return (
                    <tr key={op.id_operacion || idx} className={sinCosto ? styles.rowSinCosto : ''}>
                      <td>{formatearFecha(op.fecha)}</td>
                      <td>{op.sucursal || '-'}</td>
                      <td className={styles.descripcion}>
                        <input
                          type="text"
                          value={clienteEfectivo}
                          onChange={(e) => guardarOverride(op.id_operacion, 'cliente', e.target.value)}
                          className={styles.inputEditable}
                          style={{
                            backgroundColor: tieneOverride?.cliente ? '#fef3c7' : 'transparent'
                          }}
                          placeholder="Cliente"
                        />
                      </td>
                      <td>{op.vendedor || '-'}</td>
                      <td>
                        <input
                          type="text"
                          value={codigoEfectivo}
                          onChange={(e) => guardarOverride(op.id_operacion, 'codigo', e.target.value)}
                          className={styles.inputEditable}
                          style={{
                            backgroundColor: tieneOverride?.codigo ? '#fef3c7' : 'transparent',
                            width: '80px'
                          }}
                          placeholder="Código"
                        />
                      </td>
                      <td className={styles.descripcion}>
                        <input
                          type="text"
                          value={descripcionEfectiva}
                          onChange={(e) => guardarOverride(op.id_operacion, 'descripcion', e.target.value)}
                          className={styles.inputEditable}
                          style={{
                            backgroundColor: tieneOverride?.descripcion ? '#fef3c7' : 'transparent'
                          }}
                          placeholder="Descripción"
                        />
                      </td>
                      <td>
                        <select
                          value={marcaEfectiva}
                          onChange={(e) => {
                            guardarOverride(op.id_operacion, 'marca', e.target.value);
                            // Limpiar categoría y subcategoría si cambia la marca
                            if (e.target.value !== marcaEfectiva) {
                              guardarOverride(op.id_operacion, 'categoria', '');
                              guardarOverride(op.id_operacion, 'subcategoria', '');
                            }
                          }}
                          className={styles.selectEditable}
                          style={{
                            backgroundColor: tieneOverride?.marca ? '#fef3c7' : 'transparent'
                          }}
                        >
                          <option value="">Sin marca</option>
                          {getMarcasDisponibles().map(m => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                          {marcaEfectiva && !getMarcasDisponibles().includes(marcaEfectiva) && (
                            <option value={marcaEfectiva}>{marcaEfectiva}</option>
                          )}
                        </select>
                      </td>
                      <td>
                        <select
                          value={categoriaEfectiva}
                          onChange={(e) => {
                            guardarOverride(op.id_operacion, 'categoria', e.target.value);
                            // Limpiar subcategoría si cambia la categoría
                            if (e.target.value !== categoriaEfectiva) {
                              guardarOverride(op.id_operacion, 'subcategoria', '');
                            }
                          }}
                          className={styles.selectEditable}
                          style={{
                            backgroundColor: tieneOverride?.categoria ? '#fef3c7' : 'transparent'
                          }}
                          disabled={!marcaEfectiva}
                        >
                          <option value="">{marcaEfectiva ? 'Sin categoría' : 'Seleccione marca primero'}</option>
                          {getCategoriasParaMarca(marcaEfectiva).map(c => (
                            <option key={c} value={c}>{c}</option>
                          ))}
                          {categoriaEfectiva && !getCategoriasParaMarca(marcaEfectiva).includes(categoriaEfectiva) && (
                            <option value={categoriaEfectiva}>{categoriaEfectiva}</option>
                          )}
                        </select>
                      </td>
                      <td>
                        <select
                          value={subcategoriaEfectiva}
                          onChange={(e) => guardarOverride(op.id_operacion, 'subcategoria', e.target.value)}
                          className={styles.selectEditable}
                          style={{
                            backgroundColor: tieneOverride?.subcategoria ? '#fef3c7' : 'transparent'
                          }}
                          disabled={!categoriaEfectiva}
                        >
                          <option value="">{categoriaEfectiva ? 'Sin subcategoría' : 'Seleccione categoría primero'}</option>
                          {getSubcategoriasParaCategoria(marcaEfectiva, categoriaEfectiva).map(s => (
                            <option key={s} value={s}>{s}</option>
                          ))}
                          {subcategoriaEfectiva && !getSubcategoriasParaCategoria(marcaEfectiva, categoriaEfectiva).includes(subcategoriaEfectiva) && (
                            <option value={subcategoriaEfectiva}>{subcategoriaEfectiva}</option>
                          )}
                        </select>
                      </td>
                      <td className={styles.centrado}>
                        <input
                          type="number"
                          value={getValorEfectivo(op, 'cantidad') || op.cantidad || ''}
                          onChange={(e) => guardarOverride(op.id_operacion, 'cantidad', e.target.value ? parseFloat(e.target.value) : null)}
                          className={styles.inputEditable}
                          style={{
                            backgroundColor: tieneOverride?.cantidad ? '#fef3c7' : 'transparent',
                            width: '60px',
                            textAlign: 'center'
                          }}
                          step="0.01"
                        />
                      </td>
                      <td className={styles.monto}>
                        <input
                          type="number"
                          value={getValorEfectivo(op, 'precio_unitario') || op.precio_unitario_sin_iva || ''}
                          onChange={(e) => guardarOverride(op.id_operacion, 'precio_unitario', e.target.value ? parseFloat(e.target.value) : null)}
                          className={styles.inputEditable}
                          style={{
                            backgroundColor: tieneOverride?.precio_unitario ? '#fef3c7' : 'transparent',
                            width: '90px',
                            textAlign: 'right'
                          }}
                          step="0.01"
                        />
                      </td>
                      <td className={styles.centrado}>{op.iva_porcentaje}%</td>
                      <td className={styles.monto}>{formatearMoneda(op.precio_final_sin_iva)}</td>
                      <td>
                        <select
                          value={metodoPagoActual}
                          onChange={(e) => cambiarMetodoPago(op.id_operacion, e.target.value)}
                          className={styles.selectEditable}
                          style={{
                            backgroundColor: metodoPagoActual === 'tarjeta' ? '#fef3c7' : '#d1fae5'
                          }}
                        >
                          <option value="efectivo">Efectivo ({comisionEfectivo}%)</option>
                          <option value="tarjeta">Tarjeta ({comisionTarjeta}%)</option>
                        </select>
                      </td>
                      <td className={styles.monto} style={{ color: '#f59e0b' }}>
                        {formatearMoneda(comisionCalculada)} ({comisionAplicada}%)
                      </td>
                      <td className={styles.monto}>
                        <input
                          type="number"
                          value={getValorEfectivo(op, 'costo_unitario') || op.costo_unitario || ''}
                          onChange={(e) => guardarOverride(op.id_operacion, 'costo_unitario', e.target.value ? parseFloat(e.target.value) : null)}
                          className={styles.inputEditable}
                          style={{
                            backgroundColor: tieneOverride?.costo_unitario ? '#fef3c7' : (sinCosto ? '#fee2e2' : 'transparent'),
                            width: '90px',
                            textAlign: 'right'
                          }}
                          step="0.01"
                          placeholder={sinCosto ? 'Sin costo' : ''}
                        />
                      </td>
                      <td className={styles.monto} style={{ color: gananciaCalculada >= 0 ? '#22c55e' : '#ef4444' }}>
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
