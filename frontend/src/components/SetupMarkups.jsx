import { useState, useEffect } from 'react';
import api from '../services/api';
import styles from './SetupMarkups.module.css';

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

  // Estados para configuración global
  const [markupWebTarjeta, setMarkupWebTarjeta] = useState('');
  const [editandoWebTarjeta, setEditandoWebTarjeta] = useState(false);
  const [guardandoWebTarjeta, setGuardandoWebTarjeta] = useState(false);

  // ========== FUNCIONES CONFIGURACIÓN ==========
  const cargarConfig = async () => {
    try {
      const response = await api.get('/markups-tienda/config/markup_web_tarjeta');
      setMarkupWebTarjeta(response.data.valor?.toString() || '0');
    } catch (error) {
      console.error('Error cargando config:', error);
    }
  };

  const guardarWebTarjeta = async () => {
    const valor = parseFloat(markupWebTarjeta.replace(',', '.'));
    if (isNaN(valor)) {
      mostrarToast('Ingresá un valor válido', 'error');
      return;
    }

    setGuardandoWebTarjeta(true);
    try {
      await api.put('/markups-tienda/config/markup_web_tarjeta', { valor });
      mostrarToast('Configuración guardada', 'success');
      setEditandoWebTarjeta(false);
    } catch (error) {
      console.error('Error guardando config:', error);
      mostrarToast('Error al guardar', 'error');
    } finally {
      setGuardandoWebTarjeta(false);
    }
  };

  // ========== FUNCIONES MARCAS ==========
  const cargarBrands = async () => {
    setLoadingBrands(true);
    try {
      const params = new URLSearchParams();
      if (busquedaMarca) params.append('busqueda', busquedaMarca);
      if (soloConMarkup) params.append('solo_con_markup', 'true');

      const response = await api.get(`/markups-tienda/brands?${params}`);
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
      const response = await api.get('/markups-tienda/stats');
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
        `/markups-tienda/brands/${brand.comp_id}/${brand.brand_id}/markup`,
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
      await api.delete(`/markups-tienda/brands/${brand.comp_id}/${brand.brand_id}/markup`);
      mostrarToast('Markup eliminado', 'success');
      cargarBrands();
      cargarStats();
    } catch (error) {
      console.error('Error eliminando markup:', error);
      mostrarToast('Error al eliminar markup', 'error');
    }
  };

  const iniciarEdicionMarca = (brand) => {
    setEditandoMarkupMarca({ comp_id: brand.comp_id, brand_id: brand.brand_id });
    setMarkupTempMarca(brand.markup_porcentaje?.toString() || '');
  };

  const cancelarEdicionMarca = () => {
    setEditandoMarkupMarca(null);
    setMarkupTempMarca('');
  };

  // ========== FUNCIONES PRODUCTOS ==========
  const buscarProductos = async () => {
    if (busquedaProducto.length < 2) return;
    setBuscandoProductos(true);
    try {
      const response = await api.get('/buscar-productos-erp', {
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
      const response = await api.get('/markups-tienda/productos');
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
      await api.post(`/markups-tienda/productos/${producto.item_id}/markup`, {
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
      await api.delete(`/markups-tienda/productos/${producto.item_id}/markup`);
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
    cargarConfig();
  }, []);

  useEffect(() => {
    cargarBrands();
  }, [busquedaMarca, soloConMarkup]);

  return (
    <div className={styles.container}>
      {/* Header con estadísticas */}
      <div className={styles.header}>
        {stats && (
          <div className={styles.statsGrid}>
            <div className={styles.statCard}>
              <div className={styles.statIcon}>📊</div>
              <div className={styles.statContent}>
                <div className={styles.statLabel}>Total Marcas</div>
                <div className={styles.statValue}>{stats.total_marcas}</div>
              </div>
            </div>
            <div className={`${styles.statCard} ${styles.statSuccess}`}>
              <div className={styles.statIcon}>✅</div>
              <div className={styles.statContent}>
                <div className={styles.statLabel}>Con Markup</div>
                <div className={styles.statValue}>{stats.total_con_markup}</div>
              </div>
            </div>
            <div className={`${styles.statCard} ${styles.statWarning}`}>
              <div className={styles.statIcon}>❌</div>
              <div className={styles.statContent}>
                <div className={styles.statLabel}>Sin Markup</div>
                <div className={styles.statValue}>{stats.total_sin_markup}</div>
              </div>
            </div>
            <div className={`${styles.statCard} ${styles.statInfo}`}>
              <div className={styles.statIcon}>📈</div>
              <div className={styles.statContent}>
                <div className={styles.statLabel}>Markup Promedio</div>
                <div className={styles.statValue}>{stats.markup_promedio}%</div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ========== SECCIÓN CONFIGURACIÓN GLOBAL ========== */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Configuración Global</h3>
        <div className={styles.configRow}>
          <div className={styles.configLabel}>
            <span className={styles.configIcon}>💳</span>
            <div>
              <strong>Web Tarjeta %</strong>
              <small>Porcentaje adicional sobre Web Transf</small>
            </div>
          </div>
          <div className={styles.configValue}>
            {editandoWebTarjeta ? (
              <div className={styles.editInput}>
                <input
                  type="text"
                  inputMode="decimal"
                  value={markupWebTarjeta}
                  onChange={(e) => setMarkupWebTarjeta(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') guardarWebTarjeta();
                    if (e.key === 'Escape') {
                      setEditandoWebTarjeta(false);
                      cargarConfig();
                    }
                  }}
                  autoFocus
                  placeholder="0"
                />
                <span className={styles.percentSign}>%</span>
                <button
                  onClick={guardarWebTarjeta}
                  disabled={guardandoWebTarjeta}
                  className={`${styles.btn} ${styles.btnSave}`}
                >
                  {guardandoWebTarjeta ? '...' : '✓'}
                </button>
                <button
                  onClick={() => { setEditandoWebTarjeta(false); cargarConfig(); }}
                  className={`${styles.btn} ${styles.btnCancel}`}
                >
                  ✕
                </button>
              </div>
            ) : (
              <div
                className={`${styles.markupDisplay} ${styles.hasMarkup}`}
                onClick={() => setEditandoWebTarjeta(true)}
              >
                <span className={styles.markupValue}>{markupWebTarjeta || '0'}</span>
                <span className={styles.percentSign}>%</span>
                <button className={`${styles.btn} ${styles.btnEdit}`}>✏️</button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ========== SECCIÓN MARCAS ========== */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Markups por Marca</h3>

        {/* Filtros */}
        <div className={styles.filters}>
          <div className={styles.searchBox}>
            <span className={styles.searchIcon}>🔍</span>
            <input
              type="text"
              placeholder="Buscar marca..."
              value={busquedaMarca}
              onChange={(e) => setBusquedaMarca(e.target.value)}
              className={styles.searchInput}
            />
            {busquedaMarca && (
              <button onClick={() => setBusquedaMarca('')} className={styles.clearButton}>
                ✕
              </button>
            )}
          </div>

          <label className={styles.checkbox}>
            <input
              type="checkbox"
              checked={soloConMarkup}
              onChange={(e) => setSoloConMarkup(e.target.checked)}
            />
            <span>Solo con markup</span>
          </label>
        </div>

        {/* Tabla de marcas */}
        {loadingBrands ? (
          <div className={styles.loading}>
            <div className={styles.spinner}></div>
            <p>Cargando marcas...</p>
          </div>
        ) : (
          <div className={styles.tableContainer}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Marca</th>
                  <th>Markup (%)</th>
                  <th>Estado</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {brands.length === 0 ? (
                  <tr>
                    <td colSpan="4" className={styles.emptyState}>
                      <div className={styles.emptyIcon}>📦</div>
                      <p>No se encontraron marcas</p>
                    </td>
                  </tr>
                ) : (
                  brands.map((brand) => (
                    <tr key={`${brand.comp_id}-${brand.brand_id}`} className={styles.row}>
                      <td className={styles.brandName}>
                        <strong>{brand.brand_desc}</strong>
                        <span className={styles.brandId}>ID: {brand.brand_id}</span>
                      </td>
                      <td>
                        {editandoMarkupMarca?.comp_id === brand.comp_id && editandoMarkupMarca?.brand_id === brand.brand_id ? (
                          <div className={styles.editInput}>
                            <input
                              type="number"
                              step="0.1"
                              value={markupTempMarca}
                              onChange={(e) => setMarkupTempMarca(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') guardarMarkupMarca(brand);
                                if (e.key === 'Escape') cancelarEdicionMarca();
                              }}
                              autoFocus
                              placeholder="0.0"
                            />
                            <span className={styles.percentSign}>%</span>
                          </div>
                        ) : (
                          <div
                            className={`${styles.markupDisplay} ${brand.markup_porcentaje ? styles.hasMarkup : styles.noMarkup}`}
                            onClick={() => iniciarEdicionMarca(brand)}
                          >
                            {brand.markup_porcentaje ? (
                              <>
                                <span className={styles.markupValue}>{brand.markup_porcentaje}</span>
                                <span className={styles.percentSign}>%</span>
                              </>
                            ) : (
                              <span className={styles.addMarkup}>+ Agregar markup</span>
                            )}
                          </div>
                        )}
                      </td>
                      <td>
                        {brand.markup_id && (
                          <span className={`${styles.badge} ${brand.markup_activo ? styles.badgeActive : styles.badgeInactive}`}>
                            {brand.markup_activo ? 'Activo' : 'Inactivo'}
                          </span>
                        )}
                      </td>
                      <td>
                        {editandoMarkupMarca?.comp_id === brand.comp_id && editandoMarkupMarca?.brand_id === brand.brand_id ? (
                          <div className={styles.actions}>
                            <button
                              onClick={() => guardarMarkupMarca(brand)}
                              className={`${styles.btn} ${styles.btnSave}`}
                              title="Guardar (Enter)"
                            >
                              ✓
                            </button>
                            <button
                              onClick={cancelarEdicionMarca}
                              className={`${styles.btn} ${styles.btnCancel}`}
                              title="Cancelar (Esc)"
                            >
                              ✕
                            </button>
                          </div>
                        ) : (
                          <div className={styles.actions}>
                            <button
                              onClick={() => iniciarEdicionMarca(brand)}
                              className={`${styles.btn} ${styles.btnEdit}`}
                              title="Editar markup"
                            >
                              ✏️
                            </button>
                            {brand.markup_id && (
                              <button
                                onClick={() => eliminarMarkupMarca(brand)}
                                className={`${styles.btn} ${styles.btnDelete}`}
                                title="Eliminar markup"
                              >
                                🗑️
                              </button>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ========== SECCIÓN PRODUCTOS ========== */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Markups por Producto Individual</h3>

        {/* Buscador de productos */}
        <div className={styles.productSearch}>
          <div className={styles.searchBox}>
            <span className={styles.searchIcon}>🔍</span>
            <input
              type="text"
              placeholder="Buscar producto por código o descripción..."
              value={busquedaProducto}
              onChange={(e) => setBusquedaProducto(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && buscarProductos()}
              className={styles.searchInput}
            />
            {busquedaProducto && (
              <button onClick={() => { setBusquedaProducto(''); setProductosEncontrados([]); }} className={styles.clearButton}>
                ✕
              </button>
            )}
          </div>
          <button
            onClick={buscarProductos}
            disabled={busquedaProducto.length < 2 || buscandoProductos}
            className={styles.btnBuscar}
          >
            {buscandoProductos ? 'Buscando...' : 'Buscar'}
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
            <div className={styles.editInput}>
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
              <span className={styles.percentSign}>%</span>
            </div>
            <button onClick={() => guardarMarkupProducto(editandoMarkupProducto)} className={`${styles.btn} ${styles.btnSave}`}>
              Guardar
            </button>
            <button onClick={() => setEditandoMarkupProducto(null)} className={`${styles.btn} ${styles.btnCancel}`}>
              Cancelar
            </button>
          </div>
        )}

        {/* Lista de productos con markup */}
        {loadingProductos ? (
          <div className={styles.loading}>
            <div className={styles.spinner}></div>
            <p>Cargando productos...</p>
          </div>
        ) : productosConMarkup.length === 0 ? (
          <div className={styles.noData}>No hay productos con markup individual</div>
        ) : (
          <div className={styles.tableContainer}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Código</th>
                  <th>Descripción</th>
                  <th>Marca</th>
                  <th>Markup</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {productosConMarkup.map((producto) => (
                  <tr key={producto.item_id} className={styles.row}>
                    <td><strong>{producto.codigo}</strong></td>
                    <td className={styles.descripcionCell}>{producto.descripcion}</td>
                    <td>{producto.marca}</td>
                    <td>
                      {editandoMarkupProducto?.item_id === producto.item_id ? (
                        <div className={styles.editInput}>
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
                          <span className={styles.percentSign}>%</span>
                        </div>
                      ) : (
                        <div
                          className={`${styles.markupDisplay} ${styles.hasMarkup}`}
                          onClick={() => {
                            setEditandoMarkupProducto(producto);
                            setMarkupTempProducto(producto.markup_porcentaje?.toString() || '');
                          }}
                        >
                          <span className={styles.markupValue}>{producto.markup_porcentaje}</span>
                          <span className={styles.percentSign}>%</span>
                        </div>
                      )}
                    </td>
                    <td>
                      {editandoMarkupProducto?.item_id === producto.item_id ? (
                        <div className={styles.actions}>
                          <button onClick={() => guardarMarkupProducto(producto)} className={`${styles.btn} ${styles.btnSave}`}>✓</button>
                          <button onClick={() => setEditandoMarkupProducto(null)} className={`${styles.btn} ${styles.btnCancel}`}>✕</button>
                        </div>
                      ) : (
                        <div className={styles.actions}>
                          <button
                            onClick={() => {
                              setEditandoMarkupProducto(producto);
                              setMarkupTempProducto(producto.markup_porcentaje?.toString() || '');
                            }}
                            className={`${styles.btn} ${styles.btnEdit}`}
                          >✏️</button>
                          <button onClick={() => eliminarMarkupProducto(producto)} className={`${styles.btn} ${styles.btnDelete}`}>🗑️</button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Toast */}
      {toast && (
        <div className={`${styles.toast} ${styles[`toast${toast.tipo === 'success' ? 'Success' : 'Error'}`]}`}>
          {toast.tipo === 'success' ? '✓' : '✕'} {toast.mensaje}
        </div>
      )}
    </div>
  );
}
