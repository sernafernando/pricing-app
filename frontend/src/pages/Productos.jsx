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

  const user = useAuthStore((state) => state.user);
  const puedeEditar = ['SUPERADMIN', 'ADMIN', 'GERENTE', 'PRICING'].includes(user?.rol);

  const debouncedSearch = useDebounce(searchInput, 500);

  const API_URL = 'https://pricing.gaussonline.com.ar/api';
  
  useEffect(() => {
    cargarStats();
  }, []);

  useEffect(() => {
    cargarProductos();
  }, [page, debouncedSearch, filtroStock, filtroPrecio, pageSize, marcasSeleccionadas, subcategoriasSeleccionadas, ordenColumnas]);

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
  }, []);

  useEffect(() => {
    cargarSubcategorias();
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
          valorA = a.precio_lista_ml ?? -Infinity;
          valorB = b.precio_lista_ml ?? -Infinity;
          comparacion = direccion === 'asc' ? valorA - valorB : valorB - valorA;
          break;
        
        case 'precio_rebate':
          valorA = a.precio_rebate ?? -Infinity;
          valorB = b.precio_rebate ?? -Infinity;
          comparacion = direccion === 'asc' ? valorA - valorB : valorB - valorA;
          break;
        
        case 'mejor_oferta':
          valorA = a.mejor_oferta_precio ?? -Infinity;
          valorB = b.mejor_oferta_precio ?? -Infinity;
          comparacion = direccion === 'asc' ? valorA - valorB : valorB - valorA;
          break;
        
        case 'web_transf':
          valorA = a.precio_web_transferencia ?? -Infinity;
          valorB = b.precio_web_transferencia ?? -Infinity;
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
      
      const response = await axios.patch(
        `https://pricing.gaussonline.com.ar/api/productos/${itemId}/web-transferencia`,
        null,
        {
          params: {
            participa: webTransfTemp.participa,
            porcentaje_markup: webTransfTemp.porcentaje
          },
          headers: { Authorization: `Bearer ${token}` }
        }
      );
      
      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? {
              ...p,
              participa_web_transferencia: webTransfTemp.participa,
              porcentaje_markup_web: webTransfTemp.porcentaje,
              precio_web_transferencia: response.data.precio_web_transferencia,
              markup_web_real: response.data.markup_web_real  // ← AGREGAR
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
      porcentaje: producto.porcentaje_rebate || 3.8
    });
  };

  return (
    <div className={styles.container}>
      <div className={styles.statsGrid}>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Total Productos</div>
          <div className={styles.statValue}>{stats?.total_productos || 0}</div>
        </div>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Con Stock</div>
          <div className={`${styles.statValue} ${styles.green}`}>{stats?.con_stock || 0}</div>
        </div>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Sin Precio</div>
          <div className={`${styles.statValue} ${styles.red}`}>{stats?.sin_precio || 0}</div>
        </div>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Con Precio</div>
          <div className={`${styles.statValue} ${styles.blue}`}>{stats?.con_precio || 0}</div>
        </div>
      </div>

	  {/* Búsqueda */}
	  <div className={styles.searchBar} style={{ marginBottom: '16px' }}>
	    <input
	      type="text"
	      placeholder="Buscar por código, descripción o marca..."
	      value={searchInput}
	      onChange={handleSearchChange}
	      className={styles.searchInput}
	    />
	  </div>
	  
	  {/* Filtros */}
	  <div style={{ display: 'flex', gap: '12px', marginBottom: '24px', flexWrap: 'wrap' }}>
	    <select
	      value={filtroStock}
	      onChange={(e) => { setFiltroStock(e.target.value); setPage(1); }}
	      style={{ padding: '8px 16px', borderRadius: '6px', border: '1px solid #d1d5db', flex: '1', minWidth: '150px' }}
	    >
	      <option value="todos">📦 Todo el stock</option>
	      <option value="con_stock">✅ Con stock</option>
	      <option value="sin_stock">❌ Sin stock</option>
	    </select>
	  
	    <select
	      value={filtroPrecio}
	      onChange={(e) => { setFiltroPrecio(e.target.value); setPage(1); }}
	      style={{ padding: '8px 16px', borderRadius: '6px', border: '1px solid #d1d5db', flex: '1', minWidth: '150px' }}
	    >
	      <option value="todos">💰 Todos los precios</option>
	      <option value="con_precio">✅ Con precio</option>
	      <option value="sin_precio">❌ Sin precio</option>
	    </select>

		{/* Filtro de Marcas */}
		<div style={{ position: 'relative' }}>
		  <button
		    onClick={() => setMostrarMenuMarcas(!mostrarMenuMarcas)}
		    style={{
		      padding: '10px 16px',
		      borderRadius: '6px',
		      border: '1px solid #d1d5db',
		      background: marcasSeleccionadas.length > 0 ? '#3b82f6' : 'white',
		      color: marcasSeleccionadas.length > 0 ? 'white' : '#374151',
		      cursor: 'pointer',
		      display: 'flex',
		      alignItems: 'center',
		      gap: '8px',
		      fontWeight: '500'
		    }}
		  >
		    🏷️ Marcas {marcasSeleccionadas.length > 0 && `(${marcasSeleccionadas.length})`}
		  </button>
		  
		  {mostrarMenuMarcas && (
		    <div style={{
		      position: 'absolute',
		      top: '100%',
		      left: 0,
		      marginTop: '4px',
		      background: 'white',
		      border: '1px solid #d1d5db',
		      borderRadius: '8px',
		      boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
		      zIndex: 1000,
		      width: '300px',
		      display: 'flex',
		      flexDirection: 'column',
		      maxHeight: '400px'
		    }}>
		      {/* Sección fija arriba */}
		      <div style={{ borderBottom: '1px solid #e5e7eb' }}>
		        <div style={{ padding: '12px' }}>
		          <div style={{ position: 'relative' }}>
		            <input
		              type="text"
		              placeholder="Buscar marca..."
		              value={busquedaMarca}
		              onChange={(e) => setBusquedaMarca(e.target.value)}
		              style={{
		                width: '100%',
		                padding: '8px',
		                paddingRight: '32px',  // ← espacio para la X
		                border: '1px solid #d1d5db',
		                borderRadius: '4px',
		                fontSize: '14px',
		                boxSizing: 'border-box'
		              }}
		            />
		            {busquedaMarca && (
		              <button
		                onClick={() => setBusquedaMarca('')}
		                style={{
		                  position: 'absolute',
		                  right: '8px',
		                  top: '50%',
		                  transform: 'translateY(-50%)',
		                  background: 'transparent',
		                  border: 'none',
		                  cursor: 'pointer',
		                  color: '#9ca3af',
		                  fontSize: '16px',
		                  padding: '4px',
		                  lineHeight: 1
		                }}
		              >
		                ✕
		              </button>
		            )}
		          </div>
		        </div>
		        
		        {marcasSeleccionadas.length > 0 && (
		          <div style={{ padding: '0 12px 12px 12px' }}>
		            <button
		              onClick={() => {
		                setMarcasSeleccionadas([]);
		                setPage(1);
		              }}
		              style={{
		                width: '100%',
		                padding: '8px',
		                background: '#ef4444',
		                color: 'white',
		                border: 'none',
		                borderRadius: '4px',
		                cursor: 'pointer',
		                fontSize: '13px'
		              }}
		            >
		              Limpiar filtros ({marcasSeleccionadas.length})
		            </button>
		          </div>
		        )}
		      </div>
		      
		      {/* Lista con scroll */}
		      <div style={{ 
		        padding: '8px', 
		        overflowY: 'auto',
		        flex: 1
		      }}>
		        {marcasFiltradas.map(marca => (
		          <label
		            key={marca}
		            style={{
		              display: 'flex',
		              alignItems: 'center',
		              padding: '8px',
		              cursor: 'pointer',
		              borderRadius: '4px',
		              background: marcasSeleccionadas.includes(marca) ? '#eff6ff' : 'transparent'
		            }}
		            onMouseEnter={(e) => e.currentTarget.style.background = '#f3f4f6'}
		            onMouseLeave={(e) => e.currentTarget.style.background = marcasSeleccionadas.includes(marca) ? '#eff6ff' : 'transparent'}
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
		              style={{ marginRight: '8px' }}
		            />
		            <span style={{ fontSize: '14px' }}>{marca}</span>
		          </label>
		        ))}
		      </div>

		      
		    </div>
		  )}
		</div>

		{/* Filtro de Subcategorías */}
		<div style={{ position: 'relative' }}>
		  <button
		    onClick={() => setMostrarMenuSubcategorias(!mostrarMenuSubcategorias)}
		    style={{
		      padding: '10px 16px',
		      borderRadius: '6px',
		      border: '1px solid #d1d5db',
		      background: subcategoriasSeleccionadas.length > 0 ? '#10b981' : 'white',
		      color: subcategoriasSeleccionadas.length > 0 ? 'white' : '#374151',
		      cursor: 'pointer',
		      fontSize: '14px',
		      fontWeight: '500',
		      display: 'flex',
		      alignItems: 'center',
		      gap: '8px'
		    }}
		  >
		    📋 Subcategorías
		    {subcategoriasSeleccionadas.length > 0 && (
		      <span style={{
		        background: 'rgba(255,255,255,0.3)',
		        padding: '2px 8px',
		        borderRadius: '12px',
		        fontSize: '12px'
		      }}>
		        {subcategoriasSeleccionadas.length}
		      </span>
		    )}
		  </button>
		
		  {mostrarMenuSubcategorias && (
		    <>
		      <div
		        onClick={() => setMostrarMenuSubcategorias(false)}
		        style={{
		          position: 'fixed',
		          top: 0,
		          left: 0,
		          right: 0,
		          bottom: 0,
		          zIndex: 999
		        }}
		      />
		      <div style={{
		        position: 'absolute',
		        top: '100%',
		        left: 0,
		        marginTop: '4px',
		        background: 'white',
		        border: '1px solid #d1d5db',
		        borderRadius: '8px',
		        boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
		        zIndex: 1000,
		        minWidth: '350px',
		        maxWidth: '450px',
		        maxHeight: '500px',
		        display: 'flex',
		        flexDirection: 'column'
		      }}>
		        {/* Buscador fijo */}
		        <div style={{ padding: '12px', borderBottom: '1px solid #e5e7eb', position: 'relative' }}>
		          <input
		            type="text"
		            placeholder="Buscar subcategoría..."
		            value={busquedaSubcategoria}
		            onChange={(e) => setBusquedaSubcategoria(e.target.value)}
		            onClick={(e) => e.stopPropagation()}
		            style={{
		              width: '100%',
		              padding: '8px 32px 8px 12px',
		              border: '1px solid #d1d5db',
		              borderRadius: '6px',
		              fontSize: '14px',
		              outline: 'none',
		              boxSizing: 'border-box'
		            }}
		          />
		          {busquedaSubcategoria && (
		            <button
		              onClick={(e) => {
		                e.stopPropagation();
		                setBusquedaSubcategoria('');
		              }}
		              style={{
		                position: 'absolute',
		                right: '20px',
		                top: '50%',
		                transform: 'translateY(-50%)',
		                background: 'none',
		                border: 'none',
		                cursor: 'pointer',
		                fontSize: '16px',
		                color: '#9ca3af',
		                padding: '4px'
		              }}
		            >
		              ✕
		            </button>
		          )}
		        </div>
		
		        {/* Botones de acción */}
		        <div style={{
		          padding: '8px 12px',
		          borderBottom: '1px solid #e5e7eb',
		          display: 'flex',
		          gap: '8px'
		        }}>
		          <button
		            onClick={(e) => {
		              e.stopPropagation();
		              setSubcategoriasSeleccionadas([]);
		            }}
		            style={{
		              padding: '4px 12px',
		              background: '#ef4444',
		              color: 'white',
		              border: 'none',
		              borderRadius: '4px',
		              fontSize: '12px',
		              cursor: 'pointer'
		            }}
		          >
		            Limpiar
		          </button>
		          <button
		            onClick={(e) => {
		              e.stopPropagation();
		              setMostrarMenuSubcategorias(false);
		            }}
		            style={{
		              padding: '4px 12px',
		              background: '#3b82f6',
		              color: 'white',
		              border: 'none',
		              borderRadius: '4px',
		              fontSize: '12px',
		              cursor: 'pointer'
		            }}
		          >
		            Aplicar
		          </button>
		        </div>
		
		        {/* Lista jerárquica de categorías y subcategorías */}
		        {/* Lista jerárquica de categorías y subcategorías */}
		        <div style={{
		          overflowY: 'auto',
		          maxHeight: '400px',
		          padding: '8px'
		        }}>
		          {(subcategorias || [])
		            .filter(cat => 
		              !busquedaSubcategoria || 
		              cat.nombre.toLowerCase().includes(busquedaSubcategoria.toLowerCase()) ||
		              cat.subcategorias.some(sub => sub.nombre.toLowerCase().includes(busquedaSubcategoria.toLowerCase()))
		            )
		            .map(categoria => {
		              // Si la búsqueda coincide con la categoría, mostrar TODAS las subcategorías
		              const categoriaCoincide = !busquedaSubcategoria || 
		                categoria.nombre.toLowerCase().includes(busquedaSubcategoria.toLowerCase());
		              
		              const subcatsDeCategoria = categoriaCoincide 
		                ? categoria.subcategorias // Mostrar todas si la categoría coincide
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
		                <div key={categoria.nombre} style={{ marginBottom: '12px' }}>
		                  {/* Checkbox de categoría */}
		                  <label
		                    onClick={(e) => e.stopPropagation()}
		                    style={{
		                      display: 'flex',
		                      alignItems: 'center',
		                      fontSize: '13px',
		                      fontWeight: '600',
		                      color: '#374151',
		                      padding: '8px 12px',
		                      background: '#f9fafb',
		                      borderRadius: '4px',
		                      marginBottom: '4px',
		                      cursor: 'pointer'
		                    }}
		                  >
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
		                          // Deseleccionar todas de esta categoría
		                          setSubcategoriasSeleccionadas(prev =>
		                            prev.filter(id => !subcatIds.includes(id))
		                          );
		                        } else {
		                          // Seleccionar todas de esta categoría
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
		                      style={{ marginRight: '8px', cursor: 'pointer' }}
		                    />
		                    {categoria.nombre}
		                    {algunaSeleccionada && (
		                      <span style={{
		                        marginLeft: 'auto',
		                        fontSize: '11px',
		                        color: '#10b981',
		                        background: '#d1fae5',
		                        padding: '2px 8px',
		                        borderRadius: '12px'
		                      }}>
		                        {subcatsDeCategoria.filter(sub => 
		                          subcategoriasSeleccionadas.includes(sub.id.toString())
		                        ).length}/{subcatsDeCategoria.length}
		                      </span>
		                    )}
		                  </label>
		                  
		                  {/* Subcategorías */}
		                  {subcatsDeCategoria.map(subcat => (
		                    <label
		                      key={subcat.id}
		                      onClick={(e) => e.stopPropagation()}
		                      style={{
		                        display: 'flex',
		                        alignItems: 'center',
		                        padding: '6px 12px 6px 36px',
		                        cursor: 'pointer',
		                        borderRadius: '4px',
		                        fontSize: '13px',
		                        transition: 'background 0.2s',
		                        background: subcategoriasSeleccionadas.includes(subcat.id.toString()) ? '#eff6ff' : 'transparent'
		                      }}
		                      onMouseEnter={(e) => e.currentTarget.style.background = '#f3f4f6'}
		                      onMouseLeave={(e) => e.currentTarget.style.background = subcategoriasSeleccionadas.includes(subcat.id.toString()) ? '#eff6ff' : 'transparent'}
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
		                        style={{ marginRight: '8px', cursor: 'pointer' }}
		                      />
		                      <div style={{ flex: 1 }}>
		                        {subcat.nombre}
		                        {subcat.grupo_id && (
		                          <span style={{
		                            marginLeft: '8px',
		                            fontSize: '10px',
		                            color: '#6b7280',
		                            background: '#f3f4f6',
		                            padding: '2px 6px',
		                            borderRadius: '4px'
		                          }}>
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

	    <button
	      onClick={() => setMostrarExportModal(true)}
	      style={{
	        padding: '10px 16px',
	        background: '#10b981',
	        color: 'white',
	        border: 'none',
	        borderRadius: '6px',
	        cursor: 'pointer',
	        display: 'flex',
	        alignItems: 'center',
	        gap: '8px',
	        fontWeight: '600'
	      }}
	    >
	      <img src={xlsIcon} alt="Excel" style={{ width: '20px', height: '20px' }} />
	      Exportar
	    </button>

	    <button
	      onClick={() => setMostrarCalcularWebModal(true)}
	      style={{
	        padding: '10px 16px',
	        background: '#3b82f6',
	        color: 'white',
	        border: 'none',
	        borderRadius: '6px',
	        cursor: 'pointer',
	        display: 'flex',
	        alignItems: 'center',
	        gap: '8px',
	        fontWeight: '600'
	      }}
	    >
	      🧮 Calcular Web Transf.
	    </button>
	  
	  </div>
     
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <div style={{ color: '#6b7280' }}>
          Mostrando {productos.length} de {totalProductos.toLocaleString('es-AR')} productos
          {debouncedSearch && ` (filtrado por "${debouncedSearch}")`}
        </div>
        
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span style={{ color: '#6b7280', fontSize: '14px' }}>Mostrar:</span>
          <select
            value={pageSize}
            onChange={(e) => { 
              setPageSize(Number(e.target.value)); 
              setPage(1); 
            }}
            style={{ padding: '6px 10px', borderRadius: '6px', border: '1px solid #d1d5db' }}
          >
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={200}>200</option>
            <option value={500}>500</option>
            <option value={9999}>Todos</option>
          </select>
        </div>
      </div>

      <div className={styles.tableContainer}>
        {loading ? (
          <div className={styles.loading}>Cargando...</div>
        ) : (
          <>
            <table className={styles.table}>
              <thead className={styles.tableHead}>
                <tr>
                  <th onClick={(e) => handleOrdenar('codigo', e)} style={{ cursor: 'pointer', userSelect: 'none' }}>
                    Código {getIconoOrden('codigo')} {getNumeroOrden('codigo') && <span style={{ fontSize: '10px', marginLeft: '4px' }}>{getNumeroOrden('codigo')}</span>}
                  </th>
                  <th onClick={(e) => handleOrdenar('descripcion', e)} style={{ cursor: 'pointer', userSelect: 'none' }}>
                    Descripción {getIconoOrden('descripcion')} {getNumeroOrden('descripcion') && <span style={{ fontSize: '10px', marginLeft: '4px' }}>{getNumeroOrden('descripcion')}</span>}
                  </th>
                  <th onClick={(e) => handleOrdenar('marca', e)} style={{ cursor: 'pointer', userSelect: 'none' }}>
                    Marca {getIconoOrden('marca')} {getNumeroOrden('marca') && <span style={{ fontSize: '10px', marginLeft: '4px' }}>{getNumeroOrden('marca')}</span>}
                  </th>
                  <th onClick={(e) => handleOrdenar('stock', e)} style={{ cursor: 'pointer', userSelect: 'none' }}>
                    Stock {getIconoOrden('stock')} {getNumeroOrden('stock') && <span style={{ fontSize: '10px', marginLeft: '4px' }}>{getNumeroOrden('stock')}</span>}
                  </th>
                  <th onClick={(e) => handleOrdenar('costo', e)} style={{ cursor: 'pointer', userSelect: 'none' }}>
                    Costo {getIconoOrden('costo')} {getNumeroOrden('costo') && <span style={{ fontSize: '10px', marginLeft: '4px' }}>{getNumeroOrden('costo')}</span>}
                  </th>
                  <th onClick={(e) => handleOrdenar('precio_clasica', e)} style={{ cursor: 'pointer', userSelect: 'none' }}>
                    Precio Clásica {getIconoOrden('precio_clasica')} {getNumeroOrden('precio_clasica') && <span style={{ fontSize: '10px', marginLeft: '4px' }}>{getNumeroOrden('precio_clasica')}</span>}
                  </th>
                  <th onClick={(e) => handleOrdenar('precio_rebate', e)} style={{ cursor: 'pointer', userSelect: 'none' }}>
                    Precio Rebate {getIconoOrden('precio_rebate')} {getNumeroOrden('precio_rebate') && <span style={{ fontSize: '10px', marginLeft: '4px' }}>{getNumeroOrden('precio_rebate')}</span>}
                  </th>
                  <th onClick={(e) => handleOrdenar('mejor_oferta', e)} style={{ cursor: 'pointer', userSelect: 'none' }}>
                    Mejor Oferta {getIconoOrden('mejor_oferta')} {getNumeroOrden('mejor_oferta') && <span style={{ fontSize: '10px', marginLeft: '4px' }}>{getNumeroOrden('mejor_oferta')}</span>}
                  </th>
                  <th onClick={(e) => handleOrdenar('web_transf', e)} style={{ cursor: 'pointer', userSelect: 'none' }}>
                    Web Transf. {getIconoOrden('web_transf')} {getNumeroOrden('web_transf') && <span style={{ fontSize: '10px', marginLeft: '4px' }}>{getNumeroOrden('web_transf')}</span>}
                  </th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody className={styles.tableBody}>
                {productosOrdenados.map((p) => (
                  <tr key={p.item_id}>
                    <td>{p.codigo}</td>
                    <td>{p.descripcion}</td>
                    <td>{p.marca}</td>
                    <td>{p.stock}</td>
                    <td>{p.moneda_costo} ${p.costo?.toFixed(2)}</td>
                    <td>
                      {editandoPrecio === p.item_id ? (
                        <div style={{ display: 'flex', gap: '4px' }}>
                          <input
                            type="number"
                            value={precioTemp}
                            onChange={(e) => setPrecioTemp(e.target.value)}
                            onKeyPress={(e) => e.key === 'Enter' && guardarPrecio(p.item_id)}
                            autoFocus
                            style={{ width: '100px', padding: '4px' }}
                          />
                          <button onClick={() => guardarPrecio(p.item_id)} style={{ padding: '4px 8px' }}>✓</button>
                          <button onClick={() => setEditandoPrecio(null)} style={{ padding: '4px 8px' }}>✗</button>
                        </div>
                      ) : (
                        <div style={{ cursor: puedeEditar ? 'pointer' : 'default' }} onClick={() => puedeEditar && iniciarEdicion(p)}>
                          <div style={{borderBottom: puedeEditar ? '1px dashed #ccc' : 'none', display: 'inline-block' }}>
                            {p.precio_lista_ml ? `$${p.precio_lista_ml.toLocaleString('es-AR')}` : 'Sin precio'}
                          </div>
                          {p.markup !== null && p.markup !== undefined && (
                            <div style={{
                              fontSize: '10px',
                              color: getMarkupColor(p.markup),
                              marginTop: '2px',
                              fontWeight: '600'
                            }}>
                              {p.markup}%
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                    {/* Columna Precio Rebate */}
                    <td>
                      {editandoRebate === p.item_id ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', padding: '4px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <input
                              type="checkbox"
                              checked={rebateTemp.participa}
                              onChange={(e) => setRebateTemp({ ...rebateTemp, participa: e.target.checked })}
                              style={{ width: '16px', height: '16px' }}
                            />
                            <span style={{ fontSize: '12px' }}>Rebate</span>
                          </div>
                          {rebateTemp.participa && (
                            <input
                              type="number"
                              step="0.1"
                              value={rebateTemp.porcentaje}
                              onChange={(e) => setRebateTemp({ ...rebateTemp, porcentaje: parseFloat(e.target.value) })}
                              style={{ width: '60px', padding: '4px', fontSize: '12px' }}
                              placeholder="%"
                            />
                          )}
                          <div style={{ display: 'flex', gap: '4px' }}>
                            <button onClick={() => guardarRebate(p.item_id)} style={{ padding: '4px 8px', fontSize: '12px' }}>✓</button>
                            <button onClick={() => setEditandoRebate(null)} style={{ padding: '4px 8px', fontSize: '12px' }}>✗</button>
                          </div>
                        </div>
                      ) : (
                        <div
                          style={{ cursor: 'pointer', padding: '4px' }}
                          onClick={() => iniciarEdicionRebate(p)}
                        >
                          {p.participa_rebate && p.precio_rebate ? (
                            <div>
                              <div style={{
                                fontSize: '14px',
                                fontWeight: '600',
                                color: '#8b5cf6',
                                borderBottom: '1px dashed #ccc'
                              }}>
                                ${p.precio_rebate.toFixed(2).toLocaleString('es-AR')}
                              </div>
                              <div style={{
                                fontSize: '11px',
                                color: '#6b7280'
                              }}>
                                {p.porcentaje_rebate}% rebate
                              </div>
                              {/* AGREGAR ESTE CHECKBOX */}
                              <label 
                                style={{ 
                                  display: 'flex', 
                                  alignItems: 'center', 
                                  marginTop: '4px',
                                  fontSize: '11px',
                                  cursor: 'pointer'
                                }}
                                onClick={(e) => e.stopPropagation()} // Evitar que abra la edición
                              >
                                <input
                                  type="checkbox"
                                  checked={p.out_of_cards || false}
                                  onChange={async (e) => {
                                    e.stopPropagation();
                                    try {
                                      const response = await axios.patch(
                                        `${API_URL}/productos/${p.item_id}/out-of-cards`,
                                        { out_of_cards: e.target.checked },
                                        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
                                      );
                                      console.log('Respuesta:', response.data);
                                      await cargarProductos(); // Esperar a que termine
                                    } catch (error) {
                                      console.error('Error completo:', error);
                                      alert(`Error al actualizar: ${error.response?.data?.detail || error.message}`);
                                    }
                                  }}
                                  style={{ marginRight: '4px' }}
                                />
                                Out of Cards
                              </label>
                            </div>
                          ) : (
                            <div style={{ borderBottom: '1px dashed #ccc', display: 'inline-block', fontSize: '12px', color: '#9ca3af' }}>
                              Sin rebate
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                   	<td>
                   	  {p.mejor_oferta_precio ? (
                   	    <div style={{ fontSize: '12px' }}>
                   	      <div style={{ fontWeight: '600', color: '#059669' }}>
                   	        ${p.mejor_oferta_precio.toLocaleString('es-AR')}
                   	      </div>
                   	      {p.mejor_oferta_porcentaje_rebate && (
                   	        <div style={{ fontSize: '11px', color: '#7c3aed', fontWeight: '600' }}>
                   	          {p.mejor_oferta_porcentaje_rebate.toFixed(2)}%
                   	        </div>
                   	      )}
                   	      {p.mejor_oferta_monto_rebate && (
                   	        <div style={{ fontSize: '11px', color: '#7c3aed' }}>
                   	          Rebate: ${p.mejor_oferta_monto_rebate.toLocaleString('es-AR')}
                   	        </div>
                   	      )}
                   	      {p.mejor_oferta_fecha_hasta && (
                   	        <div style={{ fontSize: '10px', color: '#6b7280' }}>
                   	          Hasta {new Date(p.mejor_oferta_fecha_hasta).toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit' })}
                   	        </div>
                   	      )}
                   	      {p.mejor_oferta_pvp_seller && (
                   	        <div style={{ fontSize: '11px', color: '#6b7280' }}>
                   	          PVP: ${p.mejor_oferta_pvp_seller.toLocaleString('es-AR')}
                   	        </div>
                   	      )}
                   	      {p.mejor_oferta_markup !== null && (
                   	        <div style={{
                   	          fontSize: '11px',
                   	          fontWeight: '600',
                   	          color: getMarkupColor(p.mejor_oferta_markup * 100),
                   	          marginTop: '2px'
                   	        }}>
                   	          Markup: {(p.mejor_oferta_markup * 100).toFixed(2)}%
                   	        </div>
                   	      )}
                   	    </div>
                   	  ) : (
                   	    <span style={{ color: '#9ca3af', fontSize: '12px' }}>-</span>
                   	  )}
                   	</td>

                   	<td style={{ padding: '8px' }}>
                   	  {editandoWebTransf === p.item_id ? (
                   	    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                   	      <label style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px' }}>
                   	        <input
                   	          type="checkbox"
                   	          checked={webTransfTemp.participa}
                   	          onChange={(e) => setWebTransfTemp({...webTransfTemp, participa: e.target.checked})}
                   	        />
                   	        Participa
                   	      </label>
                   	      <input
                   	        type="number"
                   	        step="0.1"
                   	        value={webTransfTemp.porcentaje}
                   	        onChange={(e) => setWebTransfTemp({...webTransfTemp, porcentaje: parseFloat(e.target.value)})}
                   	        style={{ padding: '4px', width: '60px', borderRadius: '4px', border: '1px solid #d1d5db' }}
                   	        placeholder="%"
                   	      />
                   	      <div style={{ display: 'flex', gap: '4px' }}>
                   	        <button
                   	          onClick={() => guardarWebTransf(p.item_id)}
                   	          style={{ padding: '4px 8px', background: '#10b981', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
                   	        >
                   	          ✓
                   	        </button>
                   	        <button
                   	          onClick={() => setEditandoWebTransf(null)}
                   	          style={{ padding: '4px 8px', background: '#ef4444', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}
                   	        >
                   	          ✗
                   	        </button>
                   	      </div>
                   	    </div>
                   	  ) : (
                   	    <div onClick={() => iniciarEdicionWebTransf(p)} style={{ cursor: 'pointer' }}>
                   	      {p.participa_web_transferencia ? (
                   	        <div>
                   	          <div style={{ fontSize: '12px', color: getMarkupColor(p.markup_web_real), fontWeight: '600' }}>
                   	            ✓ {p.markup_web_real ? `${p.markup_web_real.toFixed(2)}%` : '-'}
                   	          </div>
                   	          <div style={{ fontSize: '10px', color: '#6b7280' }}>
                   	            (+{p.porcentaje_markup_web}%)
                   	          </div>
                   	          {p.precio_web_transferencia && (
                   	            <div style={{ fontSize: '13px', fontWeight: '600', marginTop: '2px' }}>
                   	              ${p.precio_web_transferencia.toLocaleString('es-AR')}
                   	            </div>
                   	          )}
                   	        </div>
                   	      ) : (
                   	        <span style={{ fontSize: '11px', color: '#9ca3af' }}>-</span>
                   	      )}
                   	    </div>
                   	  )}
                   	</td>
                   	
                    {/* Cambiar de botón a iconos */}
                    <td style={{ padding: '8px', textAlign: 'center' }}>
                      <div style={{ display: 'flex', gap: '8px', justifyContent: 'center' }}>
                        {/* Icono de detalle */}
                        {puedeEditar && (
                        <button
                          onClick={() => setProductoSeleccionado(p)}
                          style={{
                            padding: '6px 8px',
                            background: '#3b82f6',
                            color: 'white',
                            border: 'none',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            fontSize: '16px'
                          }}
                          title="Ver detalle"
                        >
                          🔍
                        </button>
                        )}
                        {/* Icono de auditoría */}
                        <button
                          onClick={() => verAuditoria(p.item_id)}
                          style={{
                            padding: '6px 8px',
                            background: '#8b5cf6',
                            color: 'white',
                            border: 'none',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            fontSize: '16px'
                          }}
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

            {/* Modal de Auditoría */}
            {auditoriaVisible && (
              <div style={{
                position: 'fixed',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                background: 'rgba(0,0,0,0.5)',
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                zIndex: 1000
              }}>
                <div style={{
                  background: 'white',
                  borderRadius: '12px',
                  padding: '24px',
                  maxWidth: '800px',
                  width: '90%',
                  maxHeight: '80vh',
                  overflow: 'auto'
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '20px' }}>
                    <h2>📋 Historial de Cambios de Precio</h2>
                    <button
                      onClick={() => setAuditoriaVisible(false)}
                      style={{
                        padding: '8px 16px',
                        background: '#ef4444',
                        color: 'white',
                        border: 'none',
                        borderRadius: '6px',
                        cursor: 'pointer'
                      }}
                    >
                      Cerrar
                    </button>
                  </div>
            
                  {auditoriaData.length === 0 ? (
                    <p style={{ textAlign: 'center', color: '#666' }}>No hay cambios registrados</p>
                  ) : (
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <thead>
                        <tr style={{ borderBottom: '2px solid #e5e7eb', textAlign: 'left' }}>
                          <th style={{ padding: '12px' }}>Fecha</th>
                          <th style={{ padding: '12px' }}>Usuario</th>
                          <th style={{ padding: '12px' }}>Precio Anterior</th>
                          <th style={{ padding: '12px' }}>Precio Nuevo</th>
                          <th style={{ padding: '12px' }}>Cambio</th>
                        </tr>
                      </thead>
                      <tbody>
                        {auditoriaData.map(item => {
                          const cambio = item.precio_nuevo - item.precio_anterior;
                          const porcentaje = ((cambio / item.precio_anterior) * 100).toFixed(2);
                          
                          return (
                            <tr key={item.id} style={{ borderBottom: '1px solid #e5e7eb' }}>
                             <td style={{ padding: '12px' }}>
                                {formatearFechaGMT3(item.fecha_cambio)}
                              </td>
                              <td style={{ padding: '12px' }}>
                                <div>
                                  <strong>{item.usuario_nombre}</strong>
                                  <br />
                                  <small style={{ color: '#666' }}>{item.usuario_email}</small>
                                </div>
                              </td>
                              <td style={{ padding: '12px' }}>
                                ${item.precio_anterior.toFixed(2)}
                              </td>
                              <td style={{ padding: '12px' }}>
                                ${item.precio_nuevo.toFixed(2)}
                              </td>
                              <td style={{ padding: '12px' }}>
                                <span style={{
                                  color: cambio >= 0 ? '#059669' : '#dc2626',
                                  fontWeight: 'bold'
                                }}>
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

            <div className={styles.pagination}>
              <button 
                onClick={() => setPage(p => Math.max(1, p - 1))} 
                disabled={page === 1} 
                className={styles.paginationBtn}
              >
                ← Anterior
              </button>
              <span>Página {page} {totalProductos > 0 && `(${((page-1)*pageSize + 1)} - ${Math.min(page*pageSize, totalProductos)})`}</span>
              <button 
                onClick={() => setPage(p => p + 1)} 
                disabled={productos.length < pageSize} 
                className={styles.paginationBtn}
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
