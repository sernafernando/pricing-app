/**
 * A list loaded in parts by offset (a "Todos" page): the next part's rows appended to the shown ones. A row that moved
 * between two requests stays once, by `keyOf` (publications by `item_id`).
 */
export function appendPage(rows, page, keyOf = (row) => row.item_id) {
  const seen = new Set(rows.map(keyOf));
  return [...rows, ...page.filter((row) => !seen.has(keyOf(row)))];
}
