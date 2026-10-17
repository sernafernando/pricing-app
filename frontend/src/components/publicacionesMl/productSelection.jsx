import { SelectionCheckbox } from './ProductCheckbox';

/**
 * `columns` with the publication's product checkbox in the title cell; the other columns are untouched. The title
 * render receives the checkbox as its `after` slot and places it after its variations toggle, so the toggle keeps
 * leading the pinned cell at the row's depth.
 */
export function withProductSelection(columns, selection) {
  return columns.map((column) =>
    column.key !== 'titulo'
      ? column
      : {
          ...column,
          render: (item) =>
            column.render(
              item,
              <SelectionCheckbox productId={item.link?.producto_item_id ?? null} label={item.item_id} selection={selection} />,
            ),
        },
  );
}
