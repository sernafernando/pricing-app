/**
 * The Auditoría de stock view's rows (auditoria-stock S3-S7, S10), from `GET /view/stock-audit`: a base product (or
 * a PC) opens into its own publications and its variants / packs, and a variant opens into its publications. The
 * publications are the `/view/items` rows of the node's `params`, as the Producto view opens a product.
 *
 * Every number shown is the backend's except two derived from it, both from the same row:
 *  - a variant's or a pack's units in base units (its own times `cantidad`), for its 7D / 30D / Full cells;
 *  - a publication's Full value: its Full units at its node's cost (the node's `costo` and currency, the response's
 *    BNA rate), what the backend sums into the node.
 */

/** A row's or a variant's `ventas` in the shape the list's metrics cells read (`MetricsCells`): the sell in / out
 * figures where they apply (the backend's `_sell_` ones), else the plain ones. `factor` turns a pack's units into
 * base units. */
export function auditMetrics(ventas, factor = 1) {
  if (!ventas) return null;
  return {
    units_7d: ventas.unidades_7d * factor,
    units_30d: ventas.unidades_30d * factor,
    series_units_90d: ventas.series_units_90d ?? [],
    gross_30d: ventas.facturado_30d,
    total_gauss_30d: ventas.total_gauss_sell_30d ?? ventas.total_gauss_30d ?? null,
    markup_30d: ventas.markup_sell_30d ?? ventas.markup_30d ?? null,
    series_markup_90d: ventas.series_markup_90d ?? null,
  };
}

/** The current markup range in the list's `MarkupCell` shape; null without it (no permission or no value). */
export function auditMarkup(range) {
  if (!range) return null;
  return { min: range.min, max: range.max, worst: range.min, any_negative: range.min < 0, partial: 0, reason: '' };
}

/** A pack's quantity of base units ("x2"); 1 for a notebook variant. */
const quantityOf = (variant) => Number(variant.cantidad) || 1;
export const isPack = (variant) => variant.tipo === 'pack' && quantityOf(variant) !== 1;

/** What a base row's Full and 30D sales got from its variants (in base units), and how to say where from:
 * "del pack x2" when it is all one pack, "de variantes" otherwise. */
export function fromVariants(row) {
  const full = row.variantes.reduce((sum, v) => sum + (v.full_unidades_base ?? 0), 0);
  const sold = row.variantes.reduce((sum, v) => sum + (v.ventas?.unidades_30d ?? 0) * quantityOf(v), 0);
  const contributing = row.variantes.filter((v) => (v.full_unidades_base ?? 0) > 0 || (v.ventas?.unidades_30d ?? 0) > 0);
  const only = contributing.length === 1 ? contributing[0] : null;
  const source = only && only.tipo === 'pack' ? `del pack x${quantityOf(only)}` : 'de variantes';
  return { full, sold, source };
}

/** Units of `product` at its cost, in USD and ARS at `rate` (ARS per USD); null where unknown. */
export function valueOf(units, { costo, moneda_costo: moneda }, rate) {
  if (units == null || costo == null) return { usd: null, ars: null };
  const amount = costo * units;
  if (moneda === 'USD') return { usd: amount, ars: rate ? amount * rate : null };
  return { usd: rate ? amount / rate : null, ars: amount };
}

const productKey = (row) => `p:${row.key}`;
const variantKey = (variant) => `v:${variant.key}`;

/**
 * The table's rows in order: each product, and when open its own publications then its variants (each open one
 * followed by its publications). `branches[key]` is what a node's publications loaded (`{ status, items, total,
 * error }`); a node with no publication of its own asks nothing. A state row ("Cargando…", an error, "Ver más")
 * follows a branch that is not fully in.
 */
export function flattenAudit(rows, expanded, branches) {
  const out = [];
  const publications = (owner, key, count, depth) => {
    if (count === 0) return;
    const branch = branches[key];
    if (!branch || branch.status === 'loading') {
      out.push({ type: 'state', id: `${key}#state`, depth, state: 'loading', pathKey: key });
      return;
    }
    for (const item of branch.items) out.push({ type: 'item', id: `${key}#${item.item_id}`, depth, item, owner });
    if (branch.status === 'error') out.push({ type: 'state', id: `${key}#state`, depth, state: 'error', error: branch.error, pathKey: key });
    else if (branch.items.length === 0) out.push({ type: 'state', id: `${key}#state`, depth, state: 'empty', pathKey: key });
    else if (branch.items.length < branch.total) {
      out.push({ type: 'more', id: `${key}#more`, depth, pathKey: key, remaining: branch.total - branch.items.length, loading: branch.status === 'more' });
    }
  };
  for (const row of rows) {
    const key = productKey(row);
    const open = expanded.has(key);
    out.push({ type: 'product', id: key, depth: 0, node: row, expanded: open, pathKey: key });
    if (!open) continue;
    publications(row, key, row.publications_count, 1);
    for (const variant of row.variantes) {
      const vKey = variantKey(variant);
      const vOpen = expanded.has(vKey);
      out.push({ type: 'variant', id: vKey, depth: 1, node: variant, parent: row, expanded: vOpen, pathKey: vKey });
      if (vOpen) publications(variant, vKey, variant.publications_count, 2);
    }
  }
  return out;
}
