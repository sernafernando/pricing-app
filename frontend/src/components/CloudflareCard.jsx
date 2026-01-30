import styles from './CloudflareCard.module.css';

/**
 * CloudflareCard - Compact card component siguiendo el diseño de Cloudflare
 * 
 * Variantes:
 * - default: Card estándar con padding normal
 * - compact: Card más chica para listings/grids
 * - metric: Card para mostrar métricas con números grandes
 */
export default function CloudflareCard({ 
  children, 
  variant = 'default',
  title,
  action,
  className = '',
  onClick,
  hoverable = false,
  ...props 
}) {
  const variantClass = styles[variant] || styles.default;
  const isClickable = onClick || hoverable;

  return (
    <div 
      className={`${styles.card} ${variantClass} ${isClickable ? styles.hoverable : ''} ${className}`}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      {...props}
    >
      {title && (
        <div className={styles.header}>
          <h3 className={styles.title}>{title}</h3>
          {action && <div className={styles.action}>{action}</div>}
        </div>
      )}
      
      <div className={styles.content}>
        {children}
      </div>
    </div>
  );
}

/**
 * MetricCard - Card específica para mostrar métricas estilo Cloudflare
 * 
 * Props:
 * - label: Etiqueta de la métrica (ej: "Solicitudes HTTP")
 * - value: Valor principal (número grande)
 * - trend: Porcentaje de cambio (ej: "+3.65%")
 * - trendDirection: "up" | "down" | "neutral"
 * - chart: Componente de gráfico opcional (sparkline)
 */
export function MetricCard({ 
  label, 
  value, 
  trend, 
  trendDirection = 'neutral',
  chart,
  info,
  className = ''
}) {
  const trendClass = styles[`trend${trendDirection.charAt(0).toUpperCase() + trendDirection.slice(1)}`];

  return (
    <CloudflareCard variant="metric" className={className}>
      <div className={styles.metricHeader}>
        <span className={styles.metricLabel}>
          {label}
          {info && <span className={styles.metricInfo} title={info}>ⓘ</span>}
        </span>
      </div>
      
      <div className={styles.metricValue}>
        {value}
        {trend && (
          <span className={`${styles.metricTrend} ${trendClass}`}>
            {trendDirection === 'up' && '▲ '}
            {trendDirection === 'down' && '▼ '}
            {trend}
          </span>
        )}
      </div>
      
      {chart && (
        <div className={styles.metricChart}>
          {chart}
        </div>
      )}
    </CloudflareCard>
  );
}
