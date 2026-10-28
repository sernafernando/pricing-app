import { useEffect, useState } from 'react';
import api from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { formatPrice } from './formatPrice';
import styles from '../../pages/ParaGanarAdvisor.module.css';

export default function ParaGanarAdvisorDetail({ selected }) {
  const { tienePermiso } = usePermisos();
  const canRefresh = tienePermiso('productos.editar_precios');

  const [board, setBoard] = useState(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!selected?.mla) {
      setBoard(null);
      setError(null);
      return undefined;
    }

    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const { data } = await api.get(
          `/para-ganar/criterios/${encodeURIComponent(selected.mla)}/sugerencia`,
        );
        if (!cancelled) setBoard(data);
      } catch (err) {
        if (cancelled) return;
        setBoard(null);
        if (err.response?.status === 403) {
          setError('No tenés permiso para ver la sugerencia.');
        } else if (err.response?.status === 404) {
          setError('MLA no encontrada.');
        } else {
          setError('No se pudo calcular el tablero TOP.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [selected?.mla]);

  const onRefreshCompetition = async () => {
    if (!selected?.mla || !canRefresh || refreshing) return;
    setRefreshing(true);
    setError(null);
    try {
      const { data } = await api.post(
        `/para-ganar/criterios/${encodeURIComponent(selected.mla)}/competencia/refresh`,
      );
      setBoard(data);
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (typeof detail === 'string') {
        setError(detail);
      } else if (err.response?.status === 403) {
        setError('No tenés permiso para actualizar competencia (productos.editar_precios).');
      } else {
        setError('No se pudo actualizar la competencia de catálogo.');
      }
    } finally {
      setRefreshing(false);
    }
  };

  const showRefresh =
    Boolean(selected?.mla) &&
    Boolean(board) &&
    (board.needs_competition_refresh || Boolean(board.catalog_product_id));

  return (
    <aside className={styles.detail} aria-label="Detalle de sugerencia">
      <div className={styles.panelTitle}>Detalle</div>
      {!selected && (
        <div className={styles.emptyState}>
          <p className={styles.emptyTitle}>Seleccioná un MLA</p>
          <p className={styles.emptyBody}>
            Acá aparece el precio sugerido (PARA GANAR) y el tablero TOP. Aplicar
            promo llega después.
          </p>
        </div>
      )}
      {selected && (
        <div className={styles.criteriaPanel}>
          <div className={styles.criteriaIdentity}>
            <div className={styles.mla}>{selected.mla}</div>
            <div className={styles.criteriaIdentityMeta}>
              {selected.codigo || '—'} · {selected.lista_nombre || 'Sin lista'}
            </div>
          </div>

          {loading && <p className={styles.emptyBody}>Calculando posiciones…</p>}
          {error && (
            <p className={styles.criteriaFeedbackError} role="alert">
              {error}
            </p>
          )}
          {board?.message && (
            <p className={styles.sellersNotice} role="status">
              {board.message}
            </p>
          )}

          {showRefresh && (
            <button
              type="button"
              className={
                board.needs_competition_refresh
                  ? styles.saveCriteriaBtn
                  : styles.secondaryActionBtn
              }
              disabled={!canRefresh || refreshing || loading}
              onClick={onRefreshCompetition}
              title={
                canRefresh
                  ? 'Trae precios de sellers del catálogo vía ML (una MLA por vez)'
                  : 'Requiere productos.editar_precios'
              }
            >
              {refreshing
                ? 'Actualizando competencia…'
                : board.needs_competition_refresh
                  ? 'Actualizar competencia de catálogo'
                  : 'Refrescar snapshot de competencia'}
            </button>
          )}

          {board && !loading && !board.needs_competition_refresh && (
            <>
              <dl className={styles.detailList}>
                <div>
                  <dt>Nuestro precio</dt>
                  <dd>$ {formatPrice(board.our_price ?? selected.precio)}</dd>
                </div>
                <div>
                  <dt>Nuestra posición</dt>
                  <dd>
                    {board.our_rank != null
                      ? `#${board.our_rank} de TOP ${board.top_sellers}`
                      : '—'}
                    {board.in_top
                      ? ' · dentro del TOP'
                      : board.our_rank != null
                        ? ' · fuera del TOP'
                        : ''}
                  </dd>
                </div>
                <div>
                  <dt>Catálogo</dt>
                  <dd>{board.catalog_product_id || '—'}</dd>
                </div>
                {board.bucket_label ? (
                  <div>
                    <dt>Competís en</dt>
                    <dd>{board.bucket_label}</dd>
                  </div>
                ) : null}
                {board.precio_sugerido != null ? (
                  <div>
                    <dt>Precio sugerido</dt>
                    <dd>
                      $ {formatPrice(board.precio_sugerido)}
                      {board.suggestion_status === 'winning'
                        ? ' · ganando'
                        : board.suggestion_status === 'losing'
                          ? ' · perdiendo'
                          : ''}
                      {board.referent_nickname
                        ? ` · ref. ${board.referent_nickname}`
                        : ''}
                    </dd>
                  </div>
                ) : null}
                {board.delta_ars != null ? (
                  <div>
                    <dt>
                      {board.suggestion_status === 'winning' ? 'Holgura' : 'Delta'}
                    </dt>
                    <dd
                      className={
                        board.delta_ars < 0
                          ? styles.deltaNeg
                          : board.delta_ars > 0
                            ? styles.deltaPos
                            : undefined
                      }
                    >
                      {board.delta_ars > 0 ? '+' : ''}
                      $ {formatPrice(board.delta_ars)}
                      {board.suggestion_status === 'winning'
                        ? ' hasta el 2º'
                        : board.suggestion_status === 'losing'
                          ? ' vs referente'
                          : ''}
                    </dd>
                  </div>
                ) : null}
              </dl>

              {board.positions?.length > 0 ? (
                <ol className={styles.topBoard} aria-label="Posiciones TOP de precio">
                  {board.positions.map((pos) => (
                    <li key={`${pos.rank}-${pos.price_ars}`} className={styles.topBoardRow}>
                      <div className={styles.topBoardRank}>#{pos.rank}</div>
                      <div className={styles.topBoardBody}>
                        <div className={styles.topBoardPrice}>
                          $ {formatPrice(pos.price_ars)}
                          {pos.seller_count > 1 ? ` · ${pos.seller_count} sellers` : ''}
                        </div>
                        <ul className={styles.topBoardSellers}>
                          {pos.sellers.map((s) => (
                            <li key={s.seller_id}>
                              {s.is_us ? (
                                <strong>Nosotros</strong>
                              ) : (
                                s.nickname || `Seller ${s.seller_id}`
                              )}
                              {(s.listing_label || board.bucket_label) && (
                                <span className={styles.topBoardTipo}>
                                  {' '}
                                  · {s.listing_label || board.bucket_label}
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      </div>
                    </li>
                  ))}
                </ol>
              ) : (
                !board.message && (
                  <p className={styles.emptyBody}>
                    No hay precios comparables en el snapshot para armar el TOP.
                  </p>
                )
              )}
            </>
          )}
        </div>
      )}
    </aside>
  );
}
