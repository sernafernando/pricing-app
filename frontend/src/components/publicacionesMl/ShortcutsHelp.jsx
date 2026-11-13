import { useId } from 'react';
import ModalTesla from '../ModalTesla';
import styles from './ShortcutsHelp.module.css';
import { HELP_CLASS } from './usePublicacionesMLKeyboard';

// What `usePublicacionesMLKeyboard` and the list's rows do, grouped by what each key acts on. Every key here exists
// in the code; keep both sides in step.
const GROUPS = [
  {
    title: 'Lista',
    entries: [
      { keys: ['↓', '↑'], what: 'Moverse por las filas (↓ entra en la primera)' },
      { keys: ['RePág', 'AvPág'], what: 'Saltar 10 filas' },
      { keys: ['Inicio', 'Fin'], what: 'Primera o última fila (con un precio activo: primer o último precio)' },
      { keys: ['Shift+↓', 'Shift+↑'], what: 'Moverse y marcar desde la última marcada' },
      { keys: ['Enter'], what: 'Abrir el detalle (con un precio activo: editarlo)' },
      { keys: ['Ctrl+Enter'], what: 'Abrir la publicación en Mercado Libre' },
      { keys: ['Alt+Enter', 'Alt+Espacio'], what: 'Abrir la publicación en el panel de vendedores' },
      { keys: ['Shift+Enter', 'Shift+Espacio'], what: 'Abrir sus promociones en el panel de vendedores' },
      { keys: ['Esc'], what: 'Salir del modo navegación' },
    ],
  },
  {
    title: 'Precios de la fila',
    entries: [
      { keys: ['→', '←'], what: 'Moverse por los precios editables (→ entra en el primero; ↓ ↑ siguen en la columna)' },
      { keys: ['Espacio'], what: 'Editar el precio activo' },
      { keys: ['Tab', 'Shift+Tab'], what: 'Recorrer los campos del editor sin salir' },
      { keys: ['Esc'], what: 'Cerrar el editor; cerrado, volver a la fila' },
    ],
  },
  {
    title: 'Producto de la fila',
    entries: [
      { keys: ['Ctrl+I'], what: 'Ver su información' },
      { keys: ['R'], what: 'Activar o desactivar el rebate' },
      { keys: ['W'], what: 'Activar o desactivar la web transferencia' },
      { keys: ['O'], what: 'Activar o desactivar fuera de tarjetas' },
    ],
  },
  {
    title: 'Copiar',
    entries: [
      { keys: ['Ctrl+F1', 'Ctrl+Shift+1'], what: 'Código del producto' },
      { keys: ['Ctrl+F2', 'Ctrl+Shift+2'], what: 'Enlace 1 (listado por precio)' },
      { keys: ['Ctrl+F3', 'Ctrl+Shift+3'], what: 'Enlace 2 (promociones)' },
    ],
  },
  {
    title: 'Colores',
    entries: [
      {
        keys: ['1–7'],
        what: 'Pintar la fila, o su producto si es de uno: Urgente, Advertencia, Atención, OK, Info, Revisión, Inactivo',
      },
      { keys: ['0'], what: 'Sacar el color: una publicación vuelve al de su producto, la de un producto queda sin color' },
      { keys: ['F6', 'F7'], what: 'Capa de color anterior o siguiente' },
    ],
  },
  {
    title: 'Sobre los marcados o filtrados',
    entries: [
      { keys: ['Ctrl+K'], what: 'Calcular Web Transf.' },
      { keys: ['Ctrl+Shift+P'], what: 'Calcular PVP' },
    ],
  },
  {
    title: 'Abrir un filtro',
    entries: [
      { keys: ['Alt+M', 'Alt+S', 'Alt+P'], what: 'Marca, Subcategoría o PM' },
      { keys: ['Alt+A'], what: 'Auditoría' },
      { keys: ['Alt+C', 'Alt+F'], what: 'Presencia (los Avanzados de Productos)' },
    ],
  },
  {
    title: 'Pantalla',
    entries: [
      { keys: ['Ctrl+F'], what: 'Ir a la búsqueda' },
      { keys: ['Alt+V'], what: 'Cambiar los precios de Productos: Normal, Cuotas o PVP' },
      { keys: ['Alt+R'], what: 'Activar o desactivar Auto-recalcular cuotas al guardar' },
      { keys: ['Ctrl+E'], what: 'Exportar la vista a CSV' },
      { keys: ['?'], what: 'Mostrar u ocultar esta ayuda' },
    ],
  },
  // What the backend's `normalize_q` reads in the search box (pinned by `test_filters.py`, `TestSearchTerm`), the same
  // operators Productos documents.
  {
    title: 'Operadores de búsqueda',
    entries: [
      { keys: ['MLA123456', 'mla:MLA123456'], what: 'Una publicación por su número (exacto)' },
      { keys: ['ean:123456'], what: 'EAN exacto' },
      { keys: ['codigo:ABC123'], what: 'Código exacto' },
      { keys: ['marca:Samsung'], what: 'Marca exacta' },
      { keys: ['desc:texto', 'descripcion:texto'], what: 'La descripción contiene el texto (sin guiones ni espacios)' },
      { keys: ['promo:DEAL', 'promo:texto'], what: 'Promoción activa de ese tipo (DEAL, SMART…) o cuyo nombre contiene el texto' },
      { keys: ['*123'], what: 'Termina en 123 (título, descripción, marca o código)' },
      { keys: ['123*'], what: 'Empieza con 123 (título, descripción, marca o código)' },
      { keys: ['texto'], what: 'Título y SKU, o descripción, marca y código (sin guiones ni espacios)' },
    ],
  },
];

function Group({ title, entries }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className={styles.group}>
      <h3 id={headingId} className={styles.heading}>
        {title}
      </h3>
      <dl className={styles.list}>
        {entries.map(({ keys, what }) => (
          <div key={what} className={styles.entry}>
            <dt className={styles.keys}>
              {keys.map((key, index) => (
                <span key={key} className={styles.key}>
                  {index > 0 && <span className={styles.or}> o </span>}
                  <kbd className={styles.kbd}>{key}</kbd>
                </span>
              ))}
            </dt>
            <dd className={styles.what}>{what}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** The keyboard shortcuts and the search operators of Publicaciones ML, opened with `?` or the header's button. */
export default function ShortcutsHelp({ onClose }) {
  return (
    <ModalTesla
      isOpen
      onClose={onClose}
      title="Atajos de teclado"
      size="full"
      className={`${HELP_CLASS} ${styles.modal}`}
      bodyClassName="compact"
    >
      <div className={styles.groups}>
        {GROUPS.map((group) => (
          <Group key={group.title} {...group} />
        ))}
      </div>
    </ModalTesla>
  );
}
