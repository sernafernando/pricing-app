import { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Ticket } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import { useSSEChannel } from '../hooks/useSSEChannel';
import { useSSE } from '../contexts/SSEContext';
import { ticketsAPI } from '../services/api';
import styles from './TicketBadge.module.css';

/**
 * TicketBadge - Badge en el TopBar que muestra la cantidad de
 * tickets pendientes de revisión asignados al usuario.
 *
 * Solo visible si el usuario tiene permiso 'tickets.ver'.
 * Clickeable: navega a /tickets.
 *
 * SSE-driven: re-fetches count when tickets:badge is published.
 * Falls back to 60s polling when SSE is degraded.
 */
export default function TicketBadge() {
  const { tienePermiso } = usePermisos();
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const { isDegraded } = useSSE();
  const inFlightRef = useRef(false);
  const lastFetchAtRef = useRef(0);

  const canView = tienePermiso('tickets.ver');

  const fetchCount = useCallback(async (options = {}) => {
    const { force = false } = options;
    const now = Date.now();
    const MIN_FETCH_INTERVAL_MS = 10000;

    if (inFlightRef.current) return;
    if (!force && now - lastFetchAtRef.current < MIN_FETCH_INTERVAL_MS) return;

    inFlightRef.current = true;

    try {
      const { data } = await ticketsAPI.badgeCount();
      setCount(data.pendientes);
      lastFetchAtRef.current = Date.now();
    } catch {
      setCount(0);
    } finally {
      inFlightRef.current = false;
      setLoading(false);
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    if (!canView) return;
    fetchCount({ force: true });
  }, [canView, fetchCount]);

  // SSE-driven reload
  useSSEChannel('tickets:badge', () => fetchCount(), { enabled: canView });

  // Fallback polling when SSE is degraded
  useEffect(() => {
    if (!canView || !isDegraded()) return;

    const interval = setInterval(() => fetchCount({ force: true }), 60000);
    return () => clearInterval(interval);
  }, [canView, isDegraded, fetchCount]);

  if (!canView || loading || count === 0) return null;

  return (
    <Link
      to="/tickets"
      className={styles.badge}
      title={`${count} ticket${count !== 1 ? 's' : ''} pendiente${count !== 1 ? 's' : ''} de revisión`}
    >
      <Ticket size={18} className={styles.icon} />
      <span className={styles.count}>{count}</span>
    </Link>
  );
}
