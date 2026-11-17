import { useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { promocionesAPI } from '../../services/api';
import { useLazyResource } from '../../hooks/useLazyResource';
import { getMarkupColor } from '../../hooks/useProductosOffsets';
import styles from './promociones.module.css';
import { usePermisos } from '../../contexts/PermisosContext';
import SellInOutMarkupExtra from './SellInOutMarkupExtra';

function formatFechaConsulta(iso) {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString('es-AR');
}

function formatPrice(value) {
  if (value === null || value === undefined) return 'N/A';
  return `$${Number(value).toLocaleString('es-AR')}`;
}

// Backend-computed markup (product decision #8) — this component only
// formats it, it never recomputes it.
function formatMarkup(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
  return `${Number(value).toFixed(1)}%`;
}

function criteriosPutBody(data, sellersExcluidos) {
  return {
    c1_activo: Boolean(data.c1_activo),
    c1_markup_min: data.c1_markup_min ?? null,
    c1_markup_max: data.c1_markup_max ?? null,
    c2_activo: Boolean(data.c2_activo),
    c2_solo_markup_positivo: data.c2_solo_markup_positivo !== false,
    c6_activo: Boolean(data.c6_activo),
    c6_solo_via_promo: Boolean(data.c6_solo_via_promo),
    c6_gap_min: data.c6_gap_min ?? 5000,
    c6_distancia_objetivo: data.c6_distancia_objetivo ?? 100,
    auto_aplicacion: Boolean(data.auto_aplicacion),
    sellers_excluidos: sellersExcluidos,
  };
}

/**
 * Catalog-competition panel for one MLA
 * (promos-catalog-prices-and-official-store, slice C2).
 *
 * Reads the LATEST STORED snapshot on mount via
 * `GET /promociones/catalogo-competencia/{mla}` — cheap (our own DB, no
 * ML-webhook call). It NEVER auto-fetches a FRESH snapshot: that only
 * happens from the explicit refresh button below, which is per-MLA only
 * (product decision #4 — the ML throttle is global and shared with
 * sales-webhook processing).
 *
 * Variants:
 *  - `undercutting` (default): same-bucket AND strictly cheaper (product
 *    decision #6 / Productos tree).
 *  - `ranking`: full same-bucket list any price (publication Promos col 2).
 *    Checkboxes (promos.escribir) persist `sellers_excluidos` — unchecked
 *    rivals do not count for C2/C6/R-AUTO.
 *
 * This component never recomputes bucket membership, currency conversion,
 * or markup — those come from the snapshot.
 */
function CatalogCompetitionPanel({ mla, catalogCompetitionCacheRef, variant = 'undercutting' }) {
  const ranking = variant === 'ranking';
  const fetcher = (id) => promocionesAPI.getCompetenciaCatalogo(id).then((r) => r.data);
  const { data, loading, error, reload } = useLazyResource(catalogCompetitionCacheRef, mla, fetcher);
  const { tienePermiso } = usePermisos();
  // Catalog snapshot refresh is gated on promos.ver (same as the GET): it
  // pulls MeLi into our DB, it does not enroll/remove a promotion.
  const canRefresh = tienePermiso('promos.ver');
  const canWriteCriterios = tienePermiso('promos.escribir');
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState(false);
  const [criterios, setCriterios] = useState(null);
  const [excluded, setExcluded] = useState(() => new Set());
  const [criteriosLoading, setCriteriosLoading] = useState(false);
  const [criteriosError, setCriteriosError] = useState(null);
  const [tilting, setTilting] = useState(false);
  const [tiltError, setTiltError] = useState(null);
  // Bumped on MLA change and on toggle so a late GET cannot overwrite optimistic PUT state.
  const criteriosGenRef = useRef(0);

  useEffect(() => {
    if (!ranking || !mla) return undefined;
    let cancelled = false;
    const gen = ++criteriosGenRef.current;
    setCriteriosLoading(true);
    setCriteriosError(null);
    promocionesAPI
      .getHayMejoresCriterios(mla)
      .then((res) => {
        if (cancelled || gen !== criteriosGenRef.current) return;
        const body = res.data || {};
        setCriterios(body);
        setExcluded(new Set(Array.isArray(body.sellers_excluidos) ? body.sellers_excluidos : []));
      })
      .catch(() => {
        if (cancelled || gen !== criteriosGenRef.current) return;
        setCriterios(null);
        setExcluded(new Set());
        setCriteriosError('No se pudieron cargar quién cuenta en el ranking');
      })
      .finally(() => {
        if (!cancelled && gen === criteriosGenRef.current) setCriteriosLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ranking, mla]);

  const handleRefresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    setRefreshError(false);
    try {
      await promocionesAPI.refreshCompetenciaCatalogo(mla);
      catalogCompetitionCacheRef.current.delete(mla);
      reload();
    } catch {
      setRefreshError(true);
    } finally {
      setRefreshing(false);
    }
  };

  const handleToggleRival = async (itemId, nextChecked) => {
    if (!canWriteCriterios || !itemId || tilting || criteriosLoading || itemId === mla) return;
    const previous = new Set(excluded);
    const next = new Set(excluded);
    if (nextChecked) next.delete(itemId);
    else next.add(itemId);
    const list = Array.from(next);
    criteriosGenRef.current += 1;
    setExcluded(next);
    setTiltError(null);
    setTilting(true);
    try {
      let base = criterios;
      if (!base) {
        const res = await promocionesAPI.getHayMejoresCriterios(mla);
        base = res.data || {};
        setCriterios(base);
      }
      const res = await promocionesAPI.putHayMejoresCriterios(mla, criteriosPutBody(base, list));
      setCriterios(res.data || base);
    } catch {
      setExcluded(previous);
      setTiltError('No se pudo guardar quién cuenta');
    } finally {
      setTilting(false);
    }
  };

  const refreshButton = !canRefresh ? null : ranking ? (
    <button
      type="button"
      className="btn-tesla outline-subtle-primary sm"
      onClick={handleRefresh}
      disabled={refreshing}
      aria-label={`Actualizar competencia de catálogo de ${mla}`}
    >
      <RefreshCw size={14} aria-hidden="true" />
      {refreshing ? 'Actualizando…' : 'Actualizar'}
    </button>
  ) : (
    <button
      type="button"
      className="btn-tesla outline-subtle-primary icon-only sm"
      onClick={handleRefresh}
      disabled={refreshing}
      aria-label={`Refrescar competencia de catálogo de ${mla}`}
    >
      <RefreshCw size={14} />
    </button>
  );

  if (loading) {
    return <div className={styles.panelState}>Cargando competencia de catálogo...</div>;
  }

  if (error) {
    return (
      <div className={styles.panelStateError}>
        Error al cargar competencia de catálogo.{' '}
        <button type="button" className="btn-tesla ghost sm" onClick={reload}>
          Reintentar
        </button>
      </div>
    );
  }

  const fetchStatus = data?.fetch_status || 'never';
  const fechaLabel = formatFechaConsulta(data?.fecha_consulta);

  if (fetchStatus === 'never') {
    return (
      <div className={styles.panelState}>
        Sin consultar todavía. {refreshButton}
        {refreshing && <span className={styles.provisionalPending}>Consultando…</span>}
        {refreshError && <span className={styles.feedbackError}>No se pudo consultar</span>}
      </div>
    );
  }

  if (fetchStatus === 'not_catalog') {
    return (
      <div className={styles.panelState}>
        No aplica: esta publicación no pertenece a un catálogo de MercadoLibre.
        {fechaLabel && <span className={styles.treeNodeSummaryCounts}> (consultado {fechaLabel})</span>}
      </div>
    );
  }

  if (fetchStatus === 'error') {
    return (
      <div className={styles.panelStateError}>
        Error al consultar competencia de catálogo{data.error_detail ? `: ${data.error_detail}` : ''}. {refreshButton}
        {refreshing && <span className={styles.provisionalPending}>Reintentando…</span>}
        {refreshError && <span className={styles.feedbackError}>No se pudo consultar</span>}
      </div>
    );
  }

  const rows = ranking ? data.same_bucket || [] : data.undercutting || [];
  const emptyCopy = ranking
    ? `Sin competidores en tu mismo formato${
        data.competitor_count > 0
          ? ` (${data.competitor_count} competidores relevados, ocultos por formato distinto o no comparables)`
          : ''
      }.`
    : `Sin competidores más baratos en tu mismo formato${
        data.competitor_count > 0
          ? ` (${data.competitor_count} competidores relevados, ocultos por formato distinto o no comparables)`
          : ''
      }.`;

  let effectivePos = 0;

  return (
    <div>
      <div className={ranking ? styles.rankingToolbar : styles.filterMessage}>
        {ranking ? (
          <>
            <span className={styles.rankingUpdated}>
              {fechaLabel
                ? `Última actualización del catálogo: ${fechaLabel}`
                : 'Sin fecha de consulta en el snapshot'}
            </span>
            {data.our_price != null && (
              <span className={styles.treeNodeSummaryCounts}>Nuestro precio: {formatPrice(data.our_price)}</span>
            )}
          </>
        ) : (
          <>
            {fechaLabel && <span className={styles.treeNodeSummaryCounts}>Consultado {fechaLabel}</span>}
            {data.our_price != null && (
              <span className={styles.treeNodeSummaryCounts}> · Nuestro precio: {formatPrice(data.our_price)}</span>
            )}
          </>
        )}
        {refreshButton}
        {!ranking && refreshing && <span className={styles.provisionalPending}>Consultando…</span>}
        {refreshError && <span className={styles.feedbackError}>No se pudo consultar</span>}
      </div>
      {ranking && (
        <p className={styles.rankingHint}>
          Destildá quien no cuente para ganar catálogo / monopolio. Los nuevos en un refresh vuelven tildados.
        </p>
      )}
      {ranking && criteriosLoading && (
        <p className={styles.rankingHint}>Cargando quién cuenta…</p>
      )}
      {criteriosError && (
        <p className={styles.feedbackError} role="alert">
          {criteriosError}
        </p>
      )}
      {tiltError && (
        <p className={styles.feedbackError} role="alert">
          {tiltError}
        </p>
      )}
      {rows.length === 0 ? (
        <div className={styles.panelState}>{emptyCopy}</div>
      ) : ranking ? (
        <ol className={styles.rankingList} aria-label="Ranking del catálogo en este tramo">
          {rows.map((competitor, index) => {
            const ours = competitor.item_id === mla;
            const itemId = competitor.item_id;
            const counts = ours || !itemId || !excluded.has(itemId);
            if (counts) effectivePos += 1;
            const posLabel = counts ? String(effectivePos) : '—';
            return (
              <li
                key={itemId || competitor.seller_id || `competitor-${index}`}
                className={`${styles.rankingRow}${ours ? ` ${styles.rankingOurs}` : ''}${
                  counts ? '' : ` ${styles.rankingExcluded}`
                }`}
              >
                <label className={styles.rankingCheck}>
                  <input
                    type="checkbox"
                    checked={counts}
                    disabled={ours || !canWriteCriterios || tilting || criteriosLoading || !itemId}
                    aria-label={
                      ours
                        ? 'Tu publicación (siempre cuenta)'
                        : `Contar a ${competitor.seller_nickname || itemId || 'competidor'}`
                    }
                    onChange={(e) => handleToggleRival(itemId, e.target.checked)}
                  />
                </label>
                <span className={styles.rankingPos}>{posLabel}</span>
                <span className={styles.rankingName}>
                  {competitor.seller_nickname || itemId || 'Competidor'}
                  {ours ? ' (vos)' : ''}
                </span>
                <span className={styles.rankingPrice}>{formatPrice(competitor.price_ars ?? competitor.price)}</span>
                <span className={styles.rankingMarkup} style={{ color: getMarkupColor(competitor.markup) }}>
                  {formatMarkup(competitor.markup)}
                  <SellInOutMarkupExtra value={competitor.markup_sell_in_out} />
                </span>
              </li>
            );
          })}
        </ol>
      ) : (
        <ul className={styles.promoList}>
          {rows.map((competitor, index) => (
            // item_id and seller_id are both Optional in the schema, so the
            // index is the last-resort tiebreaker: two competitors missing
            // both would otherwise collide on the same React key.
            <li
              key={competitor.item_id || competitor.seller_id || `competitor-${index}`}
              className={styles.promoRow}
            >
              <span className={styles.promoName}>
                {competitor.seller_nickname || competitor.item_id || 'Competidor'}
              </span>
              <span className={styles.promoPrice}>{formatPrice(competitor.price_ars ?? competitor.price)}</span>
              <span className={styles.promoMarkup} style={{ color: getMarkupColor(competitor.markup) }}>
                Tu markup si igualás: {formatMarkup(competitor.markup)}
                <SellInOutMarkupExtra value={competitor.markup_sell_in_out} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default CatalogCompetitionPanel;
