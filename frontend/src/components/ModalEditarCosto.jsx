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

export default function ModalEditarCosto({
  mostrar,
  onClose,
  onSave,
  operacion // La operación a editar
}) {
  const [costoUnitario, setCostoUnitario] = useState('');
  const [monedaCosto, setMonedaCosto] = useState('ARS'); // ARS o USD
  const [guardando, setGuardando] = useState(false);

  // Tipo de cambio
  const [tipoCambio, setTipoCambio] = useState('');
  const [tipoCambioOriginal, setTipoCambioOriginal] = useState(null);
  const [fechaTipoCambio, setFechaTipoCambio] = useState(null);

  // Búsqueda de productos en ERP
  const [busquedaProducto, setBusquedaProducto] = useState('');
  const [productosEncontrados, setProductosEncontrados] = useState([]);
  const [buscandoProductos, setBuscandoProductos] = useState(false);

  // Múltiples productos seleccionados
  const [productosSeleccionados, setProductosSeleccionados] = useState([]);

  useEffect(() => {
    if (mostrar && operacion) {
      // Si la operación ya tiene costo, pre-cargar
      if (operacion.costo_unitario && operacion.costo_unitario > 0) {
        setCostoUnitario(operacion.costo_unitario.toString());
      } else {
        setCostoUnitario('');
      }
      setMonedaCosto('ARS');
      setProductosSeleccionados([]);
      setProductosEncontrados([]);
      setBusquedaProducto('');
      setTipoCambio('');
      setTipoCambioOriginal(null);
      setFechaTipoCambio(null);

      // Cargar tipo de cambio de la fecha de la operación
      if (operacion.fecha) {
        cargarTipoCambioFecha(operacion.fecha);
      }
    }
  }, [mostrar, operacion]);

  const cargarTipoCambioFecha = async (fecha) => {
    try {
      // Extraer solo la fecha (YYYY-MM-DD)
      const fechaStr = fecha.split('T')[0];
      const response = await api.get(`/api/tipo-cambio/fecha/${fechaStr}`);
      if (response.data.venta) {
        setTipoCambio(response.data.venta.toString());
        setTipoCambioOriginal(response.data.venta);
        setFechaTipoCambio(response.data.fecha);
      }
    } catch (error) {
      console.error('Error cargando tipo de cambio:', error);
      // Fallback: cargar TC actual
      try {
        const response = await api.get('/api/tipo-cambio/actual');
        if (response.data.venta) {
          setTipoCambio(response.data.venta.toString());
          setTipoCambioOriginal(response.data.venta);
          setFechaTipoCambio(response.data.fecha);
        }
      } catch (err) {
        console.error('Error cargando TC actual:', err);
      }
    }
  };

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

  const agregarProducto = (producto) => {
    // Verificar si ya está agregado
    if (productosSeleccionados.find(p => p.item_id === producto.item_id)) {
      return;
    }

    const nuevoProducto = {
      ...producto,
      cantidad: 1 // Cantidad por defecto
    };

    const nuevosProductos = [...productosSeleccionados, nuevoProducto];
    setProductosSeleccionados(nuevosProductos);

    // Recalcular costo total
    recalcularCostoTotal(nuevosProductos);

    setProductosEncontrados([]);
    setBusquedaProducto('');
  };

  const quitarProducto = (itemId) => {
    const nuevosProductos = productosSeleccionados.filter(p => p.item_id !== itemId);
    setProductosSeleccionados(nuevosProductos);
    recalcularCostoTotal(nuevosProductos);
  };

  const cambiarCantidadProducto = (itemId, nuevaCantidad) => {
    const cantidad = parseInt(nuevaCantidad) || 1;
    const nuevosProductos = productosSeleccionados.map(p =>
      p.item_id === itemId ? { ...p, cantidad } : p
    );
    setProductosSeleccionados(nuevosProductos);
    recalcularCostoTotal(nuevosProductos);
  };

  const recalcularCostoTotal = (productos) => {
    if (productos.length === 0) {
      setCostoUnitario('');
      setMonedaCosto('ARS');
      return;
    }

    const tc = parseFloat(tipoCambio) || 1;
    let costoTotalARS = 0;
    let hayUSD = false;

    for (const p of productos) {
      if (p.costo_unitario && p.costo_unitario > 0) {
        const costoProducto = p.costo_unitario * p.cantidad;
        if (p.moneda_costo === 'USD') {
          hayUSD = true;
          costoTotalARS += costoProducto * tc;
        } else {
          costoTotalARS += costoProducto;
        }
      }
    }

    // Siempre mostrar en ARS si hay mezcla o conversión
    setCostoUnitario(costoTotalARS.toFixed(2));
    setMonedaCosto('ARS');
  };

  // Recalcular cuando cambia el TC
  useEffect(() => {
    if (productosSeleccionados.length > 0) {
      recalcularCostoTotal(productosSeleccionados);
    }
  }, [tipoCambio]);

  // Calcular costo en ARS para guardar
  const getCostoEnARS = () => {
    if (!costoUnitario || parseFloat(costoUnitario) <= 0) return 0;
    const costo = parseFloat(costoUnitario);
    const tc = parseFloat(tipoCambio) || 0;
    if (monedaCosto === 'USD' && tc > 0) {
      return costo * tc;
    }
    return costo;
  };

  const guardarCosto = async () => {
    const costoARS = getCostoEnARS();
    if (costoARS <= 0) {
      alert('Debe ingresar un costo válido mayor a 0');
      return;
    }

    if (monedaCosto === 'USD' && (!tipoCambio || parseFloat(tipoCambio) <= 0)) {
      alert('Debe ingresar un tipo de cambio válido para convertir USD a ARS');
      return;
    }

    setGuardando(true);
    try {
      await api.put(`/api/ventas-fuera-ml/metricas/${operacion.metrica_id}/costo`, {
        costo_unitario: costoARS
      });

      if (onSave) onSave();
      onClose();
    } catch (error) {
      console.error('Error guardando costo:', error);
      alert('Error al guardar el costo');
    } finally {
      setGuardando(false);
    }
  };

  const formatMoney = (valor, moneda = 'ARS') => {
    if (valor === null || valor === undefined) return '$0';
    const prefix = moneda === 'USD' ? 'U$S ' : '$ ';
    return prefix + new Intl.NumberFormat('es-AR', {
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(valor);
  };

  if (!mostrar || !operacion) return null;

  const cantidad = operacion.cantidad || 1;
  const costoUnitarioARS = getCostoEnARS();
  const costoTotal = costoUnitarioARS * cantidad;
  const montoTotal = operacion.precio_final_sin_iva || 0;
  const gananciaPreview = montoTotal - costoTotal;
  const markupPreview = costoTotal > 0 ? ((montoTotal / costoTotal) - 1) * 100 : null;

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()} style={{ maxWidth: '700px' }}>
        <h3>Editar Costo de Operacion</h3>

        {/* Info de la operación */}
        <div className={styles.offsetForm} style={{ marginBottom: '1rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', fontSize: '0.9rem' }}>
            <div><strong>Codigo:</strong> {operacion.codigo_item || '-'}</div>
            <div><strong>Fecha:</strong> {operacion.fecha ? new Date(operacion.fecha).toLocaleDateString('es-AR') : '-'}</div>
            <div style={{ gridColumn: '1 / -1' }}><strong>Descripcion:</strong> {operacion.descripcion || '-'}</div>
            <div><strong>Cantidad:</strong> {cantidad}</div>
            <div><strong>Precio Unit:</strong> {formatMoney(operacion.precio_unitario_sin_iva)}</div>
            <div><strong>Total s/IVA:</strong> {formatMoney(montoTotal)}</div>
            <div><strong>Costo Actual:</strong> {operacion.costo_pesos_sin_iva > 0 ? formatMoney(operacion.costo_pesos_sin_iva) : <span style={{ color: '#ef4444' }}>Sin costo</span>}</div>
          </div>
        </div>

        {/* Buscar producto para traer costo */}
        <div className={styles.offsetForm}>
          <h4>Buscar productos para componer costo</h4>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
            Busca uno o mas productos para sumar sus costos (productos compuestos)
          </p>

          <div className={styles.productoBusqueda}>
            <input
              type="text"
              placeholder="Buscar producto por codigo o descripcion..."
              value={busquedaProducto}
              onChange={(e) => setBusquedaProducto(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && buscarProductos()}
            />
            <button
              onClick={buscarProductos}
              disabled={busquedaProducto.length < 2 || buscandoProductos}
              className={styles.btnBuscar}
            >
              {buscandoProductos ? '...' : 'Buscar'}
            </button>
          </div>

          {productosEncontrados.length > 0 && (
            <div className={styles.productosResultados}>
              {productosEncontrados.map(producto => (
                <div
                  key={producto.item_id}
                  className={styles.productoItem}
                  onClick={() => agregarProducto(producto)}
                  style={{ cursor: 'pointer' }}
                >
                  <div className={styles.productoInfo}>
                    <span className={styles.productoCodigo}>{producto.codigo}</span>
                    <span className={styles.productoNombre}>{producto.descripcion}</span>
                    <span className={styles.productoMarca}>
                      {producto.costo_unitario > 0
                        ? `Costo: ${producto.moneda_costo === 'USD' ? 'U$S' : '$'} ${producto.costo_unitario?.toFixed(2)}`
                        : 'Sin costo'}
                    </span>
                  </div>
                  <span style={{ color: '#3b82f6', fontSize: '1.2rem', marginLeft: '0.5rem' }}>+</span>
                </div>
              ))}
            </div>
          )}

          {/* Lista de productos seleccionados */}
          {productosSeleccionados.length > 0 && (
            <div style={{
              marginTop: '0.75rem',
              border: '1px solid var(--border-color)',
              borderRadius: '6px',
              overflow: 'hidden'
            }}>
              <div style={{
                background: 'var(--bg-tertiary)',
                padding: '0.5rem 0.75rem',
                fontWeight: 600,
                fontSize: '0.85rem',
                borderBottom: '1px solid var(--border-color)'
              }}>
                Productos seleccionados ({productosSeleccionados.length})
              </div>
              {productosSeleccionados.map(producto => {
                const tc = parseFloat(tipoCambio) || 1;
                const costoEnARS = producto.moneda_costo === 'USD'
                  ? (producto.costo_unitario || 0) * tc
                  : (producto.costo_unitario || 0);
                const subtotal = costoEnARS * producto.cantidad;

                return (
                  <div
                    key={producto.item_id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      padding: '0.5rem 0.75rem',
                      borderBottom: '1px solid var(--border-color)',
                      gap: '0.5rem',
                      fontSize: '0.85rem'
                    }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {producto.codigo}
                      </div>
                      <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {producto.descripcion?.substring(0, 50)}
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Cant:</span>
                      <input
                        type="number"
                        min="1"
                        value={producto.cantidad}
                        onChange={(e) => cambiarCantidadProducto(producto.item_id, e.target.value)}
                        style={{
                          width: '50px',
                          padding: '0.25rem',
                          textAlign: 'center',
                          border: '1px solid var(--border-color)',
                          borderRadius: '4px'
                        }}
                      />
                    </div>
                    <div style={{ minWidth: '80px', textAlign: 'right' }}>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                        {producto.moneda_costo === 'USD' ? `U$S ${producto.costo_unitario?.toFixed(2)}` : `$ ${producto.costo_unitario?.toFixed(0)}`}
                      </div>
                      <div style={{ fontWeight: 500, color: '#059669' }}>
                        {formatMoney(subtotal)}
                      </div>
                    </div>
                    <button
                      onClick={() => quitarProducto(producto.item_id)}
                      style={{
                        background: '#fee2e2',
                        border: 'none',
                        borderRadius: '4px',
                        padding: '0.25rem 0.5rem',
                        cursor: 'pointer',
                        color: '#dc2626',
                        fontSize: '0.8rem'
                      }}
                      title="Quitar producto"
                    >
                      X
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {/* Input de costo manual con selector de moneda */}
          <div className={styles.formRow} style={{ marginTop: '1rem' }}>
            <div style={{ flex: 2 }}>
              <label>Costo Unitario Total:</label>
              <input
                type="number"
                step="0.01"
                min="0"
                placeholder={monedaCosto === 'USD' ? 'Ej: 150' : 'Ej: 150000'}
                value={costoUnitario}
                onChange={e => setCostoUnitario(e.target.value)}
                style={{ fontSize: '1.1rem', padding: '0.5rem' }}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label>Moneda:</label>
              <select
                value={monedaCosto}
                onChange={e => setMonedaCosto(e.target.value)}
                style={{ fontSize: '1.1rem', padding: '0.5rem', width: '100%' }}
                disabled={productosSeleccionados.length > 0}
              >
                <option value="ARS">ARS ($)</option>
                <option value="USD">USD (U$S)</option>
              </select>
            </div>
          </div>

          {/* Tipo de cambio editable - mostrar siempre si hay productos USD o si moneda es USD */}
          {(monedaCosto === 'USD' || productosSeleccionados.some(p => p.moneda_costo === 'USD')) && (
            <div className={styles.formRow} style={{ marginTop: '0.75rem' }}>
              <div style={{ flex: 1 }}>
                <label>
                  Tipo de Cambio (USD/ARS):
                  {fechaTipoCambio && (
                    <span style={{ fontWeight: 'normal', marginLeft: '0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                      (TC del {new Date(fechaTipoCambio).toLocaleDateString('es-AR')})
                    </span>
                  )}
                </label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  placeholder="Ej: 1050"
                  value={tipoCambio}
                  onChange={e => setTipoCambio(e.target.value)}
                  style={{ fontSize: '1.1rem', padding: '0.5rem' }}
                />
              </div>
              {tipoCambioOriginal && tipoCambio !== tipoCambioOriginal.toString() && (
                <div style={{ flex: 0, alignSelf: 'flex-end', marginBottom: '0.25rem' }}>
                  <button
                    type="button"
                    onClick={() => setTipoCambio(tipoCambioOriginal.toString())}
                    style={{
                      padding: '0.5rem 0.75rem',
                      fontSize: '0.8rem',
                      background: 'var(--bg-tertiary)',
                      border: '1px solid var(--border-color)',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      color: 'var(--text-secondary)'
                    }}
                    title="Restaurar TC original"
                  >
                    Restaurar
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Mostrar conversión si es USD */}
          {monedaCosto === 'USD' && costoUnitario && parseFloat(costoUnitario) > 0 && tipoCambio && parseFloat(tipoCambio) > 0 && (
            <p style={{ fontSize: '0.85rem', color: '#3b82f6', marginTop: '0.5rem', fontWeight: 500 }}>
              U$S {parseFloat(costoUnitario).toFixed(2)} x ${parseFloat(tipoCambio).toFixed(2)} = {formatMoney(costoUnitarioARS)}
            </p>
          )}

          {/* Preview de cálculos */}
          {costoUnitario && parseFloat(costoUnitario) > 0 && (monedaCosto === 'ARS' || (monedaCosto === 'USD' && tipoCambio && parseFloat(tipoCambio) > 0)) && (
            <div style={{
              marginTop: '1rem',
              padding: '1rem',
              background: gananciaPreview >= 0 ? '#d1fae5' : '#fee2e2',
              borderRadius: '8px',
              border: gananciaPreview >= 0 ? '1px solid #10b981' : '1px solid #ef4444'
            }}>
              <h4 style={{ margin: '0 0 0.5rem 0', color: '#1f2937' }}>Vista previa:</h4>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', fontSize: '0.9rem', color: '#374151' }}>
                <div><strong>Costo Unit (ARS):</strong> {formatMoney(costoUnitarioARS)}</div>
                <div><strong>Costo Total:</strong> {formatMoney(costoTotal)}</div>
                <div>
                  <strong>Ganancia:</strong>{' '}
                  <span style={{ color: gananciaPreview >= 0 ? '#059669' : '#dc2626', fontWeight: 'bold' }}>
                    {formatMoney(gananciaPreview)}
                  </span>
                </div>
                <div>
                  <strong>Markup:</strong>{' '}
                  <span style={{ color: markupPreview !== null && markupPreview >= 0 ? '#059669' : '#dc2626', fontWeight: 'bold' }}>
                    {markupPreview !== null ? `${markupPreview.toFixed(1)}%` : '-'}
                  </span>
                </div>
              </div>
            </div>
          )}

          <div className={styles.formRow} style={{ marginTop: '1rem' }}>
            <button
              onClick={guardarCosto}
              disabled={guardando || !costoUnitario || parseFloat(costoUnitario) <= 0 || (monedaCosto === 'USD' && (!tipoCambio || parseFloat(tipoCambio) <= 0))}
              className={styles.btnGuardar}
            >
              {guardando ? 'Guardando...' : 'Guardar Costo'}
            </button>
            <button onClick={onClose} className={styles.btnCancelar}>
              Cancelar
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
