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
// what they billed under them) and its real 30-day markup, by the column that draws each. One definition: the header
// draws exactly these and Cifras leaves out exactly these, so the same permissions decide whether they exist.
export const PRODUCT_HEADER_COLUMNS = { sales: 'unidades_30d', billed: 'facturado_30d', markup: 'markup_30d' };
export const PRODUCT_HEADER_FIGURES = new Set(Object.values(PRODUCT_HEADER_COLUMNS));
