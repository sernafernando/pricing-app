// Query-string builder for the export endpoints, split out of ExportModal.jsx
// so react-refresh only sees component exports there (same reason as
// `promociones/treeNodeUtils.js`).

/**
 * Cross-DB filters (promos, wholesale tiers) travel with the rest: the export
 * must cover the SAME set the listing shows, and the backend already folds
 * them (`_apply_promo_filters` / `_apply_pxq_filter`, fail-closed).
 *
 * Exported for the parity test in `masivoFilterParity.test.jsx`.
 */
export const buildFilterQueryString = (filtrosActivos) => {
  let params = '';
  if (filtrosActivos.search) params += `&search=${encodeURIComponent(filtrosActivos.search)}`;
  if (filtrosActivos.con_stock === true) params += `&con_stock=true`;
  if (filtrosActivos.con_stock === false) params += `&con_stock=false`;
  if (filtrosActivos.con_precio === true) params += `&con_precio=true`;
  if (filtrosActivos.con_precio === false) params += `&con_precio=false`;
  if (filtrosActivos.marcas?.length > 0) params += `&marcas=${filtrosActivos.marcas.join(',')}`;
  if (filtrosActivos.subcategorias?.length > 0) params += `&subcategorias=${filtrosActivos.subcategorias.join(',')}`;
  if (filtrosActivos.filtroRebate === 'con_rebate') params += `&con_rebate=true`;
  if (filtrosActivos.filtroRebate === 'sin_rebate') params += `&con_rebate=false`;
  if (filtrosActivos.filtroOferta === 'con_oferta') params += `&con_oferta=true`;
  if (filtrosActivos.filtroOferta === 'sin_oferta') params += `&con_oferta=false`;
  if (filtrosActivos.filtroWebTransf === 'con_web_transf') params += `&con_web_transf=true`;
  if (filtrosActivos.filtroWebTransf === 'sin_web_transf') params += `&con_web_transf=false`;
  if (filtrosActivos.filtroTiendaNube === 'con_descuento') params += `&tiendanube_con_descuento=true`;
  if (filtrosActivos.filtroTiendaNube === 'sin_descuento') params += `&tiendanube_sin_descuento=true`;
  if (filtrosActivos.filtroTiendaNube === 'no_publicado') params += `&tiendanube_no_publicado=true`;
  if (filtrosActivos.filtroMarkupClasica === 'positivo') params += `&markup_clasica_positivo=true`;
  if (filtrosActivos.filtroMarkupClasica === 'negativo') params += `&markup_clasica_positivo=false`;
  if (filtrosActivos.filtroMarkupRebate === 'positivo') params += `&markup_rebate_positivo=true`;
  if (filtrosActivos.filtroMarkupRebate === 'negativo') params += `&markup_rebate_positivo=false`;
  if (filtrosActivos.filtroMarkupOferta === 'positivo') params += `&markup_oferta_positivo=true`;
  if (filtrosActivos.filtroMarkupOferta === 'negativo') params += `&markup_oferta_positivo=false`;
  if (filtrosActivos.filtroMarkupWebTransf === 'positivo') params += `&markup_web_transf_positivo=true`;
  if (filtrosActivos.filtroMarkupWebTransf === 'negativo') params += `&markup_web_transf_positivo=false`;
  if (filtrosActivos.filtroOutOfCards === 'con_out_of_cards') params += `&out_of_cards=true`;
  if (filtrosActivos.filtroOutOfCards === 'sin_out_of_cards') params += `&out_of_cards=false`;
  if (filtrosActivos.coloresSeleccionados?.length > 0) params += `&colores=${filtrosActivos.coloresSeleccionados.join(',')}`;
  if (filtrosActivos.pmsSeleccionados?.length > 0) params += `&pms=${filtrosActivos.pmsSeleccionados.join(',')}`;
  if (filtrosActivos.audit_usuarios?.length > 0) params += `&audit_usuarios=${filtrosActivos.audit_usuarios.join(',')}`;
  if (filtrosActivos.audit_tipos_accion?.length > 0) params += `&audit_tipos_accion=${filtrosActivos.audit_tipos_accion.join(',')}`;
  if (filtrosActivos.audit_fecha_desde) params += `&audit_fecha_desde=${filtrosActivos.audit_fecha_desde}`;
  if (filtrosActivos.audit_fecha_hasta) params += `&audit_fecha_hasta=${filtrosActivos.audit_fecha_hasta}`;
  if (filtrosActivos.filtroMLA === 'con_mla') params += `&con_mla=true`;
  if (filtrosActivos.filtroMLA === 'sin_mla') params += `&con_mla=false`;
  if (filtrosActivos.filtroEstadoMLA === 'activa') params += `&estado_mla=activa`;
  if (filtrosActivos.filtroEstadoMLA === 'pausada') params += `&estado_mla=pausada`;
  if (filtrosActivos.filtroNuevos === 'ultimos_7_dias') params += `&nuevos_ultimos_7_dias=true`;
  if (filtrosActivos.filtroTiendaOficial) params += `&tienda_oficial=${filtrosActivos.filtroTiendaOficial}`;
  // Sin equipo_id el backend resuelve la capa global y `colores` filtraría sobre
  // una capa distinta a la de la vista (ver resolver_layer_activo en el backend).
  if (filtrosActivos.equipoActivoId) params += `&equipo_id=${filtrosActivos.equipoActivoId}`;
  if (filtrosActivos.filtroPxq === 'con_pxq') params += `&con_pxq=true`;
  if (filtrosActivos.promo_tipos) {
    params += `&promo_tipos=${encodeURIComponent(filtrosActivos.promo_tipos)}`;
    if (filtrosActivos.promo_estado) params += `&promo_estado=${filtrosActivos.promo_estado}`;
  }
  if (filtrosActivos.con_promo_aplicada) params += `&con_promo_aplicada=true`;
  if (filtrosActivos.con_promo_sin_aplicar) params += `&con_promo_sin_aplicar=true`;
  return params;
};
