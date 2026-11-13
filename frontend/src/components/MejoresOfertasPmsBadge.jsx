import { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Users } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import { useSSEChannel } from '../hooks/useSSEChannel';
import { useSSE } from '../contexts/SSEContext';
import api from '../services/api';
import { MEJORES_OFERTAS_CHANNEL, PERMISO_MEJORES_OFERTAS_PMS, mejoresOfertasPath } from './mejoresOfertas';
import styles from './MejoresOfertasPmsBadge.module.css';

const MIN_FETCH_INTERVAL_MS = 10000;
const EMPTY = { pms: [], total: 0 };

/**
 * MejoresOfertasPmsBadge - TopBar notifier for whoever reviews the PMs
 * (`alertas.ver_mejores_ofertas_pms`): the total of every PM's active publications
 * with better offers, and a popover with each PM and their own count. A PM's row
 * opens that PM's filtered Publicaciones ML page (the same link and count as the
 * PM's own MejoresOfertasBadge). Hidden while nobody has anything to review.
 *
 * Refreshes on the same SSE channel as the PM's badge, at most once per 10 s
 * (a signal inside the window reads once when it ends); 60 s polling while SSE is degraded.
 */
export default function MejoresOfertasPmsBadge() {
  const { tienePermiso } = usePermisos();
  const [data, setData] = useState(EMPTY);
  const [open, setOpen] = useState(false);
  const { isDegraded } = useSSE();
  const inFlightRef = useRef(false);
  const lastFetchAtRef = useRef(0);
  const trailingRef = useRef(null);
  const wrapperRef = useRef(null);

  const canView = tienePermiso(PERMISO_MEJORES_OFERTAS_PMS);

  const fetchCounts = useCallback(async (options = {}) => {
    const { force = false } = options;
    const wait = MIN_FETCH_INTERVAL_MS - (Date.now() - lastFetchAtRef.current);
    if (inFlightRef.current || (!force && wait > 0)) {
      if (!trailingRef.current) {
        trailingRef.current = setTimeout(() => {
          trailingRef.current = null;
          fetchCounts({ force: true });
        }, Math.max(wait, 1000));
      }
      return;
    }
    inFlightRef.current = true;
    try {
      const { data: body } = await api.get('/ml-publications/view/mejores-ofertas/por-pm');
      setData({ pms: body.pms ?? [], total: body.total ?? 0 });
      lastFetchAtRef.current = Date.now();
    } catch {
      setData(EMPTY);
    } finally {
      inFlightRef.current = false;
    }
  }, []);

  useEffect(() => {
    if (!canView) return;
    fetchCounts({ force: true });
  }, [canView, fetchCounts]);

  useEffect(() => () => clearTimeout(trailingRef.current), []);

  useSSEChannel(MEJORES_OFERTAS_CHANNEL, () => fetchCounts(), { enabled: canView });

  useEffect(() => {
    if (!canView || !isDegraded()) return;
    const interval = setInterval(() => fetchCounts({ force: true }), 60000);
    return () => clearInterval(interval);
  }, [canView, isDegraded, fetchCounts]);

  useEffect(() => {
    if (!open) return;
    const handleDocClick = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) setOpen(false);
    };
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('click', handleDocClick);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('click', handleDocClick);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  if (!canView || data.total === 0) return null;

  const label = `Promos mejores por PM: ${data.total} en total`;
  return (
    <div ref={wrapperRef} className={styles.wrapper}>
      <button
        type="button"
        className={styles.badge}
        onClick={() => setOpen((prev) => !prev)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={label}
        title={label}
      >
        <Users size={18} className={styles.icon} aria-hidden="true" />
        <span className={styles.count}>{data.total}</span>
      </button>

      {open && (
        <div className={styles.popover} role="dialog" aria-label="Promos mejores por PM">
          <div className={styles.header}>Promos mejores por PM</div>
          <ul className={styles.rows}>
            {data.pms.map((pm) => (
              <li key={pm.pm_id}>
                <Link
                  to={mejoresOfertasPath(pm.pm_id)}
                  className={`${styles.row} ${pm.count === 0 ? styles.rowZero : ''}`}
                  onClick={() => setOpen(false)}
                >
                  <span className={styles.rowName}>{pm.nombre}</span>
                  <span className={styles.rowCount}>{pm.count}</span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
