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
  const [filtroStock, setFiltroStock] = useState(null);
  const [filtroPrecio, setFiltroPrecio] = useState(null);
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
  const [mostrarMenuMarcas, setMostrarMenuMarcas] = useState(false);
  const [busquedaMarca, setBusquedaMarca] = useState('');
  const [ordenColumna, setOrdenColumna] = useState(null);
  const [ordenDireccion, setOrdenDireccion] = useState('asc');
  const [ordenColumnas, setOrdenColumnas] = useState([]);
  const [subcategorias, setSubcategorias] = useState([]);
  const [subcategoriasSeleccionadas, setSubcategoriasSeleccionadas] = useState([]);
  const [mostrarMenuSubcategorias, setMostrarMenuSubcategorias] = useState(false);
  const [busquedaSubcategoria, setBusquedaSubcategoria] = useState('');
  const [usuarios, setUsuarios] = useState([]);
  const [tiposAccion, setTiposAccion] = useState([]);
  const [filtrosAuditoria, setFiltrosAuditoria] = useState({
    usuarios: [],
    tipos_accion: [],
    fecha_desde: '',
    fecha_hasta: ''
  });
  const [mostrarFiltrosAuditoria, setMostrarFiltrosAuditoria] = useState(false);
  const [filtroRebate, setFiltroRebate] = useState(null);
  const [filtroOferta, setFiltroOferta] = useState(null);
  const [filtroWebTransf, setFiltroWebTransf] = useState(null);
  const [filtroMarkupClasica, setFiltroMarkupClasica] = useState(null);
  const [filtroMarkupRebate, setFiltroMarkupRebate] = useState(null);
  const [filtroMarkupOferta, setFiltroMarkupOferta] = useState(null);
  const [filtroMarkupWebTransf, setFiltroMarkupWebTransf] = useState(null);
  const [filtroOutOfCards, setFiltroOutOfCards] = useState(null);
  const [mostrarFiltrosAvanzados, setMostrarFiltrosAvanzados] = useState(false);

  const user = useAuthStore((state) => state.user);
  const puedeEditar = ['SUPERADMIN', 'ADMIN', 'GERENTE', 'PRICING'].includes(user?.rol);

  const debouncedSearch = useDebounce(searchInput, 500);

  const API_URL = 'https://pricing.gaussonline.com.ar/api';

  useEffect(() => {
    cargarStats();
  }, []);

  useEffect(() => {
    cargarProductos();
  }, [page, debouncedSearch, filtroStock, filtroPrecio, pageSize, marcasSeleccionadas, subcategoriasSeleccionadas, ordenColumnas, filtrosAuditoria, filtroRebate, filtroOferta, filtroWebTransf, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards]);

  const cargarStats = async () => {
    try {
      const statsRes = await productosAPI.stats();
      setStats(statsRes.data);
    } catch (error) {
      console.error('Error:', error);
    }
  };

  useEffect(() => {
    cargarMarcas();
    cargarSubcategorias();
    cargarUsuariosAuditoria();
    cargarTiposAccion();
  }, []);

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

  const productosOrdenados = [...productos].sort((a, b) => {
    if (ordenColumnas.length === 0) return 0;

    // Ordenar por cada columna en orden de prioridad
    for (const { columna, direccion } of ordenColumnas) {
      let valorA, valorB;
      let comparacion = 0;

      switch(columna) {
        case 'codigo':
          valorA = a.codigo || '';
          valorB = b.codigo || '';
          comparacion = direccion === 'asc'
            ? valorA.localeCompare(valorB, 'es', { numeric: true })
            : valorB.localeCompare(valorA, 'es', { numeric: true });
          break;

        case 'descripcion':
          valorA = a.descripcion || '';
          valorB = b.descripcion || '';
          comparacion = direccion === 'asc'
            ? valorA.localeCompare(valorB)
            : valorB.localeCompare(valorA);
          break;

        case 'marca':
          valorA = a.marca || '';
          valorB = b.marca || '';
          comparacion = direccion === 'asc'
            ? valorA.localeCompare(valorB)
            : valorB.localeCompare(valorA);
          break;

        case 'stock':
          valorA = a.stock ?? -Infinity;
          valorB = b.stock ?? -Infinity;
          comparacion = direccion === 'asc' ? valorA - valorB : valorB - valorA;
          break;

        case 'costo':
          valorA = a.costo ?? -Infinity;
          valorB = b.costo ?? -Infinity;
          comparacion = direccion === 'asc' ? valorA - valorB : valorB - valorA;
          break;

        case 'precio_clasica':
          valorA = a.markup ?? -Infinity;
          valorB = b.markup ?? -Infinity;
          comparacion = direccion === 'asc' ? valorA - valorB : valorB - valorA;
          break;

        case 'precio_rebate':
          valorA = a.markup_rebate ?? -Infinity;
          valorB = b.markup_rebate ?? -Infinity;
          comparacion = direccion === 'asc' ? valorA - valorB : valorB - valorA;
          break;

        case 'mejor_oferta':
          valorA = (a.mejor_oferta_markup !== null ? a.mejor_oferta_markup * 100 : -Infinity);
          valorB = (b.mejor_oferta_markup !== null ? b.mejor_oferta_markup * 100 : -Infinity);
          comparacion = direccion === 'asc' ? valorA - valorB : valorB - valorA;
          break;

        case 'web_transf':
          valorA = a.markup_web_real ?? -Infinity;
          valorB = b.markup_web_real ?? -Infinity;
          comparacion = direccion === 'asc' ? valorA - valorB : valorB - valorA;
          break;
      }

      // Si hay diferencia en esta columna, retornar
      if (comparacion !== 0) return comparacion;
    }

    return 0;
  });


  const marcasFiltradas = marcas.filter(m =>
    m.toLowerCase().includes(busquedaMarca.toLowerCase())
  );

  const cargarMarcas = async () => {
    try {
      const response = await productosAPI.marcas();
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
      const response = await productosAPI.subcategorias();
      setSubcategorias(response.data.categorias); // ← Cambiar de .subcategorias a .categorias
    } catch (error) {
      console.error('Error cargando subcategorías:', error);
    }
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
        <div className="filters-dropdown-group">
        {/* Filtro de Marcas */}
        <div className="filter-dropdown">
          <button
            onClick={() => setMostrarMenuMarcas(!mostrarMenuMarcas)}
            className={`filter-button marcas ${marcasSeleccionadas.length > 0 ? 'active' : ''}`}
          >
            🏷️ Marcas {marcasSeleccionadas.length > 0 && `(${marcasSeleccionadas.length})`}
          </button>

          {mostrarMenuMarcas && (
          	<>
          	<div onClick={() => setMostrarMenuMarcas(false)} className="dropdown-overlay" />
            <div className="dropdown-panel marcas">
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

                {marcasSeleccionadas.length > 0 && (
                  <button
                    onClick={() => {
                      setMarcasSeleccionadas([]);
                      setPage(1);
                    }}
                    className="btn-clear"
                  >
                    Limpiar filtros ({marcasSeleccionadas.length})
                  </button>
                )}
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
            </div>
           </>
          )}
        </div>

        {/* Filtro de Subcategorías */}
        <div className="filter-dropdown">
          <button
            onClick={() => setMostrarMenuSubcategorias(!mostrarMenuSubcategorias)}
            className={`filter-button subcategorias ${subcategoriasSeleccionadas.length > 0 ? 'active' : ''}`}
          >
            📋 Subcategorías
            {subcategoriasSeleccionadas.length > 0 && (
              <span className="filter-badge">
                {subcategoriasSeleccionadas.length}
              </span>
            )}
          </button>

          {mostrarMenuSubcategorias && (
            <>
              <div onClick={() => setMostrarMenuSubcategorias(false)} className="dropdown-overlay" />
              <div className="dropdown-panel subcategorias">
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

                <div className="dropdown-actions">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setSubcategoriasSeleccionadas([]);
                    }}
                    className="btn-clear"
                  >
                    Limpiar
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setMostrarMenuSubcategorias(false);
                    }}
                    className="btn-apply"
                  >
                    Aplicar
                  </button>
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
              </div>
            </>
          )}
        </div>

        {/* Filtros de Auditoría */}
        <div className="filter-dropdown">
          <button
            onClick={() => setMostrarFiltrosAuditoria(!mostrarFiltrosAuditoria)}
            className={`filter-button auditoria ${(filtrosAuditoria.usuarios.length > 0 || filtrosAuditoria.tipos_accion.length > 0 || filtrosAuditoria.fecha_desde || filtrosAuditoria.fecha_hasta) ? 'active' : ''}`}
          >
            🔍 Filtros de Auditoría
            {(filtrosAuditoria.usuarios.length > 0 || filtrosAuditoria.tipos_accion.length > 0) && (
              <span className="filter-badge">
                {filtrosAuditoria.usuarios.length + filtrosAuditoria.tipos_accion.length}
              </span>
            )}
          </button>

          {mostrarFiltrosAuditoria && (
            <>
              <div onClick={() => setMostrarFiltrosAuditoria(false)} className="dropdown-overlay" />
              <div className="dropdown-panel auditoria">
                <div className="dropdown-actions">
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
                    className="btn-clear"
                  >
                    Limpiar Todo
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setMostrarFiltrosAuditoria(false);
                    }}
                    className="btn-apply"
                  >
                    Aplicar
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
              </div>
            </>
          )}
        </div>

        {/* Botón de filtros avanzados */}
        <button
          onClick={() => setMostrarFiltrosAvanzados(!mostrarFiltrosAvanzados)}
          className={`filter-button advanced ${(filtroRebate || filtroOferta || filtroWebTransf || filtroMarkupClasica || filtroMarkupRebate || filtroMarkupOferta || filtroMarkupWebTransf || filtroOutOfCards) ? 'active' : ''}`}
        >
          �� Filtros Avanzados
          {(filtroRebate || filtroOferta || filtroWebTransf || filtroMarkupClasica || filtroMarkupRebate || filtroMarkupOferta || filtroMarkupWebTransf || filtroOutOfCards) && (
            <span className="filter-badge">
              {[filtroRebate, filtroOferta, filtroWebTransf, filtroMarkupClasica, filtroMarkupRebate, filtroMarkupOferta, filtroMarkupWebTransf, filtroOutOfCards].filter(Boolean).length}
            </span>
          )}
        </button>
        </div>

        {/* Botones de Acción */}
        <div className="action-buttons-group">
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
                {productosOrdenados.map((p) => (
                  <tr key={p.item_id}>
                    <td>{p.codigo}</td>
                    <td>{p.descripcion}</td>
                    <td>{p.marca}</td>
                    <td>{p.stock}</td>
                    <td>{p.moneda_costo} ${p.costo?.toFixed(2)}</td>
                    <td>
                      {editandoPrecio === p.item_id ? (
                        <div className="inline-edit">
                          <input
                            type="number"
                            value={precioTemp}
                            onChange={(e) => setPrecioTemp(e.target.value)}
                            onKeyPress={(e) => e.key === 'Enter' && guardarPrecio(p.item_id)}
                            autoFocus
                          />
                          <button onClick={() => guardarPrecio(p.item_id)}>✓</button>
                          <button onClick={() => setEditandoPrecio(null)}>✗</button>
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
                    <td>
                      {editandoRebate === p.item_id ? (
                        <div className="rebate-edit">
                          <label className="rebate-checkbox">
                            <input
                              type="checkbox"
                              checked={rebateTemp.participa}
                              onChange={(e) => setRebateTemp({ ...rebateTemp, participa: e.target.checked })}
                            />
                            <span>Rebate</span>
                          </label>
                          {rebateTemp.participa && (
                            <input
                              type="number"
                              step="0.1"
                              value={rebateTemp.porcentaje}
                              onChange={(e) => setRebateTemp({ ...rebateTemp, porcentaje: parseFloat(e.target.value) })}
                              placeholder="%"
                            />
                          )}
                          <div className="inline-edit">
                            <button onClick={() => guardarRebate(p.item_id)}>✓</button>
                            <button onClick={() => setEditandoRebate(null)}>✗</button>
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
                    <td>
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
                    <td>
                      {editandoWebTransf === p.item_id ? (
                        <div className="web-transf-edit">
                          <label className="web-transf-checkbox">
                            <input
                              type="checkbox"
                              checked={webTransfTemp.participa}
                              onChange={(e) => setWebTransfTemp({...webTransfTemp, participa: e.target.checked})}
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
                            placeholder="%"
                            style={{ width: '60px', padding: '4px', borderRadius: '4px', border: '1px solid #d1d5db' }}
                          />
                          <div className="inline-edit">
                            <button onClick={() => guardarWebTransf(p.item_id)}>✓</button>
                            <button onClick={() => setEditandoWebTransf(null)}>✗</button>
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
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {auditoriaVisible && (
              <div className="modal-overlay">
                <div className="modal-content">
                  <div className="modal-header">
                    <h2>📋 Historial de Cambios de Precio</h2>
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
                          <th>Precio Anterior</th>
                          <th>Precio Nuevo</th>
                          <th>Cambio</th>
                        </tr>
                      </thead>
                      <tbody className="table-body">
                        {auditoriaData.map(item => {
                          const cambio = item.precio_nuevo - item.precio_anterior;
                          const porcentaje = ((cambio / item.precio_anterior) * 100).toFixed(2);

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
                              <td>${item.precio_anterior.toFixed(2)}</td>
                              <td>${item.precio_nuevo.toFixed(2)}</td>
                              <td>
                                <span className={cambio >= 0 ? 'text-success' : 'text-danger'} style={{ fontWeight: 'bold' }}>
                                  {cambio >= 0 ? '+' : ''}{cambio.toFixed(2)} ({porcentaje}%)
                                </span>
                              </td>
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
            subcategorias: subcategoriasSeleccionadas
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
            subcategorias: subcategoriasSeleccionadas
          }}
        />
      )}
    </div>
      );
    }
