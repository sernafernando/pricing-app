import { useState, useEffect, useMemo, useRef } from 'react';
import PricingModalTesla from '../components/PricingModalTesla';
import api from '../services/api';
import { useAuthStore } from '../store/authStore';
import { usePermisos } from '../contexts/PermisosContext';
import ExportModal from '../components/ExportModal';
import CalcularWebModal from '../components/CalcularWebModal';
import CalcularPVPModal from '../components/CalcularPVPModal';
import ModalInfoProducto from '../components/ModalInfoProducto';
import StatCard from '../components/StatCard';
import SearchInput from '../components/SearchInput';
import { useToast } from '../hooks/useToast';
import Toast from '../components/Toast';
import { usePrearmadasStats } from '../hooks/usePrearmadasStats';
import PrearmadaBadge from '../components/PrearmadaBadge';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useExpandedSet } from '../hooks/useExpandedSet';
import ProductoMLAsPanel from '../components/promociones/ProductoMLAsPanel';
import styles from '../components/promociones/promociones.module.css';
import PromoFilterBar from '../components/promociones/PromoFilterBar';
import '../styles/tabla-productos-shared.css';
import './Productos.css';

import { COLORES_DISPONIBLES } from '../utils/productosConstants';
import { PROMO_TYPES } from '../constants/promoTypes';
import { formatearFechaGMT3, getIconoOrden as getIconoOrdenFn, getNumeroOrden as getNumeroOrdenFn } from '../utils/productosFormat';
import { useProductosOffsets } from '../hooks/useProductosOffsets';
import { useProductosAuditoria } from '../hooks/useProductosAuditoria';
import { useProductosSeleccion } from '../hooks/useProductosSeleccion';
import { useProductosToggles } from '../hooks/useProductosToggles';
import { useProductosInlineEditing } from '../hooks/useProductosInlineEditing';

import { useProductosFilters } from '../hooks/useProductosFilters';

import { useProductosData } from '../hooks/useProductosData';
import { useProductosKeyboard } from '../hooks/useProductosKeyboard';

export default function Productos() {
  const [productoSeleccionado, setProductoSeleccionado] = useState(null);
  const [mostrarExportModal, setMostrarExportModal] = useState(false);
  const [mostrarCalcularWebModal, setMostrarCalcularWebModal] = useState(false);
  const [mostrarCalcularPVPModal, setMostrarCalcularPVPModal] = useState(false);
  const [busquedaMarca, setBusquedaMarca] = useState('');
  const [busquedaSubcategoria, setBusquedaSubcategoria] = useState('');



  // Selección múltiple

  // Modal de configuración individual
  const [mostrarModalConfig, setMostrarModalConfig] = useState(false);
  const [productoConfig, setProductoConfig] = useState(null);
  const [configTemp, setConfigTemp] = useState({
    recalcular_cuotas_auto: null,
    markup_adicional_cuotas_custom: null,
    markup_adicional_cuotas_pvp_custom: null
  });
  // Modal de información
  const [mostrarModalInfo, setMostrarModalInfo] = useState(false);
  const [productoInfo, setProductoInfo] = useState(null);


  // Toast notification
  const { toast, showToast, hideToast } = useToast();
  const {
    searchInput, setSearchInput, debouncedSearch,
    filtroStock, setFiltroStock, filtroPrecio, setFiltroPrecio,
    page, setPage, pageSize, setPageSize,
    marcasSeleccionadas, setMarcasSeleccionadas,
    subcategoriasSeleccionadas, setSubcategoriasSeleccionadas,
    pmsSeleccionados, setPmsSeleccionados,
    filtroRebate, setFiltroRebate, filtroOferta, setFiltroOferta,
    filtroWebTransf, setFiltroWebTransf, filtroTiendaNube, setFiltroTiendaNube,
    filtroMarkupClasica, setFiltroMarkupClasica,
    filtroMarkupRebate, setFiltroMarkupRebate,
    filtroMarkupOferta, setFiltroMarkupOferta,
    filtroMarkupWebTransf, setFiltroMarkupWebTransf,
    filtroOutOfCards, setFiltroOutOfCards,
    filtroMLA, setFiltroMLA, filtroEstadoMLA, setFiltroEstadoMLA,
    filtroNuevos, setFiltroNuevos, filtroTiendaOficial, setFiltroTiendaOficial,
    coloresSeleccionados, setColoresSeleccionados,
    filtroPromoTipos, setFiltroPromoTipos, filtroPromoEstado, setFiltroPromoEstado,
    filtrosAuditoria, setFiltrosAuditoria,
    panelFiltroActivo, setPanelFiltroActivo,
    mostrarFiltrosAvanzados, setMostrarFiltrosAvanzados,
    ordenColumnas,
    handleOrdenar, limpiarTodosFiltros, limpiarFiltros, aplicarFiltroStat,
    construirFiltrosParams,
  } = useProductosFilters();
  const {
    productos,
    setProductos,
    loading,
    stats,
    totalProductos,
    marcas,
    subcategorias,
    pms,
    marcasPorPM,
    subcategoriasPorPM,
    cargarProductos,
    cargarStats,
  } = useProductosData({
    construirFiltrosParams,
    page,
    pageSize,
    ordenColumnas,
    filters: {
      debouncedSearch,
      filtroStock, filtroPrecio,
      marcasSeleccionadas, subcategoriasSeleccionadas,
      filtroRebate, filtroOferta, filtroWebTransf, filtroTiendaNube,
      filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf,
      filtroOutOfCards, filtroMLA, filtroEstadoMLA, filtroNuevos, filtroTiendaOficial,
      coloresSeleccionados, pmsSeleccionados, filtrosAuditoria,
      filtroPromoTipos, filtroPromoEstado,
    },
    showToast,
  });

  // Modal de ban
  const [mostrarModalBan, setMostrarModalBan] = useState(false);
  const [productoBan, setProductoBan] = useState(null);
  const [palabraVerificacion, setPalabraVerificacion] = useState('');
  const [palabraObjetivo, setPalabraObjetivo] = useState('');
  const [motivoBan, setMotivoBan] = useState('');


  const user = useAuthStore((state) => state.user);
  const { tienePermiso } = usePermisos();
  const { calcularMarkupConOffset, getMarkupColor } = useProductosOffsets();
  const { auditoriaVisible, setAuditoriaVisible, auditoriaData, usuarios, tiposAccion, verAuditoria } = useProductosAuditoria({ showToast });

  // Permisos granulares de edición
  const puedeEditarPrecioClasica = tienePermiso('productos.editar_precio_clasica');
  const puedeEditarCuotas = tienePermiso('productos.editar_precio_cuotas');
  const puedeToggleRebate = tienePermiso('productos.toggle_rebate');
  const puedeToggleWebTransf = tienePermiso('productos.toggle_web_transferencia');
  const puedeMarcarColor = tienePermiso('productos.marcar_color');
  const puedeMarcarColorLote = tienePermiso('productos.marcar_color_lote');
  const puedeCalcularWebMasivo = tienePermiso('productos.calcular_web_masivo');
  const puedeCalcularPVPMasivo = tienePermiso('productos.calcular_pvp_masivo');
  const puedeToggleOutOfCards = tienePermiso('productos.toggle_out_of_cards');

  // Legacy: puedeEditar es true si tiene al menos un permiso de edición
  const puedeEditar = puedeEditarPrecioClasica || puedeEditarCuotas || puedeToggleRebate || puedeToggleWebTransf;

  const prearmadasItemIds = useMemo(
    () => productos.slice(0, 100).map((p) => p.item_id),
    [productos],
  );
  const { statsById: prearmadasStats } = usePrearmadasStats(prearmadasItemIds);



  const { productosSeleccionados, colorDropdownAbierto, setColorDropdownAbierto, toggleSeleccion, seleccionarTodos, limpiarSeleccion, pintarLote, cambiarColorProducto, cambiarColorRapido } = useProductosSeleccion({ productos, setProductos, cargarStats, showToast });
  const { editandoRebate, setEditandoRebate, rebateTemp, setRebateTemp, editandoWebTransf, setEditandoWebTransf, webTransfTemp, setWebTransfTemp, iniciarEdicionRebate, guardarRebate, iniciarEdicionWebTransf, guardarWebTransf, toggleRebateRapido, toggleWebTransfRapido, toggleOutOfCardsRapido } = useProductosToggles({ setProductos, cargarStats, showToast });



  // Copiar enlaces al clipboard con Ctrl+F1/F2/F3 o Ctrl+Shift+1/2/3 (alternativa para Linux)
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


  const getIconoOrden = (columna) => getIconoOrdenFn(columna, ordenColumnas);
  const getNumeroOrden = (columna) => getNumeroOrdenFn(columna, ordenColumnas);

  // Los productos ya vienen ordenados desde el backend
  const productosOrdenados = productos;

  const mlaExpanded = useExpandedSet();
  const mlasCacheRef = useRef(new Map());
  const promosCacheRef = useRef(new Map());

  // Stable key derived from item_ids, not the array reference: productosOrdenados
  // gets a new array identity on every inline edit (setProductos(prods => prods.map(...))),
  // which would otherwise clear the caches and force a refetch on every re-expand.
  const productIdsKey = useMemo(() => productosOrdenados.map(p => p.item_id).join(','), [productosOrdenados]);
  useEffect(() => {
    mlasCacheRef.current.clear();
    promosCacheRef.current.clear();
  }, [productIdsKey]);

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
      await api.post(
        '/producto-banlist',
        {
          item_ids: productoBan.item_id ? String(productoBan.item_id) : null,
          eans: productoBan.ean || null,
          motivo: motivoBan || 'Sin motivo especificado'
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

  // Modal de configuración individual
  const abrirModalConfig = (producto) => {
    setProductoConfig(producto);
    setConfigTemp({
      recalcular_cuotas_auto: producto.recalcular_cuotas_auto,
      markup_adicional_cuotas_custom: producto.markup_adicional_cuotas_custom || '',
      markup_adicional_cuotas_pvp_custom: producto.markup_adicional_cuotas_pvp_custom || ''
    });
    setMostrarModalConfig(true);
  };

  const guardarConfigIndividual = async () => {
    try {
      // Preparar datos: null significa usar global
      const data = {
        recalcular_cuotas_auto: configTemp.recalcular_cuotas_auto === 'null' ? null :
                                configTemp.recalcular_cuotas_auto === 'true' ? true :
                                configTemp.recalcular_cuotas_auto === 'false' ? false : null,
        markup_adicional_cuotas_custom: configTemp.markup_adicional_cuotas_custom === '' ? null :
                                        parseFloat(configTemp.markup_adicional_cuotas_custom),
        markup_adicional_cuotas_pvp_custom: configTemp.markup_adicional_cuotas_pvp_custom === '' ? null :
                                            parseFloat(configTemp.markup_adicional_cuotas_pvp_custom)
      };

      const response = await api.patch(
        `/productos/${productoConfig.item_id}/config-cuotas`,
        data
      );

      // Actualizar producto en el estado
      setProductos(prods => prods.map(p =>
        p.item_id === productoConfig.item_id
          ? {
              ...p,
              recalcular_cuotas_auto: response.data.recalcular_cuotas_auto,
              markup_adicional_cuotas_custom: response.data.markup_adicional_cuotas_custom,
              markup_adicional_cuotas_pvp_custom: response.data.markup_adicional_cuotas_pvp_custom
            }
          : p
      ));

      setMostrarModalConfig(false);
      showToast('Configuración actualizada correctamente', 'success');
      
      // Opcional: recalcular cuotas automáticamente después de guardar
      if (modoVista === 'pvp' && productoConfig.precio_pvp) {
        await recalcularCuotasDesdeClasica(productoConfig, 'pvp');
      } else if (modoVista === 'cuotas' && productoConfig.precio_lista_ml) {
        await recalcularCuotasDesdeClasica(productoConfig, 'web');
      }
    } catch (error) {
      showToast('Error al guardar configuración: ' + (error.response?.data?.detail || error.message), 'error');
    }
  };

  const {
    editandoPrecio, setEditandoPrecio, precioTemp, setPrecioTemp,
    editandoCuota, setEditandoCuota, cuotaTemp, setCuotaTemp,
    modoVista, setModoVista, recalcularCuotasAuto, setRecalcularCuotasAuto,
    mostrarModalMarkupNegativo, setMostrarModalMarkupNegativo,
    datosGuardadoPendiente, setDatosGuardadoPendiente,
    recalculandoCuotasMasivo,
    iniciarEdicion, iniciarEdicionCuota,
    guardarCuota, guardarPrecio, recalcularCuotasDesdeClasica, recalcularCuotasMasivo,
    confirmarGuardadoMarkupNegativo,
  } = useProductosInlineEditing({
    productos,
    setProductos,
    cargarProductos,
    cargarStats,
    showToast,
    filtros: {
      debouncedSearch,
      filtroStock,
      filtroPrecio,
      marcasSeleccionadas,
      subcategoriasSeleccionadas,
      pmsSeleccionados,
      filtroRebate,
      filtroOferta,
      filtroWebTransf,
      filtroTiendaNube,
      filtroMarkupClasica,
      filtroMarkupRebate,
      filtroMarkupOferta,
      filtroMarkupWebTransf,
      filtroOutOfCards,
      coloresSeleccionados,
      filtroMLA,
      filtroEstadoMLA,
      filtroNuevos,
    },
  });

  const TOTAL_COLS =
    8 + // checkbox, codigo, descripcion, marca, stock, costo, precio_clasica, acciones
    (modoVista === 'normal' ? 3 : 4) +
    1; // leading expand-toggle column

  const {
    celdaActiva, setCeldaActiva,
    modoNavegacion,
    mostrarShortcutsHelp, setMostrarShortcutsHelp,
  } = useProductosKeyboard({
    data: { productos, setProductos, cargarStats },
    editing: {
      editandoPrecio, setEditandoPrecio, precioTemp, setPrecioTemp,
      editandoCuota, setEditandoCuota,
      iniciarEdicionCuota,
      modoVista, setModoVista,
      recalcularCuotasAuto, setRecalcularCuotasAuto,
    },
    toggles: {
      editandoRebate, setEditandoRebate, rebateTemp, setRebateTemp,
      editandoWebTransf, setEditandoWebTransf, webTransfTemp, setWebTransfTemp,
      toggleRebateRapido, toggleWebTransfRapido, toggleOutOfCardsRapido,
    },
    seleccion: { toggleSeleccion, cambiarColorRapido, setColorDropdownAbierto },
    ui: {
      mostrarExportModal, setMostrarExportModal,
      mostrarCalcularWebModal, setMostrarCalcularWebModal,
      mostrarCalcularPVPModal, setMostrarCalcularPVPModal,
      mostrarModalConfig,
      mostrarModalInfo, setMostrarModalInfo, setProductoInfo,
      mostrarFiltrosAvanzados, setMostrarFiltrosAvanzados,
      panelFiltroActivo, setPanelFiltroActivo,
    },
    permissions: {
      puedeEditar,
      puedeMarcarColor,
      puedeToggleRebate,
      puedeToggleWebTransf,
      puedeToggleOutOfCards,
      puedeCalcularWebMasivo,
      puedeCalcularPVPMasivo,
    },
    showToast,
  });

  return (
    <div className="productos-container">
      <div className="stats-grid">
        <StatCard
          label="📦 Total Productos"
          value={stats?.total_productos?.toLocaleString('es-AR') || 0}
          onClick={limpiarFiltros}
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
        <SearchInput
          value={searchInput}
          onChange={(val) => { setSearchInput(val); setPage(1); }}
          placeholder="Buscar productos..."
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
            className={`filter-button ${(filtroRebate || filtroOferta || filtroWebTransf || filtroMarkupClasica || filtroMarkupRebate || filtroMarkupOferta || filtroMarkupWebTransf || filtroOutOfCards || coloresSeleccionados.length > 0 || filtroPromoTipos.length > 0) ? 'active' : ''}`}
          >
            Avanzados
            {(filtroRebate || filtroOferta || filtroWebTransf || filtroMarkupClasica || filtroMarkupRebate || filtroMarkupOferta || filtroMarkupWebTransf || filtroOutOfCards || coloresSeleccionados.length > 0 || filtroPromoTipos.length > 0) && (
              <span className="filter-badge">
                {[filtroRebate, filtroOferta, filtroWebTransf, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards].filter(Boolean).length + coloresSeleccionados.length + filtroPromoTipos.length}
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

          {/* Botón cíclico de Vista: Normal → Cuotas → PVP */}
          <button
            className="filter-button"
            onClick={() => {
              const siguienteModo = 
                modoVista === 'normal' ? 'cuotas' :
                modoVista === 'cuotas' ? 'pvp' :
                'normal';
              setModoVista(siguienteModo);
              // Resetear columna activa para evitar ir a columnas ocultas
              if (celdaActiva) {
                setCeldaActiva({ ...celdaActiva, colIndex: 0 });
              }
            }}
            title="Alt+V para ciclar vistas | Alt+P para ir directo a PVP"
          >
            {modoVista === 'normal' && 'Normal'}
            {modoVista === 'cuotas' && '📊 Cuotas'}
            {modoVista === 'pvp' && '💰 PVP'}
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

          {puedeCalcularPVPMasivo && (
          <button
            onClick={() => setMostrarCalcularPVPModal(true)}
            className="btn-tesla outline-subtle-primary sm"
            title="Calcular precios PVP masivamente (Ctrl+Shift+P)"
          >
            Calcular PVP
          </button>
          )}

          {(modoVista === 'cuotas' || modoVista === 'pvp') && puedeEditarCuotas && (
          <button
            onClick={recalcularCuotasMasivo}
            className="btn-tesla outline-subtle-primary sm"
            disabled={recalculandoCuotasMasivo}
            title="Recalcula cuotas desde el precio base existente para todos los productos filtrados"
          >
            {recalculandoCuotasMasivo ? 'Recalculando...' : `Recalcular Cuotas ${modoVista === 'pvp' ? 'PVP' : 'Web'}`}
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
                        aria-label="Limpiar búsqueda"
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
                    <div className="dropdown-empty-message">
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
                setFiltroWebTransf(null);
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
                setFiltroPromoTipos([]);
                setFiltroPromoEstado('disponible');
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
                  <label>Mejor Oferta</label>
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
                    value={filtroWebTransf || 'todos'}
                    onChange={(e) => { setFiltroWebTransf(e.target.value === 'todos' ? null : e.target.value); setPage(1); }}
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
                    <option value="con_descuento">Con Descuento</option>
                    <option value="sin_descuento">💵 Sin Descuento</option>
                    <option value="no_publicado">📦 No Publicado</option>
                  </select>
                </div>

                <div className="filter-item">
                  <label>Out of Cards</label>
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
              <div className="filter-group-title">Filtros de Estado</div>
              <div className="filter-group-content">
                <div className="filter-item">
                  <label>MercadoLibre</label>
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
                  <label>🏷️ Promos</label>
                  <div className={styles.filterBar}>
                    {PROMO_TYPES.map(({ type, label }) => {
                      const selected = filtroPromoTipos.includes(type);
                      return (
                        <button
                          key={type}
                          type="button"
                          className={`${styles.filterChip} ${selected ? styles.filterChipActive : ''}`}
                          aria-pressed={selected}
                          onClick={() => {
                            setFiltroPromoTipos(
                              selected
                                ? filtroPromoTipos.filter((t) => t !== type)
                                : [...filtroPromoTipos, type]
                            );
                            setPage(1);
                          }}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                  <select
                    value={filtroPromoEstado}
                    onChange={(e) => { setFiltroPromoEstado(e.target.value); setPage(1); }}
                    className="filter-select-compact"
                    aria-label="Estado de promo"
                  >
                    <option value="disponible">Disponible</option>
                    <option value="aplicada">Aplicada</option>
                    <option value="sin_aplicar">Sin aplicar</option>
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

                <div className="filter-item">
                  <label>🏪 Tienda Oficial</label>
                  <select
                    value={filtroTiendaOficial || 'todos'}
                    onChange={(e) => { setFiltroTiendaOficial(e.target.value === 'todos' ? null : e.target.value); setPage(1); }}
                    className="filter-select"
                  >
                    <option value="todos">Todas</option>
                    <option value="57997">🏢 Gauss</option>
                    <option value="2645" title="TP-Link">📡 TP-Link</option>
                    <option value="144" title="Forza, Verbatim">⚡ Forza/Verbatim</option>
                    <option value="191942" title="Epson, Forza, Logitech, MGN, Razer">🎯 Multi-marca</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Filtros de Color */}
            <div className="filter-group">
              <div className="filter-group-title">Marcado por Color</div>
              <div className="filter-group-content color-filter-container">
                {COLORES_DISPONIBLES.map(c => (
                  <label
                    key={c.id || 'sin_color'}
                    className="color-checkbox"
                    style={{
                      backgroundColor: c.color || 'var(--bg-primary)',
                      border: coloresSeleccionados.includes(c.id === null ? 'sin_color' : c.id) ? '3px solid var(--text-primary)' : '2px solid var(--border-secondary)',
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
                      aria-label={`Filtrar por color: ${c.nombre}`}
                      onChange={(e) => {
                        const colorValue = c.id === null ? 'sin_color' : c.id;
                        if (e.target.checked) {
                          setColoresSeleccionados([...coloresSeleccionados, colorValue]);
                        } else {
                          setColoresSeleccionados(coloresSeleccionados.filter(color => color !== colorValue));
                        }
                        setPage(1);
                      }}
                      className="color-checkbox-hidden"
                    />
                    {coloresSeleccionados.includes(c.id === null ? 'sin_color' : c.id) && <span className="color-checkmark">✓</span>}
                    {c.id === null && !coloresSeleccionados.includes('sin_color') && <span className="color-checkmark">✕</span>}
                  </label>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      <PromoFilterBar />

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
                  <th aria-label="Expandir" />
                  <th className="th-checkbox">
                    <input
                      type="checkbox"
                      checked={productosSeleccionados.size === productos.length && productos.length > 0}
                      onChange={seleccionarTodos}
                      className="checkbox-pointer"
                      aria-label="Seleccionar todos los productos"
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
                    {modoVista === 'pvp' ? 'Precio PVP' : 'Precio Clásica'} {getIconoOrden('precio_clasica')} {getNumeroOrden('precio_clasica') && <span>{getNumeroOrden('precio_clasica')}</span>}
                  </th>

                  {modoVista === 'normal' && (
                    <>
                      <th onClick={(e) => handleOrdenar('precio_rebate', e)}>
                        Precio Rebate {getIconoOrden('precio_rebate')} {getNumeroOrden('precio_rebate') && <span>{getNumeroOrden('precio_rebate')}</span>}
                      </th>
                      <th onClick={(e) => handleOrdenar('mejor_oferta', e)}>
                        Mejor Oferta {getIconoOrden('mejor_oferta')} {getNumeroOrden('mejor_oferta') && <span>{getNumeroOrden('mejor_oferta')}</span>}
                      </th>
                      <th onClick={(e) => handleOrdenar('web_transf', e)}>
                        Web Transf. {getIconoOrden('web_transf')} {getNumeroOrden('web_transf') && <span>{getNumeroOrden('web_transf')}</span>}
                      </th>
                    </>
                  )}

                  {modoVista === 'cuotas' && (
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

                  {modoVista === 'pvp' && (
                    <>
                      <th onClick={(e) => handleOrdenar('precio_pvp_3_cuotas', e)}>
                        PVP 3 Cuotas {getIconoOrden('precio_pvp_3_cuotas')} {getNumeroOrden('precio_pvp_3_cuotas') && <span>{getNumeroOrden('precio_pvp_3_cuotas')}</span>}
                      </th>
                      <th onClick={(e) => handleOrdenar('precio_pvp_6_cuotas', e)}>
                        PVP 6 Cuotas {getIconoOrden('precio_pvp_6_cuotas')} {getNumeroOrden('precio_pvp_6_cuotas') && <span>{getNumeroOrden('precio_pvp_6_cuotas')}</span>}
                      </th>
                      <th onClick={(e) => handleOrdenar('precio_pvp_9_cuotas', e)}>
                        PVP 9 Cuotas {getIconoOrden('precio_pvp_9_cuotas')} {getNumeroOrden('precio_pvp_9_cuotas') && <span>{getNumeroOrden('precio_pvp_9_cuotas')}</span>}
                      </th>
                      <th onClick={(e) => handleOrdenar('precio_pvp_12_cuotas', e)}>
                        PVP 12 Cuotas {getIconoOrden('precio_pvp_12_cuotas')} {getNumeroOrden('precio_pvp_12_cuotas') && <span>{getNumeroOrden('precio_pvp_12_cuotas')}</span>}
                      </th>
                    </>
                  )}

                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody className="table-tesla-body">
                {productosOrdenados.flatMap((p, rowIndex) => {
                  const isRowActive = modoNavegacion && celdaActiva?.rowIndex === rowIndex;
                  const colorClass = p.color_marcado ? `row-color-${p.color_marcado}` : '';
                  const isMlaOpen = mlaExpanded.isOpen(p.item_id);
                  const filas = [
                  <tr
                    key={p.item_id}
                    data-nav-row={rowIndex}
                    className={`${colorClass} ${p.color_marcado ? 'row-colored' : ''} ${isRowActive ? 'keyboard-row-active' : ''}`}
                  >
                    <td className={styles.spoilerToggleCell}>
                      <button
                        type="button"
                        className={styles.spoilerToggle}
                        onClick={() => mlaExpanded.toggle(p.item_id)}
                        aria-label={isMlaOpen ? `Colapsar publicaciones de ${p.codigo}` : `Expandir publicaciones de ${p.codigo}`}
                        aria-expanded={isMlaOpen}
                      >
                        {isMlaOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      </button>
                    </td>
                    <td className="td-center">
                      <input
                        type="checkbox"
                        checked={productosSeleccionados.has(p.item_id)}
                        onChange={(e) => toggleSeleccion(p.item_id, e.shiftKey)}
                        onClick={(e) => e.stopPropagation()}
                        className="checkbox-pointer"
                        aria-label={`Seleccionar producto ${p.codigo}`}
                      />
                    </td>
                    <td>{p.codigo}</td>
                    <td>
                      {p.descripcion}
                      <PrearmadaBadge stats={prearmadasStats[p.item_id]} />
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
                              'var(--text-tertiary)',
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
                           p.catalog_status === 'competing' ? '!' :
                           ''}
                        </span>
                      )}
                    </td>
                    <td>{p.marca}</td>
                    <td>{p.stock}</td>
                    <td>{p.moneda_costo} ${p.costo?.toFixed(2)}</td>
                    <td className={isRowActive && celdaActiva?.colIndex === 0 ? 'keyboard-cell-active' : ''}>
                      {editandoPrecio === p.item_id ? (
                        <div className="inline-edit">
                          <input
                            type="text"
                            inputMode="decimal"
                            value={precioTemp}
                            onChange={(e) => setPrecioTemp(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault();
                                guardarPrecio(p.item_id);
                              }
                            }}
                            onFocus={(e) => e.target.select()}
                            autoFocus
                          />
                          <button 
                            onClick={() => guardarPrecio(p.item_id)} 
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault();
                                guardarPrecio(p.item_id);
                              }
                            }}
                            aria-label="Guardar precio"
                          >✓</button>
                          <button 
                            onClick={() => setEditandoPrecio(null)} 
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault();
                                setEditandoPrecio(null);
                              }
                            }}
                            aria-label="Cancelar edición"
                          >✗</button>
                        </div>
                      ) : (
                        <div onClick={() => puedeEditar && iniciarEdicion(p)}>
                          <div className={puedeEditar ? 'editable-field' : ''}>
                            {modoVista === 'pvp' ? (
                              p.precio_pvp ? `$${p.precio_pvp.toLocaleString('es-AR')}` : 'Sin precio'
                            ) : (
                              p.precio_lista_ml ? `$${p.precio_lista_ml.toLocaleString('es-AR')}` : 'Sin precio'
                            )}
                          </div>
                          {modoVista === 'pvp' ? (
                            p.markup_pvp !== null && p.markup_pvp !== undefined && (
                              <div className="markup-display" style={{ color: getMarkupColor(p.markup_pvp) }}>
                                {p.markup_pvp}%
                              </div>
                            )
                          ) : (
                            <>
                              {p.markup !== null && p.markup !== undefined && (
                                <div className="markup-display" style={{ color: getMarkupColor(p.markup) }}>
                                  {p.markup}%
                                  {(() => {
                                    const mkOffset = calcularMarkupConOffset(p);
                                    if (mkOffset === null) return null;
                                    return (
                                      <span
                                        className="markup-offset-display"
                                        title="Markup con offsets aplicados"
                                      >
                                        → {mkOffset.toFixed(2)}%
                                      </span>
                                    );
                                  })()}
                                </div>
                              )}
                            </>
                          )}
                        </div>
                      )}
                    </td>

                    {/* Vista Normal: Rebate, Oferta, Web Transf */}
                    {modoVista === 'normal' && (
                      <>
                    <td className={isRowActive && celdaActiva?.colIndex === 1 ? 'keyboard-cell-active' : ''}>
                      {editandoRebate === p.item_id ? (
                        <div className="rebate-edit">
                          <label className="rebate-checkbox">
                            <input
                              type="checkbox"
                              checked={rebateTemp.participa}
                              onChange={(e) => setRebateTemp({ ...rebateTemp, participa: e.target.checked })}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  e.preventDefault();
                                  guardarRebate(p.item_id);
                                }
                              }}
                            />
                            <span>Rebate</span>
                          </label>
                          {rebateTemp.participa && (
                            <input
                              type="text"
                              inputMode="decimal"
                              value={rebateTemp.porcentaje}
                              onChange={(e) => setRebateTemp({ ...rebateTemp, porcentaje: e.target.value })}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  e.preventDefault();
                                  guardarRebate(p.item_id);
                                }
                              }}
                              onFocus={(e) => e.target.select()}
                              placeholder="%"
                              autoFocus
                            />
                          )}
                          <div className="inline-edit">
                            <button 
                              onClick={() => guardarRebate(p.item_id)} 
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  e.preventDefault();
                                  guardarRebate(p.item_id);
                                }
                              }}
                              aria-label="Guardar rebate"
                            >✓</button>
                            <button 
                              onClick={() => setEditandoRebate(null)} 
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  e.preventDefault();
                                  setEditandoRebate(null);
                                }
                              }}
                              aria-label="Cancelar edición"
                            >✗</button>
                          </div>
                        </div>
                      ) : (
                        <div className="rebate-info" onClick={() => iniciarEdicionRebate(p)}>
                          {p.participa_rebate && p.precio_rebate ? (
                            <div>
                              <div className="rebate-price">
                                ${p.precio_rebate.toFixed(2).toLocaleString('es-AR')}
                              </div>
                              <div className="rebate-percentage">
                                {p.porcentaje_rebate}% rebate
                              </div>
                              <label
                                className="out-of-cards-checkbox"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <input
                                  type="checkbox"
                                  checked={p.out_of_cards || false}
                                  onChange={async (e) => {
                                    e.stopPropagation();
                                    const nuevoValor = e.target.checked;
                                    try {
                                      await api.patch(
                                        `/productos/${p.item_id}/out-of-cards`,
                                        { out_of_cards: nuevoValor }
                                      );
                                      
                                      // Actualizar estado local en lugar de recargar
                                      setProductos(prods => prods.map(prod =>
                                        prod.item_id === p.item_id
                                          ? { ...prod, out_of_cards: nuevoValor }
                                          : prod
                                      ));
                                      
                                      // Recargar stats para reflejar cambios en contadores
                                      cargarStats();
                                    } catch (error) {
                                      
                                      showToast(`Error: ${error.response?.data?.detail || error.message}`, 'error');
                                    }
                                  }}
                                />
                                Out of Cards
                              </label>
                            </div>
                          ) : (
                            <div className="text-muted editable-field">
                              Sin rebate
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                    <td className={isRowActive && celdaActiva?.colIndex === 2 ? 'keyboard-cell-active' : ''}>
                      {p.mejor_oferta_precio ? (
                        <div className="mejor-oferta-info">
                          <div className="mejor-oferta-precio">
                            ${p.mejor_oferta_precio.toLocaleString('es-AR')}
                          </div>
                          {p.mejor_oferta_porcentaje_rebate && (
                            <div className="mejor-oferta-rebate">
                              {p.mejor_oferta_porcentaje_rebate.toFixed(2)}%
                            </div>
                          )}
                          {p.mejor_oferta_monto_rebate && (
                            <div className="mejor-oferta-rebate">
                              Rebate: ${p.mejor_oferta_monto_rebate.toLocaleString('es-AR')}
                            </div>
                          )}
                          {p.mejor_oferta_fecha_hasta && (
                            <div className="mejor-oferta-detalle">
                              Hasta {new Date(p.mejor_oferta_fecha_hasta).toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit' })}
                            </div>
                          )}
                          {p.mejor_oferta_pvp_seller && (
                            <div className="mejor-oferta-detalle">
                              PVP: ${p.mejor_oferta_pvp_seller.toLocaleString('es-AR')}
                            </div>
                          )}
                          {p.mejor_oferta_markup !== null && (
                            <div className="mejor-oferta-detalle" style={{ color: getMarkupColor(p.mejor_oferta_markup * 100) }}>
                              Markup: {(p.mejor_oferta_markup * 100).toFixed(2)}%
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="text-muted">-</span>
                      )}
                    </td>
                    <td className={isRowActive && celdaActiva?.colIndex === 3 ? 'keyboard-cell-active' : ''}>
                      <div>
                        {/* Mostrar precios de Tienda Nube si existen */}
                        {(p.tn_price || p.tn_promotional_price) && (
                          <div className="web-transf-info web-transf-info-divider">
                            {p.tn_has_promotion && p.tn_promotional_price ? (
                              <div>
                                <div className="web-transf-precio-container">
                                  <span>${p.tn_promotional_price.toLocaleString('es-AR')}</span>
                                  <span className="web-transf-porcentaje-info">
                                    ${(p.tn_promotional_price * 0.75).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} transf.
                                  </span>
                                </div>
                                {p.tn_price && (
                                  <div className="tn-price-strikethrough">
                                    ${p.tn_price.toLocaleString('es-AR')}
                                  </div>
                                )}
                              </div>
                            ) : p.tn_price ? (
                              <div className="web-transf-info-row">
                                <span>${p.tn_price.toLocaleString('es-AR')}</span>
                                <span className="web-transf-porcentaje-info">
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
                            <button 
                              onClick={() => guardarWebTransf(p.item_id)} 
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  e.preventDefault();
                                  guardarWebTransf(p.item_id);
                                }
                              }}
                              aria-label="Guardar Web/Transferencia"
                            >✓</button>
                            <button 
                              onClick={() => setEditandoWebTransf(null)} 
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  e.preventDefault();
                                  setEditandoWebTransf(null);
                                }
                              }}
                              aria-label="Cancelar edición"
                            >✗</button>
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
                    </>
                    )}

                    {/* Vista Cuotas: 3, 6, 9, 12 cuotas */}
                    {modoVista === 'cuotas' && (
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
                              <button onClick={() => guardarCuota(p.item_id, '3')} aria-label="Guardar cuota">✓</button>
                              <button onClick={() => setEditandoCuota(null)} aria-label="Cancelar edición">✗</button>
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
                              <button onClick={() => guardarCuota(p.item_id, '6')} aria-label="Guardar cuota">✓</button>
                              <button onClick={() => setEditandoCuota(null)} aria-label="Cancelar edición">✗</button>
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
                              <button onClick={() => guardarCuota(p.item_id, '9')} aria-label="Guardar cuota">✓</button>
                              <button onClick={() => setEditandoCuota(null)} aria-label="Cancelar edición">✗</button>
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
                              <button onClick={() => guardarCuota(p.item_id, '12')} aria-label="Guardar cuota">✓</button>
                              <button onClick={() => setEditandoCuota(null)} aria-label="Cancelar edición">✗</button>
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

                    {/* Vista PVP: PVP 3, 6, 9, 12 cuotas - EDITABLES */}
                    {modoVista === 'pvp' && (
                      <>
                        <td className={isRowActive && celdaActiva?.colIndex === 1 ? 'keyboard-cell-active' : ''}>
                          {editandoCuota?.item_id === p.item_id && editandoCuota?.tipo === '3' && editandoCuota?.esPVP ? (
                            <div className="inline-edit">
                              <input
                                type="text"
                                value={cuotaTemp}
                                onChange={(e) => setCuotaTemp(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') { e.preventDefault(); guardarCuota(p.item_id, '3', true); }
                                }}
                                onFocus={(e) => e.target.select()}
                                autoFocus
                              />
                              <button onClick={() => guardarCuota(p.item_id, '3', true)} aria-label="Guardar cuota">✓</button>
                              <button onClick={() => setEditandoCuota(null)} aria-label="Cancelar edición">✗</button>
                            </div>
                          ) : (
                            <div onClick={() => {
                              if (puedeEditar) {
                                setEditandoCuota({ item_id: p.item_id, tipo: '3', esPVP: true });
                                setCuotaTemp(p.precio_pvp_3_cuotas || '');
                              }
                            }}>
                              <div className={puedeEditar ? 'editable-field' : ''}>
                                {p.precio_pvp_3_cuotas ? `$${p.precio_pvp_3_cuotas.toLocaleString('es-AR')}` : '-'}
                              </div>
                              {p.markup_pvp_3_cuotas !== null && p.markup_pvp_3_cuotas !== undefined && (
                                <div className="markup-display" style={{ color: getMarkupColor(p.markup_pvp_3_cuotas) }}>
                                  {p.markup_pvp_3_cuotas.toFixed(2)}%
                                </div>
                              )}
                            </div>
                          )}
                        </td>

                        <td className={isRowActive && celdaActiva?.colIndex === 2 ? 'keyboard-cell-active' : ''}>
                          {editandoCuota?.item_id === p.item_id && editandoCuota?.tipo === '6' && editandoCuota?.esPVP ? (
                            <div className="inline-edit">
                              <input
                                type="text"
                                value={cuotaTemp}
                                onChange={(e) => setCuotaTemp(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') { e.preventDefault(); guardarCuota(p.item_id, '6', true); }
                                }}
                                onFocus={(e) => e.target.select()}
                                autoFocus
                              />
                              <button onClick={() => guardarCuota(p.item_id, '6', true)} aria-label="Guardar cuota">✓</button>
                              <button onClick={() => setEditandoCuota(null)} aria-label="Cancelar edición">✗</button>
                            </div>
                          ) : (
                            <div onClick={() => {
                              if (puedeEditar) {
                                setEditandoCuota({ item_id: p.item_id, tipo: '6', esPVP: true });
                                setCuotaTemp(p.precio_pvp_6_cuotas || '');
                              }
                            }}>
                              <div className={puedeEditar ? 'editable-field' : ''}>
                                {p.precio_pvp_6_cuotas ? `$${p.precio_pvp_6_cuotas.toLocaleString('es-AR')}` : '-'}
                              </div>
                              {p.markup_pvp_6_cuotas !== null && p.markup_pvp_6_cuotas !== undefined && (
                                <div className="markup-display" style={{ color: getMarkupColor(p.markup_pvp_6_cuotas) }}>
                                  {p.markup_pvp_6_cuotas.toFixed(2)}%
                                </div>
                              )}
                            </div>
                          )}
                        </td>

                        <td className={isRowActive && celdaActiva?.colIndex === 3 ? 'keyboard-cell-active' : ''}>
                          {editandoCuota?.item_id === p.item_id && editandoCuota?.tipo === '9' && editandoCuota?.esPVP ? (
                            <div className="inline-edit">
                              <input
                                type="text"
                                value={cuotaTemp}
                                onChange={(e) => setCuotaTemp(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') { e.preventDefault(); guardarCuota(p.item_id, '9', true); }
                                }}
                                onFocus={(e) => e.target.select()}
                                autoFocus
                              />
                              <button onClick={() => guardarCuota(p.item_id, '9', true)} aria-label="Guardar cuota">✓</button>
                              <button onClick={() => setEditandoCuota(null)} aria-label="Cancelar edición">✗</button>
                            </div>
                          ) : (
                            <div onClick={() => {
                              if (puedeEditar) {
                                setEditandoCuota({ item_id: p.item_id, tipo: '9', esPVP: true });
                                setCuotaTemp(p.precio_pvp_9_cuotas || '');
                              }
                            }}>
                              <div className={puedeEditar ? 'editable-field' : ''}>
                                {p.precio_pvp_9_cuotas ? `$${p.precio_pvp_9_cuotas.toLocaleString('es-AR')}` : '-'}
                              </div>
                              {p.markup_pvp_9_cuotas !== null && p.markup_pvp_9_cuotas !== undefined && (
                                <div className="markup-display" style={{ color: getMarkupColor(p.markup_pvp_9_cuotas) }}>
                                  {p.markup_pvp_9_cuotas.toFixed(2)}%
                                </div>
                              )}
                            </div>
                          )}
                        </td>

                        <td className={isRowActive && celdaActiva?.colIndex === 4 ? 'keyboard-cell-active' : ''}>
                          {editandoCuota?.item_id === p.item_id && editandoCuota?.tipo === '12' && editandoCuota?.esPVP ? (
                            <div className="inline-edit">
                              <input
                                type="text"
                                value={cuotaTemp}
                                onChange={(e) => setCuotaTemp(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') { e.preventDefault(); guardarCuota(p.item_id, '12', true); }
                                }}
                                onFocus={(e) => e.target.select()}
                                autoFocus
                              />
                              <button onClick={() => guardarCuota(p.item_id, '12', true)} aria-label="Guardar cuota">✓</button>
                              <button onClick={() => setEditandoCuota(null)} aria-label="Cancelar edición">✗</button>
                            </div>
                          ) : (
                            <div onClick={() => {
                              if (puedeEditar) {
                                setEditandoCuota({ item_id: p.item_id, tipo: '12', esPVP: true });
                                setCuotaTemp(p.precio_pvp_12_cuotas || '');
                              }
                            }}>
                              <div className={puedeEditar ? 'editable-field' : ''}>
                                {p.precio_pvp_12_cuotas ? `$${p.precio_pvp_12_cuotas.toLocaleString('es-AR')}` : '-'}
                              </div>
                              {p.markup_pvp_12_cuotas !== null && p.markup_pvp_12_cuotas !== undefined && (
                                <div className="markup-display" style={{ color: getMarkupColor(p.markup_pvp_12_cuotas) }}>
                                  {p.markup_pvp_12_cuotas.toFixed(2)}%
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
                          title="Información detallada (Ctrl+I)"
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
                                    border: c.id === p.color_marcado ? '2px solid var(--text-primary)' : '1px solid var(--border-secondary)'
                                  }}
                                  onClick={() => cambiarColorProducto(p.item_id, c.id)}
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
                  </tr>,
                  ];
                  if (isMlaOpen) {
                    filas.push(
                      <tr key={`${p.item_id}-mlas`} data-detail-row className={styles.filaDetalle}>
                        <td colSpan={TOTAL_COLS}>
                          <div className={styles.filaDetalleContent}>
                            <ProductoMLAsPanel
                              itemId={p.item_id}
                              mlasCacheRef={mlasCacheRef}
                              promosCacheRef={promosCacheRef}
                              promoTipos={filtroPromoTipos}
                              promoEstado={filtroPromoEstado}
                            />
                          </div>
                        </td>
                      </tr>,
                    );
                  }
                  return filas;
                })}
              </tbody>
            </table>

{auditoriaVisible && (
              <div className="modal-overlay">
                <div className="modal-content modal-auditoria">
                  <div className="modal-header">
                    <h2>Historial de Cambios</h2>
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
                              'marcar_out_of_cards': 'Out of Cards ON',
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
            filtroWebTransf,
            filtroMarkupClasica,
            filtroMarkupRebate,
            filtroMarkupOferta,
            filtroMarkupWebTransf,
            filtroOutOfCards,
            filtroMLA,
            filtroEstadoMLA,
            filtroNuevos,
            coloresSeleccionados,
            promo_tipos: filtroPromoTipos.length > 0 ? filtroPromoTipos.join(',') : null,
            promo_estado: filtroPromoTipos.length > 0 ? filtroPromoEstado : null,
            audit_usuarios: filtrosAuditoria.usuarios,
            audit_tipos_accion: filtrosAuditoria.tipos_accion,
            audit_fecha_desde: filtrosAuditoria.fecha_desde,
            audit_fecha_hasta: filtrosAuditoria.fecha_hasta
          }}
          showToast={showToast}
        />
      )}

      {mostrarCalcularPVPModal && (
        <CalcularPVPModal
          onClose={() => setMostrarCalcularPVPModal(false)}
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
            filtroWebTransf,
            filtroTiendaNube,
            filtroMarkupClasica,
            filtroMarkupRebate,
            filtroMarkupOferta,
            filtroMarkupWebTransf,
            filtroOutOfCards,
            coloresSeleccionados,
            filtroTiendaOficial,
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
            filtroWebTransf,
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
            promo_tipos: filtroPromoTipos.length > 0 ? filtroPromoTipos.join(',') : null,
            promo_estado: filtroPromoTipos.length > 0 ? filtroPromoEstado : null,
            audit_usuarios: filtrosAuditoria.usuarios,
            audit_tipos_accion: filtrosAuditoria.tipos_accion,
            audit_fecha_desde: filtrosAuditoria.fecha_desde,
            audit_fecha_hasta: filtrosAuditoria.fecha_hasta
          }}
          showToast={showToast}
        />
      )}

      {/* Modal de confirmación de ban */}
      {mostrarModalBan && productoBan && (
        <div className="modal-ban-overlay">
          <div className="modal-ban-content">
            <h2 className="modal-ban-title">Confirmar Ban</h2>

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

      {/* Modal de confirmación markup negativo */}
      {mostrarModalMarkupNegativo && datosGuardadoPendiente && (
        <div className="modal-ban-overlay">
          <div className="modal-ban-content" style={{maxWidth: '600px'}}>
            <h2 className="modal-ban-title" style={{color: 'var(--error)'}}>⚠️ MarkUp Negativo</h2>

            <div className="modal-ban-info">
              <p><strong>Producto:</strong> {datosGuardadoPendiente.producto.descripcion}</p>
              <p><strong>Código:</strong> {datosGuardadoPendiente.producto.codigo}</p>
              <p><strong>Marca:</strong> {datosGuardadoPendiente.producto.marca}</p>
              {datosGuardadoPendiente.esCuota && (
                <p><strong>Tipo:</strong> Precio {datosGuardadoPendiente.tipo} cuotas{datosGuardadoPendiente.esPVP ? ' (PVP)' : ''}</p>
              )}
              {!datosGuardadoPendiente.esCuota && (
                <p><strong>Tipo:</strong> Precio Clásica{datosGuardadoPendiente.listaTipo === 'pvp' ? ' (PVP)' : ''}</p>
              )}
            </div>

            <div className="modal-ban-warning" style={{backgroundColor: 'var(--error-bg)', borderColor: 'var(--error)', marginTop: '20px'}}>
              <p style={{fontSize: '1.1em', marginBottom: '10px'}}>
                ¿Está seguro que quiere guardar el producto <strong>{datosGuardadoPendiente.producto.descripcion}</strong> con un <strong>MarkUp Negativo</strong> del:
              </p>
              <p style={{fontSize: '2em', fontWeight: 'bold', color: 'var(--error)', margin: '10px 0'}}>
                {datosGuardadoPendiente.markup.toFixed(2)}%
              </p>
              <p style={{fontSize: '0.95em', color: 'var(--text-secondary)', marginTop: '10px'}}>
                Esto significa que el precio de venta está por debajo del costo + comisiones.
              </p>
            </div>

            <div className="config-modal-actions">
              <button
                onClick={() => {
                  setMostrarModalMarkupNegativo(false);
                  setDatosGuardadoPendiente(null);
                  // No limpiar editandoPrecio/editandoCuota para que el usuario pueda corregir el precio
                }}
                className="btn-tesla secondary"
              >
                Cancelar
              </button>
              <button
                onClick={confirmarGuardadoMarkupNegativo}
                className="btn-tesla outline-subtle-danger"
              >
                Guardar de todas formas
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
                style={{ backgroundColor: c.color || 'var(--bg-tertiary)' }}
                title={c.nombre}
                aria-label={`Pintar lote como ${c.nombre}`}
              >
                {!c.id && '✕'}
              </button>
            ))}
          </div>
          )}
          <button onClick={limpiarSeleccion} className="selection-bar-clear-btn">
            Cancelar
          </button>
        </div>
      )}

      {/* Modal de configuración individual */}
      {mostrarModalConfig && productoConfig && (
        <div className="shortcuts-modal-overlay" onClick={() => setMostrarModalConfig(false)}>
          <div 
            className={`shortcuts-modal config-modal ${modoVista === 'pvp' ? 'config-modal-pvp' : ''}`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={`shortcuts-header ${modoVista === 'pvp' ? 'config-header-pvp' : ''}`}>
              <h2>Configuración de Cuotas {modoVista === 'pvp' ? 'PVP' : 'Web'}</h2>
              <button onClick={() => setMostrarModalConfig(false)} className="close-btn">✕</button>
            </div>
            <div className="config-modal-content">
              <h3 className="config-modal-title">{productoConfig.descripcion}</h3>
              <p className="config-modal-subtitle">
                Código: {productoConfig.codigo} | Marca: {productoConfig.marca}
              </p>

              <div className="config-modal-field">
                <label className="config-modal-label">
                  Recalcular cuotas automáticamente:
                </label>
                <select
                  value={configTemp.recalcular_cuotas_auto === null ? 'null' : configTemp.recalcular_cuotas_auto.toString()}
                  onChange={(e) => setConfigTemp({ ...configTemp, recalcular_cuotas_auto: e.target.value })}
                  className="config-modal-select"
                >
                  <option value="null">Usar configuración global ({recalcularCuotasAuto ? 'Sí' : 'No'})</option>
                  <option value="true">Siempre recalcular</option>
                  <option value="false">Nunca recalcular</option>
                </select>
              </div>

              <div className="config-modal-field">
                <label className="config-modal-label">
                  Markup adicional para cuotas {modoVista === 'pvp' ? 'PVP' : 'Web'} (%):
                </label>
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  value={modoVista === 'pvp' ? configTemp.markup_adicional_cuotas_pvp_custom : configTemp.markup_adicional_cuotas_custom}
                  onChange={(e) => setConfigTemp({ 
                    ...configTemp, 
                    [modoVista === 'pvp' ? 'markup_adicional_cuotas_pvp_custom' : 'markup_adicional_cuotas_custom']: e.target.value 
                  })}
                  onFocus={(e) => e.target.select()}
                  placeholder="Dejar vacío para usar configuración global"
                  className="config-modal-input"
                />
                <p className="config-modal-help">
                  Dejar vacío para usar la configuración global
                </p>
              </div>

              <div className="config-modal-actions">
                <button onClick={() => setMostrarModalConfig(false)} className="btn-tesla secondary">
                  Cancelar
                </button>
                <button onClick={guardarConfigIndividual} className="btn-tesla outline-subtle-primary">
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
              <h2>Atajos de Teclado</h2>
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
                <h3>Operadores de Búsqueda</h3>
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
                  <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>P</kbd>
                  <span>Calcular PVP masivo (clásica + cuotas)</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>V</kbd>
                  <span>Ciclar vistas: Normal → Cuotas → PVP</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>P</kbd>
                  <span>Toggle Vista PVP</span>
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
          Modo Navegación Activo - Presiona <kbd>Esc</kbd> para salir o <kbd>?</kbd> para ayuda
        </div>
      )}

      {/* Toast notification */}
      <Toast toast={toast} onClose={hideToast} />
    </div>
  );
}
