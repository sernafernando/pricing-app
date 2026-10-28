import { useId } from 'react';
import ModalTesla from '../ModalTesla';
import styles from './ShortcutsHelp.module.css';
import { HELP_CLASS } from './usePublicacionesMLKeyboard';

// What `usePublicacionesMLKeyboard` and the list's rows do, in the order an operator meets them.
const SHORTCUTS = [
  { keys: ['↓', '↑'], what: 'Moverse por las filas de la lista (↓ entra en la primera)' },
  { keys: ['RePág', 'AvPág'], what: 'Saltar 10 filas' },
  { keys: ['Inicio', 'Fin'], what: 'Ir a la primera o a la última fila (con un precio activo: al primero o al último precio de la fila)' },
  { keys: ['Shift+↓', 'Shift+↑'], what: 'Moverse y seleccionar el producto de la fila (desde el último seleccionado)' },
  { keys: ['Enter'], what: 'Abrir el detalle de la fila (con un precio activo: editarlo)' },
  { keys: ['→', '←'], what: 'Moverse por los precios editables de la fila (→ entra en el primero); ↓ y ↑ siguen en la misma columna' },
  { keys: ['Espacio'], what: 'Editar el precio activo' },
  { keys: ['Tab', 'Shift+Tab'], what: 'Mientras se edita un precio: recorrer los campos del editor sin salir de él' },
  { keys: ['Esc'], what: 'Cerrar el editor del precio; con el editor cerrado, volver a la fila' },
  { keys: ['Ctrl+Enter'], what: 'Abrir la publicación en Mercado Libre' },
  { keys: ['Ctrl+I'], what: 'Ver la información del producto de la fila' },
  { keys: ['Ctrl+F1', 'Ctrl+Shift+1'], what: 'Copiar el código del producto' },
  { keys: ['Ctrl+F2', 'Ctrl+Shift+2'], what: 'Copiar el enlace 1 (listado por precio)' },
  { keys: ['Ctrl+F3', 'Ctrl+Shift+3'], what: 'Copiar el enlace 2 (promociones)' },
  { keys: ['1–7'], what: 'Pintar el producto de la fila (Urgente, Advertencia, Atención, OK, Info, Revisión, Inactivo)' },
  { keys: ['0'], what: 'Sacarle el color al producto de la fila' },
  { keys: ['F6', 'F7'], what: 'Capa de color anterior o siguiente' },
  { keys: ['R'], what: 'Activar o desactivar el rebate del producto de la fila' },
  { keys: ['W'], what: 'Activar o desactivar la web transferencia del producto de la fila' },
  { keys: ['O'], what: 'Activar o desactivar fuera de tarjetas en el producto de la fila' },
  { keys: ['Ctrl+K'], what: 'Calcular Web Transf. sobre los productos marcados o filtrados' },
  { keys: ['Ctrl+Shift+P'], what: 'Calcular PVP sobre los productos marcados o filtrados' },
  { keys: ['Alt+M', 'Alt+S', 'Alt+P'], what: 'Abrir el filtro de Marca, Subcategoría o PM' },
  { keys: ['Alt+A'], what: 'Abrir los filtros de Auditoría' },
  { keys: ['Alt+C', 'Alt+F'], what: 'Abrir los filtros de Presencia (los Avanzados de Productos)' },
  { keys: ['Alt+V'], what: 'Cambiar los precios de Productos: Normal, Cuotas o PVP' },
  { keys: ['Alt+R'], what: 'Activar o desactivar Auto-recalcular cuotas al guardar un precio' },
  { keys: ['Ctrl+F'], what: 'Ir a la búsqueda' },
  { keys: ['Ctrl+E'], what: 'Exportar la vista a CSV' },
  { keys: ['?'], what: 'Mostrar u ocultar esta ayuda' },
];

// What the backend's `normalize_q` reads in the search box (pinned by `test_filters.py`, `TestSearchTerm`), the same
// operators Productos documents.
const SEARCH_OPERATORS = [
  { keys: ['MLA123456'], what: 'Una publicación por su número (exacto)' },
  { keys: ['ean:123456'], what: 'Búsqueda exacta por EAN' },
  { keys: ['codigo:ABC123'], what: 'Búsqueda exacta por código' },
  { keys: ['marca:Samsung'], what: 'Búsqueda exacta por marca' },
  { keys: ['desc:texto', 'descripcion:texto'], what: 'Búsqueda en la descripción del producto (contiene, sin guiones ni espacios)' },
  { keys: ['*123'], what: 'Termina en "123" (título, descripción, marca o código)' },
  { keys: ['123*'], what: 'Comienza con "123" (título, descripción, marca o código)' },
  { keys: ['texto'], what: 'Búsqueda normal: título y SKU, o descripción, marca y código del producto (sin guiones ni espacios)' },
];

function Entries({ entries }) {
  return (
    <dl className={styles.list}>
      {entries.map(({ keys, what }) => (
        <div key={what} className={styles.entry}>
          <dt className={styles.keys}>
            {keys.map((key, index) => (
              <span key={key}>
                {index > 0 && ' o '}
                <kbd className={styles.kbd}>{key}</kbd>
              </span>
            ))}
          </dt>
          <dd className={styles.what}>{what}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The keyboard shortcuts and the search operators of Publicaciones ML, opened with `?` or the header's button. */
export default function ShortcutsHelp({ onClose }) {
  const searchId = useId();
  return (
    <ModalTesla isOpen onClose={onClose} title="Atajos de teclado" size="sm" className={HELP_CLASS}>
      <Entries entries={SHORTCUTS} />
      <section aria-labelledby={searchId} className={styles.section}>
        <h3 id={searchId} className={styles.heading}>
          Operadores de búsqueda
        </h3>
        <Entries entries={SEARCH_OPERATORS} />
      </section>
    </ModalTesla>
  );
}
