import { useMemo } from 'react';
import { priceColumns } from '../priceColumns';
import useListPrices from '../useListPrices';
import styles from './ListPriceGroup.module.css';

// The Precios view's price modes, each one a row of the group; Calcular once, on the first.
const MODES = [
  { mode: 'normal', label: 'Normal' },
  { mode: 'cuotas', label: 'Cuotas' },
  { mode: 'pvp', label: 'PVP' },
];

/**
 * The Precios view's "Precios de Productos" group for one product, in a panel's Precios tab (owner, 2026-10-28):
 * the very columns of the list (`priceColumns`, their `ListPriceCell` / `PriceEditCell` / `ToggleEditCell` and
 * Calcular), one table per mode, so whatever the list's price cells show or edit shows here too. The prices are
 * Productos' listing of that product (`useListPrices`), read again when `version` changes (the page's list reload
 * after a write).
 *
 * `group` is what the page hands the list's columns: `edit` (the list's write handlers and permissions),
 * `onCalculate` (the pricing modal), `offsets` (markup con offsets) and `version`. Without it the prices read only.
 */
export default function ListPriceGroup({ productItemId, canSeeMargin = false, group = null }) {
  const ids = useMemo(() => [productItemId], [productItemId]);
  const prices = useListPrices(ids, productItemId != null, group?.version ?? 0);
  const options = { prices, canSeeMargin, edit: group?.edit ?? null, offsets: group?.offsets ?? null };

  return (
    <section className={styles.group} aria-label="Precios de la lista">
      {MODES.map(({ mode, label }, index) => {
        const columns = priceColumns(mode, { ...options, onCalculate: index === 0 ? (group?.onCalculate ?? null) : null });
        return (
          <table key={mode} className={styles.table}>
            <caption className={styles.caption}>{label}</caption>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column.key} scope="col" className={styles.head} data-align={column.align}>
                    {column.header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                {columns.map((column) => (
                  <td key={column.key} className={styles.cell} data-align={column.align}>
                    {column.renderProduct(productItemId)}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        );
      })}
    </section>
  );
}
