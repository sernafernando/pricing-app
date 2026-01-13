import { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import styles from './DashboardMetricasML.module.css'; // Reutilizamos los estilos
import TabRentabilidadFuera from '../components/TabRentabilidadFuera';
import TabAdminVentasFuera from '../components/TabAdminVentasFuera';
import ModalEditarCosto from '../components/ModalEditarCosto';
import { useAuthStore } from '../store/authStore';
import { useQueryFilters } from '../hooks/useQueryFilters';

// API base URL
const API_URL = 'https://pricing.gaussonline.com.ar/api';

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
  
  // Usar query params para tab, fechas y filtros
  const { getFilter, updateFilters } = useQueryFilters({
    tab: 'resumen',
    fecha_desde: getDefaultFechaDesde(),
    fecha_hasta: getDefaultFechaHasta(),
    sucursal: '',
    vendedor: ''
  });

  const tabActivo = getFilter('tab');
  const fechaDesde = getFilter('fecha_desde');
  const fechaHasta = getFilter('fecha_hasta');
  const sucursalSeleccionada = getFilter('sucursal');
  const vendedorSeleccionado = getFilter('vendedor');

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
  const [soloModificadas, setSoloModificadas] = useState(false);

  // Modal editar costo
  const [modalCostoAbierto, setModalCostoAbierto] = useState(false);
  const [operacionEditando, setOperacionEditando] = useState(null);

  // Overrides de marca/categoría/subcategoría
  const [overrides, setOverrides] = useState({});
  const [jerarquiaProductos, setJerarquiaProductos] = useState({}); // { marca: { categoria: [subcategorias] } }

  const cargarDashboard = useCallback(async () => {
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
      alert('Error al cargar el dashboard');
    } finally {
      setLoading(false);
    }
  }, [fechaDesde, fechaHasta]);

  const cargarOperaciones = useCallback(async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      const params = {
        from_date: fechaDesde,
        to_date: fechaHasta,
        limit: 1000,
        solo_sin_costo: soloSinCosto
      };

      if (sucursalSeleccionada) params.sucursal = sucursalSeleccionada;
      if (vendedorSeleccionado) params.vendedor = vendedorSeleccionado;

      // Cargar operaciones, overrides y jerarquía en paralelo
      const [operacionesRes, overridesRes, jerarquiaRes] = await Promise.all([
        axios.get(`${API_URL}/ventas-fuera-ml/operaciones`, { params, headers }),
        axios.get(`${API_URL}/ventas-fuera-ml/overrides`, { params: { from_date: fechaDesde, to_date: fechaHasta }, headers }),
        axios.get(`${API_URL}/ventas-fuera-ml/jerarquia-productos`, { headers }).catch(() => ({ data: {} }))
      ]);

      setOperaciones(operacionesRes.data || []);
      setOverrides(overridesRes.data || {});
      setJerarquiaProductos(jerarquiaRes.data || {});
    } catch (error) {
      alert('Error al cargar las operaciones');
    } finally {
      setLoading(false);
    }
  }, [fechaDesde, fechaHasta, soloSinCosto, sucursalSeleccionada, vendedorSeleccionado]);

  useEffect(() => {
    if (fechaDesde && fechaHasta) {
      if (tabActivo === 'resumen') {
        cargarDashboard();
      } else if (tabActivo === 'operaciones') {
        cargarOperaciones();
      }
    }
  }, [fechaDesde, fechaHasta, tabActivo, cargarDashboard, cargarOperaciones]);

  const abrirModalCosto = (operacion) => {
    setOperacionEditando(operacion);
    setModalCostoAbierto(true);
  };

  const cerrarModalCosto = () => {
    setModalCostoAbierto(false);
    setOperacionEditando(null);
  };

  const onCostoGuardado = () => {
    // Recargar operaciones para ver el cambio
    cargarOperaciones();
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
    } catch (error) {
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

    updateFilters({
      fecha_desde: formatearFechaISO(desde),
      fecha_hasta: formatearFechaISO(hasta)
    });
  };

  // Verificar si una operación tiene override
  const tieneOverride = (opId) => {
    const override = overrides[opId];
    if (!override) return false;
    return Object.values(override).some(v => v !== null && v !== undefined && v !== '');
  };

  // Filtrar operaciones por búsqueda y modificadas
  const operacionesFiltradas = operaciones.filter(op => {
    // Filtro de modificadas
    if (soloModificadas && !tieneOverride(op.id_operacion)) return false;

    // Filtro de búsqueda
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
              onChange={(e) => updateFilters({ fecha_desde: e.target.value })}
              className={styles.dateInput}
            />
          </div>
          <div className={styles.filtroFecha}>
            <label>Hasta:</label>
            <input
              type="date"
              value={fechaHasta}
              onChange={(e) => updateFilters({ fecha_hasta: e.target.value })}
              className={styles.dateInput}
            />
          </div>

          {tabActivo === 'operaciones' && (
            <>
              <div className={styles.filtroSelect}>
                <label>Sucursal:</label>
                <select
                  value={sucursalSeleccionada}
                  onChange={(e) => updateFilters({ sucursal: e.target.value })}
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
                  onChange={(e) => updateFilters({ vendedor: e.target.value })}
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
              {tabActivo === 'operaciones' && (
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={soloModificadas}
                    onChange={(e) => setSoloModificadas(e.target.checked)}
                  />
                  Solo modificadas
                </label>
              )}
            </>
          )}

          {tabActivo !== 'rentabilidad' && tabActivo !== 'admin' && (
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

      {tabActivo === 'admin' ? (
        <TabAdminVentasFuera />
      ) : tabActivo === 'rentabilidad' ? (
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
                  const asterisco = (campo) => override?.[campo] ? <span style={{ color: '#f59e0b', marginLeft: '2px' }}>*</span> : null;

                  return (
                    <tr
                      key={op.metrica_id || idx}
                      className={sinCosto ? styles.rowSinCosto : ''}
                      style={filaModificada ? { backgroundColor: 'rgba(59, 130, 246, 0.08)' } : {}}
                    >
                      <td>{formatearFecha(op.fecha)}</td>
                      <td>{op.sucursal || '-'}</td>
                      <td>
                        <span
                          style={{
                            cursor: 'pointer',
                            padding: '2px 4px',
                            borderRadius: '3px',
                            backgroundColor: override?.cliente ? 'rgba(245, 158, 11, 0.15)' : 'transparent'
                          }}
                          onClick={() => {
                            const nuevoValor = prompt('Cliente:', clienteEfectivo);
                            if (nuevoValor !== null) guardarOverride(op.id_operacion, 'cliente', nuevoValor);
                          }}
                          title="Click para editar"
                        >
                          {clienteEfectivo || '-'}{asterisco('cliente')}
                        </span>
                      </td>
                      <td>{op.vendedor || '-'}</td>
                      <td>
                        <span
                          style={{
                            cursor: 'pointer',
                            padding: '2px 4px',
                            borderRadius: '3px',
                            backgroundColor: override?.codigo ? 'rgba(245, 158, 11, 0.15)' : 'transparent'
                          }}
                          onClick={() => {
                            const nuevoValor = prompt('Código:', codigoEfectivo);
                            if (nuevoValor !== null) guardarOverride(op.id_operacion, 'codigo', nuevoValor);
                          }}
                          title="Click para editar"
                        >
                          {codigoEfectivo || '-'}{asterisco('codigo')}
                        </span>
                      </td>
                      <td className={styles.descripcion}>
                        <span
                          style={{
                            cursor: 'pointer',
                            padding: '2px 4px',
                            borderRadius: '3px',
                            backgroundColor: override?.descripcion ? 'rgba(245, 158, 11, 0.15)' : 'transparent'
                          }}
                          onClick={() => {
                            const nuevoValor = prompt('Descripción:', descripcionEfectiva);
                            if (nuevoValor !== null) guardarOverride(op.id_operacion, 'descripcion', nuevoValor);
                          }}
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
                          className={styles.selectEditable}
                          style={{
                            backgroundColor: override?.marca ? 'rgba(245, 158, 11, 0.15)' : 'transparent'
                          }}
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
                          className={styles.selectEditable}
                          style={{
                            backgroundColor: override?.categoria ? 'rgba(245, 158, 11, 0.15)' : 'transparent'
                          }}
                          disabled={!marcaEfectiva}
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
                          className={styles.selectEditable}
                          style={{
                            backgroundColor: override?.subcategoria ? 'rgba(245, 158, 11, 0.15)' : 'transparent'
                          }}
                          disabled={!categoriaEfectiva}
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
                          style={{
                            cursor: 'pointer',
                            padding: '2px 4px',
                            borderRadius: '3px',
                            backgroundColor: override?.cantidad ? 'rgba(245, 158, 11, 0.15)' : 'transparent'
                          }}
                          onClick={() => {
                            const valorActual = getValorEfectivo(op, 'cantidad') || op.cantidad || '';
                            const nuevoValor = prompt('Cantidad:', valorActual);
                            if (nuevoValor !== null) guardarOverride(op.id_operacion, 'cantidad', nuevoValor ? parseFloat(nuevoValor) : null);
                          }}
                          title="Click para editar"
                        >
                          {getValorEfectivo(op, 'cantidad') || op.cantidad || '-'}{asterisco('cantidad')}
                        </span>
                      </td>
                      <td className={styles.monto}>
                        <span
                          style={{
                            cursor: 'pointer',
                            padding: '2px 4px',
                            borderRadius: '3px',
                            backgroundColor: override?.precio_unitario ? 'rgba(245, 158, 11, 0.15)' : 'transparent'
                          }}
                          onClick={() => {
                            const valorActual = getValorEfectivo(op, 'precio_unitario') || op.precio_unitario_sin_iva || '';
                            const nuevoValor = prompt('Precio unitario:', valorActual);
                            if (nuevoValor !== null) guardarOverride(op.id_operacion, 'precio_unitario', nuevoValor ? parseFloat(nuevoValor) : null);
                          }}
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
                          style={{
                            cursor: 'pointer',
                            padding: '2px 4px',
                            borderRadius: '3px',
                            backgroundColor: override?.costo_unitario ? 'rgba(245, 158, 11, 0.15)' : (sinCosto ? 'rgba(239, 68, 68, 0.15)' : 'transparent')
                          }}
                          onClick={() => {
                            const valorActual = getValorEfectivo(op, 'costo_unitario') || op.costo_unitario || '';
                            const nuevoValor = prompt('Costo unitario:', valorActual);
                            if (nuevoValor !== null) guardarOverride(op.id_operacion, 'costo_unitario', nuevoValor ? parseFloat(nuevoValor) : null);
                          }}
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
                          className={sinCosto ? styles.alertWarning : ''}
                          style={{
                            padding: '0.25rem 0.5rem',
                            fontSize: '0.8rem',
                            cursor: 'pointer',
                            background: sinCosto ? undefined : '#e5e7eb',
                            border: sinCosto ? undefined : 'none',
                            borderRadius: '4px'
                          }}
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
