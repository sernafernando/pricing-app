import { useState, useEffect, useCallback } from 'react';
import api, { productosAPI } from '../services/api';

/**
 * Custom hook para manejar TODA la carga de datos de la vista Tienda.
 * Incluye: productos, stats, marcas, subcategorías, PMs, dólar, web tarjeta config.
 * 
 * @param {Object} params
 * @param {Function} params.construirFiltrosParams - Función del hook de filtros
 * @param {number} params.page - Página actual
 * @param {number} params.pageSize - Tamaño de página
 * @param {Array} params.ordenColumnas - Columnas de ordenamiento
 * @param {string} params.debouncedSearch - Búsqueda con debounce
 * @param {Object} params.filters - Objeto con todos los filtros activos (para useEffect deps)
 * @param {Function} params.showToast - Función de notificación
 */
export function useTiendaData({
  construirFiltrosParams,
  page,
  pageSize,
  ordenColumnas,
  debouncedSearch,
  filters,
  showToast,
}) {
  // === ESTADO: Productos y carga principal ===
  const [productos, setProductos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [totalProductos, setTotalProductos] = useState(0);

  // === ESTADO: Stats dinámicos ===
  const [stats, setStats] = useState(null);

  // === ESTADO: Opciones de filtros (cargadas desde API) ===
  const [marcas, setMarcas] = useState([]);
  const [subcategorias, setSubcategorias] = useState([]);
  const [usuarios, setUsuarios] = useState([]);
  const [tiposAccion, setTiposAccion] = useState([]);
  const [pms, setPms] = useState([]);

  // === ESTADO: Datos derivados de PMs ===
  const [marcasPorPM, setMarcasPorPM] = useState([]);
  const [subcategoriasPorPM, setSubcategoriasPorPM] = useState([]);

  // === ESTADO: Configuración y cotizaciones ===
  const [markupWebTarjeta, setMarkupWebTarjeta] = useState(0);
  const [dolarVenta, setDolarVenta] = useState(null);

  // === ESTADO: Auditoría ===
  const [auditoriaVisible, setAuditoriaVisible] = useState(false);
  const [auditoriaData, setAuditoriaData] = useState([]);

  // === FUNCIONES DE CARGA ===

  const cargarProductos = useCallback(async () => {
    setLoading(true);
    try {
      const params = construirFiltrosParams();

      params.page = page;
      params.page_size = pageSize;

      if (ordenColumnas.length > 0) {
        params.orden_campos = ordenColumnas.map(o => o.columna).join(',');
        params.orden_direcciones = ordenColumnas.map(o => o.direccion).join(',');
      }

      const productosRes = await productosAPI.listarTienda(params);
      setTotalProductos(productosRes.data.total || productosRes.data.productos.length);
      setProductos(productosRes.data.productos);
    } catch {
      showToast('Error cargando datos', 'error');
    } finally {
      setLoading(false);
    }
  }, [construirFiltrosParams, page, pageSize, ordenColumnas, showToast]);

  const cargarStats = useCallback(async () => {
    try {
      const params = construirFiltrosParams();
      const statsRes = await productosAPI.statsDinamicos(params);
      setStats(statsRes.data);
    } catch {
      showToast('Error cargando estadísticas', 'error');
    }
  }, [construirFiltrosParams, showToast]);

  const cargarMarcas = useCallback(async () => {
    try {
      const params = construirFiltrosParams({ incluirMarcas: false });
      const response = await productosAPI.marcas(params);
      setMarcas(response.data.marcas);
    } catch {
      showToast('Error cargando marcas', 'error');
    }
  }, [construirFiltrosParams, showToast]);

  const cargarSubcategorias = useCallback(async () => {
    try {
      const params = construirFiltrosParams({ incluirSubcategorias: false });
      const response = await productosAPI.subcategorias(params);
      setSubcategorias(response.data.categorias);
    } catch {
      showToast('Error cargando subcategorías', 'error');
    }
  }, [construirFiltrosParams, showToast]);

  const cargarUsuariosAuditoria = useCallback(async () => {
    try {
      const response = await api.get('/auditoria/usuarios');
      setUsuarios(response.data.usuarios);
    } catch {
      showToast('Error cargando usuarios', 'error');
    }
  }, [showToast]);

  const cargarTiposAccion = useCallback(async () => {
    try {
      const response = await api.get('/auditoria/tipos-accion');
      setTiposAccion(response.data.tipos);
    } catch {
      showToast('Error cargando tipos de acción', 'error');
    }
  }, [showToast]);

  const cargarPMs = useCallback(async () => {
    try {
      const response = await api.get('/usuarios/pms', { params: { solo_con_marcas: true } });
      setPms(response.data);
    } catch {
      showToast('Error cargando PMs', 'error');
    }
  }, [showToast]);

  const cargarConfigWebTarjeta = useCallback(async () => {
    try {
      const response = await api.get('/markups-tienda/config/markup_web_tarjeta');
      setMarkupWebTarjeta(response.data.valor || 0);
    } catch {
      showToast('Error cargando configuración web tarjeta', 'error');
    }
  }, [showToast]);

  const cargarDolarVenta = useCallback(async () => {
    try {
      const response = await api.get('/tipo-cambio/actual');
      setDolarVenta(response.data.venta);
    } catch {
      showToast('Error cargando cotización dólar', 'error');
    }
  }, [showToast]);

  const verAuditoria = async (productoId) => {
    try {
      const response = await api.get(`/productos/${productoId}/auditoria`);
      setAuditoriaData(response.data);
      setAuditoriaVisible(true);
    } catch {
      showToast('Error al cargar el historial', 'error');
    }
  };

  // === useEffects DE CARGA ===

  // Cargar productos cuando cambian filtros/paginación/ordenamiento
  useEffect(() => {
    cargarProductos();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    page, debouncedSearch, pageSize, ordenColumnas,
    filters.filtroStock, filters.filtroPrecio,
    filters.marcasSeleccionadas, filters.subcategoriasSeleccionadas,
    filters.filtrosAuditoria, filters.filtroRebate, filters.filtroOferta,
    filters.filtroWebTransf, filters.filtroTiendaNube,
    filters.filtroMarkupClasica, filters.filtroMarkupRebate,
    filters.filtroMarkupOferta, filters.filtroMarkupWebTransf,
    filters.filtroOutOfCards, filters.coloresSeleccionados,
    filters.pmsSeleccionados, filters.filtroMLA, filters.filtroEstadoMLA,
    filters.filtroNuevos,
  ]);

  // Cargar stats cuando cambian filtros
  useEffect(() => {
    cargarStats();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    debouncedSearch,
    filters.filtroStock, filters.filtroPrecio,
    filters.marcasSeleccionadas, filters.subcategoriasSeleccionadas,
    filters.filtrosAuditoria, filters.filtroRebate, filters.filtroOferta,
    filters.filtroWebTransf, filters.filtroTiendaNube,
    filters.filtroMarkupClasica, filters.filtroMarkupRebate,
    filters.filtroMarkupOferta, filters.filtroMarkupWebTransf,
    filters.filtroOutOfCards, filters.coloresSeleccionados,
    filters.pmsSeleccionados, filters.filtroMLA, filters.filtroEstadoMLA,
    filters.filtroNuevos,
  ]);

  // Cargar marcas/subcats por PM
  useEffect(() => {
    const cargarDatosPorPM = async () => {
      if (filters.pmsSeleccionados.length > 0) {
        try {
          const [marcasRes, subcatsRes] = await Promise.all([
            productosAPI.obtenerMarcasPorPMs(filters.pmsSeleccionados.join(',')),
            productosAPI.obtenerSubcategoriasPorPMs(filters.pmsSeleccionados.join(','))
          ]);
          setMarcasPorPM(marcasRes.data.marcas);
          setSubcategoriasPorPM(subcatsRes.data.subcategorias.map(s => s.id));
        } catch {
          showToast('Error cargando datos por PM', 'error');
          setMarcasPorPM([]);
          setSubcategoriasPorPM([]);
        }
      } else {
        setMarcasPorPM([]);
        setSubcategoriasPorPM([]);
      }
    };
    cargarDatosPorPM();
  }, [filters.pmsSeleccionados, showToast]);

  // Cargar datos iniciales (mount only)
  useEffect(() => {
    cargarUsuariosAuditoria();
    cargarTiposAccion();
    cargarPMs();
    cargarConfigWebTarjeta();
    cargarDolarVenta();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Recargar marcas cuando cambien filtros (excepto marcasSeleccionadas)
  useEffect(() => {
    cargarMarcas();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    debouncedSearch,
    filters.filtroStock, filters.filtroPrecio,
    filters.subcategoriasSeleccionadas, filters.filtroRebate, filters.filtroOferta,
    filters.filtroWebTransf, filters.filtroTiendaNube,
    filters.filtroMarkupClasica, filters.filtroMarkupRebate,
    filters.filtroMarkupOferta, filters.filtroMarkupWebTransf,
    filters.filtroOutOfCards, filters.coloresSeleccionados,
    filters.filtrosAuditoria,
  ]);

  // Recargar subcategorías cuando cambien filtros (excepto subcategoriasSeleccionadas)
  useEffect(() => {
    cargarSubcategorias();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    debouncedSearch,
    filters.filtroStock, filters.filtroPrecio,
    filters.marcasSeleccionadas, filters.filtroRebate, filters.filtroOferta,
    filters.filtroWebTransf, filters.filtroTiendaNube,
    filters.filtroMarkupClasica, filters.filtroMarkupRebate,
    filters.filtroMarkupOferta, filters.filtroMarkupWebTransf,
    filters.filtroOutOfCards, filters.coloresSeleccionados,
    filters.filtrosAuditoria,
  ]);

  return {
    // Productos
    productos,
    setProductos,
    loading,
    totalProductos,

    // Stats
    stats,

    // Filter options (loaded from API)
    marcas,
    subcategorias,
    usuarios,
    tiposAccion,
    pms,
    marcasPorPM,
    subcategoriasPorPM,

    // Config & rates
    markupWebTarjeta,
    dolarVenta,

    // Auditoría
    auditoriaVisible,
    setAuditoriaVisible,
    auditoriaData,
    verAuditoria,

    // Reload functions (called from other hooks/components after mutations)
    cargarProductos,
    cargarStats,
  };
}
