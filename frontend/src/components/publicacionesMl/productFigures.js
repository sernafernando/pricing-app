// The columns whose cell reads only `metrics`: a product row of ProductoTable and the product panel draw them with
// the publications' own cells, over the product's summed figures.
export const PRODUCT_FIGURES = new Set([
  'unidades_7d',
  'unidades_30d',
  'units_trend',
  'markup_30d',
  'markup_trend',
  'facturado_30d',
  'total_gauss_30d',
  'last_sale',
  'ageing',
]);

// The figures a product panel keeps in its header on every tab (S1) instead of under Cifras: its 30-day sales (with
// what they billed under them) and its real 30-day markup. They come from the same columns, so the same permissions
// decide whether they exist.
export const PRODUCT_HEADER_FIGURES = new Set(['unidades_30d', 'facturado_30d', 'markup_30d']);
