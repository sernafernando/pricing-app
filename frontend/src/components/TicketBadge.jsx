import { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Ticket } from 'lucide-react';
import { useSSEChannel } from '../hooks/useSSEChannel';
import { useSSE } from '../contexts/SSEContext';
import { ticketsAPI } from '../services/api';
import styles from './TicketBadge.module.css';

/**
 * TicketBadge - Badge en el TopBar que muestra la cantidad de
 * tickets pendientes para el usuario.
 *
 * Visible para TODOS los usuarios logueados:
 * - Gestores (tickets.ver): cuenta tickets asignados sin revisar
 * - Usuarios normales: cuenta sus tickets abiertos
 *
 * Clickeable: navega a /tickets.
 *
 * SSE-driven: re-fetches count when tickets:badge is published.
 * Falls back to 60s polling when SSE is degraded.
 */
export default function TicketBadge() {
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const { isDegraded } = useSSE();
  const inFlightRef = useRef(false);
  const lastFetchAtRef = useRef(0);

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

  if (loading || count === 0) return null;

  return (
    <Link
      to="/tickets"
      className={styles.badge}
      title={`${count} ticket${count !== 1 ? 's' : ''} pendiente${count !== 1 ? 's' : ''}`}
    >
      <Ticket size={18} className={styles.icon} />
      <span className={styles.count}>{count}</span>
    </Link>
  );
}
