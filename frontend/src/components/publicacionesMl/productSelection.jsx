import { PageCheckbox, SelectionCheckbox } from './ProductCheckbox';

/**
 * `columns` with the publication's product checkbox in the title cell; the other columns are untouched. The title
 * render receives the checkbox as its `after` slot and places it after its variations toggle, so the toggle keeps
 * leading the pinned cell at the row's depth. With `selection.togglePage` and products on the page, the title's header
 * gets the page's checkbox.
 */
export function withProductSelection(columns, selection) {
  return columns.map((column) =>
    column.key !== 'titulo'
      ? column
      : {
          ...column,
          headerControl:
            selection.togglePage && selection.pageState !== 'empty' ? (
              <PageCheckbox state={selection.pageState} onToggle={selection.togglePage} />
            ) : undefined,
          render: (item) =>
            column.render(
              item,
              <SelectionCheckbox productId={item.link?.producto_item_id ?? null} label={item.item_id} selection={selection} />,
            ),
        },
  );
}
