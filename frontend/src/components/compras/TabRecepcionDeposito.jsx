import { useCallback, useEffect, useState } from 'react';
import {
  Package,
  ChevronRight,
  Loader2,
  AlertCircle,
  CheckCircle2,
  AlertTriangle,
  Truck,
} from 'lucide-react';
import api from '../../services/api';
import useRecepcionDeposito from '../../hooks/useRecepcionDeposito';
import ModalCargarRetiro from './ModalCargarRetiro';
import styles from './TabRecepcionDeposito.module.css';

// ── Helpers ──────────────────────────────────────────────────────

const FILTER_TABS = [
  { id: 'pagado', label: 'Por recibir' },
  { id: 'recibido', label: 'Recibidos sin controlar' },
  { id: 'controlado', label: 'Controlados' },
  { id: 'con_faltantes', label: 'Con faltantes' },
];

function estadoBadge(estado, stylesMap) {
  switch (estado) {
    case 'pagado':
      return <span className={stylesMap.badgePagado}>Pagado</span>;
    case 'con_faltantes':
      return <span className={stylesMap.badgeConFaltantes}>Con faltantes</span>;
    case 'recibido':
      return <span className={stylesMap.badgeRecibido}>Recibido</span>;
    case 'controlado':
      return <span className={stylesMap.badgeControlado}>Controlado</span>;
    default:
      return <span className={stylesMap.badge}>{estado}</span>;
  }
}

// ── Accordion body — CON OC — arrival panel (estado=pagado) ──────

function AccordionBodyConOcArribo({ pedido, onRefreshList }) {
  const { confirmarPedido } = useRecepcionDeposito();
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [submitSuccess, setSubmitSuccess] = useState(null);

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
          El pedido aún no fue recibido en depósito. Confirme el arribo para habilitar el control de ítems.
        </p>
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
                  <td className={styles.tdRight}>{linea.pod_qty}</td>
                  <td className={styles.tdRight}>{linea.cantidad_recibida_total}</td>
                  <td className={`${styles.tdRight} ${styles.saldoCell} ${linea.saldo_pendiente > 0 ? styles.saldoPendiente : styles.saldoCero}`}>
                    {linea.saldo_pendiente}
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
                        Excede saldo ({linea.saldo_pendiente})
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
      if (pedido.estado === 'pagado') {
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
  const showArriboBtn = estado === 'pagado';
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

function PedidoAccordion({ pedido, onRefreshList }) {
  const [open, setOpen] = useState(false);
  const [retiroOpen, setRetiroOpen] = useState(false);

  const handleRetiroSuccess = useCallback(() => {
    setRetiroOpen(false);
    onRefreshList();
  }, [onRefreshList]);

  // Prevent accordion toggle when clicking retiro button
  const handleRetiroClick = (e) => {
    e.stopPropagation();
    setRetiroOpen(true);
  };

  return (
    <div className={styles.accordion}>
      <button
        type="button"
        className={styles.accordionHeader}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronRight
          size={16}
          className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`}
          aria-hidden="true"
        />
        <span className={styles.pedidoNumero}>#{pedido.numero}</span>
        <span className={styles.pedidoProveedor}>{pedido.proveedor_nombre || '—'}</span>
        <div className={styles.headerBadges}>
          {estadoBadge(pedido.estado, styles)}
          {pedido.requiere_envio && (
            <>
              <span className={styles.tagRetiro}>
                <Truck size={11} aria-hidden="true" />
                Requiere retiro
              </span>
              <button
                type="button"
                className={styles.retiroButton}
                onClick={handleRetiroClick}
                aria-label={`Despachar retiro para pedido #${pedido.numero}`}
              >
                <Truck size={12} aria-hidden="true" />
                Despachar retiro
              </button>
            </>
          )}
        </div>
      </button>

      {open && (
        <div className={styles.accordionBody}>
          {/* La lista (PedidoCompraResponse) expone oc_poh_id, no tiene_oc:
              ese flag solo viene en la respuesta de saldos. Usar tiene_oc acá
              daba siempre undefined → "sin OC" aunque el pedido tuviera OC.
              CON-OC + pagado → arrival panel (no item counting yet).
              CON-OC + recibido/con_faltantes → item-level ingresos panel. */}
          {pedido.oc_poh_id != null ? (
            pedido.estado === 'pagado' ? (
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
  const [filtro, setFiltro] = useState('pagado'); // 'pagado' | 'recibido' | 'controlado' | 'con_faltantes'
  const [pedidos, setPedidos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const fetchPedidos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Each tab maps 1:1 to a backend estado value.
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
            />
          ))}
        </div>
      )}
    </div>
  );
}
