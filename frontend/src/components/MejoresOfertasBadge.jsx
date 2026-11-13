import { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { BadgePercent } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import { useSSEChannel } from '../hooks/useSSEChannel';
import { useSSE } from '../contexts/SSEContext';
import api from '../services/api';
import { MEJORES_OFERTAS_CHANNEL, mejoresOfertasPath, mejoresOfertasText } from './mejoresOfertas';
import styles from './MejoresOfertasBadge.module.css';

const PUBLICACIONES_ML_PERMISOS = ['productos.ver', 'ml_ops.ver'];
const MIN_FETCH_INTERVAL_MS = 10000;

/**
 * MejoresOfertasBadge - TopBar badge that tells a PM how many of THEIR active
 * publications have better offers, linking to their filtered Publicaciones ML page.
 *
 * Visible only to a PM (the backend answers `pm_id: null` for anyone else) who
 * can open Publicaciones ML, and only while the count is above zero.
 *
 * SSE-driven: re-fetches when the backend publishes `ml-publications:mejores-ofertas`
 * (a `hay_mejores_ofertas` flag changed), at most once per 10 s: a signal inside that
 * window reads once when it ends instead of being dropped. Falls back to 60s polling when
 * SSE is degraded, as FreeShippingBadge does.
 */
export default function MejoresOfertasBadge() {
  const { tienePermiso } = usePermisos();
  const [state, setState] = useState({ pmId: null, count: 0 });
  const [loading, setLoading] = useState(true);
  const { isDegraded } = useSSE();
  const inFlightRef = useRef(false);
  const lastFetchAtRef = useRef(0);
  const trailingRef = useRef(null);

  const canView = PUBLICACIONES_ML_PERMISOS.some((codigo) => tienePermiso(codigo));

  const fetchCount = useCallback(async (options = {}) => {
    const { force = false } = options;
    const wait = MIN_FETCH_INTERVAL_MS - (Date.now() - lastFetchAtRef.current);
    if (inFlightRef.current || (!force && wait > 0)) {
      // A signal inside the window is never dropped: one read runs when the window ends.
      if (!trailingRef.current) {
        trailingRef.current = setTimeout(() => {
          trailingRef.current = null;
          fetchCount({ force: true });
        }, Math.max(wait, 1000));
      }
      return;
    }

    inFlightRef.current = true;
    try {
      const { data } = await api.get('/ml-publications/view/mejores-ofertas/count');
      setState({ pmId: data.pm_id, count: data.count });
      lastFetchAtRef.current = Date.now();
    } catch {
      setState({ pmId: null, count: 0 });
    } finally {
      inFlightRef.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!canView) return;
    fetchCount({ force: true });
  }, [canView, fetchCount]);

  useEffect(() => () => clearTimeout(trailingRef.current), []);

  useSSEChannel(MEJORES_OFERTAS_CHANNEL, () => fetchCount(), { enabled: canView });

  useEffect(() => {
    if (!canView || !isDegraded()) return;
    const interval = setInterval(() => fetchCount({ force: true }), 60000);
    return () => clearInterval(interval);
  }, [canView, isDegraded, fetchCount]);

  const { pmId, count } = state;
  if (!canView || loading || pmId == null || count === 0) return null;

  const text = mejoresOfertasText(count);
  return (
    <Link to={mejoresOfertasPath(pmId)} className={styles.badge} title={text} aria-label={text}>
      <BadgePercent size={18} className={styles.icon} aria-hidden="true" />
      <span className={styles.label}>{text}</span>
      <span className={styles.count}>{count}</span>
    </Link>
  );
}
