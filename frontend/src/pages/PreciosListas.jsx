import { useState, useEffect } from 'react';
import api from '../services/api';
import { useDebounce } from '../hooks/useDebounce';
import styles from './Productos.module.css';
import SearchInput from '../components/SearchInput';

const LISTAS = {
  4: "Clásica",
  17: "3 Cuotas",
  14: "6 Cuotas",
  13: "9 Cuotas",
  23: "12 Cuotas"
};

export default function PreciosListas() {
  const [productos, setProductos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchInput, setSearchInput] = useState('');
  const [page, setPage] = useState(1);
  const [filtroStock, setFiltroStock] = useState('todos');
  const [totalProductos, setTotalProductos] = useState(0);
  const [pageSize, setPageSize] = useState(50);

  const debouncedSearch = useDebounce(searchInput, 500);

  useEffect(() => {
    cargarProductos();
    // cargarProductos se recrea cada render — recargar solo cuando cambian paginación/filtros
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, debouncedSearch, filtroStock, pageSize]);

  const cargarProductos = async () => {
    setLoading(true);
    try {
      const params = { page, page_size: pageSize };
      if (debouncedSearch) params.search = debouncedSearch;
      if (filtroStock === 'con_stock') params.con_stock = true;
      if (filtroStock === 'sin_stock') params.con_stock = false;

      const response = await api.get('/productos/precios-listas', { params });
      
      setProductos(response.data.productos);
      setTotalProductos(response.data.total);
    } catch (error) {
      console.error('Error:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSearchChange = (value) => {
    setSearchInput(value);
    setPage(1);
  };

  return (
    <div className={styles.container}>
      <h1 style={{ fontSize: '28px', fontWeight: '700', marginBottom: '24px' }}>
        💰 Precios por Lista ML
      </h1>

      {/* Búsqueda */}
      <div className={styles.searchBar} style={{ marginBottom: '16px' }}>
        <SearchInput
          value={searchInput}
          onChange={handleSearchChange}
          placeholder="Buscar por código, descripción o marca..."
          size="md"
        />
      </div>

      {/* Filtros */}
      <div style={{ display: 'flex', gap: '12px', marginBottom: '24px', flexWrap: 'wrap' }}>
        <select
          value={filtroStock}
          onChange={(e) => { setFiltroStock(e.target.value); setPage(1); }}
          style={{ padding: '8px 16px', borderRadius: '6px', border: '1px solid #d1d5db' }}
        >
          <option value="todos">📦 Todo el stock</option>
          <option value="con_stock">✅ Con stock</option>
          <option value="sin_stock">❌ Sin stock</option>
        </select>

        <select
          value={pageSize}
          onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
          style={{ padding: '8px 16px', borderRadius: '6px', border: '1px solid #d1d5db' }}
        >
          <option value={50}>50 por página</option>
          <option value={100}>100 por página</option>
          <option value={200}>200 por página</option>
        </select>
      </div>

      <div style={{ color: '#6b7280', marginBottom: '16px' }}>
        Mostrando {productos.length} de {totalProductos.toLocaleString('es-AR')} productos
      </div>

      <div className={styles.tableContainer}>
        {loading ? (
          <div className={styles.loading}>Cargando...</div>
        ) : (
          <>
            <table className={styles.table}>
              <thead className={styles.tableHead}>
                <tr>
                  <th style={{ minWidth: '100px' }}>Código</th>
                  <th style={{ minWidth: '200px' }}>Descripción</th>
                  <th>Marca</th>
                  <th>Stock</th>
                  <th>Costo</th>
                  {Object.entries(LISTAS).map(([id, nombre]) => (
                    <th key={id}>{nombre}</th>
                  ))}
                </tr>
              </thead>
              <tbody className={styles.tableBody}>
                {productos.map((p) => (
                  <tr key={p.item_id}>
                    <td style={{ fontFamily: 'monospace', fontSize: '13px' }}>{p.codigo}</td>
                    <td>{p.descripcion}</td>
                    <td>{p.marca}</td>
                    <td style={{ textAlign: 'center' }}>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontSize: '12px',
                        fontWeight: '600',
                        background: p.stock > 0 ? '#d1fae5' : '#fee2e2',
                        color: p.stock > 0 ? '#065f46' : '#991b1b'
                      }}>
                        {p.stock}
                      </span>
                    </td>
                    <td style={{ fontFamily: 'monospace' }}>
                      {p.moneda_costo} ${p.costo?.toFixed(2)}
                    </td>
                    {Object.keys(LISTAS).map((listId) => {
                      const precio = p.precios_listas?.[listId];
                      return (
                        <td key={listId}>
                          {precio?.precio ? (
                            <div 
                              style={{ position: 'relative' }}
                              title={precio.cotizacion_dolar ? `💵 Cotización USD: $${precio.cotizacion_dolar.toLocaleString('es-AR')}` : ''}
                            >
                              <div style={{ fontWeight: '600', fontSize: '14px' }}>
                                ${precio.precio.toLocaleString('es-AR', {
                                  minimumFractionDigits: 2,
                                  maximumFractionDigits: 2
                                })}
                              </div>
                              {precio.mla && (
                                <div style={{ fontSize: '10px', color: '#6b7280', fontFamily: 'monospace' }}>
                                  {precio.mla}
                                </div>
                              )}
                              {precio.cotizacion_dolar && (
                                <div style={{ fontSize: '9px', color: '#9ca3af', marginTop: '2px' }}>
                                  💵 ${precio.cotizacion_dolar.toLocaleString('es-AR')}
                                </div>
                              )}
                            </div>
                          ) : (
                            <span style={{ color: '#9ca3af', fontSize: '12px' }}>Sin precio</span>
                          )}
                        </td>
                      );
                    })}
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
              <span>
                Página {page} 
                {totalProductos > 0 && ` (${((page-1)*pageSize + 1)} - ${Math.min(page*pageSize, totalProductos)})`}
              </span>
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
    </div>
  );
}
