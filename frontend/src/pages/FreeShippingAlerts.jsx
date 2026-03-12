import { useState, useEffect } from 'react';
import { Truck, ExternalLink, AlertTriangle, RefreshCw, Lock, Check, X, Clock, Zap, Send } from 'lucide-react';
import api from '../services/api';
import styles from './FreeShippingAlerts.module.css';

/**
 * FreeShippingAlerts - Página con el listado de publicaciones
 * que tienen free_shipping_error=true (envío gratis activado
 * pero precio rebate < $33.000).
 *
 * Auto-fix: background task desactiva envío gratis automáticamente.
 * Manual fix: botón para re-disparar el PUT a ML si falló o está pendiente.
 */
export default function FreeShippingAlerts() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [fixingItems, setFixingItems] = useState({});

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

  const handleManualFix = async (mlaId) => {
    setFixingItems((prev) => ({ ...prev, [mlaId]: 'loading' }));

    try {
      const { data: result } = await api.post(`/free-shipping-alerts/${mlaId}/disable-free-shipping`);
      const status = result.success ? 'success' : 'failed';
      setFixingItems((prev) => ({ ...prev, [mlaId]: status }));

      if (result.success) {
        // Re-fetch para actualizar el status del auto-fix
        fetchAlerts(true);
      }
    } catch {
      setFixingItems((prev) => ({ ...prev, [mlaId]: 'failed' }));
    }
  };

  const formatPrice = (price, currency) => {
    if (price === null || price === undefined) return '-';
    const curr = currency || 'ARS';
    return `${curr} ${Number(price).toLocaleString('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
  };

  const renderAutoFixStatus = (autoFix, mlaId) => {
    // Si hay un fix manual en curso, mostrar ese estado
    const manualState = fixingItems[mlaId];
    if (manualState === 'loading') {
      return (
        <span className={styles.autoFixBadge} data-status="pending">
          <RefreshCw size={12} className={styles.spinner} />
          Enviando...
        </span>
      );
    }
    if (manualState === 'success') {
      return (
        <span className={styles.autoFixBadge} data-status="fixed">
          <Check size={12} />
          Enviado
        </span>
      );
    }
    if (manualState === 'failed') {
      return (
        <span className={styles.autoFixBadge} data-status="failed" title="Falló el disparo manual">
          <X size={12} />
          Falló (manual)
        </span>
      );
    }

    if (!autoFix || !autoFix.attempted) {
      return (
        <span className={styles.autoFixBadge} data-status="pending" title="Pendiente de auto-fix">
          <Clock size={12} />
          Pendiente
        </span>
      );
    }

    if (autoFix.skipped) {
      return (
        <span className={styles.autoFixBadge} data-status="skipped" title={autoFix.skip_reason || 'Saltado'}>
          <Zap size={12} />
          {autoFix.skip_reason === 'mandatory_free_shipping' ? 'Obligatorio' : 'Saltado'}
        </span>
      );
    }

    if (autoFix.success) {
      return (
        <span className={styles.autoFixBadge} data-status="fixed" title={`Corregido: ${autoFix.attempted_at || ''}`}>
          <Check size={12} />
          Corregido
        </span>
      );
    }

    return (
      <span className={styles.autoFixBadge} data-status="failed" title={autoFix.skip_reason || 'Falló el auto-fix'}>
        <X size={12} />
        Falló
      </span>
    );
  };

  const canManualFix = (item) => {
    const manualState = fixingItems[item.mla_id];
    if (manualState === 'loading' || manualState === 'success') return false;

    const autoFix = item.auto_fix;
    // Puede disparar manual si: no se intentó, falló, o es mandatory (el usuario decide)
    if (!autoFix || !autoFix.attempted) return true;
    if (!autoFix.success && !autoFix.skipped) return true;
    if (autoFix.skipped && autoFix.skip_reason === 'mandatory_free_shipping') return false;
    // Si ya fue corregido pero sigue en la lista, se puede re-intentar
    if (autoFix.success) return true;
    return true;
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
                <th>Auto-Fix</th>
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
                  <td className={styles.autoFixCell}>
                    {renderAutoFixStatus(item.auto_fix, item.mla_id)}
                  </td>
                  <td className={styles.actionsCell}>
                    {canManualFix(item) && (
                      <button
                        className={styles.fixBtn}
                        onClick={() => handleManualFix(item.mla_id)}
                        disabled={fixingItems[item.mla_id] === 'loading'}
                        title="Sacar envío gratis manualmente"
                      >
                        <Send size={13} />
                        Sacar envío
                      </button>
                    )}
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
