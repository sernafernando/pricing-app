import { useState, useEffect, useMemo } from 'react';
import axios from 'axios';
import '../pages/Productos.css';
import styles from './TabRentabilidad.module.css';
import ModalOffset from './ModalOffset';
import { useQueryFilters } from '../hooks/useQueryFilters';

const API_URL = import.meta.env.VITE_API_URL;

const api = axios.create({
  baseURL: `${API_URL}`,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default function TabRentabilidad({ 
  fechaDesde, 
  fechaHasta, 
  tiendasOficiales = [], 
  pmsSeleccionados = [],
  marcasSeleccionadas: marcasExternas = [],
  categoriasSeleccionadas: categoriasExternas = []
}) {
  const [loading, setLoading] = useState(false);
  const [rentabilidad, setRentabilidad] = useState(null);
  const [filtrosDisponibles, setFiltrosDisponibles] = useState({
    marcas: [],
    categorias: [],
    subcategorias: []
  });

  // Usar query params para filtros seleccionados
  const { getFilter, updateFilters } = useQueryFilters({
    marcas: [],
    categorias: [],
    subcategorias: [],
    productos: []
  }, {
    productos: 'number[]'  // Parsear productos como array de números
  });

  const marcasSeleccionadas = getFilter('marcas');
  const categoriasSeleccionadas = getFilter('categorias');
  const subcategoriasSeleccionadas = getFilter('subcategorias');
  const productosSeleccionados = getFilter('productos');

  // Búsquedas en filtros
  const [busquedaMarca, setBusquedaMarca] = useState('');
  const [busquedaCategoria, setBusquedaCategoria] = useState('');
  const [busquedaSubcategoria, setBusquedaSubcategoria] = useState('');

  // Búsqueda de productos
  const [busquedaProducto, setBusquedaProducto] = useState('');
  const [productosEncontrados, setProductosEncontrados] = useState([]);
  const [productosSeleccionadosDetalle, setProductosSeleccionadosDetalle] = useState([]);
  const [buscandoProductos, setBuscandoProductos] = useState(false);

  // Panel activo
  const [panelFiltroActivo, setPanelFiltroActivo] = useState(null);

  // Modal de offsets
  const [mostrarModalOffset, setMostrarModalOffset] = useState(false);

  // Guardar las fechas actuales para mostrar en el UI
  const [fechasActuales, setFechasActuales] = useState({ desde: null, hasta: null });

  // Convertir arrays a strings para evitar re-renders infinitos
  const marcasKey = useMemo(() => marcasSeleccionadas.join(','), [marcasSeleccionadas.join(',')]);
  const categoriasKey = useMemo(() => categoriasSeleccionadas.join(','), [categoriasSeleccionadas.join(',')]);
  const subcategoriasKey = useMemo(() => subcategoriasSeleccionadas.join(','), [subcategoriasSeleccionadas.join(',')]);
  const productosKey = useMemo(() => productosSeleccionados.join(','), [productosSeleccionados.join(',')]);
  const pmsKey = useMemo(() => pmsSeleccionados.join(','), [pmsSeleccionados.join(',')]);
  const tiendasKey = useMemo(() => tiendasOficiales.join(','), [tiendasOficiales.join(',')]);

  useEffect(() => {
    if (fechaDesde && fechaHasta) {
      // Guardar las fechas que se están usando
      setFechasActuales({ desde: fechaDesde, hasta: fechaHasta });
      cargarFiltros();
      cargarRentabilidad();
    }
  }, [fechaDesde, fechaHasta, tiendasKey, pmsKey]);

  useEffect(() => {
    if (fechaDesde && fechaHasta) {
      cargarRentabilidad();
      cargarFiltros(); // También recargar filtros disponibles cuando cambian las selecciones
    }
  }, [marcasKey, categoriasKey, subcategoriasKey, productosKey, pmsKey]);

  const cargarFiltros = async () => {
    try {
      const params = {
        fecha_desde: fechaDesde,
        fecha_hasta: fechaHasta
      };
      // Enviar todos los filtros para retroalimentación (usar | como separador para evitar conflictos con comas en nombres)
      if (marcasSeleccionadas.length > 0) {
        params.marcas = marcasSeleccionadas.join('|');
      }
      if (categoriasSeleccionadas.length > 0) {
        params.categorias = categoriasSeleccionadas.join('|');
      }
      if (subcategoriasSeleccionadas.length > 0) {
        params.subcategorias = subcategoriasSeleccionadas.join('|');
      }
      if (tiendasOficiales.length > 0) {
        params.tiendas_oficiales = tiendasOficiales.join(',');
      }
      if (pmsSeleccionados.length > 0) {
        params.pm_ids = pmsSeleccionados.join(',');
      }

      const response = await api.get('/rentabilidad/filtros', { params });
      setFiltrosDisponibles(response.data);
    } catch (error) {
      console.error('Error cargando filtros:', error);
    }
  };

  const cargarRentabilidad = async () => {
    setLoading(true);
    try {
      const params = {
        fecha_desde: fechaDesde,
        fecha_hasta: fechaHasta
      };
      // Usar | como separador para evitar conflictos con comas en nombres
      if (marcasSeleccionadas.length > 0) {
        params.marcas = marcasSeleccionadas.join('|');
      }
      if (categoriasSeleccionadas.length > 0) {
        params.categorias = categoriasSeleccionadas.join('|');
      }
      if (subcategoriasSeleccionadas.length > 0) {
        params.subcategorias = subcategoriasSeleccionadas.join('|');
      }
      if (productosSeleccionados.length > 0) {
        params.productos = productosSeleccionados.join('|');
      }
      if (tiendasOficiales.length > 0) {
        params.tiendas_oficiales = tiendasOficiales.join(',');
      }
      if (pmsSeleccionados.length > 0) {
        params.pm_ids = pmsSeleccionados.join(',');
      }

      const response = await api.get('/rentabilidad', { params });
      setRentabilidad(response.data);
    } catch (error) {
      console.error('Error cargando rentabilidad:', error);
    } finally {
      setLoading(false);
    }
  };

  const buscarProductos = async () => {
    if (busquedaProducto.length < 2) return;
    setBuscandoProductos(true);
    try {
      const params = {
        q: busquedaProducto,
        fecha_desde: fechaDesde,
        fecha_hasta: fechaHasta
      };
      if (tiendasOficiales.length > 0) {
        params.tiendas_oficiales = tiendasOficiales.join(',');
      }
      if (pmsSeleccionados.length > 0) {
        params.pm_ids = pmsSeleccionados.join(',');
      }
      
      const response = await api.get('/rentabilidad/buscar-productos', { params });
      setProductosEncontrados(response.data);
    } catch (error) {
      console.error('Error buscando productos:', error);
    } finally {
      setBuscandoProductos(false);
    }
  };

  const agregarProducto = (producto) => {
    const idsActuales = productosSeleccionados;
    if (!idsActuales.includes(producto.item_id)) {
      updateFilters({ productos: [...idsActuales, producto.item_id] });
      setProductosSeleccionadosDetalle([...productosSeleccionadosDetalle, producto]);
    }
  };

  const quitarProducto = (itemId) => {
    updateFilters({ productos: productosSeleccionados.filter(id => id !== itemId) });
    setProductosSeleccionadosDetalle(productosSeleccionadosDetalle.filter(p => p.item_id !== itemId));
  };

  const limpiarFiltros = () => {
    updateFilters({
      marcas: [],
      categorias: [],
      subcategorias: [],
      productos: []
    });
    setProductosSeleccionadosDetalle([]);
    setProductosEncontrados([]);
    setBusquedaProducto('');
  };

  const formatMoney = (valor) => {
    if (valor === null || valor === undefined) return '$0';
    return new Intl.NumberFormat('es-AR', {
      style: 'currency',
      currency: 'ARS',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(valor);
  };

  const formatPercent = (valor) => {
    if (valor === null || valor === undefined) return '0%';
    return `${valor.toFixed(2)}%`;
  };

  const formatFecha = (fecha) => {
    if (!fecha) return '';
    const [year, month, day] = fecha.split('-');
    return `${day}/${month}/${year}`;
  };

  const getMarkupColor = (markup) => {
    if (markup < 0) return '#ef4444';
    if (markup < 3) return '#f59e0b';
    if (markup < 6) return '#eab308';
    return '#22c55e';
  };

  // Función para hacer drill-down al hacer click en una card
  const handleCardClick = (card) => {
    // No hacer drill-down si ya estamos a nivel producto
    if (card.tipo === 'producto') return;

    if (card.tipo === 'marca') {
      // Click en marca: agregar la marca al filtro
      if (!marcasSeleccionadas.includes(card.nombre)) {
        updateFilters({ marcas: [...marcasSeleccionadas, card.nombre] });
      }
    } else if (card.tipo === 'categoria') {
      // Click en categoría: agregar la categoría al filtro
      if (!categoriasSeleccionadas.includes(card.nombre)) {
        updateFilters({ categorias: [...categoriasSeleccionadas, card.nombre] });
      }
    } else if (card.tipo === 'subcategoria') {
      // Click en subcategoría: agregar la subcategoría al filtro
      if (!subcategoriasSeleccionadas.includes(card.nombre)) {
        updateFilters({ subcategorias: [...subcategoriasSeleccionadas, card.nombre] });
      }
    }
  };

  // Determinar si una card es clickeable (tiene drill-down disponible)
  const isCardClickable = (card) => {
    return card.tipo !== 'producto';
  };

  // Filtrar marcas por búsqueda
  const marcasFiltradas = filtrosDisponibles.marcas.filter(m =>
    m.toLowerCase().includes(busquedaMarca.toLowerCase())
  );

  // Filtrar categorías por búsqueda
  const categoriasFiltradas = filtrosDisponibles.categorias.filter(c =>
    c.toLowerCase().includes(busquedaCategoria.toLowerCase())
  );

  // Filtrar subcategorías por búsqueda
  const subcategoriasFiltradas = filtrosDisponibles.subcategorias.filter(s =>
    s.toLowerCase().includes(busquedaSubcategoria.toLowerCase())
  );

  const getTotalFiltrosActivos = () => {
    return marcasSeleccionadas.length + categoriasSeleccionadas.length + subcategoriasSeleccionadas.length + productosSeleccionados.length;
  };

  return (
    <div className={styles.container}>
      {/* Barra de botones de filtro */}
      <div className={styles.filtrosBar}>
        <button
          className={`${styles.btnFiltro} ${panelFiltroActivo === 'marcas' ? styles.btnFiltroActivo : ''} ${marcasSeleccionadas.length > 0 && panelFiltroActivo !== 'marcas' ? styles.btnFiltroConSeleccion : ''}`}
          onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'marcas' ? null : 'marcas')}
        >
          Marcas
          {marcasSeleccionadas.length > 0 && (
            <span className={styles.btnFiltroBadge}>{marcasSeleccionadas.length}</span>
          )}
        </button>

        <button
          className={`${styles.btnFiltro} ${panelFiltroActivo === 'categorias' ? styles.btnFiltroActivo : ''} ${categoriasSeleccionadas.length > 0 && panelFiltroActivo !== 'categorias' ? styles.btnFiltroConSeleccion : ''}`}
          onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'categorias' ? null : 'categorias')}
        >
          Categorías
          {categoriasSeleccionadas.length > 0 && (
            <span className={styles.btnFiltroBadge}>{categoriasSeleccionadas.length}</span>
          )}
        </button>

        <button
          className={`${styles.btnFiltro} ${panelFiltroActivo === 'subcategorias' ? styles.btnFiltroActivo : ''} ${subcategoriasSeleccionadas.length > 0 && panelFiltroActivo !== 'subcategorias' ? styles.btnFiltroConSeleccion : ''}`}
          onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'subcategorias' ? null : 'subcategorias')}
        >
          Subcategorías
          {subcategoriasSeleccionadas.length > 0 && (
            <span className={styles.btnFiltroBadge}>{subcategoriasSeleccionadas.length}</span>
          )}
        </button>

        <button
          className={`${styles.btnProductos} ${panelFiltroActivo === 'productos' ? styles.btnProductosActivo : ''} ${productosSeleccionados.length > 0 && panelFiltroActivo !== 'productos' ? styles.btnProductosConSeleccion : ''}`}
          onClick={() => setPanelFiltroActivo(panelFiltroActivo === 'productos' ? null : 'productos')}
        >
          Productos
          {productosSeleccionados.length > 0 && (
            <span className={styles.btnFiltroBadge}>{productosSeleccionados.length}</span>
          )}
        </button>

        {getTotalFiltrosActivos() > 0 && (
          <button onClick={limpiarFiltros} className={styles.btnLimpiar}>
            Limpiar filtros
          </button>
        )}

        <button
          onClick={() => setMostrarModalOffset(true)}
          className={styles.btnOffset}
        >
          Gestionar Offsets
        </button>
      </div>

      {/* Panel de filtros */}
      {panelFiltroActivo && (
        <div className="advanced-filters-panel">
          {/* Panel de Marcas */}
          {panelFiltroActivo === 'marcas' && (
            <>
              <div className="advanced-filters-header">
                <h3>Marcas</h3>
                {marcasSeleccionadas.length > 0 && (
                  <button
                    onClick={() => updateFilters({ marcas: [] })}
                    className="btn-clear-all"
                  >
                    Limpiar ({marcasSeleccionadas.length})
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
                          updateFilters({ marcas: [...marcasSeleccionadas, marca] });
                        } else {
                          updateFilters({ marcas: marcasSeleccionadas.filter(m => m !== marca) });
                        }
                      }}
                    />
                    <span>{marca}</span>
                  </label>
                ))}
              </div>
            </>
          )}

          {/* Panel de Categorías */}
          {panelFiltroActivo === 'categorias' && (
            <>
              <div className="advanced-filters-header">
                <h3>Categorías</h3>
                {categoriasSeleccionadas.length > 0 && (
                  <button
                    onClick={() => updateFilters({ categorias: [] })}
                    className="btn-clear-all"
                  >
                    Limpiar ({categoriasSeleccionadas.length})
                  </button>
                )}
              </div>

              <div className="dropdown-header">
                <div className="dropdown-search">
                  <input
                    type="text"
                    placeholder="Buscar categoría..."
                    value={busquedaCategoria}
                    onChange={(e) => setBusquedaCategoria(e.target.value)}
                    onFocus={(e) => e.target.select()}
                  />
                  {busquedaCategoria && (
                    <button
                      onClick={() => setBusquedaCategoria('')}
                      className="dropdown-search-clear"
                    >
                      ✕
                    </button>
                  )}
                </div>
              </div>

              <div className="dropdown-content">
                {categoriasFiltradas.map(cat => (
                  <label
                    key={cat}
                    className={`dropdown-item ${categoriasSeleccionadas.includes(cat) ? 'selected' : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={categoriasSeleccionadas.includes(cat)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          updateFilters({ categorias: [...categoriasSeleccionadas, cat] });
                        } else {
                          updateFilters({ categorias: categoriasSeleccionadas.filter(c => c !== cat) });
                        }
                      }}
                    />
                    <span>{cat}</span>
                  </label>
                ))}
              </div>
            </>
          )}

          {/* Panel de Subcategorías */}
          {panelFiltroActivo === 'subcategorias' && (
            <>
              <div className="advanced-filters-header">
                <h3>Subcategorías</h3>
                {subcategoriasSeleccionadas.length > 0 && (
                  <button
                    onClick={() => updateFilters({ subcategorias: [] })}
                    className="btn-clear-all"
                  >
                    Limpiar filtros ({subcategoriasSeleccionadas.length})
                  </button>
                )}
              </div>

              <div className="dropdown-header">
                <div className="dropdown-search">
                  <input
                    type="text"
                    placeholder="Buscar subcategoría..."
                    value={busquedaSubcategoria}
                    onChange={(e) => setBusquedaSubcategoria(e.target.value)}
                    onFocus={(e) => e.target.select()}
                  />
                  {busquedaSubcategoria && (
                    <button
                      onClick={() => setBusquedaSubcategoria('')}
                      className="dropdown-search-clear"
                    >
                      ✕
                    </button>
                  )}
                </div>
              </div>

              <div className="dropdown-content">
                {subcategoriasFiltradas.map(subcat => (
                  <label
                    key={subcat}
                    className={`dropdown-item ${subcategoriasSeleccionadas.includes(subcat) ? 'selected' : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={subcategoriasSeleccionadas.includes(subcat)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          updateFilters({ subcategorias: [...subcategoriasSeleccionadas, subcat] });
                        } else {
                          updateFilters({ subcategorias: subcategoriasSeleccionadas.filter(s => s !== subcat) });
                        }
                      }}
                    />
                    <span>{subcat}</span>
                  </label>
                ))}
              </div>
            </>
          )}

          {/* Panel de Productos */}
          {panelFiltroActivo === 'productos' && (
            <>
              <div className="advanced-filters-header">
                <h3>Buscar Productos</h3>
                {productosSeleccionadosDetalle.length > 0 && (
                  <button
                    onClick={() => {
                      updateFilters({ productos: [] });
                      setProductosSeleccionadosDetalle([]);
                    }}
                    className="btn-clear-all"
                  >
                    Limpiar ({productosSeleccionadosDetalle.length})
                  </button>
                )}
              </div>

              {/* Productos seleccionados */}
              {productosSeleccionadosDetalle.length > 0 && (
                <div className={styles.productosSeleccionados}>
                  {productosSeleccionadosDetalle.map(p => (
                    <div key={p.item_id} className={styles.productoChip}>
                      <span>{p.codigo}</span>
                      <button onClick={() => quitarProducto(p.item_id)}>×</button>
                    </div>
                  ))}
                </div>
              )}

              {/* Buscador */}
              <div className={styles.productoBusqueda}>
                <input
                  type="text"
                  placeholder="Buscar por código o descripción..."
                  value={busquedaProducto}
                  onChange={(e) => setBusquedaProducto(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && buscarProductos()}
                />
                <button
                  onClick={buscarProductos}
                  disabled={busquedaProducto.length < 2 || buscandoProductos}
                  className={styles.btnBuscar}
                >
                  {buscandoProductos ? 'Buscando...' : 'Buscar'}
                </button>
              </div>

              {/* Resultados */}
              {productosEncontrados.length > 0 && (
                <div className={styles.productosResultados}>
                  {productosEncontrados.map(producto => {
                    const seleccionado = productosSeleccionados.includes(producto.item_id);
                    return (
                      <div
                        key={producto.item_id}
                        className={styles.productoItem}
                        onClick={() => seleccionado ? quitarProducto(producto.item_id) : agregarProducto(producto)}
                      >
                        <input
                          type="checkbox"
                          checked={seleccionado}
                          readOnly
                        />
                        <div className={styles.productoInfo}>
                          <span className={styles.productoCodigo}>{producto.codigo}</span>
                          <span className={styles.productoNombre}>{producto.descripcion}</span>
                          <span className={styles.productoMarca}>{producto.marca} - {producto.categoria}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {loading ? (
        <div className={styles.loading}>Cargando rentabilidad...</div>
      ) : rentabilidad ? (
        <>
          {/* Card de totales */}
          <div className={styles.totalCard}>
            <div className={styles.totalHeader}>
              <h3>Total del período</h3>
              <span className={styles.totalPeriodo}>
                {formatFecha(fechasActuales.desde)} - {formatFecha(fechasActuales.hasta)}
              </span>
            </div>
            <div className={styles.totalGrid}>
              <div className={styles.totalItem}>
                <span className={styles.totalLabel}>Ventas</span>
                <span className={styles.totalValor}>{rentabilidad.totales.total_ventas}</span>
              </div>
              <div className={styles.totalItem}>
                <span className={styles.totalLabel}>Monto Vendido</span>
                <span className={styles.totalValor}>{formatMoney(rentabilidad.totales.monto_venta)}</span>
              </div>
              <div className={styles.totalItem}>
                <span className={styles.totalLabel}>Limpio</span>
                <span className={styles.totalValor}>{formatMoney(rentabilidad.totales.monto_limpio)}</span>
              </div>
              <div className={styles.totalItem}>
                <span className={styles.totalLabel}>Costo</span>
                <span className={styles.totalValor}>{formatMoney(rentabilidad.totales.costo_total)}</span>
              </div>
              <div className={styles.totalItem}>
                <span className={styles.totalLabel}>Ganancia</span>
                <span className={styles.totalValor} style={{ color: rentabilidad.totales.ganancia >= 0 ? '#22c55e' : '#ef4444' }}>
                  {formatMoney(rentabilidad.totales.ganancia)}
                </span>
              </div>
              <div className={styles.totalItem}>
                <span className={styles.totalLabel}>Markup</span>
                <span className={styles.totalValor} style={{ color: getMarkupColor(rentabilidad.totales.markup_promedio) }}>
                  {formatPercent(rentabilidad.totales.markup_promedio)}
                </span>
              </div>
              {rentabilidad.totales.offset_total > 0 && (
                <>
                  <div className={styles.totalItem}>
                    <span className={styles.totalLabel}>+ Offsets</span>
                    <span className={styles.totalValor} style={{ color: '#3b82f6' }}>
                      {formatMoney(rentabilidad.totales.offset_total)}
                    </span>
                  </div>
                  <div className={styles.totalItem}>
                    <span className={styles.totalLabel}>Ganancia c/Offset</span>
                    <span className={styles.totalValor} style={{ color: rentabilidad.totales.ganancia_con_offset >= 0 ? '#22c55e' : '#ef4444' }}>
                      {formatMoney(rentabilidad.totales.ganancia_con_offset)}
                    </span>
                  </div>
                  <div className={styles.totalItem}>
                    <span className={styles.totalLabel}>Markup c/Offset</span>
                    <span className={styles.totalValor} style={{ color: getMarkupColor(rentabilidad.totales.markup_con_offset) }}>
                      {formatPercent(rentabilidad.totales.markup_con_offset)}
                    </span>
                  </div>
                </>
              )}
            </div>
            {/* Desglose de offsets en totales */}
            {rentabilidad.totales.desglose_offsets && rentabilidad.totales.desglose_offsets.length > 0 && (
              <div className={styles.totalDesgloseOffsets}>
                <div className={styles.desgloseOffsetsHeader}>Desglose de Offsets Aplicados</div>
                <div className={styles.totalDesgloseGrid}>
                  {rentabilidad.totales.desglose_offsets.map((offset, idx) => (
                    <div key={idx} className={styles.totalDesgloseItem}>
                      <div className={styles.desgloseOffsetInfo}>
                        <span className={styles.desgloseOffsetNivel}>{offset.nombre_nivel}</span>
                        <span className={styles.desgloseOffsetDesc}>{offset.descripcion}</span>
                      </div>
                      <span className={styles.desgloseOffsetMonto}>{formatMoney(offset.monto)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Cards por grupo */}
          <div className={styles.cardsGrid}>
            {rentabilidad.cards.map((card, index) => (
              <div
                key={index}
                className={`${styles.card} ${isCardClickable(card) ? styles.cardClickable : ''}`}
                onClick={() => handleCardClick(card)}
              >
                <div className={styles.cardHeader}>
                  <h4 className={styles.cardTitulo}>{card.nombre || 'Sin nombre'}</h4>
                  <span className={styles.cardTipo}>{card.tipo}</span>
                </div>
                <div className={styles.cardBody}>
                  <div className={styles.cardMetrica}>
                    <span>Ventas:</span>
                    <span>{card.total_ventas}</span>
                  </div>
                  <div className={styles.cardMetrica}>
                    <span>Monto:</span>
                    <span>{formatMoney(card.monto_venta)}</span>
                  </div>
                  <div className={styles.cardMetrica}>
                    <span>Limpio:</span>
                    <span>{formatMoney(card.monto_limpio)}</span>
                  </div>
                  <div className={styles.cardMetrica}>
                    <span>Costo:</span>
                    <span>{formatMoney(card.costo_total)}</span>
                  </div>
                  <div className={styles.cardMetrica}>
                    <span>Ganancia:</span>
                    <span style={{ color: card.ganancia >= 0 ? '#22c55e' : '#ef4444' }}>
                      {formatMoney(card.ganancia)}
                    </span>
                  </div>
                  <div className={styles.cardMetrica}>
                    <span>Markup:</span>
                    <span style={{ color: getMarkupColor(card.markup_promedio) }}>
                      {formatPercent(card.markup_promedio)}
                    </span>
                  </div>
                  {card.offset_total > 0 && (
                    <>
                      <div className={styles.cardMetricaOffset}>
                        <span>+ Offset:</span>
                        <span style={{ color: '#3b82f6' }}>{formatMoney(card.offset_total)}</span>
                      </div>
                      <div className={styles.cardMetricaOffset}>
                        <span>Markup c/Off:</span>
                        <span style={{ color: getMarkupColor(card.markup_con_offset) }}>
                          {formatPercent(card.markup_con_offset)}
                        </span>
                      </div>
                      {/* Desglose de offsets */}
                      {card.desglose_offsets && card.desglose_offsets.length > 0 && (
                        <div className={styles.desgloseOffsets}>
                          <div className={styles.desgloseOffsetsHeader}>Desglose Offsets</div>
                          {card.desglose_offsets.map((offset, idx) => (
                            <div key={idx} className={styles.desgloseOffsetItem}>
                              <div className={styles.desgloseOffsetInfo}>
                                <span className={styles.desgloseOffsetNivel}>{offset.nombre_nivel}</span>
                                <span className={styles.desgloseOffsetDesc}>{offset.descripcion}</span>
                              </div>
                              <span className={styles.desgloseOffsetMonto}>{formatMoney(offset.monto)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                  {/* Desglose por marca */}
                  {card.desglose_marcas && card.desglose_marcas.length > 0 && (
                    <div className={styles.cardDesglose}>
                      <div className={styles.desgloseHeader}>Desglose por marca</div>
                      {card.desglose_marcas.map((dm, idx) => (
                        <div key={idx} className={styles.desgloseItem}>
                          <span className={styles.desgloseMarca}>{dm.marca}</span>
                          <div className={styles.desgloseValores}>
                            <span>{formatMoney(dm.monto_venta)}</span>
                            <span style={{ color: dm.ganancia >= 0 ? '#22c55e' : '#ef4444' }}>
                              {formatMoney(dm.ganancia)}
                            </span>
                            <span style={{ color: getMarkupColor(dm.markup_promedio) }}>
                              {formatPercent(dm.markup_promedio)}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className={styles.empty}>No hay datos para el período seleccionado</div>
      )}

      {/* Modal de Offsets compartido */}
      <ModalOffset
        mostrar={mostrarModalOffset}
        onClose={() => setMostrarModalOffset(false)}
        onSave={() => cargarRentabilidad()}
        filtrosDisponibles={filtrosDisponibles}
        fechaDesde={fechaDesde}
        fechaHasta={fechaHasta}
        apiBasePath="/rentabilidad"
      />
    </div>
  );
}
