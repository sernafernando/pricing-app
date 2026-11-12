/**
 * Pure helpers of the Métricas ML phone layout (handoffs `mobile-metricas-pubml-tarea` T1): the compact money of
 * the KPI and card figures, the active-filter chips under the header, and the sorts the sort button offers. The
 * phone reads the same board as the desktop; these only decide how it is said in less width.
 */
import {
  AGEING_LABELS,
  PUB_STATUS_LABELS,
  PUB_TYPE_LABELS,
  STOCK_LABELS,
} from '../../../utils/metricasMlFormat';

const ONE_DECIMAL = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const INT = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 });

const toNumber = (value) => {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

/** `$ 312,4 M` from a million up, `$ 710.400` below; the minus before the sign, as `formatSignedMoney`. */
export function formatCompactMoney(value) {
  const n = toNumber(value);
  if (n === null) return '—';
  const abs = Math.abs(n);
  const text = abs >= 1_000_000 ? `$ ${ONE_DECIMAL.format(abs / 1_000_000)} M` : `$ ${INT.format(abs)}`;
  return n < 0 ? `-${text}` : text;
}

const GROUP_LABELS = { product: 'Producto', publication: 'Publicación', group: 'Agrupado' };

const ALERT_LABELS = {
  sin_ventas_30d: 'Sin ventas 30d',
  ageing_60d: 'Ageing > 60d',
  margen_cayendo: 'Markup cayendo',
};

const PRODUCT_FILTER_LABELS = [
  ['marcas', 'Marcas'],
  ['categorias', 'Categorías'],
  ['subcategorias', 'Subcategorías'],
  ['pms', 'PMs'],
];

/** One chip per included value (its label) and per excluded one ("Sin <label>"). */
function toggleChips(selected, excluded, labels) {
  return [...selected.map((value) => labels[value] ?? value), ...excluded.map((value) => `Sin ${labels[value] ?? value}`)];
}

/**
 * The chips under the header and the "Filtros (n)" count. The grouping is always named (it says what the cards
 * are), but counts only when it is not the default Producto; "Solo con ventas" counts only when turned off.
 */
export function activeFilterChips({
  groupBy,
  storeLabel,
  stock,
  stockExclude,
  ageing,
  ageingExclude,
  alerts,
  soloConVentas,
  pubStatus,
  pubStatusExclude,
  pubType,
  pubTypeExclude,
  productFilters,
}) {
  const filters = [
    ...(storeLabel ? [`Tienda: ${storeLabel}`] : []),
    ...toggleChips(stock, stockExclude, STOCK_LABELS),
    ...(soloConVentas ? [] : ['Con y sin ventas']),
    ...toggleChips(ageing, ageingExclude, AGEING_LABELS),
    ...alerts.map((value) => ALERT_LABELS[value] ?? value),
    ...toggleChips(pubStatus, pubStatusExclude, PUB_STATUS_LABELS),
    ...toggleChips(pubType, pubTypeExclude, PUB_TYPE_LABELS),
    ...PRODUCT_FILTER_LABELS.filter(([key]) => productFilters?.[key]?.length).map(
      ([key, label]) => `${label} (${productFilters[key].length})`,
    ),
  ];
  const grouped = groupBy !== 'product';
  return {
    chips: [`Agrupar: ${GROUP_LABELS[groupBy] ?? groupBy}`, ...filters],
    count: filters.length + (grouped ? 1 : 0),
  };
}

/**
 * The sorts of the phone's sort button: the board's own sort keys, never one the board would refuse (a margin sort
 * without the profit view, Total TP without the TP costs). `tplink.solo` has Total TP in Total Gauss's place.
 */
export function phoneSortOptions({ canSeeMargin, tpOn, tpSolo }) {
  return [
    { value: 'gross', label: 'Facturado' },
    { value: 'units', label: 'Unidades' },
    ...(canSeeMargin ? [{ value: 'markup', label: 'Markup' }] : []),
    ...(canSeeMargin && !tpSolo ? [{ value: 'total_gauss', label: 'Total Gauss' }] : []),
    ...(canSeeMargin && (tpOn || tpSolo) ? [{ value: 'total_tp', label: 'Total TP' }] : []),
    { value: 'stock', label: 'Stock' },
    { value: 'ageing', label: 'Ageing' },
    { value: 'last_sale', label: 'Última venta' },
    { value: 'title', label: 'Nombre' },
  ];
}
