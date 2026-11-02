import { count } from './format';

/**
 * The header figures of a product (S1): its stock, then the 30-day sales and markup the list's columns draw for it.
 *
 * @param {object} summary The product row (`readProduct`).
 * @param {object[]} columns The product's figure columns, already filtered by permission (`buildColumns`).
 */
export function productHeaderFigures(summary, columns) {
  const byKey = new Map(columns.map((column) => [column.key, column]));
  const draw = (key) => byKey.get(key)?.render({ metrics: summary.metrics });
  const figures = [{ key: 'stock', label: 'Stock', value: summary.stock == null ? null : count(summary.stock) }];
  if (byKey.has('unidades_30d')) {
    figures.push({
      key: 'sales',
      label: 'Ventas 30 días',
      value: draw('unidades_30d'),
      note: byKey.has('facturado_30d') ? <>Facturado {draw('facturado_30d')}</> : null,
    });
  }
  if (byKey.has('markup_30d')) figures.push({ key: 'markup', label: 'Markup 30 días', value: draw('markup_30d') });
  return figures;
}
