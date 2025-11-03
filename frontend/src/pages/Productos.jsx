import { useState, useEffect } from 'react';
import { productosAPI } from '../services/api';
import PricingModal from '../components/PricingModal';
import { useDebounce } from '../hooks/useDebounce';
import styles from './Productos.module.css';
import axios from 'axios';
import { useAuthStore } from '../store/authStore';
import ExportModal from '../components/ExportModal';
import xlsIcon from '../assets/xls.svg';
import CalcularWebModal from '../components/CalcularWebModal';
import './Productos.css';

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
  const [webTransfTemp, setWebTransfTemp] = useState({ participa: false, porcentaje: 6.0 });
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
  const [filtroMarkupClasica, setFiltroMarkupClasica] = useState(null);
  const [filtroMarkupRebate, setFiltroMarkupRebate] = useState(null);
  const [filtroMarkupOferta, setFiltroMarkupOferta] = useState(null);
  const [filtroMarkupWebTransf, setFiltroMarkupWebTransf] = useState(null);
  const [filtroOutOfCards, setFiltroOutOfCards] = useState(null);
  const [mostrarFiltrosAvanzados, setMostrarFiltrosAvanzados] = useState(false);
  const [colorDropdownAbierto, setColorDropdownAbierto] = useState(null); // item_id del producto
  const [coloresSeleccionados, setColoresSeleccionados] = useState([]);
  const [pms, setPms] = useState([]);
  const [pmsSeleccionados, setPmsSeleccionados] = useState([]);

  // Estados para navegación por teclado
  const [celdaActiva, setCeldaActiva] = useState(null); // { rowIndex, colIndex }
  const [modoNavegacion, setModoNavegacion] = useState(false);
  const [mostrarShortcutsHelp, setMostrarShortcutsHelp] = useState(false);

  const user = useAuthStore((state) => state.user);
  const puedeEditar = ['SUPERADMIN', 'ADMIN', 'GERENTE', 'PRICING'].includes(user?.rol);

  // Columnas editables (solo precios)
  const columnasEditables = ['precio_clasica', 'precio_rebate', 'mejor_oferta', 'precio_web_transf'];

  const debouncedSearch = useDebounce(searchInput, 500);

  const API_URL = 'https://pricing.gaussonline.com.ar/api';

  useEffect(() => {
    cargarStats();
  }, []);

  useEffect(() => {
    cargarProductos();
  }, [page, debouncedSearch, filtroStock, filtroPrecio, pageSize, marcasSeleccionadas, subcategoriasSeleccionadas, ordenColumnas, filtrosAuditoria, filtroRebate, filtroOferta, filtroWebTransf, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards, coloresSeleccionados, pmsSeleccionados]);

  const cargarStats = async () => {
    try {
      const statsRes = await productosAPI.stats();
      setStats(statsRes.data);
    } catch (error) {
      console.error('Error:', error);
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
  }, [debouncedSearch, filtroStock, filtroPrecio, subcategoriasSeleccionadas, filtroRebate, filtroOferta, filtroWebTransf, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards, coloresSeleccionados, filtrosAuditoria]);

  // Recargar subcategorías cuando cambien filtros (excepto subcategoriasSeleccionadas)
  useEffect(() => {
    cargarSubcategorias();
  }, [debouncedSearch, filtroStock, filtroPrecio, marcasSeleccionadas, filtroRebate, filtroOferta, filtroWebTransf, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards, coloresSeleccionados, filtrosAuditoria]);

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

  const marcasFiltradas = marcas.filter(m =>
    m.toLowerCase().includes(busquedaMarca.toLowerCase())
  );

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
      porcentaje: producto.porcentaje_markup_web || 6.0
    });
  };

  const guardarWebTransf = async (itemId) => {
    try {
      const token = localStorage.getItem('token');
      const porcentajeNumerico = parseFloat(webTransfTemp.porcentaje) || 0;  // ← AGREGAR
  
      const response = await axios.patch(
        `https://pricing.gaussonline.com.ar/api/productos/${itemId}/web-transferencia`,
        null,
        {
          params: {
            participa: webTransfTemp.participa,
            porcentaje_markup: porcentajeNumerico  // ← CAMBIAR de webTransfTemp.porcentaje
          },
          headers: { Authorization: `Bearer ${token}` }
        }
      );
  
      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? {
              ...p,
              participa_web_transferencia: webTransfTemp.participa,
              porcentaje_markup_web: porcentajeNumerico,  // ← CAMBIAR
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

      const productosRes = await productosAPI.listar(params);
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
    setFiltroMarkupClasica(null);
    setFiltroMarkupRebate(null);
    setFiltroMarkupOferta(null);
    setFiltroMarkupWebTransf(null);
    setFiltroOutOfCards(null);
    setColoresSeleccionados([]);
    setOrdenColumnas([]);
    setPage(1);
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
      await axios.patch(
        `https://pricing.gaussonline.com.ar/api/productos/${itemId}/color`,
        null,
        {
          headers: { Authorization: `Bearer ${token}` },
          params: { color }
        }
      );
      setColorDropdownAbierto(null);
      cargarProductos();
    } catch (error) {
      console.error('Error cambiando color:', error);
      alert('Error al cambiar el color');
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

  const guardarPrecio = async (itemId) => {
    try {
      const token = localStorage.getItem('token');
      const precioLimpio = parseFloat(precioTemp.toString().replace(/\./g, '').replace(',', '.'));
      const response = await axios.post(
        'https://pricing.gaussonline.com.ar/api/precios/set-rapido',
        { item_id: itemId, precio: parseFloat(precioTemp) },
        {
          headers: { Authorization: `Bearer ${token}` },
          params: { item_id: itemId, precio: parseFloat(precioTemp) }
        }
      );

      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? { ...p, precio_lista_ml: parseFloat(precioTemp), markup: response.data.markup }
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
      console.log('Enviando rebate:', rebateTemp);
      await axios.patch(
        `https://pricing.gaussonline.com.ar/api/productos/${itemId}/rebate`,
        {
          participa_rebate: rebateTemp.participa,
          porcentaje_rebate: rebateTemp.porcentaje
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? {
              ...p,
              participa_rebate: rebateTemp.participa,
              porcentaje_rebate: rebateTemp.porcentaje,
              precio_rebate: rebateTemp.participa && p.precio_lista_ml
                ? p.precio_lista_ml / (1 - rebateTemp.porcentaje / 100)
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
      // Si estamos editando una celda
      if (editandoPrecio || editandoRebate || editandoWebTransf) {
        // Interceptar Escape para salir de edición
        if (e.key === 'Escape') {
          e.preventDefault();
          setEditandoPrecio(null);
          setEditandoRebate(null);
          setEditandoWebTransf(null);
          return;
        }
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

      // Escape: Salir de modo navegación o cerrar paneles
      if (e.key === 'Escape') {
        e.preventDefault();
        setCeldaActiva(null);
        setModoNavegacion(false);
        setPanelFiltroActivo(null);
        setColorDropdownAbierto(null);
        setMostrarShortcutsHelp(false);
        return;
      }

      // Ctrl+F: Focus en búsqueda
      if (e.ctrlKey && e.key === 'f') {
        e.preventDefault();
        document.querySelector('.search-bar input')?.focus();
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

      // Alt+C: Toggle filtro de colores
      if (e.altKey && e.key === 'c') {
        e.preventDefault();
        setPanelFiltroActivo(panelFiltroActivo === 'colores' ? null : 'colores');
        return;
      }

      // Alt+F: Toggle filtros avanzados
      if (e.altKey && e.key === 'f') {
        e.preventDefault();
        setMostrarFiltrosAvanzados(!mostrarFiltrosAvanzados);
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
        if (e.key === 'Enter' && !editandoPrecio && !editandoRebate && !editandoWebTransf && puedeEditar) {
          e.preventDefault();
          const producto = productos[rowIndex];
          const columna = columnasEditables[colIndex];
          iniciarEdicionDesdeTeclado(producto, columna);
          return;
        }

        // Flechas: Navegación por celdas (solo si NO estamos editando)
        if (e.key === 'ArrowRight' && !editandoPrecio && !editandoRebate && !editandoWebTransf) {
          e.preventDefault();
          if (colIndex < columnasEditables.length - 1) {
            setCeldaActiva({ rowIndex, colIndex: colIndex + 1 });
          }
          return;
        }

        if (e.key === 'ArrowLeft' && !editandoPrecio && !editandoRebate && !editandoWebTransf) {
          e.preventDefault();
          if (colIndex > 0) {
            setCeldaActiva({ rowIndex, colIndex: colIndex - 1 });
          }
          return;
        }

        if (e.key === 'ArrowDown' && !editandoPrecio && !editandoRebate && !editandoWebTransf) {
          e.preventDefault();
          if (e.shiftKey) {
            // Shift+ArrowDown: Ir al final de la tabla
            setCeldaActiva({ rowIndex: productos.length - 1, colIndex });
          } else if (rowIndex < productos.length - 1) {
            setCeldaActiva({ rowIndex: rowIndex + 1, colIndex });
          }
          return;
        }

        if (e.key === 'ArrowUp' && !editandoPrecio && !editandoRebate && !editandoWebTransf) {
          e.preventDefault();
          if (e.shiftKey) {
            // Shift+ArrowUp: Ir al inicio de la tabla
            setCeldaActiva({ rowIndex: 0, colIndex });
          } else if (rowIndex > 0) {
            setCeldaActiva({ rowIndex: rowIndex - 1, colIndex });
          }
          return;
        }

        // PageUp: Subir 10 filas (solo si NO estamos editando)
        if (e.key === 'PageUp' && !editandoPrecio && !editandoRebate && !editandoWebTransf) {
          e.preventDefault();
          const newRow = Math.max(0, rowIndex - 10);
          setCeldaActiva({ rowIndex: newRow, colIndex });
          return;
        }

        // PageDown: Bajar 10 filas (solo si NO estamos editando)
        if (e.key === 'PageDown' && !editandoPrecio && !editandoRebate && !editandoWebTransf) {
          e.preventDefault();
          const newRow = Math.min(productos.length - 1, rowIndex + 10);
          setCeldaActiva({ rowIndex: newRow, colIndex });
          return;
        }

        // Home: Ir a primera columna (solo si NO estamos editando)
        if (e.key === 'Home' && !editandoPrecio && !editandoRebate && !editandoWebTransf) {
          e.preventDefault();
          setCeldaActiva({ rowIndex, colIndex: 0 });
          return;
        }

        // End: Ir a última columna (solo si NO estamos editando)
        if (e.key === 'End' && !editandoPrecio && !editandoRebate && !editandoWebTransf) {
          e.preventDefault();
          setCeldaActiva({ rowIndex, colIndex: columnasEditables.length - 1 });
          return;
        }

        // Espacio: Editar precio en celda activa (solo si NO estamos editando nada)
        if (e.key === ' ' && !editandoPrecio && !editandoRebate && !editandoWebTransf && puedeEditar) {
          e.preventDefault();
          const producto = productos[rowIndex];
          const columna = columnasEditables[colIndex];
          iniciarEdicionDesdeTeclado(producto, columna);
          return;
        }

        // Números 1-9: Selección rápida de colores (solo si NO estamos editando nada)
        if (!editandoPrecio && !editandoRebate && !editandoWebTransf && /^[1-9]$/.test(e.key)) {
          e.preventDefault();
          const colores = ['rojo', 'amarillo', 'verde', 'azul', 'naranja', 'violeta', 'rosa', 'gris', 'cyan'];
          const colorIndex = parseInt(e.key) - 1;
          if (colorIndex < colores.length && puedeEditar) {
            const producto = productos[rowIndex];
            cambiarColorRapido(producto.item_id, colores[colorIndex]);
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
  }, [modoNavegacion, celdaActiva, productos, editandoPrecio, panelFiltroActivo, mostrarShortcutsHelp, puedeEditar, mostrarFiltrosAvanzados]);

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
    }
  };

  const cambiarColorRapido = async (itemId, color) => {
    try {
      await axios.patch(
        `${API_URL}/productos/${itemId}/color`,
        { color },
        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
      );
      cargarProductos();
    } catch (error) {
      console.error('Error cambiando color:', error);
    }
  };

  const toggleRebateRapido = async (producto) => {
    try {
      await axios.patch(
        `${API_URL}/productos/${producto.item_id}/rebate`,
        {
          participa_rebate: !producto.participa_rebate,
          porcentaje_rebate: producto.porcentaje_rebate || 3.8
        },
        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
      );
      cargarProductos();
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
      await axios.patch(
        `${API_URL}/productos/${producto.item_id}/out-of-cards`,
        { out_of_cards: !producto.out_of_cards },
        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
      );
      cargarProductos();
    } catch (error) {
      console.error('Error toggling out of cards:', error);
    }
  };

  return (
    <div className="productos-container">
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">Total Productos</div>
          <div className="stat-value">{stats?.total_productos || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Con Stock</div>
          <div className="stat-value green">{stats?.con_stock || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Sin Precio</div>
          <div className="stat-value red">{stats?.sin_precio || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Con Precio</div>
          <div className="stat-value blue">{stats?.con_precio || 0}</div>
        </div>
      </div>

      <div className="search-bar">
        <input
          type="text"
          placeholder="Buscar por código, descripción o marca..."
          value={searchInput}
          onChange={handleSearchChange}
          className="search-input"
        />
      </div>

      <div className="filters-container-modern">
        {/* Filtros Básicos */}
        <div className="filters-basic-group">
          <div className="filter-item-inline">
            <label className="filter-label">📦 Stock</label>
            <select
              value={filtroStock}
              onChange={(e) => { setFiltroStock(e.target.value); setPage(1); }}
              className="filter-select-modern"
            >
              <option value="todos">Todos</option>
              <option value="con_stock">Con stock</option>
              <option value="sin_stock">Sin stock</option>
            </select>
          </div>

          <div className="filter-item-inline">
            <label className="filter-label">💰 Precio</label>
            <select
              value={filtroPrecio}
              onChange={(e) => { setFiltroPrecio(e.target.value); setPage(1); }}
              className="filter-select-modern"
            >
              <option value="todos">Todos</option>
              <option value="con_precio">Con precio</option>
              <option value="sin_precio">Sin precio</option>
            </select>
          </div>
        </div>

        {/* Filtros de Dropdown */}
        <div className="filters-dropdown-card">
          {/* Filtro de Marcas */}
          <button
            onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'marcas' ? null : 'marcas')}
            className={`filter-button marcas ${marcasSeleccionadas.length > 0 ? 'active' : ''}`}
          >
            🏷️ Marcas {marcasSeleccionadas.length > 0 && `(${marcasSeleccionadas.length})`}
          </button>

          {/* Filtro de Subcategorías */}
          <button
            onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'subcategorias' ? null : 'subcategorias')}
            className={`filter-button subcategorias ${subcategoriasSeleccionadas.length > 0 ? 'active' : ''}`}
          >
            📋 Subcategorías
            {subcategoriasSeleccionadas.length > 0 && (
              <span className="filter-badge">
                {subcategoriasSeleccionadas.length}
              </span>
            )}
          </button>

          {/* Filtro de PMs */}
          <button
            onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'pms' ? null : 'pms')}
            className={`filter-button pms ${pmsSeleccionados.length > 0 ? 'active' : ''}`}
          >
            👤 PM
            {pmsSeleccionados.length > 0 && (
              <span className="filter-badge">
                {pmsSeleccionados.length}
              </span>
            )}
          </button>

          {/* Filtros de Auditoría */}
          <button
            onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'auditoria' ? null : 'auditoria')}
            className={`filter-button auditoria ${(filtrosAuditoria.usuarios.length > 0 || filtrosAuditoria.tipos_accion.length > 0 || filtrosAuditoria.fecha_desde || filtrosAuditoria.fecha_hasta) ? 'active' : ''}`}
          >
            🔍 Filtros de Auditoría
            {(filtrosAuditoria.usuarios.length > 0 || filtrosAuditoria.tipos_accion.length > 0) && (
              <span className="filter-badge">
                {filtrosAuditoria.usuarios.length + filtrosAuditoria.tipos_accion.length}
              </span>
            )}
          </button>

          {/* Botón de filtros avanzados */}
          <button
            onClick={() => setMostrarFiltrosAvanzados(!mostrarFiltrosAvanzados)}
            className={`filter-button advanced ${(filtroRebate || filtroOferta || filtroWebTransf || filtroMarkupClasica || filtroMarkupRebate || filtroMarkupOferta || filtroMarkupWebTransf || filtroOutOfCards || coloresSeleccionados.length > 0) ? 'active' : ''}`}
          >
            🎯 Filtros Avanzados
            {(filtroRebate || filtroOferta || filtroWebTransf || filtroMarkupClasica || filtroMarkupRebate || filtroMarkupOferta || filtroMarkupWebTransf || filtroOutOfCards || coloresSeleccionados.length > 0) && (
              <span className="filter-badge">
                {[filtroRebate, filtroOferta, filtroWebTransf, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards].filter(Boolean).length + coloresSeleccionados.length}
              </span>
            )}
          </button>

          {/* Botón limpiar todos los filtros */}
          <button
            onClick={limpiarTodosFiltros}
            className="filter-button clear-all"
            title="Limpiar todos los filtros"
          >
            🧹
          </button>
        </div>
        {/* Botones de Acción */}
        <div className="action-buttons-card">
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

                      const subcatsDeCategoria = categoriaCoincide
                        ? categoria.subcategorias
                        : categoria.subcategorias.filter(sub =>
                            sub.nombre.toLowerCase().includes(busquedaSubcategoria.toLowerCase())
                          );

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
                setFiltroMarkupClasica(null);
                setFiltroMarkupRebate(null);
                setFiltroMarkupOferta(null);
                setFiltroMarkupWebTransf(null);
                setFiltroOutOfCards(null);
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

            {/* Filtros de Color */}
            <div className="filter-group">
              <div className="filter-group-title">🎨 Marcado por Color</div>
              <div className="filter-group-content" style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {COLORES_DISPONIBLES.filter(c => c.id !== null).map(c => (
                  <label
                    key={c.id}
                    className="color-checkbox"
                    style={{
                      backgroundColor: c.color,
                      border: coloresSeleccionados.includes(c.id) ? '3px solid #000' : '2px solid #ccc',
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
                      checked={coloresSeleccionados.includes(c.id)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setColoresSeleccionados([...coloresSeleccionados, c.id]);
                        } else {
                          setColoresSeleccionados(coloresSeleccionados.filter(color => color !== c.id));
                        }
                        setPage(1);
                      }}
                      style={{ display: 'none' }}
                    />
                    {coloresSeleccionados.includes(c.id) && <span style={{ fontSize: '20px' }}>✓</span>}
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
                  <th onClick={(e) => handleOrdenar('precio_rebate', e)}>
                    Precio Rebate {getIconoOrden('precio_rebate')} {getNumeroOrden('precio_rebate') && <span>{getNumeroOrden('precio_rebate')}</span>}
                  </th>
                  <th onClick={(e) => handleOrdenar('mejor_oferta', e)}>
                    Mejor Oferta {getIconoOrden('mejor_oferta')} {getNumeroOrden('mejor_oferta') && <span>{getNumeroOrden('mejor_oferta')}</span>}
                  </th>
                  <th onClick={(e) => handleOrdenar('web_transf', e)}>
                    Web Transf. {getIconoOrden('web_transf')} {getNumeroOrden('web_transf') && <span>{getNumeroOrden('web_transf')}</span>}
                  </th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody className="table-body">
                {productosOrdenados.map((p, rowIndex) => {
                  const colorInfo = COLORES_DISPONIBLES.find(c => c.id === p.color_marcado);
                  const rowStyle = colorInfo?.color ? { backgroundColor: colorInfo.color } : undefined;
                  const isRowActive = modoNavegacion && celdaActiva?.rowIndex === rowIndex;
                  return (
                  <tr
                    key={p.item_id}
                    style={rowStyle}
                    className={`${p.color_marcado ? 'row-colored' : ''} ${isRowActive ? 'keyboard-row-active' : ''}`}
                  >
                    <td>{p.codigo}</td>
                    <td>{p.descripcion}</td>
                    <td>{p.marca}</td>
                    <td>{p.stock}</td>
                    <td>{p.moneda_costo} ${p.costo?.toFixed(2)}</td>
                    <td className={isRowActive && celdaActiva?.colIndex === 0 ? 'keyboard-cell-active' : ''}>
                      {editandoPrecio === p.item_id ? (
                        <div className="inline-edit">
                          <input
                            type="number"
                            value={precioTemp}
                            onChange={(e) => setPrecioTemp(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault();
                                guardarPrecio(p.item_id);
                              }
                            }}
                            autoFocus
                          />
                          <button onClick={() => guardarPrecio(p.item_id)} onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              guardarPrecio(p.item_id);
                            }
                          }}>✓</button>
                          <button onClick={() => setEditandoPrecio(null)} onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              setEditandoPrecio(null);
                            }
                          }}>✗</button>
                        </div>
                      ) : (
                        <div onClick={() => puedeEditar && iniciarEdicion(p)}>
                          <div className={puedeEditar ? 'editable-field' : ''}>
                            {p.precio_lista_ml ? `$${p.precio_lista_ml.toLocaleString('es-AR')}` : 'Sin precio'}
                          </div>
                          {p.markup !== null && p.markup !== undefined && (
                            <div className="markup-display" style={{ color: getMarkupColor(p.markup) }}>
                              {p.markup}%
                            </div>
                          )}
                        </div>
                      )}
                    </td>
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
                              autoFocus
                            />
                            <span>Rebate</span>
                          </label>
                          {rebateTemp.participa && (
                            <input
                              type="number"
                              step="0.1"
                              value={rebateTemp.porcentaje}
                              onChange={(e) => setRebateTemp({ ...rebateTemp, porcentaje: parseFloat(e.target.value) })}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  e.preventDefault();
                                  guardarRebate(p.item_id);
                                }
                              }}
                              placeholder="%"
                            />
                          )}
                          <div className="inline-edit">
                            <button onClick={() => guardarRebate(p.item_id)} onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault();
                                guardarRebate(p.item_id);
                              }
                            }}>✓</button>
                            <button onClick={() => setEditandoRebate(null)} onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault();
                                setEditandoRebate(null);
                              }
                            }}>✗</button>
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
                                    try {
                                      await axios.patch(
                                        `${API_URL}/productos/${p.item_id}/out-of-cards`,
                                        { out_of_cards: e.target.checked },
                                        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
                                      );
                                      await cargarProductos();
                                    } catch (error) {
                                      console.error('Error:', error);
                                      alert(`Error: ${error.response?.data?.detail || error.message}`);
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
                            value={webTransfTemp.porcentaje}
                            onChange={(e) => {
                              const valor = e.target.value;
                              // Permitir solo números, punto decimal y guión al inicio
                              if (valor === '' || valor === '-' || /^-?\d*\.?\d*$/.test(valor)) {
                                setWebTransfTemp({...webTransfTemp, porcentaje: valor});
                              }
                            }}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault();
                                guardarWebTransf(p.item_id);
                              }
                            }}
                            placeholder="%"
                            style={{ width: '60px', padding: '4px', borderRadius: '4px', border: '1px solid #d1d5db' }}
                          />
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
                    </td>
                    <td className="table-actions">
                      <div className="table-actions-group">
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
                                    border: c.id === p.color_marcado ? '2px solid #000' : '1px solid #ccc'
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
                      </div>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>

{auditoriaVisible && (
              <div className="modal-overlay">
                <div className="modal-content">
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
            coloresSeleccionados,
            audit_usuarios: filtrosAuditoria.usuarios,
            audit_tipos_accion: filtrosAuditoria.tipos_accion,
            audit_fecha_desde: filtrosAuditoria.fecha_desde,
            audit_fecha_hasta: filtrosAuditoria.fecha_hasta
          }}
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
        />
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
                  <kbd>1</kbd>-<kbd>9</kbd>
                  <span>Asignar color (1=Rojo, 2=Amarillo, 3=Verde, etc.)</span>
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
    </div>
      );
    }
