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

  const [nuevoOffset, setNuevoOffset] = useState({
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
    aplica_fuera: true
  });

  useEffect(() => {
    if (mostrar) {
      cargarOffsets();
      cargarGrupos();
    }
  }, [mostrar]);

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
      await cargarGrupos();
    } catch (error) {
      console.error('Error eliminando grupo:', error);
      alert(error.response?.data?.detail || 'Error al eliminar el grupo');
    }
  };

  const buscarProductosOffset = async () => {
    if (busquedaOffsetProducto.length < 2) return;
    setBuscandoProductosOffset(true);
    try {
      const response = await api.get(`${apiBasePath}/buscar-productos`, {
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
      tipo_cambio: tipoCambioHoy ? tipoCambioHoy.toString() : '',
      porcentaje: '',
      descripcion: '',
      fecha_desde: '',
      fecha_hasta: '',
      grupo_id: '',
      max_unidades: '',
      max_monto_usd: '',
      aplica_ml: true,
      aplica_fuera: true
    });
    setProductosOffsetSeleccionados([]);
    setProductosOffsetEncontrados([]);
    setBusquedaOffsetProducto('');
    setEditandoOffset(null);
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
    setNuevoOffset({
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
      aplica_fuera: offset.aplica_fuera !== false
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

  if (!mostrar) return null;

  const muestraCondiciones = nuevoOffset.tipo_offset === 'monto_por_unidad';

  return (
    <div className={styles.modalOverlay} onClick={handleClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <h3>Gestionar Offsets de Ganancia</h3>
        <p style={{ fontSize: '0.85em', color: '#666', marginBottom: '1rem' }}>
          TC actual: {tipoCambioHoy ? `$${tipoCambioHoy.toFixed(2)}` : 'Cargando...'}
        </p>

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
                <option value="categoria">Categoria</option>
                <option value="subcategoria">Subcategoria</option>
                <option value="producto">Producto(s)</option>
              </select>
            </div>
          </div>

          {/* Selector segun tipo */}
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

          {nuevoOffset.tipo === 'subcategoria' && (
            <div className={styles.formRow}>
              <div style={{ flex: 1 }}>
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

          {nuevoOffset.tipo === 'producto' && !editandoOffset && (
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

          {/* Condiciones para monto_por_unidad */}
          {muestraCondiciones && (
            <>
              <div className={styles.formRow} style={{ backgroundColor: '#f8f9fa', padding: '0.5rem', borderRadius: '4px' }}>
                <div>
                  <label>Grupo (opcional):</label>
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <select
                      value={nuevoOffset.grupo_id}
                      onChange={e => setNuevoOffset({ ...nuevoOffset, grupo_id: e.target.value })}
                      style={{ flex: 1 }}
                    >
                      <option value="">Sin grupo</option>
                      {grupos.map(g => (
                        <option key={g.id} value={g.id}>{g.nombre}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => setMostrarFormGrupo(!mostrarFormGrupo)}
                      className={styles.btnBuscar}
                      style={{ padding: '0.25rem 0.5rem' }}
                    >
                      +
                    </button>
                  </div>
                </div>
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
              </div>

              {mostrarFormGrupo && (
                <div className={styles.formRow} style={{ backgroundColor: '#e3f2fd', padding: '0.5rem', borderRadius: '4px' }}>
                  <div style={{ flex: 1 }}>
                    <label>Nombre del nuevo grupo:</label>
                    <input
                      type="text"
                      placeholder="Ej: Rebate ASUS Q4"
                      value={nuevoGrupoNombre}
                      onChange={e => setNuevoGrupoNombre(e.target.value)}
                    />
                  </div>
                  <div style={{ display: 'flex', alignItems: 'flex-end', gap: '0.25rem' }}>
                    <button onClick={crearGrupo} className={styles.btnGuardar} style={{ padding: '0.5rem' }}>
                      Crear
                    </button>
                    <button onClick={() => setMostrarFormGrupo(false)} className={styles.btnCancelar} style={{ padding: '0.5rem' }}>
                      X
                    </button>
                  </div>
                </div>
              )}

              <p style={{ fontSize: '0.75em', color: '#666', margin: '0.25rem 0' }}>
                Si se asigna grupo, los limites aplican a la suma de todas las ventas del grupo en el periodo.
              </p>
            </>
          )}

          {/* Descripcion */}
          <div className={styles.formRow}>
            <div style={{ flex: 1 }}>
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
          <div className={styles.formRow} style={{ backgroundColor: 'rgba(255,255,255,0.05)', padding: '0.5rem', borderRadius: '4px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={nuevoOffset.aplica_ml}
                  onChange={e => setNuevoOffset({ ...nuevoOffset, aplica_ml: e.target.checked })}
                />
                Aplica en Metricas ML
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={nuevoOffset.aplica_fuera}
                  onChange={e => setNuevoOffset({ ...nuevoOffset, aplica_fuera: e.target.checked })}
                />
                Aplica en Ventas por Fuera
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
                  <th>Nivel</th>
                  <th>Valor</th>
                  <th>Tipo</th>
                  <th>Monto/Valor</th>
                  <th>Aplica</th>
                  <th>Grupo</th>
                  <th>Limites</th>
                  <th>Descripcion</th>
                  <th>Periodo</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {offsets.map(offset => (
                  <tr key={offset.id} className={editandoOffset === offset.id ? styles.editando : ''}>
                    <td>
                      {offset.item_id ? 'Producto' :
                       offset.subcategoria_id ? 'Subcategoria' :
                       offset.categoria ? 'Categoria' : 'Marca'}
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
                        : `${offset.moneda === 'USD' ? 'USD ' : '$'}${offset.monto}`
                      }
                    </td>
                    <td style={{ fontSize: '0.75em' }}>
                      {offset.aplica_ml !== false && 'ML'}
                      {offset.aplica_ml !== false && offset.aplica_fuera !== false && ' / '}
                      {offset.aplica_fuera !== false && 'Fuera'}
                    </td>
                    <td>{offset.grupo_nombre || '-'}</td>
                    <td style={{ fontSize: '0.8em' }}>
                      {offset.max_unidades ? `${offset.max_unidades}u` : ''}
                      {offset.max_unidades && offset.max_monto_usd ? ' / ' : ''}
                      {offset.max_monto_usd ? `$${offset.max_monto_usd}` : ''}
                      {!offset.max_unidades && !offset.max_monto_usd ? '-' : ''}
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

        {/* Seccion de grupos */}
        {grupos.length > 0 && (
          <div className={styles.offsetsLista} style={{ marginTop: '1rem' }}>
            <h4>Grupos de Offsets</h4>
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              {grupos.map(g => (
                <div key={g.id} style={{
                  padding: '0.25rem 0.5rem',
                  backgroundColor: '#e3f2fd',
                  borderRadius: '4px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem'
                }}>
                  <span>{g.nombre}</span>
                  <button
                    onClick={() => eliminarGrupo(g.id)}
                    style={{
                      border: 'none',
                      background: 'none',
                      cursor: 'pointer',
                      color: '#999',
                      fontSize: '0.8em'
                    }}
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
