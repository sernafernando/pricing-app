import { useState, useEffect } from 'react';
import axios from 'axios';
import '../pages/Productos.css';
import styles from './TabRentabilidad.module.css';

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

export default function TabRentabilidad({ fechaDesde, fechaHasta }) {
  const [loading, setLoading] = useState(false);
  const [rentabilidad, setRentabilidad] = useState(null);
  const [filtrosDisponibles, setFiltrosDisponibles] = useState({
    marcas: [],
    categorias: [],
    subcategorias: []
  });

  // Filtros seleccionados
  const [marcasSeleccionadas, setMarcasSeleccionadas] = useState([]);
  const [categoriasSeleccionadas, setCategoriasSeleccionadas] = useState([]);
  const [subcategoriasSeleccionadas, setSubcategoriasSeleccionadas] = useState([]);

  // Búsquedas en filtros
  const [busquedaMarca, setBusquedaMarca] = useState('');
  const [busquedaCategoria, setBusquedaCategoria] = useState('');
  const [busquedaSubcategoria, setBusquedaSubcategoria] = useState('');

  // Búsqueda de productos
  const [busquedaProducto, setBusquedaProducto] = useState('');
  const [productosEncontrados, setProductosEncontrados] = useState([]);
  const [productosSeleccionados, setProductosSeleccionados] = useState([]);
  const [buscandoProductos, setBuscandoProductos] = useState(false);

  // Panel activo
  const [panelFiltroActivo, setPanelFiltroActivo] = useState(null);

  // Modal de offsets
  const [mostrarModalOffset, setMostrarModalOffset] = useState(false);
  const [offsets, setOffsets] = useState([]);
  const [tipoCambioHoy, setTipoCambioHoy] = useState(1000);
  const [editandoOffset, setEditandoOffset] = useState(null);

  // Búsquedas para el modal de offsets
  const [busquedaOffsetMarca, setBusquedaOffsetMarca] = useState('');
  const [busquedaOffsetCategoria, setBusquedaOffsetCategoria] = useState('');
  const [busquedaOffsetSubcategoria, setBusquedaOffsetSubcategoria] = useState('');
  const [busquedaOffsetProducto, setBusquedaOffsetProducto] = useState('');
  const [productosOffsetEncontrados, setProductosOffsetEncontrados] = useState([]);
  const [productosOffsetSeleccionados, setProductosOffsetSeleccionados] = useState([]);
  const [buscandoProductosOffset, setBuscandoProductosOffset] = useState(false);

  const [nuevoOffset, setNuevoOffset] = useState({
    tipo: 'marca',           // marca, categoria, subcategoria, producto
    valor: '',               // para marca, categoria, subcategoria
    tipo_offset: 'monto_fijo', // monto_fijo, monto_por_unidad, porcentaje_costo
    monto: '',
    moneda: 'ARS',
    tipo_cambio: '',
    porcentaje: '',
    descripcion: '',
    fecha_desde: '',
    fecha_hasta: ''
  });

  // Guardar las fechas actuales para mostrar en el UI
  const [fechasActuales, setFechasActuales] = useState({ desde: null, hasta: null });

  useEffect(() => {
    if (fechaDesde && fechaHasta) {
      // Guardar las fechas que se están usando
      setFechasActuales({ desde: fechaDesde, hasta: fechaHasta });
      cargarFiltros();
      cargarRentabilidad();
    }
  }, [fechaDesde, fechaHasta]);

  useEffect(() => {
    if (fechaDesde && fechaHasta) {
      cargarRentabilidad();
    }
  }, [marcasSeleccionadas, categoriasSeleccionadas, subcategoriasSeleccionadas, productosSeleccionados]);

  const cargarFiltros = async () => {
    try {
      const params = {
        fecha_desde: fechaDesde,
        fecha_hasta: fechaHasta
      };
      // Enviar todos los filtros para retroalimentación
      if (marcasSeleccionadas.length > 0) {
        params.marcas = marcasSeleccionadas.join(',');
      }
      if (categoriasSeleccionadas.length > 0) {
        params.categorias = categoriasSeleccionadas.join(',');
      }
      if (subcategoriasSeleccionadas.length > 0) {
        params.subcategorias = subcategoriasSeleccionadas.join(',');
      }

      const response = await api.get('/api/rentabilidad/filtros', { params });
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
      if (marcasSeleccionadas.length > 0) {
        params.marcas = marcasSeleccionadas.join(',');
      }
      if (categoriasSeleccionadas.length > 0) {
        params.categorias = categoriasSeleccionadas.join(',');
      }
      if (subcategoriasSeleccionadas.length > 0) {
        params.subcategorias = subcategoriasSeleccionadas.join(',');
      }
      if (productosSeleccionados.length > 0) {
        params.productos = productosSeleccionados.map(p => p.item_id).join(',');
      }

      const response = await api.get('/api/rentabilidad', { params });
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
      const response = await api.get('/api/rentabilidad/buscar-productos', {
        params: {
          q: busquedaProducto,
          fecha_desde: fechaDesde,
          fecha_hasta: fechaHasta
        }
      });
      setProductosEncontrados(response.data);
    } catch (error) {
      console.error('Error buscando productos:', error);
    } finally {
      setBuscandoProductos(false);
    }
  };

  const agregarProducto = (producto) => {
    if (!productosSeleccionados.find(p => p.item_id === producto.item_id)) {
      setProductosSeleccionados([...productosSeleccionados, producto]);
    }
  };

  const quitarProducto = (itemId) => {
    setProductosSeleccionados(productosSeleccionados.filter(p => p.item_id !== itemId));
  };

  const cargarOffsets = async () => {
    try {
      const [offsetsRes, tcRes] = await Promise.all([
        api.get('/api/offsets-ganancia'),
        api.get('/api/tipo-cambio-hoy')
      ]);
      setOffsets(offsetsRes.data);
      if (tcRes.data.tipo_cambio) {
        setTipoCambioHoy(tcRes.data.tipo_cambio);
        setNuevoOffset(prev => ({ ...prev, tipo_cambio: tcRes.data.tipo_cambio.toString() }));
      }
    } catch (error) {
      console.error('Error cargando offsets:', error);
    }
  };

  const buscarProductosOffset = async () => {
    if (busquedaOffsetProducto.length < 2) return;
    setBuscandoProductosOffset(true);
    try {
      const response = await api.get('/api/rentabilidad/buscar-productos', {
        params: {
          q: busquedaOffsetProducto,
          fecha_desde: fechaDesde,
          fecha_hasta: fechaHasta
        }
      });
      setProductosOffsetEncontrados(response.data);
    } catch (error) {
      console.error('Error buscando productos:', error);
    } finally {
      setBuscandoProductosOffset(false);
    }
  };

  const agregarProductoOffset = (producto) => {
    if (!productosOffsetSeleccionados.find(p => p.item_id === producto.item_id)) {
      setProductosOffsetSeleccionados([...productosOffsetSeleccionados, producto]);
    }
  };

  const quitarProductoOffset = (itemId) => {
    setProductosOffsetSeleccionados(productosOffsetSeleccionados.filter(p => p.item_id !== itemId));
  };

  const resetearFormOffset = () => {
    setNuevoOffset({
      tipo: 'marca',
      valor: '',
      tipo_offset: 'monto_fijo',
      monto: '',
      moneda: 'ARS',
      tipo_cambio: tipoCambioHoy.toString(),
      porcentaje: '',
      descripcion: '',
      fecha_desde: '',
      fecha_hasta: ''
    });
    setProductosOffsetSeleccionados([]);
    setProductosOffsetEncontrados([]);
    setBusquedaOffsetProducto('');
    setEditandoOffset(null);
  };

  const limpiarFiltros = () => {
    setMarcasSeleccionadas([]);
    setCategoriasSeleccionadas([]);
    setSubcategoriasSeleccionadas([]);
    setProductosSeleccionados([]);
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
        setMarcasSeleccionadas([...marcasSeleccionadas, card.nombre]);
      }
    } else if (card.tipo === 'categoria') {
      // Click en categoría: agregar la categoría al filtro
      if (!categoriasSeleccionadas.includes(card.nombre)) {
        setCategoriasSeleccionadas([...categoriasSeleccionadas, card.nombre]);
      }
    } else if (card.tipo === 'subcategoria') {
      // Click en subcategoría: agregar la subcategoría al filtro
      if (!subcategoriasSeleccionadas.includes(card.nombre)) {
        setSubcategoriasSeleccionadas([...subcategoriasSeleccionadas, card.nombre]);
      }
    }
  };

  // Determinar si una card es clickeable (tiene drill-down disponible)
  const isCardClickable = (card) => {
    return card.tipo !== 'producto';
  };

  const guardarOffset = async () => {
    try {
      const payload = {
        tipo_offset: nuevoOffset.tipo_offset,
        descripcion: nuevoOffset.descripcion,
        fecha_desde: nuevoOffset.fecha_desde,
        fecha_hasta: nuevoOffset.fecha_hasta || null
      };

      // Debug: mostrar valor actual del porcentaje
      console.log('DEBUG nuevoOffset:', nuevoOffset);
      console.log('DEBUG porcentaje raw:', nuevoOffset.porcentaje);
      console.log('DEBUG porcentaje parseFloat:', parseFloat(nuevoOffset.porcentaje));

      // Configurar según tipo de offset
      if (nuevoOffset.tipo_offset === 'porcentaje_costo') {
        const porcentajeValue = parseFloat(nuevoOffset.porcentaje);
        console.log('DEBUG porcentajeValue:', porcentajeValue, 'isNaN:', isNaN(porcentajeValue));
        if (isNaN(porcentajeValue)) {
          alert('Debe ingresar un porcentaje válido (valor actual: ' + nuevoOffset.porcentaje + ')');
          return;
        }
        payload.porcentaje = porcentajeValue;
      } else {
        payload.monto = parseFloat(nuevoOffset.monto);
        if (nuevoOffset.tipo_offset === 'monto_por_unidad') {
          payload.moneda = nuevoOffset.moneda;
          if (nuevoOffset.moneda === 'USD') {
            payload.tipo_cambio = parseFloat(nuevoOffset.tipo_cambio);
          }
        }
      }

      // Configurar nivel de aplicación
      if (nuevoOffset.tipo === 'producto' && productosOffsetSeleccionados.length > 0) {
        payload.item_ids = productosOffsetSeleccionados.map(p => p.item_id);
      } else if (nuevoOffset.tipo === 'marca') {
        payload.marca = nuevoOffset.valor;
      } else if (nuevoOffset.tipo === 'categoria') {
        payload.categoria = nuevoOffset.valor;
      } else if (nuevoOffset.tipo === 'subcategoria') {
        payload.subcategoria_id = parseInt(nuevoOffset.valor);
      } else if (nuevoOffset.tipo === 'producto') {
        payload.item_id = parseInt(nuevoOffset.valor);
      }

      console.log('DEBUG payload final:', JSON.stringify(payload, null, 2));

      if (editandoOffset) {
        await api.put(`/api/offsets-ganancia/${editandoOffset}`, payload);
      } else {
        await api.post('/api/offsets-ganancia', payload);
      }

      resetearFormOffset();
      cargarRentabilidad();
      cargarOffsets();
    } catch (error) {
      console.error('Error guardando offset:', error);
      alert('Error al guardar el offset');
    }
  };

  const editarOffset = (offset) => {
    setEditandoOffset(offset.id);
    setNuevoOffset({
      tipo: offset.item_id ? 'producto' : offset.subcategoria_id ? 'subcategoria' : offset.categoria ? 'categoria' : 'marca',
      valor: offset.item_id?.toString() || offset.subcategoria_id?.toString() || offset.categoria || offset.marca || '',
      tipo_offset: offset.tipo_offset || 'monto_fijo',
      monto: offset.monto?.toString() || '',
      moneda: offset.moneda || 'ARS',
      tipo_cambio: offset.tipo_cambio?.toString() || tipoCambioHoy.toString(),
      porcentaje: offset.porcentaje?.toString() || '',
      descripcion: offset.descripcion || '',
      fecha_desde: offset.fecha_desde || '',
      fecha_hasta: offset.fecha_hasta || ''
    });
  };

  const eliminarOffset = async (id) => {
    if (!confirm('¿Eliminar este offset?')) return;
    try {
      await api.delete(`/api/offsets-ganancia/${id}`);
      cargarRentabilidad();
      cargarOffsets();
    } catch (error) {
      console.error('Error eliminando offset:', error);
    }
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
          onClick={() => {
            cargarOffsets();
            setMostrarModalOffset(true);
          }}
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
                    onClick={() => setMarcasSeleccionadas([])}
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
                          setMarcasSeleccionadas([...marcasSeleccionadas, marca]);
                        } else {
                          setMarcasSeleccionadas(marcasSeleccionadas.filter(m => m !== marca));
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
                    onClick={() => setCategoriasSeleccionadas([])}
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
                          setCategoriasSeleccionadas([...categoriasSeleccionadas, cat]);
                        } else {
                          setCategoriasSeleccionadas(categoriasSeleccionadas.filter(c => c !== cat));
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
                    onClick={() => setSubcategoriasSeleccionadas([])}
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
                          setSubcategoriasSeleccionadas([...subcategoriasSeleccionadas, subcat]);
                        } else {
                          setSubcategoriasSeleccionadas(subcategoriasSeleccionadas.filter(s => s !== subcat));
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
                {productosSeleccionados.length > 0 && (
                  <button
                    onClick={() => setProductosSeleccionados([])}
                    className="btn-clear-all"
                  >
                    Limpiar ({productosSeleccionados.length})
                  </button>
                )}
              </div>

              {/* Productos seleccionados */}
              {productosSeleccionados.length > 0 && (
                <div className={styles.productosSeleccionados}>
                  {productosSeleccionados.map(p => (
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
                    const seleccionado = productosSeleccionados.some(p => p.item_id === producto.item_id);
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

      {/* Modal de Offsets */}
      {mostrarModalOffset && (
        <div className={styles.modalOverlay} onClick={() => { setMostrarModalOffset(false); resetearFormOffset(); }}>
          <div className={styles.modal} onClick={e => e.stopPropagation()}>
            <h3>Gestionar Offsets de Ganancia</h3>

            <div className={styles.offsetForm}>
              <h4>{editandoOffset ? 'Editar Offset' : 'Nuevo Offset'}</h4>

              {/* Tipo de Offset */}
              <div className={styles.formRow}>
                <div>
                  <label>Tipo de Offset:</label>
                  <select
                    value={nuevoOffset.tipo_offset}
                    onChange={e => setNuevoOffset({ ...nuevoOffset, tipo_offset: e.target.value })}
                  >
                    <option value="monto_fijo">Monto Fijo Total</option>
                    <option value="monto_por_unidad">Monto por Unidad Vendida</option>
                    <option value="porcentaje_costo">% sobre Costo</option>
                  </select>
                </div>
                <div>
                  <label>Aplicar a:</label>
                  <select
                    value={nuevoOffset.tipo}
                    onChange={e => {
                      setNuevoOffset({ ...nuevoOffset, tipo: e.target.value, valor: '' });
                      setProductosOffsetSeleccionados([]);
                    }}
                    disabled={editandoOffset}
                  >
                    <option value="marca">Marca</option>
                    <option value="categoria">Categoría</option>
                    <option value="subcategoria">Subcategoría</option>
                    <option value="producto">Producto(s)</option>
                  </select>
                </div>
              </div>

              {/* Selector según tipo */}
              {nuevoOffset.tipo === 'marca' && (
                <div className={styles.formRow}>
                  <div style={{ flex: 1 }}>
                    <label>Marca:</label>
                    <select
                      value={nuevoOffset.valor}
                      onChange={e => setNuevoOffset({ ...nuevoOffset, valor: e.target.value })}
                    >
                      <option value="">Seleccionar marca...</option>
                      {filtrosDisponibles.marcas.map(m => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </select>
                  </div>
                </div>
              )}

              {nuevoOffset.tipo === 'categoria' && (
                <div className={styles.formRow}>
                  <div style={{ flex: 1 }}>
                    <label>Categoría:</label>
                    <select
                      value={nuevoOffset.valor}
                      onChange={e => setNuevoOffset({ ...nuevoOffset, valor: e.target.value })}
                    >
                      <option value="">Seleccionar categoría...</option>
                      {filtrosDisponibles.categorias.map(c => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>
                </div>
              )}

              {nuevoOffset.tipo === 'subcategoria' && (
                <div className={styles.formRow}>
                  <div style={{ flex: 1 }}>
                    <label>Subcategoría:</label>
                    <select
                      value={nuevoOffset.valor}
                      onChange={e => setNuevoOffset({ ...nuevoOffset, valor: e.target.value })}
                    >
                      <option value="">Seleccionar subcategoría...</option>
                      {filtrosDisponibles.subcategorias.map(s => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                </div>
              )}

              {nuevoOffset.tipo === 'producto' && !editandoOffset && (
                <>
                  {productosOffsetSeleccionados.length > 0 && (
                    <div className={styles.productosSeleccionados}>
                      {productosOffsetSeleccionados.map(p => (
                        <div key={p.item_id} className={styles.productoChip}>
                          <span>{p.codigo}</span>
                          <button onClick={() => quitarProductoOffset(p.item_id)}>×</button>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className={styles.productoBusqueda}>
                    <input
                      type="text"
                      placeholder="Buscar producto por código o descripción..."
                      value={busquedaOffsetProducto}
                      onChange={(e) => setBusquedaOffsetProducto(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && buscarProductosOffset()}
                    />
                    <button
                      onClick={buscarProductosOffset}
                      disabled={busquedaOffsetProducto.length < 2 || buscandoProductosOffset}
                      className={styles.btnBuscar}
                    >
                      {buscandoProductosOffset ? '...' : 'Buscar'}
                    </button>
                  </div>
                  {productosOffsetEncontrados.length > 0 && (
                    <div className={styles.productosResultados}>
                      {productosOffsetEncontrados.map(producto => {
                        const seleccionado = productosOffsetSeleccionados.some(p => p.item_id === producto.item_id);
                        return (
                          <div
                            key={producto.item_id}
                            className={styles.productoItem}
                            onClick={() => seleccionado ? quitarProductoOffset(producto.item_id) : agregarProductoOffset(producto)}
                          >
                            <input type="checkbox" checked={seleccionado} readOnly />
                            <div className={styles.productoInfo}>
                              <span className={styles.productoCodigo}>{producto.codigo}</span>
                              <span className={styles.productoNombre}>{producto.descripcion}</span>
                              <span className={styles.productoMarca}>{producto.marca}</span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </>
              )}

              {/* Monto o Porcentaje según tipo */}
              {nuevoOffset.tipo_offset === 'porcentaje_costo' ? (
                <div className={styles.formRow}>
                  <div>
                    <label>Porcentaje (%):</label>
                    <input
                      type="number"
                      step="0.1"
                      placeholder="Ej: 3"
                      value={nuevoOffset.porcentaje}
                      onChange={e => setNuevoOffset({ ...nuevoOffset, porcentaje: e.target.value })}
                    />
                  </div>
                </div>
              ) : nuevoOffset.tipo_offset === 'monto_por_unidad' ? (
                <div className={styles.formRow}>
                  <div>
                    <label>Monto por unidad:</label>
                    <input
                      type="number"
                      placeholder="Ej: 20"
                      value={nuevoOffset.monto}
                      onChange={e => setNuevoOffset({ ...nuevoOffset, monto: e.target.value })}
                    />
                  </div>
                  <div>
                    <label>Moneda:</label>
                    <select
                      value={nuevoOffset.moneda}
                      onChange={e => setNuevoOffset({ ...nuevoOffset, moneda: e.target.value })}
                    >
                      <option value="ARS">ARS</option>
                      <option value="USD">USD</option>
                    </select>
                  </div>
                  {nuevoOffset.moneda === 'USD' && (
                    <div>
                      <label>Tipo Cambio:</label>
                      <input
                        type="number"
                        value={nuevoOffset.tipo_cambio}
                        onChange={e => setNuevoOffset({ ...nuevoOffset, tipo_cambio: e.target.value })}
                      />
                    </div>
                  )}
                </div>
              ) : (
                <div className={styles.formRow}>
                  <div>
                    <label>Monto Total ($):</label>
                    <input
                      type="number"
                      placeholder="Ej: 100000"
                      value={nuevoOffset.monto}
                      onChange={e => setNuevoOffset({ ...nuevoOffset, monto: e.target.value })}
                    />
                  </div>
                </div>
              )}

              {/* Descripción */}
              <div className={styles.formRow}>
                <div style={{ flex: 1 }}>
                  <label>Descripción:</label>
                  <input
                    type="text"
                    placeholder="Ej: Rebate Q4 2024"
                    value={nuevoOffset.descripcion}
                    onChange={e => setNuevoOffset({ ...nuevoOffset, descripcion: e.target.value })}
                  />
                </div>
              </div>

              {/* Fechas */}
              <div className={styles.formRow}>
                <div>
                  <label>Desde:</label>
                  <input
                    type="date"
                    value={nuevoOffset.fecha_desde}
                    onChange={e => setNuevoOffset({ ...nuevoOffset, fecha_desde: e.target.value })}
                  />
                </div>
                <div>
                  <label>Hasta (opcional):</label>
                  <input
                    type="date"
                    value={nuevoOffset.fecha_hasta}
                    onChange={e => setNuevoOffset({ ...nuevoOffset, fecha_hasta: e.target.value })}
                  />
                </div>
              </div>

              <div className={styles.formRow}>
                <button onClick={guardarOffset} className={styles.btnGuardar}>
                  {editandoOffset ? 'Actualizar' : 'Guardar'} Offset
                </button>
                {editandoOffset && (
                  <button onClick={resetearFormOffset} className={styles.btnCancelar}>
                    Cancelar
                  </button>
                )}
              </div>
            </div>

            <div className={styles.offsetsLista}>
              <h4>Offsets existentes</h4>
              {offsets.length === 0 ? (
                <p>No hay offsets configurados</p>
              ) : (
                <table className={styles.offsetsTable}>
                  <thead>
                    <tr>
                      <th>Nivel</th>
                      <th>Valor</th>
                      <th>Tipo</th>
                      <th>Monto/Valor</th>
                      <th>Descripción</th>
                      <th>Período</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {offsets.map(offset => (
                      <tr key={offset.id} className={editandoOffset === offset.id ? styles.editando : ''}>
                        <td>
                          {offset.item_id ? 'Producto' :
                           offset.subcategoria_id ? 'Subcategoría' :
                           offset.categoria ? 'Categoría' : 'Marca'}
                        </td>
                        <td>
                          {offset.item_id || offset.subcategoria_id || offset.categoria || offset.marca}
                        </td>
                        <td>
                          {offset.tipo_offset === 'porcentaje_costo' ? '% Costo' :
                           offset.tipo_offset === 'monto_por_unidad' ? 'Por Unidad' : 'Fijo'}
                        </td>
                        <td>
                          {offset.tipo_offset === 'porcentaje_costo'
                            ? `${offset.porcentaje}%`
                            : offset.tipo_offset === 'monto_por_unidad'
                              ? `${offset.moneda === 'USD' ? 'USD ' : '$'}${offset.monto}`
                              : formatMoney(offset.monto)
                          }
                        </td>
                        <td>{offset.descripcion}</td>
                        <td>
                          {formatFecha(offset.fecha_desde)}
                          {offset.fecha_hasta ? ` a ${formatFecha(offset.fecha_hasta)}` : '+'}
                        </td>
                        <td>
                          <button
                            onClick={() => editarOffset(offset)}
                            className={styles.btnEditar}
                            title="Editar"
                          >
                            ✏️
                          </button>
                          <button
                            onClick={() => eliminarOffset(offset.id)}
                            className={styles.btnEliminar}
                            title="Eliminar"
                          >
                            🗑️
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <button onClick={() => { setMostrarModalOffset(false); resetearFormOffset(); }} className={styles.btnCerrar}>
              Cerrar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
