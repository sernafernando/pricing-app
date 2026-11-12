import { ArrowDown, ArrowUp } from 'lucide-react';
import { formatUnits } from '../../../utils/metricasMlFormat';
import { ProductCard, PublicationCard } from './PhoneCards';
import styles from './PhoneLayout.module.css';

/**
 * The phone layout's list (mobile-metricas-pubml S2): how many there are, the sort (a column and its direction, the
 * same `orden` / `dir` as the table's headers), the cards and, under them, `footer` ("Cargar 20 más" or the pager).
 *
 * @param {object} props
 * @param {'publicacion'|'producto'} props.mode
 * @param {Array} props.rows The publications, or the Producto view's product nodes.
 * @param {number} props.total
 * @param {{ key: string, dir: string }} props.sort The applied sort's first key.
 * @param {Array<{ value: string, label: string }>} props.sortOptions
 * @param {(key: string) => void} props.onSort Same key: flips its direction; another: sorts by it.
 */
export default function PhoneList({
  mode,
  rows,
  total,
  sort,
  sortOptions,
  onSort,
  canSeeSales,
  canSeeMargin,
  selectedKey,
  onSelect,
  emptyMessage,
  loading,
  footer,
}) {
  const unit = mode === 'producto' ? 'productos' : 'publicaciones';
  const known = sortOptions.some((option) => option.value === sort?.key);
  const ascending = sort?.dir === 'asc';
  return (
    <section className={styles.list} aria-label={mode === 'producto' ? 'Productos' : 'Publicaciones'} aria-busy={loading}>
      <div className={styles.listBar}>
        <span className={styles.listCount}>
          {formatUnits(total)} {unit}
        </span>
        <div className={styles.sort}>
          <label className={styles.sortLabel}>
            Ordenar
            <select className={styles.sortSelect} value={known ? sort.key : ''} onChange={(event) => onSort(event.target.value)}>
              {!known && <option value="">—</option>}
              {sortOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          {known && (
            <button
              type="button"
              className={styles.iconButton}
              aria-label={ascending ? 'Orden ascendente: cambiar a descendente' : 'Orden descendente: cambiar a ascendente'}
              onClick={() => onSort(sort.key)}
            >
              {ascending ? <ArrowUp size={16} aria-hidden="true" /> : <ArrowDown size={16} aria-hidden="true" />}
            </button>
          )}
        </div>
      </div>
      {rows.length === 0 && !loading && <p className={styles.empty}>{emptyMessage}</p>}
      {rows.map((row) =>
        mode === 'producto' ? (
          <ProductCard
            key={row.key}
            node={row}
            canSeeSales={canSeeSales}
            canSeeMargin={canSeeMargin}
            selected={row.key === selectedKey}
            onSelect={onSelect}
          />
        ) : (
          <PublicationCard
            key={row.item_id}
            item={row}
            canSeeSales={canSeeSales}
            canSeeMargin={canSeeMargin}
            selected={row.item_id === selectedKey}
            onSelect={onSelect}
          />
        ),
      )}
      {footer}
    </section>
  );
}
