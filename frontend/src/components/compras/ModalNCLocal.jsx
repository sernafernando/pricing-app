import { useState } from 'react';
import { X } from 'lucide-react';
import useNCsLocales from '../../hooks/useNCsLocales';
import ProveedorComprasAutocomplete from './ProveedorComprasAutocomplete';
import styles from './ModalNCLocal.module.css';

/**
 * ModalNCLocal — form de alta / edición de NCs locales (compras v2).
 *
 * Props:
 *   nc       — `null` (creación) o el objeto NC existente (edición).
 *              Edición solo habilitada si nc.estado === 'borrador'.
 *   empresas — `[{id, nombre}]` para el select.
 *   onClose  — `(reload: boolean) => void` — true si se guardó y hay que recargar.
 *
 * IMPORTANTE: NO cierra con click en overlay. Solo X o Cancelar.
 */
export default function ModalNCLocal({ nc, empresas, onClose, proveedorInicial = null }) {
  const { crear, editar } = useNCsLocales();
  const esEdicion = !!nc;
  const puedeEditar = !esEdicion || nc?.estado === 'borrador';

  const todayIso = () => {
    const d = new Date();
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  };

  // Sub-batch 5.E: si viene proveedorInicial (desde tab CC), pre-cargamos
  // el proveedor. Ignorado si ya hay `nc` (modo edición).
  const [form, setForm] = useState({
    empresa_id: nc?.empresa_id ? String(nc.empresa_id) : '',
    proveedor_id: nc?.proveedor_id
      ? String(nc.proveedor_id)
      : proveedorInicial?.id
        ? String(proveedorInicial.id)
        : '',
    // F2 — ND/NC type: 'credito' (HABER, default) or 'debito' (DEBE, Nota de Débito).
    tipo: nc?.tipo || 'credito',
    moneda: nc?.moneda || 'ARS',
    monto: nc?.monto ? String(nc.monto) : '',
    tipo_cambio: nc?.tipo_cambio ? String(nc.tipo_cambio) : '',
    fecha_emision: nc?.fecha_emision
      ? String(nc.fecha_emision).split('T')[0]
      : todayIso(),
    numero_nc_proveedor: nc?.numero_nc_proveedor || '',
    motivo: nc?.motivo || '',
    observaciones: nc?.observaciones || '',
  });

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const handleChange = (campo, valor) => {
    setForm((f) => ({ ...f, [campo]: valor }));
  };

  const validar = () => {
    if (!form.empresa_id) return 'Empresa requerida.';
    if (!form.proveedor_id) return 'Proveedor requerido.';
    if (!['ARS', 'USD'].includes(form.moneda)) return 'Moneda inválida (ARS o USD).';
    const monto = parseFloat(form.monto);
    if (!Number.isFinite(monto) || monto <= 0) return 'El monto debe ser mayor a 0.';
    if (!form.fecha_emision) return 'Fecha de emisión requerida.';
    if (!form.motivo.trim()) return 'Motivo requerido.';

    // TC solo aplica a USD. Si ARS y viene cargado → error.
    if (form.moneda === 'ARS' && form.tipo_cambio !== '' && form.tipo_cambio !== null) {
      return 'El tipo de cambio solo aplica a moneda USD.';
    }
    if (form.moneda === 'USD' && form.tipo_cambio !== '' && form.tipo_cambio !== null) {
      const tc = parseFloat(form.tipo_cambio);
      if (!Number.isFinite(tc) || tc <= 0) return 'El tipo de cambio debe ser mayor a 0.';
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
      const tcNum =
        form.moneda === 'USD' && form.tipo_cambio !== '' && form.tipo_cambio !== null
          ? parseFloat(form.tipo_cambio)
          : null;

      const payload = {
        empresa_id: Number(form.empresa_id),
        proveedor_id: Number(form.proveedor_id),
        // F2 — tipo is immutable after creation; edición ignores it (handled below).
        tipo: form.tipo,
        moneda: form.moneda,
        monto: parseFloat(form.monto),
        tipo_cambio: tcNum,
        fecha_emision: form.fecha_emision,
        numero_nc_proveedor: form.numero_nc_proveedor.trim() || null,
        motivo: form.motivo.trim(),
        observaciones: form.observaciones.trim() || null,
      };

      if (esEdicion) {
        // El backend PUT ignores empresa_id, proveedor_id, tipo (immutable fields).
        const updatePayload = { ...payload };
        delete updatePayload.empresa_id;
        delete updatePayload.proveedor_id;
        delete updatePayload.tipo;
        await editar(nc.id, updatePayload);
      } else {
        await crear(payload);
      }
      onClose(true);
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        'Error al guardar la NC.';
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>
            {esEdicion
              ? `Editar ${nc.tipo === 'debito' ? 'ND' : 'NC'} ${nc.numero}`
              : form.tipo === 'debito'
                ? 'Nueva Nota de Débito (ND)'
                : 'Nueva Nota de Crédito (NC)'}
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

        {esEdicion && !puedeEditar && (
          <div className={styles.warningBanner}>
            Esta NC está en estado <strong>{nc.estado}</strong> y no se puede
            editar. Los campos son de solo lectura.
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Empresa *</label>
            <select
              className={styles.select}
              value={form.empresa_id}
              onChange={(e) => handleChange('empresa_id', e.target.value)}
              disabled={esEdicion || saving}
              required
            >
              <option value="">Seleccionar...</option>
              {empresas.map((emp) => (
                <option key={emp.id} value={emp.id}>
                  {emp.nombre}
                </option>
              ))}
              {/* En edición, si empresas viene vacío (abierto desde detalle),
                  agregamos una option fantasma para que el select muestre algo. */}
              {esEdicion &&
                form.empresa_id &&
                !empresas.some((e) => String(e.id) === form.empresa_id) && (
                  <option value={form.empresa_id}>
                    {nc?.empresa_nombre || `Empresa #${form.empresa_id}`}
                  </option>
                )}
            </select>
          </div>

          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Proveedor *</label>
            <ProveedorComprasAutocomplete
              value={form.proveedor_id ? Number(form.proveedor_id) : null}
              onChange={(id) => handleChange('proveedor_id', id ? String(id) : '')}
              disabled={esEdicion || saving}
            />
          </div>

          {/* F2 — tipo selector: NC (credito) or ND (debito). Immutable after creation. */}
          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Tipo</label>
            <select
              className={styles.select}
              value={form.tipo}
              onChange={(e) => handleChange('tipo', e.target.value)}
              disabled={esEdicion || saving}
            >
              <option value="credito">Nota de Crédito (NC) — reduce deuda</option>
              <option value="debito">Nota de Débito (ND) — aumenta deuda</option>
            </select>
          </div>

          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Moneda *</label>
              <select
                className={styles.select}
                value={form.moneda}
                onChange={(e) => handleChange('moneda', e.target.value)}
                disabled={!puedeEditar || saving}
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
                disabled={!puedeEditar || saving}
                required
              />
            </div>
          </div>

          {form.moneda === 'USD' && (
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>
                Tipo de cambio{' '}
                <span className={styles.labelHint}>(ARS por 1 USD)</span>
              </label>
              <input
                type="number"
                step="0.0001"
                min="0"
                className={styles.input}
                value={form.tipo_cambio}
                onChange={(e) => handleChange('tipo_cambio', e.target.value)}
                placeholder="Ej: 1150.50 — dejar vacío para usar TC del día"
                disabled={!puedeEditar || saving}
              />
              <div className={styles.labelHint}>
                Si se deja vacío, al guardar se toma el TC del día (venta BNA).
              </div>
            </div>
          )}

          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Fecha emisión *</label>
              <input
                type="date"
                className={styles.input}
                value={form.fecha_emision}
                onChange={(e) => handleChange('fecha_emision', e.target.value)}
                disabled={!puedeEditar || saving}
                required
              />
            </div>

            <div className={styles.formGroup}>
              <label className={styles.formLabel}>
                Nro NC proveedor{' '}
                <span className={styles.labelHint}>(opcional)</span>
              </label>
              <input
                type="text"
                className={styles.input}
                value={form.numero_nc_proveedor}
                onChange={(e) => handleChange('numero_nc_proveedor', e.target.value)}
                placeholder="NC-A-0001-00000042"
                maxLength={50}
                disabled={!puedeEditar || saving}
              />
            </div>
          </div>

          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Motivo *</label>
            <textarea
              className={styles.textarea}
              value={form.motivo}
              onChange={(e) => handleChange('motivo', e.target.value)}
              placeholder="Ej: devolución de mercadería dañada, bonificación por volumen, ajuste TC..."
              rows={3}
              disabled={!puedeEditar || saving}
              required
            />
          </div>

          <div className={styles.formGroup}>
            <label className={styles.formLabel}>
              Observaciones <span className={styles.labelHint}>(opcional)</span>
            </label>
            <textarea
              className={styles.textarea}
              value={form.observaciones}
              onChange={(e) => handleChange('observaciones', e.target.value)}
              placeholder="Notas internas..."
              rows={2}
              disabled={!puedeEditar || saving}
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
            {puedeEditar && (
              <button type="submit" className={styles.btnSuccess} disabled={saving}>
                {saving ? 'Guardando...' : esEdicion ? 'Guardar cambios' : 'Crear NC'}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
