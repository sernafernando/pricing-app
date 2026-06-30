import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useDebounce } from './useDebounce';

/**
 * Owns all filter state + URL-sync loop for the Productos page.
 *
 * Mirrors useTiendaFilters pattern:
 *   - ~25 filter states
 *   - loadFiltersFromURL (mount)
 *   - syncFiltersToURL (on change, guarded by filtrosInicializados)
 *   - construirFiltrosParams (memoized via useCallback — ADR-3)
 *   - handleOrdenar, limpiarTodosFiltros, limpiarFiltros, aplicarFiltroStat
 *
 * Returns all filter values + setters + helpers for the composition root
 * (Productos.jsx) and for injection into useProductosData.
 *
 * INV-4: the ENTIRE useSearchParams read/write loop lives here — never split.
 */
export function useProductosFilters() {
  const [searchInput, setSearchInput] = useState('');
  const [page, setPage] = useState(1);
  const [filtroStock, setFiltroStock] = useState('todos');
  const [filtroPrecio, setFiltroPrecio] = useState('todos');
  const [pageSize, setPageSize] = useState(50);
  const [marcasSeleccionadas, setMarcasSeleccionadas] = useState([]);
  const [ordenColumnas, setOrdenColumnas] = useState([]);
  const [subcategoriasSeleccionadas, setSubcategoriasSeleccionadas] = useState([]);
  const [filtrosAuditoria, setFiltrosAuditoria] = useState({
    usuarios: [],
    tipos_accion: [],
    fecha_desde: '',
    fecha_hasta: ''
  });
  const [panelFiltroActivo, setPanelFiltroActivo] = useState(null); // 'marcas', 'subcategorias', 'auditoria', null
  const [filtroRebate, setFiltroRebate] = useState(null);
  const [filtroOferta, setFiltroOferta] = useState(null);
  const [filtroWebTransf, setFiltroWebTransf] = useState(null);
  const [filtroTiendaNube, setFiltroTiendaNube] = useState(null); // con_descuento, sin_descuento, no_publicado
  const [filtroMarkupClasica, setFiltroMarkupClasica] = useState(null);
  const [filtroMarkupRebate, setFiltroMarkupRebate] = useState(null);
  const [filtroMarkupOferta, setFiltroMarkupOferta] = useState(null);
  const [filtroMarkupWebTransf, setFiltroMarkupWebTransf] = useState(null);
  const [filtroOutOfCards, setFiltroOutOfCards] = useState(null);
  const [filtroMLA, setFiltroMLA] = useState(null); // con_mla, sin_mla
  const [filtroEstadoMLA, setFiltroEstadoMLA] = useState(null); // 'activa', 'pausada'
  const [filtroNuevos, setFiltroNuevos] = useState(null); // ultimos_7_dias
  const [filtroTiendaOficial, setFiltroTiendaOficial] = useState(null); // '57997', '2645', '144', '191942'
  const [mostrarFiltrosAvanzados, setMostrarFiltrosAvanzados] = useState(false);
  const [coloresSeleccionados, setColoresSeleccionados] = useState([]);
  const [pmsSeleccionados, setPmsSeleccionados] = useState([]);
  const [filtrosInicializados, setFiltrosInicializados] = useState(false);

  // URL sync (INV-4: entire loop lives here — never split)
  const [searchParams, setSearchParams] = useSearchParams();

  // Debounced search — lives here because searchInput is a filter state
  const debouncedSearch = useDebounce(searchInput, 500);

  // Función para sincronizar filtros a la URL
  const syncFiltersToURL = () => {
    const params = new URLSearchParams();

    // Search
    if (searchInput) params.set('search', searchInput);

    // Stock
    if (filtroStock && filtroStock !== 'todos') params.set('stock', filtroStock);

    // Precio
    if (filtroPrecio && filtroPrecio !== 'todos') params.set('precio', filtroPrecio);

    // Marcas (array -> comma separated string)
    if (marcasSeleccionadas.length > 0) params.set('marcas', marcasSeleccionadas.join(','));

    // Subcategorías
    if (subcategoriasSeleccionadas.length > 0) params.set('subcats', subcategoriasSeleccionadas.join(','));

    // PMs
    if (pmsSeleccionados.length > 0) params.set('pms', pmsSeleccionados.join(','));

    // Rebate
    if (filtroRebate) params.set('rebate', filtroRebate);

    // Oferta
    if (filtroOferta) params.set('oferta', filtroOferta);

    // Web Transf
    if (filtroWebTransf) params.set('webtransf', filtroWebTransf);

    // Tienda Nube
    if (filtroTiendaNube) params.set('tiendanube', filtroTiendaNube);

    // Markup Clásica
    if (filtroMarkupClasica) params.set('mkclasica', filtroMarkupClasica);

    // Markup Rebate
    if (filtroMarkupRebate) params.set('mkrebate', filtroMarkupRebate);

    // Markup Oferta
    if (filtroMarkupOferta) params.set('mkoferta', filtroMarkupOferta);

    // Markup Web Transf
    if (filtroMarkupWebTransf) params.set('mkwebtransf', filtroMarkupWebTransf);

    // Out of Cards
    if (filtroOutOfCards) params.set('outofcards', filtroOutOfCards);

    // MLA
    if (filtroMLA) params.set('mla', filtroMLA);

    // Estado MLA
    if (filtroEstadoMLA) params.set('estado_mla', filtroEstadoMLA);

    // Nuevos
    if (filtroNuevos) params.set('nuevos', filtroNuevos);

    // Tienda Oficial
    if (filtroTiendaOficial) params.set('tienda_oficial', filtroTiendaOficial);

    // Colores
    if (coloresSeleccionados.length > 0) params.set('colores', coloresSeleccionados.join(','));

    // Página
    if (page > 1) params.set('page', page.toString());

    // Page Size
    if (pageSize !== 50) params.set('pagesize', pageSize.toString());

    // Filtros de Auditoría
    if (filtrosAuditoria.usuarios.length > 0) params.set('audit_usuarios', filtrosAuditoria.usuarios.join(','));
    if (filtrosAuditoria.tipos_accion.length > 0) params.set('audit_tipos', filtrosAuditoria.tipos_accion.join(','));
    if (filtrosAuditoria.fecha_desde) params.set('audit_desde', filtrosAuditoria.fecha_desde);
    if (filtrosAuditoria.fecha_hasta) params.set('audit_hasta', filtrosAuditoria.fecha_hasta);

    setSearchParams(params, { replace: true });
  };

  // Función para cargar filtros desde la URL
  const loadFiltersFromURL = () => {
    const search = searchParams.get('search');
    const stock = searchParams.get('stock');
    const precio = searchParams.get('precio');
    const marcas = searchParams.get('marcas');
    const subcats = searchParams.get('subcats');
    const pms = searchParams.get('pms');
    const rebate = searchParams.get('rebate');
    const oferta = searchParams.get('oferta');
    const webtransf = searchParams.get('webtransf');
    const tiendanube = searchParams.get('tiendanube');
    const mkclasica = searchParams.get('mkclasica');
    const mkrebate = searchParams.get('mkrebate');
    const mkoferta = searchParams.get('mkoferta');
    const mkwebtransf = searchParams.get('mkwebtransf');
    const outofcards = searchParams.get('outofcards');
    const mla = searchParams.get('mla');
    const estado_mla = searchParams.get('estado_mla');
    const nuevos = searchParams.get('nuevos');
    const tienda_oficial = searchParams.get('tienda_oficial');
    const colores = searchParams.get('colores');
    const pageParam = searchParams.get('page');
    const pagesizeParam = searchParams.get('pagesize');
    const auditUsuarios = searchParams.get('audit_usuarios');
    const auditTipos = searchParams.get('audit_tipos');
    const auditDesde = searchParams.get('audit_desde');
    const auditHasta = searchParams.get('audit_hasta');

    // Setear estados desde URL
    if (search) setSearchInput(search);
    if (stock) setFiltroStock(stock);
    if (precio) setFiltroPrecio(precio);
    if (marcas) setMarcasSeleccionadas(marcas.split(',').map(m => m.trim()).filter(Boolean));
    if (subcats) setSubcategoriasSeleccionadas(subcats.split(',').map(s => s.trim()).filter(Boolean));
    if (pms) setPmsSeleccionados(pms.split(',').map(p => p.trim()).filter(Boolean));
    if (rebate) setFiltroRebate(rebate);
    if (oferta) setFiltroOferta(oferta);
    if (webtransf) setFiltroWebTransf(webtransf);
    if (tiendanube) setFiltroTiendaNube(tiendanube);
    if (mkclasica) setFiltroMarkupClasica(mkclasica);
    if (mkrebate) setFiltroMarkupRebate(mkrebate);
    if (mkoferta) setFiltroMarkupOferta(mkoferta);
    if (mkwebtransf) setFiltroMarkupWebTransf(mkwebtransf);
    if (outofcards) setFiltroOutOfCards(outofcards);
    if (mla) setFiltroMLA(mla);
    if (estado_mla) setFiltroEstadoMLA(estado_mla);
    if (nuevos) setFiltroNuevos(nuevos);
    if (tienda_oficial) setFiltroTiendaOficial(tienda_oficial);
    if (colores) setColoresSeleccionados(colores.split(',').map(c => c.trim()).filter(Boolean));
    if (pageParam) setPage(parseInt(pageParam, 10));
    if (pagesizeParam) setPageSize(parseInt(pagesizeParam, 10));

    // Filtros de Auditoría
    if (auditUsuarios || auditTipos || auditDesde || auditHasta) {
      setFiltrosAuditoria({
        usuarios: auditUsuarios ? auditUsuarios.split(',').map(u => u.trim()).filter(Boolean) : [],
        tipos_accion: auditTipos ? auditTipos.split(',').map(t => t.trim()).filter(Boolean) : [],
        fecha_desde: auditDesde || '',
        fecha_hasta: auditHasta || ''
      });
    }
  };

  // useEffect inicial: cargar filtros desde URL al montar el componente
  useEffect(() => {
    loadFiltersFromURL();
    // Marcar que los filtros ya fueron inicializados
    setFiltrosInicializados(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Solo al montar — loadFiltersFromURL estable

  // useEffect para sincronizar filtros a URL cuando cambian
  useEffect(() => {
    // Solo sincronizar después de que los filtros fueron inicializados desde URL
    if (filtrosInicializados) {
      syncFiltersToURL();
    }
    // syncFiltersToURL se recrea cada render — sincronizar solo cuando cambian los filtros listados
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    filtrosInicializados,
    searchInput,
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
    filtroMLA,
    filtroEstadoMLA,
    filtroNuevos,
    filtroTiendaOficial,
    coloresSeleccionados,
    page,
    pageSize,
    filtrosAuditoria
  ]);

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

  const limpiarTodosFiltros = () => {
    setSearchInput('');
    setFiltroStock('todos');
    setFiltroPrecio('todos');
    setMarcasSeleccionadas([]);
    setSubcategoriasSeleccionadas([]);
    setPmsSeleccionados([]);
    setFiltrosAuditoria({
      usuarios: [],
      tipos_accion: [],
      fecha_desde: '',
      fecha_hasta: ''
    });
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
    setOrdenColumnas([]);
    setPage(1);

    // Limpiar también la URL
    setSearchParams({}, { replace: true });
  };

  // Funciones para aplicar filtros desde las stats
  const aplicarFiltroStat = (filtros) => {
    // Limpiar los filtros que no están siendo aplicados
    if (filtros.stock === undefined) setFiltroStock('todos');
    else setFiltroStock(filtros.stock);

    if (filtros.precio === undefined) setFiltroPrecio('todos');
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
    if (filtros.webTransf === undefined) setFiltroWebTransf(null);
    else setFiltroWebTransf(filtros.webTransf);

    setFiltroOutOfCards(null);

    setPage(1);
  };

  const limpiarFiltros = () => {
    setFiltroStock('todos');
    setFiltroPrecio('todos');
    setFiltroRebate(null);
    setFiltroOferta(null);
    setFiltroWebTransf(null);
    setFiltroTiendaNube(null);
    setFiltroMarkupClasica(null);
    setFiltroMarkupRebate(null);
    setFiltroMarkupOferta(null);
    setFiltroMarkupWebTransf(null);
    setFiltroMLA(null);
    setFiltroNuevos(null);
    setPage(1);
  };

  /**
   * construirFiltrosParams — memoized via useCallback (ADR-3).
   * Builds the base filter params object for API calls (without pagination).
   * Used by useProductosData in Slice 8b.
   */
  const construirFiltrosParams = useCallback(() => {
    const params = {};
    if (debouncedSearch) params.search = debouncedSearch;
    if (filtroStock === 'con_stock') params.con_stock = true;
    if (filtroStock === 'sin_stock') params.con_stock = false;
    if (filtroPrecio === 'con_precio') params.con_precio = true;
    if (filtroPrecio === 'sin_precio') params.con_precio = false;
    if (marcasSeleccionadas.length > 0) params.marcas = marcasSeleccionadas.join(',');
    if (subcategoriasSeleccionadas.length > 0) params.subcategorias = subcategoriasSeleccionadas.join(',');
    if (filtrosAuditoria.usuarios.length > 0) params.audit_usuarios = filtrosAuditoria.usuarios.join(',');
    if (filtrosAuditoria.tipos_accion.length > 0) params.audit_tipos_accion = filtrosAuditoria.tipos_accion.join(',');
    if (filtrosAuditoria.fecha_desde) params.audit_fecha_desde = filtrosAuditoria.fecha_desde;
    if (filtrosAuditoria.fecha_hasta) params.audit_fecha_hasta = filtrosAuditoria.fecha_hasta;
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
    if (filtroMLA === 'con_mla') params.con_mla = true;
    if (filtroMLA === 'sin_mla') params.con_mla = false;
    if (filtroEstadoMLA === 'activa') params.estado_mla = 'activa';
    if (filtroEstadoMLA === 'pausada') params.estado_mla = 'pausada';
    if (filtroNuevos === 'ultimos_7_dias') params.nuevos_ultimos_7_dias = true;
    if (filtroTiendaOficial) params.tienda_oficial = filtroTiendaOficial;
    if (coloresSeleccionados.length > 0) params.colores = coloresSeleccionados.join(',');
    if (pmsSeleccionados.length > 0) params.pms = pmsSeleccionados.join(',');
    return params;
  }, [
    debouncedSearch, filtroStock, filtroPrecio, marcasSeleccionadas, subcategoriasSeleccionadas,
    filtrosAuditoria, filtroRebate, filtroOferta, filtroWebTransf, filtroTiendaNube,
    filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf,
    filtroOutOfCards, filtroMLA, filtroEstadoMLA, filtroNuevos, filtroTiendaOficial,
    coloresSeleccionados, pmsSeleccionados,
  ]);

  return {
    // Search + pagination
    searchInput, setSearchInput,
    debouncedSearch,
    page, setPage,
    pageSize, setPageSize,
    ordenColumnas, setOrdenColumnas,
    // Stock/precio filters
    filtroStock, setFiltroStock,
    filtroPrecio, setFiltroPrecio,
    // Multi-select filters
    marcasSeleccionadas, setMarcasSeleccionadas,
    subcategoriasSeleccionadas, setSubcategoriasSeleccionadas,
    pmsSeleccionados, setPmsSeleccionados,
    coloresSeleccionados, setColoresSeleccionados,
    // Boolean filters
    filtroRebate, setFiltroRebate,
    filtroOferta, setFiltroOferta,
    filtroWebTransf, setFiltroWebTransf,
    filtroTiendaNube, setFiltroTiendaNube,
    filtroMarkupClasica, setFiltroMarkupClasica,
    filtroMarkupRebate, setFiltroMarkupRebate,
    filtroMarkupOferta, setFiltroMarkupOferta,
    filtroMarkupWebTransf, setFiltroMarkupWebTransf,
    filtroOutOfCards, setFiltroOutOfCards,
    filtroMLA, setFiltroMLA,
    filtroEstadoMLA, setFiltroEstadoMLA,
    filtroNuevos, setFiltroNuevos,
    filtroTiendaOficial, setFiltroTiendaOficial,
    // Audit filters
    filtrosAuditoria, setFiltrosAuditoria,
    // UI filter panel state
    panelFiltroActivo, setPanelFiltroActivo,
    mostrarFiltrosAvanzados, setMostrarFiltrosAvanzados,
    // Handlers
    handleOrdenar,
    limpiarTodosFiltros,
    limpiarFiltros,
    aplicarFiltroStat,
    // Memoized params builder (for useProductosData in Slice 8b)
    construirFiltrosParams,
  };
}
