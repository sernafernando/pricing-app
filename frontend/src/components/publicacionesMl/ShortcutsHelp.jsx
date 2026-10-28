import ModalTesla from '../ModalTesla';
import styles from './ShortcutsHelp.module.css';
import { HELP_CLASS } from './usePublicacionesMLKeyboard';

// What `usePublicacionesMLKeyboard` and the list's rows do, in the order an operator meets them.
const SHORTCUTS = [
  { keys: ['↓', '↑'], what: 'Moverse por las filas de la lista (↓ entra en la primera)' },
  { keys: ['RePág', 'AvPág'], what: 'Saltar 10 filas' },
  { keys: ['Inicio', 'Fin'], what: 'Ir a la primera o a la última fila' },
  { keys: ['Shift+↓', 'Shift+↑'], what: 'Moverse y seleccionar el producto de la fila (desde el último seleccionado)' },
  { keys: ['Enter'], what: 'Abrir el detalle de la fila' },
  { keys: ['Ctrl+Enter'], what: 'Abrir la publicación en Mercado Libre' },
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
  { keys: ['Alt+C', 'Alt+F'], what: 'Abrir los filtros de Presencia (rebate, oferta, web transferencia, Tienda Nube, fuera de tarjetas, precio, nuevos)' },
  { keys: ['Alt+V'], what: 'Cambiar los precios de Productos: Normal, Cuotas o PVP' },
  { keys: ['Alt+R'], what: 'Activar o desactivar Auto-recalcular cuotas al guardar un precio' },
  { keys: ['Ctrl+F'], what: 'Ir a la búsqueda' },
  { keys: ['Ctrl+E'], what: 'Exportar la vista a CSV' },
  { keys: ['?'], what: 'Mostrar u ocultar esta ayuda' },
];

/** The keyboard shortcuts of Publicaciones ML, opened with `?` or the header's button. */
export default function ShortcutsHelp({ onClose }) {
  return (
    <ModalTesla isOpen onClose={onClose} title="Atajos de teclado" size="sm" className={HELP_CLASS}>
      <dl className={styles.list}>
        {SHORTCUTS.map(({ keys, what }) => (
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
    </ModalTesla>
  );
}
