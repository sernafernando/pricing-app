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
  Paperclip,
  Undo2,
} from 'lucide-react';
import api from '../../services/api';
import { useDebounce } from '../../hooks/useDebounce';
import useRecepcionDeposito, { readFocusQuery, readPedidoQuery, readEjeQuery } from '../../hooks/useRecepcionDeposito';
import { usePermisos } from '../../contexts/PermisosContext';
import AdjuntosPanel from './AdjuntosPanel';
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
  { id: 'pagado', label: 'Por recibir' },
  { id: 'recibido', label: 'Recibidos sin controlar' },
  { id: 'con_faltantes', label: 'Con faltantes' },
  { id: 'faltantes_con_res', label: 'Faltantes con resolución' },
  { id: 'controlado', label: 'Controlados' },
];
const POR_RECIBIR_ID = 'pagado';
const FALTANTES_CON_RES_ID = 'faltantes_con_res';

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
const linkedOcs = (pedido, lineas = []) => {
  if (Array.isArray(pedido.ocs) && pedido.ocs.length > 0) return pedido.ocs;
  const seen = new Map();
  lineas.forEach((l) => {
    if (l.oc_poh_id == null) return;
    const key = `${l.oc_comp_id}-${l.oc_bra_id}-${l.oc_poh_id}`;
    if (!seen.has(key)) {
      seen.set(key, {
        oc_comp_id: l.oc_comp_id,
        oc_bra_id: l.oc_bra_id,
        oc_poh_id: l.oc_poh_id,
      });
    }
  });
  if (seen.size > 0) return [...seen.values()];
  if (pedido.oc_poh_id != null) {
    return [
      {
        oc_comp_id: pedido.oc_comp_id,
        oc_bra_id: pedido.oc_bra_id,
        oc_poh_id: pedido.oc_poh_id,
      },
    ];
  }
  return [];
};

const lineasDeOc = (lineas, oc) => {
  const tagged = lineas.filter((l) => l.oc_poh_id != null);
  if (tagged.length === 0) return lineas;
  return lineas.filter(
    (l) =>
      l.oc_poh_id === oc.oc_poh_id &&
      (l.oc_comp_id == null || l.oc_comp_id === oc.oc_comp_id) &&
      (l.oc_bra_id == null || l.oc_bra_id === oc.oc_bra_id)
  );
};

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

// Ident chips on EVERY Depósito row (CON-OC and SIN-OC): factura number and
// `pedidos_documento`. Observaciones stays as a third optional chip. Each is
// omitted independently when null/blank, same rule `buildPedidoClipboardText`
// already follows. CON-OC used to XOR these away in favor of itemsBadge.
const CHIP_FACTURA_A11Y = (numero) => `Factura ${numero}`;
const CHIP_PEDIDOS_DOCUMENTO_A11Y = (texto) => `Pedidos documento: ${texto}`;
const CHIP_OBSERVACIONES_A11Y = (texto) => `Observaciones: ${texto}`;

// Free-text ident fields have no hard cap. 60 characters fit one badge line and
// still distinguish two pedidos; the FULL text travels via `title` (mouse) and
// the .sr-only span (screen readers), so truncation is visual only.
const CHIP_MAX_CHARS = 60;
const truncarChip = (t) =>
  t.length > CHIP_MAX_CHARS ? `${t.slice(0, CHIP_MAX_CHARS).trimEnd()}…` : t;

// Banner de arribo. Se CONSERVA con un solo cambio: "control de ítems" →
// "control de cantidades". La primera oración sigue siendo cierta en TODAS las
// ramas de render (incluida la de error de /saldos) y nombra el estado, no la
// tabla. La segunda es la que más se gana ahora: con los ítems a la vista, el
// operario necesita saber POR QUÉ no puede contarlos, y "control de ítems" al
// lado de ítems visibles se leía como una contradicción.
const ARRIBO_BANNER_TEXT =
  'El pedido aún no fue recibido en depósito. Confirme el arribo para habilitar el control de cantidades.';

// Linked OC whose ERP header/lines are missing must still occupy one block.
// Hiding it made the vínculo look gone. Same Spanish copy in arribo + control.
const OC_ERP_MISSING_COPY = 'OC no encontrada en ERP';

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
 * Closed-header identification chips — factura + pedidos_documento on every
 * row, including CON-OC. Observaciones remains optional. Each field is omitted
 * independently when null/blank.
 */
function identChips(pedido, stylesMap) {
  const chips = [];
  const factura = pedido.numero_factura && String(pedido.numero_factura).trim();
  if (factura) {
    chips.push(
      <span
        key="factura"
        className={stylesMap.chipIdent}
        title={factura}
      >
        <FileText size={11} aria-hidden="true" />
        <span aria-hidden="true">{truncarChip(factura)}</span>
        <span className="sr-only">{CHIP_FACTURA_A11Y(factura)}</span>
      </span>,
    );
  }
  const pedidosDoc = pedido.pedidos_documento && String(pedido.pedidos_documento).trim();
  if (pedidosDoc) {
    chips.push(
      <span
        key="pedidos-documento"
        className={stylesMap.chipIdent}
        title={pedidosDoc}
      >
        <FileText size={11} aria-hidden="true" />
        <span aria-hidden="true">{truncarChip(pedidosDoc)}</span>
        <span className="sr-only">{CHIP_PEDIDOS_DOCUMENTO_A11Y(pedidosDoc)}</span>
      </span>,
    );
  }
  const observaciones = pedido.observaciones && String(pedido.observaciones).trim();
  if (observaciones) {
    chips.push(
      <span
        key="observaciones"
        className={stylesMap.chipIdent}
        title={observaciones}
      >
        <StickyNote size={11} aria-hidden="true" />
        <span aria-hidden="true">{truncarChip(observaciones)}</span>
        <span className="sr-only">{CHIP_OBSERVACIONES_A11Y(observaciones)}</span>
      </span>,
    );
  }
  return chips;
}

/**
 * "Factura cargada" uses the Controlado visual family (badgeControlado).
 * Driven ONLY by the ERP `factura_cargada` flag — a numero_factura (or
 * document-row presence) must never light this badge (chicho lock).
 */
function facturaCargadaBadge(facturaCargada, stylesMap) {
  if (facturaCargada !== true) return null;
  return <span className={stylesMap.badgeControlado}>Factura cargada</span>;
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
    // First, mirroring the closed header (numero → OC → proveedor): this text is
    // pasted to answer "which pedido is this", and the OC is the id the operator
    // cross-checks against paperwork. Omitting it here while showing it on the
    // row would make the copy say less than the screen it came from.
    // Formatted to null rather than 0/'' so the omit-if-blank rule below covers
    // the SIN-OC case with no extra branch.
    ['OC', pedido.oc_poh_id != null ? `#${pedido.oc_poh_id}` : null],
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
  const ocs = linkedOcs(pedido, lineas);

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
        <AlertTriangle size={16} className={styles.noOcBannerIcon} />
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
      {(ocs.length > 0 ? ocs : [null]).map((oc) => {
        const blockLineas = oc ? lineasDeOc(lineas, oc) : lineas;
        const ocKey = oc ? `${oc.oc_comp_id}-${oc.oc_bra_id}-${oc.oc_poh_id}` : 'header';
        const erpMissing = Boolean(oc) && blockLineas.length === 0;
        if (!oc && blockLineas.length === 0) return null;
        return (
          <section key={ocKey} className={styles.ocBlock}>
            {oc && <h3 className={styles.ocBlockTitle}>OC #{oc.oc_poh_id}</h3>}
            {erpMissing ? (
              <p className={styles.ocErpMissing}>{OC_ERP_MISSING_COPY}</p>
            ) : (
            <div className={styles.tableWrapper}>
              <table className={styles.itemTable}>
                <caption className="sr-only">
                  Ítems de la orden de compra{oc ? ` #${oc.oc_poh_id}` : ''} (solo lectura)
                </caption>
                <thead>
                  <tr>
                    <th>Ítem</th>
                    <th>Depósito</th>
                    <th className={styles.thRight}>Cant. pedida</th>
                  </tr>
                </thead>
                <tbody>
                  {blockLineas.map((linea) => {
                    const nombre = linea.item_nombre || `Ítem #${linea.item_id}`;
                    return (
                      <tr key={`${ocKey}-${linea.pod_id}`}>
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
          </section>
        );
      })}
    </>
  );
}

// Optional control evidence (#16): obs + AdjuntosPanel tipo=otro. Shown on
// the control path (incl. control OK). Neither field is required to succeed.
function ControlEvidenceFields({ pedidoId, observaciones, onObservacionesChange, obsInputId }) {
  const fotoLabelId = `foto-control-${pedidoId}`;
  return (
    <div className={styles.observacionesInline}>
      <label htmlFor={obsInputId} className={styles.observacionesLabel}>
        Observaciones (opcional)
      </label>
      <textarea
        id={obsInputId}
        className={styles.observacionesTextarea}
        placeholder="Notas de control (opcional)…"
        value={observaciones}
        onChange={(e) => onObservacionesChange(e.target.value)}
      />
      <p id={fotoLabelId} className={styles.observacionesLabel}>
        Foto de control (opcional)
      </p>
      <div aria-labelledby={fotoLabelId}>
        <AdjuntosPanel
          entidadTipo="pedido_compra"
          entidadId={pedidoId}
          canManage
          tipo="otro"
        />
      </div>
    </div>
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
  const [faltantesTexto, setFaltantesTexto] = useState('');
  const [observaciones, setObservaciones] = useState('');
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

  const lineasErp = saldos.lineas || [];
  const lineas = lineasErp.filter((l) => Number(l.saldo_pendiente) !== 0);
  const ocs = linkedOcs(pedido, lineasErp);

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

  const handleSubmit = async ({ completo }) => {
    if (!completo && !faltantesTexto.trim()) {
      setSubmitError('El texto de faltantes es requerido.');
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);
    try {
      const payload = { lineas: tandaLineas };
      if (!completo) payload.faltantes_texto = faltantesTexto.trim();
      const obs = observaciones.trim();
      if (obs) payload.observaciones = obs;
      await registrarIngresos(pedido.id, payload);
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

      {(ocs.length > 0 ? ocs : [null]).map((oc) => {
        const blockLineas = oc ? lineasDeOc(lineas, oc) : lineas;
        const erpLineas = oc ? lineasDeOc(lineasErp, oc) : lineasErp;
        const ocKey = oc ? `${oc.oc_comp_id}-${oc.oc_bra_id}-${oc.oc_poh_id}` : 'header';
        const erpMissing = Boolean(oc) && erpLineas.length === 0;
        if (!oc && blockLineas.length === 0) return null;
        return (
      <section key={ocKey} className={styles.ocBlock}>
        {oc && <h3 className={styles.ocBlockTitle}>OC #{oc.oc_poh_id}</h3>}
        {erpMissing ? (
          <p className={styles.ocErpMissing}>{OC_ERP_MISSING_COPY}</p>
        ) : (
      <div className={styles.tableWrapper}>
        <table className={styles.itemTable}>
          <thead>
            <tr>
              <th className={styles.thCenter}>
                <input
                  type="checkbox"
                  aria-label={oc ? `Marcar todo OC #${oc.oc_poh_id}` : 'Marcar todo'}
                  checked={blockLineas.length > 0 && blockLineas.every((l) => isChecked(l.pod_id))}
                  onChange={(e) => {
                    if (e.target.checked) {
                      const next = { ...tanda };
                      blockLineas.forEach((l) => { next[l.pod_id] = String(l.saldo_pendiente); });
                      setTanda(next);
                    } else {
                      const reset = { ...tanda };
                      blockLineas.forEach((l) => { reset[l.pod_id] = '0'; });
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
            {blockLineas.map((linea) => {
              const inputErr = hasInputError(linea.pod_id);
              const checked = isChecked(linea.pod_id);
              const nombre = linea.item_nombre || `Ítem #${linea.item_id}`;
              return (
                <tr key={`${ocKey}-${linea.pod_id}`}>
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
                        className={`${styles.inputError} ${styles.qtyErrorHint}`}
                        role="alert"
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
        )}
      </section>
        );
      })}

      <div className={styles.observacionesInline}>
        <label htmlFor={`faltantes-conoc-${pedido.id}`} className={styles.observacionesLabel}>
          Texto de faltantes (requerido al marcar faltantes)
        </label>
        <textarea
          id={`faltantes-conoc-${pedido.id}`}
          className={styles.observacionesTextarea}
          placeholder="Describa los ítems faltantes…"
          value={faltantesTexto}
          onChange={(e) => setFaltantesTexto(e.target.value)}
        />
      </div>

      <ControlEvidenceFields
        pedidoId={pedido.id}
        observaciones={observaciones}
        onObservacionesChange={setObservaciones}
        obsInputId={`obs-conoc-${pedido.id}`}
      />

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
            onClick={() => handleSubmit({ completo: false })}
            disabled={!canSubmitFaltantes || submitting || anyInputError}
          >
            {submitting ? <Loader2 size={14} className={styles.spin} /> : null}
            Marcar con faltantes
          </button>
          <button
            type="button"
            className={styles.btnPrimary}
            onClick={() => handleSubmit({ completo: true })}
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
  const [faltantesTexto, setFaltantesTexto] = useState('');
  const [observaciones, setObservaciones] = useState('');
  const [faltantesError, setFaltantesError] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [submitSuccess, setSubmitSuccess] = useState(null);

  const handleConfirmar = async (completo) => {
    if (!completo && !faltantesTexto.trim()) {
      setFaltantesError(true);
      return;
    }
    setFaltantesError(false);
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);
    try {
      const payload = completo
        ? { completo: true, observaciones: observaciones.trim() || undefined }
        : {
            completo: false,
            faltantes_texto: faltantesTexto.trim(),
            observaciones: observaciones.trim() || undefined,
          };
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

  useEffect(() => {
    if (!showFaltantes || readFocusQuery() !== 'observaciones') return undefined;
    document.getElementById('pedido-observaciones')?.focus();
    return undefined;
  }, [showFaltantes]);

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
        <AlertTriangle size={16} className={styles.noOcBannerIcon} />
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

      {showControladoBtn && (
        <ControlEvidenceFields
          pedidoId={pedido.id}
          observaciones={observaciones}
          onObservacionesChange={setObservaciones}
          obsInputId={`obs-sinoc-${pedido.id}`}
        />
      )}

      {showFaltantes && (
        <div className={styles.observacionesInline}>
          <label
            htmlFor="pedido-observaciones"
            className={styles.observacionesLabel}
          >
            Texto de faltantes (requerido)
          </label>
          <textarea
            id="pedido-observaciones"
            className={`${styles.observacionesTextarea} ${faltantesError ? styles.textareaError : ''}`}
            placeholder="Describa los ítems faltantes…"
            value={faltantesTexto}
            onChange={(e) => {
              setFaltantesTexto(e.target.value);
              if (faltantesError && e.target.value.trim()) setFaltantesError(false);
            }}
            aria-required="true"
            aria-invalid={faltantesError}
          />
          {faltantesError && (
            <span className={styles.fieldError} role="alert">
              El texto de faltantes es requerido.
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

function PedidoAccordion({ pedido, onRefreshList, onCopyOutcome, defaultOpen = false }) {
  const { deshacerRecibido } = useRecepcionDeposito();
  const { tienePermiso } = usePermisos();
  const canDespacharRetiro = tienePermiso('deposito.despachar_retiro');
  const [open, setOpen] = useState(defaultOpen);
  const [retiroOpen, setRetiroOpen] = useState(false);
  const [docsOpen, setDocsOpen] = useState(false);
  const [undoing, setUndoing] = useState(false);
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
  const handleDeshacer = async () => {
    setUndoing(true);
    try {
      await deshacerRecibido(pedido.id);
      onRefreshList();
    } catch {
      /* error surface lives in the hook; list stays as-is */
    } finally {
      setUndoing(false);
    }
  };

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
          {pedido.oc_poh_id != null && itemsBadge(pedido, styles)}
          {identChips(pedido, styles)}
          {facturaCargadaBadge(pedido.factura_cargada, styles)}
          {estadoBadge(pedido.estado, styles)}
          <button
            type="button"
            className={styles.docsButton}
            onClick={() => setDocsOpen(true)}
            aria-label={`Documentos del pedido #${pedido.numero}`}
          >
            <Paperclip size={12} aria-hidden="true" />
            Docs
          </button>
          {pedido.estado === 'recibido' && (
            <button
              type="button"
              className={styles.btnSecondary}
              onClick={handleDeshacer}
              disabled={undoing}
              aria-label={`Deshacer recibido del pedido #${pedido.numero}`}
            >
              {undoing ? <Loader2 size={12} className={styles.spin} /> : <Undo2 size={12} aria-hidden="true" />}
              Deshacer recibido
            </button>
          )}
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
              {canDespacharRetiro && (
                <button
                  type="button"
                  className={styles.retiroButton}
                  onClick={() => setRetiroOpen(true)}
                  aria-label={`Coordinar retiro para pedido #${pedido.numero}`}
                >
                  <Truck size={12} aria-hidden="true" />
                  Coordinar retiro
                </button>
              )}
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

      {docsOpen && (
        <div className={styles.docsOverlay} role="dialog" aria-modal="true" aria-labelledby={`docs-title-${pedido.id}`}>
          <div className={styles.docsPanel}>
            <div className={styles.docsHeader}>
              <h2 id={`docs-title-${pedido.id}`} className={styles.docsTitle}>
                Adjuntos del pedido #{pedido.numero}
              </h2>
              <button
                type="button"
                className={styles.docsClose}
                onClick={() => setDocsOpen(false)}
                aria-label="Cerrar documentos"
              >
                <X size={16} aria-hidden="true" />
              </button>
            </div>
            <AdjuntosPanel entidadTipo="pedido_compra" entidadId={pedido.id} canManage={false} />
          </div>
        </div>
      )}

      {retiroOpen && canDespacharRetiro && (
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
  const focusPedidoId = readPedidoQuery();
  const [filtro, setFiltro] = useState(() => {
    const eje = readEjeQuery();
    if (eje && FILTER_TABS.some((t) => t.id === eje)) return eje;
    if (focusPedidoId) return 'recibido';
    return FILTER_TABS[0].id;
  });
  const [incluirCC, setIncluirCC] = useState(false);
  const [qProveedor, setQProveedor] = useState('');
  const [qNumero, setQNumero] = useState('');
  const [qFactura, setQFactura] = useState('');
  const [qEmpresa, setQEmpresa] = useState('');
  const dqProveedor = useDebounce(qProveedor, 300);
  const dqNumero = useDebounce(qNumero, 300);
  const dqFactura = useDebounce(qFactura, 300);
  const dqEmpresa = useDebounce(qEmpresa, 300);
  const [pedidos, setPedidos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const focusObservaciones = readFocusQuery() === 'observaciones';

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
      // Recibidos / Con faltantes / Controlados use eje_procesal. Por recibir
      // still sends financial `estado` (pagado ± CC).
      const params = { page_size: 200 };
      if (filtro === 'recibido') {
        params.eje_procesal = 'recibido';
      } else if (filtro === 'con_faltantes') {
        params.eje_procesal = 'faltantes_sin_res';
      } else if (filtro === FALTANTES_CON_RES_ID) {
        params.eje_procesal = 'faltantes_con_res';
      } else if (filtro === 'controlado') {
        params.eje_procesal = 'controlado';
      } else {
        params.estado =
          filtro === POR_RECIBIR_ID && incluirCC ? 'pagado,en_cuenta_corriente' : filtro;
      }
      params.tipo = 'mercaderia';
      if (dqProveedor.trim()) params.q_proveedor = dqProveedor.trim();
      if (dqNumero.trim()) params.q_numero = dqNumero.trim();
      if (dqFactura.trim()) params.q_factura = dqFactura.trim();
      if (dqEmpresa.trim()) params.q_empresa = dqEmpresa.trim();

      const { data } = await api.get('/administracion/compras/pedidos', {
        params,
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
  }, [filtro, incluirCC, dqProveedor, dqNumero, dqFactura, dqEmpresa, refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetchPedidos();
  }, [fetchPedidos]);

  useEffect(() => {
    if (!focusObservaciones || loading) return undefined;
    const node = document.getElementById('pedido-observaciones');
    if (node) {
      node.focus();
      return undefined;
    }
    return undefined;
  }, [focusObservaciones, loading, pedidos]);

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

      {filtro === POR_RECIBIR_ID && (
        <label className={styles.ccToggle}>
          <input
            type="checkbox"
            checked={incluirCC}
            onChange={(e) => setIncluirCC(e.target.checked)}
          />
          Incluir cuenta corriente
        </label>
      )}

      <div className={styles.filterBar}>
        <label className={styles.filterField}>
          <span className={styles.filterLabel}>Proveedor</span>
          <input
            className={styles.filterInput}
            value={qProveedor}
            onChange={(e) => setQProveedor(e.target.value)}
            placeholder="Contiene…"
          />
        </label>
        <label className={styles.filterField}>
          <span className={styles.filterLabel}>Pedido</span>
          <input
            className={styles.filterInput}
            value={qNumero}
            onChange={(e) => setQNumero(e.target.value)}
            placeholder="P-…"
          />
        </label>
        <label className={styles.filterField}>
          <span className={styles.filterLabel}>Factura</span>
          <input
            className={styles.filterInput}
            value={qFactura}
            onChange={(e) => setQFactura(e.target.value)}
            placeholder="Número…"
          />
        </label>
        <label className={styles.filterField}>
          <span className={styles.filterLabel}>Empresa</span>
          <input
            className={styles.filterInput}
            value={qEmpresa}
            onChange={(e) => setQEmpresa(e.target.value)}
            placeholder="Contiene…"
          />
        </label>
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
              defaultOpen={
                (focusPedidoId != null && String(p.id) === String(focusPedidoId))
                || (Boolean(focusObservaciones) && !focusPedidoId && p.id === pedidos[0]?.id)
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
