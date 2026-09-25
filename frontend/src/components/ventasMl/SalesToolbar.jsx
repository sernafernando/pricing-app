/**
 * SalesToolbar — search box for the Ventas ML listing (ventas-ml-rediseno
 * PR14.T1/T3, design D14, SEARCH R25/R26/R27).
 *
 * The search box is a FILTER, not a separate mode: `useSales`/`VentasML`
 * combine the debounced `q` value with every other active filter
 * (operation/goods status, product facets, date range) as an
 * INTERSECTION — never a replacement (SEARCH R26). This component only
 * owns the input's debounce and the explicit "sin resultados" state; the
 * combination itself happens where the request is built.
 */

import SearchInput from '../SearchInput';
import styles from './SalesToolbar.module.css';

const SEARCH_DEBOUNCE_MS = 400;

export default function SalesToolbar({ value, onSearchChange, noResults = false }) {
  return (
    <div className={styles.toolbar}>
      <SearchInput
        value={value}
        onChange={onSearchChange}
        debounce={SEARCH_DEBOUNCE_MS}
        placeholder="Buscar por orden, pack, MLA, SKU o comprador…"
        className={styles.search}
      />
      {noResults && (
        // SEARCH R27: an empty/no-match search is an explicit STATE, not an
        // error — distinct styling from `.errorBar` on purpose (no danger
        // color, no icon implying something failed).
        <p className={styles.noResults} role="status">
          Sin resultados para esta búsqueda.
        </p>
      )}
    </div>
  );
}
