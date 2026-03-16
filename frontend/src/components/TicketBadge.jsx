import { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Ticket } from 'lucide-react';
import { useSSEChannel } from '../hooks/useSSEChannel';
import { useSSE } from '../contexts/SSEContext';
import { ticketsAPI } from '../services/api';
import styles from './TicketBadge.module.css';

/**
 * TicketBadge - Acceso directo a tickets en el TopBar.
 *
 * Siempre visible para todos los usuarios logueados.
 * Muestra un badge con la cantidad de tickets pendientes si hay alguno.
 *
 * SSE-driven: re-fetches count when tickets:badge is published.
 * Falls back to 60s polling when SSE is degraded.
 */
export default function TicketBadge() {
  const [count, setCount] = useState(0);
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

  return (
    <Link
      to="/tickets"
      className={`${styles.badge} ${count > 0 ? styles.hasCount : ''}`}
      title={count > 0 ? `${count} ticket${count !== 1 ? 's' : ''} pendiente${count !== 1 ? 's' : ''}` : 'Tickets'}
    >
      <Ticket size={18} className={styles.icon} />
      {count > 0 && <span className={styles.count}>{count}</span>}
    </Link>
  );
}
