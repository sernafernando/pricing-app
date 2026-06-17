import { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Ticket } from 'lucide-react';
import { useSSEChannel } from '../hooks/useSSEChannel';
import { useSSE } from '../contexts/SSEContext';
import { usePermisos } from '../contexts/PermisosContext';
import { ticketsAPI } from '../services/api';
import styles from './TicketBadge.module.css';

/**
 * TicketBadge - Acceso directo a tickets en el TopBar.
 *
 * Siempre visible para todos los usuarios logueados.
 * Muestra un badge con la cantidad de tickets pendientes (sin_asignar + asignados_a_mi)
 * y un popover con el breakdown por categoría al hacer hover o tap.
 *
 * SSE-driven: re-fetches breakdown when tickets:badge is published.
 * Falls back to 60s polling when SSE is degraded.
 */

const ZERO_BREAKDOWN = {
  pendientes: 0,
  sin_asignar: 0,
  asignados_a_mi: 0,
  asignados_a_otros: 0,
  con_actividad_nueva: 0,
};

/** Single colored dot + label + count row inside the popover. */
function Row({ dotClass, label, value }) {
  return (
    <li className={`${styles.row} ${value === 0 ? styles.dim : ''}`}>
      <span className={`${styles.dot} ${dotClass}`} aria-hidden="true" />
      <span className={styles.rowLabel}>{label}</span>
      <span className={styles.rowCount}>{value}</span>
    </li>
  );
}

export default function TicketBadge() {
  const [breakdown, setBreakdown] = useState(ZERO_BREAKDOWN);
  const [open, setOpen] = useState(false);
  const { isDegraded } = useSSE();
  const { tienePermiso } = usePermisos();
  const inFlightRef = useRef(false);
  const lastFetchAtRef = useRef(0);
  const wrapperRef = useRef(null);
  const isTouchRef = useRef(false);

  const canSeeOtros = tienePermiso('tickets.ver');

  const fetchCount = useCallback(async (options = {}) => {
    const { force = false } = options;
    const now = Date.now();
    const MIN_FETCH_INTERVAL_MS = 10000;

    if (inFlightRef.current) return;
    if (!force && now - lastFetchAtRef.current < MIN_FETCH_INTERVAL_MS) return;

    inFlightRef.current = true;

    try {
      const { data } = await ticketsAPI.badgeCount();
      setBreakdown(data);
      lastFetchAtRef.current = Date.now();
    } catch {
      setBreakdown(ZERO_BREAKDOWN);
    } finally {
      inFlightRef.current = false;
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchCount({ force: true });
  }, [fetchCount]);

  // SSE-driven reload
  useSSEChannel('tickets:badge', () => fetchCount());

  // Fallback polling when SSE is degraded
  useEffect(() => {
    if (!isDegraded()) return;

    const interval = setInterval(() => fetchCount({ force: true }), 60000);
    return () => clearInterval(interval);
  }, [isDegraded, fetchCount]);

  // Click-outside + Escape to close (mirrors TopBar user-menu pattern)
  useEffect(() => {
    if (!open) return;

    function handleDocClick(e) {
      if (!e.target.closest('[data-ticket-badge]')) {
        setOpen(false);
      }
    }

    function handleKeyDown(e) {
      if (e.key === 'Escape') {
        setOpen(false);
      }
    }

    document.addEventListener('click', handleDocClick);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('click', handleDocClick);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  const pendientes = breakdown.pendientes;

  return (
    <div
      ref={wrapperRef}
      className={styles.wrapper}
      data-ticket-badge
      onTouchStart={() => { isTouchRef.current = true; }}
      onMouseEnter={() => { if (!isTouchRef.current) setOpen(true); }}
      onMouseLeave={() => { if (!isTouchRef.current) setOpen(false); isTouchRef.current = false; }}
    >
      <button
        type="button"
        className={`${styles.badge} ${pendientes > 0 ? styles.hasCount : ''}`}
        onClick={() => setOpen((prev) => !prev)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={
          pendientes > 0
            ? `${pendientes} ticket${pendientes !== 1 ? 's' : ''} requieren tu acción`
            : 'Tickets'
        }
        title={
          pendientes > 0
            ? `${pendientes} ticket${pendientes !== 1 ? 's' : ''} pendiente${pendientes !== 1 ? 's' : ''}`
            : 'Tickets'
        }
      >
        <Ticket size={18} className={styles.icon} />
        {pendientes > 0 && <span className={styles.count}>{pendientes}</span>}
      </button>

      {open && (
        <div className={styles.popover} role="dialog" aria-label="Resumen de tickets">
          <ul className={styles.rows}>
            <Row
              dotClass={styles.dotSinAsignar}
              label="Sin asignar"
              value={breakdown.sin_asignar}
            />
            <Row
              dotClass={styles.dotAMi}
              label="Asignados a mí"
              value={breakdown.asignados_a_mi}
            />
            {canSeeOtros && (
              <Row
                dotClass={styles.dotAOtros}
                label="Asignados a otros"
                value={breakdown.asignados_a_otros}
              />
            )}
            <Row
              dotClass={styles.dotActividad}
              label="Actividad nueva"
              value={breakdown.con_actividad_nueva}
            />
          </ul>
          <Link
            to="/tickets"
            className={styles.verTodos}
            onClick={() => setOpen(false)}
          >
            Ver todos los tickets
          </Link>
        </div>
      )}
    </div>
  );
}
