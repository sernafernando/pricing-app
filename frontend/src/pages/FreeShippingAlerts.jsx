import { useState, useEffect } from 'react';
import { Truck, ExternalLink, AlertTriangle, RefreshCw, Lock } from 'lucide-react';
import api from '../services/api';
import styles from './FreeShippingAlerts.module.css';

/**
 * FreeShippingAlerts - Página con el listado de publicaciones
 * que tienen free_shipping_error=true (envío gratis activado
 * pero precio rebate < $33.000).
 */
export default function FreeShippingAlerts() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchAlerts = async (isRefresh = false) => {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);

    try {
      const { data: result } = await api.get('/free-shipping-alerts');
      setData(result);
    } catch (err) {
      if (err.response?.status === 403) {
        setError('No tienes permiso para ver esta sección.');
      } else if (err.response?.status === 503) {
        setError('La base de datos de webhooks no esta disponible.');
      } else {
        setError('Error al cargar las alertas de envío gratis.');
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
  }, []);

  const handleRefresh = () => {
    fetchAlerts(true);
  };

  const formatPrice = (price, currency) => {
    if (price === null || price === undefined) return '-';
    const curr = currency || 'ARS';
    return `${curr} ${Number(price).toLocaleString('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
  };

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.loadingContainer}>
          <RefreshCw size={24} className={styles.spinner} />
          <span>Cargando alertas de envío gratis...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.page}>
        <div className={styles.errorContainer}>
          <AlertTriangle size={24} />
          <span>{error}</span>
          <button className={styles.retryBtn} onClick={() => fetchAlerts()}>
            Reintentar
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <Truck size={24} className={styles.headerIcon} />
          <div>
            <h1 className={styles.title}>Alertas de Envío Gratis</h1>
            <p className={styles.subtitle}>
              Publicaciones con envío gratis activado y precio rebate menor a $33.000
            </p>
          </div>
        </div>
        <div className={styles.headerRight}>
          <div className={styles.countBadge}>
            <span className={styles.countNumber}>{data?.count || 0}</span>
            <span className={styles.countLabel}>
              publicación{data?.count !== 1 ? 'es' : ''}
            </span>
          </div>
          <button
            className={styles.refreshBtn}
            onClick={handleRefresh}
            disabled={refreshing}
            title="Actualizar datos"
          >
            <RefreshCw size={16} className={refreshing ? styles.spinner : ''} />
          </button>
        </div>
      </div>

      {/* Tabla */}
      {data?.count === 0 ? (
        <div className={styles.emptyState}>
          <Truck size={48} className={styles.emptyIcon} />
          <h2>Sin alertas</h2>
          <p>No hay publicaciones con errores de envío gratis actualmente.</p>
        </div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>MLA</th>
                <th>Titulo</th>
                <th>Precio Publicado</th>
                <th>Precio Rebate</th>
                <th>Logistica</th>
                <th>Estado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((item) => (
                <tr key={item.mla_id}>
                  <td className={styles.mlaCell}>
                    <code className={styles.mlaCode}>{item.mla_id}</code>
                  </td>
                  <td className={styles.titleCell}>
                    <span className={styles.itemTitle}>{item.title || '-'}</span>
                    {item.brand && (
                      <span className={styles.itemBrand}>{item.brand}</span>
                    )}
                  </td>
                  <td className={styles.priceCell}>
                    {formatPrice(item.price, item.currency_id)}
                  </td>
                  <td className={styles.rebateCell}>
                    <span className={styles.rebatePrice}>
                      {formatPrice(item.rebate_price, item.currency_id)}
                    </span>
                  </td>
                  <td className={styles.logisticCell}>
                    <span className={styles.logisticBadge} data-type={item.logistic_type}>
                      {item.logistic_type || '-'}
                    </span>
                    {item.mandatory_free_shipping && (
                      <span className={styles.mandatoryTag} title="Envio gratis obligatorio por MercadoLibre">
                        <Lock size={12} />
                        Obligatorio
                      </span>
                    )}
                  </td>
                  <td>
                    <span className={styles.statusBadge} data-status={item.item_status}>
                      {item.item_status || '-'}
                    </span>
                  </td>
                  <td className={styles.actionsCell}>
                    <a
                      href={item.ml_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={styles.linkBtn}
                      title="Ver en MercadoLibre"
                    >
                      <ExternalLink size={14} />
                      Ver en ML
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
