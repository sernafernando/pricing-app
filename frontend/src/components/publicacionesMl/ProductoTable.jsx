import { useCallback, useMemo } from 'react';
import { TableShell } from '../kit';
import { PRODUCT_FIGURES } from './productFigures';
import VariationRows from './VariationRows';
import { treeRowTone } from './rowColor';
import { BranchState, NodeCount, NodeTitle } from './NodeCells';
import { SelectionCheckbox } from './ProductCheckbox';
import { PRODUCT_SORTS } from '../../hooks/usePublicacionesMLFilters';
import PrearmadaBadge from '../PrearmadaBadge';
import PxqTramosBadge from '../PxqTramosBadge';

/**
 * Producto view of Publicaciones ML, like Métricas ML's: one row per product
 * (`tree` from `useProductRows`), opening into its publications, in the kit's
 * `TableShell` (`getRowDepth` indents, `renderSubRows` keeps the variation
 * sub-rows of a publication).
 *
 * `columns` are the page's visible ones (`buildColumns({producto: true})`): a
 * product fills its name, its publication count, its code, brand, ERP stock and
 * cost (`PRODUCT_FIELDS`), and the sum of its publications' Métricas ML figures
 * (the row's `metrics` has the publications' shape, so the same cells draw it;
 * null reads "—"); a
 * publication fills them all, exactly like the list. Only the product figures
 * are sortable (`PRODUCT_SORTS`): the backend sorts the products, not their
 * publications. With `selection` (`{ checked, onToggle }`) a product row leads
 * with its product's checkbox, for the bulk pricing actions. A column with `renderProduct` (Productos' prices, S11)
 * draws a product row from the product's id.
 *
 * A click (or Enter/Space) on a product row opens its panel (`onSelectProduct(key)`); its chevron opens it into
 * its publications. The highlighted row is the selected publication (`selectedKey`) or, with none, the product
 * whose panel is open (`selectedProductKey`).
 *
 * Beside a product's name, Productos' badges: its prearmadas (`prearmadasStats`, by product id, from the page) and its
 * wholesale (PxQ) tiers (the row's `pxq_tramos` / `pxq_precio_desde`).
 */
// The columns a product row fills from its own product, as Productos' rows carry it: drawn by the publications' own
// cells over the product read in their shape (`productAsItem`).
const PRODUCT_FIELDS = new Set(['codigo', 'marca', 'costo', 'stock_erp']);

// No prearmadas stats given: one stable object, so the columns are not rebuilt on every render.
const NO_PREARMADAS = {};

/** A product node in the shape the publication cells read: its code and brand as a link's, its ERP stock, its cost
 * and the lines under it. */
function productAsItem(node) {
  return {
    link: { codigo: node.codigo, marca: node.marca },
    erp_stock: node.stock == null ? null : { quantity: node.stock },
    costo: node.costo,
    ppp: node.ppp,
    sell_in_out: node.sellInOut,
  };
}

export default function ProductoTable({
  tree,
  columns,
  canSeeMargin,
  expandedIds,
  onSelectItem,
  onSelectProduct,
  selectedKey,
  selectedProductKey,
  sort,
  onSort,
  offset,
  colorOverlay,
  emptyMessage = 'Ningún producto coincide con los filtros',
  selection,
  prearmadasStats = NO_PREARMADAS,
}) {
  const { rows, toggle, loadMore } = tree;

  const productColumns = useMemo(
    () =>
      columns.map((column, index) => ({
        ...column,
        sortable: Boolean(column.sortable) && PRODUCT_SORTS.includes(column.key),
        render: (row) => {
          if (row.type === 'item') return column.render(row.item);
          if (row.type === 'node') {
            if (column.key === 'titulo') {
              // The checkbox follows the node's toggle, so the toggle stays at the row's depth.
              const after = selection ? (
                <SelectionCheckbox productId={row.node.productoItemId} label={row.node.label} selection={selection} />
              ) : null;
              const { node } = row;
              const badges = (
                <>
                  <PrearmadaBadge stats={prearmadasStats[node.productoItemId]} />
                  <PxqTramosBadge tramos={node.pxqTramos} precioDesde={node.pxqPrecioDesde} />
                </>
              );
              return <NodeTitle row={row} onToggle={toggle} after={after} badges={badges} />;
            }
            if (column.key === 'publicaciones') return <NodeCount node={row.node} />;
            if (PRODUCT_FIGURES.has(column.key)) return column.render({ metrics: row.node.metrics });
            if (PRODUCT_FIELDS.has(column.key)) return column.render(productAsItem(row.node));
            if (column.renderProduct) return column.renderProduct(row.node.productoItemId);
            return null;
          }
          // "Ver más" and the states of a product's publications live in the pinned cell.
          return index === 0 ? <BranchState row={row} onMore={loadMore} onRetry={loadMore} /> : null;
        },
      })),
    [columns, toggle, loadMore, selection, prearmadasStats],
  );

  // The page selects by MLA; the table by row, so only one row is highlighted.
  const selectedRowId =
    selectedKey !== undefined
      ? rows.find((row) => row.type === 'item' && row.item.item_id === selectedKey)?.id
      : selectedProductKey !== undefined
        ? rows.find((row) => row.type === 'node' && row.node.key === selectedProductKey)?.id
        : undefined;

  // The colors painted since the rows loaded (`useColorOverlay`) win over the rows' own.
  const getRowTone = useCallback((row) => treeRowTone(row, colorOverlay), [colorOverlay]);

  const handleRowClick = (row, event) => {
    if (row.type === 'node') onSelectProduct(row.node.key);
    else if (row.type === 'item') onSelectItem(row.item, event);
  };

  return (
    <TableShell
      columns={productColumns}
      rows={rows}
      getRowKey={(row) => row.id}
      getRowDepth={(row) => row.depth}
      getRowTone={getRowTone}
      renderSubRows={(row) =>
        row.type === 'item' && row.item.variations_count > 1 && expandedIds.has(row.item.item_id) ? (
          <VariationRows item={row.item} columns={columns} canSeeMargin={canSeeMargin} depth={row.depth} />
        ) : null
      }
      sort={sort}
      onSort={onSort}
      onRowClick={handleRowClick}
      selectedKey={selectedRowId}
      offset={offset}
      emptyMessage={emptyMessage}
      ariaLabel="Publicaciones de Mercado Libre por producto"
    />
  );
}
