import { WithProductCheckbox } from './ProductCheckbox';

/** `columns` with the publication's product checkbox leading the title cell; the other columns are untouched. */
export function withProductSelection(columns, selection) {
  return columns.map((column) =>
    column.key !== 'titulo'
      ? column
      : {
          ...column,
          render: (item) => (
            <WithProductCheckbox productId={item.link?.producto_item_id ?? null} label={item.item_id} selection={selection}>
              {column.render(item)}
            </WithProductCheckbox>
          ),
        },
  );
}
