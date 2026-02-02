import { useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { productosAPI } from '../services/api';
import PricingModalTesla from '../components/PricingModalTesla';
import { useDebounce } from '../hooks/useDebounce';
import axios from 'axios';
import { useAuthStore } from '../store/authStore';
import { usePermisos } from '../contexts/PermisosContext';
import ExportModal from '../components/ExportModal';
import xlsIcon from '../assets/xls.svg';
import CalcularWebModal from '../components/CalcularWebModal';
import CalcularPVPModal from '../components/CalcularPVPModal';
import ModalInfoProducto from '../components/ModalInfoProducto';
import StatCard from '../components/StatCard';
import './Productos.css';

// Constantes para filtros
const FILTER_VALUES = {
  TODOS: 'todos',
  CON_STOCK: 'con_stock',
  SIN_STOCK: 'sin_stock',
  CON_PRECIO: 'con_precio',
  SIN_PRECIO: 'sin_precio',
  CON_REBATE: 'con_rebate',
  SIN_REBATE: 'sin_rebate',
  CON_OFERTA: 'con_oferta',
  SIN_OFERTA: 'sin_oferta',
  CON_WEB_TRANSF: 'con_web_transf',
  SIN_WEB_TRANSF: 'sin_web_transf',
  CON_DESCUENTO: 'con_descuento',
  SIN_DESCUENTO: 'sin_descuento',
  NO_PUBLICADO: 'no_publicado',
  POSITIVO: 'positivo',
  NEGATIVO: 'negativo',
  CON_OUT_OF_CARDS: 'con_out_of_cards',
  SIN_OUT_OF_CARDS: 'sin_out_of_cards'
};

export default function Productos() {
  const [productos, setProductos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState(null);
  const [productoSeleccionado, setProductoSeleccionado] = useState(null);
  const [searchInput, setSearchInput] = useState('');
  const [page, setPage] = useState(1);
  const [editandoPrecio, setEditandoPrecio] = useState(null);
  const [precioTemp, setPrecioTemp] = useState('');
  const [filtroStock, setFiltroStock] = useState("todos");
  const [filtroPrecio, setFiltroPrecio] = useState("todos");
  const [totalProductos, setTotalProductos] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [auditoriaVisible, setAuditoriaVisible] = useState(false);
  const [auditoriaData, setAuditoriaData] = useState([]);
  const [editandoRebate, setEditandoRebate] = useState(null);
  const [rebateTemp, setRebateTemp] = useState({ participa: false, porcentaje: 3.8 });
  const [mostrarExportModal, setMostrarExportModal] = useState(false);
  const [editandoWebTransf, setEditandoWebTransf] = useState(null);
  const [webTransfTemp, setWebTransfTemp] = useState({ participa: false, porcentaje: 6.0, preservar: false });
  const [mostrarCalcularWebModal, setMostrarCalcularWebModal] = useState(false);
  const [mostrarCalcularPVPModal, setMostrarCalcularPVPModal] = useState(false);
  const [marcas, setMarcas] = useState([]);
  const [marcasSeleccionadas, setMarcasSeleccionadas] = useState([]);
  const [busquedaMarca, setBusquedaMarca] = useState('');
  const [ordenColumna, setOrdenColumna] = useState(null);
  const [ordenDireccion, setOrdenDireccion] = useState('asc');
  const [ordenColumnas, setOrdenColumnas] = useState([]);
  const [subcategorias, setSubcategorias] = useState([]);
  const [subcategoriasSeleccionadas, setSubcategoriasSeleccionadas] = useState([]);
  const [busquedaSubcategoria, setBusquedaSubcategoria] = useState('');
  const [usuarios, setUsuarios] = useState([]);
  const [tiposAccion, setTiposAccion] = useState([]);
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
  const [colorDropdownAbierto, setColorDropdownAbierto] = useState(null); // item_id del producto
  const [coloresSeleccionados, setColoresSeleccionados] = useState([]);
  const [pms, setPms] = useState([]);
  const [pmsSeleccionados, setPmsSeleccionados] = useState([]);
  const [marcasPorPM, setMarcasPorPM] = useState([]); // Marcas filtradas por PMs seleccionados
  const [subcategoriasPorPM, setSubcategoriasPorPM] = useState([]); // Subcategorías filtradas por PMs seleccionados

  // Estados para navegación por teclado
  const [celdaActiva, setCeldaActiva] = useState(null); // { rowIndex, colIndex }
  const [modoNavegacion, setModoNavegacion] = useState(false);
  const [mostrarShortcutsHelp, setMostrarShortcutsHelp] = useState(false);

  // Estados para vista de cuotas
  const [modoVista, setModoVista] = useState('normal'); // 'normal', 'cuotas', 'pvp'
  const [recalcularCuotasAuto, setRecalcularCuotasAuto] = useState(() => {
    // Leer del localStorage, por defecto true
    const saved = localStorage.getItem('recalcularCuotasAuto');
    return saved === null ? true : JSON.parse(saved);
  });
  const [editandoCuota, setEditandoCuota] = useState(null); // {item_id, tipo: '3'|'6'|'9'|'12'}
  const [cuotaTemp, setCuotaTemp] = useState('');

  // Selección múltiple
  const [productosSeleccionados, setProductosSeleccionados] = useState(new Set());
  const [ultimoSeleccionado, setUltimoSeleccionado] = useState(null);

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
  const [toast, setToast] = useState(null);

  // Modal de ban
  const [mostrarModalBan, setMostrarModalBan] = useState(false);
  const [productoBan, setProductoBan] = useState(null);
  const [palabraVerificacion, setPalabraVerificacion] = useState('');
  const [palabraObjetivo, setPalabraObjetivo] = useState('');
  const [motivoBan, setMotivoBan] = useState('');

  const user = useAuthStore((state) => state.user);
  const { tienePermiso } = usePermisos();

  const API_URL = import.meta.env.VITE_API_URL;
  const toastTimeoutRef = useRef(null);

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

  // Columnas navegables según la vista activa
  const columnasNavegablesNormal = ['precio_clasica', 'precio_rebate', 'mejor_oferta', 'precio_web_transf'];
  const columnasNavegablesCuotas = ['precio_clasica', 'cuotas_3', 'cuotas_6', 'cuotas_9', 'cuotas_12'];
  const columnasNavegablesPVP = ['precio_pvp', 'pvp_cuotas_3', 'pvp_cuotas_6', 'pvp_cuotas_9', 'pvp_cuotas_12'];
  const columnasEditables = 
    modoVista === 'cuotas' ? columnasNavegablesCuotas :
    modoVista === 'pvp' ? columnasNavegablesPVP :
    columnasNavegablesNormal;

  const debouncedSearch = useDebounce(searchInput, 500);

  // URL Query Params para persistencia de filtros
  const [searchParams, setSearchParams] = useSearchParams();
  const [filtrosInicializados, setFiltrosInicializados] = useState(false);

  // Función para mostrar toast
  const showToast = (message, type = 'success') => {
    // Limpiar timeout anterior si existe
    if (toastTimeoutRef.current) {
      clearTimeout(toastTimeoutRef.current);
    }
    setToast({ message, type });
    toastTimeoutRef.current = setTimeout(() => setToast(null), 3000);
  };

  // Cleanup del toast timeout al desmontar
  useEffect(() => {
    return () => {
      if (toastTimeoutRef.current) {
        clearTimeout(toastTimeoutRef.current);
      }
    };
  }, []);

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
  }, []); // Solo al montar

  // useEffect para sincronizar filtros a URL cuando cambian
  useEffect(() => {
    // Solo sincronizar después de que los filtros fueron inicializados desde URL
    if (filtrosInicializados) {
      syncFiltersToURL();
    }
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

  useEffect(() => {
    cargarProductos();
  }, [page, debouncedSearch, filtroStock, filtroPrecio, pageSize, marcasSeleccionadas, subcategoriasSeleccionadas, ordenColumnas, filtrosAuditoria, filtroRebate, filtroOferta, filtroWebTransf, filtroTiendaNube, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards, coloresSeleccionados, pmsSeleccionados, filtroMLA, filtroEstadoMLA, filtroNuevos, filtroTiendaOficial]);

  // Cargar stats dinámicos cada vez que cambian los filtros
  useEffect(() => {
    cargarStats();
  }, [debouncedSearch, filtroStock, filtroPrecio, marcasSeleccionadas, subcategoriasSeleccionadas, filtrosAuditoria, filtroRebate, filtroOferta, filtroWebTransf, filtroTiendaNube, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards, coloresSeleccionados, pmsSeleccionados, filtroMLA, filtroEstadoMLA, filtroNuevos, filtroTiendaOficial]);

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
        } catch (error) {
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

  const cargarStats = async () => {
    try {
      // Construir parámetros con todos los filtros activos (igual que cargarProductos)
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

      // Cargar estadísticas dinámicas según filtros aplicados
      const statsRes = await productosAPI.statsDinamicos(params);
      setStats(statsRes.data);
    } catch (error) {
      // Error silencioso, no afecta funcionalidad principal
    }
  };


  useEffect(() => {
    cargarUsuariosAuditoria();
    cargarTiposAccion();
    cargarPMs();
  }, []);

  // Recargar marcas cuando cambien filtros (excepto marcasSeleccionadas)
  useEffect(() => {
    cargarMarcas();
  }, [debouncedSearch, filtroStock, filtroPrecio, subcategoriasSeleccionadas, filtroRebate, filtroOferta, filtroWebTransf, filtroTiendaNube, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards, coloresSeleccionados, filtrosAuditoria]);

  // Recargar subcategorías cuando cambien filtros (excepto subcategoriasSeleccionadas)
  useEffect(() => {
    cargarSubcategorias();
  }, [debouncedSearch, filtroStock, filtroPrecio, marcasSeleccionadas, filtroRebate, filtroOferta, filtroWebTransf, filtroTiendaNube, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards, coloresSeleccionados, filtrosAuditoria]);

  // Copiar enlaces al clipboard con Ctrl+F1/F2/F3 o Ctrl+Shift+1/2/3 (alternativa para Linux)
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Detectar qué acción ejecutar (1=código, 2=enlace1, 3=enlace2)
      let accion = null;

      // Ctrl+F1/F2/F3 (con o sin Shift)
      if (e.ctrlKey && (e.key === 'F1' || e.key === 'F2' || e.key === 'F3')) {
        accion = e.key === 'F1' ? 1 : e.key === 'F2' ? 2 : 3;
      }
      // Ctrl+Shift+1/2/3 (alternativa para sistemas que capturan F1/F2)
      // Soporta layouts: en_US, es_AR, es_ES
      // - en_US: Shift+1=!, Shift+2=@, Shift+3=#
      // - es_AR/es_ES: Shift+1=!, Shift+2=", Shift+3=·
      // - e.code es independiente del layout (Digit1/2/3)
      if (e.ctrlKey && e.shiftKey) {
        if (e.key === '!' || e.code === 'Digit1') {
          accion = 1;
        }
        if (e.key === '"' || e.key === '@' || e.code === 'Digit2') {
          accion = 2;
        }
        if (e.key === '·' || e.key === '#' || e.code === 'Digit3') {
          accion = 3;
        }
      }

      if (accion) {
        // Prevenir comportamiento por defecto del navegador INMEDIATAMENTE
        e.preventDefault();
        e.stopPropagation();

        // Verificar si hay algo en modo edición O si hay una celda activa (navegación)
        const enModoEdicion = editandoPrecio || editandoRebate || editandoWebTransf || editandoCuota;
        const hayProductoSeleccionado = celdaActiva !== null && celdaActiva.rowIndex !== null;

        if (!enModoEdicion && !hayProductoSeleccionado) {
          showToast('Debes posicionarte sobre un producto para usar este atajo (Enter para activar navegación)', 'error');
          return;
        }

        // Obtener el producto activo
        let producto = null;

        if (enModoEdicion) {
          // Si está editando, buscar por item_id
          let itemId = null;
          if (editandoPrecio) itemId = editandoPrecio;
          else if (editandoRebate) itemId = editandoRebate;
          else if (editandoWebTransf) itemId = editandoWebTransf;
          else if (editandoCuota) itemId = editandoCuota.item_id;

          if (itemId) {
            producto = productos.find(p => p.item_id === itemId);
          }
        } else if (hayProductoSeleccionado) {
          // Si está navegando, buscar por índice de fila
          producto = productos[celdaActiva.rowIndex];
        }

        if (!producto) {
          showToast('Producto no encontrado', 'error');
          return;
        }

        if (!producto.codigo) {
          showToast('El producto no tiene código asignado', 'error');
          return;
        }

        const itemCode = producto.codigo;

        // Acción 1: copiar solo el código
        if (accion === 1) {
          navigator.clipboard.writeText(itemCode).then(() => {
            showToast(`✅ Código copiado: ${itemCode}`);
          }).catch(err => {
            showToast('❌ Error al copiar al portapapeles', 'error');
            
          });
        }

        // Acción 2: primer enlace
        if (accion === 2) {
          const url = `https://listado.mercadolibre.com.ar/${itemCode}_OrderId_PRICE_NoIndex_True`;
          navigator.clipboard.writeText(url).then(() => {
            showToast(`✅ Enlace 1 copiado: ${itemCode}`);
          }).catch(err => {
            showToast('❌ Error al copiar al portapapeles', 'error');
            
          });
        }

        // Acción 3: segundo enlace
        if (accion === 3) {
          const url = `https://www.mercadolibre.com.ar/publicaciones/listado/promos?filters=official_store-57997&page=1&search=${itemCode}&sort=lowest_price`;
          navigator.clipboard.writeText(url).then(() => {
            showToast(`✅ Enlace 2 copiado: ${itemCode}`);
          }).catch(err => {
            showToast('❌ Error al copiar al portapapeles', 'error');
            
          });
        }
      }
    };

    // Usar capture: true para interceptar el evento antes que otros listeners
    window.addEventListener('keydown', handleKeyDown, { capture: true });
    return () => window.removeEventListener('keydown', handleKeyDown, { capture: true });
  }, [editandoPrecio, editandoRebate, editandoWebTransf, editandoCuota, productos, celdaActiva, showToast]);

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

  const cargarMarcas = async () => {
    try {
      // Construir params con filtros activos (excluyendo marcas)
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

      const response = await productosAPI.marcas(params);
      setMarcas(response.data.marcas);
    } catch (error) {
      showToast('Error al cargar marcas', 'error');
    }
  };

  const iniciarEdicionWebTransf = (producto) => {
    setEditandoWebTransf(producto.item_id);
    setWebTransfTemp({
      participa: producto.participa_web_transferencia || false,
      porcentaje: producto.porcentaje_markup_web || 6.0,
      preservar: producto.preservar_porcentaje_web || false
    });
  };

  const guardarWebTransf = async (itemId) => {
    try {
      const token = localStorage.getItem('token');
      // Normalizar: reemplazar coma por punto
      const porcentajeNumerico = parseFloat(webTransfTemp.porcentaje.toString().replace(',', '.')) || 0;

      const response = await axios.patch(
        `${API_URL}/productos/${itemId}/web-transferencia`,
        null,
        {
          params: {
            participa: webTransfTemp.participa,
            porcentaje_markup: porcentajeNumerico,
            preservar_porcentaje: webTransfTemp.preservar
          },
          headers: { Authorization: `Bearer ${token}` }
        }
      );

      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? {
              ...p,
              participa_web_transferencia: webTransfTemp.participa,
              porcentaje_markup_web: porcentajeNumerico,
              preservar_porcentaje_web: webTransfTemp.preservar,
              precio_web_transferencia: response.data.precio_web_transferencia,
              markup_web_real: response.data.markup_web_real
            }
          : p
      ));

      setEditandoWebTransf(null);
    } catch (error) {
      
      showToast('Error al guardar', 'error');
    }
  };

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

  const cargarProductos = async () => {
    setLoading(true);
    try {
      const params = { page, page_size: pageSize };
      if (debouncedSearch) params.search = debouncedSearch;
      if (filtroStock === 'con_stock') params.con_stock = true;
      if (filtroStock === 'sin_stock') params.con_stock = false;
      if (filtroPrecio === 'con_precio') params.con_precio = true;
      if (filtroPrecio === 'sin_precio') params.con_precio = false;
      if (marcasSeleccionadas.length > 0) params.marcas = marcasSeleccionadas.join(',');
      if (subcategoriasSeleccionadas.length > 0) params.subcategorias = subcategoriasSeleccionadas.join(',');
      if (filtrosAuditoria.usuarios.length > 0) {
        params.audit_usuarios = filtrosAuditoria.usuarios.join(',');
      }
      if (filtrosAuditoria.tipos_accion.length > 0) {
        params.audit_tipos_accion = filtrosAuditoria.tipos_accion.join(',');
      }
      if (filtrosAuditoria.fecha_desde) {
        params.audit_fecha_desde = filtrosAuditoria.fecha_desde;
      }
      if (filtrosAuditoria.fecha_hasta) {
        params.audit_fecha_hasta = filtrosAuditoria.fecha_hasta;
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

      if (filtroTiendaOficial) params.tienda_oficial = filtroTiendaOficial;

      if (coloresSeleccionados.length > 0) params.colores = coloresSeleccionados.join(',');

      if (pmsSeleccionados.length > 0) params.pms = pmsSeleccionados.join(',');

      if (ordenColumnas.length > 0) {
        params.orden_campos = ordenColumnas.map(o => o.columna).join(',');
        params.orden_direcciones = ordenColumnas.map(o => o.direccion).join(',');
      }

      if (ordenColumnas.length > 0) {
        params.orden_campos = ordenColumnas.map(o => o.columna).join(',');
        params.orden_direcciones = ordenColumnas.map(o => o.direccion).join(',');
      }

      const productosRes = await productosAPI.listar(params);
      setTotalProductos(productosRes.data.total || productosRes.data.productos.length);
      setProductos(productosRes.data.productos);

    } catch (error) {
      showToast('Error al cargar productos', 'error');
    } finally {
      setLoading(false);
    }
  };

  const cargarSubcategorias = async () => {
    try {
      // Construir params con filtros activos (excluyendo subcategorías)
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

      const response = await productosAPI.subcategorias(params);
      setSubcategorias(response.data.categorias);
    } catch (error) {
      showToast('Error al cargar subcategorías', 'error');
    }
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
    setOrdenColumnas([]);
    setPage(1);

    // Limpiar también la URL
    setSearchParams({}, { replace: true });
  };

  const verAuditoria = async (productoId) => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get(
        `${API_URL}/productos/${productoId}/auditoria`,
        { headers: { Authorization: `Bearer ${token}` }}
      );
      setAuditoriaData(response.data);
      setAuditoriaVisible(true);
    } catch (error) {
      
      showToast('Error al cargar el historial', 'error');
    }
  };

  const getMarkupColor = (markup) => {
    if (markup === null || markup === undefined) return 'var(--text-tertiary)';
    if (markup < 0) return 'var(--error)';
    if (markup < 1) return 'var(--warning)';
    return 'var(--success)';
  };

  // Validación de input numérico
  const isValidNumericInput = (value) => {
    if (value === '' || value === null || value === undefined) return true; // Allow empty
    const num = parseFloat(value);
    return !isNaN(num) && isFinite(num);
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

  const cambiarColorProducto = async (itemId, color) => {
    try {
      const token = localStorage.getItem('token');
      
      await axios.patch(
        `${API_URL}/productos/${itemId}/color`,
        { color },  // Enviar en el body, no en params
        {
          headers: { Authorization: `Bearer ${token}` }
        }
      );
      
      // Actualizar estado local en lugar de recargar
      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? { ...p, color }
          : p
      ));
      
      setColorDropdownAbierto(null);
      
      // Recargar stats para reflejar cambios en contadores
      cargarStats();
    } catch (error) {
      
      
      showToast('Error al cambiar el color', 'error');
    }
  };

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

  const iniciarEdicion = (producto) => {
    setEditandoPrecio(producto.item_id);
    // Si estamos en modo PVP, usar precio_pvp, sino precio_lista_ml
    const precioInicial = modoVista === 'pvp' ? (producto.precio_pvp || '') : (producto.precio_lista_ml || '');
    setPrecioTemp(precioInicial);
  };

  const iniciarEdicionCuota = (producto, tipo) => {
    setEditandoCuota({ item_id: producto.item_id, tipo });
    const campoPrecio = `precio_${tipo}_cuotas`;
    setCuotaTemp(producto[campoPrecio] || '');
  };

  const guardarCuota = async (itemId, tipo, esPVP = false) => {
    try {
      const token = localStorage.getItem('token');
      const precioNormalizado = parseFloat(cuotaTemp.toString().replace(',', '.'));

      const response = await axios.post(
        `${API_URL}/precios/set-cuota`,
        null,
        {
          headers: { Authorization: `Bearer ${token}` },
          params: {
            item_id: itemId,
            tipo_cuota: tipo,
            precio: precioNormalizado,
            lista_tipo: esPVP ? 'pvp' : 'web'  // ← NUEVO: distinguir web/pvp
          }
        }
      );

      // Determinar nombres de campos según si es PVP o Web
      let campoPrecio, campoMarkup;
      if (esPVP) {
        campoPrecio = tipo === 'clasica' ? 'precio_pvp' : `precio_pvp_${tipo}_cuotas`;
        campoMarkup = tipo === 'clasica' ? 'markup_pvp' : `markup_pvp_${tipo}_cuotas`;
      } else {
        campoPrecio = tipo === 'clasica' ? 'precio_lista_ml' : `precio_${tipo}_cuotas`;
        campoMarkup = tipo === 'clasica' ? 'markup' : `markup_${tipo}_cuotas`;
      }

      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? {
              ...p,
              [campoPrecio]: precioNormalizado,
              [campoMarkup]: response.data[campoMarkup]
            }
          : p
      ));

      setEditandoCuota(null);
      cargarStats();
    } catch (error) {
      
      showToast('Error al guardar precio de cuota: ' + (error.response?.data?.detail || error.message), 'error');
    }
  };

  const recalcularCuotasDesdeClasica = async (producto, listaTipo) => {
    const precioBase = listaTipo === 'pvp' ? producto.precio_pvp : producto.precio_lista_ml;
    
    if (!precioBase || Number(precioBase) <= 0) {
      showToast(`Este producto no tiene Precio ${listaTipo === 'pvp' ? 'PVP' : 'Web'} para recalcular cuotas`, 'error');
      return;
    }

    try {
      const token = localStorage.getItem('token');

      const response = await axios.post(
        `${API_URL}/precios/recalcular-cuotas`,
        null,
        {
          headers: { Authorization: `Bearer ${token}` },
          params: {
            item_id: producto.item_id,
            lista_tipo: listaTipo
          }
        }
      );

      // Actualizar precios y markups en el estado
      if (listaTipo === 'pvp') {
        setProductos((prods) => prods.map((p) =>
          p.item_id === producto.item_id
            ? {
                ...p,
                precio_pvp_3_cuotas: response.data.precio_pvp_3_cuotas,
                precio_pvp_6_cuotas: response.data.precio_pvp_6_cuotas,
                precio_pvp_9_cuotas: response.data.precio_pvp_9_cuotas,
                precio_pvp_12_cuotas: response.data.precio_pvp_12_cuotas,
                markup_pvp_3_cuotas: response.data.markup_pvp_3_cuotas,
                markup_pvp_6_cuotas: response.data.markup_pvp_6_cuotas,
                markup_pvp_9_cuotas: response.data.markup_pvp_9_cuotas,
                markup_pvp_12_cuotas: response.data.markup_pvp_12_cuotas
              }
            : p
        ));
      } else {
        setProductos((prods) => prods.map((p) =>
          p.item_id === producto.item_id
            ? {
                ...p,
                precio_3_cuotas: response.data.precio_3_cuotas,
                precio_6_cuotas: response.data.precio_6_cuotas,
                precio_9_cuotas: response.data.precio_9_cuotas,
                precio_12_cuotas: response.data.precio_12_cuotas,
                markup_3_cuotas: response.data.markup_3_cuotas,
                markup_6_cuotas: response.data.markup_6_cuotas,
                markup_9_cuotas: response.data.markup_9_cuotas,
                markup_12_cuotas: response.data.markup_12_cuotas
              }
            : p
        ));
      }

      showToast(`Cuotas ${listaTipo === 'pvp' ? 'PVP' : 'Web'} recalculadas`, 'success');
      cargarStats();
    } catch (error) {
      showToast(`Error al recalcular cuotas: ${error.response?.data?.detail || error.message}`, 'error');
    }
  };

  // Funciones de selección múltiple
  const toggleSeleccion = (itemId, shiftKey) => {
    const nuevaSeleccion = new Set(productosSeleccionados);

    if (shiftKey && ultimoSeleccionado !== null) {
      // Selección con Shift: seleccionar rango
      const indices = productos.map(p => p.item_id);
      const indiceActual = indices.indexOf(itemId);
      const indiceUltimo = indices.indexOf(ultimoSeleccionado);

      const inicio = Math.min(indiceActual, indiceUltimo);
      const fin = Math.max(indiceActual, indiceUltimo);

      for (let i = inicio; i <= fin; i++) {
        nuevaSeleccion.add(indices[i]);
      }
    } else {
      // Toggle individual
      if (nuevaSeleccion.has(itemId)) {
        nuevaSeleccion.delete(itemId);
      } else {
        nuevaSeleccion.add(itemId);
      }
    }

    setProductosSeleccionados(nuevaSeleccion);
    setUltimoSeleccionado(itemId);
  };

  const seleccionarTodos = () => {
    if (productosSeleccionados.size === productos.length) {
      setProductosSeleccionados(new Set());
    } else {
      setProductosSeleccionados(new Set(productos.map(p => p.item_id)));
    }
  };

  const limpiarSeleccion = () => {
    setProductosSeleccionados(new Set());
    setUltimoSeleccionado(null);
  };

  const pintarLote = async (color) => {
    try {
      const token = localStorage.getItem('token');

      await axios.post(
        `${API_URL}/productos/actualizar-color-lote`,
        {
          item_ids: Array.from(productosSeleccionados),
          color: color
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      setProductos(prods => prods.map(p =>
        productosSeleccionados.has(p.item_id)
          ? { ...p, color_marcado: color }
          : p
      ));

      limpiarSeleccion();
      cargarStats();
    } catch (error) {
      
      showToast('Error al actualizar colores en lote', 'error');
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
      const token = localStorage.getItem('token');

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

      const response = await axios.patch(
        `${API_URL}/productos/${productoConfig.item_id}/config-cuotas`,
        data,
        { headers: { Authorization: `Bearer ${token}` } }
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

  const guardarPrecio = async (itemId) => {
    try {
      const token = localStorage.getItem('token');
      // Normalizar: reemplazar coma por punto
      const precioNormalizado = parseFloat(precioTemp.toString().replace(',', '.'));
      
      // Validar que sea un número válido
      if (!isValidNumericInput(precioNormalizado) || precioNormalizado <= 0) {
        showToast('El precio debe ser un número válido mayor a 0', 'error');
        return;
      }

      // Determinar si recalcular cuotas: primero verificar configuración individual del producto
      const producto = productos.find(p => p.item_id === itemId);
      const shouldRecalcularCuotas = producto?.recalcular_cuotas_auto !== null 
        ? producto.recalcular_cuotas_auto 
        : recalcularCuotasAuto;

      // Si estamos en modo PVP, usar set-rapido con lista_tipo=pvp
      if (modoVista === 'pvp') {
        const response = await axios.post(
          `${API_URL}/precios/set-rapido`,
          null,
          {
            headers: { Authorization: `Bearer ${token}` },
            params: {
              item_id: itemId,
              precio: precioNormalizado,
              recalcular_cuotas: shouldRecalcularCuotas,  // Respetar config individual o global
              lista_tipo: 'pvp'
            }
          }
        );

        // Si se borraron precios PVP (precio = 0)
        if (response.data.precios_borrados) {
          setProductos(prods => prods.map(p =>
            p.item_id === itemId
              ? {
                  ...p,
                  // Limpiar solo precios PVP
                  precio_pvp: null,
                  markup_pvp: null,
                  precio_pvp_3_cuotas: null,
                  precio_pvp_6_cuotas: null,
                  precio_pvp_9_cuotas: null,
                  precio_pvp_12_cuotas: null,
                  markup_pvp_3_cuotas: null,
                  markup_pvp_6_cuotas: null,
                  markup_pvp_9_cuotas: null,
                  markup_pvp_12_cuotas: null
                }
              : p
          ));
          showToast('Precios PVP borrados', 'success');
        } else {
          // Actualización normal de precios
          setProductos(prods => prods.map(p =>
            p.item_id === itemId
              ? {
                  ...p,
                  precio_pvp: precioNormalizado,
                  markup_pvp: response.data.markup_pvp,
                  // Actualizar cuotas PVP recalculadas
                  precio_pvp_3_cuotas: response.data.precio_pvp_3_cuotas || p.precio_pvp_3_cuotas,
                  precio_pvp_6_cuotas: response.data.precio_pvp_6_cuotas || p.precio_pvp_6_cuotas,
                  precio_pvp_9_cuotas: response.data.precio_pvp_9_cuotas || p.precio_pvp_9_cuotas,
                  precio_pvp_12_cuotas: response.data.precio_pvp_12_cuotas || p.precio_pvp_12_cuotas,
                  // Actualizar markups de cuotas PVP si vienen en la respuesta
                  markup_pvp_3_cuotas: response.data.markup_pvp_3_cuotas !== undefined ? response.data.markup_pvp_3_cuotas : p.markup_pvp_3_cuotas,
                  markup_pvp_6_cuotas: response.data.markup_pvp_6_cuotas !== undefined ? response.data.markup_pvp_6_cuotas : p.markup_pvp_6_cuotas,
                  markup_pvp_9_cuotas: response.data.markup_pvp_9_cuotas !== undefined ? response.data.markup_pvp_9_cuotas : p.markup_pvp_9_cuotas,
                  markup_pvp_12_cuotas: response.data.markup_pvp_12_cuotas !== undefined ? response.data.markup_pvp_12_cuotas : p.markup_pvp_12_cuotas,
                  tiene_precio: true
                }
              : p
          ));
        }

        setEditandoPrecio(null);
        cargarStats();
        return;
      }

      // Modo web (comportamiento original)
      const response = await axios.post(
        `${API_URL}/precios/set-rapido`,
        null,  // No body needed, all params go in URL
        {
          headers: { Authorization: `Bearer ${token}` },
          params: {
            item_id: itemId,
            precio: precioNormalizado,
            recalcular_cuotas: shouldRecalcularCuotas  // Respetar config individual o global
          }
        }
      );

      // Si se borraron precios Web (precio = 0)
      if (response.data.precios_borrados) {
        setProductos(prods => prods.map(p =>
          p.item_id === itemId
            ? {
                ...p,
                // Limpiar solo precios Web
                precio_lista_ml: null,
                markup: null,
                precio_3_cuotas: null,
                precio_6_cuotas: null,
                precio_9_cuotas: null,
                precio_12_cuotas: null,
                markup_3_cuotas: null,
                markup_6_cuotas: null,
                markup_9_cuotas: null,
                markup_12_cuotas: null,
                precio_web_transferencia: null,
                markup_web_real: null,
                precio_rebate: null,
                markup_rebate: null,
                markup_oferta: null
              }
            : p
        ));
        showToast('Precios Web borrados', 'success');
      } else {
        // Actualización normal de precios
        setProductos(prods => prods.map(p =>
          p.item_id === itemId
            ? {
                ...p,
                precio_lista_ml: precioNormalizado,
                markup: response.data.markup,
                // Actualizar precios de cuotas si vienen en la respuesta
                precio_3_cuotas: response.data.precio_3_cuotas || p.precio_3_cuotas,
                precio_6_cuotas: response.data.precio_6_cuotas || p.precio_6_cuotas,
                precio_9_cuotas: response.data.precio_9_cuotas || p.precio_9_cuotas,
                precio_12_cuotas: response.data.precio_12_cuotas || p.precio_12_cuotas,
                // Actualizar markups de cuotas si vienen en la respuesta
                markup_3_cuotas: response.data.markup_3_cuotas !== undefined ? response.data.markup_3_cuotas : p.markup_3_cuotas,
                markup_6_cuotas: response.data.markup_6_cuotas !== undefined ? response.data.markup_6_cuotas : p.markup_6_cuotas,
                markup_9_cuotas: response.data.markup_9_cuotas !== undefined ? response.data.markup_9_cuotas : p.markup_9_cuotas,
                markup_12_cuotas: response.data.markup_12_cuotas !== undefined ? response.data.markup_12_cuotas : p.markup_12_cuotas,
                // Actualizar rebate y web transferencia si vienen en la respuesta
                precio_rebate: response.data.precio_rebate !== null && response.data.precio_rebate !== undefined ? response.data.precio_rebate : p.precio_rebate,
                precio_web_transferencia: response.data.precio_web_transferencia !== null && response.data.precio_web_transferencia !== undefined ? response.data.precio_web_transferencia : p.precio_web_transferencia,
                markup_web_real: response.data.markup_web_real !== null && response.data.markup_web_real !== undefined ? response.data.markup_web_real : p.markup_web_real,
                tiene_precio: true
              }
            : p
        ));
      }

      setEditandoPrecio(null);
      cargarStats();
    } catch (error) {
      showToast('Error al guardar precio', 'error');
    }
  };

  const guardarRebate = async (itemId) => {
    try {
      const token = localStorage.getItem('token');
      // Normalizar: reemplazar coma por punto
      const porcentajeNormalizado = parseFloat(rebateTemp.porcentaje.toString().replace(',', '.'));

      // Validar que sea un número válido entre 0 y 100
      if (!isValidNumericInput(porcentajeNormalizado) || porcentajeNormalizado < 0 || porcentajeNormalizado > 100) {
        showToast('El porcentaje de rebate debe ser un número entre 0 y 100', 'error');
        return;
      }
      
      await axios.patch(
        `${API_URL}/productos/${itemId}/rebate`,
        {
          participa_rebate: rebateTemp.participa,
          porcentaje_rebate: porcentajeNormalizado
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? {
              ...p,
              participa_rebate: rebateTemp.participa,
              porcentaje_rebate: porcentajeNormalizado,
              precio_rebate: rebateTemp.participa && p.precio_lista_ml
                ? p.precio_lista_ml / (1 - porcentajeNormalizado / 100)
                : null
            }
          : p
      ));

      setEditandoRebate(null);
    } catch (error) {
      
      showToast('Error al guardar rebate', 'error');
    }
  };

  const iniciarEdicionRebate = (producto) => {
    setEditandoRebate(producto.item_id);
    setRebateTemp({
      participa: producto.participa_rebate || false,
      porcentaje: producto.porcentaje_rebate !== null && producto.porcentaje_rebate !== undefined 
        ? producto.porcentaje_rebate 
        : 3.8
    });
  };

  const cargarUsuariosAuditoria = async () => {
    try {
      const response = await axios.get(`${API_URL}/auditoria/usuarios`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('token')}` }
      });
      setUsuarios(response.data.usuarios);
    } catch (error) {
      showToast('Error al cargar usuarios', 'error');
    }
  };

  const cargarTiposAccion = async () => {
    try {
      const response = await axios.get(`${API_URL}/auditoria/tipos-accion`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('token')}` }
      });
      setTiposAccion(response.data.tipos);
    } catch (error) {
      showToast('Error al cargar tipos de acción', 'error');
    }
  };

  const cargarPMs = async () => {
    try {
      const response = await axios.get(`${API_URL}/usuarios/pms?solo_con_marcas=true`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('token')}` }
      });
      setPms(response.data);
    } catch (error) {
      showToast('Error al cargar PMs', 'error');
    }
  };

  // Sistema de navegación por teclado
  useEffect(() => {
    const handleKeyDown = async (e) => {
      // Si hay un modal abierto, NO procesar shortcuts de la página
      const hayModalAbierto = mostrarExportModal || mostrarCalcularWebModal || mostrarCalcularPVPModal || mostrarModalConfig || mostrarModalInfo || mostrarShortcutsHelp;

      if (hayModalAbierto) {
        // NO hacer preventDefault - dejar que el modal maneje sus eventos
        // Solo ignorar el evento en este handler
        return;
      }

      // ESC: Salir de edición o modo navegación (solo si NO hay modal)
      if (e.key === 'Escape') {
        e.preventDefault();
        // Si estamos editando, salir de edición
        if (editandoPrecio || editandoRebate || editandoWebTransf) {
          setEditandoPrecio(null);
          setEditandoRebate(null);
          setEditandoWebTransf(null);
          return;
        }
        // Salir del modo navegación
        setCeldaActiva(null);
        setModoNavegacion(false);
        setPanelFiltroActivo(null);
        setColorDropdownAbierto(null);
        return;
      }

      // Si estamos editando una celda
      if (editandoPrecio || editandoRebate || editandoWebTransf) {
        // Interceptar Tab para evitar que escape del formulario
        if (e.key === 'Tab') {
          e.preventDefault();
          e.stopPropagation();

          // Encontrar el contenedor de edición activo buscando desde el elemento activo
          let editContainer = document.activeElement?.closest('.inline-edit, .rebate-edit, .web-transf-edit');

          // Si no hay elemento activo en un contenedor, buscar el contenedor visible
          if (!editContainer) {
            if (editandoPrecio) {
              editContainer = document.querySelector('.inline-edit');
            } else if (editandoRebate) {
              editContainer = document.querySelector('.rebate-edit');
            } else if (editandoWebTransf) {
              editContainer = document.querySelector('.web-transf-edit');
            }
          }

          if (editContainer) {
            const focusable = Array.from(editContainer.querySelectorAll('input, button')).filter(el => {
              // Filtrar solo elementos visibles y no disabled
              return el.offsetParent !== null && !el.disabled;
            });
            const currentIndex = focusable.indexOf(document.activeElement);

            if (e.shiftKey) {
              // Tab + Shift: ir hacia atrás
              const prevIndex = currentIndex <= 0 ? focusable.length - 1 : currentIndex - 1;
              focusable[prevIndex]?.focus();
            } else {
              // Tab: ir hacia adelante
              const nextIndex = currentIndex >= focusable.length - 1 ? 0 : currentIndex + 1;
              focusable[nextIndex]?.focus();
            }
          }
          return;
        }
        // Dejar pasar otras teclas (arrows, enter, etc) para que funcionen en los inputs
        return;
      }

      // Mostrar ayuda de shortcuts (?)
      if (e.key === '?' && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        setMostrarShortcutsHelp(!mostrarShortcutsHelp);
        return;
      }

      // Ctrl+F: Focus en búsqueda
      if (e.ctrlKey && e.key === 'f') {
        e.preventDefault();
        document.querySelector('.search-bar input')?.focus();
        return;
      }

      // Ctrl+I: Abrir info del producto seleccionado
      if ((e.ctrlKey || e.metaKey) && e.key === 'i') {
        e.preventDefault();
        if (celdaActiva && productos[celdaActiva.rowIndex]) {
          const producto = productos[celdaActiva.rowIndex];
          setProductoInfo(producto.item_id);
          setMostrarModalInfo(true);
        }
        return;
      }

      // Alt+M: Toggle filtro de marcas
      if (e.altKey && e.key === 'm') {
        e.preventDefault();
        setPanelFiltroActivo(panelFiltroActivo === 'marcas' ? null : 'marcas');
        return;
      }

      // Alt+S: Toggle filtro de subcategorías
      if (e.altKey && e.key === 's') {
        e.preventDefault();
        setPanelFiltroActivo(panelFiltroActivo === 'subcategorias' ? null : 'subcategorias');
        return;
      }

      // Alt+A: Toggle filtro de auditoría
      if (e.altKey && e.key === 'a') {
        e.preventDefault();
        setPanelFiltroActivo(panelFiltroActivo === 'auditoria' ? null : 'auditoria');
        return;
      }

      // Alt+P: Toggle filtro de PMs
      if (e.altKey && e.key === 'p') {
        e.preventDefault();
        setPanelFiltroActivo(panelFiltroActivo === 'pms' ? null : 'pms');
        return;
      }

      // Alt+C: Toggle filtros avanzados (donde está el filtro de colores)
      if (e.altKey && e.key === 'c') {
        e.preventDefault();
        setMostrarFiltrosAvanzados(!mostrarFiltrosAvanzados);
        return;
      }

      // Alt+F: Toggle filtros avanzados
      if (e.altKey && e.key === 'f') {
        e.preventDefault();
        setMostrarFiltrosAvanzados(!mostrarFiltrosAvanzados);
        return;
      }

      // Alt+V: Ciclar entre vistas (Normal → Cuotas → PVP → Normal)
      if (e.altKey && e.key === 'v') {
        e.preventDefault();
        const siguienteModo = 
          modoVista === 'normal' ? 'cuotas' :
          modoVista === 'cuotas' ? 'pvp' :
          'normal';
        setModoVista(siguienteModo);
        // Resetear columna activa para evitar ir a columnas ocultas
        if (celdaActiva) {
          setCeldaActiva({ ...celdaActiva, colIndex: 0 });
        }
        return;
      }

      // Alt+P: Ir directo a Vista PVP (o volver a Normal si ya está en PVP)
      if (e.altKey && e.key === 'p') {
        e.preventDefault();
        setModoVista(modoVista === 'pvp' ? 'normal' : 'pvp');
        // Resetear columna activa para evitar ir a columnas ocultas
        if (celdaActiva) {
          setCeldaActiva({ ...celdaActiva, colIndex: 0 });
        }
        return;
      }

      // Alt+R: Toggle Auto-recalcular cuotas
      if (e.altKey && e.key === 'r') {
        e.preventDefault();
        const nuevoValor = !recalcularCuotasAuto;
        setRecalcularCuotasAuto(nuevoValor);
        localStorage.setItem('recalcularCuotasAuto', JSON.stringify(nuevoValor));
        return;
      }

      // Ctrl+E: Abrir modal de export
      if (e.ctrlKey && e.key === 'e') {
        e.preventDefault();
        setMostrarExportModal(true);
        return;
      }

      // Ctrl+K: Abrir modal de calcular web (requiere permiso)
      if (e.ctrlKey && e.key === 'k' && puedeCalcularWebMasivo) {
        e.preventDefault();
        setMostrarCalcularWebModal(true);
        return;
      }

      // Ctrl+Shift+P: Abrir modal de calcular PVP (requiere permiso)
      if (e.ctrlKey && e.shiftKey && e.key === 'P' && puedeCalcularPVPMasivo) {
        e.preventDefault();
        setMostrarCalcularPVPModal(true);
        return;
      }

      // Enter: Activar modo navegación en la tabla
      if (e.key === 'Enter' && !modoNavegacion && productos.length > 0) {
        e.preventDefault();
        setModoNavegacion(true);
        setCeldaActiva({ rowIndex: 0, colIndex: 0 });
        return;
      }

      // Navegación en modo tabla
      if (modoNavegacion && celdaActiva) {
        const { rowIndex, colIndex } = celdaActiva;

        // Enter: Editar celda activa (igual que Espacio)
        if (e.key === 'Enter' && !editandoPrecio && !editandoRebate && !editandoWebTransf && !editandoCuota && puedeEditar) {
          e.preventDefault();
          const producto = productos[rowIndex];
          const columna = columnasEditables[colIndex];
          iniciarEdicionDesdeTeclado(producto, columna);
          return;
        }

        // Flechas: Navegación por celdas (solo si NO estamos editando)
        if (e.key === 'ArrowRight' && !editandoPrecio && !editandoRebate && !editandoWebTransf && !editandoCuota) {
          e.preventDefault();
          if (colIndex < columnasEditables.length - 1) {
            setCeldaActiva({ rowIndex, colIndex: colIndex + 1 });
          }
          return;
        }

        if (e.key === 'ArrowLeft' && !editandoPrecio && !editandoRebate && !editandoWebTransf && !editandoCuota) {
          e.preventDefault();
          if (colIndex > 0) {
            setCeldaActiva({ rowIndex, colIndex: colIndex - 1 });
          }
          return;
        }

        if (e.key === 'ArrowDown' && !editandoPrecio && !editandoRebate && !editandoWebTransf && !editandoCuota) {
          e.preventDefault();
          if (e.shiftKey) {
            // Shift+ArrowDown: Seleccionar siguiente fila
            if (rowIndex < productos.length - 1) {
              const siguienteItemId = productos[rowIndex + 1].item_id;
              toggleSeleccion(siguienteItemId, true);
              setCeldaActiva({ rowIndex: rowIndex + 1, colIndex });
            }
          } else if (e.ctrlKey || e.metaKey) {
            // Ctrl+ArrowDown: Navegar sin perder selección
            if (rowIndex < productos.length - 1) {
              setCeldaActiva({ rowIndex: rowIndex + 1, colIndex });
            }
          } else if (rowIndex < productos.length - 1) {
            setCeldaActiva({ rowIndex: rowIndex + 1, colIndex });
          }
          return;
        }

        if (e.key === 'ArrowUp' && !editandoPrecio && !editandoRebate && !editandoWebTransf && !editandoCuota) {
          e.preventDefault();
          if (e.shiftKey) {
            // Shift+ArrowUp: Seleccionar fila anterior
            if (rowIndex > 0) {
              const anteriorItemId = productos[rowIndex - 1].item_id;
              toggleSeleccion(anteriorItemId, true);
              setCeldaActiva({ rowIndex: rowIndex - 1, colIndex });
            }
          } else if (e.ctrlKey || e.metaKey) {
            // Ctrl+ArrowUp: Navegar sin perder selección
            if (rowIndex > 0) {
              setCeldaActiva({ rowIndex: rowIndex - 1, colIndex });
            }
          } else if (rowIndex > 0) {
            setCeldaActiva({ rowIndex: rowIndex - 1, colIndex });
          }
          return;
        }

        // PageUp: Subir 10 filas (solo si NO estamos editando)
        if (e.key === 'PageUp' && !editandoPrecio && !editandoRebate && !editandoWebTransf && !editandoCuota) {
          e.preventDefault();
          const newRow = Math.max(0, rowIndex - 10);
          setCeldaActiva({ rowIndex: newRow, colIndex });
          return;
        }

        // PageDown: Bajar 10 filas (solo si NO estamos editando)
        if (e.key === 'PageDown' && !editandoPrecio && !editandoRebate && !editandoWebTransf && !editandoCuota) {
          e.preventDefault();
          const newRow = Math.min(productos.length - 1, rowIndex + 10);
          setCeldaActiva({ rowIndex: newRow, colIndex });
          return;
        }

        // Home: Ir a primera columna (solo si NO estamos editando)
        if (e.key === 'Home' && !editandoPrecio && !editandoRebate && !editandoWebTransf && !editandoCuota) {
          e.preventDefault();
          setCeldaActiva({ rowIndex, colIndex: 0 });
          return;
        }

        // End: Ir a última columna (solo si NO estamos editando)
        if (e.key === 'End' && !editandoPrecio && !editandoRebate && !editandoWebTransf && !editandoCuota) {
          e.preventDefault();
          setCeldaActiva({ rowIndex, colIndex: columnasEditables.length - 1 });
          return;
        }

        // Espacio: Editar precio en celda activa (solo si NO estamos editando nada)
        if (e.key === ' ' && !editandoPrecio && !editandoRebate && !editandoWebTransf && !editandoCuota && puedeEditar) {
          e.preventDefault();
          const producto = productos[rowIndex];
          const columna = columnasEditables[colIndex];
          iniciarEdicionDesdeTeclado(producto, columna);
          return;
        }

        // Números 1-7: Selección rápida de colores (solo si NO estamos editando nada y no estamos en un input)
        const activeElement = document.activeElement;
        const isInputFocused = activeElement && (activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA');
        if (!editandoPrecio && !editandoRebate && !editandoWebTransf && /^[0-7]$/.test(e.key) && !e.ctrlKey && !e.altKey && !e.metaKey && !isInputFocused) {
          e.preventDefault();
          e.stopPropagation();
          if (puedeMarcarColor && productos[rowIndex]) {
            // Colores válidos según el backend
            const colores = [null, 'rojo', 'naranja', 'amarillo', 'verde', 'azul', 'purpura', 'gris'];
            const colorIndex = parseInt(e.key);
            if (colorIndex < colores.length) {
              const producto = productos[rowIndex];
              const colorSeleccionado = colores[colorIndex];
              
              cambiarColorRapido(producto.item_id, colorSeleccionado);
            }
          }
          return;
        }

        // R: Toggle rebate
        if (e.key === 'r' && !editandoPrecio && !editandoWebTransf && puedeToggleRebate) {
          e.preventDefault();
          const producto = productos[rowIndex];
          
          // Si ya estamos editando este producto, desactivar rebate y cerrar edición
          if (editandoRebate === producto.item_id) {
            await axios.patch(
              `${API_URL}/productos/${producto.item_id}/rebate`,
              {
                participa_rebate: false,
                porcentaje_rebate: producto.porcentaje_rebate || 3.8
              },
              { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
            );
            
            // Actualizar estado local en lugar de recargar
            setProductos(prods => prods.map(p =>
              p.item_id === producto.item_id
                ? {
                    ...p,
                    participa_rebate: false,
                    precio_rebate: null,
                    markup_rebate: null
                  }
                : p
            ));
            
            setEditandoRebate(null);
            
            // Recargar stats para reflejar cambios en contadores
            cargarStats();
          } else {
            // Si no estamos editando, toggle normal
            toggleRebateRapido(producto);
          }
          return;
        }

        // W: Toggle web transferencia (solo si NO estamos editando nada)
        if (e.key === 'w' && !editandoPrecio && !editandoRebate && !editandoWebTransf && puedeToggleWebTransf) {
          e.preventDefault();
          const producto = productos[rowIndex];
          toggleWebTransfRapido(producto);
          return;
        }

        // O: Toggle out of cards
        if (e.key === 'o' && !editandoPrecio && !editandoWebTransf && puedeToggleOutOfCards) {
          e.preventDefault();
          const producto = productos[rowIndex];
          
          // Si ya estamos editando Y el producto tiene out_of_cards, desactivarlo
          if (editandoRebate === producto.item_id && producto.out_of_cards) {
            await axios.patch(
              `${API_URL}/productos/${producto.item_id}/out-of-cards`,
              { out_of_cards: false },
              { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
            );
            
            // Actualizar estado local en lugar de recargar
            setProductos(prods => prods.map(p =>
              p.item_id === producto.item_id
                ? { ...p, out_of_cards: false }
                : p
            ));
            
            setEditandoRebate(null);
            
            // Recargar stats para reflejar cambios en contadores
            cargarStats();
          } else {
            // Toggle normal
            toggleOutOfCardsRapido(producto);
          }
          return;
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [modoNavegacion, celdaActiva, productos, editandoPrecio, editandoRebate, editandoWebTransf, editandoCuota, panelFiltroActivo, mostrarShortcutsHelp, puedeEditar, puedeMarcarColor, puedeToggleRebate, puedeToggleWebTransf, puedeToggleOutOfCards, puedeCalcularWebMasivo, puedeCalcularPVPMasivo, mostrarFiltrosAvanzados, modoVista, recalcularCuotasAuto, mostrarExportModal, mostrarCalcularWebModal, mostrarCalcularPVPModal, mostrarModalConfig, mostrarModalInfo]);

  // Scroll automático para seguir la celda activa
  useEffect(() => {
    if (modoNavegacion && celdaActiva) {
      // Buscar la fila activa en el DOM
      const tbody = document.querySelector('.table-tesla-body');
      if (tbody) {
        const filas = tbody.querySelectorAll('tr');
        const filaActiva = filas[celdaActiva.rowIndex];
        if (filaActiva) {
          // Usar behavior: 'auto' (instantáneo) en vez de 'smooth'
          // Esto evita acumulación de animaciones cuando se mantiene presionada la flecha
          // y mantiene la fila siempre visible sin tirones
          filaActiva.scrollIntoView({
            behavior: 'auto',
            block: 'nearest',
            inline: 'nearest'
          });
        }
      }
    }
  }, [celdaActiva, modoNavegacion]);

  // Funciones de edición rápida desde teclado
  const iniciarEdicionDesdeTeclado = (producto, columna) => {
    if (columna === 'precio_clasica') {
      setEditandoPrecio(producto.item_id);
      setPrecioTemp(producto.precio_lista_ml || '');
    } else if (columna === 'precio_rebate') {
      setEditandoRebate(producto.item_id);
      setRebateTemp({
        participa: producto.participa_rebate || false,
        porcentaje: producto.porcentaje_rebate || 3.8
      });
    } else if (columna === 'precio_web_transf') {
      setEditandoWebTransf(producto.item_id);
      setWebTransfTemp({
        participa: producto.participa_web_transferencia || false,
        porcentaje: producto.porcentaje_markup_web || 6.0
      });
    } else if (columna === 'cuotas_3') {
      iniciarEdicionCuota(producto, '3');
    } else if (columna === 'cuotas_6') {
      iniciarEdicionCuota(producto, '6');
    } else if (columna === 'cuotas_9') {
      iniciarEdicionCuota(producto, '9');
    } else if (columna === 'cuotas_12') {
      iniciarEdicionCuota(producto, '12');
    }
  };

  const cambiarColorRapido = async (itemId, color) => {
    try {
      
      await axios.patch(
        `${API_URL}/productos/${itemId}/color`,
        { color },
        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
      );
      
      // Actualizar estado local en lugar de recargar
      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? { ...p, color }
          : p
      ));
      
      // Recargar stats para reflejar cambios en contadores
      cargarStats();
    } catch (error) {
      
      
    }
  };

  const toggleRebateRapido = async (producto) => {
    try {
      // Si el rebate está desactivado, activarlo y abrir modo edición
      if (!producto.participa_rebate) {
        const response = await axios.patch(
          `${API_URL}/productos/${producto.item_id}/rebate`,
          {
            participa_rebate: true,
            porcentaje_rebate: producto.porcentaje_rebate || 3.8
          },
          { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
        );

        // Actualizar estado local en lugar de recargar
        setProductos(prods => prods.map(p =>
          p.item_id === producto.item_id
            ? {
                ...p,
                participa_rebate: true,
                porcentaje_rebate: producto.porcentaje_rebate || 3.8,
                precio_rebate: response.data.precio_rebate,
                markup_rebate: response.data.markup_rebate
              }
            : p
        ));

        // Abrir modo edición
        setEditandoRebate(producto.item_id);
        setRebateTemp({
          participa: true,
          porcentaje: producto.porcentaje_rebate || 3.8
        });

        // Hacer focus en el input de porcentaje
        setTimeout(() => {
          const input = document.querySelector('.rebate-edit input[type="number"]');
          if (input) {
            input.focus();
            input.select();
          }
        }, 100);

        // Recargar stats para reflejar cambios en contadores
        cargarStats();
      } else {
        // Si está activado, desactivarlo
        const response = await axios.patch(
          `${API_URL}/productos/${producto.item_id}/rebate`,
          {
            participa_rebate: false,
            porcentaje_rebate: producto.porcentaje_rebate || 3.8
          },
          { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
        );
        
        // Actualizar estado local en lugar de recargar
        setProductos(prods => prods.map(p =>
          p.item_id === producto.item_id
            ? {
                ...p,
                participa_rebate: false,
                precio_rebate: null,
                markup_rebate: null
              }
            : p
        ));
        
        // Cerrar modo edición si estaba abierto
        if (editandoRebate === producto.item_id) {
          setEditandoRebate(null);
        }
        
        // Recargar stats para reflejar cambios en contadores
        cargarStats();
      }
    } catch (error) {
      showToast('Error al cambiar rebate', 'error');
    }
  };

  const toggleWebTransfRapido = async (producto) => {
    try {
      const response = await axios.patch(
        `${API_URL}/productos/${producto.item_id}/web-transferencia`,
        {
          participa: !producto.participa_web_transferencia,
          porcentaje: producto.porcentaje_markup_web || 6.0
        },
        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
      );
      
      // Actualizar estado local en lugar de recargar
      setProductos(prods => prods.map(p =>
        p.item_id === producto.item_id
          ? {
              ...p,
              participa_web_transferencia: !producto.participa_web_transferencia,
              precio_web_transferencia: response.data.precio_web_transferencia,
              markup_web_real: response.data.markup_web_real
            }
          : p
      ));
      
      // Recargar stats para reflejar cambios en contadores
      cargarStats();
    } catch (error) {
      showToast('Error al cambiar Web/Transferencia', 'error');
    }
  };

  const toggleOutOfCardsRapido = async (producto) => {
    try {
      // Si ya tiene out_of_cards, desactivarlo
      if (producto.out_of_cards) {
        await axios.patch(
          `${API_URL}/productos/${producto.item_id}/out-of-cards`,
          { out_of_cards: false },
          { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
        );
        
        // Actualizar estado local en lugar de recargar
        setProductos(prods => prods.map(p =>
          p.item_id === producto.item_id
            ? { ...p, out_of_cards: false }
            : p
        ));
        
        // Cerrar modo edición si estaba abierto
        if (editandoRebate === producto.item_id) {
          setEditandoRebate(null);
        }
        
        // Recargar stats para reflejar cambios en contadores
        cargarStats();
        return;
      }

      // Si NO tiene out_of_cards, activarlo
      // Primero, si el rebate NO está activo, activarlo
      let rebateResponse = null;
      if (!producto.participa_rebate) {
        rebateResponse = await axios.patch(
          `${API_URL}/productos/${producto.item_id}/rebate`,
          {
            participa_rebate: true,
            porcentaje_rebate: producto.porcentaje_rebate || 3.8
          },
          { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
        );
      }

      // Marcar out_of_cards = true
      await axios.patch(
        `${API_URL}/productos/${producto.item_id}/out-of-cards`,
        { out_of_cards: true },
        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
      );

      // Actualizar estado local en lugar de recargar
      setProductos(prods => prods.map(p =>
        p.item_id === producto.item_id
          ? {
              ...p,
              participa_rebate: true,
              porcentaje_rebate: producto.porcentaje_rebate || 3.8,
              out_of_cards: true,
              ...(rebateResponse && {
                precio_rebate: rebateResponse.data.precio_rebate,
                markup_rebate: rebateResponse.data.markup_rebate
              })
            }
          : p
      ));

      // Abrir modo edición
      setEditandoRebate(producto.item_id);
      setRebateTemp({
        participa: true,
        porcentaje: producto.porcentaje_rebate || 3.8
      });

      // Hacer focus en el input de porcentaje
      setTimeout(() => {
        const input = document.querySelector('.rebate-edit input[type="number"]');
        if (input) {
          input.focus();
          input.select();
        }
      }, 100);

      // Recargar stats para reflejar cambios en contadores
      cargarStats();
    } catch (error) {
      showToast('Error al cambiar Out of Cards', 'error');
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
    if (filtros.webTransf === undefined) setFiltroWebTransf(null);
    else setFiltroWebTransf(filtros.webTransf);

    setFiltroOutOfCards(null);

    setPage(1);
  };

  const limpiarFiltros = () => {
    setFiltroStock("todos");
    setFiltroPrecio("todos");
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
            className={`filter-button ${(filtroRebate || filtroOferta || filtroWebTransf || filtroMarkupClasica || filtroMarkupRebate || filtroMarkupOferta || filtroMarkupWebTransf || filtroOutOfCards || coloresSeleccionados.length > 0) ? 'active' : ''}`}
          >
            Avanzados
            {(filtroRebate || filtroOferta || filtroWebTransf || filtroMarkupClasica || filtroMarkupRebate || filtroMarkupOferta || filtroMarkupWebTransf || filtroOutOfCards || coloresSeleccionados.length > 0) && (
              <span className="filter-badge">
                {[filtroRebate, filtroOferta, filtroWebTransf, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards].filter(Boolean).length + coloresSeleccionados.length}
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
                {productosOrdenados.map((p, rowIndex) => {
                  const isRowActive = modoNavegacion && celdaActiva?.rowIndex === rowIndex;
                  const colorClass = p.color_marcado ? `row-color-${p.color_marcado}` : '';
                  return (
                  <tr
                    key={p.item_id}
                    className={`${colorClass} ${p.color_marcado ? 'row-colored' : ''} ${isRowActive ? 'keyboard-row-active' : ''}`}
                  >
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
                            p.markup !== null && p.markup !== undefined && (
                              <div className="markup-display" style={{ color: getMarkupColor(p.markup) }}>
                                {p.markup}%
                              </div>
                            )
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
                                      await axios.patch(
                                        `${API_URL}/productos/${p.item_id}/out-of-cards`,
                                        { out_of_cards: nuevoValor },
                                        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
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
                  </tr>
                  );
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
                className="pagination-btn"
              >
                ← Anterior
              </button>
              <span>Página {page} {totalProductos > 0 && `(${((page-1)*pageSize + 1)} - ${Math.min(page*pageSize, totalProductos)})`}</span>
              <button
                onClick={() => setPage(p => p + 1)}
                disabled={productos.length < pageSize}
                className="pagination-btn"
              >
                Siguiente →
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
      {toast && (
        <div className={`toast ${toast.type === 'error' ? 'error' : ''}`}>
          {toast.message}
        </div>
      )}
    </div>
  );
}
