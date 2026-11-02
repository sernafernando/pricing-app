import { PageCheckbox, SelectionCheckbox } from './ProductCheckbox';
import { publicationKey } from './useRowSelection';

/**
 * `columns` with the publication's own checkbox in the title cell; the other columns are untouched. The title
 * render receives the checkbox as its `after` slot and places it after its variations toggle, so the toggle keeps
 * leading the pinned cell at the row's depth. With `selection.togglePage` and rows on the page, the title's header
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
              <SelectionCheckbox rowKey={publicationKey(item.item_id)} label={item.item_id} selection={selection} />,
            ),
        },
  );
}
