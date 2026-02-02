import { useState } from 'react';
import styles from './AlertBanner.module.css';

/**
 * AlertBanner - Banner de alertas estilo Cloudflare
 * 
 * Se muestra debajo del TopBar, arriba del contenido principal.
 * Puede ser cerrado por el usuario y persiste en localStorage.
 * 
 * Variantes:
 * - info: Azul (default) - Información general
 * - warning: Naranja - Advertencias
 * - success: Verde - Confirmaciones/éxitos
 * - error: Rojo - Errores críticos
 * 
 * Props:
 * - id: ID único para persistir estado de cierre
 * - variant: "info" | "warning" | "success" | "error"
 * - message: Texto principal del banner
 * - action: Objeto { label, onClick } para botón de acción
 * - dismissible: boolean - Si puede cerrarse (default: true)
 * - persistent: boolean - Si debe aparecer siempre (ignora localStorage)
 */
export default function AlertBanner({ 
  id,
  variant = 'info', 
  message, 
  action,
  dismissible = true,
  persistent = false,
  onDismiss
}) {
  const storageKey = `alertBanner_${id}_dismissed`;
  
  const [isDismissed, setIsDismissed] = useState(() => {
    if (persistent) return false;
    if (!id) return false;
    return localStorage.getItem(storageKey) === 'true';
  });

  const handleDismiss = () => {
    setIsDismissed(true);
    if (id && !persistent) {
      localStorage.setItem(storageKey, 'true');
    }
    // Llamar callback si existe (para alertas dinámicas del backend)
    if (onDismiss) {
      onDismiss();
    }
  };

  if (isDismissed) return null;

  const variantClass = styles[variant] || styles.info;

  return (
    <div className={`${styles.banner} ${variantClass}`}>
      <div className={styles.content}>
        <span className={styles.message}>{message}</span>
        
        {action && (
          <button 
            className={styles.actionBtn} 
            onClick={action.onClick}
          >
            {action.label}
          </button>
        )}
      </div>
      
      {dismissible && (
        <button 
          className={styles.closeBtn} 
          onClick={handleDismiss}
          aria-label="Cerrar alerta"
        >
          ✕
        </button>
      )}
    </div>
  );
}

/**
 * AlertBannerContainer - Wrapper para múltiples banners
 * Se posiciona debajo del TopBar
 */
export function AlertBannerContainer({ children, sidebarExpanded = true }) {
  return (
    <div 
      className={styles.container}
      data-sidebar-expanded={sidebarExpanded}
    >
      {children}
    </div>
  );
}
