/**
 * STAT CARD - Diseño Tesla Minimalista
 * 
 * Mejoras visuales:
 * - Bordes más sutiles
 * - Espaciado generoso
 * - Animaciones suaves
 * - Indicador visual de interactividad
 * - Efecto glassmorphism sutil
 */

import './StatCard.css';

export default function StatCard({ 
  label, 
  value, 
  color = 'blue', 
  onClick, 
  icon,
  subItems = [] 
}) {
  const colorClasses = {
    green: 'stat-color-green',
    red: 'stat-color-red',
    blue: 'stat-color-blue',
    orange: 'stat-color-orange',
    purple: 'stat-color-purple',
  };

  return (
    <div 
      className={`stat-card-tesla ${onClick ? 'stat-card-clickable' : ''}`}
      onClick={onClick}
    >
      {/* Indicador visual si es clickeable */}
      {onClick && <div className="stat-card-indicator" />}

      {/* Label con mejor tipografía */}
      <div className="stat-card-label">
        {label}
      </div>

      {/* Value con animación */}
      {subItems.length === 0 ? (
        <div className={`stat-card-value ${colorClasses[color]}`}>
          {icon && <span className="stat-card-icon">{icon}</span>}
          <span className="stat-card-number">{value}</span>
        </div>
      ) : (
        /* Sub-items con mejor separación */
        <div className="stat-card-subitems">
          {subItems.map((item, idx) => (
            <div
              key={idx}
              onClick={(e) => {
                if (item.onClick) {
                  e.stopPropagation();
                  item.onClick();
                }
              }}
              className={`stat-subitem ${item.onClick ? 'stat-subitem-clickable' : ''}`}
            >
              <span className="stat-subitem-label">
                {item.label}
              </span>
              <span className={`stat-subitem-value ${colorClasses[item.color || color]}`}>
                {item.value}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
