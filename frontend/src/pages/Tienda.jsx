import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { productosAPI } from '../services/api';
import PricingModal from '../components/PricingModal';
import { useDebounce } from '../hooks/useDebounce';
import './Tienda.css';
import styles from './Productos.module.css';
import dashboardStyles from './DashboardMetricasML.module.css';
import axios from 'axios';
import { useAuthStore } from '../store/authStore';
import { usePermisos } from '../contexts/PermisosContext';
import ExportModal from '../components/ExportModal';
import xlsIcon from '../assets/xls.svg';
import CalcularWebModal from '../components/CalcularWebModal';
import ModalInfoProducto from '../components/ModalInfoProducto';
import SetupMarkups from '../components/SetupMarkups';
import './Productos.css';

export default function Productos() {
  const { tienePermiso } = usePermisos();
  const puedeGestionarMarkups = tienePermiso('productos.gestionar_markups_tienda');
  const [tabActivo, setTabActivo] = useState('productos'); // 'productos' o 'setup-markups'
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
  const [vistaModoCuotas, setVistaModoCuotas] = useState(false); // false = vista normal, true = vista cuotas
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
    markup_adicional_cuotas_custom: null
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

  // Estado para Web Tarjeta (porcentaje adicional sobre Web Transf)
  const [markupWebTarjeta, setMarkupWebTarjeta] = useState(0);

  const user = useAuthStore((state) => state.user);
  const puedeEditar = ['SUPERADMIN', 'ADMIN', 'GERENTE', 'PRICING'].includes(user?.rol);

  // Columnas navegables según la vista activa
  const columnasNavegablesNormal = ['precio_clasica', 'precio_gremio', 'precio_web_transf', 'web_tarjeta'];
  const columnasNavegablesCuotas = ['precio_clasica', 'cuotas_3', 'cuotas_6', 'cuotas_9', 'cuotas_12'];
  const columnasEditables = vistaModoCuotas ? columnasNavegablesCuotas : columnasNavegablesNormal;

  const debouncedSearch = useDebounce(searchInput, 500);

  // URL Query Params para persistencia de filtros
  const [searchParams, setSearchParams] = useSearchParams();
  const [filtrosInicializados, setFiltrosInicializados] = useState(false);

  // Función para mostrar toast
  const showToast = (message, type = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000); // Desaparece después de 3 segundos
  };

  const API_URL = 'https://pricing.gaussonline.com.ar/api';

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
    coloresSeleccionados,
    page,
    pageSize,
    filtrosAuditoria
  ]);

  useEffect(() => {
    cargarProductos();
  }, [page, debouncedSearch, filtroStock, filtroPrecio, pageSize, marcasSeleccionadas, subcategoriasSeleccionadas, ordenColumnas, filtrosAuditoria, filtroRebate, filtroOferta, filtroWebTransf, filtroTiendaNube, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards, coloresSeleccionados, pmsSeleccionados, filtroMLA, filtroEstadoMLA, filtroNuevos]);

  // Cargar stats dinámicos cada vez que cambian los filtros
  useEffect(() => {
    cargarStats();
  }, [debouncedSearch, filtroStock, filtroPrecio, marcasSeleccionadas, subcategoriasSeleccionadas, filtrosAuditoria, filtroRebate, filtroOferta, filtroWebTransf, filtroTiendaNube, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards, coloresSeleccionados, pmsSeleccionados, filtroMLA, filtroEstadoMLA, filtroNuevos]);

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
          console.error('Error cargando datos por PM:', error);
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
      if (coloresSeleccionados.length > 0) params.colores = coloresSeleccionados.join(',');
      if (pmsSeleccionados.length > 0) params.pms = pmsSeleccionados.join(',');

      // Cargar estadísticas dinámicas según filtros aplicados
      const statsRes = await productosAPI.statsDinamicos(params);
      setStats(statsRes.data);
    } catch (error) {
      console.error('Error cargando stats:', error);
    }
  };

  const cargarStatsOLD = async () => {
    try {
      // VERSIÓN ANTERIOR - Traer TODOS los productos filtrados (sin paginación) para calcular stats
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
      if (coloresSeleccionados.length > 0) params.colores = coloresSeleccionados.join(',');
      if (pmsSeleccionados.length > 0) params.pms = pmsSeleccionados.join(',');

      // Primero traer el total para saber cuántos productos filtrados hay
      const countRes = await productosAPI.listarTienda({ ...params, page: 1, page_size: 1 });
      const totalFiltrados = countRes.data.total || 0;

      // Ahora traer TODOS los productos filtrados
      params.page = 1;
      params.page_size = totalFiltrados || 9999;

      const todosRes = await productosAPI.listarTienda(params);
      const todosProductos = todosRes.data.productos;

      // Calcular estadísticas sobre TODOS los productos filtrados
      const fechaLimiteNuevos = new Date();
      fechaLimiteNuevos.setDate(fechaLimiteNuevos.getDate() - 7);

      let nuevos = 0;
      let nuevos_sin_precio = 0;
      let stock_sin_precio = 0;
      let sin_mla = 0;
      let sin_mla_con_stock = 0;
      let sin_mla_sin_stock = 0;
      let sin_mla_nuevos = 0;
      let oferta_sin_rebate = 0;
      let markup_neg_clasica = 0;
      let markup_neg_rebate = 0;
      let markup_neg_oferta = 0;
      let markup_neg_web = 0;
      let con_stock = 0;
      let con_precio = 0;

      todosProductos.forEach(p => {
        // Con stock
        if (p.stock > 0) con_stock++;

        // Con precio
        if (p.precio_lista_ml) con_precio++;

        // Nuevos (últimos 7 días)
        const esNuevo = p.fecha_sync && new Date(p.fecha_sync) >= fechaLimiteNuevos;
        if (esNuevo) {
          nuevos++;
          if (!p.precio_lista_ml) nuevos_sin_precio++;
        }

        // Stock sin precio
        if (p.stock > 0 && !p.precio_lista_ml) stock_sin_precio++;

        // Sin MLA
        if (!p.tiene_mla) {
          sin_mla++;
          if (p.stock > 0) sin_mla_con_stock++;
          else sin_mla_sin_stock++;
          if (esNuevo) sin_mla_nuevos++;
        }

        // Oferta sin rebate
        if (p.tiene_oferta && !p.participa_rebate) oferta_sin_rebate++;

        // Markup negativo clásica
        if (p.markup_calculado < 0) markup_neg_clasica++;

        // Markup negativo rebate
        if (p.participa_rebate && p.precio_lista_ml && p.costo) {
          const precioRebate = p.precio_lista_ml * (1 - (p.porcentaje_rebate || 0) / 100);
          if (precioRebate < p.costo) markup_neg_rebate++;
        }

        // Markup negativo oferta
        if (p.precio_3_cuotas && p.costo && p.precio_3_cuotas < p.costo) markup_neg_oferta++;

        // Markup negativo web
        if (p.participa_web_transferencia && p.precio_web_transferencia && p.costo && p.precio_web_transferencia < p.costo) {
          markup_neg_web++;
        }
      });

      setStats({
        total_productos: todosProductos.length,
        nuevos_ultimos_7_dias: nuevos,
        nuevos_sin_precio: nuevos_sin_precio,
        con_stock_sin_precio: stock_sin_precio,
        sin_mla_no_banlist: sin_mla,
        sin_mla_con_stock: sin_mla_con_stock,
        sin_mla_sin_stock: sin_mla_sin_stock,
        sin_mla_nuevos: sin_mla_nuevos,
        mejor_oferta_sin_rebate: oferta_sin_rebate,
        markup_negativo_clasica: markup_neg_clasica,
        markup_negativo_rebate: markup_neg_rebate,
        markup_negativo_oferta: markup_neg_oferta,
        markup_negativo_web: markup_neg_web,
        con_stock: con_stock,
        con_precio: con_precio
      });
    } catch (error) {
      console.error('Error cargando stats:', error);
    }
  };

  // Cargar configuración de Web Tarjeta
  const cargarConfigWebTarjeta = async () => {
    try {
      const response = await axios.get(`${API_URL}/markups-tienda/config/markup_web_tarjeta`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('token')}` }
      });
      setMarkupWebTarjeta(response.data.valor || 0);
    } catch (error) {
      console.error('Error cargando config web tarjeta:', error);
    }
  };

  useEffect(() => {
    cargarUsuariosAuditoria();
    cargarTiposAccion();
    cargarPMs();
    cargarConfigWebTarjeta();
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

      // Ctrl+F1/F2/F3
      if (e.ctrlKey && !e.shiftKey && (e.key === 'F1' || e.key === 'F2' || e.key === 'F3')) {
        accion = e.key === 'F1' ? 1 : e.key === 'F2' ? 2 : 3;
      }
      // Ctrl+Shift+1/2/3 (alternativa para sistemas que capturan F1/F2)
      if (e.ctrlKey && e.shiftKey && (e.key === '!' || e.key === '@' || e.key === '#' || e.key === '1' || e.key === '2' || e.key === '3')) {
        accion = (e.key === '1' || e.key === '!') ? 1 : (e.key === '2' || e.key === '@') ? 2 : 3;
      }

      if (accion) {
        // Prevenir comportamiento por defecto del navegador INMEDIATAMENTE
        e.preventDefault();
        e.stopPropagation();

        // Verificar si hay algo en modo edición O si hay una celda activa (navegación)
        const enModoEdicion = editandoPrecio || editandoRebate || editandoWebTransf || editandoCuota;
        const hayProductoSeleccionado = celdaActiva !== null && celdaActiva.rowIndex !== null;

        if (!enModoEdicion && !hayProductoSeleccionado) {
          showToast('⚠️ Debes posicionarte sobre un producto para usar este atajo', 'error');
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
          showToast('⚠️ Producto no encontrado', 'error');
          return;
        }

        if (!producto.codigo) {
          showToast('⚠️ El producto no tiene código asignado', 'error');
          return;
        }

        const itemCode = producto.codigo;

        // Acción 1: copiar solo el código
        if (accion === 1) {
          navigator.clipboard.writeText(itemCode).then(() => {
            showToast(`✅ Código copiado: ${itemCode}`);
          }).catch(err => {
            showToast('❌ Error al copiar al portapapeles', 'error');
            console.error('Error al copiar:', err);
          });
        }

        // Acción 2: primer enlace
        if (accion === 2) {
          const url = `https://listado.mercadolibre.com.ar/${itemCode}_OrderId_PRICE_NoIndex_True`;
          navigator.clipboard.writeText(url).then(() => {
            showToast(`✅ Enlace 1 copiado: ${itemCode}`);
          }).catch(err => {
            showToast('❌ Error al copiar al portapapeles', 'error');
            console.error('Error al copiar:', err);
          });
        }

        // Acción 3: segundo enlace
        if (accion === 3) {
          const url = `https://www.mercadolibre.com.ar/publicaciones/listado/promos?filters=official_store-57997&page=1&search=${itemCode}&sort=lowest_price`;
          navigator.clipboard.writeText(url).then(() => {
            showToast(`✅ Enlace 2 copiado: ${itemCode}`);
          }).catch(err => {
            showToast('❌ Error al copiar al portapapeles', 'error');
            console.error('Error al copiar:', err);
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
      console.error('Error cargando marcas:', error);
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
        `https://pricing.gaussonline.com.ar/api/productos/${itemId}/web-transferencia`,
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
      console.error('Error al guardar web transferencia:', error);
      alert('Error al guardar');
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

      if (coloresSeleccionados.length > 0) params.colores = coloresSeleccionados.join(',');

      if (pmsSeleccionados.length > 0) params.pms = pmsSeleccionados.join(',');

      if (ordenColumnas.length > 0) {
        params.orden_campos = ordenColumnas.map(o => o.columna).join(',');
        params.orden_direcciones = ordenColumnas.map(o => o.direccion).join(',');
      }

      /*const productosRes = await productosAPI.listar(params);
      setTotalProductos(productosRes.data.total || productosRes.data.productos.length);*/

      /*const productosConDatos = await Promise.all(
        productosRes.data.productos.map(async (p) => {
          const ofertasRes = await axios.get(`https://pricing.gaussonline.com.ar/api/productos/${p.item_id}/ofertas-vigentes`).catch(() => null);

          const ofertaMinima = ofertasRes?.data.publicaciones
            .filter(pub => pub.tiene_oferta)
            .sort((a, b) => a.oferta.precio_final - b.oferta.precio_final)[0];

          return {
            ...p,
            // mejor_oferta: ofertaMinima
            // p.markup ya viene del backend, no hace falta calcularlo
          };
        })
      );
      setProductos(productosConDatos);*/

      if (ordenColumnas.length > 0) {
        params.orden_campos = ordenColumnas.map(o => o.columna).join(',');
        params.orden_direcciones = ordenColumnas.map(o => o.direccion).join(',');
      }

      const productosRes = await productosAPI.listarTienda(params);
      setTotalProductos(productosRes.data.total || productosRes.data.productos.length);
      setProductos(productosRes.data.productos);

    } catch (error) {
      console.error('Error:', error);
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
      console.error('Error cargando subcategorías:', error);
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
        `https://pricing.gaussonline.com.ar/api/productos/${productoId}/auditoria`,
        { headers: { Authorization: `Bearer ${token}` }}
      );
      setAuditoriaData(response.data);
      setAuditoriaVisible(true);
    } catch (error) {
      console.error('Error cargando auditoría:', error);
      alert('Error al cargar el historial');
    }
  };

  const getMarkupColor = (markup) => {
    if (markup === null || markup === undefined) return '#6b7280';
    if (markup < 0) return '#ef4444';
    if (markup < 1) return '#f97316';
    return '#059669';
  };

  const COLORES_DISPONIBLES = [
    { id: 'rojo', nombre: 'Urgente', color: '#fee2e2', colorTexto: '#991b1b' },
    { id: 'naranja', nombre: 'Advertencia', color: '#fed7aa', colorTexto: '#9a3412' },
    { id: 'amarillo', nombre: 'Atención', color: '#fef3c7', colorTexto: '#92400e' },
    { id: 'verde', nombre: 'OK', color: '#d1fae5', colorTexto: '#065f46' },
    { id: 'azul', nombre: 'Info', color: '#dbeafe', colorTexto: '#1e40af' },
    { id: 'purpura', nombre: 'Revisión', color: '#e9d5ff', colorTexto: '#6b21a8' },
    { id: 'gris', nombre: 'Inactivo', color: '#e5e7eb', colorTexto: '#374151' },
    { id: null, nombre: 'Sin color', color: null, colorTexto: null },
  ];

  const cambiarColorProducto = async (itemId, color) => {
    try {
      const token = localStorage.getItem('token');
      console.log('Cambiando color desde dropdown:', { itemId, color });
      await axios.patch(
        `${API_URL}/productos/${itemId}/color-tienda`,
        { color },  // Enviar en el body, no en params
        {
          headers: { Authorization: `Bearer ${token}` }
        }
      );
      setColorDropdownAbierto(null);
      cargarProductos();
    } catch (error) {
      console.error('Error cambiando color:', error);
      console.error('Detalles:', error.response?.data);
      alert('Error al cambiar el color');
    }
  };

  const abrirModalBan = (producto) => {
    // Obtener palabras de la descripción (filtrar palabras de más de 3 caracteres)
    const palabras = producto.descripcion
      .split(/\s+/)
      .filter(p => p.length > 3)
      .map(p => p.replace(/[^a-zA-Z0-9áéíóúñÁÉÍÓÚÑ]/g, ''));

    if (palabras.length === 0) {
      alert('No hay palabras suficientes en la descripción del producto');
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
      alert('La palabra de verificación no coincide');
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
      console.error('Error al banear producto:', error);
      alert(`Error: ${error.response?.data?.detail || error.message}`);
    }
  };

  const handleSearchChange = (e) => {
    setSearchInput(e.target.value);
    setPage(1);
  };

  const iniciarEdicion = (producto) => {
    setEditandoPrecio(producto.item_id);
    setPrecioTemp(producto.precio_lista_ml || '');
  };

  const iniciarEdicionCuota = (producto, tipo) => {
    setEditandoCuota({ item_id: producto.item_id, tipo });
    const campoPrecio = `precio_${tipo}_cuotas`;
    setCuotaTemp(producto[campoPrecio] || '');
  };

  const guardarCuota = async (itemId, tipo) => {
    try {
      const token = localStorage.getItem('token');
      const precioNormalizado = parseFloat(cuotaTemp.toString().replace(',', '.'));

      const response = await axios.post(
        'https://pricing.gaussonline.com.ar/api/precios/set-cuota',
        null,
        {
          headers: { Authorization: `Bearer ${token}` },
          params: {
            item_id: itemId,
            tipo_cuota: tipo,
            precio: precioNormalizado
          }
        }
      );

      const campoPrecio = `precio_${tipo}_cuotas`;
      const campoMarkup = `markup_${tipo}_cuotas`;

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
      alert('Error al guardar precio de cuota');
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
        'https://pricing.gaussonline.com.ar/api/productos/actualizar-color-tienda-lote',
        {
          item_ids: Array.from(productosSeleccionados),
          color: color
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      setProductos(prods => prods.map(p =>
        productosSeleccionados.has(p.item_id)
          ? { ...p, color_marcado_tienda: color }
          : p
      ));

      limpiarSeleccion();
      cargarStats();
    } catch (error) {
      console.error(error);
      alert('Error al actualizar colores en lote');
    }
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
        `https://pricing.gaussonline.com.ar/api/productos/${productoConfig.item_id}/config-cuotas`,
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
      alert('Configuración actualizada correctamente');
    } catch (error) {
      alert('Error al guardar configuración: ' + (error.response?.data?.detail || error.message));
    }
  };

  const guardarPrecio = async (itemId) => {
    try {
      const token = localStorage.getItem('token');
      // Normalizar: reemplazar coma por punto
      const precioNormalizado = parseFloat(precioTemp.toString().replace(',', '.'));

      const response = await axios.post(
        'https://pricing.gaussonline.com.ar/api/precios/set-rapido',
        null,  // No body needed, all params go in URL
        {
          headers: { Authorization: `Bearer ${token}` },
          params: {
            item_id: itemId,
            precio: precioNormalizado,
            recalcular_cuotas: recalcularCuotasAuto  // Enviar flag de recalculo
          }
        }
      );

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
              markup_web_real: response.data.markup_web_real !== null && response.data.markup_web_real !== undefined ? response.data.markup_web_real : p.markup_web_real
            }
          : p
      ));

      setEditandoPrecio(null);
      cargarStats();
    } catch (error) {
      alert('Error al guardar precio');
    }
  };

  const guardarRebate = async (itemId) => {
    try {
      const token = localStorage.getItem('token');
      // Normalizar: reemplazar coma por punto
      const porcentajeNormalizado = parseFloat(rebateTemp.porcentaje.toString().replace(',', '.'));

      console.log('Enviando rebate:', rebateTemp);
      await axios.patch(
        `https://pricing.gaussonline.com.ar/api/productos/${itemId}/rebate`,
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
      console.error('Error al guardar rebate:', error);
      alert('Error al guardar rebate');
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
      console.error('Error cargando usuarios:', error);
    }
  };

  const cargarTiposAccion = async () => {
    try {
      const response = await axios.get(`${API_URL}/auditoria/tipos-accion`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('token')}` }
      });
      setTiposAccion(response.data.tipos);
    } catch (error) {
      console.error('Error cargando tipos:', error);
    }
  };

  const cargarPMs = async () => {
    try {
      const response = await axios.get(`${API_URL}/usuarios/pms?solo_con_marcas=true`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('token')}` }
      });
      setPms(response.data);
    } catch (error) {
      console.error('Error cargando PMs:', error);
    }
  };

  // Sistema de navegación por teclado
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Si hay un modal abierto, NO procesar shortcuts de la página
      const hayModalAbierto = mostrarExportModal || mostrarCalcularWebModal || mostrarModalConfig || mostrarModalInfo || mostrarShortcutsHelp;

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

      // Alt+V: Toggle Vista Normal / Vista Cuotas
      if (e.altKey && e.key === 'v') {
        e.preventDefault();
        setVistaModoCuotas(!vistaModoCuotas);
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

      // Ctrl+K: Abrir modal de calcular web
      if (e.ctrlKey && e.key === 'k') {
        e.preventDefault();
        setMostrarCalcularWebModal(true);
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
          if (puedeEditar && productos[rowIndex]) {
            // Colores válidos según el backend
            const colores = [null, 'rojo', 'naranja', 'amarillo', 'verde', 'azul', 'purpura', 'gris'];
            const colorIndex = parseInt(e.key);
            if (colorIndex < colores.length) {
              const producto = productos[rowIndex];
              const colorSeleccionado = colores[colorIndex];
              console.log('Cambiando color a:', colorSeleccionado || 'sin color', 'para producto:', producto.item_id);
              cambiarColorRapido(producto.item_id, colorSeleccionado);
            }
          }
          return;
        }

        // R: Toggle rebate (solo si NO estamos editando nada)
        if (e.key === 'r' && !editandoPrecio && !editandoRebate && !editandoWebTransf && puedeEditar) {
          e.preventDefault();
          const producto = productos[rowIndex];
          toggleRebateRapido(producto);
          return;
        }

        // W: Toggle web transferencia (solo si NO estamos editando nada)
        if (e.key === 'w' && !editandoPrecio && !editandoRebate && !editandoWebTransf && puedeEditar) {
          e.preventDefault();
          const producto = productos[rowIndex];
          toggleWebTransfRapido(producto);
          return;
        }

        // O: Toggle out of cards (solo si NO estamos editando nada)
        if (e.key === 'o' && !editandoPrecio && !editandoRebate && !editandoWebTransf && puedeEditar) {
          e.preventDefault();
          const producto = productos[rowIndex];
          toggleOutOfCardsRapido(producto);
          return;
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [modoNavegacion, celdaActiva, productos, editandoPrecio, editandoRebate, editandoWebTransf, editandoCuota, panelFiltroActivo, mostrarShortcutsHelp, puedeEditar, mostrarFiltrosAvanzados, vistaModoCuotas, recalcularCuotasAuto, mostrarExportModal, mostrarCalcularWebModal, mostrarModalConfig, mostrarModalInfo]);

  // Scroll automático para seguir la celda activa
  useEffect(() => {
    if (modoNavegacion && celdaActiva) {
      // Buscar la fila activa en el DOM
      const tabla = document.querySelector('.table-body');
      if (tabla) {
        const filas = tabla.querySelectorAll('tr');
        const filaActiva = filas[celdaActiva.rowIndex];
        if (filaActiva) {
          // Hacer scroll para que la fila esté visible y centrada
          filaActiva.scrollIntoView({
            behavior: 'smooth',
            block: 'center',  // Centrar la fila en la pantalla
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
    } else if (columna === 'precio_gremio') {
      // Precio Gremio es solo lectura - no se edita directamente
      // El markup se configura desde el tab de Admin/Markups
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
      console.log('Enviando cambio de color:', { itemId, color, url: `${API_URL}/productos/${itemId}/color` });
      const response = await axios.patch(
        `${API_URL}/productos/${itemId}/color`,
        { color },
        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
      );
      console.log('Respuesta del servidor:', response.data);
      cargarProductos();
    } catch (error) {
      console.error('Error cambiando color:', error);
      console.error('Detalles del error:', error.response?.data);
    }
  };

  const toggleRebateRapido = async (producto) => {
    try {
      // Si el rebate está desactivado, activarlo y abrir modo edición
      if (!producto.participa_rebate) {
        await axios.patch(
          `${API_URL}/productos/${producto.item_id}/rebate`,
          {
            participa_rebate: true,
            porcentaje_rebate: producto.porcentaje_rebate || 3.8
          },
          { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
        );

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

        cargarProductos();
      } else {
        // Si está activado, desactivarlo (comportamiento actual)
        await axios.patch(
          `${API_URL}/productos/${producto.item_id}/rebate`,
          {
            participa_rebate: false,
            porcentaje_rebate: producto.porcentaje_rebate || 3.8
          },
          { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
        );
        cargarProductos();
      }
    } catch (error) {
      console.error('Error toggling rebate:', error);
    }
  };

  const toggleWebTransfRapido = async (producto) => {
    try {
      await axios.patch(
        `${API_URL}/productos/${producto.item_id}/web-transferencia`,
        {
          participa: !producto.participa_web_transferencia,
          porcentaje: producto.porcentaje_markup_web || 6.0
        },
        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
      );
      cargarProductos();
    } catch (error) {
      console.error('Error toggling web transf:', error);
    }
  };

  const toggleOutOfCardsRapido = async (producto) => {
    try {
      // Si el rebate NO está activo, activarlo primero
      if (!producto.participa_rebate) {
        await axios.patch(
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

      cargarProductos();
    } catch (error) {
      console.error('Error toggling out of cards:', error);
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
      {/* Tabs de navegación */}
      <div className={dashboardStyles.tabs}>
        <button
          className={`${dashboardStyles.tab} ${tabActivo === 'productos' ? dashboardStyles.tabActivo : ''}`}
          onClick={() => setTabActivo('productos')}
        >
          📦 Productos
        </button>
        {puedeGestionarMarkups && (
          <button
            className={`${dashboardStyles.tab} ${tabActivo === 'setup-markups' ? dashboardStyles.tabActivo : ''}`}
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
        <div className="stat-card clickable" title="Click para limpiar todos los filtros" onClick={limpiarFiltros}>
          <div className="stat-label">📦 Total Productos</div>
          <div className="stat-value">{stats?.total_productos?.toLocaleString('es-AR') || 0}</div>
        </div>

        <div className="stat-card clickable" title="Desglose de stock y precios">
          <div className="stat-label">📊 Stock & Precio</div>
          <div className="stat-value-group">
            <div className="stat-sub-item clickable-sub" onClick={() => aplicarFiltroStat({ stock: 'con_stock' })}>
              <span className="stat-sub-label">Con Stock:</span>
              <span className="stat-sub-value green">{stats?.con_stock?.toLocaleString('es-AR') || 0}</span>
            </div>
            <div className="stat-sub-item clickable-sub" onClick={() => aplicarFiltroStat({ precio: 'con_precio' })}>
              <span className="stat-sub-label">Con Precio:</span>
              <span className="stat-sub-value blue">{stats?.con_precio?.toLocaleString('es-AR') || 0}</span>
            </div>
            <div className="stat-sub-item clickable-sub" onClick={() => aplicarFiltroStat({ stock: 'con_stock', precio: 'sin_precio' })}>
              <span className="stat-sub-label">Stock sin $:</span>
              <span className="stat-sub-value red">{stats?.con_stock_sin_precio?.toLocaleString('es-AR') || 0}</span>
            </div>
          </div>
        </div>

        <div className="stat-card clickable" title="Productos cargados en los últimos 7 días">
          <div className="stat-label">✨ Nuevos (7 días)</div>
          <div className="stat-value-group">
            <div className="stat-sub-item clickable-sub" onClick={() => aplicarFiltroStat({ nuevos: 'ultimos_7_dias' })}>
              <span className="stat-sub-label">Total:</span>
              <span className="stat-sub-value blue">{stats?.nuevos_ultimos_7_dias?.toLocaleString('es-AR') || 0}</span>
            </div>
            <div className="stat-sub-item clickable-sub" onClick={() => aplicarFiltroStat({ nuevos: 'ultimos_7_dias', precio: 'sin_precio' })}>
              <span className="stat-sub-label">Sin Precio:</span>
              <span className="stat-sub-value red">{stats?.nuevos_sin_precio?.toLocaleString('es-AR') || 0}</span>
            </div>
          </div>
        </div>

        <div className="stat-card clickable" title="Productos sin publicación en MercadoLibre (excluye banlist)">
          <div className="stat-label">🔍 Sin MLA</div>
          <div className="stat-value-group">
            <div className="stat-sub-item clickable-sub" onClick={() => aplicarFiltroStat({ mla: 'sin_mla' })}>
              <span className="stat-sub-label">Total:</span>
              <span className="stat-sub-value orange">{stats?.sin_mla_no_banlist?.toLocaleString('es-AR') || 0}</span>
            </div>
            <div className="stat-sub-item clickable-sub" onClick={() => aplicarFiltroStat({ mla: 'sin_mla', stock: 'con_stock' })}>
              <span className="stat-sub-label">Con Stock:</span>
              <span className="stat-sub-value green">{stats?.sin_mla_con_stock?.toLocaleString('es-AR') || 0}</span>
            </div>
            <div className="stat-sub-item clickable-sub" onClick={() => aplicarFiltroStat({ mla: 'sin_mla', stock: 'sin_stock' })}>
              <span className="stat-sub-label">Sin Stock:</span>
              <span className="stat-sub-value">{stats?.sin_mla_sin_stock?.toLocaleString('es-AR') || 0}</span>
            </div>
            <div className="stat-sub-item clickable-sub" onClick={() => aplicarFiltroStat({ mla: 'sin_mla', nuevos: 'ultimos_7_dias' })}>
              <span className="stat-sub-label">Nuevos:</span>
              <span className="stat-sub-value blue">{stats?.sin_mla_nuevos?.toLocaleString('es-AR') || 0}</span>
            </div>
          </div>
        </div>

        <div className="stat-card clickable" title="Click para filtrar productos con oferta sin rebate" onClick={() => aplicarFiltroStat({ oferta: 'con_oferta', rebate: 'sin_rebate' })}>
          <div className="stat-label">💎 Oferta sin Rebate</div>
          <div className="stat-value purple">{stats?.mejor_oferta_sin_rebate?.toLocaleString('es-AR') || 0}</div>
        </div>

        <div className="stat-card clickable" title="Productos con markup negativo en diferentes modalidades">
          <div className="stat-label">📉 Markup Negativo</div>
          <div className="stat-value-group">
            <div className="stat-sub-item clickable-sub" onClick={() => aplicarFiltroStat({ markupClasica: 'negativo' })}>
              <span className="stat-sub-label">Clásica:</span>
              <span className="stat-sub-value red">{stats?.markup_negativo_clasica || 0}</span>
            </div>
            <div className="stat-sub-item clickable-sub" onClick={() => aplicarFiltroStat({ markupRebate: 'negativo' })}>
              <span className="stat-sub-label">Rebate:</span>
              <span className="stat-sub-value red">{stats?.markup_negativo_rebate || 0}</span>
            </div>
            <div className="stat-sub-item clickable-sub" onClick={() => aplicarFiltroStat({ markupOferta: 'negativo' })}>
              <span className="stat-sub-label">Oferta:</span>
              <span className="stat-sub-value red">{stats?.markup_negativo_oferta || 0}</span>
            </div>
            <div className="stat-sub-item clickable-sub" onClick={() => aplicarFiltroStat({ markupWebTransf: 'negativo' })}>
              <span className="stat-sub-label">Web:</span>
              <span className="stat-sub-value red">{stats?.markup_negativo_web || 0}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="search-bar">
        <input
          type="text"
          placeholder="Buscar por código, descripción o marca... (ej: ean:123456, marca:Samsung, *123, código*)"
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
            <option value="todos">📦 Stock</option>
            <option value="con_stock">Con stock</option>
            <option value="sin_stock">Sin stock</option>
          </select>

          <select
            value={filtroPrecio}
            onChange={(e) => { setFiltroPrecio(e.target.value); setPage(1); }}
            className="filter-select-compact"
            title="Filtrar por precio"
          >
            <option value="todos">💰 Precio</option>
            <option value="con_precio">Con precio</option>
            <option value="sin_precio">Sin precio</option>
          </select>

          {/* Botones de filtro */}
          <button
            onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'marcas' ? null : 'marcas')}
            className={`filter-button marcas ${marcasSeleccionadas.length > 0 ? 'active' : ''}`}
          >
            🏷️ Marcas
            {marcasSeleccionadas.length > 0 && (
              <span className="filter-badge">{marcasSeleccionadas.length}</span>
            )}
          </button>

          <button
            onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'subcategorias' ? null : 'subcategorias')}
            className={`filter-button subcategorias ${subcategoriasSeleccionadas.length > 0 ? 'active' : ''}`}
          >
            📋 Subcategorías
            {subcategoriasSeleccionadas.length > 0 && (
              <span className="filter-badge">{subcategoriasSeleccionadas.length}</span>
            )}
          </button>

          <button
            onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'pms' ? null : 'pms')}
            className={`filter-button pms ${pmsSeleccionados.length > 0 ? 'active' : ''}`}
          >
            👤 PM
            {pmsSeleccionados.length > 0 && (
              <span className="filter-badge">{pmsSeleccionados.length}</span>
            )}
          </button>

          <button
            onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'auditoria' ? null : 'auditoria')}
            className={`filter-button auditoria ${(filtrosAuditoria.usuarios.length > 0 || filtrosAuditoria.tipos_accion.length > 0 || filtrosAuditoria.fecha_desde || filtrosAuditoria.fecha_hasta) ? 'active' : ''}`}
          >
            🔍 Auditoría
            {(filtrosAuditoria.usuarios.length > 0 || filtrosAuditoria.tipos_accion.length > 0) && (
              <span className="filter-badge">
                {filtrosAuditoria.usuarios.length + filtrosAuditoria.tipos_accion.length}
              </span>
            )}
          </button>

          <button
            onClick={() => setMostrarFiltrosAvanzados(!mostrarFiltrosAvanzados)}
            className={`filter-button advanced ${(filtroRebate || filtroOferta || filtroWebTransf || filtroMarkupClasica || filtroMarkupRebate || filtroMarkupOferta || filtroMarkupWebTransf || filtroOutOfCards || coloresSeleccionados.length > 0) ? 'active' : ''}`}
          >
            🎯 Avanzados
            {(filtroRebate || filtroOferta || filtroWebTransf || filtroMarkupClasica || filtroMarkupRebate || filtroMarkupOferta || filtroMarkupWebTransf || filtroOutOfCards || coloresSeleccionados.length > 0) && (
              <span className="filter-badge">
                {[filtroRebate, filtroOferta, filtroWebTransf, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards].filter(Boolean).length + coloresSeleccionados.length}
              </span>
            )}
          </button>

          <button
            onClick={limpiarTodosFiltros}
            className="filter-button clear-all"
            title="Limpiar todos los filtros"
          >
            🧹
          </button>

          {/* Separador visual */}
          <div className="filter-separator"></div>

          {/* Vista Normal/Cuotas */}
          <label className="filter-checkbox-label">
            <input
              type="checkbox"
              checked={vistaModoCuotas}
              onChange={(e) => {
                setVistaModoCuotas(e.target.checked);
                // Resetear columna activa para evitar ir a columnas ocultas
                if (celdaActiva) {
                  setCeldaActiva({ ...celdaActiva, colIndex: 0 });
                }
              }}
              className="filter-checkbox"
            />
            <span className="filter-checkbox-text">
              {vistaModoCuotas ? '📊 Cuotas' : '📋 Normal'}
            </span>
          </label>

          {/* Auto-recalcular */}
          <label className="filter-checkbox-label">
            <input
              type="checkbox"
              checked={recalcularCuotasAuto}
              onChange={(e) => setRecalcularCuotasAuto(e.target.checked)}
              className="filter-checkbox"
            />
            <span className="filter-checkbox-text">♻️ Auto-recalcular</span>
          </label>

          {/* Separador visual */}
          <div className="filter-separator"></div>

          {/* Botones de Exportar y Calcular */}
          <button
            onClick={() => setMostrarExportModal(true)}
            className="btn-action export"
          >
            <img src={xlsIcon} alt="Excel" />
            Exportar
          </button>

          <button
            onClick={() => setMostrarCalcularWebModal(true)}
            className="btn-action calculate"
          >
            🧮 Calcular Web Transf.
          </button>
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
                      className="btn-clear-all"
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
                      className="btn-clear-all"
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
                      className="btn-clear-all"
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
                    <div style={{ padding: '20px', textAlign: 'center', color: '#6b7280' }}>
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
                    className="btn-clear-all"
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
              className="btn-clear-all"
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
                      backgroundColor: c.color || '#ffffff',
                      border: coloresSeleccionados.includes(c.id === null ? 'sin_color' : c.id) ? '3px solid #000' : '2px solid #ccc',
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

      <div className="table-container">
        {loading ? (
          <div className="loading">Cargando...</div>
        ) : (
          <>
            <table className="table">
              <thead className="table-head">
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
                        Precio Gremio {getIconoOrden('precio_gremio')} {getNumeroOrden('precio_gremio') && <span>{getNumeroOrden('precio_gremio')}</span>}
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
              <tbody className="table-body">
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
                              p.catalog_status === 'winning' ? '#22c55e' :
                              p.catalog_status === 'sharing_first_place' ? '#3b82f6' :
                              p.catalog_status === 'competing' ? '#f59e0b' :
                              '#6b7280',
                            color: '#fff',
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
                      {p.precio_gremio_sin_iva ? (
                        <div className="gremio-info">
                          <div className="gremio-price">
                            ${p.precio_gremio_sin_iva.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </div>
                          <div className="gremio-price-iva">
                            ${p.precio_gremio_con_iva?.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
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
                    </td>
                    <td className={isRowActive && celdaActiva?.colIndex === 2 ? 'keyboard-cell-active' : ''}>
                      <div>
                        {/* Mostrar precios de Tienda Nube si existen */}
                        {(p.tn_price || p.tn_promotional_price) && (
                          <div className="web-transf-info" style={{ marginBottom: '8px', borderBottom: '1px solid #e5e7eb', paddingBottom: '6px' }}>
                            {p.tn_has_promotion && p.tn_promotional_price ? (
                              <div>
                                <div style={{ fontSize: '12px', fontWeight: '600', color: '#22c55e', display: 'flex', gap: '8px', alignItems: 'center' }}>
                                  <span>${p.tn_promotional_price.toLocaleString('es-AR')}</span>
                                  <span style={{ fontSize: '11px', color: '#3b82f6', fontWeight: '500' }}>
                                    ${(p.tn_promotional_price * 0.75).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} transf.
                                  </span>
                                </div>
                                {p.tn_price && (
                                  <div style={{
                                    fontSize: '10px',
                                    color: '#6b7280',
                                    textDecoration: 'line-through'
                                  }}>
                                    ${p.tn_price.toLocaleString('es-AR')}
                                  </div>
                                )}
                              </div>
                            ) : p.tn_price ? (
                              <div style={{ fontSize: '12px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                                <span>${p.tn_price.toLocaleString('es-AR')}</span>
                                <span style={{ fontSize: '11px', color: '#3b82f6', fontWeight: '500' }}>
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
                            style={{ width: '60px', padding: '4px', borderRadius: '4px', border: '1px solid #d1d5db' }}
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
                          className="icon-button info"
                          title="Información detallada (Ctrl+I)"
                        >
                          ℹ️
                        </button>
                        {puedeEditar && (
                          <button
                            onClick={() => setProductoSeleccionado(p)}
                            className="icon-button detail"
                            title="Ver detalle"
                          >
                            🔍
                          </button>
                        )}
                        <button
                          onClick={() => verAuditoria(p.item_id)}
                          className="icon-button audit"
                          title="Ver historial de cambios"
                        >
                          📋
                        </button>
                        {puedeEditar && (
                          <button
                            onClick={() => abrirModalConfig(p)}
                            className="icon-button config"
                            title="Configuración de cuotas"
                          >
                            ⚙️
                          </button>
                        )}
                        <div style={{ position: 'relative', display: 'inline-block' }}>
                          <button
                            onClick={() => setColorDropdownAbierto(colorDropdownAbierto === p.item_id ? null : p.item_id)}
                            className="icon-button color"
                            title="Marcar con color"
                          >
                            🎨
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
                                    border: c.id === p.color_marcado_tienda ? '2px solid #000' : '1px solid #ccc'
                                  }}
                                  onClick={() => cambiarColorProducto(p.item_id, c.id)}
                                  title={c.nombre}
                                >
                                  {c.nombre}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                        {['SUPERADMIN', 'ADMIN'].includes(user?.rol) && (
                          <button
                            onClick={() => abrirModalBan(p)}
                            className="icon-button ban"
                            title="Agregar a banlist"
                            style={{ color: '#ef4444' }}
                          >
                            🚫
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
                      <tbody className="table-body">
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

      {productoSeleccionado && (
        <PricingModal
          producto={productoSeleccionado}
          onClose={() => setProductoSeleccionado(null)}
          onSave={() => {
            setProductoSeleccionado(null);
            cargarProductos();
            cargarStats();
          }}
        />
      )}

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
        <div style={{
          position: 'fixed',
          bottom: '20px',
          left: '50%',
          transform: 'translateX(-50%)',
          backgroundColor: '#2563eb',
          color: 'white',
          padding: '15px 25px',
          borderRadius: '8px',
          boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          zIndex: 1000,
          display: 'flex',
          alignItems: 'center',
          gap: '15px'
        }}>
          <span style={{ fontWeight: 'bold' }}>
            {productosSeleccionados.size} producto{productosSeleccionados.size !== 1 ? 's' : ''} seleccionado{productosSeleccionados.size !== 1 ? 's' : ''}
          </span>
          <div style={{ display: 'flex', gap: '8px' }}>
            {COLORES_DISPONIBLES.map(c => (
              <button
                key={c.id}
                onClick={() => pintarLote(c.id)}
                style={{
                  width: '30px',
                  height: '30px',
                  borderRadius: '4px',
                  border: '2px solid white',
                  backgroundColor: c.color || '#f3f4f6',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
                title={c.nombre}
              >
                {!c.id && '✕'}
              </button>
            ))}
          </div>
          <button
            onClick={limpiarSeleccion}
            style={{
              backgroundColor: '#dc2626',
              color: 'white',
              border: 'none',
              padding: '8px 15px',
              borderRadius: '4px',
              cursor: 'pointer',
              fontWeight: 'bold'
            }}
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
              <p style={{ color: '#666', marginBottom: '20px', fontSize: '14px' }}>
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
                    border: '1px solid #d1d5db'
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
                    border: '1px solid #d1d5db'
                  }}
                />
                <p style={{ fontSize: '12px', color: '#666', marginTop: '5px' }}>
                  Dejar vacío para usar la configuración global
                </p>
              </div>

              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                <button
                  onClick={() => setMostrarModalConfig(false)}
                  style={{
                    padding: '10px 20px',
                    borderRadius: '4px',
                    border: '1px solid #d1d5db',
                    backgroundColor: 'white',
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
                    backgroundColor: '#2563eb',
                    color: 'white',
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
        <div className={`${styles.toast} ${toast.type === 'error' ? styles.error : ''}`}>
          {toast.message}
        </div>
      )}
      </>
      )}
    </div>
      );
    }
