import { useRef, useCallback } from 'react';

/**
 * Hook para manejar el cierre de modales al hacer click afuera.
 * Solo cierra si tanto mousedown como mouseup ocurren en el backdrop.
 * Esto previene que se cierre cuando se hace drag desde dentro del modal.
 *
 * @param {Function} onClose - Función a ejecutar cuando se hace click afuera
 * @returns {Object} - { overlayRef, handleOverlayMouseDown }
 */
export const useModalClickOutside = (onClose) => {
  const overlayRef = useRef(null);
  const mouseDownTarget = useRef(null);

  const handleOverlayMouseDown = useCallback((e) => {
    // Guardar dónde se inició el click
    mouseDownTarget.current = e.target;
  }, []);

  const handleOverlayClick = useCallback((e) => {
    // Solo cerrar si:
    // 1. El click se inició en el overlay (mousedown)
    // 2. El click terminó en el overlay (mouseup/click)
    // 3. Ambos son el mismo elemento (el overlay)
    if (
      mouseDownTarget.current === overlayRef.current &&
      e.target === overlayRef.current
    ) {
      onClose();
    }
    // Reset
    mouseDownTarget.current = null;
  }, [onClose]);

  return {
    overlayRef,
    handleOverlayMouseDown,
    handleOverlayClick
  };
};
