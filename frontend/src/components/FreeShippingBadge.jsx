import { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Truck } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import { useSSEChannel } from '../hooks/useSSEChannel';
import { useSSE } from '../contexts/SSEContext';
import api from '../services/api';
import styles from './FreeShippingBadge.module.css';

/**
 * FreeShippingBadge - Badge en el TopBar que muestra la cantidad de
 * publicaciones con free_shipping_error=true.
 *
 * Solo visible si el usuario tiene permiso 'alertas.ver_free_shipping'.
 * Clickeable: navega a /free-shipping-alerts.
 *
 * SSE-driven: re-fetches count when ml-webhook publishes free-shipping:count.
 * Falls back to 60s polling when SSE is degraded.
 */
export default function FreeShippingBadge() {
  const { tienePermiso } = usePermisos();
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const { isDegraded } = useSSE();
  const inFlightRef = useRef(false);
  const lastFetchAtRef = useRef(0);

  const canView = tienePermiso('alertas.ver_free_shipping');

  const fetchCount = useCallback(async (options = {}) => {
    const { force = false } = options;
    const now = Date.now();
    const MIN_FETCH_INTERVAL_MS = 10000;

    if (inFlightRef.current) return;
    if (!force && now - lastFetchAtRef.current < MIN_FETCH_INTERVAL_MS) return;

    inFlightRef.current = true;

    try {
      const { data } = await api.get('/free-shipping-alerts/count');
      setCount(data.count);
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

  // SSE-driven reload: instant update when ml-webhook detects free_shipping_error changes
  useSSEChannel('free-shipping:count', () => fetchCount(), { enabled: canView });

  // Fallback polling: re-activate 60s polling when SSE is degraded
  useEffect(() => {
    if (!canView || !isDegraded()) return;

    const interval = setInterval(() => fetchCount({ force: true }), 60000);
    return () => clearInterval(interval);
  }, [canView, isDegraded, fetchCount]);

  if (!canView || loading || count === 0) return null;

  return (
    <Link
      to="/free-shipping-alerts"
      className={styles.badge}
      title={`${count} publicación${count !== 1 ? 'es' : ''} con error de envío gratis`}
    >
      <Truck size={18} className={styles.icon} />
      <span className={styles.count}>{count}</span>
    </Link>
  );
}
