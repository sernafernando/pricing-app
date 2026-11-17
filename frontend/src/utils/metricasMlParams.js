import { TP_SOLO_DIMENSION } from './metricasMlTp';
import { DEFAULT_COSTO } from './metricasMlCanal';

// Alerts of one channel only: "Sin producto" exists only with fuera lines; the ML stale alerts are not offered on
// Por fuera (approved mockup 2).
const FUERA_ONLY_ALERTS = new Set(['sin_producto']);
const ML_ONLY_ALERTS = new Set(['sin_ventas_30d', 'ageing_60d']);

/**
 * The ONE place the Métricas ML board turns its filter state into request
 * params (ODD `metricas-ml-tablero` T4) -- the board, the nested
 * publications and the CSV export all go through it, so they can never
 * disagree about what is filtered. Paging/sorting are added by the caller.
 *
 * `canal` (vpf-metricas-canal-fe C3): with ML (the default) the params are exactly the ones they always were; with
 * fuera or todo they add `canal`, `costo` and the fuera filters `empresas` / `vendedores`. Por fuera has no store
 * nor publication, so it never sends those ML-only filters.
 */
export function buildMetricasMLParams({
  fechaDesde,
  fechaHasta,
  compararCon,
  groupBy,
  dimension = 'marca',
  searchQuery,
  productFilters,
  storeFilter,
  pubStatus,
  pubType,
  pubStatusExclude,
  pubTypeExclude,
  alerts,
  stock,
  stockExclude,
  ageing,
  ageingExclude,
  soloConVentas = true,
  tpSolo = false,
  canal = 'ml',
  costo = DEFAULT_COSTO,
  empresas = [],
  vendedores = [],
}) {
  const fuera = canal === 'fuera';
  const ml = canal === 'ml';
  const shownAlerts = (alerts ?? []).filter(
    (alert) => !(ml && FUERA_ONLY_ALERTS.has(alert)) && !(fuera && ML_ONLY_ALERTS.has(alert)),
  );
  const params = {
    date_from: fechaDesde,
    date_to: fechaHasta,
    comparar_con: compararCon,
    group_by: groupBy,
    // Always explicit: the board's own default must never decide which
    // rows the operator sees.
    solo_con_ventas: soloConVentas,
  };
  // What the "Agrupado" view sums by; the other views have no dimension.
  // A `tplink.solo` user's board takes "Agrupado" by tienda only, and no PM (the backend answers 422).
  if (groupBy === 'group') params.dimension = tpSolo ? TP_SOLO_DIMENSION : dimension;
  if (searchQuery) params.q = searchQuery;
  if (productFilters?.marcas?.length > 0) params.marcas = productFilters.marcas.join(',');
  if (productFilters?.categorias?.length > 0) params.categorias = productFilters.categorias.join(',');
  if (productFilters?.subcategorias?.length > 0) params.subcategorias = productFilters.subcategorias.join(',');
  if (!tpSolo && productFilters?.pms?.length > 0) params.pms = productFilters.pms.join(',');
  if (!fuera) {
    if (storeFilter) params.stores = storeFilter;
    if (pubStatus?.length > 0) params.pub_status = pubStatus.join(',');
    if (pubType?.length > 0) params.pub_type = pubType.join(',');
    if (pubStatusExclude?.length > 0) params.pub_status_exclude = pubStatusExclude.join(',');
    if (pubTypeExclude?.length > 0) params.pub_type_exclude = pubTypeExclude.join(',');
  }
  if (shownAlerts.length > 0) params.alerts = shownAlerts.join(',');
  if (stock?.length > 0) params.stock = stock.join(',');
  if (stockExclude?.length > 0) params.stock_exclude = stockExclude.join(',');
  if (ageing?.length > 0) params.ageing = ageing.join(',');
  if (ageingExclude?.length > 0) params.ageing_exclude = ageingExclude.join(',');
  if (!ml) {
    params.canal = canal;
    params.costo = costo;
    if (empresas?.length > 0) params.empresas = empresas.join(',');
    if (vendedores?.length > 0) params.vendedores = vendedores.join(',');
  }
  return params;
}
