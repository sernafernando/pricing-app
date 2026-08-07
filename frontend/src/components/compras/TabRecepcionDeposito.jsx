import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Package,
  ChevronRight,
  Check,
  Copy,
  X,
  Loader2,
  AlertCircle,
  CheckCircle2,
  AlertTriangle,
  Truck,
  FileText,
  StickyNote,
} from 'lucide-react';
import api from '../../services/api';
import useRecepcionDeposito from '../../hooks/useRecepcionDeposito';
import ModalCargarRetiro from './ModalCargarRetiro';
import styles from './TabRecepcionDeposito.module.css';

// ponytail: this file is 884+ lines and already violates the ~200-line
// component-size convention. The genuine fix is splitting by accordion body
// (AccordionBodyConOc, AccordionBodySinOc, AccordionBodyConOcArribo,
// PedidoAccordion → own files) — a move-only refactor touching every export
// and every test import. Bolting that onto a behavioural change would spend
// the review budget on churn and bury the diff. Revisit next time this file
// is touched for an unrelated reason. See design D5 (compras-recepcion-
// visibilidad-items) for the full rationale. Tracked in docs/tech-debt-ledger.md.

// ── Helpers ──────────────────────────────────────────────────────

// Single source of truth for the Spanish label of each estado. Both the badge
// and the clipboard payload read from here — never inline these strings again.
const ESTADO_LABELS = {
  pagado: 'Pagado',
  en_cuenta_corriente: 'En cuenta corriente',
  con_faltantes: 'Con faltantes',
  recibido: 'Recibido',
  controlado: 'Controlado',
};

// `pagado` and `en_cuenta_corriente` deliberately share ONE badge tone.
// They are the same fact to a warehouse operator — "awaiting reception" — and how
// the pedido was paid is an accounting concern that must not read as a different
// logistics state. The badge TEXT still names the estado for whoever needs it, so
// nothing is hidden; only the colour, which is the channel that would otherwise
// imply "handle these two differently", is shared. Giving them separate tones
// would reintroduce visually the very split the merged "Por recibir" tab removed.
const ESTADO_BADGE_CLASS = {
  pagado: 'badgePagado',
  en_cuenta_corriente: 'badgePagado',
  con_faltantes: 'badgeConFaltantes',
  recibido: 'badgeRecibido',
  controlado: 'badgeControlado',
};

// A tab id is NOT a single estado: it is the `estado` query param sent verbatim
// to the listing endpoint, which splits on comma and filters with IN(...).
//
// 'pagado' and 'en_cuenta_corriente' deliberately share ONE tab: how a pedido
// was paid (cash up front vs. supplier credit) is an accounting concern with no
// bearing on the warehouse. Both estados mean "awaiting reception", so splitting
// them only forced the operator to check two tabs to do a single job.
// The badge still distinguishes them — that information is useful, the filter is not.
const FILTER_TABS = [
  { id: 'pagado,en_cuenta_corriente', label: 'Por recibir' },
  { id: 'recibido', label: 'Recibidos sin controlar' },
  { id: 'controlado', label: 'Controlados' },
  { id: 'con_faltantes', label: 'Con faltantes' },
];

// Outcome text announced by the SINGLE list-level copy live region, keyed by
// copyStatus. 'idle' is deliberately absent: it maps to an empty string, because
// the region is mounted from the first render and only its TEXT may change.
const COPY_STATUS_MESSAGE = {
  copied: (numero) => `Datos del pedido #${numero} copiados`,
  error: (numero) => `No se pudo copiar el pedido #${numero}`,
};

// How long a copy outcome stays visible/announced. Shared by the two timers that
// legitimately exist — the row's icon flash and the list's announcement — so the
// visual and the spoken feedback can never drift apart.
const COPY_FLASH_MS = 1500;

// Composición de ítems para el header cerrado (solo CON-OC). "líneas" —
// nunca "productos distintos": la granularidad de pod_id es ítem×destino, así
// que un ítem enviado a dos depósitos son DOS líneas. "u" es un símbolo de
// unidad y no pluraliza (como "kg"), por eso solo "línea" tiene rama plural.
const ITEMS_BADGE_LABEL = (lineas, unidades) =>
  `${lineas} ${lineas === 1 ? 'línea' : 'líneas'} · ${formatUnidades(unidades)} u`;

// Versión hablada del badge: "5 líneas · 120 u" leído en voz alta es críptico.
const ITEMS_BADGE_A11Y = (lineas, unidades) =>
  `${lineas} ${lineas === 1 ? 'línea' : 'líneas'} de orden de compra, ` +
  `${formatUnidades(unidades)} ${Number(unidades) === 1 ? 'unidad' : 'unidades'} en total`;

// Toda cantidad de esta pestaña pasa por acá. El backend serializa los Decimal
// del ERP como string ("120.000000"), y volcarlo crudo en una celda mostraba
// "10.000000" donde el operario espera "10" — justo en las columnas que tiene
// que leer para reconocer el pedido. Es UNA sola función a propósito: el badge
// del header y las tablas hablan del mismo dato, así que no pueden divergir de
// formato. `maximumFractionDigits: 2` conserva el caso fraccionario real sin
// arrastrar los seis decimales del Numeric(18,6).
// El guard nullish no es por los llamadores de HOY: `SaldoLineaResponse` declara
// pod_qty / cantidad_recibida_total / saldo_pendiente como Decimal REQUERIDOS, y
// oc_unidades_total siempre viaja junto a oc_lineas_total, que ya está guardado.
// Es por el contrato de la función: sin él, `Number(undefined)` pinta "NaN" y
// `Number(null)` pinta un "0" inventado, así que el próximo que la use sobre un
// campo opcional se come eso en pantalla. Un dato ausente se muestra como
// ausente — el mismo guion que usa el resto de la tabla.
const formatUnidades = (v) =>
  v == null ? '—' : Number(v).toLocaleString('es-AR', { maximumFractionDigits: 2 });

// Chips de identificación para pedidos SIN OC: los únicos datos identificatorios
// que existen a nivel pedido. Se omiten cuando el campo es null/vacío, igual que
// buildPedidoClipboardText.
const CHIP_FACTURA_A11Y = (numero) => `Factura ${numero}`;
const CHIP_OBSERVACIONES_A11Y = (texto) => `Observaciones: ${texto}`;

// `observaciones` es texto libre sin tope. 60 caracteres entran en una línea al
// tamaño del badge y alcanzan para distinguir dos pedidos; el texto COMPLETO
// viaja por `title` (mouse) y por el span .sr-only (lectores de pantalla), así
// que el truncado es puramente visual y no oculta información a nadie.
const OBSERVACIONES_MAX_CHARS = 60;
const truncarObservaciones = (t) =>
  t.length > OBSERVACIONES_MAX_CHARS ? `${t.slice(0, OBSERVACIONES_MAX_CHARS).trimEnd()}…` : t;

// Banner de arribo. Se CONSERVA con un solo cambio: "control de ítems" →
// "control de cantidades". La primera oración sigue siendo cierta en TODAS las
// ramas de render (incluida la de error de /saldos) y nombra el estado, no la
// tabla. La segunda es la que más se gana ahora: con los ítems a la vista, el
// operario necesita saber POR QUÉ no puede contarlos, y "control de ítems" al
// lado de ítems visibles se leía como una contradicción.
const ARRIBO_BANNER_TEXT =
  'El pedido aún no fue recibido en depósito. Confirme el arribo para habilitar el control de cantidades.';

function estadoBadge(estado, stylesMap) {
  const badgeClass = ESTADO_BADGE_CLASS[estado];
  if (!badgeClass) return <span className={stylesMap.badge}>{estado}</span>;
  return <span className={stylesMap[badgeClass]}>{ESTADO_LABELS[estado]}</span>;
}

/**
 * Closed-header items badge (CON-OC only). Absent entirely when
 * `oc_lineas_total == null` — that already reads as "no OC data"; a "sin OC"
 * placeholder would spend header space to say nothing actionable, and
 * rendering "0 ítems" is the forbidden fake zero.
 *
 * Zero is rejected here too, not only null. Today the backend cannot send it —
 * the aggregate's GROUP BY emits no row for an OC with no lines, so such a
 * pedido is absent from the map and both fields land as null. But that
 * invariant lives two layers away, and this function is the one place that
 * decides whether the forbidden output can reach a screen. It must not depend
 * on a promise it cannot see: a 0 arriving from any future caller means "no
 * composition to show", which is exactly the null case.
 */
function itemsBadge(pedido, stylesMap) {
  if (pedido.oc_lineas_total == null || Number(pedido.oc_lineas_total) === 0) return null;
  const { oc_lineas_total: lineas, oc_unidades_total: unidades } = pedido;
  return (
    <span className={stylesMap.badgeItems}>
      <span aria-hidden="true">{ITEMS_BADGE_LABEL(lineas, unidades)}</span>
      <span className="sr-only">{ITEMS_BADGE_A11Y(lineas, unidades)}</span>
    </span>
  );
}

/**
 * Closed-header identification chips (SIN-OC only) — factura and
 * observaciones are the only pedido-level fields that identify one pedido
 * from another when there is no OC. Each is omitted independently when
 * null/blank, same rule `buildPedidoClipboardText` already follows.
 */
function identChips(pedido, stylesMap) {
  const chips = [];
  if (pedido.numero_factura && String(pedido.numero_factura).trim() !== '') {
    chips.push(
      <span
        key="factura"
        className={stylesMap.chipIdent}
        title={pedido.numero_factura}
      >
        <FileText size={11} aria-hidden="true" />
        <span aria-hidden="true">{pedido.numero_factura}</span>
        <span className="sr-only">{CHIP_FACTURA_A11Y(pedido.numero_factura)}</span>
      </span>,
    );
  }
  if (pedido.observaciones && String(pedido.observaciones).trim() !== '') {
    chips.push(
      <span
        key="observaciones"
        className={stylesMap.chipIdent}
        title={pedido.observaciones}
      >
        <StickyNote size={11} aria-hidden="true" />
        <span aria-hidden="true">{truncarObservaciones(pedido.observaciones)}</span>
        <span className="sr-only">{CHIP_OBSERVACIONES_A11Y(pedido.observaciones)}</span>
      </span>,
    );
  }
  return chips;
}

/**
 * Builds the plain-text clipboard payload for a pedido HEADER.
 *
 * Money fields (monto, moneda, saldo_pendiente, tipo_cambio*, varianza*) are
 * excluded on purpose: warehouse-only listings withhold the money trail, and
 * the clipboard must not become a side channel around that decision.
 * Items are excluded too — this is a header summary, not a picking list.
 *
 * Lines whose value is null/empty are omitted entirely.
 *
 * Kept module-scoped (not exported): `react-refresh/only-export-components`
 * forbids non-component named exports here. Covered via the copy button.
 */
function buildPedidoClipboardText(pedido) {
  const campos = [
    ['Proveedor', pedido.proveedor_nombre],
    ['Estado', ESTADO_LABELS[pedido.estado] ?? pedido.estado],
    ['Factura', pedido.numero_factura],
    ['Observaciones', pedido.observaciones],
  ];

  const lineas = [`Pedido #${pedido.numero}`];
  campos.forEach(([etiqueta, valor]) => {
    if (valor == null || String(valor).trim() === '') return;
    lineas.push(`${etiqueta}: ${valor}`);
  });
  if (pedido.requiere_envio) lineas.push('Requiere retiro');

  return lineas.join('\n');
}

// ── Accordion body — CON OC — arrival panel (estado=pagado) ──────

function AccordionBodyConOcArribo({ pedido, onRefreshList }) {
  const { confirmarPedido, getSaldos } = useRecepcionDeposito();
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [submitSuccess, setSubmitSuccess] = useState(null);

  // Read-only item list (D5a). Mirrors AccordionBodyConOc's fetch shape, with
  // ONE deliberate divergence: loading/error render as inline blocks instead
  // of early-returning the body, so the banner + "Marcar como recibido" stay
  // reachable even when /saldos fails. No refetch after handleArribo —
  // onRefreshList() moves the row out of this tab entirely.
  const [saldos, setSaldos] = useState(null);
  const [loadingSaldos, setLoadingSaldos] = useState(false);
  const [errorSaldos, setErrorSaldos] = useState(null);

  const fetchSaldos = useCallback(async () => {
    setLoadingSaldos(true);
    setErrorSaldos(null);
    try {
      const data = await getSaldos(pedido.id);
      setSaldos(data);
    } catch (err) {
      setErrorSaldos(
        err.response?.data?.detail || err.message || 'Error al cargar saldos.'
      );
    } finally {
      setLoadingSaldos(false);
    }
  }, [getSaldos, pedido.id]);

  useEffect(() => {
    fetchSaldos();
  }, [fetchSaldos]);

  const handleArribo = async () => {
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);
    try {
      // CON-OC + pagado → confirmar-pedido routes to confirmar_arribo_con_oc (state-only)
      await confirmarPedido(pedido.id, { completo: true });
      setSubmitSuccess('Arribo registrado. El pedido está listo para el control de items.');
      onRefreshList();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setSubmitError(typeof detail === 'string' ? detail : 'Error al registrar arribo.');
    } finally {
      setSubmitting(false);
    }
  };

  const lineas = saldos?.lineas ?? [];

  return (
    <>
      {loadingSaldos && (
        <div className={styles.centered}>
          <Loader2 size={16} className={styles.spin} /> Cargando ítems…
        </div>
      )}
      {errorSaldos && (
        <div className={styles.inlineError} role="alert">
          <AlertCircle size={14} /> {errorSaldos}
        </div>
      )}
      {submitError && (
        <div className={styles.inlineError} role="alert">
          <AlertCircle size={14} /> {submitError}
        </div>
      )}
      {submitSuccess && (
        <div className={styles.inlineSuccess} role="status">
          <CheckCircle2 size={14} /> {submitSuccess}
        </div>
      )}
      <div className={styles.noOcBanner} role="status">
        <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 2 }} />
        <p className={styles.noOcBannerText}>{ARRIBO_BANNER_TEXT}</p>
      </div>
      <div className={styles.noOcActions}>
        <button
          type="button"
          className={styles.btnPrimary}
          disabled={submitting}
          onClick={handleArribo}
        >
          {submitting ? <Loader2 size={14} className={styles.spin} /> : null}
          Marcar como recibido
        </button>
      </div>
      {lineas.length > 0 && (
        <div className={styles.tableWrapper}>
          <table className={styles.itemTable}>
            <caption className="sr-only">Ítems de la orden de compra (solo lectura)</caption>
            <thead>
              <tr>
                <th>Ítem</th>
                <th>Depósito</th>
                <th className={styles.thRight}>Cant. pedida</th>
              </tr>
            </thead>
            <tbody>
              {lineas.map((linea) => {
                const nombre = linea.item_nombre || `Ítem #${linea.item_id}`;
                return (
                  <tr key={linea.pod_id}>
                    <td>
                      <div className={styles.itemNombre}>{nombre}</div>
                      <div className={styles.itemCodigo}>#{linea.item_code ?? linea.item_id}</div>
                    </td>
                    <td>{linea.deposito_nombre || '—'}</td>
                    <td className={styles.tdRight}>{formatUnidades(linea.pod_qty)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ── Accordion body — CON OC ───────────────────────────────────────

function AccordionBodyConOc({ pedido, onRefreshList }) {
  const { getSaldos, registrarIngresos } = useRecepcionDeposito();

  const [saldos, setSaldos] = useState(null);
  const [loadingSaldos, setLoadingSaldos] = useState(false);
  const [errorSaldos, setErrorSaldos] = useState(null);

  // Tanda state: { [pod_id]: string } — each input value for this batch
  const [tanda, setTanda] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [submitSuccess, setSubmitSuccess] = useState(null);

  const fetchSaldos = useCallback(async () => {
    setLoadingSaldos(true);
    setErrorSaldos(null);
    try {
      const data = await getSaldos(pedido.id);
      setSaldos(data);
      // Initialize tanda with 0 for each line
      const init = {};
      (data.lineas || []).forEach((l) => {
        init[l.pod_id] = '0';
      });
      setTanda(init);
    } catch (err) {
      setErrorSaldos(
        err.response?.data?.detail || err.message || 'Error al cargar saldos.'
      );
    } finally {
      setLoadingSaldos(false);
    }
  }, [getSaldos, pedido.id]);

  useEffect(() => {
    fetchSaldos();
  }, [fetchSaldos]);

  if (loadingSaldos) {
    return (
      <div className={styles.centered}>
        <Loader2 size={16} className={styles.spin} /> Cargando saldos…
      </div>
    );
  }

  if (errorSaldos) {
    return (
      <div className={styles.inlineError}>
        <AlertCircle size={14} /> {errorSaldos}
      </div>
    );
  }

  if (!saldos) return null;

  const lineas = saldos.lineas || [];

  // ── Per-line input validation ──
  const hasInputError = (podId) => {
    const saldo = lineas.find((l) => l.pod_id === podId);
    if (!saldo) return false;
    const val = parseFloat(tanda[podId] || '0');
    return val > saldo.saldo_pendiente;
  };

  const anyInputError = lineas.some((l) => hasInputError(l.pod_id));

  // Tanda lines with cantidad > 0
  const tandaLineas = lineas
    .map((l) => ({ pod_id: l.pod_id, cantidad_recibida: parseFloat(tanda[l.pod_id] || '0') }))
    .filter((l) => l.cantidad_recibida > 0);

  // "Marcar recibido" enabled: every line's tanda covers its full saldo, no errors
  const allCovered = lineas.every((l) => {
    const val = parseFloat(tanda[l.pod_id] || '0');
    return Math.abs(val - l.saldo_pendiente) < 0.000001;
  });

  // "Marcar con faltantes" enabled: at least one input > 0, no errors, NOT all covered
  const canSubmitFaltantes = tandaLineas.length > 0 && !anyInputError && !allCovered;
  const canSubmitRecibido = allCovered && !anyInputError && tandaLineas.length > 0;

  const handleCheckbox = (podId, checked) => {
    const saldo = lineas.find((l) => l.pod_id === podId);
    setTanda((prev) => ({
      ...prev,
      [podId]: checked ? String(saldo?.saldo_pendiente ?? 0) : '0',
    }));
  };

  const handleMarcarTodo = () => {
    const next = {};
    lineas.forEach((l) => {
      next[l.pod_id] = l.saldo_pendiente > 0 ? String(l.saldo_pendiente) : '0';
    });
    setTanda(next);
  };

  const handleDesmarcarTodo = () => {
    const next = {};
    lineas.forEach((l) => { next[l.pod_id] = '0'; });
    setTanda(next);
  };

  // Todo marcado: hay líneas con saldo > 0 y todas están en su saldo pleno.
  const lineasMarcables = lineas.filter((l) => l.saldo_pendiente > 0);
  const allMarked =
    lineasMarcables.length > 0 &&
    lineasMarcables.every(
      (l) => Math.abs(parseFloat(tanda[l.pod_id] || '0') - l.saldo_pendiente) < 0.000001
    );

  const handleInputChange = (podId, value) => {
    // Las unidades son enteras: solo dígitos, sin decimales ("1.3 memorias" no existe).
    if (value !== '' && !/^\d+$/.test(value)) return;
    setTanda((prev) => ({ ...prev, [podId]: value }));
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);
    try {
      await registrarIngresos(pedido.id, { lineas: tandaLineas });
      setSubmitSuccess('Control registrado correctamente.');
      await fetchSaldos();
      onRefreshList();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setSubmitError(
        typeof detail === 'string' ? detail : 'Error al registrar ingresos.'
      );
    } finally {
      setSubmitting(false);
    }
  };

  const isChecked = (podId) => {
    const saldo = lineas.find((l) => l.pod_id === podId);
    if (!saldo || saldo.saldo_pendiente <= 0) return false;
    const val = parseFloat(tanda[podId] || '0');
    return Math.abs(val - saldo.saldo_pendiente) < 0.000001;
  };

  return (
    <>
      {submitError && (
        <div className={styles.inlineError} role="alert">
          <AlertCircle size={14} /> {submitError}
        </div>
      )}
      {submitSuccess && (
        <div className={styles.inlineSuccess} role="status">
          <CheckCircle2 size={14} /> {submitSuccess}
        </div>
      )}

      <div className={styles.tableWrapper}>
        <table className={styles.itemTable}>
          <thead>
            <tr>
              <th className={styles.thCenter}>
                <input
                  type="checkbox"
                  aria-label="Marcar todo"
                  checked={lineas.length > 0 && lineas.every((l) => isChecked(l.pod_id))}
                  onChange={(e) => {
                    if (e.target.checked) handleMarcarTodo();
                    else {
                      const reset = {};
                      lineas.forEach((l) => { reset[l.pod_id] = '0'; });
                      setTanda(reset);
                    }
                  }}
                />
              </th>
              <th>Ítem</th>
              <th>Depósito</th>
              <th className={styles.thRight}>Cant. pedida</th>
              <th className={styles.thRight}>Recibido prev.</th>
              <th className={styles.thRight}>Saldo</th>
              <th className={styles.thRight}>Recibidas (tanda)</th>
            </tr>
          </thead>
          <tbody>
            {lineas.map((linea) => {
              const inputErr = hasInputError(linea.pod_id);
              const checked = isChecked(linea.pod_id);
              const nombre = linea.item_nombre || `Ítem #${linea.item_id}`;
              return (
                <tr key={linea.pod_id}>
                  <td className={styles.tdCenter}>
                    <input
                      type="checkbox"
                      aria-label={`Marcar ${nombre}`}
                      checked={checked}
                      disabled={linea.saldo_pendiente <= 0}
                      onChange={(e) => handleCheckbox(linea.pod_id, e.target.checked)}
                    />
                  </td>
                  <td>
                    <div className={styles.itemNombre}>{nombre}</div>
                    <div className={styles.itemCodigo}>#{linea.item_code ?? linea.item_id}</div>
                  </td>
                  <td>{linea.deposito_nombre || '—'}</td>
                  <td className={styles.tdRight}>{formatUnidades(linea.pod_qty)}</td>
                  <td className={styles.tdRight}>{formatUnidades(linea.cantidad_recibida_total)}</td>
                  <td className={`${styles.tdRight} ${styles.saldoCell} ${linea.saldo_pendiente > 0 ? styles.saldoPendiente : styles.saldoCero}`}>
                    {formatUnidades(linea.saldo_pendiente)}
                  </td>
                  <td className={styles.tdRight}>
                    <label htmlFor={`qty-${pedido.id}-${linea.pod_id}`} className="sr-only">
                      Cantidad recibida para {nombre}
                    </label>
                    <input
                      id={`qty-${pedido.id}-${linea.pod_id}`}
                      type="number"
                      min="0"
                      max={linea.saldo_pendiente}
                      step="1"
                      value={tanda[linea.pod_id] ?? '0'}
                      disabled={linea.saldo_pendiente <= 0}
                      onChange={(e) => handleInputChange(linea.pod_id, e.target.value)}
                      className={`${styles.inputCantidad} ${inputErr ? styles.inputError : ''}`}
                      aria-invalid={inputErr}
                      aria-describedby={inputErr ? `qty-err-${pedido.id}-${linea.pod_id}` : undefined}
                    />
                    {inputErr && (
                      <span
                        id={`qty-err-${pedido.id}-${linea.pod_id}`}
                        className={styles.inputError}
                        role="alert"
                        style={{ display: 'block', fontSize: 'var(--font-xs)', color: 'var(--cf-accent-red)', marginTop: 2 }}
                      >
                        Excede saldo ({formatUnidades(linea.saldo_pendiente)})
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className={styles.actionBar}>
        <div className={styles.actionBarLeft}>
          <button
            type="button"
            className={styles.btnSecondary}
            onClick={allMarked ? handleDesmarcarTodo : handleMarcarTodo}
            disabled={submitting}
          >
            {allMarked ? 'Desmarcar todo' : 'Marcar todo'}
          </button>
        </div>
        <div className={styles.actionBarRight}>
          <button
            type="button"
            className={styles.btnSecondary}
            onClick={handleSubmit}
            disabled={!canSubmitFaltantes || submitting || anyInputError}
          >
            {submitting ? <Loader2 size={14} className={styles.spin} /> : null}
            Marcar con faltantes
          </button>
          <button
            type="button"
            className={styles.btnPrimary}
            onClick={handleSubmit}
            disabled={!canSubmitRecibido || submitting || anyInputError}
          >
            {submitting ? <Loader2 size={14} className={styles.spin} /> : null}
            Marcar como controlado
          </button>
        </div>
      </div>
    </>
  );
}

// ── Accordion body — SIN OC ───────────────────────────────────────

function AccordionBodySinOc({ pedido, onRefreshList }) {
  const { confirmarPedido } = useRecepcionDeposito();
  const [showFaltantes, setShowFaltantes] = useState(false);
  const [observaciones, setObservaciones] = useState('');
  const [obsError, setObsError] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [submitSuccess, setSubmitSuccess] = useState(null);

  const handleConfirmar = async (completo) => {
    if (!completo && !observaciones.trim()) {
      setObsError(true);
      return;
    }
    setObsError(false);
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);
    try {
      const payload = completo
        ? { completo: true }
        : { completo: false, observaciones: observaciones.trim() };
      await confirmarPedido(pedido.id, payload);
      // D-SINOC messages based on source estado
      let msg;
      if (pedido.estado === 'pagado' || pedido.estado === 'en_cuenta_corriente') {
        msg = 'Pedido marcado como recibido.';
      } else if (completo) {
        msg = 'Pedido marcado como controlado.';
      } else {
        msg = 'Pedido marcado con faltantes.';
      }
      setSubmitSuccess(msg);
      onRefreshList();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setSubmitError(
        typeof detail === 'string' ? detail : 'Error al confirmar recepción.'
      );
    } finally {
      setSubmitting(false);
    }
  };

  // D-SINOC state machine button gating:
  //   pagado         → show ONLY "Marcar como recibido" (arrival)
  //   recibido       → show "Marcar como controlado" + "Con faltantes"
  //   con_faltantes  → show ONLY "Marcar como controlado"
  //   controlado     → no action buttons (terminal)
  const estado = pedido.estado;
  const showArriboBtn = estado === 'pagado' || estado === 'en_cuenta_corriente';
  const showControladoBtn = estado === 'recibido' || estado === 'con_faltantes';
  const showFaltantesBtn = estado === 'recibido';

  return (
    <>
      {submitError && (
        <div className={styles.inlineError} role="alert">
          <AlertCircle size={14} /> {submitError}
        </div>
      )}
      {submitSuccess && (
        <div className={styles.inlineSuccess} role="status">
          <CheckCircle2 size={14} /> {submitSuccess}
        </div>
      )}

      <div className={styles.noOcBanner} role="status">
        <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 2 }} />
        <p className={styles.noOcBannerText}>
          Este pedido no tiene OC vinculada. No es posible registrar por ítem.
        </p>
      </div>

      <div className={styles.noOcActions}>
        {showArriboBtn && (
          <button
            type="button"
            className={styles.btnPrimary}
            disabled={submitting}
            onClick={() => handleConfirmar(true)}
          >
            {submitting ? <Loader2 size={14} className={styles.spin} /> : null}
            Marcar como recibido
          </button>
        )}
        {showControladoBtn && (
          <button
            type="button"
            className={styles.btnPrimary}
            disabled={submitting}
            onClick={() => handleConfirmar(true)}
          >
            {submitting ? <Loader2 size={14} className={styles.spin} /> : null}
            Marcar como controlado
          </button>
        )}
        {showFaltantesBtn && (
          <button
            type="button"
            className={styles.btnSecondary}
            disabled={submitting}
            onClick={() => setShowFaltantes((v) => !v)}
          >
            Con faltantes
          </button>
        )}
      </div>

      {showFaltantes && (
        <div className={styles.observacionesInline}>
          <label
            htmlFor={`obs-sinoc-${pedido.id}`}
            className={styles.observacionesLabel}
          >
            Observaciones (requerido) *
          </label>
          <textarea
            id={`obs-sinoc-${pedido.id}`}
            className={`${styles.observacionesTextarea} ${obsError ? styles.inputError : ''}`}
            placeholder="Describa los ítems faltantes o motivo…"
            value={observaciones}
            onChange={(e) => {
              setObservaciones(e.target.value);
              if (obsError && e.target.value.trim()) setObsError(false);
            }}
            aria-required="true"
            aria-invalid={obsError}
          />
          {obsError && (
            <span role="alert" style={{ fontSize: 'var(--font-xs)', color: 'var(--cf-accent-red)' }}>
              Las observaciones son requeridas al marcar con faltantes.
            </span>
          )}
          <div>
            <button
              type="button"
              className={styles.btnSecondary}
              disabled={submitting}
              onClick={() => handleConfirmar(false)}
            >
              {submitting ? <Loader2 size={14} className={styles.spin} /> : null}
              Confirmar con faltantes
            </button>
          </div>
        </div>
      )}
    </>
  );
}

// ── Single accordion card ─────────────────────────────────────────

function PedidoAccordion({ pedido, onRefreshList, onCopyOutcome }) {
  const [open, setOpen] = useState(false);
  const [retiroOpen, setRetiroOpen] = useState(false);
  // 'idle' | 'copied' | 'error'. A boolean could not tell "never clicked" apart
  // from "clicked and failed", which is exactly the state the operator needs.
  // This state is VISUAL only (icon swap + .copyButtonError); the announcement
  // lives in the tab's single live region, reached through onCopyOutcome.
  const [copyStatus, setCopyStatus] = useState('idle');
  const copyResetTimerRef = useRef(null);

  // The copy-feedback flash timer must never outlive the component.
  useEffect(() => () => clearTimeout(copyResetTimerRef.current), []);

  const handleRetiroSuccess = useCallback(() => {
    setRetiroOpen(false);
    onRefreshList();
  }, [onRefreshList]);

  const handleCopiar = async () => {
    // One timer for both outcomes: scheduling the reset in a single place keeps
    // copyResetTimerRef the only handle the unmount cleanup has to clear. The
    // ANNOUNCEMENT is not flashed here — it is handed to the tab, which owns the
    // one live region shared by every row and schedules its own reset.
    const flashStatus = (status) => {
      setCopyStatus(status);
      clearTimeout(copyResetTimerRef.current);
      copyResetTimerRef.current = setTimeout(() => setCopyStatus('idle'), COPY_FLASH_MS);
      onCopyOutcome(status, pedido.numero);
    };

    // Explicit guard: where the async clipboard API is absent there is nothing
    // to reject, so relying on the throw would leave the button silently inert.
    if (typeof navigator.clipboard?.writeText !== 'function') {
      flashStatus('error');
      return;
    }

    try {
      await navigator.clipboard.writeText(buildPedidoClipboardText(pedido));
      flashStatus('copied');
    } catch {
      // Realistic path: the clipboard permission is denied by the browser.
      flashStatus('error');
    }
  };

  // The accessible name describes the ACTION and never the outcome. It used to
  // swap to "No se pudo copiar…" on failure, which was wrong twice over: the
  // name then lied about what the control still does, and screen readers do not
  // reliably re-read the name of the element that already holds focus — which is
  // precisely the element the operator just clicked. Both outcomes now travel
  // through the tab's role="status" region, the one channel that fires on a text
  // change alone. Keeping both would risk announcing the failure twice.
  // `title` mirrors it for the same reason: tooltip and accessible name are both
  // "what this button does" affordances, not a status channel.
  const copiarLabel = `Copiar datos del pedido #${pedido.numero}`;

  return (
    <div className={styles.accordion}>
      {/* The header is a plain container: the toggle and the action buttons are
          siblings. Nesting them inside one <button> was invalid HTML and forced
          a stopPropagation hack on every action. */}
      <div className={styles.accordionHeader}>
        <button
          type="button"
          className={styles.accordionToggle}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <ChevronRight
            size={16}
            className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`}
            aria-hidden="true"
          />
          <span className={styles.pedidoNumero}>#{pedido.numero}</span>
          {/* Sits beside the pedido number, not after the proveedor: both are
              IDENTIFIERS, while the proveedor is a name — and `.pedidoProveedor`
              takes `flex: 1`, so anything after it gets pushed to the far edge,
              away from the number it qualifies.
              The "OC" prefix is not decoration: `#PC-0001` next to a bare `#500`
              reads as two pedido numbers. It also lands inside the toggle on
              purpose, so the accordion's accessible name becomes
              "#PC-0001 OC #500 Proveedor SA" — the OC IS part of identifying the
              pedido, which is the whole point of this row.
              `#{oc_poh_id}` matches how ModalPedidoDetalle and ModalVincularOC
              already name an OC; the ERP header carries no friendlier number. */}
          {pedido.oc_poh_id != null && (
            <span className={styles.pedidoOc}>OC #{pedido.oc_poh_id}</span>
          )}
          <span className={styles.pedidoProveedor}>{pedido.proveedor_nombre || '—'}</span>
        </button>
        <div className={styles.headerBadges}>
          {pedido.oc_poh_id != null ? itemsBadge(pedido, styles) : identChips(pedido, styles)}
          {estadoBadge(pedido.estado, styles)}
          <button
            type="button"
            className={`${styles.copyButton} ${copyStatus === 'error' ? styles.copyButtonError : ''}`}
            onClick={handleCopiar}
            aria-label={copiarLabel}
            title={copiarLabel}
          >
            {copyStatus === 'copied' && <Check size={12} aria-hidden="true" />}
            {copyStatus === 'error' && <X size={12} aria-hidden="true" />}
            {copyStatus === 'idle' && <Copy size={12} aria-hidden="true" />}
          </button>
          {pedido.requiere_envio && (
            <>
              <span className={styles.tagRetiro}>
                <Truck size={11} aria-hidden="true" />
                Requiere retiro
              </span>
              <button
                type="button"
                className={styles.retiroButton}
                onClick={() => setRetiroOpen(true)}
                aria-label={`Coordinar retiro para pedido #${pedido.numero}`}
              >
                <Truck size={12} aria-hidden="true" />
                Coordinar retiro
              </button>
            </>
          )}
        </div>
      </div>

      {open && (
        <div className={styles.accordionBody}>
          {/* La lista (PedidoCompraResponse) expone oc_poh_id, no tiene_oc:
              ese flag solo viene en la respuesta de saldos. Usar tiene_oc acá
              daba siempre undefined → "sin OC" aunque el pedido tuviera OC.
              CON-OC + pagado → arrival panel (no item counting yet).
              CON-OC + recibido/con_faltantes → item-level ingresos panel. */}
          {pedido.oc_poh_id != null ? (
            pedido.estado === 'pagado' || pedido.estado === 'en_cuenta_corriente' ? (
              <AccordionBodyConOcArribo pedido={pedido} onRefreshList={onRefreshList} />
            ) : (
              <AccordionBodyConOc pedido={pedido} onRefreshList={onRefreshList} />
            )
          ) : (
            <AccordionBodySinOc pedido={pedido} onRefreshList={onRefreshList} />
          )}
        </div>
      )}

      {retiroOpen && (
        <ModalCargarRetiro
          pedidoId={pedido.id}
          pedidoNumero={pedido.numero}
          proveedorId={pedido.proveedor_id}
          isOpen={retiroOpen}
          onClose={() => setRetiroOpen(false)}
          onSuccess={handleRetiroSuccess}
        />
      )}
    </div>
  );
}

// ── Main tab ──────────────────────────────────────────────────────

export default function TabRecepcionDeposito() {
  // `filtro` holds a FILTER_TABS id, i.e. the raw `estado` query param — which
  // may be a comma-separated list of estados, not a single one.
  const [filtro, setFiltro] = useState(FILTER_TABS[0].id);
  const [pedidos, setPedidos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  // ONE live-region text for the whole list. Hoisted out of PedidoAccordion
  // because at most one row can ever carry an outcome, while a full page mounted
  // up to 200 concurrent live regions to say so.
  const [copyStatusMessage, setCopyStatusMessage] = useState('');
  const copyMessageTimerRef = useRef(null);

  // The shared announcement timer must never outlive the tab.
  useEffect(() => () => clearTimeout(copyMessageTimerRef.current), []);

  // Single place where the announcement is set AND reset, so there is exactly one
  // timer here no matter how many rows report an outcome. Rows send the outcome,
  // not the text: COPY_STATUS_MESSAGE stays the only source of the wording.
  const handleCopyOutcome = useCallback((status, numero) => {
    setCopyStatusMessage(COPY_STATUS_MESSAGE[status]?.(numero) ?? '');
    clearTimeout(copyMessageTimerRef.current);
    copyMessageTimerRef.current = setTimeout(() => setCopyStatusMessage(''), COPY_FLASH_MS);
  }, []);

  const fetchPedidos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Sent verbatim as the `estado` param. The backend splits it on comma and
      // filters with IN(...), so a tab id may carry several estados at once
      // (see FILTER_TABS: "Por recibir" = pagado + en_cuenta_corriente).
      const estados = filtro;

      const { data } = await api.get('/administracion/compras/pedidos', {
        params: { estado: estados, page_size: 200 },
      });
      // Normalize: API may return {items:[...]} or plain array
      const items = Array.isArray(data) ? data : data.items ?? data.pedidos ?? [];
      setPedidos(items);
    } catch (err) {
      setError(
        err.response?.data?.detail || err.message || 'Error al cargar pedidos.'
      );
    } finally {
      setLoading(false);
    }
  }, [filtro, refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetchPedidos();
  }, [fetchPedidos]);

  const handleRefreshList = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  return (
    <div className={styles.container}>
      <div className={styles.pageHeader}>
        <Package size={20} aria-hidden="true" />
        Recepción de Depósito
      </div>

      {/* Copy outcome for assistive technology — ONE region for the whole list.
          Mounted unconditionally and empty on purpose: a live region inserted at
          the same instant its text appears is routinely missed, so only the text
          may change. It sits ABOVE the loading/error/empty branches so it also
          survives every render state of the tab, and it is shared by every row
          because at most one copy outcome exists at a time. The visual channel
          (icon swap + .copyButtonError) stays per-row, inside PedidoAccordion.
          `sr-only` is the global utility this file already uses for the qty
          label — reused rather than duplicated as a module class. */}
      <div role="status" className="sr-only">
        {copyStatusMessage}
      </div>

      {/* Filter tabs */}
      <div className={styles.filterTabs} role="tablist" aria-label="Filtrar pedidos">
        {FILTER_TABS.map((ft) => (
          <button
            key={ft.id}
            type="button"
            role="tab"
            aria-selected={filtro === ft.id}
            className={`${styles.filterTab} ${filtro === ft.id ? styles.filterTabActive : ''}`}
            onClick={() => setFiltro(ft.id)}
          >
            {ft.label}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className={styles.errorBanner} role="alert">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className={styles.centered}>
          <Loader2 size={18} className={styles.spin} /> Cargando pedidos…
        </div>
      )}

      {/* Empty */}
      {!loading && !error && pedidos.length === 0 && (
        <div className={styles.emptyState}>
          No hay pedidos en este filtro.
        </div>
      )}

      {/* Accordion list */}
      {!loading && pedidos.length > 0 && (
        <div className={styles.accordionList}>
          {pedidos.map((p) => (
            <PedidoAccordion
              key={p.id}
              pedido={p}
              onRefreshList={handleRefreshList}
              onCopyOutcome={handleCopyOutcome}
            />
          ))}
        </div>
      )}
    </div>
  );
}
