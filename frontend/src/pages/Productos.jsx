import { useState, useEffect } from 'react';
import { productosAPI } from '../services/api';
import PricingModal from '../components/PricingModal';
import { useDebounce } from '../hooks/useDebounce';
import styles from './Productos.module.css';
import axios from 'axios';

export default function Productos() {
  const [productos, setProductos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState(null);
  const [productoSeleccionado, setProductoSeleccionado] = useState(null);
  const [searchInput, setSearchInput] = useState('');
  const [page, setPage] = useState(1);
  const [editandoPrecio, setEditandoPrecio] = useState(null);
  const [precioTemp, setPrecioTemp] = useState('');
  const [filtroStock, setFiltroStock] = useState('todos');
  const [filtroPrecio, setFiltroPrecio] = useState('todos');
  const [totalProductos, setTotalProductos] = useState(0);
  const [pageSize, setPageSize] = useState(50);

  const debouncedSearch = useDebounce(searchInput, 500);

  useEffect(() => {
    cargarStats();
  }, []);

  useEffect(() => {
    cargarProductos();
  }, [page, debouncedSearch, filtroStock, filtroPrecio, pageSize]);

  const cargarStats = async () => {
    try {
      const statsRes = await productosAPI.stats();
      setStats(statsRes.data);
    } catch (error) {
      console.error('Error:', error);
    }
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

      const productosRes = await productosAPI.listar(params);
      setTotalProductos(productosRes.data.total || productosRes.data.productos.length);

      const productosConDatos = await Promise.all(
        productosRes.data.productos.map(async (p) => {
          const ofertasRes = await axios.get(`https://pricing.gaussonline.com.ar/api/productos/${p.item_id}/ofertas-vigentes`).catch(() => null);

          const ofertaMinima = ofertasRes?.data.publicaciones
            .filter(pub => pub.tiene_oferta)
            .sort((a, b) => a.oferta.precio_final - b.oferta.precio_final)[0];

          return {
            ...p,
            mejor_oferta: ofertaMinima
            // p.markup ya viene del backend, no hace falta calcularlo
          };
        })
      );

      setProductos(productosConDatos);
    } catch (error) {
      console.error('Error:', error);
    } finally {
      setLoading(false);
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
                  <th>Código</th>
                  <th>Descripción</th>
                  <th>Marca</th>
                  <th>Stock</th>
                  <th>Costo</th>
                  <th>Precio Clásica</th>
                  <th>Mejor Oferta</th>
                  <th>Acción</th>
                </tr>
              </thead>
              <tbody className={styles.tableBody}>
                {productos.map((p) => (
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
                        <div style={{ cursor: 'pointer' }} onClick={() => iniciarEdicion(p)}>
                          <div style={{ borderBottom: '1px dashed #ccc', display: 'inline-block' }}>
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
                   	<td>
                   	  {p.mejor_oferta ? (
                   	    <div style={{ fontSize: '12px' }}>
                   	      <div>
                   	        <span style={{ fontWeight: 'bold', color: '#f59e0b' }}>
                   	          ${p.mejor_oferta.oferta.precio_final.toLocaleString('es-AR')}
                   	        </span>
                   	        {p.mejor_oferta.oferta.aporte_meli_porcentaje && (
                   	          <span style={{ fontSize: '9px', color: '#10b981', marginLeft: '4px' }}>
                   	            +{p.mejor_oferta.oferta.aporte_meli_porcentaje}%
                   	          </span>
                   	        )}
                   	      </div>
                   	      <div style={{ fontSize: '10px', color: '#6b7280' }}>
                   	        Hasta {new Date(p.mejor_oferta.oferta.fecha_hasta).toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit' })}
                   	      </div>
                   	      {p.mejor_oferta.oferta.pvp_seller > 0 && (
                   	        <div style={{ fontSize: '11px', marginTop: '4px', borderTop: '1px solid #e5e7eb', paddingTop: '4px' }}>
                   	          <div style={{ color: '#374151' }}>
                   	            PVP: ${p.mejor_oferta.oferta.pvp_seller.toLocaleString('es-AR')}
                   	          </div>
                   	          {p.mejor_oferta.oferta.markup_oferta !== null && (
                   	            <div style={{ 
                   	              fontSize: '10px', 
                   	              color: getMarkupColor(p.mejor_oferta.oferta.markup_oferta),
                   	              fontWeight: '600'
                   	            }}>
                   	              {p.mejor_oferta.oferta.markup_oferta}%
                   	            </div>
                   	          )}
                   	        </div>
                   	      )}
                   	    </div>
                   	  ) : '-'}
                   	</td>
                    <td>
                      <button onClick={() => setProductoSeleccionado(p)} className={styles.priceBtn}>
                        Detalle
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

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
    </div>
  );
}
