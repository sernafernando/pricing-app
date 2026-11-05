import { useEffect, useRef, useState } from 'react';
import { MoreVertical } from 'lucide-react';
import styles from './TacticalAcciones.module.css';

/**
 * A tactical row's actions menu (the list design's "⋮", handoffs/diseno-tactical/listado-tacticals-PENDIENTE.html):
 * `acciones` are `{ label, onSelect }`. The first item takes the focus on open and the arrows, Home and End move it
 * (the WAI-ARIA menu pattern); Escape, Tab or a click outside closes it, Escape back on its button. The menu is fixed under its button, so the table's sideways scroller never clips it; a
 * scroll or resize closes it rather than leave it away from its row.
 */
const ANCHO = 148;
export default function TacticalAcciones({ nombre, acciones }) {
  const [abierto, setAbierto] = useState(null); // the menu's fixed position while open
  const boton = useRef(null);
  const menu = useRef(null);

  useEffect(() => {
    if (!abierto) return undefined;
    menu.current?.querySelector('[role="menuitem"]')?.focus();
    const afuera = (event) => {
      if (!menu.current?.contains(event.target) && !boton.current?.contains(event.target)) setAbierto(null);
    };
    const lejos = () => setAbierto(null);
    document.addEventListener('mousedown', afuera);
    window.addEventListener('scroll', lejos, true);
    window.addEventListener('resize', lejos);
    return () => {
      document.removeEventListener('mousedown', afuera);
      window.removeEventListener('scroll', lejos, true);
      window.removeEventListener('resize', lejos);
    };
  }, [abierto]);

  const alternar = () => {
    if (abierto) {
      setAbierto(null);
      return;
    }
    const caja = boton.current.getBoundingClientRect();
    setAbierto({ top: caja.bottom + 4, left: Math.max(4, caja.right - ANCHO) });
  };
  const cerrar = () => {
    setAbierto(null);
    boton.current?.focus();
  };
  const teclas = (event) => {
    if (event.key === 'Escape') {
      cerrar();
      return;
    }
    if (event.key === 'Tab') {
      setAbierto(null);
      return;
    }
    const items = [...menu.current.querySelectorAll('[role="menuitem"]')];
    const actual = items.indexOf(document.activeElement);
    const destino = {
      ArrowDown: (actual + 1) % items.length,
      ArrowUp: (actual - 1 + items.length) % items.length,
      Home: 0,
      End: items.length - 1,
    }[event.key];
    if (destino === undefined) return;
    event.preventDefault();
    items[destino].focus();
  };
  return (
    <div className={styles.acciones}>
      <button
        ref={boton}
        type="button"
        className={styles.boton}
        aria-haspopup="true"
        aria-expanded={abierto !== null}
        aria-label={`Acciones de ${nombre}`}
        onClick={alternar}
      >
        <MoreVertical size={15} aria-hidden="true" />
      </button>
      {abierto && (
        <div
          ref={menu}
          className={styles.menu}
          role="menu"
          style={{ top: abierto.top, left: abierto.left, width: ANCHO }}
          onKeyDown={teclas}
        >
          {acciones.map((accion) => (
            <button
              key={accion.label}
              type="button"
              role="menuitem"
              tabIndex={-1}
              onClick={() => {
                setAbierto(null);
                accion.onSelect();
              }}
            >
              {accion.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
