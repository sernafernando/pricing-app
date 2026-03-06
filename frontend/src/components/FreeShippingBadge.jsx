import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Truck } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import styles from './FreeShippingBadge.module.css';

/**
 * FreeShippingBadge - Badge en el TopBar que muestra la cantidad de
 * publicaciones con free_shipping_error=true.
 *
 * Solo visible si el usuario tiene permiso 'alertas.ver_free_shipping'.
 * Clickeable: navega a /free-shipping-alerts.
 * Polling cada 5 minutos.
 */
export default function FreeShippingBadge() {
  const { tienePermiso } = usePermisos();
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);

  const canView = tienePermiso('alertas.ver_free_shipping');

  useEffect(() => {
    if (!canView) return;

    const fetchCount = async () => {
      try {
        const { data } = await api.get('/free-shipping-alerts/count');
        setCount(data.count);
      } catch {
        setCount(0);
      } finally {
        setLoading(false);
      }
    };

    fetchCount();

    // Polling cada 60 segundos (query liviano a DB interna)
    const interval = setInterval(fetchCount, 60000);
    return () => clearInterval(interval);
  }, [canView]);

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
