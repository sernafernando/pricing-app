import { useState } from 'react';
import { X } from 'lucide-react';
import useComprasPedidos from '../../hooks/useComprasPedidos';
import ProveedorComprasAutocomplete from './ProveedorComprasAutocomplete';
import styles from './ModalPedidoCompra.module.css';

/**
 * ModalPedidoCompra — form de alta/edición de pedidos de compra.
 *
 * Props:
 *   pedido   — `null` (nuevo) o el objeto existente (editar).
 *   empresas — `[{id, nombre}]` para el select.
 *   onClose  — `(reload: boolean) => void` — true si se guardó y hay que recargar.
 *
 * IMPORTANTE: NO cierra con click en overlay. Solo X button o Cancelar.
 */
export default function ModalPedidoCompra({ pedido, empresas, onClose }) {
  const pedidosApi = useComprasPedidos();
  const esEdicion = !!pedido;

  const [form, setForm] = useState({
    empresa_id: pedido?.empresa_id ? String(pedido.empresa_id) : '',
    proveedor_id: pedido?.proveedor_id ? String(pedido.proveedor_id) : '',
    moneda: pedido?.moneda || 'ARS',
    monto: pedido?.monto ? String(pedido.monto) : '',
    fecha_pago_texto: pedido?.fecha_pago_texto || '',
    fecha_pago_estimada: pedido?.fecha_pago_estimada || '',
    requiere_envio: pedido?.requiere_envio || false,
    numero_factura: pedido?.numero_factura || '',
  });

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const handleChange = (campo, valor) => {
    setForm((f) => ({ ...f, [campo]: valor }));
  };

  const validar = () => {
    if (!form.empresa_id) return 'Empresa requerida.';
    if (!form.proveedor_id) return 'Proveedor requerido.';
    const monto = parseFloat(form.monto);
    if (!Number.isFinite(monto) || monto <= 0) return 'El monto debe ser mayor a 0.';
    if (!['ARS', 'USD'].includes(form.moneda)) return 'Moneda inválida (ARS o USD).';
    return null;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const validationError = validar();
    if (validationError) {
      setError(validationError);
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const payload = {
        empresa_id: Number(form.empresa_id),
        proveedor_id: Number(form.proveedor_id),
        moneda: form.moneda,
        monto: parseFloat(form.monto),
        fecha_pago_texto: form.fecha_pago_texto || null,
        fecha_pago_estimada: form.fecha_pago_estimada || null,
        requiere_envio: form.requiere_envio,
        numero_factura: form.numero_factura || null,
      };

      if (esEdicion) {
        await pedidosApi.editar(pedido.id, payload);
      } else {
        await pedidosApi.crear(payload);
      }
      onClose(true);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al guardar el pedido.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>
            {esEdicion ? `Editar pedido ${pedido.numero}` : 'Nuevo pedido'}
          </span>
          <button
            className={styles.modalCloseBtn}
            onClick={() => onClose(false)}
            aria-label="Cerrar"
            type="button"
          >
            <X size={18} />
          </button>
        </div>

        {error && <div className={styles.errorBanner}>{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Empresa *</label>
            <select
              className={styles.select}
              value={form.empresa_id}
              onChange={(e) => handleChange('empresa_id', e.target.value)}
              required
            >
              <option value="">Seleccionar...</option>
              {empresas.map((emp) => (
                <option key={emp.id} value={emp.id}>
                  {emp.nombre}
                </option>
              ))}
            </select>
          </div>

          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Proveedor *</label>
            <ProveedorComprasAutocomplete
              value={form.proveedor_id ? Number(form.proveedor_id) : null}
              onChange={(id) => handleChange('proveedor_id', id ? String(id) : '')}
              disabled={saving}
            />
          </div>

          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Moneda *</label>
              <select
                className={styles.select}
                value={form.moneda}
                onChange={(e) => handleChange('moneda', e.target.value)}
              >
                <option value="ARS">ARS</option>
                <option value="USD">USD</option>
              </select>
            </div>

            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Monto *</label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                className={styles.input}
                value={form.monto}
                onChange={(e) => handleChange('monto', e.target.value)}
                placeholder="0.00"
                required
              />
            </div>
          </div>

          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Fecha pago (texto libre)</label>
            <input
              type="text"
              className={styles.input}
              value={form.fecha_pago_texto}
              onChange={(e) => handleChange('fecha_pago_texto', e.target.value)}
              placeholder="Ej: 30 días fecha factura"
              maxLength={200}
            />
          </div>

          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Fecha pago estimada</label>
            <input
              type="date"
              className={styles.input}
              value={form.fecha_pago_estimada}
              onChange={(e) => handleChange('fecha_pago_estimada', e.target.value)}
            />
          </div>

          <div className={styles.formGroup}>
            <label className={styles.checkboxLabel}>
              <input
                type="checkbox"
                checked={form.requiere_envio}
                onChange={(e) => handleChange('requiere_envio', e.target.checked)}
              />
              <span>Requiere envío (retiro proveedor)</span>
            </label>
          </div>

          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Número de factura (opcional)</label>
            <input
              type="text"
              className={styles.input}
              value={form.numero_factura}
              onChange={(e) => handleChange('numero_factura', e.target.value)}
              placeholder="FA-00012345"
              maxLength={50}
            />
          </div>

          <div className={styles.formActions}>
            <button
              type="button"
              className={styles.btnSecondary}
              onClick={() => onClose(false)}
              disabled={saving}
            >
              Cancelar
            </button>
            <button type="submit" className={styles.btnSuccess} disabled={saving}>
              {saving ? 'Guardando...' : esEdicion ? 'Guardar cambios' : 'Crear pedido'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
