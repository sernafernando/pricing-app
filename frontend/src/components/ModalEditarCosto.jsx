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
  const [tipoCambioHoy, setTipoCambioHoy] = useState(null);

  // Búsqueda de productos en ERP
  const [busquedaProducto, setBusquedaProducto] = useState('');
  const [productosEncontrados, setProductosEncontrados] = useState([]);
  const [buscandoProductos, setBuscandoProductos] = useState(false);
  const [productoSeleccionado, setProductoSeleccionado] = useState(null);

  useEffect(() => {
    if (mostrar && operacion) {
      // Si la operación ya tiene costo, pre-cargar
      if (operacion.costo_unitario && operacion.costo_unitario > 0) {
        setCostoUnitario(operacion.costo_unitario.toString());
      } else {
        setCostoUnitario('');
      }
      setMonedaCosto('ARS');
      setProductoSeleccionado(null);
      setProductosEncontrados([]);
      setBusquedaProducto('');

      // Cargar tipo de cambio actual
      cargarTipoCambio();
    }
  }, [mostrar, operacion]);

  const cargarTipoCambio = async () => {
    try {
      const response = await api.get('/api/tipo-cambio/actual');
      if (response.data.venta) {
        setTipoCambioHoy(response.data.venta);
      }
    } catch (error) {
      console.error('Error cargando tipo de cambio:', error);
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

  const seleccionarProducto = (producto) => {
    setProductoSeleccionado(producto);
    // Si el producto tiene costo, usarlo en su moneda original
    if (producto.costo_unitario && producto.costo_unitario > 0) {
      setCostoUnitario(producto.costo_unitario.toFixed(2));
      setMonedaCosto(producto.moneda_costo || 'ARS');
    }
    setProductosEncontrados([]);
    setBusquedaProducto('');
  };

  // Calcular costo en ARS para guardar
  const getCostoEnARS = () => {
    if (!costoUnitario || parseFloat(costoUnitario) <= 0) return 0;
    const costo = parseFloat(costoUnitario);
    if (monedaCosto === 'USD' && tipoCambioHoy) {
      return costo * tipoCambioHoy;
    }
    return costo;
  };

  const guardarCosto = async () => {
    const costoARS = getCostoEnARS();
    if (costoARS <= 0) {
      alert('Debe ingresar un costo válido mayor a 0');
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
      <div className={styles.modal} onClick={e => e.stopPropagation()} style={{ maxWidth: '600px' }}>
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
          <h4>Buscar costo de producto</h4>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
            Busca un producto para traer su costo del sistema
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
                  onClick={() => seleccionarProducto(producto)}
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
                </div>
              ))}
            </div>
          )}

          {productoSeleccionado && (
            <div style={{
              marginTop: '0.5rem',
              padding: '0.5rem',
              background: 'rgba(59, 130, 246, 0.15)',
              borderRadius: '4px',
              fontSize: '0.85rem',
              color: 'var(--text-primary)'
            }}>
              Costo de: <strong>{productoSeleccionado.codigo}</strong> - {productoSeleccionado.descripcion?.substring(0, 40)}
            </div>
          )}

          {/* Input de costo manual con selector de moneda */}
          <div className={styles.formRow} style={{ marginTop: '1rem' }}>
            <div style={{ flex: 2 }}>
              <label>Costo Unitario:</label>
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
              >
                <option value="ARS">ARS ($)</option>
                <option value="USD">USD (U$S)</option>
              </select>
            </div>
          </div>

          {tipoCambioHoy && (
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
              TC actual: <strong>$ {tipoCambioHoy.toFixed(2)}</strong>
              {monedaCosto === 'USD' && costoUnitario && parseFloat(costoUnitario) > 0 && (
                <span style={{ marginLeft: '1rem', color: '#3b82f6' }}>
                  = {formatMoney(costoUnitarioARS)} ARS
                </span>
              )}
            </p>
          )}

          {/* Preview de cálculos */}
          {costoUnitario && parseFloat(costoUnitario) > 0 && (
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
              disabled={guardando || !costoUnitario || parseFloat(costoUnitario) <= 0}
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
