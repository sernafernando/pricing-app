/**
 * The ONE place the Métricas ML board turns its filter state into request
 * params (ODD `metricas-ml-tablero` T4) -- the board, the nested
 * publications and the CSV export all go through it, so they can never
 * disagree about what is filtered. Paging/sorting are added by the caller.
 */
export function buildMetricasMLParams({
  fechaDesde,
  fechaHasta,
  compararCon,
  groupBy,
  searchQuery,
  productFilters,
  storeFilter,
  pubStatus,
  pubType,
  pubStatusExclude,
  pubTypeExclude,
  alerts,
  soloConVentas = true,
}) {
  const params = {
    date_from: fechaDesde,
    date_to: fechaHasta,
    comparar_con: compararCon,
    group_by: groupBy,
    // Always explicit: the board's own default must never decide which
    // rows the operator sees.
    solo_con_ventas: soloConVentas,
  };
  if (searchQuery) params.q = searchQuery;
  if (productFilters?.marcas?.length > 0) params.marcas = productFilters.marcas.join(',');
  if (productFilters?.subcategorias?.length > 0) params.subcategorias = productFilters.subcategorias.join(',');
  if (productFilters?.pms?.length > 0) params.pms = productFilters.pms.join(',');
  if (storeFilter) params.stores = storeFilter;
  if (pubStatus?.length > 0) params.pub_status = pubStatus.join(',');
  if (pubType?.length > 0) params.pub_type = pubType.join(',');
  if (pubStatusExclude?.length > 0) params.pub_status_exclude = pubStatusExclude.join(',');
  if (pubTypeExclude?.length > 0) params.pub_type_exclude = pubTypeExclude.join(',');
  if (alerts?.length > 0) params.alerts = alerts.join(',');
  return params;
}
