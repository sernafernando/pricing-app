import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './SetupMarkups.module.css';

const api = axios.create({
  baseURL: 'https://pricing.gaussonline.com.ar',
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default function SetupMarkups() {
  // Estados para marcas
  const [brands, setBrands] = useState([]);
  const [loadingBrands, setLoadingBrands] = useState(false);
  const [busquedaMarca, setBusquedaMarca] = useState('');
  const [soloConMarkup, setSoloConMarkup] = useState(false);
  const [editandoMarkupMarca, setEditandoMarkupMarca] = useState(null);
  const [markupTempMarca, setMarkupTempMarca] = useState('');
  const [stats, setStats] = useState(null);

  // Estados para productos individuales
  const [busquedaProducto, setBusquedaProducto] = useState('');
  const [productosEncontrados, setProductosEncontrados] = useState([]);
  const [buscandoProductos, setBuscandoProductos] = useState(false);
  const [productosConMarkup, setProductosConMarkup] = useState([]);
  const [loadingProductos, setLoadingProductos] = useState(false);
  const [editandoMarkupProducto, setEditandoMarkupProducto] = useState(null);
  const [markupTempProducto, setMarkupTempProducto] = useState('');

  const [toast, setToast] = useState(null);

  // ========== FUNCIONES MARCAS ==========
  const cargarBrands = async () => {
    setLoadingBrands(true);
    try {
      const params = new URLSearchParams();
      if (busquedaMarca) params.append('busqueda', busquedaMarca);
      if (soloConMarkup) params.append('solo_con_markup', 'true');

      const response = await api.get(`/api/markups-tienda/brands?${params}`);
      setBrands(response.data);
    } catch (error) {
      console.error('Error cargando brands:', error);
      mostrarToast('Error al cargar marcas', 'error');
    } finally {
      setLoadingBrands(false);
    }
  };

  const cargarStats = async () => {
    try {
      const response = await api.get('/api/markups-tienda/stats');
      setStats(response.data);
    } catch (error) {
      console.error('Error cargando stats:', error);
    }
  };

  const guardarMarkupMarca = async (brand) => {
    if (!markupTempMarca || isNaN(parseFloat(markupTempMarca))) {
      mostrarToast('Ingresá un markup válido', 'error');
      return;
    }

    try {
      await api.post(
        `/api/markups-tienda/brands/${brand.comp_id}/${brand.brand_id}/markup`,
        {
          comp_id: brand.comp_id,
          brand_id: brand.brand_id,
          brand_desc: brand.brand_desc,
          markup_porcentaje: parseFloat(markupTempMarca),
          activo: true
        }
      );

      mostrarToast('Markup guardado', 'success');
      setEditandoMarkupMarca(null);
      setMarkupTempMarca('');
      cargarBrands();
      cargarStats();
    } catch (error) {
      console.error('Error guardando markup:', error);
      mostrarToast('Error al guardar markup', 'error');
    }
  };

  const eliminarMarkupMarca = async (brand) => {
    if (!confirm(`¿Eliminar markup de ${brand.brand_desc}?`)) return;

    try {
      await api.delete(`/api/markups-tienda/brands/${brand.comp_id}/${brand.brand_id}/markup`);
      mostrarToast('Markup eliminado', 'success');
      cargarBrands();
      cargarStats();
    } catch (error) {
      console.error('Error eliminando markup:', error);
      mostrarToast('Error al eliminar markup', 'error');
    }
  };

  // ========== FUNCIONES PRODUCTOS ==========
  const buscarProductos = async () => {
    if (busquedaProducto.length < 2) return;
    setBuscandoProductos(true);
    try {
      const response = await api.get('/api/buscar-productos-erp', {
        params: { q: busquedaProducto }
      });
      setProductosEncontrados(response.data);
    } catch (error) {
      console.error('Error buscando productos:', error);
    } finally {
      setBuscandoProductos(false);
    }
  };

  const cargarProductosConMarkup = async () => {
    setLoadingProductos(true);
    try {
      const response = await api.get('/api/markups-tienda/productos');
      setProductosConMarkup(response.data);
    } catch (error) {
      console.error('Error cargando productos con markup:', error);
    } finally {
      setLoadingProductos(false);
    }
  };

  const guardarMarkupProducto = async (producto) => {
    if (!markupTempProducto || isNaN(parseFloat(markupTempProducto))) {
      mostrarToast('Ingresá un markup válido', 'error');
      return;
    }

    try {
      await api.post(`/api/markups-tienda/productos/${producto.item_id}/markup`, {
        item_id: producto.item_id,
        codigo: producto.codigo,
        descripcion: producto.descripcion,
        markup_porcentaje: parseFloat(markupTempProducto),
        activo: true
      });

      mostrarToast('Markup guardado', 'success');
      setEditandoMarkupProducto(null);
      setMarkupTempProducto('');
      setProductosEncontrados([]);
      setBusquedaProducto('');
      cargarProductosConMarkup();
      cargarStats();
    } catch (error) {
      console.error('Error guardando markup:', error);
      mostrarToast('Error al guardar markup', 'error');
    }
  };

  const eliminarMarkupProducto = async (producto) => {
    if (!confirm(`¿Eliminar markup de ${producto.codigo}?`)) return;

    try {
      await api.delete(`/api/markups-tienda/productos/${producto.item_id}/markup`);
      mostrarToast('Markup eliminado', 'success');
      cargarProductosConMarkup();
      cargarStats();
    } catch (error) {
      console.error('Error eliminando markup:', error);
      mostrarToast('Error al eliminar markup', 'error');
    }
  };

  const seleccionarProducto = (producto) => {
    setEditandoMarkupProducto(producto);
    setMarkupTempProducto('');
    setProductosEncontrados([]);
  };

  // ========== HELPERS ==========
  const mostrarToast = (mensaje, tipo) => {
    setToast({ mensaje, tipo });
    setTimeout(() => setToast(null), 3000);
  };

  useEffect(() => {
    cargarBrands();
    cargarStats();
    cargarProductosConMarkup();
  }, []);

  useEffect(() => {
    cargarBrands();
  }, [busquedaMarca, soloConMarkup]);

  return (
    <div className={styles.container}>
      {/* Stats compactas */}
      {stats && (
        <div className={styles.statsRow}>
          <div className={styles.statItem}>
            <span className={styles.statNumber}>{stats.total_marcas}</span>
            <span className={styles.statLabel}>Marcas</span>
          </div>
          <div className={styles.statDivider} />
          <div className={styles.statItem}>
            <span className={`${styles.statNumber} ${styles.green}`}>{stats.total_con_markup}</span>
            <span className={styles.statLabel}>Con Markup</span>
          </div>
          <div className={styles.statDivider} />
          <div className={styles.statItem}>
            <span className={`${styles.statNumber} ${styles.red}`}>{stats.total_sin_markup}</span>
            <span className={styles.statLabel}>Sin Markup</span>
          </div>
          <div className={styles.statDivider} />
          <div className={styles.statItem}>
            <span className={`${styles.statNumber} ${styles.blue}`}>{stats.markup_promedio}%</span>
            <span className={styles.statLabel}>Promedio</span>
          </div>
        </div>
      )}

      {/* Sección Marcas */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Markups por Marca</h3>

        <div className={styles.filtersRow}>
          <div className={styles.searchBox}>
            <input
              type="text"
              placeholder="Buscar marca..."
              value={busquedaMarca}
              onChange={(e) => setBusquedaMarca(e.target.value)}
            />
            {busquedaMarca && (
              <button onClick={() => setBusquedaMarca('')} className={styles.clearBtn}>✕</button>
            )}
          </div>
          <label className={styles.checkboxLabel}>
            <input
              type="checkbox"
              checked={soloConMarkup}
              onChange={(e) => setSoloConMarkup(e.target.checked)}
            />
            Solo con markup
          </label>
        </div>

        <div className={styles.tableWrapper}>
          {loadingBrands ? (
            <div className={styles.loading}>Cargando...</div>
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Marca</th>
                  <th style={{width: '120px'}}>Markup</th>
                  <th style={{width: '80px'}}>Estado</th>
                  <th style={{width: '100px'}}>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {brands.length === 0 ? (
                  <tr><td colSpan="4" className={styles.noData}>No se encontraron marcas</td></tr>
                ) : (
                  brands.map((brand) => (
                    <tr key={`${brand.comp_id}-${brand.brand_id}`}>
                      <td>
                        <strong>{brand.brand_desc}</strong>
                        <span className={styles.subText}>ID: {brand.brand_id}</span>
                      </td>
                      <td>
                        {editandoMarkupMarca?.brand_id === brand.brand_id ? (
                          <div className={styles.inputGroup}>
                            <input
                              type="number"
                              step="0.1"
                              value={markupTempMarca}
                              onChange={(e) => setMarkupTempMarca(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') guardarMarkupMarca(brand);
                                if (e.key === 'Escape') setEditandoMarkupMarca(null);
                              }}
                              autoFocus
                              placeholder="0"
                            />
                            <span>%</span>
                          </div>
                        ) : (
                          <span
                            className={`${styles.markupValue} ${brand.markup_porcentaje ? styles.hasValue : styles.noValue}`}
                            onClick={() => {
                              setEditandoMarkupMarca(brand);
                              setMarkupTempMarca(brand.markup_porcentaje?.toString() || '');
                            }}
                          >
                            {brand.markup_porcentaje ? `${brand.markup_porcentaje}%` : '—'}
                          </span>
                        )}
                      </td>
                      <td>
                        {brand.markup_id && (
                          <span className={`${styles.badge} ${brand.markup_activo ? styles.active : styles.inactive}`}>
                            {brand.markup_activo ? 'Activo' : 'Inactivo'}
                          </span>
                        )}
                      </td>
                      <td>
                        {editandoMarkupMarca?.brand_id === brand.brand_id ? (
                          <div className={styles.actionBtns}>
                            <button onClick={() => guardarMarkupMarca(brand)} className={styles.btnSave}>✓</button>
                            <button onClick={() => setEditandoMarkupMarca(null)} className={styles.btnCancel}>✕</button>
                          </div>
                        ) : (
                          <div className={styles.actionBtns}>
                            <button
                              onClick={() => {
                                setEditandoMarkupMarca(brand);
                                setMarkupTempMarca(brand.markup_porcentaje?.toString() || '');
                              }}
                              className={styles.btnEdit}
                            >✏️</button>
                            {brand.markup_id && (
                              <button onClick={() => eliminarMarkupMarca(brand)} className={styles.btnDelete}>🗑️</button>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Sección Productos */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Markups por Producto Individual</h3>

        {/* Buscador de productos */}
        <div className={styles.productSearch}>
          <div className={styles.searchBox}>
            <input
              type="text"
              placeholder="Buscar producto por código o descripción..."
              value={busquedaProducto}
              onChange={(e) => setBusquedaProducto(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && buscarProductos()}
            />
          </div>
          <button
            onClick={buscarProductos}
            disabled={busquedaProducto.length < 2 || buscandoProductos}
            className={styles.btnBuscar}
          >
            {buscandoProductos ? '...' : 'Buscar'}
          </button>
        </div>

        {/* Resultados de búsqueda */}
        {productosEncontrados.length > 0 && (
          <div className={styles.searchResults}>
            {productosEncontrados.map(producto => (
              <div
                key={producto.item_id}
                className={styles.searchResultItem}
                onClick={() => seleccionarProducto(producto)}
              >
                <div className={styles.productInfo}>
                  <span className={styles.productCode}>{producto.codigo}</span>
                  <span className={styles.productName}>{producto.descripcion}</span>
                  <span className={styles.productBrand}>{producto.marca}</span>
                </div>
                <button className={styles.btnAdd}>+ Agregar</button>
              </div>
            ))}
          </div>
        )}

        {/* Form para agregar markup al producto seleccionado */}
        {editandoMarkupProducto && !editandoMarkupProducto.markup_id && (
          <div className={styles.addMarkupForm}>
            <div className={styles.selectedProduct}>
              <span className={styles.productCode}>{editandoMarkupProducto.codigo}</span>
              <span className={styles.productName}>{editandoMarkupProducto.descripcion}</span>
            </div>
            <div className={styles.inputGroup}>
              <input
                type="number"
                step="0.1"
                value={markupTempProducto}
                onChange={(e) => setMarkupTempProducto(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') guardarMarkupProducto(editandoMarkupProducto);
                  if (e.key === 'Escape') setEditandoMarkupProducto(null);
                }}
                autoFocus
                placeholder="Markup %"
              />
              <span>%</span>
            </div>
            <button onClick={() => guardarMarkupProducto(editandoMarkupProducto)} className={styles.btnSave}>Guardar</button>
            <button onClick={() => setEditandoMarkupProducto(null)} className={styles.btnCancel}>Cancelar</button>
          </div>
        )}

        {/* Lista de productos con markup */}
        <div className={styles.tableWrapper}>
          {loadingProductos ? (
            <div className={styles.loading}>Cargando...</div>
          ) : productosConMarkup.length === 0 ? (
            <div className={styles.noData}>No hay productos con markup individual</div>
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Código</th>
                  <th>Descripción</th>
                  <th>Marca</th>
                  <th style={{width: '100px'}}>Markup</th>
                  <th style={{width: '80px'}}>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {productosConMarkup.map((producto) => (
                  <tr key={producto.item_id}>
                    <td><strong>{producto.codigo}</strong></td>
                    <td className={styles.descripcionCell}>{producto.descripcion}</td>
                    <td>{producto.marca}</td>
                    <td>
                      {editandoMarkupProducto?.item_id === producto.item_id ? (
                        <div className={styles.inputGroup}>
                          <input
                            type="number"
                            step="0.1"
                            value={markupTempProducto}
                            onChange={(e) => setMarkupTempProducto(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') guardarMarkupProducto(producto);
                              if (e.key === 'Escape') setEditandoMarkupProducto(null);
                            }}
                            autoFocus
                          />
                          <span>%</span>
                        </div>
                      ) : (
                        <span
                          className={`${styles.markupValue} ${styles.hasValue}`}
                          onClick={() => {
                            setEditandoMarkupProducto(producto);
                            setMarkupTempProducto(producto.markup_porcentaje?.toString() || '');
                          }}
                        >
                          {producto.markup_porcentaje}%
                        </span>
                      )}
                    </td>
                    <td>
                      {editandoMarkupProducto?.item_id === producto.item_id ? (
                        <div className={styles.actionBtns}>
                          <button onClick={() => guardarMarkupProducto(producto)} className={styles.btnSave}>✓</button>
                          <button onClick={() => setEditandoMarkupProducto(null)} className={styles.btnCancel}>✕</button>
                        </div>
                      ) : (
                        <div className={styles.actionBtns}>
                          <button
                            onClick={() => {
                              setEditandoMarkupProducto(producto);
                              setMarkupTempProducto(producto.markup_porcentaje?.toString() || '');
                            }}
                            className={styles.btnEdit}
                          >✏️</button>
                          <button onClick={() => eliminarMarkupProducto(producto)} className={styles.btnDelete}>🗑️</button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div className={`${styles.toast} ${toast.tipo === 'success' ? styles.toastSuccess : styles.toastError}`}>
          {toast.tipo === 'success' ? '✓' : '✕'} {toast.mensaje}
        </div>
      )}
    </div>
  );
}
