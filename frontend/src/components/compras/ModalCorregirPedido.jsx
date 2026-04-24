import { useMemo, useState } from 'react';
import { X, AlertTriangle, Info, History } from 'lucide-react';
import useComprasPedidos from '../../hooks/useComprasPedidos';
import styles from './ModalCorregirPedido.module.css';

/**
 * ModalCorregirPedido — crea una versión corregida de un pedido aprobado/
 * pagado_parcial/pagado. La moneda NO se puede cambiar (está deshabilitada
 * con tooltip explicativo). Si cambia el monto o el tipo de cambio el clon
 * nace en `pendiente_aprobacion` (requerirá re-aprobar); si solo cambian
 * campos cosméticos (factura, fechas, envío, observaciones) el clon hereda
 * `aprobado` y la transferencia es inmediata.
 *
 * Props:
 *   pedido   — pedido original (objeto completo con estado, monto, moneda...)
 *   onClose  — `(clon|null) => void`. Si viene `clon`, el padre cierra este
 *              modal, cierra el modal detalle del original y abre el del clon.
 *
 * NO cierra en overlay click (regla del sistema de modales Tesla).
 */
export default function ModalCorregirPedido({ pedido, onClose }) {
  const pedidosApi = useComprasPedidos();

  const [form, setForm] = useState({
    numero_factura: pedido?.numero_factura || '',
    monto: pedido?.monto ? String(pedido.monto) : '',
    tipo_cambio: pedido?.tipo_cambio ? String(pedido.tipo_cambio) : '',
    fecha_pago_texto: pedido?.fecha_pago_texto || '',
    fecha_pago_estimada: pedido?.fecha_pago_estimada || '',
    requiere_envio: pedido?.requiere_envio || false,
    observaciones: pedido?.observaciones || '',
    motivo_correccion: '',
  });

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const handleChange = (campo, valor) => {
    setForm((f) => ({ ...f, [campo]: valor }));
  };

  // ¿Cambió monto o TC respecto al original? Si sí → el clon nace pendiente.
  const cambiosFinancieros = useMemo(() => {
    const montoChg =
      form.monto !== '' &&
      Number(form.monto) !== Number(pedido?.monto);
    const tcChg =
      pedido?.moneda === 'USD' &&
      form.tipo_cambio !== '' &&
      Number(form.tipo_cambio) !== Number(pedido?.tipo_cambio || 0);
    return { monto: montoChg, tipo_cambio: tcChg, any: montoChg || tcChg };
  }, [form.monto, form.tipo_cambio, pedido]);

  const estadoClonPreview = cambiosFinancieros.any
    ? 'pendiente_aprobacion'
    : 'aprobado';

  const validar = () => {
    const motivo = (form.motivo_correccion || '').trim();
    if (motivo.length < 5) {
      return 'El motivo de corrección debe tener al menos 5 caracteres.';
    }
    if (form.monto !== '') {
      const m = parseFloat(form.monto);
      if (!Number.isFinite(m) || m <= 0) {
        return 'El monto debe ser mayor a 0.';
      }
    }
    if (pedido?.moneda === 'USD' && form.tipo_cambio !== '') {
      const tc = parseFloat(form.tipo_cambio);
      if (!Number.isFinite(tc) || tc <= 0) {
        return 'El tipo de cambio debe ser mayor a 0.';
      }
    }
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
      // Enviamos solo los campos que CAMBIARON respecto al original — el
      // backend distingue cosmético vs financiero comparando los valores.
      const payload = { motivo_correccion: form.motivo_correccion.trim() };

      // Comparación estricta por valor (no por referencia). Usamos Number()
      // para monto/TC y string-compare para el resto.
      if (form.numero_factura !== (pedido.numero_factura || '')) {
        payload.numero_factura = form.numero_factura || null;
      }
      if (form.monto !== '' && Number(form.monto) !== Number(pedido.monto)) {
        payload.monto = parseFloat(form.monto);
      }
      if (
        pedido.moneda === 'USD' &&
        form.tipo_cambio !== '' &&
        Number(form.tipo_cambio) !== Number(pedido.tipo_cambio || 0)
      ) {
        payload.tipo_cambio = parseFloat(form.tipo_cambio);
      }
      if (form.fecha_pago_texto !== (pedido.fecha_pago_texto || '')) {
        payload.fecha_pago_texto = form.fecha_pago_texto || null;
      }
      if (form.fecha_pago_estimada !== (pedido.fecha_pago_estimada || '')) {
        payload.fecha_pago_estimada = form.fecha_pago_estimada || null;
      }
      if (form.requiere_envio !== pedido.requiere_envio) {
        payload.requiere_envio = form.requiere_envio;
      }
      if (form.observaciones !== (pedido.observaciones || '')) {
        payload.observaciones = form.observaciones || null;
      }

      const clon = await pedidosApi.corregir(pedido.id, payload);
      onClose(clon);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al corregir el pedido.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>
            <History size={18} />
            Corregir pedido {pedido?.numero}
          </span>
          <button
            className={styles.modalCloseBtn}
            onClick={() => onClose(null)}
            aria-label="Cerrar"
            type="button"
          >
            <X size={18} />
          </button>
        </div>

        {error && <div className={styles.errorBanner}>{error}</div>}

        <div className={styles.contextBanner}>
          <Info size={14} />
          <span>
            Se creará un <strong>nuevo pedido</strong> con los cambios aplicados
            y el actual quedará <strong>cancelado</strong>. Las imputaciones se
            transfieren automáticamente al clon.
          </span>
        </div>

        {cambiosFinancieros.any ? (
          <div className={styles.warningBanner}>
            <AlertTriangle size={14} />
            <span>
              Cambió {cambiosFinancieros.monto && <code>monto</code>}
              {cambiosFinancieros.monto && cambiosFinancieros.tipo_cambio && ' y '}
              {cambiosFinancieros.tipo_cambio && <code>tipo_cambio</code>} — el
              clon nacerá en <strong>pendiente_aprobacion</strong> y requerirá
              re-aprobación antes de aplicarse a la cuenta corriente.
            </span>
          </div>
        ) : (
          <div className={styles.infoGreenBanner}>
            <Info size={14} />
            <span>
              Corrección cosmética (factura / fechas / envío / observaciones) —
              el clon hereda <strong>aprobado</strong> automáticamente.
            </span>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          {/* Moneda no editable */}
          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Moneda</label>
            <input
              type="text"
              className={styles.input}
              value={pedido?.moneda || ''}
              disabled
              title="Para cambiar la moneda, cancelá el pedido y creá uno nuevo."
            />
            <div className={styles.labelHint}>
              La moneda no se puede cambiar al corregir. Para cambiarla, cancelá
              el pedido y creá uno nuevo.
            </div>
          </div>

          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Monto</label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                className={styles.input}
                value={form.monto}
                onChange={(e) => handleChange('monto', e.target.value)}
                placeholder="0.00"
              />
            </div>

            {pedido?.moneda === 'USD' && (
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>
                  Tipo de cambio <span className={styles.labelHint}>(ARS/USD)</span>
                </label>
                <input
                  type="number"
                  step="0.0001"
                  min="0"
                  className={styles.input}
                  value={form.tipo_cambio}
                  onChange={(e) => handleChange('tipo_cambio', e.target.value)}
                  placeholder="Ej: 1250.50"
                />
              </div>
            )}
          </div>

          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Número de factura</label>
            <input
              type="text"
              className={styles.input}
              value={form.numero_factura}
              onChange={(e) => handleChange('numero_factura', e.target.value)}
              placeholder="FA-00012345"
              maxLength={50}
            />
          </div>

          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Fecha pago (texto)</label>
              <input
                type="text"
                className={styles.input}
                value={form.fecha_pago_texto}
                onChange={(e) => handleChange('fecha_pago_texto', e.target.value)}
                placeholder="Ej: 30 días FF"
                maxLength={200}
              />
            </div>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Fecha pago estimada</label>
              <input
                type="date"
                className={styles.input}
                value={form.fecha_pago_estimada}
                onChange={(e) =>
                  handleChange('fecha_pago_estimada', e.target.value)
                }
              />
            </div>
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
            <label className={styles.formLabel}>Observaciones</label>
            <textarea
              className={styles.textarea}
              value={form.observaciones}
              onChange={(e) => handleChange('observaciones', e.target.value)}
              placeholder="Notas, aclaraciones, referencias..."
              rows={3}
            />
          </div>

          <div className={styles.formGroupRequired}>
            <label className={styles.formLabel}>
              Motivo de la corrección <span className={styles.asterisk}>*</span>
            </label>
            <textarea
              className={styles.textarea}
              value={form.motivo_correccion}
              onChange={(e) => handleChange('motivo_correccion', e.target.value)}
              placeholder="Describí por qué se corrige este pedido (mínimo 5 caracteres)..."
              rows={2}
              minLength={5}
              maxLength={500}
              required
            />
            <div className={styles.labelHint}>
              El motivo queda registrado en los eventos de ambos pedidos para
              auditoría.
            </div>
          </div>

          <div className={styles.formActions}>
            <div className={styles.previewEstado}>
              Clon nacerá en: <strong>{estadoClonPreview}</strong>
            </div>
            <button
              type="button"
              className={styles.btnSecondary}
              onClick={() => onClose(null)}
              disabled={saving}
            >
              Cancelar
            </button>
            <button type="submit" className={styles.btnPrimary} disabled={saving}>
              {saving ? 'Creando clon...' : 'Crear versión corregida'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
