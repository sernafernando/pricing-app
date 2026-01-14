import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * Custom hook para manejar TODOS los filtros de la vista Tienda
 * Consolida 25+ useState de filtros en un solo hook reutilizable
 */
export function useTiendaFilters() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [filtrosInicializados, setFiltrosInicializados] = useState(false);

  // Filtros básicos
  const [searchInput, setSearchInput] = useState('');
  const [filtroStock, setFiltroStock] = useState("todos");
  const [filtroPrecio, setFiltroPrecio] = useState("todos");
  
  // Filtros de selección múltiple
  const [marcasSeleccionadas, setMarcasSeleccionadas] = useState([]);
  const [subcategoriasSeleccionadas, setSubcategoriasSeleccionadas] = useState([]);
  const [pmsSeleccionados, setPmsSeleccionados] = useState([]);
  const [coloresSeleccionados, setColoresSeleccionados] = useState([]);
  
  // Filtros booleanos
  const [filtroRebate, setFiltroRebate] = useState(null);
  const [filtroOferta, setFiltroOferta] = useState(null);
  const [filtroWebTransf, setFiltroWebTransf] = useState(null);
  const [filtroTiendaNube, setFiltroTiendaNube] = useState(null);
  const [filtroOutOfCards, setFiltroOutOfCards] = useState(null);
  const [filtroMLA, setFiltroMLA] = useState(null);
  const [filtroEstadoMLA, setFiltroEstadoMLA] = useState(null);
  const [filtroNuevos, setFiltroNuevos] = useState(null);
  
  // Filtros de markup
  const [filtroMarkupClasica, setFiltroMarkupClasica] = useState(null);
  const [filtroMarkupRebate, setFiltroMarkupRebate] = useState(null);
  const [filtroMarkupOferta, setFiltroMarkupOferta] = useState(null);
  const [filtroMarkupWebTransf, setFiltroMarkupWebTransf] = useState(null);
  
  // Filtros de auditoría
  const [filtrosAuditoria, setFiltrosAuditoria] = useState({
    usuarios: [],
    tipos_accion: [],
    fecha_desde: '',
    fecha_hasta: ''
  });

  // Cargar filtros desde URL al montar (solo una vez)
  useEffect(() => {
    loadFiltersFromURL();
    setFiltrosInicializados(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sincronizar filtros a URL cuando cambian
  useEffect(() => {
    if (filtrosInicializados) {
      syncFiltersToURL();
    }
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
    coloresSeleccionados,
    filtrosAuditoria
  ]);

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
    const colores = searchParams.get('colores');
    const auditUsuarios = searchParams.get('audit_usuarios');
    const auditTipos = searchParams.get('audit_tipos');
    const auditDesde = searchParams.get('audit_desde');
    const auditHasta = searchParams.get('audit_hasta');

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
    if (colores) setColoresSeleccionados(colores.split(',').map(c => c.trim()).filter(Boolean));

    if (auditUsuarios || auditTipos || auditDesde || auditHasta) {
      setFiltrosAuditoria({
        usuarios: auditUsuarios ? auditUsuarios.split(',').map(u => u.trim()).filter(Boolean) : [],
        tipos_accion: auditTipos ? auditTipos.split(',').map(t => t.trim()).filter(Boolean) : [],
        fecha_desde: auditDesde || '',
        fecha_hasta: auditHasta || ''
      });
    }
  };

  const syncFiltersToURL = () => {
    const params = new URLSearchParams();

    if (searchInput) params.set('search', searchInput);
    if (filtroStock && filtroStock !== 'todos') params.set('stock', filtroStock);
    if (filtroPrecio && filtroPrecio !== 'todos') params.set('precio', filtroPrecio);
    if (marcasSeleccionadas.length > 0) params.set('marcas', marcasSeleccionadas.join(','));
    if (subcategoriasSeleccionadas.length > 0) params.set('subcats', subcategoriasSeleccionadas.join(','));
    if (pmsSeleccionados.length > 0) params.set('pms', pmsSeleccionados.join(','));
    if (filtroRebate) params.set('rebate', filtroRebate);
    if (filtroOferta) params.set('oferta', filtroOferta);
    if (filtroWebTransf) params.set('webtransf', filtroWebTransf);
    if (filtroTiendaNube) params.set('tiendanube', filtroTiendaNube);
    if (filtroMarkupClasica) params.set('mkclasica', filtroMarkupClasica);
    if (filtroMarkupRebate) params.set('mkrebate', filtroMarkupRebate);
    if (filtroMarkupOferta) params.set('mkoferta', filtroMarkupOferta);
    if (filtroMarkupWebTransf) params.set('mkwebtransf', filtroMarkupWebTransf);
    if (filtroOutOfCards) params.set('outofcards', filtroOutOfCards);
    if (filtroMLA) params.set('mla', filtroMLA);
    if (filtroEstadoMLA) params.set('estado_mla', filtroEstadoMLA);
    if (filtroNuevos) params.set('nuevos', filtroNuevos);
    if (coloresSeleccionados.length > 0) params.set('colores', coloresSeleccionados.join(','));
    if (filtrosAuditoria.usuarios.length > 0) params.set('audit_usuarios', filtrosAuditoria.usuarios.join(','));
    if (filtrosAuditoria.tipos_accion.length > 0) params.set('audit_tipos', filtrosAuditoria.tipos_accion.join(','));
    if (filtrosAuditoria.fecha_desde) params.set('audit_desde', filtrosAuditoria.fecha_desde);
    if (filtrosAuditoria.fecha_hasta) params.set('audit_hasta', filtrosAuditoria.fecha_hasta);

    setSearchParams(params, { replace: true });
  };

  const limpiarTodosFiltros = () => {
    setSearchInput('');
    setFiltroStock("todos");
    setFiltroPrecio("todos");
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
    setSearchParams({}, { replace: true });
  };

  // Helper para construir params de API
  const construirFiltrosParams = (opciones = {}) => {
    const { 
      incluirMarcas = true, 
      incluirSubcategorias = true,
      incluirAuditoria = true 
    } = opciones;
    
    const params = {};
    
    if (searchInput) params.search = searchInput;
    if (filtroStock === 'con_stock') params.con_stock = true;
    if (filtroStock === 'sin_stock') params.con_stock = false;
    if (filtroPrecio === 'con_precio') params.con_precio = true;
    if (filtroPrecio === 'sin_precio') params.con_precio = false;
    
    if (incluirMarcas && marcasSeleccionadas.length > 0) {
      params.marcas = marcasSeleccionadas.join(',');
    }
    if (incluirSubcategorias && subcategoriasSeleccionadas.length > 0) {
      params.subcategorias = subcategoriasSeleccionadas.join(',');
    }
    
    if (incluirAuditoria) {
      if (filtrosAuditoria.usuarios.length > 0) params.audit_usuarios = filtrosAuditoria.usuarios.join(',');
      if (filtrosAuditoria.tipos_accion.length > 0) params.audit_tipos_accion = filtrosAuditoria.tipos_accion.join(',');
      if (filtrosAuditoria.fecha_desde) params.audit_fecha_desde = filtrosAuditoria.fecha_desde;
      if (filtrosAuditoria.fecha_hasta) params.audit_fecha_hasta = filtrosAuditoria.fecha_hasta;
    }
    
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
    if (coloresSeleccionados.length > 0) params.colores = coloresSeleccionados.join(',');
    if (pmsSeleccionados.length > 0) params.pms = pmsSeleccionados.join(',');
    
    return params;
  };

  return {
    // Estados
    searchInput,
    filtroStock,
    filtroPrecio,
    marcasSeleccionadas,
    subcategoriasSeleccionadas,
    pmsSeleccionados,
    coloresSeleccionados,
    filtroRebate,
    filtroOferta,
    filtroWebTransf,
    filtroTiendaNube,
    filtroOutOfCards,
    filtroMLA,
    filtroEstadoMLA,
    filtroNuevos,
    filtroMarkupClasica,
    filtroMarkupRebate,
    filtroMarkupOferta,
    filtroMarkupWebTransf,
    filtrosAuditoria,
    filtrosInicializados,
    
    // Setters
    setSearchInput,
    setFiltroStock,
    setFiltroPrecio,
    setMarcasSeleccionadas,
    setSubcategoriasSeleccionadas,
    setPmsSeleccionados,
    setColoresSeleccionados,
    setFiltroRebate,
    setFiltroOferta,
    setFiltroWebTransf,
    setFiltroTiendaNube,
    setFiltroOutOfCards,
    setFiltroMLA,
    setFiltroEstadoMLA,
    setFiltroNuevos,
    setFiltroMarkupClasica,
    setFiltroMarkupRebate,
    setFiltroMarkupOferta,
    setFiltroMarkupWebTransf,
    setFiltrosAuditoria,
    
    // Helpers
    construirFiltrosParams,
    limpiarTodosFiltros
  };
}
