import { createPortal } from 'react-dom';
import { Loader2, Package } from 'lucide-react';
import { posicion } from './sellInPopover';
import styles from './SellInOperacionProductos.module.css';

const FILAS_MAX = 12; // a hover card cannot scroll: the rest is counted


/**
 * Hover card of the operation picker: the products of one Compras operation (`GET
 * /sell-in/compras/operaciones/{id}/productos`), with ordered and received units, so the operator
 * recognises the order without opening Compras. `estado` is `{ estado: 'cargando' | 'ok' | 'error', items }`.
 */
export default function SellInOperacionProductos({ id, operacion, rect, estado }) {
  const items = estado?.items ?? [];
  const resto = items.length - FILAS_MAX;
  return createPortal(
    <div id={id} role="tooltip" className={styles.card} style={posicion(rect)}>
      <p className={styles.titulo}>
        <Package size={14} aria-hidden="true" />
        Productos de la operación N° {operacion.id}
        <span className={styles.numero}>{operacion.numero}</span>
      </p>
      {(!estado || estado.estado === 'cargando') && (
        <p className={styles.nota}>
          <Loader2 size={14} className={styles.spin} aria-hidden="true" />
          Cargando productos…
        </p>
      )}
      {estado?.estado === 'error' && <p className={styles.nota}>No se pudieron leer los productos.</p>}
      {estado?.estado === 'ok' && items.length === 0 && (
        <p className={styles.nota}>La operación no tiene productos en sus órdenes de compra.</p>
      )}
      {estado?.estado === 'ok' && items.length > 0 && (
        <table className={styles.tabla}>
          <thead>
            <tr>
              <th scope="col">Producto</th>
              <th scope="col" className={styles.num}>
                Pedidas
              </th>
              <th scope="col" className={styles.num}>
                Recibidas
              </th>
            </tr>
          </thead>
          <tbody>
            {items.slice(0, FILAS_MAX).map((item) => (
              <tr key={item.item_id}>
                <td>
                  <span className={styles.producto}>
                    <span className={styles.codigo}>{item.codigo ?? `#${item.item_id}`}</span>
                    <span className={styles.descripcion}>{item.descripcion ?? 'Sin descripción'}</span>
                  </span>
                </td>
                <td className={styles.num}>{item.pedida}</td>
                <td className={styles.num}>{item.recibida}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {estado?.estado === 'ok' && resto > 0 && <p className={styles.nota}>y {resto} productos más</p>}
    </div>,
    document.body,
  );
}
