import { useEffect, useRef } from 'react';

const ENFOCABLES = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/** What Tab can reach inside `contenedor` right now: enabled ones only, read at each keypress. */
const enfocables = (contenedor) =>
  [...contenedor.querySelectorAll(ENFOCABLES)].filter((el) => !el.disabled && el.getAttribute('tabindex') !== '-1');

/**
 * Focus for a dialog that is mounted while open (the "Asignar a programa" modal, the suggestions drawer): on mount
 * the focus moves inside (to `[data-foco-inicial]`, or the first enabled control), Tab and Shift+Tab wrap inside,
 * and on unmount it goes back to what had it before (the button that opened it). Returns the `onKeyDown` for the
 * dialog's root and the `ref` to put on it.
 *
 * Not `ModalTesla`'s trap: it reads the controls once when it opens, so a control that is disabled then (like
 * "Asignar" before a program is chosen) or enabled later breaks the wrap and Tab walks out to the page.
 */
export function useFocoAtrapado() {
  const ref = useRef(null);
  useEffect(() => {
    const anterior = document.activeElement;
    const contenedor = ref.current;
    const inicial = contenedor?.querySelector('[data-foco-inicial]:not(:disabled)') ?? (contenedor && enfocables(contenedor)[0]);
    inicial?.focus();
    return () => {
      if (anterior?.isConnected) anterior.focus();
    };
  }, []);

  const onKeyDown = (e) => {
    if (e.key !== 'Tab' || !ref.current) return;
    const lista = enfocables(ref.current);
    if (lista.length === 0) return;
    const primero = lista[0];
    const ultimo = lista[lista.length - 1];
    const dentro = ref.current.contains(document.activeElement);
    if (e.shiftKey && (document.activeElement === primero || !dentro)) {
      e.preventDefault();
      ultimo.focus();
    } else if (!e.shiftKey && (document.activeElement === ultimo || !dentro)) {
      e.preventDefault();
      primero.focus();
    }
  };
  return { ref, onKeyDown };
}
