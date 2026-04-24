import { useState } from 'react';
import { Link } from 'react-router-dom';
import { X, AlertTriangle, Plus, Trash2, MinusCircle } from 'lucide-react';
import { useAuthStore } from '../../store/authStore';
import useComprasOP from '../../hooks/useComprasOP';
import ProveedorComprasAutocomplete from './ProveedorComprasAutocomplete';
import styles from './ModalOrdenPagoNueva.module.css';

/**
 * ModalOrdenPagoNueva — crea una OP con flujo anti-doble-contabilización.
 *
 * Piezas clave (design §7.3 + §7.4):
 *
 * 1. BANNER sessionStorage dismissable por día/usuario. Key:
 *    `compras_op_doble_contab_banner_dismissed_${userId}_${YYYYMMDD}`.
 *    TTL natural: sessionStorage se limpia al cerrar tab. Reset diario
 *    porque la key incluye la fecha.
 *
 * 2. SELECTOR de modo imputación: `especifica | a_cuenta | mixta`.
 *    - especifica: suma de items DEBE ser === monto_total.
 *    - a_cuenta: sin items (todo al saldo).
 *    - mixta: suma de items < monto_total (el resto va al saldo).
 *
 * 3. 409 POSIBLE_DUPLICADO_OP_ERP: si el backend responde 409, abrimos
 *    un modal HIJO con la lista de duplicados. "Confirmar, es distinto"
 *    reenvía el POST con `confirmar_duplicado: true` — el form queda
 *    abierto con todos los datos si el usuario cancela.
 *
 * REGLA AGENTS.md: NO cierra con click en overlay. Solo X o Cancelar.
 */

const todayYYYYMMDD = () => {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}${mm}${dd}`;
};

const bannerKeyFor = (userId) =>
  `compras_op_doble_contab_banner_dismissed_${userId}_${todayYYYYMMDD()}`;

const formatCurrency = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const TIPOS_ITEM = [
  { value: 'pedido_compra', label: 'Pedido de compra' },
  { value: 'factura_erp', label: 'Factura ERP' },
];

export default function ModalOrdenPagoNueva({
  empresas,
  onClose,
  pedidoInicial = null,
  pendientesDelProveedor = [],
  op = null,
  opItems = [],
  proveedorInicial = null,
}) {
  const user = useAuthStore((s) => s.user);
  const userId = user?.id || 'anon';
  const opApi = useComprasOP();

  // ── Modo edición ──
  // Si viene `op`, estamos editando una OP pendiente (sub-batch 1.1).
  // `opItems` debe ser la lista de items del último evento items_*
  // leída desde el detalle de la OP (items_editados si existe, sino
  // items_registrados). El componente NO va a la DB a buscarlos.
  const isEditMode = op !== null && op !== undefined;

  // ── Banner anti-doble-contab (solo en creación) ──
  const bannerKey = bannerKeyFor(userId);
  const [bannerDismissed, setBannerDismissed] = useState(
    isEditMode ? true : sessionStorage.getItem(bannerKey) === 'true'
  );

  const dismissBanner = () => {
    sessionStorage.setItem(bannerKey, 'true');
    setBannerDismissed(true);
  };

  // ── Form state ──
  // Prioridad: op (edit) > pedidoInicial (pre-carga) > defaults.
  const saldoInicial = pedidoInicial
    ? Number(pedidoInicial.saldo_pendiente ?? pedidoInicial.monto) || 0
    : 0;

  const [form, setForm] = useState(() => {
    if (isEditMode) {
      return {
        empresa_id: String(op.empresa_id ?? ''),
        proveedor_id: String(op.proveedor_id ?? ''),
        moneda: op.moneda || 'ARS',
        monto_total: String(op.monto_total ?? ''),
        modo_imputacion: op.modo_imputacion || 'a_cuenta',
        observaciones: op.observaciones || '',
      };
    }
    return {
      empresa_id: pedidoInicial
        ? String(pedidoInicial.empresa_id)
        : proveedorInicial?.empresa_id
          ? String(proveedorInicial.empresa_id)
          : '',
      proveedor_id: pedidoInicial
        ? String(pedidoInicial.proveedor_id)
        : proveedorInicial?.id
          ? String(proveedorInicial.id)
          : '',
      moneda: pedidoInicial?.moneda || 'ARS',
      monto_total: pedidoInicial ? String(saldoInicial) : '',
      modo_imputacion: pedidoInicial ? 'especifica' : 'a_cuenta',
      observaciones: pedidoInicial
        ? `Pago imputado a pedido ${pedidoInicial.numero}`
        : '',
    };
  });

  const [items, setItems] = useState(() => {
    if (isEditMode) {
      return (opItems || []).map((it) => ({
        tipo: it.tipo || 'pedido_compra',
        id: it.id !== null && it.id !== undefined ? String(it.id) : '',
        monto: String(it.monto ?? ''),
        numero_factura: it.numero_factura || '',
      }));
    }
    return pedidoInicial
      ? [
          {
            tipo: 'pedido_compra',
            id: String(pedidoInicial.id),
            monto: String(saldoInicial),
            numero_factura: pedidoInicial.numero_factura || '',
          },
        ]
      : [];
  });

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  // ── 409 duplicado flow ──
  const [duplicadoInfo, setDuplicadoInfo] = useState(null);
  const [submittingConfirm, setSubmittingConfirm] = useState(false);

  const requiereItems =
    form.modo_imputacion === 'especifica' || form.modo_imputacion === 'mixta';

  // Pedidos pendientes del proveedor actualmente seleccionado,
  // filtrados por moneda del form (no mezclar ARS/USD en una OP).
  const pedidosDisponibles = pendientesDelProveedor.filter((p) => {
    if (form.proveedor_id && String(p.proveedor_id) !== String(form.proveedor_id)) {
      return false;
    }
    if (form.moneda && p.moneda !== form.moneda) return false;
    return true;
  });

  // IDs de pedidos ya agregados como items (para evitar duplicar al elegir del dropdown).
  const idsPedidosYaAgregados = new Set(
    items
      .filter((it) => it.tipo === 'pedido_compra' && it.id)
      .map((it) => String(it.id))
  );

  const handleChange = (campo, valor) => {
    setForm((f) => {
      const next = { ...f, [campo]: valor };
      // Si cambió a a_cuenta, limpiar items.
      if (campo === 'modo_imputacion' && valor === 'a_cuenta') {
        setItems([]);
      }
      return next;
    });
  };

  const addItem = () => {
    setItems((prev) => [
      ...prev,
      { tipo: 'pedido_compra', id: '', monto: '', numero_factura: '' },
    ]);
  };

  const removeItem = (idx) => {
    setItems((prev) => prev.filter((_, i) => i !== idx));
  };

  const updateItem = (idx, campo, valor) => {
    setItems((prev) =>
      prev.map((it, i) => (i === idx ? { ...it, [campo]: valor } : it))
    );
  };

  // ── Validación ──
  const sumaItems = items.reduce((acc, it) => acc + (parseFloat(it.monto) || 0), 0);
  const montoTotalNum = parseFloat(form.monto_total) || 0;

  const validar = () => {
    if (!form.empresa_id) return 'Empresa requerida.';
    if (!form.proveedor_id) return 'Proveedor requerido.';
    if (!Number.isFinite(montoTotalNum) || montoTotalNum <= 0)
      return 'El monto total debe ser mayor a 0.';
    if (!['ARS', 'USD'].includes(form.moneda)) return 'Moneda inválida.';
    if (!['especifica', 'a_cuenta', 'mixta'].includes(form.modo_imputacion))
      return 'Modo de imputación inválido.';

    if (requiereItems) {
      if (items.length === 0) return 'Agregá al menos un item imputable.';
      for (const [idx, it] of items.entries()) {
        if (!it.tipo || !['pedido_compra', 'factura_erp'].includes(it.tipo))
          return `Item #${idx + 1}: tipo inválido.`;
        if (!it.id) return `Item #${idx + 1}: id requerido.`;
        const m = parseFloat(it.monto);
        if (!Number.isFinite(m) || m <= 0) return `Item #${idx + 1}: monto > 0 requerido.`;
      }
      const sumaRedondeada = Math.round(sumaItems * 100) / 100;
      const totalRedondeado = Math.round(montoTotalNum * 100) / 100;
      if (form.modo_imputacion === 'especifica' && sumaRedondeada !== totalRedondeado) {
        return `En modo específica la suma de items (${sumaRedondeada}) debe ser igual al monto total (${totalRedondeado}).`;
      }
      if (form.modo_imputacion === 'mixta' && sumaRedondeada >= totalRedondeado) {
        return `En modo mixta la suma de items (${sumaRedondeada}) debe ser MENOR al monto total (${totalRedondeado}). El resto va a saldo.`;
      }
    }
    return null;
  };

  const buildPayload = (confirmarDuplicado = false) => ({
    empresa_id: Number(form.empresa_id),
    proveedor_id: Number(form.proveedor_id),
    moneda: form.moneda,
    monto_total: montoTotalNum,
    modo_imputacion: form.modo_imputacion,
    observaciones: form.observaciones || null,
    items: items.map((it) => ({
      tipo: it.tipo,
      id: it.id ? Number(it.id) : null,
      monto: parseFloat(it.monto),
      numero_factura: it.numero_factura || null,
    })),
    confirmar_duplicado: confirmarDuplicado,
  });

  const buildEditPayload = () => ({
    monto_total: montoTotalNum,
    moneda: form.moneda,
    modo_imputacion: form.modo_imputacion,
    observaciones: form.observaciones || null,
    items: items.map((it) => ({
      tipo: it.tipo,
      id: it.id ? Number(it.id) : null,
      monto: parseFloat(it.monto),
      numero_factura: it.numero_factura || null,
    })),
  });

  const handleSubmit = async (e) => {
    e.preventDefault();
    const v = validar();
    if (v) {
      setError(v);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (isEditMode) {
        await opApi.editar(op.id, buildEditPayload());
        onClose(true);
        return;
      }
      await opApi.crear(buildPayload(false));
      onClose(true);
    } catch (err) {
      const res = err.response;
      if (res?.status === 409) {
        // El backend payload puede venir como dict directo O como
        // { error: { code, message } } debido al handler del proyecto.
        const raw = res.data?.detail ?? res.data ?? {};
        const codigo =
          raw.codigo ||
          raw.code ||
          res.data?.error?.code ||
          (typeof raw === 'string' && raw.includes('POSIBLE_DUPLICADO_OP_ERP')
            ? 'POSIBLE_DUPLICADO_OP_ERP'
            : null);
        if (codigo === 'POSIBLE_DUPLICADO_OP_ERP') {
          setDuplicadoInfo({
            mensaje:
              raw.mensaje ||
              'Detectamos en el ERP una OP reciente para este proveedor. Verificá antes de continuar.',
            duplicados: Array.isArray(raw.duplicados_detectados)
              ? raw.duplicados_detectados
              : Array.isArray(raw.duplicados)
              ? raw.duplicados
              : [],
          });
        } else {
          setError(res.data?.detail || 'Conflicto al crear la OP.');
        }
      } else {
        setError(res?.data?.detail || 'Error al crear la OP.');
      }
    } finally {
      setSaving(false);
    }
  };

  const handleConfirmarDuplicado = async () => {
    setSubmittingConfirm(true);
    setError(null);
    try {
      await opApi.crear(buildPayload(true));
      onClose(true);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al crear la OP con confirmación.');
      setDuplicadoInfo(null);
    } finally {
      setSubmittingConfirm(false);
    }
  };

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>
            {isEditMode ? `Editar OP ${op.numero}` : 'Nueva Orden de Pago'}
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

        {/* Banner anti-doble-contabilización */}
        {!bannerDismissed && (
          <div className={styles.banner} role="alert">
            <AlertTriangle size={20} className={styles.bannerIcon} />
            <div className={styles.bannerBody}>
              <strong>Atención:</strong> Si este pago ya se registró directamente en el ERP,
              NO lo cargues acá. Se contabilizaría dos veces.
            </div>
            <button
              type="button"
              className={styles.bannerDismiss}
              onClick={dismissBanner}
            >
              Entendido
            </button>
          </div>
        )}

        {error && <div className={styles.errorBanner}>{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className={styles.formRow}>
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
              <label className={styles.formLabel}>Monto total *</label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                className={styles.input}
                value={form.monto_total}
                onChange={(e) => handleChange('monto_total', e.target.value)}
                placeholder="0.00"
                required
              />
            </div>

            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Modo imputación *</label>
              <select
                className={styles.select}
                value={form.modo_imputacion}
                onChange={(e) => handleChange('modo_imputacion', e.target.value)}
              >
                <option value="a_cuenta">A cuenta</option>
                <option value="especifica">Específica</option>
                <option value="mixta">Mixta</option>
              </select>
            </div>
          </div>

          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Observaciones</label>
            <textarea
              className={styles.textarea}
              value={form.observaciones}
              onChange={(e) => handleChange('observaciones', e.target.value)}
              placeholder="Notas internas..."
              rows={2}
            />
          </div>

          {/* Tabla de items */}
          {requiereItems && (
            <div className={styles.itemsSection}>
              <div className={styles.itemsHeader}>
                <h4 className={styles.itemsTitle}>Items imputados</h4>
                <div className={styles.itemsSummary}>
                  <span>Imputado: {formatCurrency(sumaItems, form.moneda)}</span>
                  <span> / Total: {formatCurrency(montoTotalNum, form.moneda)}</span>
                  <span className={styles.itemsRemanente}>
                    Remanente:{' '}
                    {formatCurrency(Math.max(0, montoTotalNum - sumaItems), form.moneda)}
                  </span>
                </div>
                <button
                  type="button"
                  className={styles.btnPrimary}
                  onClick={addItem}
                >
                  <Plus size={14} /> Agregar
                </button>
              </div>
              {items.length === 0 ? (
                <div className={styles.emptyItems}>
                  Agregá items para imputar el pago a pedidos/facturas específicas.
                </div>
              ) : (
                <div className={styles.itemsTableWrapper}>
                  <table className={styles.itemsTable}>
                    <thead>
                      <tr>
                        <th>Tipo</th>
                        <th>ID</th>
                        <th className={styles.thRight}>Monto</th>
                        <th>N° Factura</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((it, idx) => {
                        // Auto-sugerir monto al elegir pedido del dropdown.
                        const handleSelectPedido = (valorId) => {
                          if (!valorId) {
                            updateItem(idx, 'id', '');
                            return;
                          }
                          const pedido = pendientesDelProveedor.find(
                            (p) => String(p.id) === String(valorId)
                          );
                          setItems((prev) =>
                            prev.map((row, i) =>
                              i === idx
                                ? {
                                    ...row,
                                    id: valorId,
                                    monto: pedido
                                      ? String(pedido.saldo_pendiente ?? pedido.monto)
                                      : row.monto,
                                    numero_factura:
                                      pedido?.numero_factura || row.numero_factura,
                                  }
                                : row
                            )
                          );
                        };
                        return (
                          <tr key={idx}>
                            <td>
                              <select
                                className={styles.selectSmall}
                                value={it.tipo}
                                onChange={(e) => updateItem(idx, 'tipo', e.target.value)}
                              >
                                {TIPOS_ITEM.map((t) => (
                                  <option key={t.value} value={t.value}>
                                    {t.label}
                                  </option>
                                ))}
                              </select>
                            </td>
                            <td>
                              {it.tipo === 'pedido_compra' ? (
                                <select
                                  className={styles.selectSmall}
                                  value={it.id}
                                  onChange={(e) => handleSelectPedido(e.target.value)}
                                >
                                  <option value="">Seleccionar pedido...</option>
                                  {pedidosDisponibles
                                    .filter(
                                      (p) =>
                                        String(p.id) === String(it.id) ||
                                        !idsPedidosYaAgregados.has(String(p.id))
                                    )
                                    .map((p) => (
                                      <option key={p.id} value={p.id}>
                                        {p.numero} — {formatCurrency(
                                          p.saldo_pendiente ?? p.monto,
                                          p.moneda
                                        )}
                                      </option>
                                    ))}
                                </select>
                              ) : (
                                <input
                                  type="number"
                                  className={styles.inputSmall}
                                  value={it.id}
                                  onChange={(e) => updateItem(idx, 'id', e.target.value)}
                                  placeholder="ct_transaction_id"
                                />
                              )}
                            </td>
                            <td>
                              <input
                                type="number"
                                step="0.01"
                                min="0.01"
                                className={styles.inputSmallRight}
                                value={it.monto}
                                onChange={(e) => updateItem(idx, 'monto', e.target.value)}
                                placeholder="0.00"
                              />
                            </td>
                            <td>
                              <input
                                type="text"
                                className={styles.inputSmall}
                                value={it.numero_factura}
                                onChange={(e) =>
                                  updateItem(idx, 'numero_factura', e.target.value)
                                }
                                placeholder="FA-..."
                                maxLength={50}
                              />
                            </td>
                            <td>
                              <button
                                type="button"
                                className={styles.iconBtnDanger}
                                onClick={() => removeItem(idx)}
                                aria-label="Quitar item"
                              >
                                <Trash2 size={12} />
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {form.proveedor_id && (
            <div className={styles.ncsHint}>
              <MinusCircle size={14} />
              <span>
                ¿Tenés una NC del proveedor para aplicar?{' '}
                <Link
                  to={`/administracion/compras?tab=ncs-locales&proveedor_id=${form.proveedor_id}`}
                >
                  Gestionar NCs de este proveedor →
                </Link>
              </span>
            </div>
          )}

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
              {saving
                ? isEditMode
                  ? 'Guardando...'
                  : 'Creando...'
                : isEditMode
                  ? 'Guardar cambios'
                  : 'Crear OP'}
            </button>
          </div>
        </form>

        {/* Modal de confirmación de duplicado (hijo) */}
        {duplicadoInfo && (
          <div className={styles.modalOverlay}>
            <div className={styles.modalContentDup}>
              <div className={styles.modalHeader}>
                <span className={styles.modalTitle}>
                  <AlertTriangle
                    size={18}
                    style={{ verticalAlign: 'middle', marginRight: 6 }}
                  />
                  Posible duplicado detectado
                </span>
                <button
                  className={styles.modalCloseBtn}
                  onClick={() => setDuplicadoInfo(null)}
                  aria-label="Cerrar"
                  type="button"
                >
                  <X size={18} />
                </button>
              </div>

              <p className={styles.dupMessage}>{duplicadoInfo.mensaje}</p>

              {duplicadoInfo.duplicados.length > 0 ? (
                <div className={styles.dupTableWrapper}>
                  <table className={styles.dupTable}>
                    <thead>
                      <tr>
                        <th>ct_transaction</th>
                        <th>Fecha</th>
                        <th>N° Doc</th>
                        <th className={styles.thRight}>Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {duplicadoInfo.duplicados.map((d, i) => (
                        <tr key={i}>
                          <td className={styles.tdMono}>{d.ct_transaction}</td>
                          <td>
                            {d.ct_date ? String(d.ct_date).substring(0, 10) : '—'}
                          </td>
                          <td>{d.ct_docnumber || '—'}</td>
                          <td className={styles.tdRight}>
                            {formatCurrency(d.ct_total, form.moneda)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className={styles.emptyItems}>
                  El backend marcó duplicado pero no envió detalles.
                </div>
              )}

              <div className={styles.formActions}>
                <button
                  type="button"
                  className={styles.btnSecondary}
                  onClick={() => setDuplicadoInfo(null)}
                  disabled={submittingConfirm}
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  className={styles.btnWarning}
                  onClick={handleConfirmarDuplicado}
                  disabled={submittingConfirm}
                >
                  {submittingConfirm ? 'Guardando...' : 'Confirmar, es un pago distinto'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
