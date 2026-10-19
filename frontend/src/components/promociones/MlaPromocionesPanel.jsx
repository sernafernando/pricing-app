import { useCallback, useEffect, useRef, useState } from 'react';
import { promocionesAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { useLazyResource } from '../../hooks/useLazyResource';
import { usePromoFilterStore } from '../../store/promoFilterStore';
import { getMarkupColor } from '../../hooks/useProductosOffsets';
import { matchesPromoFilter } from './promoFilterPredicate';
import { resolvePromoName } from './resolvePromoName';
import PromoApplyControl from './PromoApplyControl';
import { formatRelativeAge, promoDisplayPrice } from './promoDisplayPrice';
import styles from './promociones.module.css';

const NO_TYPES = [];
const NO_NAMES = {};

// A row older than this reads as stale (ML recalculates SMART/PRICE_MATCHING
// candidates daily, so a day-old mirror row may no longer be ML's offer).
const STALE_ROW_MS = 24 * 60 * 60 * 1000;

// SELLER_CAMPAIGN/DEAL/SMART/PRE_NEGOTIATED/PRICE_MATCHING can be enrolled
// via the apply control (FE-C). DOD/LIGHTNING/PRICE_DISCOUNT are read-only
// informational entries. PRICE_MATCHING_MELI_ALL is intentionally EXCLUDED
// (ML-autogestionado, never writable) — its absence here is what keeps it
// read-only; never add it.
const APPLICABLE_TYPES = new Set(['SELLER_CAMPAIGN', 'DEAL', 'SMART', 'PRE_NEGOTIATED', 'PRICE_MATCHING']);

// SMART, PRE_NEGOTIATED and PRICE_MATCHING all carry ML co-funding
// (meli_percentage / seller_percentage in payload); other types don't fund
// the discount.
const CO_FUNDED_TYPES = new Set(['SMART', 'PRE_NEGOTIATED', 'PRICE_MATCHING']);

// Per-type badge hue so each promotion type is visually distinct (no longer
// all-blue). Types not listed (PRICE_DISCOUNT/DOD/LIGHTNING/
// PRICE_MATCHING_MELI_ALL) fall back to the read-only grey badge.
const TYPE_BADGE_CLASS = {
  SELLER_CAMPAIGN: styles.badgeTypeSellerCampaign,
  DEAL: styles.badgeTypeDeal,
  SMART: styles.badgeTypeSmart,
  PRE_NEGOTIATED: styles.badgeTypePreNegotiated,
  PRICE_MATCHING: styles.badgeTypePriceMatching,
};

function formatPercentage(value) {
  if (value === null || value === undefined) return null;
  return `${value}%`;
}

function formatPrice(value) {
  if (value === null || value === undefined) return 'N/A';
  return `$${Number(value).toLocaleString('es-AR')}`;
}

// Backend-computed markup on the promo's effective revenue (server-side
// pricing math). No FE computation — only rendering.
function formatMarkup(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
  return `${Number(value).toFixed(1)}%`;
}

// Formats an ISO date string as short DD/MM (locale-safe, no new deps).
// Returns null when the input isn't a parseable date.
function formatShortDate(isoString) {
  if (!isoString) return null;
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return null;
  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  return `${day}/${month}`;
}

// Compact date range for a promo row; null when either date is missing or
// unparseable (never renders "Invalid Date" or a dash-only string).
function formatDateRange(startDate, finishDate) {
  const start = formatShortDate(startDate);
  const finish = formatShortDate(finishDate);
  if (!start || !finish) return null;
  return `${start} – ${finish}`;
}

// Mirror statuses in the words the PM sees elsewhere in the panel.
const ML_STATUS_LABEL = {
  candidate: 'candidata',
  started: 'activa',
  pending: 'en espera',
  finished: 'finalizada',
};

function formatDateTime(isoString) {
  const day = formatShortDate(isoString);
  if (!day) return null;
  const date = new Date(isoString);
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${day} ${hours}:${minutes}`;
}

// "pedida por X el dd/mm hh:mm" (without the user for a system write).
function describeRequest({ usuario, fecha }) {
  const when = formatDateTime(fecha);
  return `pedida${usuario ? ` por ${usuario}` : ''}${when ? ` el ${when}` : ''}`;
}

function capitalize(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * Level 2 panel: promotions of a single MLA.
 * `onApplied(result)` (optional) means "the data this write touches may have
 * changed": it is called once an apply or remove returned a result, and again
 * (without arguments) at the ~5s and ~65s mirror re-reads, including after a
 * rejected write. A host that shows data the write changes (price, markup) re-reads
 * it; the re-reads are idempotent.
 * `ignoreGlobalFilter` is for a host that is not a Productos tree (the
 * Publicaciones ML side panel): the shared type/name filter belongs to the
 * page whose filter bar sets it, and showing "Sin promos del tipo filtrado"
 * there, with no bar to clear it, would hide promotions with no way out.
 * Lazily fetches `GET /promociones/item/{mla}` on first mount (i.e. on
 * first expand — the parent conditionally mounts this component).
 */
function MlaPromocionesPanel({ mla, promosCacheRef, pullOnOpen = true, ignoreGlobalFilter = false, onApplied }) {
  // The pull endpoint is a READ (it reconciles our mirror from ML and never
  // writes to ML) and requires `promos.ver`. It used to require
  // `promos.escribir`, which left read-only users looking at an unrefreshed
  // mirror with no way to know — part of incident 2026-10-05.
  const { tienePermiso } = usePermisos();
  const canPull = tienePermiso('promos.ver');

  // Opening the panel shows the mirror we ALREADY have, immediately, and pulls fresh state from
  // MercadoLibre in the BACKGROUND (see the effect below). The pull used to run first and block
  // the first paint: one ML round trip per MLA behind a proxy shared with sales-webhook
  // processing, 25-30 s on the first open of a 50-MLA product.
  //
  // Pulling on open is still a deliberate product decision (the owner asked for it: seeing stale
  // promotions without knowing they are stale was the worse failure). Only the ORDER changed: read,
  // show, then pull and re-read. While the pull is in flight apply/remove are locked and an
  // "Actualizando desde ML…" state is visible, so nobody acts on a row the pull may be about to change.
  //
  // `alwaysRefetch` makes a collapse/re-expand genuinely re-read instead of serving the cached
  // mirror. The cache is still WRITTEN — the promo filter bar derives its types from those
  // entries — so bypassing it is not an option, only re-reading it is.
  //
  const readMirror = useCallback((id) => promocionesAPI.getPromocionesItem(id).then((r) => r.data), []);

  // Whether this mount should pull from ML is the PARENT's call, because only it knows why the panel
  // is mounting: a user opening it (pull), a global "Expandir todo" mounting twenty at once (do not —
  // one click must not become twenty concurrent pulls on a throttle shared with sales-webhook
  // processing), or a remount right after the refresh button already pulled (do not — that would
  // pull twice for one click). The post-apply timers and the error-state retry re-read the mirror
  // only: each of those pulling would have added three more ML calls per apply.
  const { data: mirror, loading, error, reload } = useLazyResource(promosCacheRef, mla, readMirror, {
    alwaysRefetch: true,
  });

  // Background pull state. `data` is what the panel shows: the pulled-and-re-read mirror once the
  // pull settled FOR THE MIRROR IT STARTED FROM, otherwise the hook's mirror (a later `reload()`
  // yields a newer object, which wins).
  const [pull, setPull] = useState(null); // { forMla, status: 'running' | 'done', forMirror?, data? }
  const pulledForRef = useRef(null);
  const aliveRef = useRef(true);
  // Id of the latest pull started; a pull that is not the latest when it settles is ignored (the panel
  // moved to another MLA, even one it already pulled before).
  const pullSeqRef = useRef(0);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);
  const pullSettled = pull?.forMla === mla && pull.status === 'done' && pull.forMirror === mirror;
  const data = pullSettled ? pull.data : mirror;
  // The pull is "in flight" from the moment the mirror lands (the effect below starts it in the same
  // commit), so nothing — the ML confirmation, the apply controls — acts in the gap before it.
  const shouldPull = pullOnOpen && canPull;
  const pullPending =
    shouldPull && Boolean(mirror) && !loading && !error && !mirror.motivo_sin_actualizacion && pull?.forMla !== mla;
  const refreshing = (pull?.forMla === mla && pull.status === 'running') || pullPending;
  // The store says ML must not be asked about this publication (not active): show the mirror
  // read-only with the reason and never pull. Absent for active / not-yet-stored publications.
  const motivoSinActualizacion = data?.motivo_sin_actualizacion || null;

  useEffect(() => {
    if (!shouldPull || !mirror || loading || error || mirror.motivo_sin_actualizacion) return;
    if (pulledForRef.current === mla) return;
    pulledForRef.current = mla;
    pullSeqRef.current += 1;
    const pullId = pullSeqRef.current;
    setPull({ forMla: mla, status: 'running' });
    // The pull endpoint is FAIL-SOFT: a dead proxy, an ML timeout or a missing route all come back
    // as HTTP 200 `{ok: false}`, never as a rejection. So `.catch` alone would almost never fire and
    // the panel would show the old mirror as if it had just been refreshed. `ok` is the only honest
    // signal, and both it and the rejection path feed the same `refreshFailed` flag.
    Promise.resolve(promocionesAPI.refreshItemPromociones(mla))
      .then((r) => ({ ok: r?.data?.ok === true, motivo: r?.data?.motivo || null }))
      // A failed refresh degrades to the stored mirror rather than blanking the panel: stale data
      // on a working screen beats an error and nothing.
      .catch(() => ({ ok: false, motivo: null }))
      .then((refresh) => {
        const flags = { refreshFailed: !refresh.ok, refreshMotivo: refresh.motivo };
        return readMirror(mla)
          .then((fresh) => ({ ...fresh, ...flags }))
          .catch(() => ({ ...mirror, ...flags }));
      })
      .then((merged) => {
        // Unmounted, or the panel was pointed at another MLA while this pull was in flight.
        if (!aliveRef.current || pullSeqRef.current !== pullId) return;
        // The filter bar derives its promo types from these entries.
        promosCacheRef.current.set(mla, { status: 'ok', data: merged });
        setPull({ forMla: mla, status: 'done', forMirror: mirror, data: merged });
      });
  }, [shouldPull, mirror, loading, error, mla, promosCacheRef, readMirror]);

  // The error-state retry re-reads the mirror; once it lands, the background pull above runs for it
  // (when this mount is meant to pull), so a retry still refreshes from ML without pulling twice.
  const retry = reload;
  // After our own enroll/remove write the server refreshes on its own
  // (immediate + a ~60s retry-queue drain), and the panel just re-READS that
  // mirror at two points: ~5s (fast SELLER_CAMPAIGN/DEAL/consistency) and ~65s
  // (after the server's ~60s retry drains for slower SMART reconciliation).
  const reloadTimersRef = useRef([]);
  const onAppliedRef = useRef(onApplied);
  useEffect(() => {
    onAppliedRef.current = onApplied;
  }, [onApplied]);
  const storedTypes = usePromoFilterStore((state) => state.selectedTypes);
  const storedNames = usePromoFilterStore((state) => state.selectedNames);
  // Empty selections mean "show all" to `matchesPromoFilter`.
  const selectedTypes = ignoreGlobalFilter ? NO_TYPES : storedTypes;
  const selectedNames = ignoreGlobalFilter ? NO_NAMES : storedNames;

  const clearReloadTimers = useCallback(() => {
    reloadTimersRef.current.forEach((timerId) => clearTimeout(timerId));
    reloadTimersRef.current = [];
  }, []);

  useEffect(() => () => clearReloadTimers(), [clearReloadTimers]);

  // Used for a write that returned a result (`onApplied`) and for one that was
  // rejected (`onReloadNeeded`, no result to hand over): either way the truth
  // lives in the mirror.
  const scheduleMirrorReloads = useCallback(() => {
    // Do NOT assert the final state from either reload alone
    // (eventual consistency — the table stays the source of
    // truth). After a write the server refreshes the mirror on
    // its own (immediate + ~60s retry) and these two reloads
    // only RE-READ it — they do not pull from ML. Opening the
    // panel does pull, which is a different path on purpose.
    //
    // Clear any prior pending timers before scheduling new
    // ones, and clear on unmount so we never call reload()
    // after the panel (and the underlying setState) is gone.
    clearReloadTimers();
    // A host that shows data the write changes (price, markup) re-reads it at the
    // same points: the new price lands in our tables as late as the mirror does.
    const reloadAgain = () => {
      reload();
      onAppliedRef.current?.();
    };
    reloadTimersRef.current = [setTimeout(reloadAgain, 5000), setTimeout(reloadAgain, 65000)];
  }, [clearReloadTimers, reload]);

  // An EMPTY mirror is only "no promos" when ML agrees (incident 2026-10-05:
  // 0 mirror rows, 9 live promos). The mirror read stays fast and mirror-only;
  // the panel asks ML separately AFTER rendering. Keyed by the `data` object
  // so a reload re-asks, and a stale answer for an older read is ignored.
  // A failed refresh already means "unconfirmed": no extra call then.
  // `mlCheckState` is one explicit value: 'idle' (nothing to confirm),
  // 'checking', 'confirmed' or 'unconfirmed'. An answer recorded for another
  // read counts as 'checking' for the current one.
  const [mlCheck, setMlCheck] = useState(null); // { forData, status, promosEnMl }
  const mirrorEmpty = Boolean(data) && !loading && !error && (data.promotions || []).length === 0;
  const needsMlCheck = mirrorEmpty && !data.refreshFailed && !refreshing && !motivoSinActualizacion;
  const mlCheckState = !needsMlCheck ? 'idle' : mlCheck?.forData === data ? mlCheck.status : 'checking';
  const promosEnMl = mlCheckState === 'unconfirmed' ? mlCheck.promosEnMl : null;
  useEffect(() => {
    if (!needsMlCheck) return undefined;
    let ignore = false;
    const forData = data;
    setMlCheck({ forData, status: 'checking', promosEnMl: null });
    Promise.resolve()
      .then(() => promocionesAPI.confirmarSinPromosML(mla))
      .then((r) => {
        if (ignore) return;
        const confirmed = r?.data?.sin_promos_confirmado === true;
        setMlCheck({
          forData,
          status: confirmed ? 'confirmed' : 'unconfirmed',
          promosEnMl: r?.data?.promos_en_ml ?? null,
        });
      })
      .catch(() => {
        if (!ignore) setMlCheck({ forData, status: 'unconfirmed', promosEnMl: null });
      });
    return () => {
      ignore = true;
    };
  }, [needsMlCheck, data, mla]);

  if (loading) {
    return <div className={styles.panelState}>Cargando promociones...</div>;
  }

  if (error) {
    return (
      <div className={styles.panelStateError}>
        Error al cargar promociones.{' '}
        <button type="button" className="btn-tesla outline-subtle-primary sm" onClick={retry}>
          Reintentar
        </button>
      </div>
    );
  }

  const promociones = data?.promotions || [];

  // Only the pull path sets this, so a plain mirror read (read-only user, or a
  // parent that asked not to pull) never claims a failure it did not have.
  // The REASON, when the backend could name one. "No se pudo actualizar"
  // alone is true and useless: a closed publication, an expired token and a
  // proxy outage all read the same, while the real cause sat in a server
  // log. Finding one real case that way took about an hour.
  const staleNotice = data?.refreshFailed ? (
    <div className={styles.staleNotice}>
      {data.refreshMotivo
        ? `No se pudo actualizar desde MercadoLibre: ${data.refreshMotivo}. Mostrando el último estado conocido.`
        : 'No se pudo actualizar desde MercadoLibre — mostrando el último estado conocido.'}
    </div>
  ) : null;

  // Not active (per the store): ML is not asked about it, so what we show is the last state we have.
  const readOnlyNotice = motivoSinActualizacion ? (
    <div className={styles.staleNotice}>{`${motivoSinActualizacion}. Mostrando el último estado conocido (solo lectura).`}</div>
  ) : null;
  const refreshingNotice = refreshing ? (
    <div className={styles.panelState} role="status">
      Actualizando desde ML…
    </div>
  ) : null;
  // Enrolls ML accepted but did not apply, for promos the panel has no row to badge.
  const sinPromo = data?.escrituras_no_aplicadas_sin_promo || [];
  const writesNotice =
    sinPromo.length > 0 ? (
      <div className={styles.staleNotice} role="alert">
        ML no aplicó promociones pedidas:
        <ul className={styles.writeWarningList}>
          {sinPromo.map((w) => (
            <li key={w.promotion_id}>
              {`${w.promotion_id}: ${describeRequest(w)}; ${
                w.mirror_status
                  ? `ML la muestra como ${ML_STATUS_LABEL[w.mirror_status] || w.mirror_status}`
                  : 'ML no la muestra'
              }`}
            </li>
          ))}
        </ul>
      </div>
    ) : null;
  const notices = (
    <>
      {refreshingNotice}
      {readOnlyNotice}
      {staleNotice}
      {writesNotice}
    </>
  );
  // Apply/remove stay locked while the pull may still change the rows, and for a not-active publication.
  const controlsLockedLabel = refreshing ? 'Actualizando desde ML…' : motivoSinActualizacion ? 'Solo lectura' : null;

  if (promociones.length === 0) {
    // An empty mirror is only "no promos" when ML agrees. If the refresh
    // failed, or ML reports promos (or could not be asked), saying
    // "Sin promociones" would be a confident lie — the mirror had 0 rows for
    // an MLA with 9 live promos in the 2026-10-05 incident.
    if (refreshing) {
      return (
        <>
          {notices}
          <div className={styles.panelState}>Sin promociones en el espejo — se confirma al terminar de actualizar.</div>
        </>
      );
    }
    if (motivoSinActualizacion) {
      return (
        <>
          {notices}
          <div className={styles.panelState}>Sin promociones en el último estado conocido.</div>
        </>
      );
    }
    if (!data?.refreshFailed && mlCheckState === 'checking') {
      return (
        <>
          {writesNotice}
          <div className={styles.panelState}>Sin promociones en el espejo — confirmando con ML…</div>
        </>
      );
    }
    if (data?.refreshFailed || mlCheckState !== 'confirmed') {
      return (
        <>
          {staleNotice}
          {writesNotice}
          <div className={styles.staleNotice}>
            No se pudo confirmar con ML — datos posiblemente desactualizados.
            {promosEnMl > 0 ? ` ML informa ${promosEnMl} promociones para esta publicación.` : ''}
          </div>
        </>
      );
    }
    return (
      <>
        {staleNotice}
        {writesNotice}
        <div className={styles.panelState}>Sin promociones habilitadas.</div>
      </>
    );
  }

  // Global filter (client-side only): type narrows first, then name narrows
  // within the permitted types. Nothing selected in either -> show all.
  const filteredPromociones = promociones.filter((promo) =>
    matchesPromoFilter(promo, selectedTypes, selectedNames),
  );

  if (filteredPromociones.length === 0) {
    return (
      <>
        {notices}
        <div className={styles.filterMessage}>Sin promos del tipo filtrado.</div>
      </>
    );
  }

  return (
    <>
      {notices}
      <ul className={styles.promoList}>
        {filteredPromociones.map((promo) => {
          const applicable = APPLICABLE_TYPES.has(promo.promotion_type);
          const sellerPct = formatPercentage(promo.payload?.seller_percentage);
          const meliPct = formatPercentage(promo.payload?.meli_percentage);
          // `price` is 0 for candidate promos (not yet applied); fall back to the
          // suggested discounted price so the row shows the price it WOULD apply
          // at, not $0. Shared with PromoApplyControl, which sends this exact
          // value as `precio_visto` so the backend can refuse a moved offer.
          const effectivePrice = promoDisplayPrice(promo);
          const dateRange = formatDateRange(promo.start_date, promo.finish_date);
          const age = formatRelativeAge(promo.updated_at);
          const ageIsStale = age && Date.now() - Date.parse(promo.updated_at) > STALE_ROW_MS;

          return (
            <li
              key={promo.promotion_id}
              className={`${styles.promoRow} ${applicable ? styles.promoApplicable : styles.promoReadonly}`}
            >
              <span className={`${styles.badge} ${TYPE_BADGE_CLASS[promo.promotion_type] || styles.badgeReadonly}`}>
                {promo.promotion_type || 'N/A'}
              </span>
              {promo.application_status === 'active' && (
                <span className={`${styles.badge} ${styles.badgeApplied}`}>Aplicada</span>
              )}
              {promo.application_status === 'programmed' && (
                <span className={`${styles.badge} ${styles.badgeProgrammed}`}>Programada</span>
              )}
              {promo.application_status === 'pending' && (
                <span className={`${styles.badge} ${styles.badgePending}`}>En espera</span>
              )}
              {promo.escritura_no_aplicada && (
                <span
                  className={`${styles.badge} ${styles.badgeNotApplied}`}
                  title={`${capitalize(describeRequest(promo.escritura_no_aplicada))}; ML la sigue mostrando como ${
                    ML_STATUS_LABEL[promo.status] || promo.status || 'sin estado'
                  }`}
                >
                  {promo.escritura_no_aplicada.accion === 'remove' ? 'ML no la quitó' : 'ML no aplicó la promo'}
                </span>
              )}
              <span className={styles.promoName}>
                {resolvePromoName(promo) || promo.promotion_type || promo.promotion_id}
              </span>
              {dateRange && <span className={styles.promoDates}>{dateRange}</span>}
              <span className={styles.promoPrice}>
                {formatPrice(effectivePrice)}
                {promo.original_price != null && promo.original_price !== effectivePrice && (
                  <span className={styles.promoOriginalPrice}> ({formatPrice(promo.original_price)})</span>
                )}
              </span>
              {CO_FUNDED_TYPES.has(promo.promotion_type) && (sellerPct || meliPct) && (
                <span className={styles.promoSmartCost}>
                  {sellerPct && `Costo vendedor: ${sellerPct}`}
                  {sellerPct && meliPct && ' · '}
                  {meliPct && `Cofinanciación ML: ${meliPct}`}
                </span>
              )}
              <span className={styles.promoMarkup} style={{ color: getMarkupColor(promo.nuestro_markup) }}>
                Tu markup: {formatMarkup(promo.nuestro_markup)}
              </span>
              {age && (
                <span
                  className={ageIsStale ? styles.promoFreshnessStale : styles.promoFreshness}
                  title="Última vez que el espejo de promociones se actualizó desde MercadoLibre"
                >
                  actualizado {age}
                </span>
              )}
              {applicable && controlsLockedLabel && (
                <button type="button" className={styles.applySlot} disabled title={controlsLockedLabel}>
                  {controlsLockedLabel}
                </button>
              )}
              {applicable && !controlsLockedLabel && (
                <PromoApplyControl
                  mla={mla}
                  promotion={promo}
                  onApplied={(result) => {
                    scheduleMirrorReloads();
                    onAppliedRef.current?.(result);
                  }}
                  onReloadNeeded={scheduleMirrorReloads}
                />
              )}
            </li>
          );
          })}
      </ul>
    </>
  );
}

export default MlaPromocionesPanel;
