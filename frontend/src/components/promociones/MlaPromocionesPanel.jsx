import { useCallback, useEffect, useRef, useState } from 'react';
import { promocionesAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { useLazyResource } from '../../hooks/useLazyResource';
import { usePromoFilterStore } from '../../store/promoFilterStore';
import { matchesPromoFilter } from './promoFilterPredicate';
import { buildMlSellerPromosUrl } from '../../utils/mlSellerPanel';
import { resolvePromoName } from './resolvePromoName';
import PromoApplyControl from './PromoApplyControl';
import { formatRelativeAge, promoDisplayPrice } from './promoDisplayPrice';
import { forgetPromoEmptyConfirmed, forgetPromoPull, markPromoEmptyConfirmed, promoEmptyConfirmedRecently, promoPullGeneration } from './promoPullTtl';
import SellInOutMarkupExtra from './SellInOutMarkupExtra';
import {
  APPLICABLE_PROMOTION_TYPES as APPLICABLE_TYPES,
  COFUNDED_PROMOTION_TYPES as CO_FUNDED_TYPES,
} from './applicablePromoTypes';
import styles from './promociones.module.css';

// A row older than this reads as stale (ML recalculates SMART/PRICE_MATCHING
// candidates daily, so a day-old mirror row may no longer be ML's offer).
const STALE_ROW_MS = 24 * 60 * 60 * 1000;

// Per-type badge hue so each promotion type is visually distinct (no longer
// all-blue). Types not listed (PRICE_DISCOUNT/DOD/PRICE_MATCHING_MELI_ALL)
// fall back to the neutral grey badge, like SMART_LIGHTNING (all read-only).
const TYPE_BADGE_CLASS = {
  SELLER_CAMPAIGN: styles.badgeTypeSellerCampaign,
  DEAL: styles.badgeTypeDeal,
  SMART: styles.badgeTypeSmart,
  PRE_NEGOTIATED: styles.badgeTypePreNegotiated,
  PRICE_MATCHING: styles.badgeTypePriceMatching,
  LIGHTNING: styles.badgeTypeLightning,
  SMART_LIGHTNING: styles.badgeTypeSmartLightning,
};

// The row's markup tone, on the same thresholds as `getMarkupColor` (useProductosOffsets): none -> muted,
// negative -> danger, under 1% -> warning, else success.
function markupToneClass(markup) {
  if (markup === null || markup === undefined) return styles.rowMarkupNone;
  if (markup < 0) return styles.rowMarkupNegative;
  if (markup < 1) return styles.rowMarkupLow;
  return styles.rowMarkupPositive;
}

// The column header over the sectioned rows (Publicaciones ML panel); the rows carry the same grid.
const COLUMNS = ['Tipo', 'Promoción', 'Precio', 'Tu markup', 'Estado', 'Acción'];

function ColumnHeader() {
  return (
    <div className={styles.promoColumns} data-testid="promo-columns" aria-hidden="true">
      {COLUMNS.map((label) => (
        <span key={label}>{label}</span>
      ))}
    </div>
  );
}

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

// ML's seller coupon (captured in backend/tests/fixtures/ml_publications/history_events_MLA1402898289_20261016.json):
// a buyer's discount code, not a price promotion, and it cannot be applied from here (owner: "en promos hay promos
// que no son promos sino cupones y no se pueden activar desde ahí").
const COUPON_TYPE = 'SELLER_COUPON_CAMPAIGN';

// The Publicaciones ML panel's sections (S3), in order; one with nothing in it is left out.
const SECTIONS = [
  { key: 'active', title: 'Activa ahora' },
  { key: 'available', title: 'Disponibles para activar' },
  { key: 'other', title: 'Otras promociones' },
  { key: 'coupons', title: 'Cupones' },
];

/** The section a promotion belongs in: a coupon; the one active now; a candidate this app can apply and has not
 * scheduled (no `application_status`); else the rest -- programmed, waiting (these keep their Desaplicar), those ML
 * manages, and any other applicable row (its control still shows: the type decides it, not the section). */
function sectionOf(promo) {
  if (promo.promotion_type === COUPON_TYPE) return 'coupons';
  if (promo.application_status === 'active') return 'active';
  if (promo.status === 'candidate' && !promo.application_status && APPLICABLE_TYPES.has(promo.promotion_type)) return 'available';
  return 'other';
}

/** The promotions by section, each in its `sectionOf`. */
function groupPromotions(promotions) {
  const groups = { active: [], available: [], other: [], coupons: [] };
  for (const promo of promotions) groups[sectionOf(promo)].push(promo);
  return groups;
}

/**
 * A coupon, read-only: its name, dates and -- only when ML's object carries it as captured (`fixed_percentage`) -- its
 * percentage, with a link to the publication's promotions in Mercado Libre. No price nor markup: a coupon is not a
 * price this app sets. A row in any other shape shows what it has and nothing guessed.
 */
function CouponRow({ promo, mla }) {
  const percentage = promo.payload?.fixed_percentage;
  const dateRange = formatDateRange(promo.start_date, promo.finish_date);
  const url = buildMlSellerPromosUrl(mla);
  return (
    <li className={styles.couponRow}>
      <span className={styles.couponMain}>
        <span className={styles.promoName}>{resolvePromoName(promo) || promo.promotion_id}</span>
        {dateRange && <span className={styles.promoDates}>{dateRange}</span>}
      </span>
      {typeof percentage === 'number' && (
        <span className={styles.couponDiscount}>{formatPercentage(percentage)} de descuento</span>
      )}
      {url && (
        <a className={styles.couponLink} href={url} target="_blank" rel="noopener noreferrer">
          Ver promociones en Mercado Libre
        </a>
      )}
    </li>
  );
}

/**
 * Level 2 panel: promotions of a single MLA.
 * `onApplied(result)` (optional) means "the data this write touches may have
 * changed": it is called once an apply or remove returned a result, and again
 * (without arguments) at the ~5s and ~65s mirror re-reads, including after a
 * rejected write. A host that shows data the write changes (price, markup) re-reads
 * it; the re-reads are idempotent.
 * `onPulled(mla, startedOn)` (optional) is called once a background pull ML
 * answered settles for this mount (not on a failed or abandoned one), with the
 * `promoPullGeneration` it started on.
 * `suggestedPromotionIds` (optional) are the promotions the host's "Hay candidatas mejores" block
 * suggests; their rows carry a "Sugerida" chip.
 * `sections` (the same host) splits them into Activa ahora, Disponibles para activar, Otras promociones and, last
 * and quieter, Cupones (S3); a Productos tree keeps its one list.
 * Lazily fetches `GET /promociones/item/{mla}` on first mount (i.e. on
 * first expand — the parent conditionally mounts this component).
 */
function MlaPromocionesPanel({
  mla,
  promosCacheRef,
  pullOnOpen = true,
  suggestedPromotionIds,
  sections = false,
  onApplied,
  onPulled,
}) {
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
  const onPulledRef = useRef(onPulled);
  useEffect(() => {
    onPulledRef.current = onPulled;
  }, [onPulled]);
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
    const startedOn = promoPullGeneration(mla);
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
        // Only a pull ML answered, and that this mount still wanted, counts as done.
        if (merged.refreshFailed) return;
        // What ML has was just re-read: an earlier "no promotions" answer no longer stands, whatever the host.
        forgetPromoEmptyConfirmed(mla);
        onPulledRef.current?.(mla, startedOn);
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
  // The global type/name filter; every host renders its filter bar, so a filtered-out promotion has a way back.
  // Empty selections mean "show all" to `matchesPromoFilter`.
  const selectedTypes = usePromoFilterStore((state) => state.selectedTypes);
  const selectedNames = usePromoFilterStore((state) => state.selectedNames);

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
    // A write changes this MLA's promotions: the next open pulls again, whichever host ran it.
    forgetPromoPull(mla);
    // A host that shows data the write changes (price, markup) re-reads it at the
    // same points: the new price lands in our tables as late as the mirror does.
    const reloadAgain = () => {
      reload();
      onAppliedRef.current?.();
    };
    reloadTimersRef.current = [setTimeout(reloadAgain, 5000), setTimeout(reloadAgain, 65000)];
  }, [clearReloadTimers, reload, mla]);

  // An EMPTY mirror is only "no promos" when ML agrees (incident 2026-10-05:
  // 0 mirror rows, 9 live promos). The mirror read stays fast and mirror-only;
  // the panel asks ML separately AFTER rendering. Keyed by the `data` object
  // so a reload re-asks (unless ML confirmed "none" less than 5 minutes ago,
  // `promoPullTtl`), and a stale answer for an older read is ignored.
  // A failed refresh already means "unconfirmed": no extra call then.
  // `mlCheckState` is one explicit value: 'idle' (nothing to confirm),
  // 'checking', 'confirmed' or 'unconfirmed'. An answer recorded for another
  // read counts as 'checking' for the current one.
  const [mlCheck, setMlCheck] = useState(null); // { forData, status, promosEnMl }
  const mirrorEmpty = Boolean(data) && !loading && !error && (data.promotions || []).length === 0;
  const askMl = mirrorEmpty && !data.refreshFailed && !refreshing && !motivoSinActualizacion;
  // ML confirmed this MLA has none less than 5 minutes ago (`promoPullTtl`): no second live call.
  const confirmedRecently = askMl && promoEmptyConfirmedRecently(mla);
  const needsMlCheck = askMl && !confirmedRecently;
  const mlCheckState = confirmedRecently
    ? 'confirmed'
    : !needsMlCheck
      ? 'idle'
      : mlCheck?.forData === data
        ? mlCheck.status
        : 'checking';
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
        if (confirmed) markPromoEmptyConfirmed(mla);
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

  // One promotion's row; the list (or each section) maps it.
  const renderRow = (promo) => {
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
        className={`${styles.promoGridRow} ${promo.application_status === 'active' ? styles.promoGridRowActive : ''}`}
      >
        <span className={styles.promoTypeCell}>
          <span className={`${styles.badge} ${TYPE_BADGE_CLASS[promo.promotion_type] || styles.badgeTypeNeutral}`}>
            {promo.promotion_type || 'N/A'}
          </span>
          {suggestedPromotionIds?.includes(promo.promotion_id) && (
            <span className={`${styles.badge} ${styles.badgeSuggested}`}>Sugerida</span>
          )}
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
        </span>
        <span className={styles.promoMain}>
          <span className={styles.promoName}>
            {resolvePromoName(promo) || promo.promotion_type || promo.promotion_id}
          </span>
          {dateRange && <span className={styles.promoDates}>{dateRange}</span>}
          {CO_FUNDED_TYPES.has(promo.promotion_type) && (sellerPct || meliPct) && (
            <span className={styles.promoSmartCost}>
              {sellerPct && `Costo vendedor: ${sellerPct}`}
              {sellerPct && meliPct && ' · '}
              {meliPct && `Cofinanciación ML: ${meliPct}`}
            </span>
          )}
        </span>
        <span className={styles.promoPrice}>
          <span>{formatPrice(effectivePrice)}</span>
          {promo.original_price != null && promo.original_price !== effectivePrice && (
            <s className={styles.promoOriginalPrice}>{formatPrice(promo.original_price)}</s>
          )}
        </span>
        <span className={`${styles.promoMarkup} ${markupToneClass(promo.nuestro_markup)}`}>
          <span className={styles.markupLabel}>Tu markup: </span>
          {formatMarkup(promo.nuestro_markup)}
          <SellInOutMarkupExtra value={promo.markup_sell_in_out} />
        </span>
        <span className={styles.promoStatusCell}>
          {age && (
            <span
              className={ageIsStale ? styles.promoFreshnessStale : styles.promoFreshness}
              title="Última vez que el espejo de promociones se actualizó desde MercadoLibre"
            >
              actualizado {age}
            </span>
          )}
        </span>
        <span className={styles.promoAction}>
          {!applicable && <span className={styles.actionNote}>Lo maneja ML</span>}
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
        </span>
      </li>
    );
  };

  if (!sections) {
    return (
      <>
        {notices}
        <ul className={`${styles.promoList} ${styles.promoGridList}`}>{filteredPromociones.map(renderRow)}</ul>
      </>
    );
  }

  const groups = groupPromotions(filteredPromociones);
  // The column header goes once, over the first section of promotion rows shown (coupons have their own row).
  const headedSection = SECTIONS.find(({ key }) => key !== 'coupons' && groups[key].length > 0)?.key;
  return (
    <>
      {notices}
      {SECTIONS.map(({ key, title }) =>
        groups[key].length === 0 ? null : (
          <section key={key} className={key === 'coupons' ? styles.couponSection : styles.promoSection} aria-label={title}>
            <h4 className={styles.sectionTitle}>{title}</h4>
            {key === headedSection && <ColumnHeader />}
            <ul className={styles.promoList}>
              {key === 'coupons' ? groups[key].map((promo) => <CouponRow key={promo.promotion_id} promo={promo} mla={mla} />) : groups[key].map(renderRow)}
            </ul>
          </section>
        ),
      )}
    </>
  );
}

export default MlaPromocionesPanel;
