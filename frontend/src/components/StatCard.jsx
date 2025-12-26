/**
 * STAT CARD - Componente estandarizado con nuevo sistema de diseño
 * 
 * Usa design tokens y clases del sistema base.
 * Reemplaza las stat-cards custom de Productos.jsx y Tienda.jsx
 */

export default function StatCard({ 
  label, 
  value, 
  color = 'blue', 
  onClick, 
  icon,
  subItems = [] 
}) {
  const colorClasses = {
    green: 'text-[var(--success)]',
    red: 'text-[var(--error)]',
    blue: 'text-[var(--brand-primary)]',
    orange: 'text-[#ff9800]',
    purple: 'text-[#9c27b0]',
  };

  return (
    <div 
      className={`card ${onClick ? 'card-hover' : ''}`}
      onClick={onClick}
      style={{
        flex: '0 1 240px',
        minWidth: '200px',
        textAlign: 'center',
        cursor: onClick ? 'pointer' : 'default',
      }}
    >
      {/* Label */}
      <div className="text-sm font-medium" style={{ color: 'var(--text-secondary)', marginBottom: 'var(--spacing-sm)' }}>
        {label}
      </div>

      {/* Value con color */}
      {subItems.length === 0 ? (
        <div 
          className={`text-3xl font-bold ${colorClasses[color]}`}
          style={{ lineHeight: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 'var(--spacing-xs)' }}
        >
          {icon && <span>{icon}</span>}
          {value}
        </div>
      ) : (
        /* Sub-items (para markup negativo, etc) */
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-xs)', marginTop: 'var(--spacing-sm)' }}>
          {subItems.map((item, idx) => (
            <div
              key={idx}
              onClick={item.onClick}
              className={item.onClick ? 'card-hover' : ''}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                fontSize: '13px',
                padding: 'var(--spacing-xs) var(--spacing-sm)',
                background: 'var(--bg-secondary)',
                borderRadius: 'var(--radius-base)',
                gap: 'var(--spacing-md)',
                cursor: item.onClick ? 'pointer' : 'default',
              }}
            >
              <span style={{ fontWeight: 500, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                {item.label}
              </span>
              <span className={`font-semibold ${colorClasses[item.color || color]}`}>
                {item.value}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
