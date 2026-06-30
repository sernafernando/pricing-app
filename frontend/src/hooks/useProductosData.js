import { useState, useEffect, useCallback } from 'react';
import { productosAPI } from '../services/api';
import api from '../services/api';

/**
 * Owns all data state for the Productos page:
 *   productos, loading, stats, totalProductos,
 *   marcas, subcategorias, pms, marcasPorPM, subcategoriasPorPM
 *
 * Also owns all data-loading functions:
 *   cargarProductos, cargarStats, cargarMarcas, cargarSubcategorias, cargarPMs.
 *
 * DECISION 1 (ADR-1+ADR-2):
 *   cargarStats is owned here and wrapped in useCallback.
 *   It uses construirFiltrosParams() from useProductosFilters (memoized, ADR-3).
 *   Dep array is [construirFiltrosParams] — the stale showToast dep from the
 *   interim (page-level) implementation is dropped here; the catch is silent.
 *
 * Receives:
 *   { construirFiltrosParams, page, pageSize, ordenColumnas, filters, showToast }
 *   where `filters` is an object with all individual filter values that
 *   cargarMarcas / cargarSubcategorias need to build their custom params.
 *
 * Returns all state + setters + loaders for injection into mutation hooks and JSX.
 *
 * Mirrors useTiendaData pattern.
 */
export function useProductosData({
  construirFiltrosParams,
  page,
  pageSize,
  ordenColumnas,
  filters,
  showToast,
}) {
  const {
    debouncedSearch,
    filtroStock,
    filtroPrecio,
    marcasSeleccionadas,
    subcategoriasSeleccionadas,
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
    pmsSeleccionados,
    filtrosAuditoria,
  } = filters;

  const [productos, setProductos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState(null);
  const [totalProductos, setTotalProductos] = useState(0);
  const [marcas, setMarcas] = useState([]);
  const [subcategorias, setSubcategorias] = useState([]);
  const [pms, setPms] = useState([]);
  const [marcasPorPM, setMarcasPorPM] = useState([]);
  const [subcategoriasPorPM, setSubcategoriasPorPM] = useState([]);

  /**
   * cargarStats — OWNED here (ADR-2).
   * Uses construirFiltrosParams() for the full filter param set.
   * showToast dep dropped — catch is intentionally silent (no toast on stats error).
   */
  const cargarStats = useCallback(async () => {
    try {
      const params = construirFiltrosParams();
      const statsRes = await productosAPI.statsDinamicos(params);
      setStats(statsRes.data);
    } catch {
      // Error silencioso, no afecta funcionalidad principal
    }
  }, [construirFiltrosParams]);

  /**
   * cargarProductos — uses construirFiltrosParams() + pagination + ordering.
   */
  const cargarProductos = useCallback(async () => {
    setLoading(true);
    try {
      const params = { ...construirFiltrosParams(), page, page_size: pageSize };
      if (ordenColumnas.length > 0) {
        params.orden_campos = ordenColumnas.map(o => o.columna).join(',');
        params.orden_direcciones = ordenColumnas.map(o => o.direccion).join(',');
      }
      const productosRes = await productosAPI.listar(params);
      setTotalProductos(productosRes.data.total || productosRes.data.productos.length);
      setProductos(productosRes.data.productos);
    } catch {
      showToast('Error al cargar productos', 'error');
    } finally {
      setLoading(false);
    }
  }, [construirFiltrosParams, page, pageSize, ordenColumnas, showToast]);

  /**
   * cargarMarcas — builds its own params (excludes marcasSeleccionadas).
   * Mirrors the original in Productos.jsx.
   */
  const cargarMarcas = useCallback(async () => {
    try {
      const params = {};
      if (debouncedSearch) params.search = debouncedSearch;
      if (filtroStock === 'con_stock') params.con_stock = true;
      if (filtroStock === 'sin_stock') params.con_stock = false;
      if (filtroPrecio === 'con_precio') params.con_precio = true;
      if (filtroPrecio === 'sin_precio') params.con_precio = false;
      if (subcategoriasSeleccionadas.length > 0) params.subcategorias = subcategoriasSeleccionadas.join(',');
      if (filtroRebate === 'con_rebate') params.con_rebate = true;
      if (filtroRebate === 'sin_rebate') params.con_rebate = false;
      if (filtroOferta === 'con_oferta') params.con_oferta = true;
      if (filtroOferta === 'sin_oferta') params.con_oferta = false;
      if (filtroWebTransf === 'con_web_transf') params.con_web_transf = true;
      if (filtroWebTransf === 'sin_web_transf') params.con_web_transf = false;
      if (filtroTiendaNube === 'con_descuento') params.tn_con_descuento = true;
      if (filtroTiendaNube === 'sin_descuento') params.tn_sin_descuento = true;
      if (filtroTiendaNube === 'no_publicado') params.tn_no_publicado = true;
      if (filtroMarkupClasica === 'positivo') params.markup_clasica_positivo = true;
      if (filtroMarkupClasica === 'negativo') params.markup_clasica_positivo = false;
      if (filtroMarkupRebate === 'positivo') params.markup_rebate_positivo = true;
      if (filtroMarkupRebate === 'negativo') params.markup_rebate_positivo = false;
      if (filtroMarkupOferta === 'positivo') params.markup_oferta_positivo = true;
      if (filtroMarkupOferta === 'negativo') params.markup_oferta_positivo = false;
      if (filtroMarkupWebTransf === 'positivo') params.markup_web_transf_positivo = true;
      if (filtroMarkupWebTransf === 'negativo') params.markup_web_transf_positivo = false;
      if (filtroOutOfCards === 'con_out_of_cards') params.out_of_cards = true;
      if (filtroOutOfCards === 'sin_out_of_cards') params.out_of_cards = false;
      if (coloresSeleccionados.length > 0) params.colores = coloresSeleccionados.join(',');
      if (filtrosAuditoria.usuarios.length > 0) params.audit_usuarios = filtrosAuditoria.usuarios.join(',');
      if (filtrosAuditoria.tipos_accion.length > 0) params.audit_tipos_accion = filtrosAuditoria.tipos_accion.join(',');
      if (filtrosAuditoria.fecha_desde) params.audit_fecha_desde = filtrosAuditoria.fecha_desde;
      if (filtrosAuditoria.fecha_hasta) params.audit_fecha_hasta = filtrosAuditoria.fecha_hasta;
      if (pmsSeleccionados.length > 0) params.pms = pmsSeleccionados.join(',');
      const response = await productosAPI.marcas(params);
      setMarcas(response.data.marcas);
    } catch {
      showToast('Error al cargar marcas', 'error');
    }
  }, [
    debouncedSearch, filtroStock, filtroPrecio, subcategoriasSeleccionadas,
    filtroRebate, filtroOferta, filtroWebTransf, filtroTiendaNube,
    filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf,
    filtroOutOfCards, coloresSeleccionados, filtrosAuditoria, pmsSeleccionados, showToast,
  ]);

  /**
   * cargarSubcategorias — builds its own params (excludes subcategoriasSeleccionadas).
   */
  const cargarSubcategorias = useCallback(async () => {
    try {
      const params = {};
      if (debouncedSearch) params.search = debouncedSearch;
      if (filtroStock === 'con_stock') params.con_stock = true;
      if (filtroStock === 'sin_stock') params.con_stock = false;
      if (filtroPrecio === 'con_precio') params.con_precio = true;
      if (filtroPrecio === 'sin_precio') params.con_precio = false;
      if (marcasSeleccionadas.length > 0) params.marcas = marcasSeleccionadas.join(',');
      if (filtroRebate === 'con_rebate') params.con_rebate = true;
      if (filtroRebate === 'sin_rebate') params.con_rebate = false;
      if (filtroOferta === 'con_oferta') params.con_oferta = true;
      if (filtroOferta === 'sin_oferta') params.con_oferta = false;
      if (filtroWebTransf === 'con_web_transf') params.con_web_transf = true;
      if (filtroWebTransf === 'sin_web_transf') params.con_web_transf = false;
      if (filtroTiendaNube === 'con_descuento') params.tn_con_descuento = true;
      if (filtroTiendaNube === 'sin_descuento') params.tn_sin_descuento = true;
      if (filtroTiendaNube === 'no_publicado') params.tn_no_publicado = true;
      if (filtroMarkupClasica === 'positivo') params.markup_clasica_positivo = true;
      if (filtroMarkupClasica === 'negativo') params.markup_clasica_positivo = false;
      if (filtroMarkupRebate === 'positivo') params.markup_rebate_positivo = true;
      if (filtroMarkupRebate === 'negativo') params.markup_rebate_positivo = false;
      if (filtroMarkupOferta === 'positivo') params.markup_oferta_positivo = true;
      if (filtroMarkupOferta === 'negativo') params.markup_oferta_positivo = false;
      if (filtroMarkupWebTransf === 'positivo') params.markup_web_transf_positivo = true;
      if (filtroMarkupWebTransf === 'negativo') params.markup_web_transf_positivo = false;
      if (filtroOutOfCards === 'con_out_of_cards') params.out_of_cards = true;
      if (filtroOutOfCards === 'sin_out_of_cards') params.out_of_cards = false;
      if (coloresSeleccionados.length > 0) params.colores = coloresSeleccionados.join(',');
      if (filtrosAuditoria.usuarios.length > 0) params.audit_usuarios = filtrosAuditoria.usuarios.join(',');
      if (filtrosAuditoria.tipos_accion.length > 0) params.audit_tipos_accion = filtrosAuditoria.tipos_accion.join(',');
      if (filtrosAuditoria.fecha_desde) params.audit_fecha_desde = filtrosAuditoria.fecha_desde;
      if (filtrosAuditoria.fecha_hasta) params.audit_fecha_hasta = filtrosAuditoria.fecha_hasta;
      if (pmsSeleccionados.length > 0) params.pms = pmsSeleccionados.join(',');
      const response = await productosAPI.subcategorias(params);
      setSubcategorias(response.data.categorias);
    } catch {
      showToast('Error al cargar subcategorías', 'error');
    }
  }, [
    debouncedSearch, filtroStock, filtroPrecio, marcasSeleccionadas,
    filtroRebate, filtroOferta, filtroWebTransf, filtroTiendaNube,
    filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf,
    filtroOutOfCards, coloresSeleccionados, filtrosAuditoria, pmsSeleccionados, showToast,
  ]);

  const cargarPMs = useCallback(async () => {
    try {
      const response = await api.get('/usuarios/pms?solo_con_marcas=true');
      setPms(response.data);
    } catch {
      showToast('Error al cargar PMs', 'error');
    }
  }, [showToast]);

  // Cargar PMs al montar
  useEffect(() => {
    cargarPMs();
  }, [cargarPMs]);

  // Cargar productos cuando cambian filtros / paginación
  useEffect(() => {
    cargarProductos();
  }, [cargarProductos]);

  // Cargar stats dinámicos cuando cambian filtros
  useEffect(() => {
    cargarStats();
  }, [cargarStats]);

  // Cargar marcas cuando cambian filtros (excepto marcasSeleccionadas)
  useEffect(() => {
    cargarMarcas();
  }, [cargarMarcas]);

  // Cargar subcategorías cuando cambian filtros (excepto subcategoriasSeleccionadas)
  useEffect(() => {
    cargarSubcategorias();
  }, [cargarSubcategorias]);

  // Cargar marcas y subcategorías cuando se seleccionan PMs
  useEffect(() => {
    const cargarDatosPorPM = async () => {
      if (pmsSeleccionados.length > 0) {
        try {
          const [marcasRes, subcatsRes] = await Promise.all([
            productosAPI.obtenerMarcasPorPMs(pmsSeleccionados.join(',')),
            productosAPI.obtenerSubcategoriasPorPMs(pmsSeleccionados.join(','))
          ]);
          setMarcasPorPM(marcasRes.data.marcas);
          setSubcategoriasPorPM(subcatsRes.data.subcategorias.map(s => s.id));
        } catch {
          setMarcasPorPM([]);
          setSubcategoriasPorPM([]);
        }
      } else {
        setMarcasPorPM([]);
        setSubcategoriasPorPM([]);
      }
    };
    cargarDatosPorPM();
  }, [pmsSeleccionados]);

  return {
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
  };
}
