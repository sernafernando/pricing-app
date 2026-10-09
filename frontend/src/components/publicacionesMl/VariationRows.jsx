import { useState } from 'react';
import { formatAmount } from '../../utils/ventasMlFormat';
import MarkupCell from './MarkupCell';
import StockCell from './StockCell';
import { costLabel, readVariation } from './variationRows';
import { describeVariationsError, useVariations } from './useVariations';
import cellStyles from './cells.module.css';
import styles from './VariationRows.module.css';

/** Cell of a variation under the column `key`; columns it has nothing for stay empty. */
function VariationCell({ column, variation, canSeeMargin }) {
  switch (column.key) {
    case 'titulo':
      return (
        <div className={styles.identity}>
          <span className={styles.variationId}>Variación {variation.id}</span>
          {variation.attributes.length > 0 && <span className={styles.attributes}>{variation.attributes.join(' · ')}</span>}
          {variation.sku && <span className={cellStyles.code}>SKU {variation.sku}</span>}
          {variation.linked ? (
            <span className={styles.product}>{variation.productName ?? '—'}</span>
          ) : (
            <span className={cellStyles.empty}>Sin producto vinculado</span>
          )}
          {variation.inherited && <span className={cellStyles.note}>producto de la publicación</span>}
        </div>
      );
    case 'precio':
      // There is no cost column: a variation's cost sits under the price, where the figure is compared.
      if (!canSeeMargin) return null;
      return variation.cost == null ? (
        <span className={cellStyles.empty}>—</span>
      ) : (
        <div className={`${cellStyles.stack} ${cellStyles.stackEnd}`}>
          <span className={cellStyles.amount}>{formatAmount(variation.cost)}</span>
          <span className={cellStyles.note}>{costLabel(variation.costCurrency)}</span>
        </div>
      );
    case 'markup':
      return canSeeMargin ? <MarkupCell markup={variation.markup} /> : null;
    case 'stock_full':
      return <StockCell stock={{ available: variation.available, full: null, own: null }} />;
    default:
      return null;
  }
}

/** One full-width row for the loading / error / empty states. */
function StateRow({ span, depth, children }) {
  return (
    <tr className={styles.row}>
      <td colSpan={span} className={styles.stateCell}>
        <div className={styles.state} style={{ '--indent': depth + 1 }}>
          {children}
        </div>
      </td>
    </tr>
  );
}

/**
 * Sub-rows of an expanded publication (`TableShell` `renderSubRows`): one row
 * per variation under the same columns as the list, so SKU/EAN and product sit
 * in the pinned column and cost, markup and stock line up with their headers.
 * `depth` is the tree depth of the publication (0 in the list): the sub-rows sit one level under it.
 */
export default function VariationRows({ item, columns, canSeeMargin, depth = 0 }) {
  const [attempt, setAttempt] = useState(0);
  const { status, variations, error } = useVariations(item.item_id, attempt);
  const span = columns.length;

  if (status === 'loading') {
    return (
      <StateRow span={span} depth={depth}>
        <span role="status">Cargando variaciones…</span>
      </StateRow>
    );
  }
  if (status === 'error') {
    return (
      <StateRow span={span} depth={depth}>
        <span role="alert">{describeVariationsError(error)}</span>
        <button type="button" className="btn-tesla outline sm" onClick={() => setAttempt((n) => n + 1)}>
          Reintentar
        </button>
      </StateRow>
    );
  }
  if (variations.length === 0) {
    return (
      <StateRow span={span} depth={depth}>
        <span>Esta publicación no tiene variaciones</span>
      </StateRow>
    );
  }
  return variations.map((raw) => {
    const variation = readVariation(raw, { canSeeMargin });
    return (
      <tr
        key={variation.id}
        className={styles.row}
        style={{ '--indent': depth + 1 }}
        data-negative={variation.negative ? '' : undefined}
      >
        {columns.map((column, index) => (
          <td
            key={column.key}
            className={styles.cell}
            data-pinned={index === 0 ? '' : undefined}
            data-align={column.align}
          >
            <VariationCell column={column} variation={variation} canSeeMargin={canSeeMargin} />
          </td>
        ))}
      </tr>
    );
  });
}
