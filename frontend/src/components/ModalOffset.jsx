import { useState, useEffect } from 'react';
import axios from 'axios';
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

export default function ModalOffset({
  mostrar,
  onClose,
  onSave,
  filtrosDisponibles,
  fechaDesde,
  fechaHasta,
  apiBasePath = '/api/rentabilidad' // Para buscar productos
}) {
  const [offsets, setOffsets] = useState([]);
  const [grupos, setGrupos] = useState([]);
  const [tipoCambioHoy, setTipoCambioHoy] = useState(null);
  const [editandoOffset, setEditandoOffset] = useState(null);

  // Búsquedas para productos
  const [busquedaOffsetProducto, setBusquedaOffsetProducto] = useState('');
  const [productosOffsetEncontrados, setProductosOffsetEncontrados] = useState([]);
  const [productosOffsetSeleccionados, setProductosOffsetSeleccionados] = useState([]);
  const [buscandoProductosOffset, setBuscandoProductosOffset] = useState(false);

  // Crear nuevo grupo
  const [mostrarFormGrupo, setMostrarFormGrupo] = useState(false);
  const [nuevoGrupoNombre, setNuevoGrupoNombre] = useState('');

  // Filtros de grupo
  const [filtrosGrupo, setFiltrosGrupo] = useState([]);
  const [nuevoFiltro, setNuevoFiltro] = useState({ marca: '', categoria: '', subcategoria_id: '', item_id: '' });
  const [busquedaFiltroProducto, setBusquedaFiltroProducto] = useState('');
  const [productosFiltroEncontrados, setProductosFiltroEncontrados] = useState([]);
  const [buscandoFiltroProducto, setBuscandoFiltroProducto] = useState(false);

  // Opciones de filtro con relaciones (para filtros cascada)
  const [opcionesFiltro, setOpcionesFiltro] = useState({
    marcas: [],
    categorias: [],
    subcategorias: [],
    categorias_por_marca: {},
    subcategorias_por_categoria: {},
    marcas_por_categoria: {}
  });

  const [nuevoOffset, setNuevoOffset] = useState({
    modo: 'individual', // 'individual' o 'grupo'
    tipo: 'marca',
    valor: '',
    tipo_offset: 'monto_fijo',
    monto: '',
    moneda: 'ARS',
    tipo_cambio: '',
    porcentaje: '',
    descripcion: '',
    fecha_desde: '',
    fecha_hasta: '',
    grupo_id: '',
    max_unidades: '',
    max_monto_usd: '',
    aplica_ml: true,
    aplica_fuera: true,
    aplica_tienda_nube: true
  });

  useEffect(() => {
    if (mostrar) {
      cargarOffsets();
      cargarGrupos();
      cargarOpcionesFiltro();
    }
  }, [mostrar]);

  const cargarOpcionesFiltro = async () => {
    try {
      const response = await api.get('/api/offset-filtros-opciones');
      setOpcionesFiltro(response.data);
    } catch (error) {
      console.error('Error cargando opciones de filtro:', error);
    }
  };

  const cargarOffsets = async () => {
    try {
      const [offsetsRes, tcRes] = await Promise.all([
        api.get('/api/offsets-ganancia'),
        api.get('/api/tipo-cambio/actual')
      ]);
      setOffsets(offsetsRes.data);
      if (tcRes.data.venta) {
        setTipoCambioHoy(tcRes.data.venta);
        setNuevoOffset(prev => ({ ...prev, tipo_cambio: tcRes.data.venta.toString() }));
      }
    } catch (error) {
      console.error('Error cargando offsets:', error);
    }
  };

  const cargarGrupos = async () => {
    try {
      const response = await api.get('/api/offset-grupos');
      setGrupos(response.data);
    } catch (error) {
      console.error('Error cargando grupos:', error);
    }
  };

  const crearGrupo = async () => {
    if (!nuevoGrupoNombre.trim()) return;
    try {
      await api.post('/api/offset-grupos', { nombre: nuevoGrupoNombre.trim() });
      setNuevoGrupoNombre('');
      setMostrarFormGrupo(false);
      await cargarGrupos();
    } catch (error) {
      console.error('Error creando grupo:', error);
      alert('Error al crear el grupo');
    }
  };

  const eliminarGrupo = async (grupoId) => {
    if (!confirm('¿Eliminar este grupo?')) return;
    try {
      await api.delete(`/api/offset-grupos/${grupoId}`);
      // Limpiar selección si era el grupo seleccionado
      if (nuevoOffset.grupo_id === grupoId.toString()) {
        setNuevoOffset({ ...nuevoOffset, grupo_id: '' });
        setFiltrosGrupo([]);
      }
      await cargarGrupos();
    } catch (error) {
      console.error('Error eliminando grupo:', error);
      alert(error.response?.data?.detail || 'Error al eliminar el grupo');
    }
  };

  // Funciones para filtros de grupo
  const cargarFiltrosGrupo = async (grupoId) => {
    if (!grupoId) {
      setFiltrosGrupo([]);
      return;
    }
    try {
      const response = await api.get(`/api/offset-grupos/${grupoId}/filtros`);
      setFiltrosGrupo(response.data);
    } catch (error) {
      console.error('Error cargando filtros:', error);
    }
  };

  const agregarFiltroGrupo = async () => {
    if (!nuevoOffset.grupo_id) {
      alert('Seleccione un grupo primero');
      return;
    }
    const filtro = {};
    // Solo agregar campos con valor, convirtiendo IDs a enteros
    if (nuevoFiltro.marca) filtro.marca = nuevoFiltro.marca;
    if (nuevoFiltro.categoria) filtro.categoria = nuevoFiltro.categoria;
    if (nuevoFiltro.subcategoria_id) filtro.subcategoria_id = parseInt(nuevoFiltro.subcategoria_id);
    if (nuevoFiltro.item_id) filtro.item_id = parseInt(nuevoFiltro.item_id);

    if (Object.keys(filtro).length === 0) {
      alert('Debe especificar al menos un campo para el filtro');
      return;
    }

    try {
      await api.post(`/api/offset-grupos/${nuevoOffset.grupo_id}/filtros`, filtro);
      setNuevoFiltro({ marca: '', categoria: '', subcategoria_id: '', item_id: '' });
      setBusquedaFiltroProducto('');
      setProductosFiltroEncontrados([]);
      await cargarFiltrosGrupo(nuevoOffset.grupo_id);
      await cargarGrupos();
    } catch (error) {
      console.error('Error agregando filtro:', error);
      alert(error.response?.data?.detail || 'Error al agregar el filtro');
    }
  };

  const eliminarFiltroGrupo = async (filtroId) => {
    try {
      await api.delete(`/api/offset-grupos/${nuevoOffset.grupo_id}/filtros/${filtroId}`);
      await cargarFiltrosGrupo(nuevoOffset.grupo_id);
      await cargarGrupos();
    } catch (error) {
      console.error('Error eliminando filtro:', error);
    }
  };

  const buscarProductoFiltro = async () => {
    if (busquedaFiltroProducto.length < 2) return;
    setBuscandoFiltroProducto(true);
    try {
      const response = await api.get('/api/buscar-productos-erp', {
        params: { q: busquedaFiltroProducto }
      });
      setProductosFiltroEncontrados(response.data);
    } catch (error) {
      console.error('Error buscando productos:', error);
    } finally {
      setBuscandoFiltroProducto(false);
    }
  };

  const seleccionarProductoFiltro = (producto) => {
    setNuevoFiltro({ ...nuevoFiltro, item_id: producto.item_id });
    setBusquedaFiltroProducto(producto.codigo + ' - ' + producto.descripcion);
    setProductosFiltroEncontrados([]);
  };

  const buscarProductosOffset = async () => {
    if (busquedaOffsetProducto.length < 2) return;
    setBuscandoProductosOffset(true);
    try {
      // Usar endpoint genérico que busca en todos los productos del ERP
      const response = await api.get('/api/buscar-productos-erp', {
        params: { q: busquedaOffsetProducto }
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
      modo: 'individual',
      tipo: 'marca',
      valor: '',
      tipo_offset: 'monto_fijo',
      monto: '',
      moneda: 'ARS',
      tipo_cambio: tipoCambioHoy ? tipoCambioHoy.toString() : '',
      porcentaje: '',
      descripcion: '',
      fecha_desde: '',
      fecha_hasta: '',
      grupo_id: '',
      max_unidades: '',
      max_monto_usd: '',
      aplica_ml: true,
      aplica_fuera: true,
      aplica_tienda_nube: true
    });
    setProductosOffsetSeleccionados([]);
    setProductosOffsetEncontrados([]);
    setBusquedaOffsetProducto('');
    setEditandoOffset(null);
    setMostrarFormGrupo(false);
    setFiltrosGrupo([]);
    setNuevoFiltro({ marca: '', categoria: '', subcategoria_id: '', item_id: '' });
    setBusquedaFiltroProducto('');
    setProductosFiltroEncontrados([]);
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

  const formatFecha = (fecha) => {
    if (!fecha) return '';
    const [year, month, day] = fecha.split('-');
    return `${day}/${month}/${year}`;
  };

  const guardarOffset = async () => {
    try {
      const payload = {
        tipo_offset: nuevoOffset.tipo_offset,
        descripcion: nuevoOffset.descripcion,
        fecha_desde: nuevoOffset.fecha_desde,
        fecha_hasta: nuevoOffset.fecha_hasta || null
      };

      // Configurar según tipo de offset
      if (nuevoOffset.tipo_offset === 'porcentaje_costo') {
        const porcentajeValue = parseFloat(nuevoOffset.porcentaje);
        if (isNaN(porcentajeValue)) {
          alert('Debe ingresar un porcentaje válido');
          return;
        }
        payload.porcentaje = porcentajeValue;
      } else {
        payload.monto = parseFloat(nuevoOffset.monto);
        payload.moneda = nuevoOffset.moneda;
        if (nuevoOffset.moneda === 'USD') {
          payload.tipo_cambio = parseFloat(nuevoOffset.tipo_cambio);
        }
      }

      // Campos de grupo y límites
      if (nuevoOffset.grupo_id) {
        payload.grupo_id = parseInt(nuevoOffset.grupo_id);
      }
      if (nuevoOffset.max_unidades) {
        payload.max_unidades = parseInt(nuevoOffset.max_unidades);
      }
      if (nuevoOffset.max_monto_usd) {
        payload.max_monto_usd = parseFloat(nuevoOffset.max_monto_usd);
      }

      // Canales de aplicación
      payload.aplica_ml = nuevoOffset.aplica_ml;
      payload.aplica_fuera = nuevoOffset.aplica_fuera;
      payload.aplica_tienda_nube = nuevoOffset.aplica_tienda_nube;

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

      if (editandoOffset) {
        await api.put(`/api/offsets-ganancia/${editandoOffset}`, payload);
      } else {
        await api.post('/api/offsets-ganancia', payload);
      }

      resetearFormOffset();
      cargarOffsets();
      if (onSave) onSave();
    } catch (error) {
      console.error('Error guardando offset:', error);
      alert('Error al guardar el offset');
    }
  };

  const editarOffset = (offset) => {
    setEditandoOffset(offset.id);
    cargarOffsetEnForm(offset);
  };

  const clonarOffset = (offset) => {
    setEditandoOffset(null); // No estamos editando, es nuevo
    cargarOffsetEnForm(offset);
  };

  const cargarOffsetEnForm = (offset) => {
    // Si tiene grupo_id, es modo grupo
    const tieneGrupo = !!offset.grupo_id;
    setNuevoOffset({
      modo: tieneGrupo ? 'grupo' : 'individual',
      tipo: offset.item_id ? 'producto' : offset.subcategoria_id ? 'subcategoria' : offset.categoria ? 'categoria' : 'marca',
      valor: offset.item_id?.toString() || offset.subcategoria_id?.toString() || offset.categoria || offset.marca || '',
      tipo_offset: offset.tipo_offset || 'monto_fijo',
      monto: offset.monto?.toString() || '',
      moneda: offset.moneda || 'ARS',
      tipo_cambio: offset.tipo_cambio?.toString() || (tipoCambioHoy ? tipoCambioHoy.toString() : ''),
      porcentaje: offset.porcentaje?.toString() || '',
      descripcion: offset.descripcion || '',
      fecha_desde: offset.fecha_desde || '',
      fecha_hasta: offset.fecha_hasta || '',
      grupo_id: offset.grupo_id?.toString() || '',
      max_unidades: offset.max_unidades?.toString() || '',
      max_monto_usd: offset.max_monto_usd?.toString() || '',
      aplica_ml: offset.aplica_ml !== false,
      aplica_fuera: offset.aplica_fuera !== false,
      aplica_tienda_nube: offset.aplica_tienda_nube !== false
    });
  };

  const eliminarOffset = async (id) => {
    if (!confirm('¿Eliminar este offset?')) return;
    try {
      await api.delete(`/api/offsets-ganancia/${id}`);
      cargarOffsets();
      if (onSave) onSave();
    } catch (error) {
      console.error('Error eliminando offset:', error);
    }
  };

  const handleClose = () => {
    resetearFormOffset();
    onClose();
  };

  // Cerrar con ESC
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && mostrar) {
        handleClose();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [mostrar]);

  if (!mostrar) return null;

  const esGrupo = nuevoOffset.modo === 'grupo';

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modal}>
        <button className={styles.modalCloseBtn} onClick={handleClose} title="Cerrar (ESC)">&times;</button>
        <h3>Gestionar Offsets de Ganancia</h3>
        <p className={styles.tcActual}>
          TC actual: {tipoCambioHoy ? `$${tipoCambioHoy.toFixed(2)}` : 'Cargando...'}
        </p>

        <div className={styles.offsetForm}>
          <h4>{editandoOffset ? 'Editar Offset' : 'Nuevo Offset'}</h4>

          {/* Modo: Individual o Grupo */}
          <div className={styles.formRow}>
            <div>
              <label>Modo:</label>
              <select
                value={nuevoOffset.modo}
                onChange={e => {
                  const newModo = e.target.value;
                  setNuevoOffset({
                    ...nuevoOffset,
                    modo: newModo,
                    tipo: newModo === 'grupo' ? 'producto' : nuevoOffset.tipo,
                    grupo_id: ''
                  });
                  if (newModo === 'individual') {
                    setProductosOffsetSeleccionados([]);
                  }
                }}
                disabled={editandoOffset}
              >
                <option value="individual">Individual</option>
                <option value="grupo">Grupo de productos</option>
              </select>
            </div>
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
          </div>

          {/* Aplicar a (solo en modo individual) */}
          {!esGrupo && (
            <div className={styles.formRow}>
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
                  <option value="categoria">Categoria</option>
                  <option value="subcategoria">Subcategoria</option>
                  <option value="producto">Producto(s)</option>
                </select>
              </div>
            </div>
          )}

          {/* Selector segun tipo (solo modo individual) */}
          {!esGrupo && nuevoOffset.tipo === 'marca' && (
            <div className={styles.formRow}>
              <div>
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

          {!esGrupo && nuevoOffset.tipo === 'categoria' && (
            <div className={styles.formRow}>
              <div>
                <label>Categoria:</label>
                <select
                  value={nuevoOffset.valor}
                  onChange={e => setNuevoOffset({ ...nuevoOffset, valor: e.target.value })}
                >
                  <option value="">Seleccionar categoria...</option>
                  {filtrosDisponibles.categorias.map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {!esGrupo && nuevoOffset.tipo === 'subcategoria' && (
            <div className={styles.formRow}>
              <div>
                <label>Subcategoria:</label>
                <select
                  value={nuevoOffset.valor}
                  onChange={e => setNuevoOffset({ ...nuevoOffset, valor: e.target.value })}
                >
                  <option value="">Seleccionar subcategoria...</option>
                  {filtrosDisponibles.subcategorias.map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {/* Busqueda de productos: solo modo individual con tipo producto */}
          {!esGrupo && nuevoOffset.tipo === 'producto' && !editandoOffset && (
            <>
              {productosOffsetSeleccionados.length > 0 && (
                <div className={styles.productosSeleccionados}>
                  {productosOffsetSeleccionados.map(p => (
                    <div key={p.item_id} className={styles.productoChip}>
                      <span>{p.codigo}</span>
                      <button onClick={() => quitarProductoOffset(p.item_id)}>x</button>
                    </div>
                  ))}
                </div>
              )}
              <div className={styles.productoBusqueda}>
                <input
                  type="text"
                  placeholder="Buscar producto por codigo o descripcion..."
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

          {/* Monto o Porcentaje segun tipo */}
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
          ) : (
            <div className={styles.formRow}>
              <div>
                <label>{nuevoOffset.tipo_offset === 'monto_por_unidad' ? 'Monto por unidad:' : 'Monto Total:'}</label>
                <input
                  type="number"
                  placeholder={nuevoOffset.tipo_offset === 'monto_por_unidad' ? 'Ej: 20' : 'Ej: 100000'}
                  value={nuevoOffset.monto}
                  onChange={e => setNuevoOffset({ ...nuevoOffset, monto: e.target.value })}
                />
              </div>
              <div>
                <label>Moneda:</label>
                <select
                  value={nuevoOffset.moneda}
                  onChange={e => {
                    const newMoneda = e.target.value;
                    setNuevoOffset({
                      ...nuevoOffset,
                      moneda: newMoneda,
                      tipo_cambio: newMoneda === 'USD' && tipoCambioHoy ? tipoCambioHoy.toString() : nuevoOffset.tipo_cambio
                    });
                  }}
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
          )}

          {/* Seleccion de grupo (modo grupo) */}
          {esGrupo && (
            <>
              <div className={styles.formRowHighlight}>
                <div>
                  <label>Grupo:</label>
                  <div className={styles.grupoSelector}>
                    <select
                      value={nuevoOffset.grupo_id}
                      onChange={e => {
                        const grupoId = e.target.value;
                        setNuevoOffset({ ...nuevoOffset, grupo_id: grupoId });
                        cargarFiltrosGrupo(grupoId);
                      }}
                    >
                      <option value="">Seleccionar o crear grupo...</option>
                      {grupos.map(g => (
                        <option key={g.id} value={g.id}>{g.nombre} {g.filtros?.length > 0 ? `(${g.filtros.length} filtros)` : ''}</option>
                      ))}
                    </select>
                    {nuevoOffset.grupo_id && (
                      <button
                        type="button"
                        onClick={() => eliminarGrupo(parseInt(nuevoOffset.grupo_id))}
                        className={styles.btnEliminarGrupo}
                        title="Eliminar grupo seleccionado"
                      >
                        🗑️
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setMostrarFormGrupo(!mostrarFormGrupo)}
                      className={styles.btnBuscar}
                      title="Crear nuevo grupo"
                    >
                      +
                    </button>
                  </div>
                </div>
              </div>

              {mostrarFormGrupo && (
                <div className={styles.formRowBlue}>
                  <div>
                    <label>Nombre del nuevo grupo:</label>
                    <input
                      type="text"
                      placeholder="Ej: Rebate ASUS Q4"
                      value={nuevoGrupoNombre}
                      onChange={e => setNuevoGrupoNombre(e.target.value)}
                    />
                  </div>
                  <div className={styles.grupoSelector}>
                    <button onClick={crearGrupo} className={styles.btnGuardar}>
                      Crear
                    </button>
                    <button onClick={() => setMostrarFormGrupo(false)} className={styles.btnCancelar}>
                      X
                    </button>
                  </div>
                </div>
              )}

              {/* Filtros del grupo */}
              {nuevoOffset.grupo_id && (
                <div className={styles.filtrosGrupoContainer}>
                  <h5>Filtros del grupo (el offset aplica a ventas que coincidan con AL MENOS un filtro):</h5>

                  {/* Filtros existentes */}
                  {filtrosGrupo.length > 0 && (
                    <div className={styles.filtrosExistentes}>
                      {filtrosGrupo.map(f => (
                        <div key={f.id} className={styles.filtroItem}>
                          <span>
                            {f.marca && <span className={`${styles.filtroTag} ${styles.filtroTagMarca}`}>Marca: {f.marca}</span>}
                            {f.categoria && <span className={`${styles.filtroTag} ${styles.filtroTagCategoria}`}>Cat: {f.categoria}</span>}
                            {f.subcategoria_id && <span className={`${styles.filtroTag} ${styles.filtroTagSubcat}`}>Subcat: {f.subcategoria_nombre || f.subcategoria_id}</span>}
                            {f.item_id && <span className={`${styles.filtroTag} ${styles.filtroTagProducto}`}>Producto: {f.producto_descripcion || f.item_id}</span>}
                          </span>
                          <button
                            onClick={() => eliminarFiltroGrupo(f.id)}
                            className={styles.filtroDeleteBtn}
                          >
                            x
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Agregar nuevo filtro con cascada */}
                  <div className={styles.agregarFiltroRow}>
                    <div className={styles.filtroField}>
                      <label>Marca:</label>
                      <select
                        value={nuevoFiltro.marca}
                        onChange={e => {
                          const marca = e.target.value;
                          // Si cambia la marca, verificar si la categoría sigue siendo válida
                          let nuevaCategoria = nuevoFiltro.categoria;
                          if (marca && nuevaCategoria) {
                            const categoriasValidas = opcionesFiltro.categorias_por_marca[marca] || [];
                            if (!categoriasValidas.includes(nuevaCategoria)) {
                              nuevaCategoria = '';
                            }
                          }
                          setNuevoFiltro({ ...nuevoFiltro, marca, categoria: nuevaCategoria, subcategoria_id: '' });
                        }}
                      >
                        <option value="">-</option>
                        {(() => {
                          // Si hay categoría seleccionada, filtrar marcas por esa categoría
                          const marcasDisponibles = nuevoFiltro.categoria
                            ? (opcionesFiltro.marcas_por_categoria[nuevoFiltro.categoria] || [])
                            : opcionesFiltro.marcas;
                          return marcasDisponibles.map(m => (
                            <option key={m} value={m}>{m}</option>
                          ));
                        })()}
                      </select>
                    </div>
                    <div className={styles.filtroField}>
                      <label>Categoría:</label>
                      <select
                        value={nuevoFiltro.categoria}
                        onChange={e => {
                          const categoria = e.target.value;
                          // Si cambia la categoría, verificar si la marca sigue siendo válida
                          let nuevaMarca = nuevoFiltro.marca;
                          if (categoria && nuevaMarca) {
                            const marcasValidas = opcionesFiltro.marcas_por_categoria[categoria] || [];
                            if (!marcasValidas.includes(nuevaMarca)) {
                              nuevaMarca = '';
                            }
                          }
                          setNuevoFiltro({ ...nuevoFiltro, categoria, marca: nuevaMarca, subcategoria_id: '' });
                        }}
                      >
                        <option value="">-</option>
                        {(() => {
                          // Si hay marca seleccionada, filtrar categorías por esa marca
                          const categoriasDisponibles = nuevoFiltro.marca
                            ? (opcionesFiltro.categorias_por_marca[nuevoFiltro.marca] || [])
                            : opcionesFiltro.categorias;
                          return categoriasDisponibles.map(c => (
                            <option key={c} value={c}>{c}</option>
                          ));
                        })()}
                      </select>
                    </div>
                    <div className={styles.filtroField}>
                      <label>Subcategoría:</label>
                      <select
                        value={nuevoFiltro.subcategoria_id}
                        onChange={e => setNuevoFiltro({ ...nuevoFiltro, subcategoria_id: e.target.value })}
                        disabled={!nuevoFiltro.categoria}
                      >
                        <option value="">-</option>
                        {(() => {
                          // Solo mostrar subcategorías de la categoría seleccionada
                          if (!nuevoFiltro.categoria) return null;
                          const subcatIds = opcionesFiltro.subcategorias_por_categoria[nuevoFiltro.categoria] || [];
                          return opcionesFiltro.subcategorias
                            .filter(s => subcatIds.includes(s.id))
                            .map(s => (
                              <option key={s.id} value={s.id}>{s.nombre}</option>
                            ));
                        })()}
                      </select>
                    </div>
                    <div className={`${styles.filtroField} ${styles.filtroFieldProducto}`}>
                      <label>Producto:</label>
                      <div className={styles.filtroSearchRow}>
                        <input
                          type="text"
                          placeholder="Buscar..."
                          value={busquedaFiltroProducto}
                          onChange={e => {
                            setBusquedaFiltroProducto(e.target.value);
                            if (e.target.value.length < 2) {
                              setNuevoFiltro({ ...nuevoFiltro, item_id: '' });
                            }
                          }}
                          onKeyDown={e => e.key === 'Enter' && buscarProductoFiltro()}
                        />
                        <button onClick={buscarProductoFiltro} disabled={buscandoFiltroProducto}>
                          {buscandoFiltroProducto ? '...' : '🔍'}
                        </button>
                      </div>
                      {productosFiltroEncontrados.length > 0 && (
                        <div className={styles.filtroSearchResults}>
                          {productosFiltroEncontrados.map(p => (
                            <div
                              key={p.item_id}
                              onClick={() => seleccionarProductoFiltro(p)}
                              className={styles.filtroSearchItem}
                            >
                              <strong>{p.codigo}</strong> - {p.descripcion}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    <button
                      onClick={agregarFiltroGrupo}
                      className={styles.btnAgregarFiltro}
                    >
                      + Agregar
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

          {/* Limites (solo para monto_por_unidad) */}
          {nuevoOffset.tipo_offset === 'monto_por_unidad' && (
            <div className={styles.formRowHighlight}>
              <div>
                <label>Max. Unidades:</label>
                <input
                  type="number"
                  placeholder="Ej: 200"
                  value={nuevoOffset.max_unidades}
                  onChange={e => setNuevoOffset({ ...nuevoOffset, max_unidades: e.target.value })}
                />
              </div>
              <div>
                <label>Max. Monto USD:</label>
                <input
                  type="number"
                  placeholder="Ej: 2000"
                  value={nuevoOffset.max_monto_usd}
                  onChange={e => setNuevoOffset({ ...nuevoOffset, max_monto_usd: e.target.value })}
                />
              </div>
              {esGrupo && (
                <p className={styles.limitesHint}>
                  Los limites aplican al grupo completo
                </p>
              )}
            </div>
          )}

          {/* Descripcion */}
          <div className={styles.formRow}>
            <div>
              <label>Descripcion:</label>
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

          {/* Canales de aplicacion */}
          <div className={styles.formRowHighlight}>
            <div className={styles.checkboxRow}>
              <label className={styles.checkboxLabel}>
                <input
                  type="checkbox"
                  checked={nuevoOffset.aplica_ml}
                  onChange={e => setNuevoOffset({ ...nuevoOffset, aplica_ml: e.target.checked })}
                />
                Aplica en Metricas ML
              </label>
              <label className={styles.checkboxLabel}>
                <input
                  type="checkbox"
                  checked={nuevoOffset.aplica_fuera}
                  onChange={e => setNuevoOffset({ ...nuevoOffset, aplica_fuera: e.target.checked })}
                />
                Aplica en Ventas por Fuera
              </label>
              <label className={styles.checkboxLabel}>
                <input
                  type="checkbox"
                  checked={nuevoOffset.aplica_tienda_nube}
                  onChange={e => setNuevoOffset({ ...nuevoOffset, aplica_tienda_nube: e.target.checked })}
                />
                Aplica en Tienda Nube
              </label>
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
                  <th>Aplica a</th>
                  <th>Tipo</th>
                  <th>Offset</th>
                  <th>Descripcion</th>
                  <th>Periodo</th>
                  <th>Canal</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {offsets.map(offset => {
                  const nivel = offset.item_id ? 'Producto' :
                               offset.subcategoria_id ? 'Subcat' :
                               offset.categoria ? 'Cat' : 'Marca';
                  const valor = offset.item_id || offset.subcategoria_id || offset.categoria || offset.marca;

                  const tipoLabel = offset.tipo_offset === 'porcentaje_costo' ? '% Costo' :
                                   offset.tipo_offset === 'monto_por_unidad' ? '$/unidad' : 'Fijo';

                  const montoStr = offset.tipo_offset === 'porcentaje_costo'
                    ? `${offset.porcentaje}%`
                    : `${offset.moneda === 'USD' ? 'U$' : '$'}${offset.monto}`;

                  const canales = [];
                  if (offset.aplica_ml) canales.push('ML');
                  if (offset.aplica_fuera) canales.push('Fuera');
                  if (offset.aplica_tienda_nube) canales.push('TN');
                  const canalStr = canales.length === 3 ? 'Todos' : canales.join(', ') || '-';

                  return (
                    <tr key={offset.id} className={editandoOffset === offset.id ? styles.editando : ''}>
                      <td>
                        <span className={styles.tdSmall}>{nivel}:</span> {valor}
                        {offset.grupo_nombre && <><br/><span className={styles.tdSmall}>Grupo: {offset.grupo_nombre}</span></>}
                      </td>
                      <td className={styles.tdSmall}>{tipoLabel}</td>
                      <td>
                        {montoStr}
                        {offset.max_unidades && <span className={styles.tdSmall}> (max {offset.max_unidades}u)</span>}
                      </td>
                      <td>{offset.descripcion || '-'}</td>
                      <td className={styles.tdSmall}>
                        {formatFecha(offset.fecha_desde)}{offset.fecha_hasta ? ` - ${formatFecha(offset.fecha_hasta)}` : '+'}
                      </td>
                      <td className={styles.tdSmall}>{canalStr}</td>
                      <td className={styles.accionesOffset}>
                        <button onClick={() => clonarOffset(offset)} className={styles.btnClonar} title="Clonar">📋</button>
                        <button onClick={() => editarOffset(offset)} className={styles.btnEditar} title="Editar">✏️</button>
                        <button onClick={() => eliminarOffset(offset.id)} className={styles.btnEliminar} title="Eliminar">🗑️</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Seccion de grupos */}
        {grupos.length > 0 && (
          <div className={`${styles.offsetsLista} ${styles.gruposSeccion}`}>
            <h4>Grupos de Offsets</h4>
            <div className={styles.gruposList}>
              {grupos.map(g => (
                <div key={g.id} className={styles.grupoChip}>
                  <span>{g.nombre}</span>
                  <button
                    onClick={() => eliminarGrupo(g.id)}
                    title="Eliminar grupo"
                  >
                    x
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        <button onClick={handleClose} className={styles.btnCerrar}>
          Cerrar
        </button>
      </div>
    </div>
  );
}
