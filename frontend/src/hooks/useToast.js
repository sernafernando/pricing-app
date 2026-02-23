import { useState, useRef, useEffect, useCallback } from 'react';

/**
 * Reusable toast notification hook.
 *
 * @param {number} [duration=3000] - Auto-dismiss time in ms.
 * @returns {{ toast: { message: string, type: string } | null, showToast: Function, hideToast: Function }}
 *
 * Usage:
 *   const { toast, showToast, hideToast } = useToast();
 *   showToast('Guardado correctamente');           // default: success
 *   showToast('Algo falló', 'error');
 *   showToast('Procesando...', 'info');
 *
 * Render:
 *   <Toast toast={toast} onClose={hideToast} />
 */
export function useToast(duration = 3000) {
  const [toast, setToast] = useState(null);
  const timerRef = useRef(null);

  const hideToast = useCallback(() => setToast(null), []);

  const showToast = useCallback(
    (message, type = 'success') => {
      if (timerRef.current) clearTimeout(timerRef.current);
      setToast({ message, type });
      timerRef.current = setTimeout(() => setToast(null), duration);
    },
    [duration],
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return { toast, showToast, hideToast };
}
