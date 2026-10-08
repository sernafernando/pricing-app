import { useMemo } from 'react';
import { TableShell } from '../kit';
import VariationRows from './VariationRows';
import useGroupTree from './useGroupTree';
import { BranchState, NodeCount, NodeMarkup, NodeNegatives, NodeTitle } from './NodeCells';

/**
 * Agrupado view of Publicaciones ML (publicaciones-ml-vista P12a):
 * marca > categoría > subcategoría > producto > [familia] > publicación, in the
 * kit's `TableShell` (`getRowDepth` indents, `renderSubRows` keeps the
 * variation sub-rows of a leaf publication).
 *
 * `columns` are the page's visible ones (`buildColumns({agrupado: true})`):
 * a node fills the columns it has a figure for -- name, count, negatives,
 * markup range -- and a publication fills them all, exactly like the list.
 * The tree has no sort. The user's filters (the store included) reach every
 * level; the markup filters do not (`/groups` does not apply them).
 */
export default function AgrupadoTable({
  columns,
  filters,
  familias,
  canSeeMargin,
  expandedIds,
  onSelectItem,
  selectedKey,
  offset,
  emptyMessage = 'Ninguna publicación coincide con los filtros',
}) {
  const { rows, toggle, loadMore } = useGroupTree({ filters, familias, canSeeMargin });

  const treeColumns = useMemo(
    () =>
      columns.map((column, index) => ({
        ...column,
        sortable: false,
        render: (row) => {
          if (row.type === 'item') return column.render(row.item);
          if (row.type === 'node') {
            if (column.key === 'titulo') return <NodeTitle row={row} onToggle={toggle} />;
            if (column.key === 'publicaciones') return <NodeCount node={row.node} />;
            if (column.key === 'negativos') return <NodeNegatives node={row.node} />;
            if (column.key === 'markup') return <NodeMarkup node={row.node} />;
            return null;
          }
          // "Ver más" and the states of a branch live in the pinned cell.
          return index === 0 ? <BranchState row={row} onMore={loadMore} onRetry={loadMore} /> : null;
        },
      })),
    [columns, toggle, loadMore],
  );

  // The page selects by MLA; the table by row, so only one row is highlighted.
  const selectedRowId = selectedKey === undefined ? undefined : rows.find((row) => row.type === 'item' && row.item.item_id === selectedKey)?.id;

  const handleRowClick = (row, event) => {
    if (row.type === 'node') toggle(row);
    else if (row.type === 'item') onSelectItem(row.item, event);
  };

  return (
    <TableShell
      columns={treeColumns}
      rows={rows}
      getRowKey={(row) => row.id}
      getRowDepth={(row) => row.depth}
      renderSubRows={(row) =>
        row.type === 'item' && row.item.variations_count > 1 && expandedIds.has(row.item.item_id) ? (
          <VariationRows item={row.item} columns={columns} canSeeMargin={canSeeMargin} depth={row.depth} />
        ) : null
      }
      onRowClick={handleRowClick}
      selectedKey={selectedRowId}
      offset={offset}
      emptyMessage={emptyMessage}
      ariaLabel="Publicaciones de Mercado Libre agrupadas"
    />
  );
}
