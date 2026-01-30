import { useState } from 'react';
import { Link } from 'react-router-dom';
import styles from './SidebarSection.module.css';

export default function SidebarSection({ 
  title, 
  icon, 
  items, 
  defaultOpen = false, 
  isExpanded = true,
  currentPath 
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  const toggleOpen = () => {
    setIsOpen(!isOpen);
  };

  return (
    <div className={styles.section}>
      {/* Section Header */}
      <div 
        className={styles.sectionHeader} 
        onClick={toggleOpen}
        role="button"
        tabIndex={0}
        aria-expanded={isOpen}
      >
        <span className={styles.icon}>{icon}</span>
        {isExpanded && (
          <>
            <span className={styles.title}>{title}</span>
            <span className={`${styles.arrow} ${isOpen ? styles.arrowOpen : ''}`}>
              ▸
            </span>
          </>
        )}
      </div>

      {/* Section Items */}
      {isOpen && (
        <div className={styles.sectionItems}>
          {items.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`${styles.item} ${currentPath === item.path ? styles.active : ''}`}
              title={!isExpanded ? item.label : undefined}
            >
              <span className={styles.itemLabel}>{item.label}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
