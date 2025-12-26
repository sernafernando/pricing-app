/**
 * MODAL TESLA - Componente Base Estandarizado
 * 
 * Características:
 * - Portal a document.body
 * - ESC para cerrar
 * - Click outside para cerrar (opcional)
 * - Auto-focus en primer elemento
 * - Tab trap (mantiene foco dentro)
 * - Estructura consistente (header, body, footer)
 * - Soporte para tabs
 * - Tamaños predefinidos
 */

import { createPortal } from 'react-dom';
import { useEffect, useRef, useCallback } from 'react';

export default function ModalTesla({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  footer,
  size = 'md', // xs, sm, md, lg, xl, full
  showCloseButton = true,
  closeOnOverlay = true,
  closeOnEsc = true,
  className = '',
  bodyClassName = '',
  tabs,
  activeTab,
  onTabChange,
}) {
  const modalRef = useRef(null);
  const overlayRef = useRef(null);

  // ESC para cerrar
  useEffect(() => {
    if (!isOpen || !closeOnEsc) return;

    const handleEsc = (e) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('keydown', handleEsc);
    return () => document.removeEventListener('keydown', handleEsc);
  }, [isOpen, closeOnEsc, onClose]);

  // Click outside para cerrar
  const handleOverlayClick = useCallback((e) => {
    if (closeOnOverlay && e.target === overlayRef.current) {
      onClose();
    }
  }, [closeOnOverlay, onClose]);

  // Tab trap - mantener foco dentro del modal
  useEffect(() => {
    if (!isOpen || !modalRef.current) return;

    const focusableElements = modalRef.current.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    
    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];

    const handleTab = (e) => {
      if (e.key !== 'Tab') return;

      if (e.shiftKey) {
        if (document.activeElement === firstElement) {
          e.preventDefault();
          lastElement?.focus();
        }
      } else {
        if (document.activeElement === lastElement) {
          e.preventDefault();
          firstElement?.focus();
        }
      }
    };

    document.addEventListener('keydown', handleTab);
    
    // Auto-focus en primer elemento
    setTimeout(() => firstElement?.focus(), 100);

    return () => document.removeEventListener('keydown', handleTab);
  }, [isOpen]);

  // Prevenir scroll del body cuando modal está abierto
  useEffect(() => {
    if (isOpen) {
      document.body.classList.add('modal-open');
      return () => document.body.classList.remove('modal-open');
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const modalContent = (
    <div 
      ref={overlayRef}
      className="modal-overlay-tesla" 
      onClick={handleOverlayClick}
      data-close-on-overlay={closeOnOverlay}
    >
      <div 
        ref={modalRef}
        className={`modal-tesla ${size} ${className}`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="modal-header-tesla">
          <div style={{ flex: 1 }}>
            <h2 className="modal-title-tesla">{title}</h2>
            {subtitle && <p className="modal-subtitle-tesla">{subtitle}</p>}
          </div>
          {showCloseButton && (
            <button 
              className="btn-close-tesla" 
              onClick={onClose}
              aria-label="Cerrar modal"
            >
              ×
            </button>
          )}
        </div>

        {/* Tabs (opcional) */}
        {tabs && tabs.length > 0 && (
          <div className="modal-tabs">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                className={`modal-tab ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => onTabChange?.(tab.id)}
                disabled={tab.disabled}
              >
                {tab.label}
                {tab.badge && <span className="badge">{tab.badge}</span>}
              </button>
            ))}
          </div>
        )}

        {/* Body */}
        <div className={`modal-body-tesla ${bodyClassName}`}>
          {children}
        </div>

        {/* Footer (opcional) */}
        {footer && (
          <div className="modal-footer-tesla">
            {footer}
          </div>
        )}
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
}

// Componentes helper para facilitar el uso

export function ModalSection({ title, children, className = '' }) {
  return (
    <div className={`modal-section ${className}`}>
      {title && <h3 className="modal-section-title">{title}</h3>}
      <div className="modal-section-content">{children}</div>
    </div>
  );
}

export function ModalDivider() {
  return <div className="modal-divider" />;
}

export function ModalAlert({ type = 'info', children }) {
  return (
    <div className={`modal-alert ${type}`}>
      {children}
    </div>
  );
}

export function ModalLoading({ message = 'Cargando...' }) {
  return (
    <div className="modal-loading">
      <div className="spinner" />
      <span>{message}</span>
    </div>
  );
}

export function ModalFooterButtons({ onCancel, onConfirm, confirmText = 'Guardar', cancelText = 'Cancelar', confirmLoading, confirmDisabled, confirmVariant = 'primary' }) {
  return (
    <div className="btn-group-tesla right">
      {onCancel && (
        <button 
          className="btn-tesla secondary" 
          onClick={onCancel}
          disabled={confirmLoading}
        >
          {cancelText}
        </button>
      )}
      {onConfirm && (
        <button 
          className={`btn-tesla ${confirmVariant} ${confirmLoading ? 'loading' : ''}`}
          onClick={onConfirm}
          disabled={confirmDisabled || confirmLoading}
        >
          {confirmText}
        </button>
      )}
    </div>
  );
}
