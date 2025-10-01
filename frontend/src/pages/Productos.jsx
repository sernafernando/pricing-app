import { useState, useEffect } from 'react';
import { productosAPI } from '../services/api';
import PricingModal from '../components/PricingModal';
import { useDebounce } from '../hooks/useDebounce';
import styles from './Productos.module.css';

export default function Productos() {
  const [productos, setProductos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState(null);
  const [productoSeleccionado, setProductoSeleccionado] = useState(null);
  const [searchInput, setSearchInput] = useState('');
  const [page, setPage] = useState(1);
  
  const debouncedSearch = useDebounce(searchInput, 500);
  
  useEffect(() => {
    cargarStats();
  }, []);
  
  useEffect(() => {
    cargarProductos();
  }, [page, debouncedSearch]);
  
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
      const params = { page, page_size: 50 };
      if (debouncedSearch) params.search = debouncedSearch;
      
      const productosRes = await productosAPI.listar(params);
      setProductos(productosRes.data.productos);
    } catch (error) {
      console.error('Error:', error);
    } finally {
      setLoading(false);
    }
  };
  
  const handleSearchChange = (e) => {
    setSearchInput(e.target.value);
    setPage(1);
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
      
      <div className={styles.searchBar}>
        <input
          type="text"
          placeholder="Buscar por código, descripción o marca..."
          value={searchInput}
          onChange={handleSearchChange}
          className={styles.searchInput}
        />
        {loading && <span style={{ marginLeft: '10px', color: '#666' }}>Buscando...</span>}
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
                  <th>Precio ML</th>
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
                    <td>{p.precio_lista_ml ? `$${p.precio_lista_ml.toFixed(2)}` : '-'}</td>
                    <td>
                      <button
                        onClick={() => setProductoSeleccionado(p)}
                        className={styles.priceBtn}
                      >
                        Precio
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
              <span>Página {page}</span>
              <button
                onClick={() => setPage(p => p + 1)}
                disabled={productos.length < 50}
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
