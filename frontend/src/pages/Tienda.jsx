import { useState, useEffect, useRef, useCallback } from 'react';
import PricingModalTesla from '../components/PricingModalTesla';
import { useDebounce } from '../hooks/useDebounce';
import { useTiendaFilters } from '../hooks/useTiendaFilters';
import { useTiendaData } from '../hooks/useTiendaData';
import { useTiendaPricing } from '../hooks/useTiendaPricing';
import { useTiendaSelection } from '../hooks/useTiendaSelection';
import { useTiendaKeyboard } from '../hooks/useTiendaKeyboard';
import './Tienda.css';
import '../styles/table-tesla.css';
import '../styles/buttons-tesla.css';
import axios from 'axios';
import { useAuthStore } from '../store/authStore';
import { usePermisos } from '../contexts/PermisosContext';
import ExportModal from '../components/ExportModal';
import CalcularWebModal from '../components/CalcularWebModal';
import ModalInfoProducto from '../components/ModalInfoProducto';
import SetupMarkups from '../components/SetupMarkups';
import StatCard from '../components/StatCard';
import './Productos.css';

export default function Tienda() {
  const { tienePermiso } = usePermisos();
  const puedeGestionarMarkups = tienePermiso('productos.gestionar_markups_tienda');
  const [tabActivo, setTabActivo] = useState('productos'); // 'productos' o 'setup-markups'
  const [productoSeleccionado, setProductoSeleccionado] = useState(null);
  
  // Custom hook para filtros (consolida 25+ estados)
  const filters = useTiendaFilters();
  const {
    searchInput, setSearchInput,
    filtroStock, setFiltroStock,
    filtroPrecio, setFiltroPrecio,
    marcasSeleccionadas, setMarcasSeleccionadas,
    subcategoriasSeleccionadas, setSubcategoriasSeleccionadas,
    pmsSeleccionados, setPmsSeleccionados,
    coloresSeleccionados, setColoresSeleccionados,
    filtroRebate, setFiltroRebate,
    filtroOferta, setFiltroOferta,
    filtroWebTransf: filtroWebTransfFiltro,
    setFiltroWebTransf: setFiltroWebTransfFiltro,
    filtroTiendaNube, setFiltroTiendaNube,
    filtroOutOfCards, setFiltroOutOfCards,
    filtroMLA, setFiltroMLA,
    filtroEstadoMLA, setFiltroEstadoMLA,
    filtroNuevos, setFiltroNuevos,
    filtroMarkupClasica, setFiltroMarkupClasica,
    filtroMarkupRebate, setFiltroMarkupRebate,
    filtroMarkupOferta, setFiltroMarkupOferta,
    filtroMarkupWebTransf, setFiltroMarkupWebTransf,
    filtrosAuditoria, setFiltrosAuditoria,
    construirFiltrosParams,
    limpiarTodosFiltros,
  } = filters;

  // Pagination & sorting (local to component, drives data loading)
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [ordenColumnas, setOrdenColumnas] = useState([]);
  const debouncedSearch = useDebounce(searchInput, 500);

  // Toast notification
  const [toast, setToast] = useState(null);
  const toastTimeoutRef = useRef(null);
  const showToast = useCallback((message, type = 'success') => {
    if (toastTimeoutRef.current) clearTimeout(toastTimeoutRef.current);
    setToast({ message, type });
    toastTimeoutRef.current = setTimeout(() => setToast(null), 3000);
  }, []);
  useEffect(() => {
    return () => { if (toastTimeoutRef.current) clearTimeout(toastTimeoutRef.current); };
  }, []);

  // === DATA HOOK: productos, stats, marcas, subcats, PMs, dólar, web tarjeta ===
  const {
    productos, setProductos, loading, totalProductos,
    stats,
    marcas, subcategorias, usuarios, tiposAccion, pms,
    marcasPorPM, subcategoriasPorPM,
    markupWebTarjeta, dolarVenta,
    auditoriaVisible, setAuditoriaVisible, auditoriaData, verAuditoria,
    cargarProductos, cargarStats,
  } = useTiendaData({
    construirFiltrosParams,
    page,
    pageSize,
    ordenColumnas,
    debouncedSearch,
    filters,
    showToast,
  });

  const API_URL = import.meta.env.VITE_API_URL;

  // === PRICING HOOK: edición de precios, toggles, colores ===
  const {
    editandoPrecio, setEditandoPrecio,
    editandoRebate, setEditandoRebate,
    editandoWebTransf, setEditandoWebTransf,
    webTransfTemp, setWebTransfTemp,
    editandoCuota, setEditandoCuota,
    cuotaTemp, setCuotaTemp,
    editandoPrecioGremio, setEditandoPrecioGremio,
    modoEdicionGremio,
    precioGremioTemp, setPrecioGremioTemp,
    iniciarEdicionWebTransf, guardarWebTransf,
    cambiarColorProducto, cambiarColorRapido,
    iniciarEdicionCuota, guardarCuota,
    calcularPrecioDesdeMarkup,
    iniciarEdicionPrecioGremio, guardarPrecioGremio,
    eliminarPrecioGremioManual, eliminarTodosPreciosGremioManuales,
    toggleRebateRapido, toggleWebTransfRapido, toggleOutOfCardsRapido,
    iniciarEdicionDesdeTeclado,
  } = useTiendaPricing({
    setProductos,
    productos,
    cargarProductos,
    cargarStats,
    showToast,
  });

  // === ESTADOS DE UI ===
  const [mostrarExportModal, setMostrarExportModal] = useState(false);
  const [mostrarCalcularWebModal, setMostrarCalcularWebModal] = useState(false);
  const [busquedaMarca, setBusquedaMarca] = useState('');
  const [busquedaSubcategoria, setBusquedaSubcategoria] = useState('');
  const [panelFiltroActivo, setPanelFiltroActivo] = useState(null);
  const [mostrarFiltrosAvanzados, setMostrarFiltrosAvanzados] = useState(false);
  const [colorDropdownAbierto, setColorDropdownAbierto] = useState(null);

  // Navigation state is managed by useTiendaKeyboard (see below)

  // === ESTADOS DE VISTA ===
  const [vistaModoCuotas, setVistaModoCuotas] = useState(false);
  const [recalcularCuotasAuto, setRecalcularCuotasAuto] = useState(() => {
    const saved = localStorage.getItem('recalcularCuotasAuto');
    return saved === null ? true : JSON.parse(saved);
  });
  const [vistaModoPrecioGremioUSD, setVistaModoPrecioGremioUSD] = useState(false);

  // === SELECTION HOOK: multi-select, batch paint ===
  const {
    productosSeleccionados,
    toggleSeleccion,
    seleccionarTodos,
    limpiarSeleccion,
    pintarLote,
  } = useTiendaSelection({
    productos,
    setProductos,
    cargarStats,
    showToast,
  });

  // === MODALES ===
  const [mostrarModalConfig, setMostrarModalConfig] = useState(false);
  const [productoConfig, setProductoConfig] = useState(null);
  const [configTemp, setConfigTemp] = useState({ recalcular_cuotas_auto: null, markup_adicional_cuotas_custom: null });
  const [mostrarModalInfo, setMostrarModalInfo] = useState(false);
  const [productoInfo, setProductoInfo] = useState(null);
  const [mostrarModalBan, setMostrarModalBan] = useState(false);
  const [productoBan, setProductoBan] = useState(null);
  const [palabraVerificacion, setPalabraVerificacion] = useState('');
  const [palabraObjetivo, setPalabraObjetivo] = useState('');
  const [motivoBan, setMotivoBan] = useState('');

  const user = useAuthStore((state) => state.user);

  // === PERMISOS ===
  const puedeEditarPrecioGremioManual = tienePermiso('tienda.editar_precio_gremio_manual');
  const puedeEditarWebTransf = tienePermiso('tienda.editar_precio_web_transf');
  const puedeMarcarColor = tienePermiso('productos.marcar_color');
  const puedeMarcarColorLote = tienePermiso('productos.marcar_color_lote');
  const puedeCalcularWebMasivo = tienePermiso('productos.calcular_web_masivo');
  const puedeEditar = tienePermiso('tienda.editar_precio_gremio') || puedeEditarWebTransf || tienePermiso('productos.editar_precio_cuotas');

  // === KEYBOARD HOOK: navigation, shortcuts, clipboard ===
  const {
    celdaActiva, setCeldaActiva,
    modoNavegacion,
    mostrarShortcutsHelp, setMostrarShortcutsHelp,
  } = useTiendaKeyboard({
    pricing: {
      editandoPrecio, setEditandoPrecio,
      editandoRebate, setEditandoRebate,
      editandoWebTransf, setEditandoWebTransf,
      editandoCuota,
      iniciarEdicionDesdeTeclado,
      cambiarColorRapido,
      toggleRebateRapido, toggleWebTransfRapido, toggleOutOfCardsRapido,
    },
    selection: { toggleSeleccion },
    data: { productos, setProductos, cargarStats },
    ui: {
      panelFiltroActivo, setPanelFiltroActivo,
      mostrarFiltrosAvanzados, setMostrarFiltrosAvanzados,
      vistaModoCuotas, setVistaModoCuotas,
      recalcularCuotasAuto, setRecalcularCuotasAuto,
      vistaModoPrecioGremioUSD, setVistaModoPrecioGremioUSD,
      mostrarExportModal, setMostrarExportModal,
      mostrarCalcularWebModal, setMostrarCalcularWebModal,
      mostrarModalConfig, mostrarModalInfo,
      setProductoInfo, setMostrarModalInfo,
      colorDropdownAbierto, setColorDropdownAbierto,
    },
    permissions: { puedeEditar, puedeMarcarColor, puedeEditarWebTransf, puedeCalcularWebMasivo },
    showToast,
  });

  // Auto-focus en inputs de búsqueda cuando se abren los paneles de filtro
  useEffect(() => {
    if (panelFiltroActivo === 'marcas' || panelFiltroActivo === 'subcategorias') {
      // Pequeño delay para asegurar que el panel esté renderizado
      setTimeout(() => {
        const input = document.querySelector('.dropdown-search input');
        if (input) {
          input.focus();
        }
      }, 100);
    }
  }, [panelFiltroActivo]);

  // Guardar preferencia de recalcular cuotas en localStorage
  useEffect(() => {
    localStorage.setItem('recalcularCuotasAuto', JSON.stringify(recalcularCuotasAuto));
  }, [recalcularCuotasAuto]);

  const handleOrdenar = (columna, event) => {
    const shiftPressed = event?.shiftKey;

    if (!shiftPressed) {
      // Sin Shift: ordenamiento simple (como antes)
      const existente = ordenColumnas.find(o => o.columna === columna);

      if (existente) {
        if (existente.direccion === 'asc') {
          setOrdenColumnas([{ columna, direccion: 'desc' }]);
        } else {
          setOrdenColumnas([]);
        }
      } else {
        setOrdenColumnas([{ columna, direccion: 'asc' }]);
      }
    } else {
      // Con Shift: ordenamiento múltiple
      const existente = ordenColumnas.find(o => o.columna === columna);

      if (existente) {
        if (existente.direccion === 'asc') {
          // Cambiar a descendente
          setOrdenColumnas(
            ordenColumnas.map(o =>
              o.columna === columna ? { ...o, direccion: 'desc' } : o
            )
          );
        } else {
          // Quitar esta columna del ordenamiento
          setOrdenColumnas(ordenColumnas.filter(o => o.columna !== columna));
        }
      } else {
        // Agregar nueva columna al ordenamiento
        setOrdenColumnas([...ordenColumnas, { columna, direccion: 'asc' }]);
      }
    }
  };

  const getIconoOrden = (columna) => {
    const orden = ordenColumnas.find(o => o.columna === columna);
    if (!orden) return '↕';
    return orden.direccion === 'asc' ? '▲' : '▼';
  };

  const getNumeroOrden = (columna) => {
    const index = ordenColumnas.findIndex(o => o.columna === columna);
    return index >= 0 ? index + 1 : null;
  };

  // Los productos ya vienen ordenados desde el backend
  const productosOrdenados = productos;

  // Filtrar marcas por búsqueda y por PM seleccionado
  const marcasFiltradas = marcas.filter(m => {
    // Filtrar por búsqueda
    const matchBusqueda = m.toLowerCase().includes(busquedaMarca.toLowerCase());

    // Si hay PMs seleccionados, solo mostrar marcas de esos PMs
    if (marcasPorPM.length > 0) {
      return matchBusqueda && marcasPorPM.includes(m);
    }

    return matchBusqueda;
  });

  const formatearFechaGMT3 = (fechaString) => {
    const fecha = new Date(fechaString + 'Z'); // Forzar que se interprete como UTC
    // Convertir a GMT-3 (Argentina)
    const opciones = {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
      timeZone: 'America/Argentina/Buenos_Aires'
    };
    return fecha.toLocaleString('es-AR', opciones);
  };

  const getMarkupColor = (markup) => {
    if (markup === null || markup === undefined) return 'var(--text-secondary)';
    if (markup < 0) return 'var(--error)';
    if (markup < 1) return 'var(--warning)';
    return 'var(--success)';
  };

  const COLORES_DISPONIBLES = [
    { id: 'rojo', nombre: 'Urgente', color: 'var(--product-urgent-bg)', colorTexto: 'var(--product-urgent-text)' },
    { id: 'naranja', nombre: 'Advertencia', color: 'var(--product-warning-bg)', colorTexto: 'var(--product-warning-text)' },
    { id: 'amarillo', nombre: 'Atención', color: 'var(--product-attention-bg)', colorTexto: 'var(--product-attention-text)' },
    { id: 'verde', nombre: 'OK', color: 'var(--product-ok-bg)', colorTexto: 'var(--product-ok-text)' },
    { id: 'azul', nombre: 'Info', color: 'var(--product-info-bg)', colorTexto: 'var(--product-info-text)' },
    { id: 'purpura', nombre: 'Revisión', color: 'var(--product-review-bg)', colorTexto: 'var(--product-review-text)' },
    { id: 'gris', nombre: 'Inactivo', color: 'var(--product-inactive-bg)', colorTexto: 'var(--product-inactive-text)' },
    { id: null, nombre: 'Sin color', color: null, colorTexto: null },
  ];

  const abrirModalBan = (producto) => {
    // Obtener palabras de la descripción (filtrar palabras de más de 3 caracteres)
    const palabras = producto.descripcion
      .split(/\s+/)
      .filter(p => p.length > 3)
      .map(p => p.replace(/[^a-zA-Z0-9áéíóúñÁÉÍÓÚÑ]/g, ''));

    if (palabras.length === 0) {
      showToast('No hay palabras suficientes en la descripción del producto', 'error');
      return;
    }

    // Elegir una palabra aleatoria
    const palabraAleatoria = palabras[Math.floor(Math.random() * palabras.length)];

    setProductoBan(producto);
    setPalabraObjetivo(palabraAleatoria);
    setPalabraVerificacion('');
    setMotivoBan('');
    setMostrarModalBan(true);
  };

  const confirmarBan = async () => {
    // Verificar palabra
    if (palabraVerificacion.toLowerCase() !== palabraObjetivo.toLowerCase()) {
      showToast('La palabra de verificación no coincide', 'error');
      return;
    }

    try {
      const token = localStorage.getItem('token');
      await axios.post(
        `${API_URL}/producto-banlist`,
        {
          item_ids: productoBan.item_id ? String(productoBan.item_id) : null,
          eans: productoBan.ean || null,
          motivo: motivoBan || 'Sin motivo especificado'
        },
        {
          headers: { Authorization: `Bearer ${token}` }
        }
      );

      showToast('Producto agregado a la banlist', 'success');
      setMostrarModalBan(false);
      setProductoBan(null);
      setPalabraVerificacion('');
      setPalabraObjetivo('');
      setMotivoBan('');

      // Recargar productos para reflejar el cambio
      cargarProductos();
    } catch (error) {
      showToast(`Error: ${error.response?.data?.detail || error.message}`, 'error');
    }
  };

  const handleSearchChange = (e) => {
    setSearchInput(e.target.value);
    setPage(1);
  };

  // Modal de configuración individual
  const abrirModalConfig = (producto) => {
    setProductoConfig(producto);
    setConfigTemp({
      recalcular_cuotas_auto: producto.recalcular_cuotas_auto,
      markup_adicional_cuotas_custom: producto.markup_adicional_cuotas_custom || ''
    });
    setMostrarModalConfig(true);
  };

  const guardarConfigIndividual = async () => {
    try {
      const token = localStorage.getItem('token');

      // Preparar datos: null significa usar global
      const data = {
        recalcular_cuotas_auto: configTemp.recalcular_cuotas_auto === 'null' ? null :
                                configTemp.recalcular_cuotas_auto === 'true' ? true :
                                configTemp.recalcular_cuotas_auto === 'false' ? false : null,
        markup_adicional_cuotas_custom: configTemp.markup_adicional_cuotas_custom === '' ? null :
                                        parseFloat(configTemp.markup_adicional_cuotas_custom)
      };

      await axios.patch(
        `${API_URL}/productos/${productoConfig.item_id}/config-cuotas`,
        data,
        { headers: { Authorization: `Bearer ${token}` } }
      );

      // Actualizar producto en el estado
      setProductos(prods => prods.map(p =>
        p.item_id === productoConfig.item_id
          ? {
              ...p,
              recalcular_cuotas_auto: data.recalcular_cuotas_auto,
              markup_adicional_cuotas_custom: data.markup_adicional_cuotas_custom
            }
          : p
      ));

      setMostrarModalConfig(false);
      showToast('Configuración actualizada correctamente', 'success');
    } catch (error) {
      showToast('Error al guardar configuración: ' + (error.response?.data?.detail || error.message), 'error');
    }
  };

  // Funciones para aplicar filtros desde las stats
  const aplicarFiltroStat = (filtros) => {
    // Limpiar los filtros que no están siendo aplicados
    if (filtros.stock === undefined) setFiltroStock("todos");
    else setFiltroStock(filtros.stock);

    if (filtros.precio === undefined) setFiltroPrecio("todos");
    else setFiltroPrecio(filtros.precio);

    if (filtros.rebate === undefined) setFiltroRebate(null);
    else setFiltroRebate(filtros.rebate);

    if (filtros.oferta === undefined) setFiltroOferta(null);
    else setFiltroOferta(filtros.oferta);

    if (filtros.markupClasica === undefined) setFiltroMarkupClasica(null);
    else setFiltroMarkupClasica(filtros.markupClasica);

    if (filtros.markupRebate === undefined) setFiltroMarkupRebate(null);
    else setFiltroMarkupRebate(filtros.markupRebate);

    if (filtros.markupOferta === undefined) setFiltroMarkupOferta(null);
    else setFiltroMarkupOferta(filtros.markupOferta);

    if (filtros.markupWebTransf === undefined) setFiltroMarkupWebTransf(null);
    else setFiltroMarkupWebTransf(filtros.markupWebTransf);

    if (filtros.mla === undefined) setFiltroMLA(null);
    else setFiltroMLA(filtros.mla);

    if (filtros.nuevos === undefined) setFiltroNuevos(null);
    else setFiltroNuevos(filtros.nuevos);

    // Limpiar otros filtros avanzados
    if (filtros.webTransf === undefined) setFiltroWebTransfFiltro(null);
    else setFiltroWebTransfFiltro(filtros.webTransf);

    setFiltroOutOfCards(null);

    setPage(1);
  };


  return (
    <div className="productos-container">
      {/* Tabs de navegación */}
      <div className="tabs-container">
        <button
          className={`tab-button ${tabActivo === 'productos' ? 'tab-active' : ''}`}
          onClick={() => setTabActivo('productos')}
        >
          📦 Productos
        </button>
        {puedeGestionarMarkups && (
          <button
            className={`tab-button ${tabActivo === 'setup-markups' ? 'tab-active' : ''}`}
            onClick={() => setTabActivo('setup-markups')}
          >
            ⚙️ Setup Markups
          </button>
        )}
      </div>

      {tabActivo === 'setup-markups' ? (
        <SetupMarkups />
      ) : (
        <>
      <div className="stats-grid">
        <StatCard
          label="📦 Total Productos"
          value={stats?.total_productos?.toLocaleString('es-AR') || 0}
          onClick={limpiarTodosFiltros}
        />

        <StatCard
          label="📊 Stock & Precio"
          subItems={[
            {
              label: 'Con Stock:',
              value: stats?.con_stock?.toLocaleString('es-AR') || 0,
              color: 'green',
              onClick: () => aplicarFiltroStat({ stock: 'con_stock' })
            },
            {
              label: 'Con Precio:',
              value: stats?.con_precio?.toLocaleString('es-AR') || 0,
              color: 'blue',
              onClick: () => aplicarFiltroStat({ precio: 'con_precio' })
            },
            {
              label: 'Stock sin $:',
              value: stats?.con_stock_sin_precio?.toLocaleString('es-AR') || 0,
              color: 'red',
              onClick: () => aplicarFiltroStat({ stock: 'con_stock', precio: 'sin_precio' })
            }
          ]}
        />

        <StatCard
          label="✨ Nuevos (7 días)"
          subItems={[
            {
              label: 'Total:',
              value: stats?.nuevos_ultimos_7_dias?.toLocaleString('es-AR') || 0,
              color: 'blue',
              onClick: () => aplicarFiltroStat({ nuevos: 'ultimos_7_dias' })
            },
            {
              label: 'Sin Precio:',
              value: stats?.nuevos_sin_precio?.toLocaleString('es-AR') || 0,
              color: 'red',
              onClick: () => aplicarFiltroStat({ nuevos: 'ultimos_7_dias', precio: 'sin_precio' })
            }
          ]}
        />

        <StatCard
          label="Sin MLA"
          subItems={[
            {
              label: 'Total:',
              value: stats?.sin_mla_no_banlist?.toLocaleString('es-AR') || 0,
              color: 'orange',
              onClick: () => aplicarFiltroStat({ mla: 'sin_mla' })
            },
            {
              label: 'Con Stock:',
              value: stats?.sin_mla_con_stock?.toLocaleString('es-AR') || 0,
              color: 'green',
              onClick: () => aplicarFiltroStat({ mla: 'sin_mla', stock: 'con_stock' })
            },
            {
              label: 'Sin Stock:',
              value: stats?.sin_mla_sin_stock?.toLocaleString('es-AR') || 0,
              color: 'blue',
              onClick: () => aplicarFiltroStat({ mla: 'sin_mla', stock: 'sin_stock' })
            },
            {
              label: 'Nuevos:',
              value: stats?.sin_mla_nuevos?.toLocaleString('es-AR') || 0,
              color: 'blue',
              onClick: () => aplicarFiltroStat({ mla: 'sin_mla', nuevos: 'ultimos_7_dias' })
            }
          ]}
        />

        <StatCard
          label="💎 Oferta sin Rebate"
          value={stats?.mejor_oferta_sin_rebate?.toLocaleString('es-AR') || 0}
          color="purple"
          onClick={() => aplicarFiltroStat({ oferta: 'con_oferta', rebate: 'sin_rebate' })}
        />

        <StatCard
          label="📉 Markup Negativo"
          subItems={[
            {
              label: 'Clásica:',
              value: stats?.markup_negativo_clasica || 0,
              color: 'red',
              onClick: () => aplicarFiltroStat({ markupClasica: 'negativo' })
            },
            {
              label: 'Rebate:',
              value: stats?.markup_negativo_rebate || 0,
              color: 'red',
              onClick: () => aplicarFiltroStat({ markupRebate: 'negativo' })
            },
            {
              label: 'Oferta:',
              value: stats?.markup_negativo_oferta || 0,
              color: 'red',
              onClick: () => aplicarFiltroStat({ markupOferta: 'negativo' })
            },
            {
              label: 'Web:',
              value: stats?.markup_negativo_web || 0,
              color: 'red',
              onClick: () => aplicarFiltroStat({ markupWebTransf: 'negativo' })
            }
          ]}
        />
      </div>

      <div className="search-bar">
        <input
          type="text"
          placeholder="Buscar productos..."
          value={searchInput}
          onChange={handleSearchChange}
          onFocus={(e) => e.target.select()}
          className="search-input"
        />
      </div>

      <div className="filters-container-modern">
        {/* Todos los filtros en una sola línea compacta */}
        <div className="filters-unified">
          {/* Selectores compactos de Stock y Precio */}
          <select
            value={filtroStock}
            onChange={(e) => { setFiltroStock(e.target.value); setPage(1); }}
            className="filter-select-compact"
            title="Filtrar por stock"
          >
            <option value="todos">Stock</option>
            <option value="con_stock">Con stock</option>
            <option value="sin_stock">Sin stock</option>
          </select>

          <select
            value={filtroPrecio}
            onChange={(e) => { setFiltroPrecio(e.target.value); setPage(1); }}
            className="filter-select-compact"
            title="Filtrar por precio"
          >
            <option value="todos">Precio</option>
            <option value="con_precio">Con precio</option>
            <option value="sin_precio">Sin precio</option>
          </select>

          {/* Botones de filtro */}
          <button
            onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'marcas' ? null : 'marcas')}
            className={`filter-button ${marcasSeleccionadas.length > 0 ? 'active' : ''}`}
          >
            Marcas
            {marcasSeleccionadas.length > 0 && (
              <span className="filter-badge">{marcasSeleccionadas.length}</span>
            )}
          </button>

          <button
            onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'subcategorias' ? null : 'subcategorias')}
            className={`filter-button ${subcategoriasSeleccionadas.length > 0 ? 'active' : ''}`}
          >
            Subcategorías
            {subcategoriasSeleccionadas.length > 0 && (
              <span className="filter-badge">{subcategoriasSeleccionadas.length}</span>
            )}
          </button>

          <button
            onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'pms' ? null : 'pms')}
            className={`filter-button ${pmsSeleccionados.length > 0 ? 'active' : ''}`}
          >
            PM
            {pmsSeleccionados.length > 0 && (
              <span className="filter-badge">{pmsSeleccionados.length}</span>
            )}
          </button>

          <button
            onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'auditoria' ? null : 'auditoria')}
            className={`filter-button ${(filtrosAuditoria.usuarios.length > 0 || filtrosAuditoria.tipos_accion.length > 0 || filtrosAuditoria.fecha_desde || filtrosAuditoria.fecha_hasta) ? 'active' : ''}`}
          >
            Auditoría
            {(filtrosAuditoria.usuarios.length > 0 || filtrosAuditoria.tipos_accion.length > 0) && (
              <span className="filter-badge">
                {filtrosAuditoria.usuarios.length + filtrosAuditoria.tipos_accion.length}
              </span>
            )}
          </button>

          <button
            onClick={() => setMostrarFiltrosAvanzados(!mostrarFiltrosAvanzados)}
            className={`filter-button ${(filtroRebate || filtroOferta || filtroWebTransfFiltro || filtroMarkupClasica || filtroMarkupRebate || filtroMarkupOferta || filtroMarkupWebTransf || filtroOutOfCards || coloresSeleccionados.length > 0) ? 'active' : ''}`}
          >
            Avanzados
            {(filtroRebate || filtroOferta || filtroWebTransfFiltro || filtroMarkupClasica || filtroMarkupRebate || filtroMarkupOferta || filtroMarkupWebTransf || filtroOutOfCards || coloresSeleccionados.length > 0) && (
              <span className="filter-badge">
                {[filtroRebate, filtroOferta, filtroWebTransfFiltro, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards].filter(Boolean).length + coloresSeleccionados.length}
              </span>
            )}
          </button>

          <button
            onClick={limpiarTodosFiltros}
            className="btn-tesla outline-subtle-danger sm"
            title="Limpiar todos los filtros"
          >
            Limpiar
          </button>

          {/* Separador visual */}
          <div className="filter-separator"></div>

          {/* Toggle Vista Cuotas */}
          <button
            className="filter-button"
            onClick={() => {
              setVistaModoCuotas(!vistaModoCuotas);
              // Resetear columna activa para evitar ir a columnas ocultas
              if (celdaActiva) {
                setCeldaActiva({ ...celdaActiva, colIndex: 0 });
              }
            }}
            title="Alt+V para cambiar vista"
          >
            {vistaModoCuotas ? '📊 Cuotas' : 'Normal'}
          </button>

          {/* Toggle Precio Gremio ARS/USD */}
          <button
            className="filter-button"
            onClick={() => setVistaModoPrecioGremioUSD(!vistaModoPrecioGremioUSD)}
            title="Alt+D para cambiar"
          >
            {vistaModoPrecioGremioUSD ? '💵 Gremio USD' : '💰 Gremio ARS'}
          </button>

          {/* Auto-recalcular */}
          <button
            onClick={() => setRecalcularCuotasAuto(!recalcularCuotasAuto)}
            className={`btn-tesla outline-subtle-primary sm ${recalcularCuotasAuto ? 'toggle-active' : ''}`}
            title="Alt+R para toggle"
          >
            {recalcularCuotasAuto ? '✓ ' : ''}Auto-recalcular
          </button>

          {/* Separador visual */}
          <div className="filter-separator"></div>

          {/* Botones de Exportar y Calcular */}
          <button
            onClick={() => setMostrarExportModal(true)}
            className="btn-tesla outline-subtle-success sm"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M19 12v7H5v-7H3v7c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2v-7h-2zm-6 .67l2.59-2.58L17 11.5l-5 5-5-5 1.41-1.41L11 12.67V3h2z"/></svg>
            Exportar
          </button>

          {puedeCalcularWebMasivo && (
          <button
            onClick={() => setMostrarCalcularWebModal(true)}
            className="btn-tesla outline-subtle-primary sm"
          >
            Calcular Web Transf.
          </button>
          )}

          {tienePermiso('tienda.editar_precio_gremio_manual') && (
          <button
            onClick={eliminarTodosPreciosGremioManuales}
            className="btn-tesla outline-subtle-warning sm"
            title="Eliminar todos los precios gremio manuales y volver al cálculo automático"
          >
            Resetear Precios Gremio
          </button>
          )}
        </div>
      </div>

      {/* Panel compartido de filtros */}
      {panelFiltroActivo && (
          <div className="advanced-filters-panel">
            {/* Contenido de Marcas */}
            {panelFiltroActivo === 'marcas' && (
              <>
                <div className="advanced-filters-header">
                  <h3>Marcas</h3>
                  {marcasSeleccionadas.length > 0 && (
                    <button
                      onClick={() => {
                        setMarcasSeleccionadas([]);
                        setPage(1);
                      }}
                      className="btn-tesla outline-subtle-danger sm"
                    >
                      Limpiar filtros ({marcasSeleccionadas.length})
                    </button>
                  )}
                </div>

                <div className="dropdown-header">
                  <div className="dropdown-search">
                    <input
                      type="text"
                      placeholder="Buscar marca..."
                      value={busquedaMarca}
                      onChange={(e) => setBusquedaMarca(e.target.value)}
                      onFocus={(e) => e.target.select()}
                    />
                    {busquedaMarca && (
                      <button
                        onClick={() => setBusquedaMarca('')}
                        className="dropdown-search-clear"
                        aria-label="Limpiar búsqueda de marca"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                </div>

                <div className="dropdown-content">
                  {marcasFiltradas.map(marca => (
                    <label
                      key={marca}
                      className={`dropdown-item ${marcasSeleccionadas.includes(marca) ? 'selected' : ''}`}
                    >
                      <input
                        type="checkbox"
                        checked={marcasSeleccionadas.includes(marca)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setMarcasSeleccionadas([...marcasSeleccionadas, marca]);
                          } else {
                            setMarcasSeleccionadas(marcasSeleccionadas.filter(m => m !== marca));
                          }
                          setPage(1);
                        }}
                      />
                      <span>{marca}</span>
                    </label>
                  ))}
                </div>
              </>
            )}

            {/* Contenido de Subcategorías */}
            {panelFiltroActivo === 'subcategorias' && (
              <>
                <div className="advanced-filters-header">
                  <h3>Subcategorías</h3>
                  <div className="dropdown-actions">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setSubcategoriasSeleccionadas([]);
                      }}
                      className="btn-tesla outline-subtle-danger sm"
                    >
                      Limpiar
                    </button>
                  </div>
                </div>

                <div className="dropdown-header">
                  <div className="dropdown-search">
                    <input
                      type="text"
                      placeholder="Buscar subcategoría..."
                      value={busquedaSubcategoria}
                      onChange={(e) => setBusquedaSubcategoria(e.target.value)}
                      onFocus={(e) => e.target.select()}
                      onClick={(e) => e.stopPropagation()}
                    />
                    {busquedaSubcategoria && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setBusquedaSubcategoria('');
                        }}
                        className="dropdown-search-clear"
                        aria-label="Limpiar búsqueda de subcategoría"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                </div>

                <div className="dropdown-content">
                  {(subcategorias || [])
                    .filter(cat =>
                      !busquedaSubcategoria ||
                      cat.nombre.toLowerCase().includes(busquedaSubcategoria.toLowerCase()) ||
                      cat.subcategorias.some(sub => sub.nombre.toLowerCase().includes(busquedaSubcategoria.toLowerCase()))
                    )
                    .map(categoria => {
                      const categoriaCoincide = !busquedaSubcategoria ||
                        categoria.nombre.toLowerCase().includes(busquedaSubcategoria.toLowerCase());

                      let subcatsDeCategoria = categoriaCoincide
                        ? categoria.subcategorias
                        : categoria.subcategorias.filter(sub =>
                            sub.nombre.toLowerCase().includes(busquedaSubcategoria.toLowerCase())
                          );

                      // Si hay PMs seleccionados, filtrar también por subcategorías del PM
                      if (subcategoriasPorPM.length > 0) {
                        subcatsDeCategoria = subcatsDeCategoria.filter(sub =>
                          subcategoriasPorPM.includes(sub.id)
                        );
                      }

                      const todasSeleccionadas = subcatsDeCategoria.length > 0 && subcatsDeCategoria.every(sub =>
                        subcategoriasSeleccionadas.includes(sub.id.toString())
                      );

                      const algunaSeleccionada = subcatsDeCategoria.some(sub =>
                        subcategoriasSeleccionadas.includes(sub.id.toString())
                      );

                      return (
                        <div key={categoria.nombre} className="category-group">
                          <label onClick={(e) => e.stopPropagation()} className="category-header">
                            <input
                              type="checkbox"
                              checked={todasSeleccionadas}
                              ref={input => {
                                if (input) input.indeterminate = algunaSeleccionada && !todasSeleccionadas;
                              }}
                              onChange={(e) => {
                                e.stopPropagation();
                                const subcatIds = subcatsDeCategoria.map(s => s.id.toString());
                                if (todasSeleccionadas) {
                                  setSubcategoriasSeleccionadas(prev =>
                                    prev.filter(id => !subcatIds.includes(id))
                                  );
                                } else {
                                  setSubcategoriasSeleccionadas(prev => {
                                    const nuevas = [...prev];
                                    subcatIds.forEach(id => {
                                      if (!nuevas.includes(id)) {
                                        nuevas.push(id);
                                      }
                                    });
                                    return nuevas;
                                  });
                                }
                              }}
                            />
                            {categoria.nombre}
                            {algunaSeleccionada && (
                              <span className="category-count">
                                {subcatsDeCategoria.filter(sub =>
                                  subcategoriasSeleccionadas.includes(sub.id.toString())
                                ).length}/{subcatsDeCategoria.length}
                              </span>
                            )}
                          </label>

                          {subcatsDeCategoria.map(subcat => (
                            <label
                              key={subcat.id}
                              onClick={(e) => e.stopPropagation()}
                              className={`subcategory-item ${subcategoriasSeleccionadas.includes(subcat.id.toString()) ? 'selected' : ''}`}
                            >
                              <input
                                type="checkbox"
                                checked={subcategoriasSeleccionadas.includes(subcat.id.toString())}
                                onChange={(e) => {
                                  e.stopPropagation();
                                  const subcatId = subcat.id.toString();
                                  if (subcategoriasSeleccionadas.includes(subcatId)) {
                                    setSubcategoriasSeleccionadas(prev => prev.filter(m => m !== subcatId));
                                  } else {
                                    setSubcategoriasSeleccionadas(prev => [...prev, subcatId]);
                                  }
                                }}
                              />
                              <div>
                                {subcat.nombre}
                                {subcat.grupo_id && (
                                  <span className="subcategory-badge">
                                    G{subcat.grupo_id}
                                  </span>
                                )}
                              </div>
                            </label>
                          ))}
                        </div>
                      );
                    })}
                </div>
              </>
            )}

            {/* Contenido de PMs */}
            {panelFiltroActivo === 'pms' && (
              <>
                <div className="advanced-filters-header">
                  <h3>Product Managers</h3>
                  {pmsSeleccionados.length > 0 && (
                    <button
                      onClick={() => {
                        setPmsSeleccionados([]);
                        setPage(1);
                      }}
                      className="btn-tesla outline-subtle-danger sm"
                    >
                      Limpiar filtros ({pmsSeleccionados.length})
                    </button>
                  )}
                </div>

                <div className="dropdown-content">
                  {pms.map(pm => (
                    <label
                      key={pm.id}
                      className={`dropdown-item ${pmsSeleccionados.includes(pm.id) ? 'selected' : ''}`}
                    >
                      <input
                        type="checkbox"
                        checked={pmsSeleccionados.includes(pm.id)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setPmsSeleccionados([...pmsSeleccionados, pm.id]);
                          } else {
                            setPmsSeleccionados(pmsSeleccionados.filter(id => id !== pm.id));
                          }
                          setPage(1);
                        }}
                      />
                      <span>{pm.nombre} ({pm.email})</span>
                    </label>
                  ))}
                  {pms.length === 0 && (
                    <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                      No hay PMs disponibles
                    </div>
                  )}
                </div>
              </>
            )}

            {/* Contenido de Auditoría */}
            {panelFiltroActivo === 'auditoria' && (
              <>
                <div className="advanced-filters-header">
                  <h3>Filtros de Auditoría</h3>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setFiltrosAuditoria({
                        usuarios: [],
                        tipos_accion: [],
                        fecha_desde: '',
                        fecha_hasta: ''
                      });
                      setPage(1);
                    }}
                    className="btn-tesla outline-subtle-danger sm"
                  >
                    Limpiar Todo
                  </button>
                </div>

                <div className="dropdown-content with-padding">
                  <div className="audit-section">
                    <div className="audit-section-header">
                      👤 Usuario que modificó
                      {filtrosAuditoria.usuarios.length > 0 && (
                        <span className="audit-section-badge">
                          {filtrosAuditoria.usuarios.length}
                        </span>
                      )}
                    </div>
                    <div className="audit-section-content">
                      {usuarios.map(usuario => (
                        <label
                          key={usuario.id}
                          onClick={(e) => e.stopPropagation()}
                          className={`dropdown-item ${filtrosAuditoria.usuarios.includes(usuario.id) ? 'selected' : ''}`}
                        >
                          <input
                            type="checkbox"
                            checked={filtrosAuditoria.usuarios.includes(usuario.id)}
                            onChange={(e) => {
                              e.stopPropagation();
                              setFiltrosAuditoria(prev => ({
                                ...prev,
                                usuarios: e.target.checked
                                  ? [...prev.usuarios, usuario.id]
                                  : prev.usuarios.filter(u => u !== usuario.id)
                              }));
                              setPage(1);
                            }}
                          />
                          {usuario.nombre}
                        </label>
                      ))}
                    </div>
                  </div>

                  <div className="audit-section">
                    <div className="audit-section-header">
                      ⚡ Tipo de Modificación
                      {filtrosAuditoria.tipos_accion.length > 0 && (
                        <span className="audit-section-badge">
                          {filtrosAuditoria.tipos_accion.length}
                        </span>
                      )}
                    </div>
                    <div className="audit-section-content">
                      {tiposAccion.map(tipo => (
                        <label
                          key={tipo}
                          onClick={(e) => e.stopPropagation()}
                          className={`dropdown-item ${filtrosAuditoria.tipos_accion.includes(tipo) ? 'selected' : ''}`}
                        >
                          <input
                            type="checkbox"
                            checked={filtrosAuditoria.tipos_accion.includes(tipo)}
                            onChange={(e) => {
                              e.stopPropagation();
                              setFiltrosAuditoria(prev => ({
                                ...prev,
                                tipos_accion: e.target.checked
                                  ? [...prev.tipos_accion, tipo]
                                  : prev.tipos_accion.filter(t => t !== tipo)
                              }));
                              setPage(1);
                            }}
                          />
                          {tipo.split('_').map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(' ')}
                        </label>
                      ))}
                    </div>
                  </div>

                  <div className="audit-section">
                    <div className="audit-section-header">
                      📅 Rango de Fechas
                    </div>
                    <div className="audit-section-content">
                      <div className="date-input-group">
                        <label className="date-input-label">Desde</label>
                        <input
                          type="datetime-local"
                          value={filtrosAuditoria.fecha_desde.replace(' ', 'T')}
                          onChange={(e) => {
                            e.stopPropagation();
                            setFiltrosAuditoria(prev => ({
                              ...prev,
                              fecha_desde: e.target.value.replace('T', ' ')
                            }));
                            setPage(1);
                          }}
                          onClick={(e) => e.stopPropagation()}
                          className="date-input"
                        />
                      </div>

                      <div className="date-input-group">
                        <label className="date-input-label">Hasta</label>
                        <input
                          type="datetime-local"
                          value={filtrosAuditoria.fecha_hasta.replace(' ', 'T')}
                          onChange={(e) => {
                            e.stopPropagation();
                            setFiltrosAuditoria(prev => ({
                              ...prev,
                              fecha_hasta: e.target.value.replace('T', ' ')
                            }));
                            setPage(1);
                          }}
                          onClick={(e) => e.stopPropagation()}
                          className="date-input"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

      {/* Panel de filtros avanzados */}
      {mostrarFiltrosAvanzados && (
        <div className="advanced-filters-panel">
          <div className="advanced-filters-header">
            <h3>Filtros Avanzados</h3>
            <button
              onClick={() => {
                setFiltroRebate(null);
                setFiltroOferta(null);
                setFiltroWebTransfFiltro(null);
                setFiltroTiendaNube(null);
                setFiltroMarkupClasica(null);
                setFiltroMarkupRebate(null);
                setFiltroMarkupOferta(null);
                setFiltroMarkupWebTransf(null);
                setFiltroOutOfCards(null);
                setFiltroMLA(null);
                setFiltroEstadoMLA(null);
                setFiltroNuevos(null);
                setColoresSeleccionados([]);
                setPage(1);
              }}
              className="btn-tesla outline-subtle-danger sm"
            >
              Limpiar Todos
            </button>
          </div>

          <div className="advanced-filters-grid">
            {/* Filtros de Presencia */}
            <div className="filter-group">
              <div className="filter-group-title">💰 Filtros de Presencia</div>
              <div className="filter-group-content">
                <div className="filter-item">
                  <label>🎁 Rebate</label>
                  <select
                    value={filtroRebate || 'todos'}
                    onChange={(e) => { setFiltroRebate(e.target.value === 'todos' ? null : e.target.value); setPage(1); }}
                    className="filter-select-compact"
                  >
                    <option value="todos">Todos</option>
                    <option value="con_rebate">Con Rebate</option>
                    <option value="sin_rebate">Sin Rebate</option>
                  </select>
                </div>

                <div className="filter-item">
                  <label>🏷️ Mejor Oferta</label>
                  <select
                    value={filtroOferta || 'todos'}
                    onChange={(e) => { setFiltroOferta(e.target.value === 'todos' ? null : e.target.value); setPage(1); }}
                    className="filter-select-compact"
                  >
                    <option value="todos">Todos</option>
                    <option value="con_oferta">Con Oferta</option>
                    <option value="sin_oferta">Sin Oferta</option>
                  </select>
                </div>

                <div className="filter-item">
                  <label>💳 Web Transferencia</label>
                  <select
                    value={filtroWebTransfFiltro || 'todos'}
                    onChange={(e) => { setFiltroWebTransfFiltro(e.target.value === 'todos' ? null : e.target.value); setPage(1); }}
                    className="filter-select-compact"
                  >
                    <option value="todos">Todos</option>
                    <option value="con_web_transf">Con Web Transf.</option>
                    <option value="sin_web_transf">Sin Web Transf.</option>
                  </select>
                </div>

                <div className="filter-item">
                  <label>🛒 Tienda Nube</label>
                  <select
                    value={filtroTiendaNube || 'todos'}
                    onChange={(e) => { setFiltroTiendaNube(e.target.value === 'todos' ? null : e.target.value); setPage(1); }}
                    className="filter-select-compact"
                  >
                    <option value="todos">Todos</option>
                    <option value="con_descuento">🏷️ Con Descuento</option>
                    <option value="sin_descuento">💵 Sin Descuento</option>
                    <option value="no_publicado">📦 No Publicado</option>
                  </select>
                </div>

                <div className="filter-item">
                  <label>🚫 Out of Cards</label>
                  <select
                    value={filtroOutOfCards || 'todos'}
                    onChange={(e) => { setFiltroOutOfCards(e.target.value === 'todos' ? null : e.target.value); setPage(1); }}
                    className="filter-select-compact"
                  >
                    <option value="todos">Todos</option>
                    <option value="con_out_of_cards">Marcados</option>
                    <option value="sin_out_of_cards">No Marcados</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Filtros de Markup */}
            <div className="filter-group">
              <div className="filter-group-title">📊 Filtros de Markup</div>
              <div className="filter-group-content">
                <div className="filter-item">
                  <label>Markup Clásica</label>
                  <select
                    value={filtroMarkupClasica || 'todos'}
                    onChange={(e) => { setFiltroMarkupClasica(e.target.value === 'todos' ? null : e.target.value); setPage(1); }}
                    className="filter-select-compact"
                  >
                    <option value="todos">Todos</option>
                    <option value="positivo">✅ Positivo</option>
                    <option value="negativo">❌ Negativo</option>
                  </select>
                </div>

                <div className="filter-item">
                  <label>Markup Rebate</label>
                  <select
                    value={filtroMarkupRebate || 'todos'}
                    onChange={(e) => { setFiltroMarkupRebate(e.target.value === 'todos' ? null : e.target.value); setPage(1); }}
                    className="filter-select-compact"
                  >
                    <option value="todos">Todos</option>
                    <option value="positivo">✅ Positivo</option>
                    <option value="negativo">❌ Negativo</option>
                  </select>
                </div>

                <div className="filter-item">
                  <label>Markup Oferta</label>
                  <select
                    value={filtroMarkupOferta || 'todos'}
                    onChange={(e) => { setFiltroMarkupOferta(e.target.value === 'todos' ? null : e.target.value); setPage(1); }}
                    className="filter-select-compact"
                  >
                    <option value="todos">Todos</option>
                    <option value="positivo">✅ Positivo</option>
                    <option value="negativo">❌ Negativo</option>
                  </select>
                </div>

                <div className="filter-item">
                  <label>Markup Web Transf.</label>
                  <select
                    value={filtroMarkupWebTransf || 'todos'}
                    onChange={(e) => { setFiltroMarkupWebTransf(e.target.value === 'todos' ? null : e.target.value); setPage(1); }}
                    className="filter-select-compact"
                  >
                    <option value="todos">Todos</option>
                    <option value="positivo">✅ Positivo</option>
                    <option value="negativo">❌ Negativo</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Filtros de Estado */}
            <div className="filter-group">
              <div className="filter-group-title">📋 Filtros de Estado</div>
              <div className="filter-group-content">
                <div className="filter-item">
                  <label>🔍 MercadoLibre</label>
                  <select
                    value={filtroMLA || 'todos'}
                    onChange={(e) => { setFiltroMLA(e.target.value === 'todos' ? null : e.target.value); setPage(1); }}
                    className="filter-select-compact"
                  >
                    <option value="todos">Todos</option>
                    <option value="con_mla">Con MLA</option>
                    <option value="sin_mla">Sin MLA</option>
                  </select>
                </div>

                <div className="filter-item">
                  <label>📊 Estado MLA</label>
                  <select
                    value={filtroEstadoMLA || 'todos'}
                    onChange={(e) => {
                      const valor = e.target.value === 'todos' ? null : e.target.value;
                      setFiltroEstadoMLA(valor);
                      setPage(1);
                    }}
                    className="filter-select"
                  >
                    <option value="todos">Todos</option>
                    <option value="activa">Activas</option>
                    <option value="pausada">Pausadas</option>
                  </select>
                </div>

                <div className="filter-item">
                  <label>✨ Productos Nuevos</label>
                  <select
                    value={filtroNuevos || 'todos'}
                    onChange={(e) => { setFiltroNuevos(e.target.value === 'todos' ? null : e.target.value); setPage(1); }}
                    className="filter-select-compact"
                  >
                    <option value="todos">Todos</option>
                    <option value="ultimos_7_dias">Últimos 7 días</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Filtros de Color */}
            <div className="filter-group">
              <div className="filter-group-title">🎨 Marcado por Color</div>
              <div className="filter-group-content" style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {COLORES_DISPONIBLES.map(c => (
                  <label
                    key={c.id || 'sin_color'}
                    className="color-checkbox"
                    style={{
                      backgroundColor: c.color || 'var(--bg-primary)',
                      border: coloresSeleccionados.includes(c.id === null ? 'sin_color' : c.id) ? '3px solid var(--text-primary)' : '2px solid var(--border-primary)',
                      cursor: 'pointer',
                      width: '40px',
                      height: '40px',
                      borderRadius: '6px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      transition: 'all 0.2s'
                    }}
                    title={c.nombre}
                  >
                    <input
                      type="checkbox"
                      checked={coloresSeleccionados.includes(c.id === null ? 'sin_color' : c.id)}
                      onChange={(e) => {
                        const colorValue = c.id === null ? 'sin_color' : c.id;
                        if (e.target.checked) {
                          setColoresSeleccionados([...coloresSeleccionados, colorValue]);
                        } else {
                          setColoresSeleccionados(coloresSeleccionados.filter(color => color !== colorValue));
                        }
                        setPage(1);
                      }}
                      style={{ display: 'none' }}
                    />
                    {coloresSeleccionados.includes(c.id === null ? 'sin_color' : c.id) && <span style={{ fontSize: '20px', lineHeight: 1, display: 'block' }}>✓</span>}
                    {c.id === null && !coloresSeleccionados.includes('sin_color') && <span style={{ fontSize: '20px', lineHeight: 1, display: 'block' }}>🚫</span>}
                  </label>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="results-info">
        <div>
          Mostrando {productos.length} de {totalProductos.toLocaleString('es-AR')} productos
          {debouncedSearch && ` (filtrado por "${debouncedSearch}")`}
        </div>

        <div className="page-size-selector">
          <span>Mostrar:</span>
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setPage(1);
            }}
          >
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={200}>200</option>
            <option value={500}>500</option>
            <option value={9999}>Todos</option>
          </select>
        </div>
      </div>

      <div className="table-container-tesla">
        {loading ? (
          <div className="loading">Cargando...</div>
        ) : (
          <>
            <table className="table-tesla striped">
              <thead className="table-tesla-head">
                <tr>
                  <th style={{ width: '40px', textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      checked={productosSeleccionados.size === productos.length && productos.length > 0}
                      onChange={seleccionarTodos}
                      style={{ cursor: 'pointer' }}
                    />
                  </th>
                  <th onClick={(e) => handleOrdenar('codigo', e)}>
                    Código {getIconoOrden('codigo')} {getNumeroOrden('codigo') && <span>{getNumeroOrden('codigo')}</span>}
                  </th>
                  <th onClick={(e) => handleOrdenar('descripcion', e)}>
                    Descripción {getIconoOrden('descripcion')} {getNumeroOrden('descripcion') && <span>{getNumeroOrden('descripcion')}</span>}
                  </th>
                  <th onClick={(e) => handleOrdenar('marca', e)}>
                    Marca {getIconoOrden('marca')} {getNumeroOrden('marca') && <span>{getNumeroOrden('marca')}</span>}
                  </th>
                  <th onClick={(e) => handleOrdenar('stock', e)}>
                    Stock {getIconoOrden('stock')} {getNumeroOrden('stock') && <span>{getNumeroOrden('stock')}</span>}
                  </th>
                  <th onClick={(e) => handleOrdenar('costo', e)}>
                    Costo {getIconoOrden('costo')} {getNumeroOrden('costo') && <span>{getNumeroOrden('costo')}</span>}
                  </th>
                  <th onClick={(e) => handleOrdenar('precio_clasica', e)}>
                    Precio Clásica {getIconoOrden('precio_clasica')} {getNumeroOrden('precio_clasica') && <span>{getNumeroOrden('precio_clasica')}</span>}
                  </th>

                  {!vistaModoCuotas ? (
                    <>
                      <th onClick={(e) => handleOrdenar('precio_gremio', e)}>
                        Precio Gremio {vistaModoPrecioGremioUSD ? 'USD' : 'ARS'} {getIconoOrden('precio_gremio')} {getNumeroOrden('precio_gremio') && <span>{getNumeroOrden('precio_gremio')}</span>}
                      </th>
                      <th onClick={(e) => handleOrdenar('web_transf', e)}>
                        Web Transf. {getIconoOrden('web_transf')} {getNumeroOrden('web_transf') && <span>{getNumeroOrden('web_transf')}</span>}
                      </th>
                      <th onClick={(e) => handleOrdenar('web_tarjeta', e)}>
                        Web Tarjeta {getIconoOrden('web_tarjeta')} {getNumeroOrden('web_tarjeta') && <span>{getNumeroOrden('web_tarjeta')}</span>}
                      </th>
                    </>
                  ) : (
                    <>
                      <th onClick={(e) => handleOrdenar('precio_3_cuotas', e)}>
                        3 Cuotas {getIconoOrden('precio_3_cuotas')} {getNumeroOrden('precio_3_cuotas') && <span>{getNumeroOrden('precio_3_cuotas')}</span>}
                      </th>
                      <th onClick={(e) => handleOrdenar('precio_6_cuotas', e)}>
                        6 Cuotas {getIconoOrden('precio_6_cuotas')} {getNumeroOrden('precio_6_cuotas') && <span>{getNumeroOrden('precio_6_cuotas')}</span>}
                      </th>
                      <th onClick={(e) => handleOrdenar('precio_9_cuotas', e)}>
                        9 Cuotas {getIconoOrden('precio_9_cuotas')} {getNumeroOrden('precio_9_cuotas') && <span>{getNumeroOrden('precio_9_cuotas')}</span>}
                      </th>
                      <th onClick={(e) => handleOrdenar('precio_12_cuotas', e)}>
                        12 Cuotas {getIconoOrden('precio_12_cuotas')} {getNumeroOrden('precio_12_cuotas') && <span>{getNumeroOrden('precio_12_cuotas')}</span>}
                      </th>
                    </>
                  )}

                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody className="table-tesla-body">
                {productosOrdenados.map((p, rowIndex) => {
                  const isRowActive = modoNavegacion && celdaActiva?.rowIndex === rowIndex;
                  const colorClass = p.color_marcado_tienda ? `row-color-${p.color_marcado_tienda}` : '';
                  return (
                  <tr
                    key={p.item_id}
                    className={`${colorClass} ${p.color_marcado_tienda ? 'row-colored' : ''} ${isRowActive ? 'keyboard-row-active' : ''}`}
                  >
                    <td style={{ textAlign: 'center' }}>
                      <input
                        type="checkbox"
                        checked={productosSeleccionados.has(p.item_id)}
                        onChange={(e) => toggleSeleccion(p.item_id, e.shiftKey)}
                        onClick={(e) => e.stopPropagation()}
                        style={{ cursor: 'pointer' }}
                      />
                    </td>
                    <td>{p.codigo}</td>
                    <td>
                      {p.descripcion}
                      {p.has_catalog && p.catalog_status && (
                        <span
                          style={{
                            padding: '2px 6px',
                            borderRadius: '3px',
                            fontSize: '10px',
                            fontWeight: '600',
                            marginLeft: '6px',
                            backgroundColor:
                              p.catalog_status === 'winning' ? 'var(--success)' :
                              p.catalog_status === 'sharing_first_place' ? 'var(--info)' :
                              p.catalog_status === 'competing' ? 'var(--warning)' :
                              'var(--text-secondary)',
                            color: 'var(--text-inverse)',
                            whiteSpace: 'nowrap'
                          }}
                          title={
                            p.catalog_status === 'winning' && p.catalog_winner_price ?
                              `Ganando a $${p.catalog_winner_price.toFixed(2)}` :
                            p.catalog_status === 'competing' && p.catalog_price_to_win ?
                              `Precio para ganar: $${p.catalog_price_to_win.toFixed(2)}` :
                            p.catalog_status === 'sharing_first_place' && p.catalog_winner_price ?
                              `Empatando a $${p.catalog_winner_price.toFixed(2)}` :
                            ''
                          }
                        >
                          {p.catalog_status === 'winning' ? '🏆' :
                           p.catalog_status === 'sharing_first_place' ? '🤝' :
                           p.catalog_status === 'competing' ? '⚠️' :
                           ''}
                        </span>
                      )}
                    </td>
                    <td>{p.marca}</td>
                    <td>{p.stock}</td>
                    <td>{p.moneda_costo} ${p.costo?.toFixed(2)}</td>
                    <td className={isRowActive && celdaActiva?.colIndex === 0 ? 'keyboard-cell-active' : ''}>
                      {/* Precio solo lectura en Tienda */}
                      <div>
                        <div>
                          {p.precio_lista_ml ? `$${p.precio_lista_ml.toLocaleString('es-AR')}` : 'Sin precio'}
                        </div>
                        {p.markup !== null && p.markup !== undefined && (
                          <div className="markup-display" style={{ color: getMarkupColor(p.markup) }}>
                            {p.markup}%
                          </div>
                        )}
                      </div>
                    </td>

                    {/* Vista Normal: Gremio, Oferta, Web Transf */}
                    {!vistaModoCuotas ? (
                      <>
                    <td className={isRowActive && celdaActiva?.colIndex === 1 ? 'keyboard-cell-active' : ''}>
                      {editandoPrecioGremio === p.item_id && puedeEditarPrecioGremioManual ? (
                        <div className={`inline-edit ${modoEdicionGremio === 'precio' ? 'gremio-edit-precio' : 'gremio-edit-markup'}`}>
                          {/* Indicador de modo */}
                          <div style={{ fontSize: '10px', color: 'var(--info)', marginBottom: '6px', fontWeight: '600' }}>
                            {modoEdicionGremio === 'precio' ? '💰 Modo Precio' : '📊 Modo Markup'}
                          </div>
                          
                          {modoEdicionGremio === 'precio' ? (
                            // MODO PRECIO
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                              <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                                <input
                                  type="text"
                                  inputMode="decimal"
                                  placeholder="Sin IVA"
                                  value={precioGremioTemp.sin_iva}
                                  onChange={(e) => {
                                    const valor = e.target.value;
                                    const valorNum = parseFloat(valor.replace(',', '.'));
                                    setPrecioGremioTemp({
                                      ...precioGremioTemp,
                                      sin_iva: valor,
                                      con_iva: !isNaN(valorNum) 
                                        ? (valorNum * (1 + (p.iva || 21) / 100)).toFixed(2) 
                                        : ''
                                    });
                                  }}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') guardarPrecioGremio(p.item_id);
                                    if (e.key === 'Escape') setEditandoPrecioGremio(null);
                                  }}
                                  style={{ width: '95px', padding: '4px 6px', fontSize: '12px' }}
                                  autoFocus
                                />
                                <span style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>↔</span>
                                <input
                                  type="text"
                                  inputMode="decimal"
                                  placeholder="Con IVA"
                                  value={precioGremioTemp.con_iva}
                                  onChange={(e) => {
                                    const valor = e.target.value;
                                    const valorNum = parseFloat(valor.replace(',', '.'));
                                    setPrecioGremioTemp({
                                      ...precioGremioTemp,
                                      con_iva: valor,
                                      sin_iva: !isNaN(valorNum) 
                                        ? (valorNum / (1 + (p.iva || 21) / 100)).toFixed(2) 
                                        : ''
                                    });
                                  }}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') guardarPrecioGremio(p.item_id);
                                    if (e.key === 'Escape') setEditandoPrecioGremio(null);
                                  }}
                                  style={{ width: '95px', padding: '4px 6px', fontSize: '12px' }}
                                />
                              </div>
                              <small style={{ fontSize: '9px', color: 'var(--text-secondary)', fontStyle: 'italic' }}>
                                Editá uno, el otro se calcula automáticamente
                              </small>
                              
                              {/* Botones */}
                              <div style={{ display: 'flex', gap: '4px', marginTop: '4px' }}>
                                <button 
                                  onClick={() => guardarPrecioGremio(p.item_id)} 
                                  className="btn-tesla success"
                                  title="Guardar (Enter)"
                                  aria-label="Guardar precio gremio"
                                >
                                  ✓
                                </button>
                                <button 
                                  onClick={() => setEditandoPrecioGremio(null)} 
                                  className="btn-tesla danger"
                                  title="Cancelar (Esc)"
                                  aria-label="Cancelar edición"
                                >
                                  ✗
                                </button>
                                {p.tiene_override_gremio && (
                                  <button 
                                    onClick={() => eliminarPrecioGremioManual(p.item_id)} 
                                    className="btn-tesla secondary"
                                    title="Volver al cálculo automático"
                                    aria-label="Volver al cálculo automático"
                                  >
                                    ⟲
                                  </button>
                                )}
                              </div>
                            </div>
                          ) : (
                            // MODO MARKUP
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                              <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                                <label style={{ fontSize: '11px', fontWeight: '500', minWidth: '60px' }}>
                                  Markup %:
                                </label>
                                <input
                                  type="text"
                                  inputMode="decimal"
                                  placeholder="Ej: 15 o -5"
                                  value={precioGremioTemp.markup}
                                  onChange={(e) => setPrecioGremioTemp({ ...precioGremioTemp, markup: e.target.value })}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') guardarPrecioGremio(p.item_id);
                                    if (e.key === 'Escape') setEditandoPrecioGremio(null);
                                  }}
                                  style={{ width: '80px', padding: '4px 6px', fontSize: '12px' }}
                                  autoFocus
                                />
                              </div>
                              
                              {/* Preview de precio calculado */}
                              {precioGremioTemp.markup !== '' && !isNaN(parseFloat(precioGremioTemp.markup.replace(',', '.'))) && (
                                <div style={{ fontSize: '10px', color: 'var(--success)', marginTop: '2px', padding: '4px', background: 'var(--success-light)', borderRadius: '3px' }}>
                                  Preview: ${calcularPrecioDesdeMarkup(p, precioGremioTemp.markup).sin_iva.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} s/IVA
                                </div>
                              )}
                              
                              {/* Botones */}
                              <div style={{ display: 'flex', gap: '4px', marginTop: '4px' }}>
                                <button 
                                  onClick={() => guardarPrecioGremio(p.item_id)} 
                                  className="btn-tesla success"
                                  title="Guardar (Enter)"
                                  aria-label="Guardar precio gremio"
                                >
                                  ✓
                                </button>
                                <button 
                                  onClick={() => setEditandoPrecioGremio(null)} 
                                  className="btn-tesla danger"
                                  title="Cancelar (Esc)"
                                  aria-label="Cancelar edición"
                                >
                                  ✗
                                </button>
                                {p.tiene_override_gremio && (
                                  <button 
                                    onClick={() => eliminarPrecioGremioManual(p.item_id)} 
                                    className="btn-tesla secondary"
                                    title="Volver al cálculo automático"
                                    aria-label="Volver al cálculo automático"
                                  >
                                    ⟲
                                  </button>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div 
                          className="gremio-container"
                          onClick={(e) => puedeEditarPrecioGremioManual && iniciarEdicionPrecioGremio(p, e)}
                          style={{ cursor: puedeEditarPrecioGremioManual ? 'pointer' : 'default' }}
                        >
                          {p.precio_gremio_sin_iva ? (
                            <div className="gremio-info">
                              <div className="gremio-price">
                                {vistaModoPrecioGremioUSD && dolarVenta ? (
                                  <>U$S {(p.precio_gremio_sin_iva / dolarVenta).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</>
                                ) : (
                                  <>$ {p.precio_gremio_sin_iva.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</>
                                )}
                                {p.tiene_override_gremio && <span className="manual-badge" title="Precio manual">✏️</span>}
                              </div>
                              <div className="gremio-price-iva">
                                {vistaModoPrecioGremioUSD && dolarVenta ? (
                                  <>U$S {(p.precio_gremio_con_iva / dolarVenta).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</>
                                ) : (
                                  <>$ {p.precio_gremio_con_iva?.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</>
                                )}
                                <span className="iva-label"> c/IVA</span>
                              </div>
                              {p.markup_gremio !== null && p.markup_gremio !== undefined && (
                                <div className="gremio-markup">
                                  Markup: {p.markup_gremio.toFixed(1)}%
                                </div>
                              )}
                            </div>
                          ) : (
                            <div className="text-muted">
                              Sin markup
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                    <td className={isRowActive && celdaActiva?.colIndex === 2 ? 'keyboard-cell-active' : ''}>
                      <div>
                        {/* Mostrar precios de Tienda Nube si existen */}
                        {(p.tn_price || p.tn_promotional_price) && (
                          <div className="web-transf-info" style={{ marginBottom: '8px', borderBottom: '1px solid var(--border-primary)', paddingBottom: '6px' }}>
                            {p.tn_has_promotion && p.tn_promotional_price ? (
                              <div>
                                <div style={{ fontSize: '12px', fontWeight: '600', color: 'var(--success)', display: 'flex', gap: '8px', alignItems: 'center' }}>
                                  <span>${p.tn_promotional_price.toLocaleString('es-AR')}</span>
                                  <span style={{ fontSize: '11px', color: 'var(--info)', fontWeight: '500' }}>
                                    ${(p.tn_promotional_price * 0.75).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} transf.
                                  </span>
                                </div>
                                {p.tn_price && (
                                  <div style={{
                                    fontSize: '10px',
                                    color: 'var(--text-secondary)',
                                    textDecoration: 'line-through'
                                  }}>
                                    ${p.tn_price.toLocaleString('es-AR')}
                                  </div>
                                )}
                              </div>
                            ) : p.tn_price ? (
                              <div style={{ fontSize: '12px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                                <span>${p.tn_price.toLocaleString('es-AR')}</span>
                                <span style={{ fontSize: '11px', color: 'var(--info)', fontWeight: '500' }}>
                                  ${(p.tn_price * 0.75).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} transf.
                                </span>
                              </div>
                            ) : null}
                          </div>
                        )}

                        {/* Lógica manual de Web Transf */}
                        {editandoWebTransf === p.item_id ? (
                        <div className="web-transf-edit">
                          <label className="web-transf-checkbox">
                            <input
                              type="checkbox"
                              checked={webTransfTemp.participa}
                              onChange={(e) => setWebTransfTemp({...webTransfTemp, participa: e.target.checked})}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  e.preventDefault();
                                  guardarWebTransf(p.item_id);
                                }
                              }}
                              autoFocus
                            />
                            Participa
                          </label>
                         <input
                            type="text"
                            inputMode="decimal"
                            value={webTransfTemp.porcentaje}
                            onChange={(e) => {
                              // Permitir escribir libremente
                              setWebTransfTemp({...webTransfTemp, porcentaje: e.target.value});
                            }}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault();
                                guardarWebTransf(p.item_id);
                              }
                            }}
                            onFocus={(e) => e.target.select()}
                            placeholder="%"
                            style={{ width: '60px', padding: '4px', borderRadius: '4px', border: '1px solid var(--border-primary)' }}
                          />
                          <label className="web-transf-checkbox" style={{ fontSize: '11px', marginLeft: '8px' }}>
                            <input
                              type="checkbox"
                              checked={webTransfTemp.preservar}
                              onChange={(e) => setWebTransfTemp({...webTransfTemp, preservar: e.target.checked})}
                              title="Preservar porcentaje en cambios masivos"
                            />
                            🔒
                          </label>
                          <div className="inline-edit">
                            <button onClick={() => guardarWebTransf(p.item_id)} onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault();
                                guardarWebTransf(p.item_id);
                              }
                            }}>✓</button>
                            <button onClick={() => setEditandoWebTransf(null)} onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault();
                                setEditandoWebTransf(null);
                              }
                            }}>✗</button>
                          </div>
                        </div>
                      ) : (
                        <div className="web-transf-info" onClick={() => iniciarEdicionWebTransf(p)}>
                          {p.participa_web_transferencia ? (
                            <div>
                              <div className="web-transf-markup" style={{ color: getMarkupColor(p.markup_web_real) }}>
                                ✓ {p.markup_web_real ? `${p.markup_web_real.toFixed(2)}%` : '-'}
                                {p.preservar_porcentaje_web && <span style={{ marginLeft: '4px', fontSize: '10px' }}>🔒</span>}
                              </div>
                              <div className="web-transf-porcentaje">
                                (+{p.porcentaje_markup_web}%)
                              </div>
                              {p.precio_web_transferencia && (
                                <div className="web-transf-precio">
                                  ${p.precio_web_transferencia.toLocaleString('es-AR')}
                                </div>
                              )}
                            </div>
                          ) : (
                            <span className="text-muted">-</span>
                          )}
                        </div>
                        )}
                      </div>
                    </td>
                    <td className={isRowActive && celdaActiva?.colIndex === 3 ? 'keyboard-cell-active' : ''}>
                      {p.precio_web_transferencia && markupWebTarjeta > 0 ? (
                        <div className="web-tarjeta-info">
                          <div className="web-tarjeta-precio">
                            ${(p.precio_web_transferencia * (1 + markupWebTarjeta / 100)).toLocaleString('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                          </div>
                          <div className="web-tarjeta-markup">
                            +{markupWebTarjeta}%
                          </div>
                        </div>
                      ) : p.precio_web_transferencia ? (
                        <div className="web-tarjeta-info">
                          <div className="web-tarjeta-precio">
                            ${p.precio_web_transferencia.toLocaleString('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                          </div>
                          <div className="web-tarjeta-markup text-muted">
                            Sin markup
                          </div>
                        </div>
                      ) : (
                        <span className="text-muted">-</span>
                      )}
                    </td>
                    </>
                    ) : (
                      /* Vista Cuotas: 3, 6, 9, 12 cuotas */
                      <>
                        <td className={isRowActive && celdaActiva?.colIndex === 1 ? 'keyboard-cell-active' : ''}>
                          {editandoCuota?.item_id === p.item_id && editandoCuota?.tipo === '3' ? (
                            <div className="inline-edit">
                              <input
                                type="text"
                                inputMode="decimal"
                                value={cuotaTemp}
                                onChange={(e) => setCuotaTemp(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') {
                                    e.preventDefault();
                                    guardarCuota(p.item_id, '3');
                                  }
                                }}
                                onFocus={(e) => e.target.select()}
                                autoFocus
                              />
                              <button onClick={() => guardarCuota(p.item_id, '3')}>✓</button>
                              <button onClick={() => setEditandoCuota(null)}>✗</button>
                            </div>
                          ) : (
                            <div onClick={() => puedeEditar && iniciarEdicionCuota(p, '3')}>
                              <div className={puedeEditar ? 'editable-field' : ''}>
                                {p.precio_3_cuotas ? `$${p.precio_3_cuotas.toLocaleString('es-AR')}` : '-'}
                              </div>
                              {p.markup_3_cuotas !== null && p.markup_3_cuotas !== undefined && (
                                <div className="markup-display" style={{ color: getMarkupColor(p.markup_3_cuotas) }}>
                                  {p.markup_3_cuotas.toFixed(2)}%
                                </div>
                              )}
                            </div>
                          )}
                        </td>
                        <td className={isRowActive && celdaActiva?.colIndex === 2 ? 'keyboard-cell-active' : ''}>
                          {editandoCuota?.item_id === p.item_id && editandoCuota?.tipo === '6' ? (
                            <div className="inline-edit">
                              <input
                                type="text"
                                inputMode="decimal"
                                value={cuotaTemp}
                                onChange={(e) => setCuotaTemp(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') {
                                    e.preventDefault();
                                    guardarCuota(p.item_id, '6');
                                  }
                                }}
                                onFocus={(e) => e.target.select()}
                                autoFocus
                              />
                              <button onClick={() => guardarCuota(p.item_id, '6')}>✓</button>
                              <button onClick={() => setEditandoCuota(null)}>✗</button>
                            </div>
                          ) : (
                            <div onClick={() => puedeEditar && iniciarEdicionCuota(p, '6')}>
                              <div className={puedeEditar ? 'editable-field' : ''}>
                                {p.precio_6_cuotas ? `$${p.precio_6_cuotas.toLocaleString('es-AR')}` : '-'}
                              </div>
                              {p.markup_6_cuotas !== null && p.markup_6_cuotas !== undefined && (
                                <div className="markup-display" style={{ color: getMarkupColor(p.markup_6_cuotas) }}>
                                  {p.markup_6_cuotas.toFixed(2)}%
                                </div>
                              )}
                            </div>
                          )}
                        </td>
                        <td className={isRowActive && celdaActiva?.colIndex === 3 ? 'keyboard-cell-active' : ''}>
                          {editandoCuota?.item_id === p.item_id && editandoCuota?.tipo === '9' ? (
                            <div className="inline-edit">
                              <input
                                type="text"
                                inputMode="decimal"
                                value={cuotaTemp}
                                onChange={(e) => setCuotaTemp(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') {
                                    e.preventDefault();
                                    guardarCuota(p.item_id, '9');
                                  }
                                }}
                                onFocus={(e) => e.target.select()}
                                autoFocus
                              />
                              <button onClick={() => guardarCuota(p.item_id, '9')}>✓</button>
                              <button onClick={() => setEditandoCuota(null)}>✗</button>
                            </div>
                          ) : (
                            <div onClick={() => puedeEditar && iniciarEdicionCuota(p, '9')}>
                              <div className={puedeEditar ? 'editable-field' : ''}>
                                {p.precio_9_cuotas ? `$${p.precio_9_cuotas.toLocaleString('es-AR')}` : '-'}
                              </div>
                              {p.markup_9_cuotas !== null && p.markup_9_cuotas !== undefined && (
                                <div className="markup-display" style={{ color: getMarkupColor(p.markup_9_cuotas) }}>
                                  {p.markup_9_cuotas.toFixed(2)}%
                                </div>
                              )}
                            </div>
                          )}
                        </td>
                        <td className={isRowActive && celdaActiva?.colIndex === 4 ? 'keyboard-cell-active' : ''}>
                          {editandoCuota?.item_id === p.item_id && editandoCuota?.tipo === '12' ? (
                            <div className="inline-edit">
                              <input
                                type="text"
                                inputMode="decimal"
                                value={cuotaTemp}
                                onChange={(e) => setCuotaTemp(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') {
                                    e.preventDefault();
                                    guardarCuota(p.item_id, '12');
                                  }
                                }}
                                onFocus={(e) => e.target.select()}
                                autoFocus
                              />
                              <button onClick={() => guardarCuota(p.item_id, '12')}>✓</button>
                              <button onClick={() => setEditandoCuota(null)}>✗</button>
                            </div>
                          ) : (
                            <div onClick={() => puedeEditar && iniciarEdicionCuota(p, '12')}>
                              <div className={puedeEditar ? 'editable-field' : ''}>
                                {p.precio_12_cuotas ? `$${p.precio_12_cuotas.toLocaleString('es-AR')}` : '-'}
                              </div>
                              {p.markup_12_cuotas !== null && p.markup_12_cuotas !== undefined && (
                                <div className="markup-display" style={{ color: getMarkupColor(p.markup_12_cuotas) }}>
                                  {p.markup_12_cuotas.toFixed(2)}%
                                </div>
                              )}
                            </div>
                          )}
                        </td>
                      </>
                    )}

                    <td className="table-actions">
                      <div className="table-actions-group">
                        <button
                          onClick={() => {
                            setProductoInfo(p.item_id);
                            setMostrarModalInfo(true);
                          }}
                          className="btn-tesla outline-subtle-primary icon-only sm"
                          title="Información del producto"
                          aria-label="Información del producto"
                        >
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>
                        </button>
                        {puedeEditar && (
                          <button
                            onClick={() => setProductoSeleccionado(p)}
                            className="btn-tesla outline-subtle-primary icon-only sm"
                            title="Ver detalle"
                            aria-label="Ver detalle del producto"
                          >
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
                          </button>
                        )}
                        <button
                          onClick={() => verAuditoria(p.item_id)}
                          className="btn-tesla outline-subtle-primary icon-only sm"
                          title="Ver historial de cambios"
                          aria-label="Ver historial de cambios"
                        >
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/></svg>
                        </button>
                        {puedeEditar && (
                          <button
                            onClick={() => abrirModalConfig(p)}
                            className="btn-tesla outline-subtle-primary icon-only sm"
                            title="Configuración de cuotas"
                            aria-label="Configuración de cuotas"
                          >
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 0 0 .12-.61l-1.92-3.32a.488.488 0 0 0-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94L14.4 2.81c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.49.49 0 0 0-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>
                          </button>
                        )}
                        {puedeMarcarColor && (
                        <div style={{ position: 'relative', display: 'inline-block' }}>
                          <button
                            onClick={() => setColorDropdownAbierto(colorDropdownAbierto === p.item_id ? null : p.item_id)}
                            className="btn-tesla outline-subtle-primary icon-only sm"
                            title="Marcar con color"
                            aria-label="Marcar producto con color"
                          >
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3c-4.97 0-9 4.03-9 9s4.03 9 9 9c.83 0 1.5-.67 1.5-1.5 0-.39-.15-.74-.39-1.01-.23-.26-.38-.61-.38-.99 0-.83.67-1.5 1.5-1.5H16c2.76 0 5-2.24 5-5 0-4.42-4.03-8-9-8zm-5.5 9c-.83 0-1.5-.67-1.5-1.5S5.67 9 6.5 9 8 9.67 8 10.5 7.33 12 6.5 12zm3-4C8.67 8 8 7.33 8 6.5S8.67 5 9.5 5s1.5.67 1.5 1.5S10.33 8 9.5 8zm5 0c-.83 0-1.5-.67-1.5-1.5S13.67 5 14.5 5s1.5.67 1.5 1.5S15.33 8 14.5 8zm3 4c-.83 0-1.5-.67-1.5-1.5S16.67 9 17.5 9s1.5.67 1.5 1.5-.67 1.5-1.5 1.5z"/></svg>
                          </button>
                          {colorDropdownAbierto === p.item_id && (
                            <div className="color-dropdown">
                              {COLORES_DISPONIBLES.map(c => (
                                <button
                                  key={c.id || 'sin-color'}
                                  className="color-option"
                                  style={{
                                    backgroundColor: c.color,
                                    color: c.colorTexto,
                                    border: c.id === p.color_marcado_tienda ? '2px solid var(--text-primary)' : '1px solid var(--border-secondary)'
                                  }}
                                   onClick={() => { cambiarColorProducto(p.item_id, c.id); setColorDropdownAbierto(null); }}
                                  title={c.nombre}
                                  aria-label={`Marcar producto como ${c.nombre}`}
                                >
                                  {c.nombre}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                        )}
                        {['SUPERADMIN', 'ADMIN'].includes(user?.rol) && (
                          <button
                            onClick={() => abrirModalBan(p)}
                            className="btn-tesla outline-subtle-danger icon-only sm"
                            title="Agregar a banlist"
                          >
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>

{auditoriaVisible && (
              <div className="modal-overlay">
                <div className="modal-content modal-auditoria">
                  <div className="modal-header">
                    <h2>📋 Historial de Cambios</h2>
                    <button onClick={() => setAuditoriaVisible(false)} className="modal-close">
                      Cerrar
                    </button>
                  </div>

                  {auditoriaData.length === 0 ? (
                    <p className="text-muted">No hay cambios registrados</p>
                  ) : (
                    <table className="table">
                      <thead className="table-head">
                        <tr>
                          <th>Fecha</th>
                          <th>Usuario</th>
                          <th>Tipo de Cambio</th>
                          <th>Valores Anteriores</th>
                          <th>Valores Nuevos</th>
                        </tr>
                      </thead>
                      <tbody className="table-tesla-body">
                        {auditoriaData.map(item => {
                          const formatearTipoAccion = (tipo) => {
                            const tipos = {
                              'modificar_precio_clasica': '💰 Precio Clásica',
                              'modificar_precio_web': '🌐 Precio Web',
                              'activar_rebate': '✅ Activar Rebate',
                              'desactivar_rebate': '❌ Desactivar Rebate',
                              'modificar_porcentaje_rebate': '📊 % Rebate',
                              'marcar_out_of_cards': '🚫 Out of Cards ON',
                              'desmarcar_out_of_cards': '✅ Out of Cards OFF',
                              'activar_web_transferencia': '✅ Web Transf. ON',
                              'desactivar_web_transferencia': '❌ Web Transf. OFF',
                              'modificacion_masiva': '📦 Modificación Masiva'
                            };
                            return tipos[tipo] || tipo;
                          };

                          const formatearValores = (valores) => {
                            if (!valores) return '-';
                            return Object.entries(valores).map(([key, value]) => (
                              <div key={key}>
                                <strong>{key}:</strong> {typeof value === 'number' ? value.toFixed(2) : String(value)}
                              </div>
                            ));
                          };

                          return (
                            <tr key={item.id}>
                              <td>{formatearFechaGMT3(item.fecha_cambio)}</td>
                              <td>
                                <div>
                                  <strong>{item.usuario_nombre}</strong>
                                  <br />
                                  <small className="text-muted">{item.usuario_email}</small>
                                </div>
                              </td>
                              <td>{formatearTipoAccion(item.tipo_accion)}</td>
                              <td style={{ fontSize: '0.9em' }}>{formatearValores(item.valores_anteriores)}</td>
                              <td style={{ fontSize: '0.9em' }}>{formatearValores(item.valores_nuevos)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            )}

            <div className="pagination">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="btn-tesla outline-subtle-primary"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" style={{ marginRight: '4px' }}>
                  <path d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z"/>
                </svg>
                Anterior
              </button>
              <span className="pagination-info">Página {page} {totalProductos > 0 && `(1 - ${pageSize} de ${totalProductos.toLocaleString('es-AR')})`}</span>
              <button
                onClick={() => setPage(p => p + 1)}
                disabled={productos.length < pageSize}
                className="btn-tesla outline-subtle-primary"
              >
                Siguiente
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" style={{ marginLeft: '4px' }}>
                  <path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/>
                </svg>
              </button>
            </div>
          </>
        )}
      </div>

      <PricingModalTesla
        isOpen={!!productoSeleccionado}
        producto={productoSeleccionado}
        onClose={() => setProductoSeleccionado(null)}
        onSave={() => {
          setProductoSeleccionado(null);
          cargarProductos();
          cargarStats();
        }}
      />

      {mostrarModalInfo && (
        <ModalInfoProducto
          isOpen={mostrarModalInfo}
          onClose={() => {
            setMostrarModalInfo(false);
            setProductoInfo(null);
          }}
          itemId={productoInfo}
        />
      )}

      {mostrarCalcularWebModal && (
        <CalcularWebModal
          onClose={() => setMostrarCalcularWebModal(false)}
          onSuccess={() => {
            cargarProductos();
            cargarStats();
          }}
          filtrosActivos={{
            search: debouncedSearch,
            con_stock: filtroStock === 'con_stock' ? true : filtroStock === 'sin_stock' ? false : null,
            con_precio: filtroPrecio === 'con_precio' ? true : filtroPrecio === 'sin_precio' ? false : null,
            marcas: marcasSeleccionadas,
            subcategorias: subcategoriasSeleccionadas,
            pmsSeleccionados,
            filtroRebate,
            filtroOferta,
            filtroWebTransfFiltro,
            filtroMarkupClasica,
            filtroMarkupRebate,
            filtroMarkupOferta,
            filtroMarkupWebTransf,
            filtroOutOfCards,
            filtroMLA,
            filtroEstadoMLA,
            filtroNuevos,
            coloresSeleccionados,
            audit_usuarios: filtrosAuditoria.usuarios,
            audit_tipos_accion: filtrosAuditoria.tipos_accion,
            audit_fecha_desde: filtrosAuditoria.fecha_desde,
            audit_fecha_hasta: filtrosAuditoria.fecha_hasta
          }}
          showToast={showToast}
        />
      )}

      {mostrarExportModal && (
        <ExportModal
          onClose={() => setMostrarExportModal(false)}
          filtrosActivos={{
            search: debouncedSearch,
            con_stock: filtroStock === 'con_stock' ? true : filtroStock === 'sin_stock' ? false : null,
            con_precio: filtroPrecio === 'con_precio' ? true : filtroPrecio === 'sin_precio' ? false : null,
            marcas: marcasSeleccionadas,
            subcategorias: subcategoriasSeleccionadas,
            pmsSeleccionados,
            filtroRebate,
            filtroOferta,
            filtroWebTransfFiltro,
            filtroTiendaNube,
            filtroMarkupClasica,
            filtroMarkupRebate,
            filtroMarkupOferta,
            filtroMarkupWebTransf,
            filtroOutOfCards,
            filtroMLA,
            filtroEstadoMLA,
            filtroNuevos,
            coloresSeleccionados,
            audit_usuarios: filtrosAuditoria.usuarios,
            audit_tipos_accion: filtrosAuditoria.tipos_accion,
            audit_fecha_desde: filtrosAuditoria.fecha_desde,
            audit_fecha_hasta: filtrosAuditoria.fecha_hasta
          }}
          showToast={showToast}
          esTienda={true}
        />
      )}

      {/* Modal de confirmación de ban */}
      {mostrarModalBan && productoBan && (
        <div className="modal-ban-overlay">
          <div className="modal-ban-content">
            <h2 className="modal-ban-title">⚠️ Confirmar Ban</h2>

            <div className="modal-ban-info">
              <p><strong>Producto:</strong> {productoBan.codigo}</p>
              <p><strong>Descripción:</strong> {productoBan.descripcion}</p>
              <p><strong>Item ID:</strong> {productoBan.item_id}</p>
              {productoBan.ean && <p><strong>EAN:</strong> {productoBan.ean}</p>}
            </div>

            <div className="modal-ban-warning">
              <p>Para confirmar, escribe la siguiente palabra:</p>
              <p className="modal-ban-word">{palabraObjetivo}</p>
            </div>

            <div className="modal-ban-field">
              <label>Palabra de verificación:</label>
              <input
                type="text"
                value={palabraVerificacion}
                onChange={(e) => setPalabraVerificacion(e.target.value)}
                placeholder="Escribe la palabra aquí"
                className="modal-ban-input"
                autoFocus
              />
            </div>

            <div className="modal-ban-field">
              <label>Motivo (opcional):</label>
              <textarea
                value={motivoBan}
                onChange={(e) => setMotivoBan(e.target.value)}
                placeholder="Razón por la cual se banea este producto"
                className="modal-ban-textarea"
              />
            </div>

            <div className="modal-ban-actions">
              <button
                onClick={() => {
                  setMostrarModalBan(false);
                  setProductoBan(null);
                  setPalabraVerificacion('');
                  setPalabraObjetivo('');
                  setMotivoBan('');
                }}
                className="modal-ban-btn-cancel"
              >
                Cancelar
              </button>
              <button
                onClick={confirmarBan}
                className="modal-ban-btn-confirm"
              >
                Confirmar Ban
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Barra de acciones flotante para selección múltiple */}
      {productosSeleccionados.size > 0 && (
        <div className="selection-bar">
          <span className="selection-bar-count">
            {productosSeleccionados.size} producto{productosSeleccionados.size !== 1 ? 's' : ''} seleccionado{productosSeleccionados.size !== 1 ? 's' : ''}
          </span>
          {puedeMarcarColorLote && (
          <div className="selection-bar-colors">
            {COLORES_DISPONIBLES.map(c => (
              <button
                key={c.id}
                onClick={() => pintarLote(c.id)}
                className="selection-bar-color-btn"
                style={{ backgroundColor: c.color || 'var(--bg-secondary)' }}
                title={c.nombre}
                aria-label={`Pintar lote como ${c.nombre}`}
              >
                {!c.id && '✕'}
              </button>
            ))}
          </div>
          )}
          <button
            onClick={limpiarSeleccion}
            className="selection-bar-btn selection-bar-btn-cancel"
            aria-label="Cancelar selección"
          >
            Cancelar
          </button>
        </div>
      )}

      {/* Modal de configuración individual */}
      {mostrarModalConfig && productoConfig && (
        <div className="shortcuts-modal-overlay" onClick={() => setMostrarModalConfig(false)}>
          <div className="shortcuts-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '500px' }}>
            <div className="shortcuts-header">
              <h2>⚙️ Configuración de Cuotas</h2>
              <button onClick={() => setMostrarModalConfig(false)} className="close-btn">✕</button>
            </div>
            <div style={{ padding: '20px' }}>
              <h3 style={{ marginBottom: '10px' }}>{productoConfig.descripcion}</h3>
              <p style={{ color: 'var(--text-secondary)', marginBottom: '20px', fontSize: '14px' }}>
                Código: {productoConfig.codigo} | Marca: {productoConfig.marca}
              </p>

              <div style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', fontWeight: 'bold', marginBottom: '8px' }}>
                  Recalcular cuotas automáticamente:
                </label>
                <select
                  value={configTemp.recalcular_cuotas_auto === null ? 'null' : configTemp.recalcular_cuotas_auto.toString()}
                  onChange={(e) => setConfigTemp({ ...configTemp, recalcular_cuotas_auto: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid var(--border-primary)'
                  }}
                >
                  <option value="null">Usar configuración global ({recalcularCuotasAuto ? 'Sí' : 'No'})</option>
                  <option value="true">Siempre recalcular</option>
                  <option value="false">Nunca recalcular</option>
                </select>
              </div>

              <div style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', fontWeight: 'bold', marginBottom: '8px' }}>
                  Markup adicional para cuotas (%):
                </label>
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  value={configTemp.markup_adicional_cuotas_custom}
                  onChange={(e) => setConfigTemp({ ...configTemp, markup_adicional_cuotas_custom: e.target.value })}
                  onFocus={(e) => e.target.select()}
                  placeholder="Dejar vacío para usar configuración global"
                  style={{
                    width: '100%',
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid var(--border-primary)'
                  }}
                />
                <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '5px' }}>
                  Dejar vacío para usar la configuración global
                </p>
              </div>

              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                <button
                  onClick={() => setMostrarModalConfig(false)}
                  style={{
                    padding: '10px 20px',
                    borderRadius: '4px',
                    border: '1px solid var(--border-primary)',
                    backgroundColor: 'var(--bg-primary)',
                    cursor: 'pointer'
                  }}
                >
                  Cancelar
                </button>
                <button
                  onClick={guardarConfigIndividual}
                  style={{
                    padding: '10px 20px',
                    borderRadius: '4px',
                    border: 'none',
                    backgroundColor: 'var(--brand-primary)',
                    color: 'var(--text-inverse)',
                    cursor: 'pointer',
                    fontWeight: 'bold'
                  }}
                >
                  Guardar
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal de ayuda de shortcuts */}
      {mostrarShortcutsHelp && (
        <div className="shortcuts-modal-overlay" onClick={() => setMostrarShortcutsHelp(false)}>
          <div className="shortcuts-modal" onClick={(e) => e.stopPropagation()}>
            <div className="shortcuts-header">
              <h2>⌨️ Atajos de Teclado</h2>
              <button onClick={() => setMostrarShortcutsHelp(false)} className="close-btn">✕</button>
            </div>
            <div className="shortcuts-content">
              <div className="shortcuts-section">
                <h3>Navegación en Tabla</h3>
                <div className="shortcut-item">
                  <kbd>Enter</kbd>
                  <span>Activar modo navegación</span>
                </div>
                <div className="shortcut-item">
                  <kbd>↑</kbd> <kbd>↓</kbd> <kbd>←</kbd> <kbd>→</kbd>
                  <span>Navegar por celdas (una a la vez)</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Shift</kbd> + <kbd>↑</kbd>
                  <span>Ir al inicio de la tabla</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Shift</kbd> + <kbd>↓</kbd>
                  <span>Ir al final de la tabla</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Re Pág</kbd> (PageUp)
                  <span>Subir 10 filas</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Av Pág</kbd> (PageDown)
                  <span>Bajar 10 filas</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Home</kbd>
                  <span>Ir a primera columna</span>
                </div>
                <div className="shortcut-item">
                  <kbd>End</kbd>
                  <span>Ir a última columna</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Enter</kbd> o <kbd>Espacio</kbd>
                  <span>Editar celda activa</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Tab</kbd> (en edición)
                  <span>Navegar entre campos del formulario</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Esc</kbd>
                  <span>Salir de edición (mantiene navegación)</span>
                </div>
              </div>

              <div className="shortcuts-section">
                <h3>Acciones Rápidas (en fila activa)</h3>
                <div className="shortcut-item">
                  <kbd>Ctrl</kbd>+<kbd>I</kbd>
                  <span>Ver información detallada del producto</span>
                </div>
                <div className="shortcut-item">
                  <kbd>0</kbd>-<kbd>7</kbd>
                  <span>Asignar color (0=Sin color, 1=Rojo, 2=Naranja, 3=Amarillo, 4=Verde, 5=Azul, 6=Púrpura, 7=Gris)</span>
                </div>
                <div className="shortcut-item">
                  <kbd>R</kbd>
                  <span>Toggle Rebate ON/OFF</span>
                </div>
                <div className="shortcut-item">
                  <kbd>W</kbd>
                  <span>Toggle Web Transferencia ON/OFF</span>
                </div>
                <div className="shortcut-item">
                  <kbd>O</kbd>
                  <span>Toggle Out of Cards</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Ctrl</kbd>+<kbd>F1</kbd> o <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>1</kbd>
                  <span>Copiar código del producto</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Ctrl</kbd>+<kbd>F2</kbd> o <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>2</kbd>
                  <span>Copiar primer enlace ML</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Ctrl</kbd>+<kbd>F3</kbd> o <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>3</kbd>
                  <span>Copiar segundo enlace ML</span>
                </div>
              </div>

              <div className="shortcuts-section">
                <h3>Filtros</h3>
                <div className="shortcut-item">
                  <kbd>Ctrl</kbd> + <kbd>F</kbd>
                  <span>Buscar productos</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>M</kbd>
                  <span>Toggle filtro Marcas</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>S</kbd>
                  <span>Toggle filtro Subcategorías</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>P</kbd>
                  <span>Toggle filtro PMs</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>C</kbd>
                  <span>Toggle filtro Colores</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>A</kbd>
                  <span>Toggle filtro Auditoría</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>F</kbd>
                  <span>Toggle filtros avanzados</span>
                </div>
              </div>

              <div className="shortcuts-section">
                <h3>🔍 Operadores de Búsqueda</h3>
                <div className="shortcut-item">
                  <kbd>ean:123456</kbd>
                  <span>Búsqueda exacta por EAN</span>
                </div>
                <div className="shortcut-item">
                  <kbd>codigo:ABC123</kbd>
                  <span>Búsqueda exacta por código</span>
                </div>
                <div className="shortcut-item">
                  <kbd>marca:Samsung</kbd>
                  <span>Búsqueda exacta por marca</span>
                </div>
                <div className="shortcut-item">
                  <kbd>desc:texto</kbd>
                  <span>Búsqueda en descripción (contiene)</span>
                </div>
                <div className="shortcut-item">
                  <kbd>*123</kbd>
                  <span>Termina en "123" (en cualquier campo)</span>
                </div>
                <div className="shortcut-item">
                  <kbd>123*</kbd>
                  <span>Comienza con "123" (en cualquier campo)</span>
                </div>
                <div className="shortcut-item">
                  <kbd>texto</kbd>
                  <span>Búsqueda normal (contiene en desc, marca o código)</span>
                </div>
              </div>

              <div className="shortcuts-section">
                <h3>Acciones Globales</h3>
                <div className="shortcut-item">
                  <kbd>Ctrl</kbd> + <kbd>E</kbd>
                  <span>Abrir modal de exportar</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Ctrl</kbd> + <kbd>K</kbd>
                  <span>Calcular Web Transferencia masivo</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>V</kbd>
                  <span>Toggle Vista Normal / Vista Cuotas</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>R</kbd>
                  <span>Toggle Auto-recalcular cuotas</span>
                </div>
                <div className="shortcut-item">
                  <kbd>?</kbd>
                  <span>Mostrar/ocultar esta ayuda</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Indicador de modo navegación */}
      {modoNavegacion && (
        <div className="navigation-indicator">
          ⌨️ Modo Navegación Activo - Presiona <kbd>Esc</kbd> para salir o <kbd>?</kbd> para ayuda
        </div>
      )}

      {/* Toast notification */}
      {toast && (
        <div className={`toast ${toast.type === 'error' ? 'error' : ''}`}>
          {toast.message}
        </div>
      )}
      </>
      )}
    </div>
      );
    }
