import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import styles from './SidebarSection.module.css';

export default function SidebarSection({ 
  title, 
  icon: Icon, 
  items, 
  defaultOpen = false, 
  isExpanded = true,
  currentPath,
  forceOpen = false,
  onItemClick
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [lastForceOpen, setLastForceOpen] = useState(forceOpen);

  // Detectar cambios en forceOpen y resetear estado interno
  useEffect(() => {
    if (forceOpen !== lastForceOpen) {
      setIsOpen(forceOpen);
      setLastForceOpen(forceOpen);
    }
  }, [forceOpen, lastForceOpen]);

  const toggleOpen = () => {
    setIsOpen(!isOpen);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggleOpen();
    }
  };

  // Controlar si la sección está abierta (manual o forzado)
  const effectiveOpen = forceOpen || isOpen;

  // Detectar si algún item de esta sección está activo
  const hasActiveItem = items.some(item => item.path === currentPath);

  return (
    <div className={styles.section}>
      {/* Section Header */}
      <div 
        className={`${styles.sectionHeader} ${!isExpanded && hasActiveItem ? styles.sectionActive : ''}`}
        onClick={toggleOpen}
        onKeyDown={handleKeyDown}
        role="button"
        tabIndex={0}
        aria-expanded={effectiveOpen}
      >
        <span className={styles.icon}>
          {Icon && <Icon size={isExpanded ? 14 : 20} strokeWidth={2} />}
        </span>
        {isExpanded && (
          <>
            <span className={styles.title}>{title}</span>
            <span className={`${styles.arrow} ${effectiveOpen ? styles.arrowOpen : ''}`}>
              <ChevronRight size={12} strokeWidth={2} />
            </span>
          </>
        )}
      </div>

      {/* Section Items - Solo mostrar si está expandido Y abierto */}
      {effectiveOpen && isExpanded && (
        <div className={styles.sectionItems}>
          {items.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`${styles.item} ${currentPath === item.path ? styles.active : ''}`}
              onClick={onItemClick}
            >
              <span className={styles.itemLabel}>{item.label}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
